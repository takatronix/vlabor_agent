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
from .storage import ConversationStore

log = logging.getLogger(__name__)


async def _on_startup(app: web.Application) -> None:
    cfg: ChatBackendConfig = app["cfg"]
    pool = McpPool(cfg.mcp_servers)
    await pool.start()
    app["mcp_pool"] = pool
    app["store"] = ConversationStore()
    log.info("[startup] MCP servers connected: %s", pool.server_names())
    log.info("[startup] conversation store: %s", app["store"].root)


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


async def _list_conversations(request: web.Request) -> web.Response:
    store: ConversationStore = request.app["store"]
    return web.json_response(
        {"conversations": [s.to_dict() for s in store.list()]}
    )


async def _get_conversation(request: web.Request) -> web.Response:
    store: ConversationStore = request.app["store"]
    cid = request.match_info.get("cid", "")
    payload = store.load(cid)
    if payload is None:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(payload)


async def _delete_conversation(request: web.Request) -> web.Response:
    store: ConversationStore = request.app["store"]
    cid = request.match_info.get("cid", "")
    ok = store.delete(cid)
    if not ok:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"ok": True})


async def _create_conversation(request: web.Request) -> web.Response:
    store: ConversationStore = request.app["store"]
    cid = store.create()
    return web.json_response({"id": cid})


# ---------------------------------------------------------------------------
# Auto-diagnose entry point
# ---------------------------------------------------------------------------
#
# Called by vlabor_dashboard whenever a /vlabor/health component flips to
# ``critical`` (per-component cooldown applied on the dashboard side). The
# endpoint mints a fresh conversation tagged ``origin=auto``, kicks off a
# background task that runs the chat-loop with a templated prompt, and
# returns immediately so the dashboard's 1Hz health timer isn't blocked.
#
# Output is persisted to the conversation store; the dashboard's chat
# tab can poll /api/conversations to surface the new session as an alert.
# A live-tail WebSocket is intentionally out of scope for this slice —
# the conversation list refresh is enough for the operator UX, and adding
# a pubsub channel would make the storage path more complex than it is
# at this stage of the project.

_DIAGNOSE_SYSTEM_PROMPT = (
    "あなたは VLAbor の自動診断エージェントです。critical 異常検知により"
    " 自動起動されました。次の手順で日本語で回答してください:\n\n"
    "1. vlabor-diagnostics MCP の get_health_snapshot で全体状況を確認。\n"
    "2. 失敗コンポーネントごとに get_component_detail で詳細を取得。\n"
    "3. read_ros_logs(node=<該当ノード>, level_min=30) で直近のエラーログを確認。\n"
    "4. read_vlabor_events(category='device' or 'pipeline', since_sec=600)\n"
    "   で関連イベントを確認。必要に応じてカメラ画像 (vlabor-perception)\n"
    "   など他 MCP も参照可。\n"
    "5. 各失敗コンポーネントについて vlabor-visual.show_diagnostic_marker\n"
    "   を呼び、profile が visual_anchor_frame を宣言しているなら\n"
    "   その frame に severity 付きでマーカーを出す。title は短く\n"
    "   (例『D405 切断』)、detail は対策の一行 (例『USB を再接続』)。\n"
    "6. 最後に診断結論を 3 行以内でまとめる。形式は:\n"
    "     原因: ...\n"
    "     根拠: ... (どのログ / どの component の状態を見たか)\n"
    "     対策: ... (オペレーターが今できる行動)\n"
    "7. record_event(category='diagnostic', severity=<critical|warning>,\n"
    "   source=<component_id>, code=<short upper>, message=<one-line>,\n"
    "   remediation=<対策>) で診断結論を /vlabor/events に publish。\n\n"
    "禁止: 推測だけで結論しない、log/event を読まずに走らない、Live\n"
    "View マーカーを忘れない。"
)


async def _run_diagnose_session(app: web.Application, cid: str,
                                trigger: dict) -> None:
    """Background coroutine: drives one chat-loop turn for an
    auto-triggered diagnosis. Stores the transcript on completion.
    Handles errors gracefully — the dashboard already moved on after
    POSTing, so any failure here is logged, not surfaced upstream."""
    cfg: ChatBackendConfig = app["cfg"]
    pool: McpPool = app["mcp_pool"]
    store: ConversationStore = app["store"]
    api_key = read_api_key(cfg.api_key_path)
    if not api_key:
        log.warning("[diagnose] no API key at %s — skipping session %s",
                    cfg.api_key_path, cid)
        store.set_meta(cid, origin="auto", trigger=trigger,
                       title="自動診断: APIキー未設定でスキップ")
        return

    components = trigger.get("components") or []
    user_prompt_lines = ["異常検知。以下のコンポーネントが critical です:"]
    for c in components:
        line = f"- id={c.get('id')} label={c.get('label')} "
        line += f"severity={c.get('severity')} message={c.get('message')!r}"
        if c.get("visual_anchor_frame"):
            line += f" anchor={c['visual_anchor_frame']}"
        user_prompt_lines.append(line)
    user_prompt_lines.append("\n上記の手順に従って診断してください。")
    user_text = "\n".join(user_prompt_lines)

    messages: list[dict] = [
        {"role": "user", "content": [
            {"type": "text", "text": _DIAGNOSE_SYSTEM_PROMPT + "\n\n" + user_text}
        ]}
    ]
    title = "自動診断: " + ", ".join(
        str(c.get("label") or c.get("id") or "?") for c in components
    )[:60]
    store.set_meta(cid, origin="auto", trigger=trigger, title=title)

    client = AsyncAnthropic(api_key=api_key)
    try:
        from .chat_loop import run_chat
        async for _event in run_chat(
            client=client, model=cfg.anthropic_model,
            messages=messages, pool=pool,
        ):
            # Drain events: nothing live-streams them, but the chat
            # loop appends to ``messages`` only after each iteration.
            # We just keep the loop going until ``done``.
            pass
    except Exception as exc:  # pragma: no cover — surfaced to log only
        log.exception("[diagnose] session %s failed: %s", cid, exc)
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": f"(診断中にエラー: {exc})"}
        ]})
    store.save(cid, messages)
    store.set_meta(cid, origin="auto", trigger=trigger, title=title)
    log.info("[diagnose] session %s done (%d messages)", cid, len(messages))


async def _post_diagnose(request: web.Request) -> web.Response:
    """Auto-diagnose trigger from vlabor_dashboard. Body schema::

        {"trigger": "auto", "profile": "...",
         "components": [
            {"id": "d405_color", "label": "...", "severity": "critical",
             "message": "...", "remediation": "...",
             "visual_anchor_frame": "d405_link", "category": "device"}
         ]}

    Returns the freshly minted conversation id immediately; the actual
    LLM run happens in a background asyncio task.
    """
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "expected json object"}, status=400)
    components = body.get("components") or []
    if not isinstance(components, list) or not components:
        return web.json_response(
            {"error": "components[] required"}, status=400)

    store: ConversationStore = request.app["store"]
    cid = store.create()
    asyncio.get_event_loop().create_task(
        _run_diagnose_session(request.app, cid, body))
    return web.json_response(
        {"ok": True, "conversation_id": cid, "components": len(components)},
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
        # Each user turn carries the conversation_id (or none for first
        # turn — backend mints one and announces it). Persisting on
        # the server side means a tab refresh, a different browser, or
        # a different machine all see the same chat history.
        store: ConversationStore = request.app["store"]
        cid = (payload.get("conversation_id") or "").strip()
        if not cid:
            cid = store.create()
            await ws.send_json({"type": "conversation_created", "id": cid})

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
        # transcript back so the client can persist it, and write the
        # authoritative copy to disk.
        store.save(cid, messages)
        await ws.send_json({"type": "transcript", "conversation_id": cid, "messages": messages})

    return ws


def build_app(cfg: ChatBackendConfig) -> web.Application:
    app = web.Application()
    app["cfg"] = cfg
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_get("/", _index)
    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/chat", _ws_chat)
    app.router.add_get("/api/conversations", _list_conversations)
    app.router.add_post("/api/conversations", _create_conversation)
    app.router.add_get(r"/api/conversations/{cid}", _get_conversation)
    app.router.add_delete(r"/api/conversations/{cid}", _delete_conversation)
    app.router.add_post("/diagnose", _post_diagnose)
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
