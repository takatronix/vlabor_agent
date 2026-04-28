# Claude Code 指示書: vlabor_agent

Robot agent orchestration project. **Early scaffolding stage** —
expect this doc to change as the architecture solidifies.

## 設計の単一の真実

[docs/design/overview.md](docs/design/overview.md) が設計の起点。新規
作業は必ず読んでから着手する。Phase / open question もここ。

## 作業前チェック

1. `pwd` が `/home/aspa/ros2_ws/src/vlabor_agent/` 配下であること
2. 触っているのが `vlabor_ros2/` や `fluent_vision_ros2/` でない
   こと (それぞれ別 OSS — 跨る変更は分割)
3. `git status` でスナップショット

## サブパッケージの境界

| ディレクトリ | 言語 | ROS2? | 役割 |
|-------------|------|-------|------|
| `chat_backend/` | Python (FastAPI / aiohttp 想定) | No | Anthropic API + MCP tool-use loop |
| `bt_runtime/` | Python (py_trees_ros) | Yes | behavior tree executor |
| `web_ui/` | TypeScript (vite + React or Svelte) | No | chat panel + BT canvas |
| `examples/` | yaml / json | No | task tree / prompt サンプル |
| `docker/` | compose / Dockerfile | No | chat_backend + web_ui のコンテナ |

`chat_backend` ↔ `web_ui` は WebSocket、`chat_backend` ↔ `bt_runtime`
は ROS2 service / topic か WebSocket。ROS2 にどこまで載せるかは
`docs/design/overview.md` の "Open questions" を参照。

## vlabor 連携

- vlabor の中身は **直接 import しない**。
- vlabor が公開する **MCP server (vlabor-obs / 将来 vlabor-act)** を
  通じて操作する。これにより agent は機種非依存で書ける。

## License

Apache-2.0. PR / contribution は `docs/design/` 確認後で。

## 関連ドキュメント

- [`docs/design/overview.md`](docs/design/overview.md) — メイン設計
- [`~/ros2_ws/CLAUDE.md`](../../CLAUDE.md) — 上位 ros2_ws ルール
- [`~/ros2_ws/src/vlabor_ros2/CLAUDE.md`](../vlabor_ros2/CLAUDE.md) — vlabor 側 (連携先)
