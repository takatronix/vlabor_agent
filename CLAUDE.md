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

| ディレクトリ | 言語 | 役割 |
|-------------|------|------|
| `chat_backend/` | Python (FastAPI / aiohttp) | Anthropic API + MCP tool-use loop |
| `bt_runtime/` | Python (py_trees) | behavior tree executor |
| `web_ui/` | TypeScript (vite + React or Svelte) | chat panel + BT canvas |
| `examples/` | yaml / json | task tree / prompt サンプル |
| `docker/` | compose / Dockerfile | chat_backend + bt_runtime + web_ui コンテナ |

`chat_backend` ↔ `web_ui` ↔ `bt_runtime` は WebSocket / HTTP のみ。
プロセス間で ROS2 は使わない (下記参照)。

## ROS2 依存なし

**vlabor_agent は ROS2 に依存しない**。ロボットとの通信は MCP
サーバ経由のみ (今は `vlabor-obs` 1 個、将来は各ロボ案件が自分で
提供する MCP に対応)。

- `bt_runtime` は `py_trees`（**`py_trees_ros` ではない**）
- Docker base は `python:3.12-slim` / `node:20-slim`、`ros:*` ベースは使わない
- ROS2 native 機能 (TF / rosout / param) を agent から直接欲しくなったら、
  それは vlabor 側 (or 他ロボ側) の MCP に **そのドメインで意味のある
  抽象化** として足してもらう。agent 側は ROS の細部を知らない方針。

## vlabor 連携

- vlabor の中身は **直接 import しない / topic 直接購読しない**。
- vlabor が公開する **MCP server (vlabor-obs / 将来 vlabor-act)** を
  通じて操作する。これにより agent は機種非依存で書ける。

## License

Apache-2.0. PR / contribution は `docs/design/` 確認後で。

## 関連ドキュメント

- [`docs/design/overview.md`](docs/design/overview.md) — メイン設計
- [`~/ros2_ws/CLAUDE.md`](../../CLAUDE.md) — 上位 ros2_ws ルール
- [`~/ros2_ws/src/vlabor_ros2/CLAUDE.md`](../vlabor_ros2/CLAUDE.md) — vlabor 側 (連携先)
