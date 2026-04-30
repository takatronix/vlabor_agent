# Voice chat + multi-provider + announce API

This is the v1.0 design + reference for vlabor_agent's voice mode and
the OpenAI provider. The companion plan lives at
[`/home/aspa/.claude/plans/...`](../../) (session-local) — this file
is the long-lived OSS doc.

## What v1.0 ships

1. **設定モーダル** (⚙️) で API キー登録 (Anthropic + OpenAI)、provider
   / model、音声設定をブラウザから編集
2. **マルチ provider chat-loop**: Anthropic か OpenAI を任意で選択
3. **音声会話モード** (🎤): 連続リッスン → VAD → Whisper STT → chat →
   `input_mode='voice'` のターンだけ自動 TTS で読み上げ
4. **`POST /api/announce`** + `voice_announce` WS broadcast: 任意
   サブシステムから browser に音声通知できる汎用 API
5. **Auto-diagnose 音声化**: 既存の `/diagnose` 完了時、settings に
   従って結論を全 browser に音声配信

half-duplex 固定 (barge-in は trigger-only スイッチで残してあるが TTS
streaming は v1.1 で導入予定)。

## エンドポイント

| Method | Path | 用途 |
|---|---|---|
| GET  | `/api/keys/status` | provider ごとに `{is_set: bool}` |
| POST | `/api/keys` | `{provider, value}` を 0o600 で保存。空 value = 削除 |
| GET  | `/api/settings` | `~/.vlabor/agent/settings.json` 読み込み |
| PUT  | `/api/settings` | partial-merge して保存 |
| POST | `/api/stt` | `multipart/form-data: audio` → Whisper → `{ok, text}` |
| POST | `/api/tts` | `{text, voice?, speed?, model?}` → `audio/mpeg` |
| POST | `/api/announce` | `{text, severity?, source?}` → `voice_announce` を全 chat WS に fan-out |
| POST | `/diagnose` | (既存) auto-diagnose、settings.notify_diagnose で音声通知 |
| WS   | `/chat` | (既存) `metadata.input_mode` に対応 |

WS から流れる新イベント:

```json
{"type":"voice_announce","text":"...","severity":"critical",
 "source":"auto-diagnose-<cid>","ts":1714370543.2}
```

browser 側は `notify_enabled` + `notify_severity_min` + 60 秒 dedupe
を踏んでから TTS を再生。

## 設定の保管場所

| 種類 | パス |
|---|---|
| Anthropic key | `~/.vlabor/profiles/<profile>/anthropic_api_key.txt` |
| OpenAI key | `~/.vlabor/profiles/<profile>/openai_api_key.txt` |
| 操作者設定 | `~/.vlabor/agent/settings.json` |

`settings.json` 構造 (defaults は
[`chat_backend/chat_backend/user_settings.py`](../../chat_backend/chat_backend/user_settings.py:33) の
`DEFAULTS` を参照):

```json
{
  "chat": {"provider": "anthropic", "model": ""},
  "voice": {
    "stt_engine": "openai_whisper",
    "stt_lang": "ja",
    "tts_voice": "alloy",
    "tts_speed": 1.0,
    "tts_model": "tts-1",
    "silence_ms": 800,
    "energy_db": -45,
    "barge_in": false,
    "notify_enabled": true,
    "notify_severity_min": "critical",
    "notify_diagnose": true,
    "notify_dedupe_window_sec": 60
  }
}
```

`model` が空文字なら provider のデフォルト
(`claude-sonnet-4-6` / `gpt-4o-mini`) にフォールバック。

## Provider 抽象化

[`providers/base.py`](../../chat_backend/chat_backend/providers/base.py)
の `ChatProvider` Protocol が共通インターフェース。

- [`anthropic_provider.py`](../../chat_backend/chat_backend/providers/anthropic_provider.py):
  既存 `messages.stream` フローを移植
- [`openai_provider.py`](../../chat_backend/chat_backend/providers/openai_provider.py):
  Chat Completions の function-calling を Anthropic 形式の `tool_use`
  / `tool_result` ブロックに変換

`chat_loop.run_chat(provider=..., api_key=...)` が dispatch。MCP プールの
ツール spec は `tools_for_anthropic()` / `tools_for_openai()` で両形式を
生成する。

注意:
- OpenAI provider は **画像入力 (Anthropic image block) を未対応**。
  現状 MCP からカメラ画像が返って来ると text に落とす。GPT-4o の
  vision 入力対応は v1.1 で。
- OpenAI の `finish_reason` を Anthropic 表現 (`tool_use` / `end_turn` /
  `max_tokens`) に正規化しているので、既存 chat_loop の終了条件は
  そのまま動く。

## Voice mode 詳細

ヘッダの `🎤` ボタンで ON/OFF。ON で `getUserMedia` を要求し続ける
mic 常時開放モード。

ステート遷移 (browser 側):

```
IDLE → (energy > threshold)
  → RECORDING → (silence_ms 経過)
    → STT_BUSY → (Whisper 完了)
      → CHATTING → ('done' イベント)
        → if last user_mode == 'voice': TTS_BUSY → (audio.ended)
        → else: IDLE
        → IDLE
```

### VAD

Web Audio API の `AnalyserNode` から FFT を取り、RMS の dB を 1
フレームごとに評価。`energy_db > threshold` で発話開始、
`silence_ms` 連続で無音とみなして finalize → `/api/stt`。

最低発話長 (250ms 未満) はドロップ — 咳・物音の誤動作を防ぐ。

### barge-in (任意)

`settings.voice.barge_in === true` のとき、TTS 再生中も VAD が走り、
発話検知で `audio.pause()` → 即座に新 RECORDING へ。デフォルト OFF。

## auto-diagnose の音声化

dashboard が critical 検出で `POST /diagnose` するフローは既存。
chat_loop 完了後、`_run_diagnose_session` の最後に
`settings.voice.notify_diagnose === true` なら `_broadcast_voice_announce`
が呼ばれて全 chat WS に `voice_announce` を流す。

severity は trigger 内コンポーネントの最も重いものを使う。各 browser
は `notify_severity_min` フィルタと dedupe を経て TTS 再生。

## 検証 (E2E)

### 設定 UI

1. `http://localhost:8887/` を開く → ⚙️ → Anthropic + OpenAI キー入力 → 保存
2. `~/.vlabor/profiles/piper_single_teleop/openai_api_key.txt` が
   mode 0o600 で書かれていること

### Voice mode

3. 🎤 ON → mic 権限許可 → 「ロボットの状態は？」と話しかける
4. STT → chat バブル化 → MCP ツール経由で answer → TTS 読み上げ
5. テキスト送信 → text として送信される (TTS 鳴らない)

### 音声通知 API

```bash
curl -sS -X POST http://127.0.0.1:8887/api/announce \
  -H 'content-type: application/json' \
  -d '{"text":"テスト通知","severity":"critical","source":"manual"}'
# → {"ok": true, "delivered_to": <N>, ...}
```

接続中の browser から音声で「テスト通知」が流れる。

### 自動診断 + 音声通知

D405 USB を抜く → dashboard が critical → `/diagnose` POST →
agent 診断 → conversation 保存 + `voice_announce` fan-out →
browser から「D405 のカメラが切断された…」と音声。

## 制約 / 既知

- OpenAI 経由の VLM (GPT-4o image input) は未対応 — 必要なら追加。
- TTS は完了後一括 fetch → blob → play (chunked stream は v1.1)。
- 音声履歴は保存していない (テキストのみ persist)。
- VAD は単純な energy threshold。Silero VAD WASM を入れたければ
  browser 側 `VadEngine` を差し替える設計余地は残してある。
- ローカル STT/TTS (whisper.cpp / VOICEVOX) フォールバックは v2。

## 関連ファイル

新規:
- [`chat_backend/chat_backend/keys.py`](../../chat_backend/chat_backend/keys.py)
- [`chat_backend/chat_backend/voice.py`](../../chat_backend/chat_backend/voice.py)
- [`chat_backend/chat_backend/user_settings.py`](../../chat_backend/chat_backend/user_settings.py)
- [`chat_backend/chat_backend/providers/base.py`](../../chat_backend/chat_backend/providers/base.py)
- [`chat_backend/chat_backend/providers/anthropic_provider.py`](../../chat_backend/chat_backend/providers/anthropic_provider.py)
- [`chat_backend/chat_backend/providers/openai_provider.py`](../../chat_backend/chat_backend/providers/openai_provider.py)

変更:
- [`chat_backend/chat_backend/server.py`](../../chat_backend/chat_backend/server.py) — 新エンドポイント、WS fan-out
- [`chat_backend/chat_backend/chat_loop.py`](../../chat_backend/chat_backend/chat_loop.py) — provider dispatch
- [`chat_backend/chat_backend/mcp_pool.py`](../../chat_backend/chat_backend/mcp_pool.py) — `tools_for_openai`
- [`chat_backend/chat_backend/config.py`](../../chat_backend/chat_backend/config.py) — `profile_dir`、key accessor
- [`chat_backend/chat_backend/devpage.py`](../../chat_backend/chat_backend/devpage.py) — Settings / Voice UI
- [`chat_backend/pyproject.toml`](../../chat_backend/pyproject.toml) — `openai>=1.40.0`
- [`docker/Dockerfile`](../../docker/Dockerfile) — 同上 pre-bake
