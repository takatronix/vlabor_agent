# chat_backend

Anthropic API + MCP tool-use loop for `vlabor_agent`.

## What it does (Phase 0)

- Connects to the MCP servers configured in
  `~/.vlabor/agent/config.json` (default: `vlabor-obs` at
  `http://127.0.0.1:9100/sse`).
- Exposes their tools to Claude via the Messages API.
- Runs the tool-use loop until Claude produces a final answer.
- Forwards image content from MCP `tool_result` blocks verbatim so
  Claude can do its own VLM-style reasoning over camera frames.

## Run

```bash
cd chat_backend
uv pip install -e .   # or: pip install -e .
VLABOR_AGENT_PORT=8887 vlabor-agent-chat
```

API key is read from
`~/.vlabor/profiles/<profile>/anthropic_api_key.txt` on every WS
connection so a key rotation doesn't need a restart.

## Endpoints

| Path | Kind | Notes |
|------|------|-------|
| `/healthz` | GET | Returns connected MCP servers + tool count. |
| `/chat`    | WS  | Send `{type:"user_message", text, history}`; receive a stream of `assistant_text` / `tool_use_start` / `tool_use_result` events ending in `done` (or `error`). |

## What's not here yet

- `stdio` / `http` MCP transports (only `sse` works in Phase 0).
- BT runtime — the chat backend just runs the LLM tool-use loop;
  building a behavior tree out of the dialogue happens in
  `bt_runtime/`, which doesn't exist yet.
- Token / cost telemetry — punt to Phase 2.

See `docs/design/overview.md` at the project root for the full plan.
