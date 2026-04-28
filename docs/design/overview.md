---
name: agent_orchestrator project design (BT + Chat + MCP)
description: ロボット用エージェント orchestration プロジェクトの初期設計。vlabor から分離、BT 可視化 + LLM chat + MCP tool 実行
type: project
originSessionId: d5249822-82f6-4d03-9d82-dba091d2f0d6
---
# agent_orchestrator (仮名) — 初期設計メモ

vlabor_dashboard とは別プロジェクトとして立てる。「vlabor / aspa-navigation 等のロボット案件から汎用に使える、エージェント運用 UI + 実行 runtime」。

## なぜ別プロジェクトか

- 責務分離: vlabor_dashboard = ロボット運用、agent_orchestrator = エージェント運用
- 機種非依存: so101 / piper / aspa-navigation 全部から使いたい
- ライフサイクル: 各ロボ案件と独立に進めたい
- OSS化判断が別: vlabor は社用ハード寄り、agent は汎用 OSS にしやすい

## 想定リポジトリ構成

```
vlabor_agent/
├── README.md
├── CLAUDE.md
├── docs/design/         (this doc + roadmap)
├── chat_backend/        (Python: Anthropic API + MCP tool-use loop)
├── bt_runtime/          (Python: BT executor — py_trees, NOT py_trees_ros)
├── web_ui/              (TypeScript: chat + BT canvas + 操作ガイド)
├── docker/              (python:3.12-slim / node:20-slim ベース)
└── examples/
    ├── piper_pickplace/ (vlabor 連携サンプル)
    └── aspa_navigate/   (将来)
```

vlabor との接点は **MCP server (vlabor-obs / 将来 vlabor-act 等)** だけ。
agent は MCP tool を叩く。それ以外 vlabor 内部は知らない。

## ROS2 依存を持たない判断

- bt_runtime は `py_trees`（**`py_trees_ros` ではない**）
- BT action = **MCP tool 呼び出しのみ**。ROS topic / service を直接叩かない
- Docker base は `python:3.12-slim` / `node:20-slim`、`ros:*` ベース不使用
- 機種非依存設計の核。ROS native 機能 (TF / param / rosout) が欲しい場合は
  vlabor 側 MCP に「ドメインとして意味のある抽象」として足す方針

## アーキテクチャ全体像

```
┌─────────────────────────────────────────┐
│  Web UI (port 8887)                     │
│  ┌──────────────┬───────────────────┐   │
│  │ Chat         │ BT Canvas         │   │
│  │ (LLM)        │ (Live state)      │   │
│  │              │                   │   │
│  │ [Approve]    │ Goal              │   │
│  │              │  ├─ Find cube ✓   │   │
│  │              │  ├─ Plan grasp ●  │   │
│  │              │  └─ Pick    ⏸    │   │
│  └──────────────┴───────────────────┘   │
└──────┬───────────────────────┬──────────┘
       │ WebSocket             │ WebSocket
   ┌───▼────────────┐    ┌─────▼──────────┐
   │ chat-backend   │    │ bt-runtime     │
   │ (Python)       │◄──►│ (ROS2 node,    │
   │ Claude API +   │ BT │  py_trees_ros  │
   │ MCP tool-use   │ⓘ  │  or BT.CPP)    │
   │                │    │                │
   └───┬────────────┘    └─────┬──────────┘
       │ MCP                    │ ROS topics / actions
       ▼                        ▼
   vlabor-obs (port 9100)    vlabor stack
   future: vlabor-act        (piper_ctrl / MoveIt / mux)
```

## 主要技術選定 (現時点)

| 領域 | 候補 | 状況 |
|---|---|---|
| Chat UI base | **LibreChat** か自作 | LibreChat = AGPL3、Anthropic+MCP 標準、agent loop あり |
| BT engine | **py_trees_ros** か **BehaviorTree.CPP** | py_trees は Python で速く回せる / BT.CPP は Nav2/MoveIt と同型 |
| BT 可視化 | **Groot1 (OSS)** に乗る or 自作 (three.js) | Groot1 は BT.CPP 形式専用、自作は柔軟だが工数 |
| LLM 出力形式 | JSON tree (我々の schema) → BT に変換 | LLM に直接 BT.CPP XML 吐かせるのは険しい |
| MCP client | TypeScript SDK (`@modelcontextprotocol/sdk`) or Python `mcp` | chat-backend の言語次第 |

**第一候補組合せ (推奨):**
- chat-backend: **Python (FastAPI / aiohttp)** + Anthropic SDK + `mcp` Python SDK
- bt-runtime: **py_trees_ros** (Python で chat-backend と同言語)
- BT 形式: 自前 JSON schema を採用、Groot1 形式への export はオプション
- web-ui: **react/svelte 自作** (LibreChat は機能多すぎ、embed しにくい)

## コア仕様

### LLM の役割

- 自然言語の goal を **JSON task tree** に変換
- 例: `"cube を黒トレイに"` →
  ```json
  {"type":"sequence","children":[
    {"type":"action","name":"find_object","args":{"label":"cube"}},
    {"type":"action","name":"plan_grasp","args":{}},
    {"type":"approval_gate","reason":"physical motion"},
    {"type":"action","name":"execute_grasp","args":{}},
    {"type":"action","name":"move_to","args":{"target":"black_tray"}}
  ]}
  ```
- bt-runtime がこの JSON を実行

### bt-runtime の役割

- JSON tree を py_trees の BT に組み立てて tick
- 各 action node = MCP tool 呼び出し or ROS2 action / service
- approval_gate node = WebSocket で UI に approval リクエスト送って待つ
- 実行状態 (RUNNING/SUCCESS/FAILURE) を WS で UI にストリーム

### web-ui の役割

- Chat panel: 普通の LLM chat、tool_use を可視化
- BT canvas: 現在実行中の tree をリアルタイム描画 (running ノード光る、成功緑、失敗赤)
- Approval UI: 危険動作前にオペレータ承認
- 過去セッション再生 (replay)

## MVP スコープ (1 週間想定)

Phase 0 — 基盤:
- chat-backend (Anthropic + MCP tool 1 個動く、テキストのみ)
- web-ui の chat だけ

Phase 1 — BT 可視化:
- LLM → JSON tree 出力
- bt-runtime が tree を tick (ダミー action から)
- web-ui に BT canvas 追加、live 状態反映

Phase 2 — 実 vlabor 連携:
- vlabor-obs (read-only) を MCP として組み込み
- approval_gate 実装
- Pi05 推論 trigger も BT action 化

Phase 3 — 拡張:
- 画像 in tool_result
- Multi-agent (planner / critic / executor)
- セッション保存 / 再生
- Groot1 export

## 長時間タスクの扱い

ロボットの pick-place は数十秒〜数分、片付け mission は十数分かかる。
chat-backend / bt-runtime / web-ui どこが落ちても tree が消えないよう
段階的に堅牢化する。

### MVP (Phase 0〜1)

- bt_runtime は **単一プロセス・in-memory**
- Tree state を **300ms 周期で `~/.vlabor/agent/tasks/<task_id>.json` に snapshot**
  (RUNNING ノード・完了済 child・最後の tool_result など)
- web-ui の WebSocket 切断 ≠ task 中断。clientは re-connect で snapshot から復元
- bt_runtime 自体が落ちた場合、再起動時に「未完了の task が N 個ある」と
  list 表示 → operator に **手動で resume / abandon** 選ばせる (auto-resume は安全上やらない)

### 長時間 MCP tool (例: MoveIt plan, 推論実行)

MCP のツール呼び出しはデフォルトで同期。長いと WS タイムアウトに当たるので、
**「kick off + poll」パターン**を BT level で標準化する:

```
sequence:
  - tool_call: vlabor_act/start_task   → returns task_id
  - poll_until: vlabor_act/get_task_status(task_id) status=done
  - tool_call: vlabor_act/get_task_result(task_id)
```

`poll_until` は専用の BT decorator として実装、tick ごとに status を見る。
chat_backend は MCP server に kick-off だけ送って即 return、poll は
bt_runtime が回す → web-ui には status 進捗をストリーム。

### Phase 2+ で検討

- snapshot を SQLite に変更 (履歴保管 + replay 用)
- 1 task = 1 subprocess に分離 (crash 隔離) — ただし Docker / process 数が膨らむので様子見
- 外部 task queue (Celery / Dramatiq) 導入: multi-robot / 複数 operator 同時運用が必要になったら

### 中断・キャンセル

- web-ui の "Stop" → bt_runtime に `cancel(task_id)` → 走行中の MCP tool に
  cancel hint を伝播 + 後続 tick で running ノードを `INTERRUPTED` 状態に
- Cancel hint は MCP server 側で **意味のある単位** で実装する責務 (vlabor 側で
  軌道生成中なら破棄、軌道追従中なら「停止コマンドを送る」など)
- agent はそのセマンティクスに踏み込まない

## 開いてる設計問題

1. **BT 標準準拠 vs 自前**: 第一は自前 JSON、後で Groot 形式への export を提供。vs 最初から BT.CPP XML に振り切る。
2. **LLM output schema**: tool_use → BT への変換を chat-backend / bt-runtime どちら側で?
3. **Multi-robot**: 同じ runtime が複数ロボ同時 orchestrate できるべきか? (将来)
4. **オフライン LLM**: claude API 必須にすべきか、Ollama / LMStudio もサポートか?
5. **snapshot の SQLite 化タイミング**: file ベースで運用始めて、replay / 履歴 UI が
   要求として固まってから switch。

## 次回 cold-start 時にやること

1. ✓ リポジトリ作成 (`~/ros2_ws/src/vlabor_agent` + GitHub `takatronix/vlabor_agent`)
2. Phase 0 実装 (chat_backend Hello World — Anthropic API でテキスト往復のみ)
3. vlabor-obs を MCP として呼べることを確認 (chat の tool_use ループ)
4. BT の最小 schema 固める (JSON schema 書き出す + サンプル tree 1 つ)
5. snapshot ファイルパスと format を docs に確定

参考メモ:
- 関連 vlabor MCP 設計: profile yaml の `dashboard.mcp.examples` (`vlabor-obs`)
- 関連 daihen 設計ドキュメント: `daihen-physical-ai/docs/` 配下に同類の設計書ある
- BehaviorTree.CPP: <https://www.behaviortree.dev/>
- py_trees: <https://github.com/splintered-reality/py_trees>
- Groot: <https://github.com/BehaviorTree/Groot> (Groot1 の方は GPLv3 OSS)
