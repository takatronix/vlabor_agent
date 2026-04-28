"""Entry point for the chat backend.

Two HTTP endpoints:

  * ``GET /healthz`` — liveness probe.
  * ``WS  /chat`` — bidirectional chat. Client sends one JSON message
    per user turn; backend streams events (``assistant_text`` /
    ``tool_use_start`` / ``tool_use_result`` / ``done`` / ``error``)
    until the loop yields ``done`` or ``error``.

WS message shape from client:
  ``{"type": "user_message", "text": "...", "history": [..]}``

``history`` is the running conversation (Anthropic ``messages``
shape). The backend treats the client as the source of truth so a
disconnect / refresh doesn't lose state — the new connection just
sends history again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from aiohttp import WSMsgType, web
from anthropic import AsyncAnthropic

from .chat_loop import run_chat
from .config import ChatBackendConfig, read_api_key
from .devpage import DEV_HTML
from .mcp_pool import McpPool

log = logging.getLogger(__name__)


async def _on_startup(app: web.Application) -> None:
    cfg: ChatBackendConfig = app["cfg"]
    pool = McpPool(cfg.mcp_servers)
    await pool.start()
    app["mcp_pool"] = pool
    log.info("[startup] MCP servers connected: %s", pool.server_names())


async def _on_cleanup(app: web.Application) -> None:
    pool: McpPool | None = app.get("mcp_pool")
    if pool is not None:
        await pool.aclose()


async def _index(request: web.Request) -> web.Response:
    # Phase 0 dev page — replace with web_ui once that ships.
    return web.Response(text=DEV_HTML, content_type="text/html")


async def _healthz(request: web.Request) -> web.Response:
    pool: McpPool = request.app["mcp_pool"]
    return web.json_response(
        {
            "ok": True,
            "mcp_servers": pool.server_names(),
            "tool_count": len(pool.tools_for_anthropic()),
        }
    )


async def _ws_chat(request: web.Request) -> web.WebSocketResponse:
    cfg: ChatBackendConfig = request.app["cfg"]
    pool: McpPool = request.app["mcp_pool"]

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    # Don't close the connection on missing API key — that triggers a
    # reconnect storm in any auto-reconnecting client. Just keep the
    # socket open and reject individual messages until the operator
    # drops a key in place.

    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "message": "invalid json"})
            continue
        if payload.get("type") != "user_message":
            await ws.send_json(
                {"type": "error", "message": f"unsupported type {payload.get('type')}"}
            )
            continue

        # Re-read the key on every turn so a fresh save shows up
        # without dropping the WS.
        api_key = read_api_key(cfg.api_key_path)
        if not api_key:
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"no API key at {cfg.api_key_path} — save one and try again",
                }
            )
            await ws.send_json({"type": "done", "stop_reason": "no_api_key"})
            continue

        text = (payload.get("text") or "").strip()
        if not text:
            await ws.send_json({"type": "error", "message": "empty text"})
            continue
        history = payload.get("history") or []
        if not isinstance(history, list):
            history = []

        messages = list(history)
        messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

        client = AsyncAnthropic(api_key=api_key)
        async for event in run_chat(
            client=client,
            model=cfg.anthropic_model,
            messages=messages,
            pool=pool,
        ):
            await ws.send_json(event)
        # The chat loop mutates ``messages`` in place; echo the final
        # transcript back so the client can persist it.
        await ws.send_json({"type": "transcript", "messages": messages})

    return ws


def build_app(cfg: ChatBackendConfig) -> web.Application:
    app = web.Application()
    app["cfg"] = cfg
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/", _index)
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/chat", _ws_chat)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    cfg = ChatBackendConfig.load()
    log.info(
        "[boot] vlabor_agent chat_backend host=%s port=%d model=%s",
        cfg.host, cfg.port, cfg.anthropic_model,
    )
    app = build_app(cfg)
    try:
        web.run_app(app, host=cfg.host, port=cfg.port)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
