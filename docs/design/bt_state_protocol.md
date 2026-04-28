# BT State Protocol — bt_runtime ↔ web_ui ↔ external viewers

Single JSON contract for "what is the behavior tree doing right
now?". `bt_runtime` (py_trees executor, Python) is the producer.
Consumers: `web_ui` (primary BT canvas) and any external viewer
(vlabor_dashboard's BT View overlay iframes web_ui rather than
hitting this directly, but operators / debug tools may consume the
raw JSON.)

## Transport

`bt_runtime` exposes two endpoints on its HTTP/WebSocket server:

| URL | Method | Behaviour |
|---|---|---|
| `/bt`        | GET | Return the latest snapshot (one JSON object). For polling clients. |
| `/bt/stream` | WebSocket | Push every snapshot as it changes (one JSON message per tick or per state-change, server-decides). |

Default port: `8889` (separate from chat_backend's 8888 so the two
processes can be restarted independently). Override with env
`BT_RUNTIME_PORT`.

## Snapshot schema

```json
{
  "schema_version": 1,
  "tick": 1234,
  "ts": 1729891234.567,
  "tree_name": "PickGreenCube",
  "root": <Node>
}
```

`Node` is recursive:

```json
{
  "id": "n0",
  "name": "PickAndPlace",
  "type": "Sequence",          // py_trees class name (Sequence | Selector | Parallel | Action | Condition | Decorator | …)
  "status": "RUNNING",          // RUNNING | SUCCESS | FAILURE | INVALID
  "tip": false,                 // true = currently-active leaf this tick
  "feedback": "",               // py_trees feedback_message (short)
  "blackboard_reads": [         // optional — keys this node read this tick
    {"key": "target.cube_id", "value": "22"}
  ],
  "blackboard_writes": [        // optional
    {"key": "plan.id", "value": "p_abc123"}
  ],
  "children": [<Node>, ...]     // empty for leaves
}
```

### Status colour mapping (recommended for renderers)

| status | color | meaning |
|---|---|---|
| RUNNING | yellow `#ffd166` | currently ticking |
| SUCCESS | green `#3fbf60` | last tick returned SUCCESS |
| FAILURE | red `#ef5350` | last tick returned FAILURE |
| INVALID | grey `#666` | not yet ticked / reset |

`tip=true` highlights the leaf py_trees would attribute the current
status to (= the deepest active leaf in the active branch). Useful
for "which step are we on?" UX.

## Producer guarantees (`bt_runtime` side)

- `tick` is monotonically increasing across the lifetime of one
  `bt_runtime` process. Reset only on process restart.
- `ts` is `time.time()` floating seconds.
- Snapshot is generated AFTER each tick's `propagate` returns. A WS
  client that subscribed mid-execution sees only post-tick states.
- Rate limit: WS push at most 30 Hz. If the BT ticks faster, the
  producer coalesces — clients always see the latest.
- Schema migrations: bump `schema_version` on breaking changes,
  keep at least one prior version reachable via `/bt?v=<n>` for one
  release.

## Consumer responsibilities (`web_ui` / dashboard / debug clients)

- Treat `id` as the only stable key across snapshots. `name` may
  change if the operator edits the tree; `id` doesn't.
- Cache the previous snapshot; only redraw nodes whose `(status,
  tip, feedback, blackboard_*)` changed. Avoid full DOM rebuilds
  on every push.
- Render even unchanged subtrees so structural edits become visible
  on the next snapshot without operator-side state.

## Why not py_trees' built-in display?

`py_trees.display.dot_tree()` outputs DOT text — fine for
post-mortem PDFs, but rendering DOT live in a browser is heavy and
loses status colours. JSON + a small custom renderer (vis.js / d3 /
hand-rolled SVG) is lighter and lets us inline blackboard data,
status badges, and the operator-friendly `tip` highlight.

## Compatibility note for the dashboard's BT View overlay

The dashboard iframes `web_ui`'s BT page (default
`http://<host>:8887/bt`). It does NOT call `/bt` JSON directly — the
data binding is `bt_runtime ⇄ web_ui` only. If you want a JSON
viewer separately, add a route inside `web_ui` (e.g. `/bt/raw`).

This keeps the dashboard agnostic of the BT format: any `web_ui`
that serves a BT page on the configured URL works.
