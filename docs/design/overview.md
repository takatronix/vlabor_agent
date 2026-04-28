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
agent_orchestrator/
├── README.md
├── docs/design/         (this doc + roadmap)
├── packages/
│   ├── chat-backend/    (Anthropic API + MCP tool-use loop)
│   ├── bt-runtime/      (BT executor、ROS2 ノード)
│   ├── bt-bridge/       (LLM JSON ↔ BehaviorTree.CPP 双方向)
│   └── web-ui/          (chat + BT canvas + 操作ガイド)
├── docker/
└── examples/
    ├── piper_pickplace/ (vlabor 連携サンプル)
    └── aspa_navigate/   (将来)
```

vlabor との接点は **MCP server (vlabor-obs / 将来 vlabor-act 等)** だけ。
agent は MCP tool を叩く。それ以外 vlabor 内部は知らない。

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

## 開いてる設計問題

1. **BT 標準準拠 vs 自前**: 第一は自前 JSON、後で Groot 形式への export を提供。vs 最初から BT.CPP XML に振り切る。
2. **LLM output schema**: tool_use → BT への変換を chat-backend / bt-runtime どちら側で?
3. **長時間タスク**: BT の running をどこで保持? ROS2 service ベースか永続 DB か。
4. **Multi-robot**: 同じ runtime が複数ロボ同時 orchestrate できるべきか? (将来)
5. **オフライン LLM**: claude API 必須にすべきか、Ollama / LMStudio もサポートか?

## 次回 cold-start 時にやること

1. リポジトリ作成 (たぶん `~/ros2_ws/src/agent_orchestrator` 単独 git、後日 push)
2. Phase 0 実装 (chat-backend Hello World)
3. vlabor-obs を MCP として呼べることを確認
4. BT の最小 schema 固める (JSON schema 書き出す)

参考メモ:
- 関連 vlabor MCP 設計: profile yaml の `dashboard.mcp.examples` (`vlabor-obs`)
- 関連 daihen 設計ドキュメント: `daihen-physical-ai/docs/` 配下に同類の設計書ある
- BehaviorTree.CPP: <https://www.behaviortree.dev/>
- py_trees: <https://github.com/splintered-reality/py_trees>
- Groot: <https://github.com/BehaviorTree/Groot> (Groot1 の方は GPLv3 OSS)
