"""Entry point for the chat backend.

Endpoints:

  GET  /                    embedded dev page (devpage.DEV_HTML)
  GET  /healthz             liveness probe
  GET  /api/conversations   conversation list
  POST /api/conversations   create empty conversation, returns id
  GET  /api/conversations/{cid}    full transcript
  DELETE /api/conversations/{cid}  remove from disk
  GET  /api/keys/status     which providers have a key on disk
  POST /api/keys            write {provider, value} to disk (chmod 0600)
  GET  /api/settings        operator preferences (provider / voice)
  PUT  /api/settings        partial-merge into preferences
  POST /api/stt             multipart audio → text via Whisper
  POST /api/tts             {text, voice?, speed?} → audio/mpeg bytes
  POST /api/announce        broadcast voice_announce WS event
  POST /diagnose            auto-diagnose trigger from vlabor_dashboard
  WS   /chat                bidirectional chat (text + voice metadata)

WS chat client message shape:
  ``{"type": "user_message", "text": "...", "history": [..],
     "metadata": {"input_mode": "voice" | "text"}}``

WS chat server pushes (per turn):
  assistant_text_delta / assistant_text / tool_use_start /
  tool_use_result / done / error / transcript

Out-of-band server pushes (any time, broadcast to every chat WS):
  ``{"type": "voice_announce", "text": "...", "severity": "...",
     "source": "...", "ts": <unix>}``
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any

from aiohttp import WSMsgType, web

from .chat_loop import run_chat
from .config import ChatBackendConfig
from .devpage import DEV_HTML
from . import keys as keys_mod
from .mcp_pool import McpPool
from .storage import ConversationStore
from . import user_settings
from . import voice as voice_mod

log = logging.getLogger(__name__)


async def _on_startup(app: web.Application) -> None:
    cfg: ChatBackendConfig = app["cfg"]
    pool = McpPool(cfg.mcp_servers)
    await pool.start()
    app["mcp_pool"] = pool
    app["store"] = ConversationStore()
    # Live set of /chat WS clients — used for voice_announce fan-out.
    # Updated from inside the WS handler.
    app["ws_clients"] = set()
    log.info("[startup] MCP config source: %s", cfg.mcp_config_source)
    log.info("[startup] MCP servers connected: %s", pool.server_names())
    log.info("[startup] conversation store: %s", app["store"].root)
    log.info("[startup] profile_dir: %s", cfg.profile_dir)


async def _on_cleanup(app: web.Application) -> None:
    pool: McpPool | None = app.get("mcp_pool")
    if pool is not None:
        await pool.aclose()


# ---------------------------------------------------------------------------
# Static / status
# ---------------------------------------------------------------------------

async def _index(request: web.Request) -> web.Response:
    return web.Response(text=DEV_HTML, content_type="text/html")


async def _healthz(request: web.Request) -> web.Response:
    cfg: ChatBackendConfig = request.app["cfg"]
    pool: McpPool = request.app["mcp_pool"]
    return web.json_response(
        {
            "ok": True,
            "mcp_config_source": cfg.mcp_config_source,
            "mcp_servers": pool.server_names(),
            "tool_count": len(pool.tools_for_anthropic()),
        }
    )


async def _get_mcp_status(request: web.Request) -> web.Response:
    """Per-server view of the MCP pool — connection state, configured
    URL, and the tool catalogue. Drives the right-pane MCP status
    panel in devpage.py."""
    cfg: ChatBackendConfig = request.app["cfg"]
    pool: McpPool = request.app["mcp_pool"]
    return web.json_response({
        "ok": True,
        "mcp_config_source": cfg.mcp_config_source,
        "servers": pool.mcp_status(),
    })


async def _post_mcp_reload(request: web.Request) -> web.Response:
    """Wake any disconnected MCP supervisor so it retries immediately
    instead of waiting out its backoff. Useful when the operator has
    just brought up an MCP server that was missing at agent startup."""
    pool: McpPool = request.app["mcp_pool"]
    woken = await pool.reload()
    return web.json_response({
        "ok": True,
        "woken": woken,
        "servers": pool.mcp_status(),
    })


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

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
# Keys + Settings
# ---------------------------------------------------------------------------

async def _get_keys_status(request: web.Request) -> web.Response:
    cfg: ChatBackendConfig = request.app["cfg"]
    return web.json_response({
        "ok": True,
        "profile_dir": cfg.profile_dir,
        "keys": keys_mod.status(cfg.profile_dir),
    })


async def _post_keys(request: web.Request) -> web.Response:
    """Body: ``{"provider": "anthropic"|"openai", "value": "<key>"}``.
    Writes the file and chmods 0600. Empty value deletes the file."""
    cfg: ChatBackendConfig = request.app["cfg"]
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400)
    provider = (body.get("provider") or "").strip()
    if provider not in keys_mod.KNOWN_PROVIDERS:
        return web.json_response(
            {"error": f"unknown provider: {provider!r}"}, status=400)
    value = (body.get("value") or "").strip()
    if not value:
        keys_mod.delete_key(cfg.profile_dir, provider)
        return web.json_response({"ok": True, "deleted": True,
                                  "provider": provider})
    path = keys_mod.write_key(cfg.profile_dir, provider, value)
    return web.json_response({
        "ok": True, "provider": provider, "path": str(path),
    })


async def _get_settings(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "settings": user_settings.load()})


async def _put_settings(request: web.Request) -> web.Response:
    """Partial-merge body into operator settings."""
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "expected json object"}, status=400)
    merged = user_settings.patch(body)
    return web.json_response({"ok": True, "settings": merged})


# ---------------------------------------------------------------------------
# STT / TTS / Announce
# ---------------------------------------------------------------------------

async def _post_stt(request: web.Request) -> web.Response:
    cfg: ChatBackendConfig = request.app["cfg"]
    api_key = cfg.openai_key()
    if not api_key:
        return web.json_response(
            {"ok": False, "error": "OpenAI API key not set"}, status=400)
    try:
        reader = await request.multipart()
    except Exception as exc:
        return web.json_response(
            {"ok": False, "error": f"multipart parse: {exc}"}, status=400)
    audio_bytes = b""
    filename = "speech.webm"
    lang = (request.query.get("lang") or "ja").strip()
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "audio":
            audio_bytes = await part.read(decode=False)
            filename = part.filename or filename
        elif part.name == "lang":
            txt = await part.text()
            if txt:
                lang = txt.strip()
    if not audio_bytes:
        return web.json_response(
            {"ok": False, "error": "no audio in request"}, status=400)
    settings = user_settings.load()
    lang = lang or settings.get("voice", {}).get("stt_lang", "ja")
    try:
        text = await voice_mod.whisper_stt(
            api_key=api_key, audio_bytes=audio_bytes,
            filename=filename, lang=lang,
        )
    except voice_mod.VoiceError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    return web.json_response({
        "ok": True, "text": text, "language": lang,
        "size_bytes": len(audio_bytes),
    })


async def _post_tts(request: web.Request) -> web.StreamResponse:
    """Body: ``{text, voice?, speed?}``. Returns audio/mpeg bytes."""
    cfg: ChatBackendConfig = request.app["cfg"]
    api_key = cfg.openai_key()
    if not api_key:
        return web.json_response(
            {"ok": False, "error": "OpenAI API key not set"}, status=400)
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400)
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "empty text"}, status=400)
    settings = user_settings.load().get("voice", {})
    voice = body.get("voice") or settings.get("tts_voice", "alloy")
    try:
        speed = float(body.get("speed") or settings.get("tts_speed", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    model = body.get("model") or settings.get("tts_model", "tts-1")
    try:
        audio = await voice_mod.openai_tts(
            api_key=api_key, text=text, voice=voice,
            speed=speed, model=model, fmt="mp3",
        )
    except voice_mod.VoiceError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    return web.Response(body=audio, content_type="audio/mpeg")


async def _broadcast_voice_announce(app: web.Application, *,
                                    text: str, severity: str,
                                    source: str) -> int:
    """Push a ``voice_announce`` event to every connected /chat WS.
    Returns the number of clients that received the message."""
    msg = {
        "type": "voice_announce",
        "text": text,
        "severity": severity,
        "source": source,
        "ts": time.time(),
    }
    clients = list(app.get("ws_clients") or [])
    sent = 0
    for ws in clients:
        if ws.closed:
            continue
        try:
            await ws.send_json(msg)
            sent += 1
        except Exception as exc:  # pragma: no cover
            log.debug("voice_announce push failed: %s", exc)
    return sent


async def _post_announce(request: web.Request) -> web.Response:
    """Body: ``{text, severity?, source?, voice?, speed?}``.
    Fans the message out to every browser; each browser checks the
    severity threshold + dedupe before actually playing TTS."""
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400)
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "empty text"}, status=400)
    severity = (body.get("severity") or "info").strip().lower()
    source = (body.get("source") or "manual").strip()
    sent = await _broadcast_voice_announce(
        request.app, text=text, severity=severity, source=source)
    log.info("[announce] severity=%s source=%s sent=%d text=%r",
             severity, source, sent, text[:80])
    return web.json_response({
        "ok": True, "delivered_to": sent,
        "severity": severity, "source": source,
    })


# ---------------------------------------------------------------------------
# Auto-diagnose entry point
# ---------------------------------------------------------------------------

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


def _final_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Pull the most recent assistant message's text content out for
    the diagnose voice announcement. Tool_use blocks are skipped."""
    for m in reversed(messages):
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                b.get("text") or "" for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


async def _run_diagnose_session(app: web.Application, cid: str,
                                trigger: dict) -> None:
    """Background coroutine: drives one chat-loop turn for an
    auto-triggered diagnosis. Stores transcript + announces voice if
    settings allow."""
    cfg: ChatBackendConfig = app["cfg"]
    pool: McpPool = app["mcp_pool"]
    store: ConversationStore = app["store"]
    settings = user_settings.load()
    chat_settings = settings.get("chat", {})
    provider_name = chat_settings.get("provider") or "anthropic"
    model = chat_settings.get("model") or ""

    if provider_name == "openai":
        api_key = cfg.openai_key()
    else:
        api_key = cfg.anthropic_key()
    if not api_key:
        log.warning("[diagnose] no %s key — skipping session %s",
                    provider_name, cid)
        store.set_meta(cid, origin="auto", trigger=trigger,
                       provider=provider_name,
                       title=f"自動診断: {provider_name} APIキー未設定でスキップ")
        return

    components = trigger.get("components") or []
    user_prompt_lines = ["異常検知。以下のコンポーネントが critical です:"]
    severities: list[str] = []
    for c in components:
        line = f"- id={c.get('id')} label={c.get('label')} "
        line += f"severity={c.get('severity')} message={c.get('message')!r}"
        if c.get("visual_anchor_frame"):
            line += f" anchor={c['visual_anchor_frame']}"
        user_prompt_lines.append(line)
        if c.get("severity"):
            severities.append(str(c["severity"]))
    user_prompt_lines.append("\n上記の手順に従って診断してください。")
    user_text = "\n".join(user_prompt_lines)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [
            {"type": "text", "text": _DIAGNOSE_SYSTEM_PROMPT + "\n\n" + user_text}
        ]}
    ]
    title = "自動診断: " + ", ".join(
        str(c.get("label") or c.get("id") or "?") for c in components
    )[:60]
    store.set_meta(cid, origin="auto", trigger=trigger,
                   provider=provider_name, title=title)

    try:
        async for _event in run_chat(
            model=model, messages=messages, pool=pool,
            provider=provider_name, api_key=api_key,
        ):
            # Drain events: nothing live-streams them — we just keep the
            # loop going until it yields ``done`` or ``error``.
            pass
    except Exception as exc:  # pragma: no cover — surfaced to log only
        log.exception("[diagnose] session %s failed: %s", cid, exc)
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": f"(診断中にエラー: {exc})"}
        ]})
    store.save(cid, messages)
    store.set_meta(cid, origin="auto", trigger=trigger,
                   provider=provider_name, title=title)
    log.info("[diagnose] session %s done (%d messages, provider=%s)",
             cid, len(messages), provider_name)

    # Voice announce the conclusion (if enabled). Re-load the settings
    # right before checking so the operator can toggle voice off
    # mid-session via the Settings modal and stop the announcement
    # at the door, without having to restart the agent.
    voice_settings = user_settings.load().get("voice", {})
    if voice_settings.get("notify_diagnose"):
        text = _final_assistant_text(messages)
        if text:
            # Pick the worst severity in the trigger as the announce
            # severity so notify_severity_min thresholding works as
            # expected on the browser side.
            sev = "critical" if "critical" in severities else (
                  "warning" if "warning" in severities else "info")
            await _broadcast_voice_announce(
                app, text=text, severity=sev,
                source=f"auto-diagnose-{cid}",
            )


async def _post_diagnose(request: web.Request) -> web.Response:
    """Auto-diagnose trigger from vlabor_dashboard."""
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


# ---------------------------------------------------------------------------
# Chat WebSocket
# ---------------------------------------------------------------------------

async def _ws_chat(request: web.Request) -> web.WebSocketResponse:
    cfg: ChatBackendConfig = request.app["cfg"]
    pool: McpPool = request.app["mcp_pool"]

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    request.app.setdefault("ws_clients", set()).add(ws)

    try:
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
                    {"type": "error",
                     "message": f"unsupported type {payload.get('type')}"}
                )
                continue

            settings = user_settings.load()
            chat_settings = settings.get("chat", {})
            provider_name = chat_settings.get("provider") or "anthropic"
            model = chat_settings.get("model") or ""
            if provider_name == "openai":
                api_key = cfg.openai_key()
            else:
                api_key = cfg.anthropic_key()
            if not api_key:
                await ws.send_json({
                    "type": "error",
                    "message": (f"no {provider_name} API key set — "
                                f"open Settings and save one"),
                })
                await ws.send_json({"type": "done", "stop_reason": "no_api_key"})
                continue

            text = (payload.get("text") or "").strip()
            if not text:
                await ws.send_json({"type": "error", "message": "empty text"})
                continue
            history = payload.get("history") or []
            if not isinstance(history, list):
                history = []
            metadata = payload.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            input_mode = (metadata.get("input_mode") or "text").lower()

            store: ConversationStore = request.app["store"]
            cid = (payload.get("conversation_id") or "").strip()
            if not cid:
                cid = store.create()
                await ws.send_json({"type": "conversation_created", "id": cid})

            messages = list(history)
            messages.append(
                {"role": "user", "content": [{"type": "text", "text": text}]})

            async for event in run_chat(
                model=model, messages=messages, pool=pool,
                provider=provider_name, api_key=api_key,
            ):
                await ws.send_json(event)
            store.save(cid, messages)
            store.set_meta(cid, provider=provider_name,
                           last_input_mode=input_mode)
            await ws.send_json({
                "type": "transcript",
                "conversation_id": cid,
                "messages": messages,
            })
    finally:
        clients = request.app.get("ws_clients")
        if clients is not None:
            clients.discard(ws)

    return ws


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

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
    app.router.add_get("/api/keys/status", _get_keys_status)
    app.router.add_post("/api/keys", _post_keys)
    app.router.add_get("/api/mcp/status", _get_mcp_status)
    app.router.add_post("/api/mcp/reload", _post_mcp_reload)
    app.router.add_get("/api/settings", _get_settings)
    app.router.add_put("/api/settings", _put_settings)
    app.router.add_post("/api/stt", _post_stt)
    app.router.add_post("/api/tts", _post_tts)
    app.router.add_post("/api/announce", _post_announce)
    app.router.add_post("/diagnose", _post_diagnose)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    cfg = ChatBackendConfig.load()
    log.info(
        "[boot] vlabor_agent chat_backend host=%s port=%d profile_dir=%s",
        cfg.host, cfg.port, cfg.profile_dir,
    )
    app = build_app(cfg)
    try:
        web.run_app(app, host=cfg.host, port=cfg.port)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
