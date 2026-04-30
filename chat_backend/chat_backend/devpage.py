"""Tiny self-contained chat UI served at ``/``.

Phase 0 dev surface — replaced once the real ``web_ui`` ships. Kept
deliberately single-file so the chat backend stays useful even
without a separate frontend build step.

Three-column layout (full viewport):
  * Left: conversation history sidebar (collapsible)
  * Centre: chat (assistant + user bubbles, MCP tool cards, markdown,
    inline images from tool_result blocks)
  * Right: Live View iframe (vlabor scene_viewer) + Behavior Tree
    placeholder (filled in Phase 1)
"""

from __future__ import annotations

DEV_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>vlabor_agent</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --panel: #161b22;
      --panel-2: #1c232c;
      --border: #30363d;
      --border-soft: #21262d;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #58a6ff;
      --accent-soft: rgba(88,166,255,0.12);
      --user: #1f6feb;
      --assistant: #21262d;
      --tool: #2a2417;
      --tool-border: #6c4f1f;
      --tool-ok: #1a3a25;
      --tool-ok-border: #2ea043;
      --error: #4a1d1d;
      --error-border: #f85149;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Hiragino Sans", "Noto Sans JP", system-ui, sans-serif;
      font-size: 14px; line-height: 1.55;
      display: flex; flex-direction: column;
    }

    header {
      display: flex; align-items: center; gap: 12px;
      padding: 8px 13px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      flex-shrink: 0;
    }
    header h1 { margin: 0; font-size: 14px; font-weight: 600; color: var(--accent); }
    .status { display: inline-flex; align-items: center; gap: 3px;
              font-size: 12px; color: var(--muted); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #555; }
    .dot.ok { background: #3fb950; }
    .dot.bad { background: #f85149; }
    .grow { flex: 1; }
    header code { font-size: 11px; color: var(--muted);
                  background: rgba(255,255,255,0.04); padding: 1px 3px; border-radius: 3px; }
    .icon-btn {
      background: transparent; border: 1px solid var(--border);
      color: var(--muted); padding: 4px 10px; border-radius: 4px;
      cursor: pointer; font-size: 12px; transition: all 0.15s;
    }
    .icon-btn:hover { color: var(--accent); border-color: var(--accent); }

    /* 3-column layout fills the viewport. Side panels are resizable
       via CSS variables (set by the drag handle JS) and collapsible
       via the header toggle buttons. */
    main {
      flex: 1; min-height: 0;
      display: grid;
      grid-template-columns:
        var(--col-left, 240px) 3px 1fr 3px var(--col-right, 360px);
      width: 100%;
    }
    main.collapse-left  { grid-template-columns: 0 0 1fr 3px var(--col-right, 360px); }
    main.collapse-right { grid-template-columns: var(--col-left, 240px) 3px 1fr 0 0; }
    main.collapse-left.collapse-right { grid-template-columns: 0 0 1fr 0 0; }
    aside, .right-pane { overflow: hidden; }

    /* Drag handles — thin vertical bars sitting in the grid gaps. */
    .resizer {
      cursor: col-resize; user-select: none;
      background: var(--border-soft);
      transition: background 0.15s;
      position: relative;
    }
    .resizer:hover, .resizer.dragging { background: var(--accent); }
    .resizer.hidden { background: transparent; cursor: default; pointer-events: none; }

    /* --- Left sidebar (history) --- */
    aside {
      display: flex; flex-direction: column;
      border-right: 1px solid var(--border);
      background: var(--panel);
      min-height: 0;
    }
    aside .new-btn {
      margin: 10px; padding: 8px 12px;
      background: var(--accent); color: #0d1117;
      border: 0; border-radius: 3px; cursor: pointer;
      font-weight: 600; font-size: 13px;
    }
    aside .new-btn:hover { filter: brightness(1.15); }
    aside .conv-list {
      flex: 1; overflow-y: auto;
      display: flex; flex-direction: column;
      padding: 0 8px 10px;
    }
    aside .conv-item {
      padding: 8px 10px; border-radius: 3px;
      cursor: pointer; user-select: none;
      display: flex; flex-direction: column; gap: 2px;
      position: relative;
    }
    aside .conv-item:hover { background: rgba(255,255,255,0.04); }
    aside .conv-item.active { background: var(--accent-soft); }
    aside .conv-title {
      font-size: 13px; color: var(--text);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    aside .conv-meta { font-size: 10.5px; color: var(--muted); }
    aside .conv-del,
    aside .conv-dl {
      position: absolute; top: 3px;
      background: transparent; border: 0; color: var(--muted);
      font-size: 13px; cursor: pointer; opacity: 0; transition: opacity 0.15s;
      padding: 2px 3px;
    }
    aside .conv-del { right: 3px; }
    aside .conv-dl { right: 22px; }
    aside .conv-item:hover .conv-del,
    aside .conv-item:hover .conv-dl { opacity: 1; }
    aside .conv-del:hover { color: #f85149; }
    aside .conv-dl:hover { color: var(--accent); }
    aside .conv-empty {
      padding: 12px; font-size: 12px; color: var(--muted); text-align: center;
    }

    /* --- Centre chat --- */
    .chat-panel {
      display: flex; flex-direction: column;
      min-height: 0; min-width: 0;
      padding: 14px 18px 12px;
      gap: 10px;
    }
    #log {
      flex: 1; overflow-y: auto;
      display: flex; flex-direction: column; gap: 14px;
      padding: 4px 4px 4px 0;
    }
    #log::-webkit-scrollbar { width: 8px; }
    #log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    .msg { display: flex; gap: 10px; max-width: 100%; }
    .msg.user { justify-content: flex-end; }
    .avatar {
      width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-size: 12px; font-weight: 700;
    }
    .avatar.assistant { background: rgba(88,166,255,0.18); color: var(--accent); }
    .avatar.user { background: rgba(63,185,80,0.18); color: #3fb950; }

    .bubble {
      max-width: 78%;
      padding: 10px 14px; border-radius: 12px;
      word-wrap: break-word; overflow-wrap: anywhere;
    }
    .msg.assistant .bubble { background: var(--assistant); border-bottom-left-radius: 3px; }
    .msg.user .bubble {
      background: var(--user); color: #fff;
      border-bottom-right-radius: 3px;
    }

    .bubble p { margin: 0 0 8px; }
    .bubble p:last-child { margin-bottom: 0; }
    .bubble h1, .bubble h2, .bubble h3 { margin: 12px 0 3px; line-height: 1.3; }
    .bubble h1 { font-size: 18px; }
    .bubble h2 { font-size: 13px; }
    .bubble h3 { font-size: 14px; color: var(--accent); }
    .bubble ul, .bubble ol { margin: 3px 0; padding-left: 22px; }
    .bubble li { margin: 2px 0; }
    .bubble a { color: var(--accent); text-decoration: none; border-bottom: 1px dotted; }
    .bubble a:hover { border-bottom-style: solid; }
    .bubble code {
      background: rgba(255,255,255,0.08); padding: 1px 3px;
      border-radius: 3px; font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12.5px;
    }
    .msg.user .bubble code { background: rgba(0,0,0,0.25); }
    .bubble pre {
      background: rgba(0,0,0,0.4); padding: 10px 12px;
      border-radius: 3px; overflow-x: auto;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12px; line-height: 1.5;
      margin: 8px 0;
    }
    .bubble pre code { background: transparent; padding: 0; font-size: 12px; }
    .bubble blockquote {
      border-left: 3px solid var(--border); padding: 0 12px;
      color: var(--muted); margin: 8px 0;
    }
    .bubble table {
      border-collapse: collapse; margin: 8px 0;
      font-size: 13px; width: 100%;
    }
    .bubble th, .bubble td {
      border: 1px solid var(--border); padding: 5px 10px;
      text-align: left;
    }
    .bubble th { background: rgba(255,255,255,0.05); font-weight: 600; }
    .bubble tr:nth-child(even) td { background: rgba(255,255,255,0.02); }
    .bubble hr { border: 0; border-top: 1px solid var(--border); margin: 12px 0; }
    .bubble img {
      max-width: 100%; max-height: 320px;
      border-radius: 3px; display: block; margin: 3px 0;
      border: 1px solid var(--border);
    }

    /* Tool-use cards — kept low-contrast on purpose so the chat
       transcript stays readable. The actual tool result is hidden in
       a <details> body the operator can expand if they need it. */
    .tool {
      align-self: flex-start;
      background: transparent;
      border: 1px solid var(--border-soft);
      border-radius: 6px; padding: 3px 8px;
      max-width: 78%; margin-left: 38px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 11px; line-height: 1.35;
      color: var(--muted); opacity: 0.78;
    }
    .tool:hover { opacity: 1; }
    .tool[data-state="success"] {
      border-color: rgba(46,160,67,0.35); color: #8fb89d;
    }
    .tool[data-state="error"] {
      background: var(--error); border-color: var(--error-border);
      color: #ffd1d1; opacity: 1;
    }
    .tool summary { cursor: pointer; outline: none; user-select: none; }
    .tool summary::-webkit-details-marker { color: var(--muted); }
    .tool .body { margin-top: 3px; padding-top: 3px;
                  border-top: 1px dashed rgba(255,255,255,0.08); }
    .tool pre {
      margin: 0; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;
      font-size: 11px;
    }
    .tool .label { font-size: 10px; opacity: 0.55; margin-top: 3px; }
    .tool img { max-width: 100%; max-height: 280px; border-radius: 4px;
                display: block; margin: 4px 0; }

    .system {
      align-self: center;
      font-size: 11px; color: var(--muted);
      padding: 4px 12px; background: rgba(255,255,255,0.04);
      border-radius: 999px;
    }

    .composer {
      display: flex; gap: 8px; align-items: flex-end;
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 12px; padding: 8px;
      transition: border-color 0.15s;
    }
    .composer:focus-within { border-color: var(--accent); }
    .composer textarea {
      flex: 1; resize: none;
      background: transparent; color: var(--text);
      border: 0; outline: none;
      font: inherit; padding: 3px 8px;
      max-height: 200px; min-height: 38px;
      line-height: 1.5;
    }
    .composer textarea::placeholder { color: var(--muted); }
    .send-btn {
      align-self: flex-end;
      background: var(--accent); color: #0d1117;
      border: 0; border-radius: 8px;
      padding: 8px 18px; font-weight: 600;
      cursor: pointer; transition: opacity 0.15s, filter 0.15s;
      font-size: 13px; line-height: 1;
    }
    .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .send-btn:hover:not(:disabled) { filter: brightness(1.15); }

    .empty {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      flex: 1; gap: 3px; color: var(--muted);
    }
    .empty .big { font-size: 13px; color: var(--text); }
    .empty .small { font-size: 12px; }

    /* --- Right pane (Live View + BT) --- */
    .right-pane {
      display: flex; flex-direction: column;
      border-left: 1px solid var(--border);
      background: var(--panel);
      min-height: 0;
    }
    .pane-card {
      display: flex; flex-direction: column;
      border-bottom: 1px solid var(--border-soft);
      min-height: 0;
    }
    .pane-card:last-child { border-bottom: 0; }
    .pane-header {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 12px;
      font-size: 12px; font-weight: 600; color: var(--accent);
      background: var(--panel-2);
      border-bottom: 1px solid var(--border-soft);
      flex-shrink: 0;
    }
    .pane-header .pane-host { font-weight: normal; color: var(--muted); font-size: 11px; }
    .pane-header .grow { flex: 1; }
    .pane-card.live { flex: 1; min-height: 200px; }
    .pane-card.mcp  { display: none; }
    /* Header MCP summary: tiny dots, one per server, hover for tooltip.
       Replaces the bulky right-pane MCP list. */
    .mcp-summary {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 2px 8px;
      border: 1px solid var(--border-soft); border-radius: 4px;
      background: rgba(255,255,255,0.04);
      font-size: 11px; color: var(--muted);
      cursor: pointer;
    }
    .mcp-summary:hover { color: var(--text); border-color: var(--border); }
    .mcp-summary .label { font-weight: 600; }
    .mcp-summary .dots { display: inline-flex; gap: 3px; }
    .mcp-summary .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: #6e7681; cursor: help;
    }
    .mcp-summary .dot.connected { background: #3fb950; }
    .mcp-summary .dot.disconnected { background: #f85149; }
    /* Popover (click on summary opens detailed list, click outside closes). */
    .mcp-popover {
      display: none; position: absolute; top: 38px; right: 12px;
      z-index: 50; min-width: 280px; max-width: 360px;
      background: var(--panel-2); border: 1px solid var(--border);
      border-radius: 6px; padding: 8px; font-size: 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    }
    .mcp-popover.open { display: block; }
    .mcp-server {
      display: flex; align-items: center; gap: 6px;
      padding: 4px 0; border-bottom: 1px solid var(--border-soft);
      cursor: pointer; user-select: none;
    }
    .mcp-server:last-child { border-bottom: 0; }
    .mcp-server .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: #6e7681; flex-shrink: 0;
    }
    .mcp-server.connected .dot { background: #3fb950; }
    .mcp-server.disconnected .dot { background: #f85149; }
    .mcp-server .name { flex: 1; font-weight: 600; }
    .mcp-server .meta { font-size: 11px; color: var(--muted); }
    .mcp-tools {
      display: none; padding: 4px 0 6px 18px;
      font-size: 11px; color: var(--muted);
      font-family: 'Consolas', monospace;
    }
    .mcp-server.expanded + .mcp-tools { display: block; }
    .mcp-tools .tool-row {
      padding: 1px 0; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }
    .pane-body { flex: 1; min-height: 0; position: relative; }
    .pane-body iframe {
      width: 100%; height: 100%; border: 0;
      background: #05080c;
      display: block;
    }
    .pane-empty {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      height: 100%; gap: 3px; color: var(--muted); font-size: 12px;
      padding: 13px; text-align: center;
    }

    .bt-canvas-wrap {
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
    }

    @media (max-width: 1100px) {
      main { grid-template-columns: var(--col-left, 220px) 1fr 0 !important; }
      .right-pane { display: none; }
    }

    /* --- Settings modal + voice mode --- */
    .modal-backdrop {
      position: fixed; inset: 0; z-index: 50;
      background: rgba(0,0,0,0.78);
      backdrop-filter: blur(4px);
      display: none; align-items: center; justify-content: center;
    }
    .modal-backdrop[data-open="1"] { display: flex; }
    .modal-card {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 12px; padding: 18px 22px;
      width: min(560px, 92vw); max-height: 88vh; overflow: auto;
      box-shadow: 0 12px 40px rgba(0,0,0,0.6);
    }
    .modal-card h2 {
      margin: 0 0 12px 0; font-size: 15px;
      display: flex; align-items: center; gap: 8px;
    }
    .modal-card h2 .grow { flex: 1; }
    .modal-card h3 {
      margin: 18px 0 6px 0; font-size: 12px;
      text-transform: uppercase; letter-spacing: 0.04em;
      color: var(--muted);
    }
    .modal-card label {
      display: block; font-size: 12px; color: var(--muted);
      margin: 8px 0 3px 0;
    }
    .modal-card input[type="text"], .modal-card input[type="password"],
    .modal-card input[type="number"], .modal-card select {
      width: 100%; padding: 6px 9px;
      background: var(--bg); color: var(--text);
      border: 1px solid var(--border); border-radius: 6px;
      font: 13px ui-monospace, monospace;
      box-sizing: border-box;
    }
    .modal-card .row { display: flex; gap: 8px; align-items: center; }
    .modal-card .row > * { min-width: 0; }
    .modal-card .row > input { flex: 1; }
    .modal-card .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
    .modal-card .check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
    .modal-card .actions {
      display: flex; gap: 8px; justify-content: flex-end;
      margin-top: 18px; padding-top: 12px;
      border-top: 1px solid var(--border);
    }
    .modal-card .actions button {
      padding: 7px 14px; font-size: 13px; border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg); color: var(--text); cursor: pointer;
    }
    .modal-card .actions button.primary {
      background: var(--accent); border-color: var(--accent); color: #06121a;
    }
    .key-status {
      font-size: 11px; color: var(--muted);
      padding: 2px 8px; border-radius: 999px;
      border: 1px solid var(--border);
    }
    .key-status[data-set="1"] { color: #56d394; border-color: #2c7a55; }
    .show-toggle {
      padding: 5px 10px; font-size: 11px;
      background: var(--bg); color: var(--muted);
      border: 1px solid var(--border); border-radius: 6px;
      cursor: pointer;
    }

    /* --- Voice mode indicator --- */
    .voice-btn {
      position: relative;
    }
    .voice-btn[data-state="on"] {
      background: rgba(86, 211, 148, 0.18);
      border-color: #56d394;
      color: #56d394;
    }
    .voice-btn[data-state="on"]::after {
      content: ''; position: absolute;
      top: 4px; right: 4px;
      width: 6px; height: 6px; border-radius: 50%;
      background: #56d394;
      box-shadow: 0 0 6px #56d394;
      animation: pulse-voice 1.4s ease-in-out infinite;
    }
    @keyframes pulse-voice {
      0%, 100% { opacity: 0.5; transform: scale(0.8); }
      50% { opacity: 1; transform: scale(1.2); }
    }
    .voice-status {
      display: none;
      padding: 3px 10px; margin: 6px 12px 0 12px;
      background: var(--bg2); border: 1px solid var(--border);
      border-radius: 6px;
      font-size: 12px; color: var(--muted);
      align-items: center; gap: 8px;
    }
    .voice-status[data-state]:not([data-state="idle"]) { display: flex; }
    .voice-status canvas {
      flex: 1; height: 18px; min-width: 60px;
      background: var(--bg); border-radius: 3px;
    }
    .voice-status .vs-label { white-space: nowrap; }
    .voice-status[data-state="recording"] { color: #ff5d8f; }
    .voice-status[data-state="stt_busy"]  { color: #ffd166; }
    .voice-status[data-state="chatting"]  { color: var(--accent); }
    .voice-status[data-state="tts_busy"]  { color: #56d394; }
  </style>
</head>
<body>
  <header>
    <h1>vlabor_agent</h1>
    <span class="status">
      <span id="wsDot" class="dot"></span>
      <span id="wsLabel" data-i18n="ws.connecting">接続中</span>
    </span>
    <span class="grow"></span>
    <span id="mcpSummary" class="mcp-summary"
          title="MCP サーバ — クリックで詳細"
          onclick="document.getElementById('mcpPopover').classList.toggle('open');event.stopPropagation();">
      <span class="label">MCP</span>
      <span class="dots" id="mcpSummaryDots"></span>
      <span id="mcpSummaryCount">0/0</span>
    </span>
    <code id="serverHost">…</code>
    <button class="icon-btn" id="settingsBtn"
            data-i18n="header.settings"
            data-i18n-title="header.settingsTip"
            title="API キー + 音声設定">⚙ 設定</button>
    <button class="icon-btn" id="resetBtn"
            data-i18n="header.reset"
            data-i18n-title="header.resetTip"
            title="新規チャット (現在の会話は保存)">↺ リセット</button>
  </header>
  <!-- MCP detailed list — anchored under the header summary chip,
       toggled by clicking the chip; closed by clicking outside. -->
  <div class="mcp-popover" id="mcpPopover">
    <div style="display:flex; align-items:center; margin-bottom:6px;">
      <span style="font-weight:600;">MCP サーバ</span>
      <span style="flex:1;"></span>
      <button class="icon-btn" id="mcpReload"
              data-i18n-title="pane.mcpReload"
              title="MCP 接続状態を再取得">↻</button>
    </div>
    <div id="mcpStatusBody">
      <div class="pane-empty" data-i18n="pane.mcpLoading">読み込み中…</div>
    </div>
  </div>
  <main id="layout">
    <aside>
      <button class="new-btn" id="newChatBtn" type="button"
              data-i18n="sidebar.new">+ 新規チャット</button>
      <div class="conv-list" id="convList">
        <div class="conv-empty" data-i18n="sidebar.empty">(会話なし)</div>
      </div>
    </aside>
    <div class="resizer" id="resizerLeft" data-edge="left"
         data-i18n-title="resize.left"
         title="ドラッグで履歴ペインの幅を調整"></div>

    <section class="chat-panel">
      <div id="log">
        <div class="empty" id="emptyState">
          <div class="big" data-i18n="chat.emptyBig">エージェントに何でも聞いてください</div>
          <div class="small" data-i18n="chat.emptySmall">ツールは設定済みの MCP サーバから提供されます。Markdown / 表 / 画像 対応。</div>
        </div>
      </div>
      <div class="composer">
        <textarea id="input" rows="1"
                  data-i18n-placeholder="chat.placeholder"
                  placeholder="メッセージを入力 — Enter で送信、Shift+Enter で改行"></textarea>
        <button id="send" class="send-btn" type="button"
                data-i18n="chat.send">送信</button>
      </div>
    </section>
    <div class="resizer" id="resizerRight" data-edge="right"
         data-i18n-title="resize.right"
         title="ドラッグでライブビュー / MCP ペインの幅を調整"></div>

    <div class="right-pane">
      <div class="pane-card live">
        <div class="pane-header">
          <span data-i18n="pane.live">ライブビュー</span>
          <span class="pane-host" id="liveHost">—</span>
          <span class="grow"></span>
          <button class="icon-btn" id="liveReload"
                  data-i18n-title="pane.liveReload"
                  title="iframe を再読み込み">↻</button>
        </div>
        <div class="pane-body">
          <iframe id="liveFrame" title="Live View" loading="lazy"></iframe>
          <div class="pane-empty" id="liveEmpty" style="display:none;">
            <span data-i18n="pane.liveUnreachable">scene_viewer に接続できません</span><br>
            <span style="font-size:11px;"><span data-i18n="pane.liveExpected">期待アドレス:</span> <code id="liveUrl">—</code></span>
          </div>
        </div>
      </div>
    </div>
  </main>

  <div class="modal-backdrop" id="settingsBackdrop" data-open="0">
    <div class="modal-card" onclick="event.stopPropagation()">
      <h2>
        <span>⚙️ 設定</span>
        <span class="grow"></span>
        <span style="font-size:11px; color: var(--muted); margin-right: 10px;">~/.vlabor/agent/settings.json</span>
        <button id="settingsClose" type="button"
                style="background:transparent; border:0; color:var(--muted); font-size:18px; cursor:pointer; padding:0 4px;"
                title="閉じる (Esc)">✕</button>
      </h2>

      <h3>API キー</h3>
      <label>
        Anthropic
        <span class="key-status" id="keyStatusAnthropic" data-set="0">未設定</span>
      </label>
      <div class="row">
        <input type="password" id="keyAnthropic" placeholder="sk-ant-…  (空のまま Save で変更なし)" autocomplete="off">
        <button class="show-toggle" data-target="keyAnthropic" type="button">表示</button>
      </div>

      <label>
        OpenAI
        <span class="key-status" id="keyStatusOpenai" data-set="0">未設定</span>
      </label>
      <div class="row">
        <input type="password" id="keyOpenai" placeholder="sk-…  (Whisper / TTS / GPT 用)" autocomplete="off">
        <button class="show-toggle" data-target="keyOpenai" type="button">表示</button>
      </div>

      <h3>Chat provider</h3>
      <div class="grid2">
        <div>
          <label>Provider</label>
          <select id="chatProvider">
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>
        <div>
          <label>Model (空欄でデフォルト)</label>
          <input type="text" id="chatModel" placeholder="claude-sonnet-4-6 / gpt-4o-mini">
        </div>
      </div>

      <h3>Voice mode</h3>
      <div class="grid2">
        <div>
          <label>TTS voice</label>
          <select id="ttsVoice">
            <option value="alloy">alloy</option>
            <option value="echo">echo</option>
            <option value="fable">fable</option>
            <option value="onyx">onyx</option>
            <option value="nova">nova</option>
            <option value="shimmer">shimmer</option>
          </select>
        </div>
        <div>
          <label>TTS speed</label>
          <input type="number" id="ttsSpeed" step="0.05" min="0.5" max="4.0" value="1.0">
        </div>
        <div>
          <label>STT 言語</label>
          <input type="text" id="sttLang" value="ja" placeholder="ja / en / ...">
        </div>
        <div>
          <label>無音閾値 (ms)</label>
          <input type="number" id="silenceMs" min="200" max="3000" step="100" value="800">
        </div>
        <div>
          <label>エネルギー閾値 (dB)</label>
          <input type="number" id="energyDb" min="-80" max="-20" step="1" value="-45">
        </div>
        <div>
          <label class="check">
            <input type="checkbox" id="bargeIn">
            割込発話 (TTS 中に話したら停止)
          </label>
        </div>
      </div>

      <h3>表示</h3>
      <div class="grid2">
        <div>
          <label class="check">
            <input type="checkbox" id="showLeftPane" checked>
            履歴サイドバーを表示
          </label>
        </div>
        <div>
          <label class="check">
            <input type="checkbox" id="showRightPane" checked>
            Live View / BT パネルを表示
          </label>
        </div>
      </div>

      <h3>音声通知 / 自動診断アナウンス</h3>
      <div class="grid2">
        <div>
          <label class="check">
            <input type="checkbox" id="notifyEnabled" checked>
            音声通知を有効化
          </label>
        </div>
        <div>
          <label class="check">
            <input type="checkbox" id="notifyDiagnose" checked>
            自動診断結果を読み上げる
          </label>
        </div>
        <div>
          <label>通知の最低 severity</label>
          <select id="notifySeverity">
            <option value="critical">critical</option>
            <option value="warning">warning</option>
            <option value="info">info (すべて)</option>
          </select>
        </div>
      </div>

      <div class="actions">
        <button id="settingsSave" type="button" class="primary">保存</button>
      </div>
    </div>
  </div>

<script>
// --- i18n ------------------------------------------------------------------
// Minimal JP/EN dictionary. The dashboard parent (vlabor_dashboard) uses
// VLLang internally and postMessages "set_language" here on switch, so
// the iframe stays in sync without a build step.
const I18N = {
  ja: {
    'header.settings': '⚙ 設定',
    'header.settingsTip': 'API キー + 音声設定',
    'header.reset': '↺ リセット',
    'header.resetTip': '新規チャット (現在の会話は保存)',
    'ws.connecting': '接続中',
    'ws.connected': '接続済み',
    'ws.disconnected': '切断',
    'ws.error': 'エラー',
    'sidebar.new': '+ 新規チャット',
    'sidebar.empty': '(会話なし)',
    'sidebar.untitled': '(無題)',
    'sidebar.delete': '削除',
    'sidebar.download': 'JSON ダウンロード',
    'sidebar.confirmDelete': 'この会話を削除しますか？',
    'sidebar.dlError': 'ダウンロード失敗: ',
    'sidebar.msgUnit': 'メッセージ',
    'chat.emptyBig': 'エージェントに何でも聞いてください',
    'chat.emptySmall': 'ツールは設定済みの MCP サーバから提供されます。Markdown / 表 / 画像 対応。',
    'chat.send': '送信',
    'chat.placeholder': 'メッセージを入力 — Enter で送信、Shift+Enter で改行',
    'pane.live': 'ライブビュー',
    'pane.liveReload': 'iframe を再読み込み',
    'pane.liveUnreachable': 'scene_viewer に接続できません',
    'pane.liveExpected': '期待アドレス:',
    'pane.mcp': 'MCP サーバ',
    'pane.mcpReload': 'MCP 接続状態を再取得',
    'pane.mcpLoading': '読み込み中…',
    'pane.mcpEmpty': '登録された MCP サーバなし',
    'pane.mcpFailed': 'MCP 状態取得失敗',
    'mcp.tools': 'tools',
    'mcp.connected': '接続済み',
    'mcp.disconnected': '未接続',
    'mcp.empty': '(なし)',
    'resize.left': 'ドラッグで履歴ペインの幅を調整',
    'resize.right': 'ドラッグでライブビュー / MCP ペインの幅を調整',
  },
  en: {
    'header.settings': '⚙ Settings',
    'header.settingsTip': 'API keys + voice settings',
    'header.reset': '↺ Reset',
    'header.resetTip': 'New chat (current conversation saved)',
    'ws.connecting': 'connecting',
    'ws.connected': 'connected',
    'ws.disconnected': 'disconnected',
    'ws.error': 'error',
    'sidebar.new': '+ New chat',
    'sidebar.empty': '(no conversations)',
    'sidebar.untitled': '(untitled)',
    'sidebar.delete': 'Delete',
    'sidebar.download': 'Download JSON',
    'sidebar.confirmDelete': 'Delete this conversation?',
    'sidebar.dlError': 'Download failed: ',
    'sidebar.msgUnit': 'msg',
    'chat.emptyBig': 'Ask the agent anything',
    'chat.emptySmall': 'Tools come from the configured MCP servers. Markdown, tables, and images supported.',
    'chat.send': 'Send',
    'chat.placeholder': 'Type a message — Enter to send, Shift+Enter for newline',
    'pane.live': 'Live View',
    'pane.liveReload': 'Reload iframe',
    'pane.liveUnreachable': 'scene_viewer not reachable',
    'pane.liveExpected': 'expected at',
    'pane.mcp': 'MCP servers',
    'pane.mcpReload': 'Refresh MCP status',
    'pane.mcpLoading': 'Loading…',
    'pane.mcpEmpty': 'No MCP servers configured',
    'pane.mcpFailed': 'Failed to load MCP status',
    'mcp.tools': 'tools',
    'mcp.connected': 'connected',
    'mcp.disconnected': 'disconnected',
    'mcp.empty': '(none)',
    'resize.left': 'Drag to resize history pane',
    'resize.right': 'Drag to resize Live View / MCP pane',
  },
};
let curLang = 'ja';
function t(key) {
  const d = I18N[curLang] || I18N.en;
  return (d && d[key]) || (I18N.en && I18N.en[key]) || key;
}
function applyI18n() {
  document.documentElement.setAttribute('lang', curLang);
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
}
function setLanguage(lang) {
  if (!I18N[lang] || lang === curLang) return;
  curLang = lang;
  try { localStorage.setItem('vlabor_agent.lang', lang); } catch (_) {}
  applyI18n();
  // Re-render dynamic content that contained localized text
  refreshConversationList && refreshConversationList();
  refreshMcpStatus && refreshMcpStatus();
  // Re-render the WS status pill if it's currently set
  if (typeof ws !== 'undefined' && ws) {
    if (ws.readyState === WebSocket.OPEN) setWsStatus('open');
    else if (ws.readyState === WebSocket.CLOSED) setWsStatus('closed');
  }
}

const log = document.getElementById('log');
const empty = document.getElementById('emptyState');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const wsDot = document.getElementById('wsDot');
const wsLabel = document.getElementById('wsLabel');
const resetBtn = document.getElementById('resetBtn');
const layout = document.getElementById('layout');
// Header pane-toggle buttons were removed in favour of the Settings
// modal — visibility is now controlled by checkboxes there. The
// localStorage layout state still persists so a refresh keeps the
// last operator-chosen layout.
const convList = document.getElementById('convList');
const newChatBtn = document.getElementById('newChatBtn');
const liveFrame = document.getElementById('liveFrame');
const liveReload = document.getElementById('liveReload');
const liveHost = document.getElementById('liveHost');
const liveUrl = document.getElementById('liveUrl');
const liveEmpty = document.getElementById('liveEmpty');
document.getElementById('serverHost').textContent = location.host;

if (window.marked) {
  marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
}

const history = [];
let ws = null;
let inflight = false;
let activeAssistantBubble = null;
let conversationId = null;
let inflightStartedAt = 0;
let lastWsMessageAt = 0;

// Format a CloseEvent into a human-readable cause string. Browsers
// strip most network-layer detail for security, so the close code is
// often the only signal we have for diagnosis.
function describeWsClose(ev) {
  const code = ev && typeof ev.code === 'number' ? ev.code : 0;
  const reason = ev && ev.reason ? String(ev.reason) : '';
  const meanings = {
    1000: 'normal close',
    1001: 'going away (page unload?)',
    1005: 'no status (peer dropped without code)',
    1006: 'abnormal close — no clean shutdown (network drop, proxy idle, browser tab killed, or server crashed)',
    1011: 'server internal error',
    1012: 'server restart',
    1013: 'try again later (server overloaded?)',
    1015: 'TLS failure',
  };
  const parts = [meanings[code] || ('code ' + code)];
  if (reason) parts.push('reason: "' + reason + '"');
  if (lastWsMessageAt) {
    parts.push(Math.round((Date.now() - lastWsMessageAt) / 1000) + 's since last server msg');
  }
  if (inflightStartedAt) {
    parts.push(Math.round((Date.now() - inflightStartedAt) / 1000) + 's into turn');
  }
  return parts.join('; ');
}

// --- helpers ---------------------------------------------------------------

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function md(text) {
  if (!window.marked) return escapeHtml(text);
  const raw = marked.parse(String(text || ''));
  return window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
}
function clearEmpty() {
  if (empty && empty.parentNode) empty.remove();
}

// --- chat rendering --------------------------------------------------------

function addUser(text) {
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg user';
  wrap.innerHTML = `<div class="bubble">${md(text)}</div><div class="avatar user">U</div>`;
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}
function ensureAssistantBubble() {
  if (activeAssistantBubble) return activeAssistantBubble;
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg assistant';
  wrap.innerHTML = `<div class="avatar assistant">vA</div><div class="bubble"></div>`;
  log.appendChild(wrap);
  activeAssistantBubble = wrap.querySelector('.bubble');
  log.scrollTop = log.scrollHeight;
  return activeAssistantBubble;
}
function appendAssistantText(text) {
  const bubble = ensureAssistantBubble();
  bubble.dataset.raw = (bubble.dataset.raw || '') + text;
  bubble.innerHTML = md(bubble.dataset.raw);
  log.scrollTop = log.scrollHeight;
}
function addToolCall(name, inputObj, id) {
  clearEmpty();
  activeAssistantBubble = null;
  const tool = document.createElement('details');
  tool.className = 'tool';
  tool.dataset.state = 'pending';
  tool.id = `tool-${id}`;
  let argText = '';
  try { argText = JSON.stringify(inputObj || {}, null, 2); } catch (_) { argText = String(inputObj); }
  tool.innerHTML = `
    <summary>🔧 <strong>${escapeHtml(name)}</strong>
      <span style="opacity:0.6">running…</span></summary>
    <div class="body">
      <div class="label">arguments</div>
      <pre>${escapeHtml(argText)}</pre>
    </div>`;
  log.appendChild(tool);
  log.scrollTop = log.scrollHeight;
}
function blocksToHtml(blocks) {
  if (!Array.isArray(blocks) || !blocks.length) return '<pre>(no content)</pre>';
  const parts = [];
  for (const b of blocks) {
    if (b.type === 'text') parts.push(`<pre>${escapeHtml(b.text || '')}</pre>`);
    else if (b.type === 'image') {
      const src = b.source || {};
      if (src.type === 'base64' && src.data) {
        const mime = src.media_type || 'image/png';
        parts.push(`<img alt="tool result image" src="data:${mime};base64,${src.data}">`);
      } else parts.push('<pre>[image — unrenderable source]</pre>');
    } else parts.push(`<pre>${escapeHtml(JSON.stringify(b))}</pre>`);
  }
  return parts.join('');
}
function finishToolCall(id, name, isError, summary, content) {
  const tool = document.getElementById(`tool-${id}`);
  if (!tool) return;
  tool.dataset.state = isError ? 'error' : 'success';
  const icon = isError ? '❌' : '✓';
  const summaryText = summary || (isError ? 'failed' : 'ok');
  const argBody = tool.querySelector('.body') ? tool.querySelector('.body').innerHTML : '';
  tool.innerHTML = `
    <summary>${icon} <strong>${escapeHtml(name)}</strong>
      <span style="opacity:0.75"> — ${escapeHtml(summaryText)}</span></summary>
    <div class="body">
      ${argBody}
      <div class="label">result</div>
      ${blocksToHtml(content)}
    </div>`;
  log.scrollTop = log.scrollHeight;
}
function appendSystem(text) {
  clearEmpty();
  const div = document.createElement('div');
  div.className = 'system';
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}
function setWsStatus(state) {
  wsDot.classList.remove('ok', 'bad');
  if (state === 'open') { wsDot.classList.add('ok'); wsLabel.textContent = t('ws.connected'); }
  else if (state === 'closed') { wsDot.classList.add('bad'); wsLabel.textContent = t('ws.disconnected'); }
  else if (state === 'error') { wsDot.classList.add('bad'); wsLabel.textContent = t('ws.error'); }
  else { wsLabel.textContent = state; }
}

// --- WS --------------------------------------------------------------------

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/chat`);
  ws.addEventListener('open', () => setWsStatus('open'));
  ws.addEventListener('close', (ev) => {
    setWsStatus('closed');
    // If a turn was in flight when the socket dropped, no `done`/`error`
    // event will ever arrive — clear the stuck state so the user can try
    // again instead of staring at a permanently-disabled send button.
    // Surface the close code / reason so the user can tell whether it
    // was a clean shutdown, a server crash, or a network drop.
    if (inflight) {
      inflight = false;
      sendBtn.disabled = false;
      activeAssistantBubble = null;
      appendSystem('(connection lost — ' + describeWsClose(ev) + ' — please retry)');
    }
    setTimeout(connect, 2000);
  });
  ws.addEventListener('error', () => {
    setWsStatus('error');
    if (inflight) {
      inflight = false;
      sendBtn.disabled = false;
      activeAssistantBubble = null;
    }
  });
  ws.addEventListener('message', (ev) => {
    lastWsMessageAt = Date.now();
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === 'assistant_text_delta') appendAssistantText(m.text);
    else if (m.type === 'assistant_text') {
      // Final consolidated text for this assistant block. If we already
      // streamed the same content via deltas, skip — otherwise (legacy
      // backend, no streaming) render the whole thing now.
      const bubble = activeAssistantBubble;
      if (!bubble || (bubble.dataset.raw || '') !== m.text) appendAssistantText(m.text);
      // Close out the current bubble so the next assistant turn opens a fresh one.
      activeAssistantBubble = null;
    }
    else if (m.type === 'tool_use_start') addToolCall(m.name, m.input, m.id);
    else if (m.type === 'tool_use_result') finishToolCall(m.id, m.name, m.is_error, m.summary, m.content);
    else if (m.type === 'conversation_created') {
      conversationId = m.id;
      refreshConversationList();
    } else if (m.type === 'done') {
      activeAssistantBubble = null;
      inflight = false;
      sendBtn.disabled = false;
      if (m.stop_reason === 'no_api_key') appendSystem('(no API key — save one and resend)');
      refreshConversationList();
    } else if (m.type === 'error') {
      activeAssistantBubble = null;
      inflight = false;
      sendBtn.disabled = false;
      const err = document.createElement('div');
      err.className = 'tool';
      err.dataset.state = 'error';
      err.innerHTML = `<summary>❌ <strong>error</strong>
        <span style="opacity:0.75"> — ${escapeHtml(m.message || 'unknown')}</span></summary>`;
      log.appendChild(err);
      log.scrollTop = log.scrollHeight;
    } else if (m.type === 'transcript') {
      history.length = 0;
      for (const x of m.messages) history.push(x);
      if (m.conversation_id) conversationId = m.conversation_id;
      refreshConversationList();
    }
  });
}

// --- composer --------------------------------------------------------------

function autoSize() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
}
input.addEventListener('input', autoSize);

function submit() {
  const text = (input.value || '').trim();
  if (!text || inflight || !ws || ws.readyState !== WebSocket.OPEN) return;
  inflight = true;
  sendBtn.disabled = true;
  inflightStartedAt = Date.now();
  lastWsMessageAt = 0;
  addUser(text);
  input.value = '';
  autoSize();
  ws.send(JSON.stringify({
    type: 'user_message',
    text,
    history,
    conversation_id: conversationId,
  }));
}
sendBtn.addEventListener('click', submit);
input.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  submit();
});

// --- conversation list / load ---------------------------------------------

async function refreshConversationList() {
  let data;
  try {
    const resp = await fetch('/api/conversations');
    data = await resp.json();
  } catch (_) { return; }
  const items = (data && data.conversations) || [];
  convList.innerHTML = '';
  if (!items.length) {
    convList.innerHTML = `<div class="conv-empty">${escapeHtml(t('sidebar.empty'))}</div>`;
    return;
  }
  for (const c of items) {
    const row = document.createElement('div');
    row.className = 'conv-item' + (c.id === conversationId ? ' active' : '');
    row.dataset.id = c.id;
    row.innerHTML = `
      <span class="conv-title">${escapeHtml(c.title || t('sidebar.untitled'))}</span>
      <span class="conv-meta">${escapeHtml(c.updated_at || '')} · ${c.message_count} ${escapeHtml(t('sidebar.msgUnit'))}</span>
      <button class="conv-dl"  title="${escapeHtml(t('sidebar.download'))}">⬇</button>
      <button class="conv-del" title="${escapeHtml(t('sidebar.delete'))}">✕</button>`;
    row.addEventListener('click', (e) => {
      if (e.target.classList.contains('conv-del')) return;
      if (e.target.classList.contains('conv-dl')) return;
      loadConversation(c.id);
    });
    row.querySelector('.conv-dl').addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const resp = await fetch('/api/conversations/' + encodeURIComponent(c.id));
        if (!resp.ok) throw new Error('fetch failed');
        const payload = await resp.json();
        const blob = new Blob([JSON.stringify(payload, null, 2)],
                              { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const safeTitle = (c.title || c.id || 'conversation').replace(/[\/\\:*?"<>|]/g, '_').slice(0, 80);
        a.href = url;
        a.download = `${safeTitle}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        alert(t('sidebar.dlError') + (err.message || err));
      }
    });
    row.querySelector('.conv-del').addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm(t('sidebar.confirmDelete'))) return;
      try { await fetch('/api/conversations/' + encodeURIComponent(c.id), { method: 'DELETE' }); }
      catch (_) {}
      if (c.id === conversationId) {
        conversationId = null;
        history.length = 0;
        log.innerHTML = '';
        log.appendChild(empty);
      }
      await refreshConversationList();
    });
    convList.appendChild(row);
  }
}
async function loadConversation(id) {
  let payload;
  try {
    const resp = await fetch('/api/conversations/' + encodeURIComponent(id));
    if (!resp.ok) return;
    payload = await resp.json();
  } catch (_) { return; }
  conversationId = payload.id;
  history.length = 0;
  for (const m of (payload.messages || [])) history.push(m);
  rerenderFromHistory();
  await refreshConversationList();
  input.focus();
}
function rerenderFromHistory() {
  log.innerHTML = '';
  if (!history.length) { log.appendChild(empty); return; }
  for (const m of history) {
    if (m.role === 'user') {
      // user message can either be a text turn or a list of tool_results.
      if (Array.isArray(m.content)) {
        const text = m.content.filter(b => b && b.type === 'text').map(b => b.text || '').join('');
        if (text) addUser(text);
        for (const b of m.content) {
          if (b && b.type === 'tool_result') {
            finishToolCall(b.tool_use_id || '', '(tool)',
                           !!b.is_error, '', b.content || []);
          }
        }
      } else if (typeof m.content === 'string') {
        addUser(m.content);
      }
    } else if (m.role === 'assistant') {
      activeAssistantBubble = null;
      const blocks = Array.isArray(m.content) ? m.content : [];
      for (const b of blocks) {
        if (b.type === 'text' && b.text) appendAssistantText(b.text);
        else if (b.type === 'tool_use') {
          addToolCall(b.name || '(tool)', b.input || {}, b.id || '');
        }
      }
    }
  }
  activeAssistantBubble = null;
}
newChatBtn.addEventListener('click', () => {
  conversationId = null;
  history.length = 0;
  activeAssistantBubble = null;
  log.innerHTML = '';
  log.appendChild(empty);
  refreshConversationList();
  input.focus();
});

// --- header buttons --------------------------------------------------------

function persistLayoutPrefs() {
  try {
    localStorage.setItem('vlabor_agent.layout', JSON.stringify({
      collapseLeft: layout.classList.contains('collapse-left'),
      collapseRight: layout.classList.contains('collapse-right'),
    }));
  } catch (_) {}
}
function restoreLayoutPrefs() {
  try {
    const raw = localStorage.getItem('vlabor_agent.layout');
    if (!raw) return;
    const p = JSON.parse(raw);
    if (p.collapseLeft) layout.classList.add('collapse-left');
    if (p.collapseRight) layout.classList.add('collapse-right');
  } catch (_) {}
}
function setPaneVisibility(side, visible) {
  const cls = side === 'left' ? 'collapse-left' : 'collapse-right';
  if (visible) layout.classList.remove(cls);
  else layout.classList.add(cls);
  persistLayoutPrefs();
}

// --- drag to resize side panels --------------------------------------------

const RESIZE_KEY = 'vlabor_agent.col_widths';
const MIN_LEFT = 160, MAX_LEFT = 480;
const MIN_RIGHT = 240, MAX_RIGHT = 720;

function applyColWidths(left, right) {
  if (typeof left === 'number') {
    layout.style.setProperty('--col-left', `${Math.max(MIN_LEFT, Math.min(MAX_LEFT, left))}px`);
  }
  if (typeof right === 'number') {
    layout.style.setProperty('--col-right', `${Math.max(MIN_RIGHT, Math.min(MAX_RIGHT, right))}px`);
  }
}
function persistColWidths() {
  try {
    const left = parseInt(getComputedStyle(layout).getPropertyValue('--col-left'), 10) || 240;
    const right = parseInt(getComputedStyle(layout).getPropertyValue('--col-right'), 10) || 360;
    localStorage.setItem(RESIZE_KEY, JSON.stringify({ left, right }));
  } catch (_) {}
}
function restoreColWidths() {
  try {
    const raw = localStorage.getItem(RESIZE_KEY);
    if (!raw) return;
    const p = JSON.parse(raw);
    applyColWidths(p.left, p.right);
  } catch (_) {}
}
restoreColWidths();

function startDrag(e, edge) {
  if (e.button !== 0) return;
  // The resizer is a no-op when its column is collapsed.
  if (edge === 'left' && layout.classList.contains('collapse-left')) return;
  if (edge === 'right' && layout.classList.contains('collapse-right')) return;
  e.preventDefault();
  const startX = e.clientX;
  const css = getComputedStyle(layout);
  const startLeft = parseInt(css.getPropertyValue('--col-left'), 10) || 240;
  const startRight = parseInt(css.getPropertyValue('--col-right'), 10) || 360;
  const handle = (edge === 'left' ? document.getElementById('resizerLeft')
                                  : document.getElementById('resizerRight'));
  handle.classList.add('dragging');
  document.body.style.cursor = 'col-resize';

  function onMove(ev) {
    const dx = ev.clientX - startX;
    if (edge === 'left') applyColWidths(startLeft + dx, undefined);
    else applyColWidths(undefined, startRight - dx);
  }
  function onUp() {
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    persistColWidths();
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}
document.getElementById('resizerLeft').addEventListener('mousedown', (e) => startDrag(e, 'left'));
document.getElementById('resizerRight').addEventListener('mousedown', (e) => startDrag(e, 'right'));

// Double-click on a resizer resets that side to its default width.
document.getElementById('resizerLeft').addEventListener('dblclick', () => {
  applyColWidths(240, undefined); persistColWidths();
});
document.getElementById('resizerRight').addEventListener('dblclick', () => {
  applyColWidths(undefined, 360); persistColWidths();
});

restoreLayoutPrefs();

resetBtn.addEventListener('click', () => {
  history.length = 0;
  conversationId = null;
  log.innerHTML = '';
  log.appendChild(empty);
  appendSystem('chat cleared (next send creates a new conversation)');
  refreshConversationList();
});

// --- right pane: Live View probe -------------------------------------------

function setLiveView() {
  // scene_viewer convention: same host, port 8097. If the host can't
  // reach it (e.g. running this UI from a laptop pointed at a robot's
  // backend), the iframe just shows browser's own connection error
  // and we surface the URL in the empty state.
  const host = location.hostname;
  const url = `${location.protocol}//${host}:8097/`;
  liveHost.textContent = `${host}:8097`;
  liveUrl.textContent = url;
  liveFrame.src = url;
}
liveReload.addEventListener('click', () => {
  liveFrame.src = liveFrame.src;  // force reload
});
setLiveView();

// --- MCP status pane -------------------------------------------------------

async function refreshMcpStatus() {
  const body = document.getElementById('mcpStatusBody');
  const dotsEl = document.getElementById('mcpSummaryDots');
  const countEl = document.getElementById('mcpSummaryCount');
  let data;
  try {
    const resp = await fetch('/api/mcp/status');
    data = await resp.json();
  } catch (_) {
    if (body) body.innerHTML = `<div class="pane-empty">${escapeHtml(t('pane.mcpFailed'))}</div>`;
    if (dotsEl) dotsEl.innerHTML = '';
    if (countEl) countEl.textContent = '!';
    return;
  }
  const servers = (data && data.servers) || [];
  // Header summary: tiny dots, one per server. Click chip to open popover.
  if (dotsEl) {
    dotsEl.innerHTML = '';
    for (const s of servers) {
      const d = document.createElement('span');
      d.className = 'dot ' + (s.connected ? 'connected' : 'disconnected');
      d.title = `${s.name} — ${s.connected ? 'connected' : 'disconnected'} · ${s.tool_count} tools`;
      dotsEl.appendChild(d);
    }
  }
  if (countEl) {
    const ok = servers.filter(s => s.connected).length;
    countEl.textContent = `${ok}/${servers.length}`;
  }
  if (!body) return;
  if (!servers.length) {
    body.innerHTML = `<div class="pane-empty">${escapeHtml(t('pane.mcpEmpty'))}</div>`;
    return;
  }
  body.innerHTML = '';
  for (const s of servers) {
    const row = document.createElement('div');
    row.className = 'mcp-server ' + (s.connected ? 'connected' : 'disconnected');
    row.innerHTML = `
      <span class="dot"></span>
      <span class="name">${escapeHtml(s.name)}</span>
      <span class="meta">${s.tool_count} ${escapeHtml(t('mcp.tools'))} · ${escapeHtml(s.transport || '')}</span>`;
    row.title = `${s.url}\n${s.connected ? t('mcp.connected') : t('mcp.disconnected')}`;
    const toolsDiv = document.createElement('div');
    toolsDiv.className = 'mcp-tools';
    if (s.tools && s.tools.length) {
      toolsDiv.innerHTML = s.tools.map(
        n => `<div class="tool-row">• ${escapeHtml(n)}</div>`
      ).join('');
    } else {
      toolsDiv.innerHTML = `<div class="tool-row">${escapeHtml(t('mcp.empty'))}</div>`;
    }
    row.addEventListener('click', () => row.classList.toggle('expanded'));
    body.appendChild(row);
    body.appendChild(toolsDiv);
  }
}
document.getElementById('mcpReload')?.addEventListener('click', refreshMcpStatus);
// Close popover when clicking outside.
document.addEventListener('click', (ev) => {
  const pop = document.getElementById('mcpPopover');
  const sum = document.getElementById('mcpSummary');
  if (!pop || !pop.classList.contains('open')) return;
  if (pop.contains(ev.target) || (sum && sum.contains(ev.target))) return;
  pop.classList.remove('open');
});

// --- boot ------------------------------------------------------------------

connect();
refreshConversationList();
refreshMcpStatus();
input.focus();

// Cross-frame command channel: when this UI is embedded in the vlabor
// dashboard's Agent tab, the dashboard postMessages here to switch
// conversations (e.g. after the operator presses 🩺 診断 — the
// dashboard POSTs /diagnose, gets a conversation_id, then asks us to
// open it). No origin pinning because the dashboard host is dynamic
// (LAN .local / .home / IP); the worst a forged postMessage can do
// here is open a different conversation.
window.addEventListener('message', (ev) => {
  const m = ev && ev.data;
  if (!m || typeof m !== 'object') return;
  if (m.type === 'open_conversation' && m.cid) {
    loadConversation(m.cid);
  }
  if (m.type === 'set_language' && m.lang) {
    setLanguage(m.lang);
  }
});

// Apply default language (JP) and any localStorage override on first load.
// The dashboard parent will postMessage 'set_language' shortly after the
// iframe loads to override with its own VLLang choice.
try {
  const stored = localStorage.getItem('vlabor_agent.lang');
  if (stored && I18N[stored]) curLang = stored;
} catch (_) {}
applyI18n();

// =========================================================================
// Settings modal — API keys (Anthropic + OpenAI), provider/model, voice
// =========================================================================

const settingsBtn = document.getElementById('settingsBtn');
const settingsBackdrop = document.getElementById('settingsBackdrop');
let _currentSettings = null;
let _keyStatus = { anthropic: false, openai: false };

function openSettings() {
  settingsBackdrop.dataset.open = '1';
  refreshSettingsForm();
}
function closeSettings() {
  settingsBackdrop.dataset.open = '0';
}
settingsBtn.addEventListener('click', openSettings);
settingsBackdrop.addEventListener('click', (e) => {
  if (e.target === settingsBackdrop) closeSettings();
});
document.getElementById('settingsClose').addEventListener('click', closeSettings);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && settingsBackdrop.dataset.open === '1') {
    closeSettings();
  }
});

async function refreshSettingsForm() {
  // Pull latest from server so a key set elsewhere shows up.
  try {
    const [ks, ss] = await Promise.all([
      fetch('/api/keys/status').then(r => r.json()),
      fetch('/api/settings').then(r => r.json()),
    ]);
    _keyStatus = ks.keys || {};
    _currentSettings = ss.settings || {};
  } catch (e) {
    _currentSettings = _currentSettings || {};
  }
  document.getElementById('keyStatusAnthropic').dataset.set = _keyStatus.anthropic ? '1' : '0';
  document.getElementById('keyStatusAnthropic').textContent =
    _keyStatus.anthropic ? '設定済み' : '未設定';
  document.getElementById('keyStatusOpenai').dataset.set = _keyStatus.openai ? '1' : '0';
  document.getElementById('keyStatusOpenai').textContent =
    _keyStatus.openai ? '設定済み' : '未設定';
  // Settings form fields
  const c = _currentSettings.chat || {};
  const v = _currentSettings.voice || {};
  document.getElementById('chatProvider').value = c.provider || 'anthropic';
  document.getElementById('chatModel').value = c.model || '';
  document.getElementById('ttsVoice').value = v.tts_voice || 'alloy';
  document.getElementById('ttsSpeed').value = v.tts_speed || 1.0;
  document.getElementById('sttLang').value = v.stt_lang || 'ja';
  document.getElementById('silenceMs').value = v.silence_ms || 800;
  document.getElementById('energyDb').value = v.energy_db || -45;
  document.getElementById('bargeIn').checked = !!v.barge_in;
  document.getElementById('notifyEnabled').checked = !!v.notify_enabled;
  document.getElementById('notifyDiagnose').checked = !!v.notify_diagnose;
  document.getElementById('notifySeverity').value = v.notify_severity_min || 'critical';
  // Clear key inputs (we never round-trip secrets)
  document.getElementById('keyAnthropic').value = '';
  document.getElementById('keyOpenai').value = '';
  // Layout (panel visibility) — read live from current DOM classes
  // rather than localStorage so it reflects whatever's on screen now.
  document.getElementById('showLeftPane').checked =
    !layout.classList.contains('collapse-left');
  document.getElementById('showRightPane').checked =
    !layout.classList.contains('collapse-right');
}

async function saveKey(provider, value) {
  const resp = await fetch('/api/keys', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ provider, value }),
  });
  return resp.ok;
}

async function saveSettings() {
  // 1. keys (only POST when a value is in the input)
  const ka = document.getElementById('keyAnthropic').value.trim();
  const ko = document.getElementById('keyOpenai').value.trim();
  if (ka) await saveKey('anthropic', ka);
  if (ko) await saveKey('openai', ko);

  // 2. preferences
  const partial = {
    chat: {
      provider: document.getElementById('chatProvider').value,
      model: document.getElementById('chatModel').value.trim(),
    },
    voice: {
      tts_voice: document.getElementById('ttsVoice').value,
      tts_speed: parseFloat(document.getElementById('ttsSpeed').value) || 1.0,
      stt_lang: document.getElementById('sttLang').value.trim() || 'ja',
      silence_ms: parseInt(document.getElementById('silenceMs').value) || 800,
      energy_db: parseFloat(document.getElementById('energyDb').value) || -45,
      barge_in: document.getElementById('bargeIn').checked,
      notify_enabled: document.getElementById('notifyEnabled').checked,
      notify_diagnose: document.getElementById('notifyDiagnose').checked,
      notify_severity_min: document.getElementById('notifySeverity').value,
    },
  };
  await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(partial),
  });
  // Layout — apply immediately; persisted to localStorage by setPaneVisibility.
  setPaneVisibility('left', document.getElementById('showLeftPane').checked);
  setPaneVisibility('right', document.getElementById('showRightPane').checked);
  await refreshSettingsForm();
  closeSettings();
}
document.getElementById('settingsSave').addEventListener('click', saveSettings);

// Show / hide secret inputs
for (const t of document.querySelectorAll('.show-toggle')) {
  t.addEventListener('click', () => {
    const target = document.getElementById(t.dataset.target);
    if (!target) return;
    if (target.type === 'password') {
      target.type = 'text'; t.textContent = '隠す';
    } else {
      target.type = 'password'; t.textContent = '表示';
    }
  });
}

// =========================================================================
// Voice mode — continuous mic + VAD + Whisper STT + auto TTS reply
//
// UI is hidden for now (the operator's main browser sits on an mDNS
// hostname which Chrome refuses to expose mic to without an explicit
// flag). The plumbing stays compiled in so a future build that adds
// HTTPS / a flagged origin only needs the buttons re-enabled in the
// header. Every DOM lookup is guarded so a missing button doesn't
// crash the rest of the dev page.
// =========================================================================

const voiceBtn = document.getElementById('voiceBtn');
const voiceStatus = document.getElementById('voiceStatus');
const voiceStatusLabel = document.getElementById('voiceStatusLabel');
const voiceWave = document.getElementById('voiceWave');
const VOICE_UI_PRESENT = !!voiceBtn;
const VOICE_MODE_KEY = 'vlabor_agent.voice_mode';

let voiceState = 'off';
// 'off' | 'idle' | 'recording' | 'stt_busy' | 'chatting' | 'tts_busy'
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let audioCtx = null;
let analyser = null;
let analyserData = null;
let vadRaf = 0;
let speechStartTs = 0;
let lastEnergyAboveTs = 0;
let lastUserInputMode = 'text';   // tracks the most recent user turn
let currentTtsAudio = null;
const announceDedupe = new Map();  // text → last ts (ms)

function setVoiceState(next) {
  voiceState = next;
  if (!VOICE_UI_PRESENT) return;
  if (next === 'off') {
    voiceBtn.dataset.state = 'off';
    voiceStatus.dataset.state = 'idle';
    return;
  }
  voiceBtn.dataset.state = 'on';
  voiceStatus.dataset.state = next;
  voiceStatusLabel.textContent = ({
    idle: '待機中 — 話してください',
    recording: '🔴 録音中',
    stt_busy: '💭 認識中',
    chatting: '💬 思考中',
    tts_busy: '🔊 発話中',
  })[next] || next;
}

async function enableVoiceMode() {
  if (voiceState !== 'off') return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // navigator.mediaDevices is undefined outside secure contexts
    // (https / localhost). Tell the operator how to fix instead of
    // showing the cryptic "reading 'getUserMedia' of undefined" stack.
    alert(
      '音声モードはブラウザの secure context が必要です。\n\n' +
      '次のいずれかでアクセスし直してください:\n' +
      '  • http://localhost:8887/   (同じ PC から操作する場合)\n' +
      '  • http://127.0.0.1:8887/   (同上)\n' +
      '  • chrome://flags の "Insecure origins treated as secure"\n' +
      '    に ' + window.location.origin + ' を追加して再起動 (LAN 越し)\n' +
      '  • HTTPS を有効化\n\n' +
      '現在の URL: ' + window.location.origin
    );
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    alert('マイクアクセス拒否されました: ' + e.message);
    return;
  }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(mediaStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  analyserData = new Float32Array(analyser.fftSize);
  src.connect(analyser);
  setVoiceState('idle');
  localStorage.setItem(VOICE_MODE_KEY, '1');
  startVadLoop();
}

function disableVoiceMode() {
  if (voiceState === 'off') return;
  cancelAnimationFrame(vadRaf);
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try { mediaRecorder.stop(); } catch (_) {}
  }
  if (mediaStream) {
    for (const t of mediaStream.getTracks()) t.stop();
  }
  if (audioCtx) audioCtx.close().catch(() => {});
  mediaStream = mediaRecorder = audioCtx = analyser = analyserData = null;
  recordedChunks = [];
  setVoiceState('off');
  localStorage.setItem(VOICE_MODE_KEY, '0');
}

if (VOICE_UI_PRESENT) voiceBtn.addEventListener('click', () => {
  if (voiceState === 'off') enableVoiceMode();
  else disableVoiceMode();
});

// Restore voice mode preference on load (waits for a click — browsers
// require a user gesture before getUserMedia, so we just style the
// button as if it should be on and let the user re-click to grant).

function startVadLoop() {
  const cv = voiceWave;
  const ctx = cv.getContext('2d');
  function loop() {
    if (!analyser) return;
    analyser.getFloatTimeDomainData(analyserData);
    let sumSq = 0;
    for (let i = 0; i < analyserData.length; i++) {
      sumSq += analyserData[i] * analyserData[i];
    }
    const rms = Math.sqrt(sumSq / analyserData.length);
    const db = 20 * Math.log10(Math.max(1e-7, rms));
    drawWave(cv, ctx, analyserData, db);

    const settings = (_currentSettings || {}).voice || {};
    const threshold = settings.energy_db ?? -45;
    const silenceMs = settings.silence_ms ?? 800;
    const now = performance.now();

    if (voiceState === 'idle' || voiceState === 'tts_busy') {
      if (db > threshold) {
        if (voiceState === 'tts_busy' && settings.barge_in) {
          stopTts();
        }
        if (voiceState === 'idle') startRecording();
      }
    } else if (voiceState === 'recording') {
      if (db > threshold) {
        lastEnergyAboveTs = now;
      } else if (now - lastEnergyAboveTs > silenceMs) {
        stopRecordingAndSend();
      }
    }
    vadRaf = requestAnimationFrame(loop);
  }
  vadRaf = requestAnimationFrame(loop);
}

function drawWave(cv, ctx, data, db) {
  const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = (voiceState === 'recording') ? '#ff5d8f'
                  : (voiceState === 'tts_busy')  ? '#56d394'
                  : '#7dd3fc';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  const step = data.length / w;
  for (let x = 0; x < w; x++) {
    const v = data[Math.floor(x * step)] || 0;
    const y = h / 2 + v * (h / 2);
    if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function startRecording() {
  if (!mediaStream) return;
  recordedChunks = [];
  const mr = new MediaRecorder(mediaStream, { mimeType: 'audio/webm;codecs=opus' });
  mr.addEventListener('dataavailable', (e) => {
    if (e.data && e.data.size > 0) recordedChunks.push(e.data);
  });
  mr.addEventListener('stop', onRecordingStopped);
  mr.start();
  mediaRecorder = mr;
  speechStartTs = performance.now();
  lastEnergyAboveTs = performance.now();
  setVoiceState('recording');
}

function stopRecordingAndSend() {
  if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
  const dur = performance.now() - speechStartTs;
  if (dur < 250) {
    // Drop ultra-short blips — typically a cough or background bump.
    try { mediaRecorder.stop(); } catch (_) {}
    recordedChunks = [];
    setVoiceState('idle');
    return;
  }
  try { mediaRecorder.stop(); } catch (_) {}
}

async function onRecordingStopped() {
  const blob = new Blob(recordedChunks, { type: 'audio/webm' });
  recordedChunks = [];
  if (blob.size < 800) {
    setVoiceState('idle');
    return;
  }
  setVoiceState('stt_busy');
  let text = '';
  try {
    const fd = new FormData();
    fd.append('audio', blob, 'speech.webm');
    const lang = (_currentSettings?.voice?.stt_lang) || 'ja';
    const resp = await fetch('/api/stt?lang=' + encodeURIComponent(lang),
                             { method: 'POST', body: fd });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || 'stt failed');
    text = (data.text || '').trim();
  } catch (e) {
    setVoiceState('idle');
    appendVoiceError('音声認識失敗: ' + e.message);
    return;
  }
  if (!text) { setVoiceState('idle'); return; }
  // Send through chat WS as a voice-tagged user message.
  lastUserInputMode = 'voice';
  setVoiceState('chatting');
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    appendVoiceError('WebSocket 切断中 — テキストとして表示');
    addUser(text);
    setVoiceState('idle');
    return;
  }
  inflight = true;
  sendBtn.disabled = true;
  inflightStartedAt = Date.now();
  lastWsMessageAt = 0;
  addUser(text);
  ws.send(JSON.stringify({
    type: 'user_message',
    text,
    history,
    conversation_id: conversationId,
    metadata: { input_mode: 'voice' },
  }));
}

function appendVoiceError(msg) {
  const div = document.createElement('div');
  div.className = 'tool';
  div.dataset.state = 'error';
  div.textContent = '🎤 ' + msg;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// Override submit() to mark text-mode turns so TTS doesn't fire after them.
const _origSubmit = submit;
submit = function() {
  lastUserInputMode = 'text';
  return _origSubmit();
};
sendBtn.removeEventListener('click', _origSubmit);
sendBtn.addEventListener('click', submit);

// Hook into WS message stream — when a chat turn ends and the prior
// user input was voice, fetch TTS for the assistant's final text.
let _ttsBuffer = '';
const _origOnMessage = ws ? null : null; // placeholder — patch in connect()

// Attach a non-disruptive 'message' listener for voice events.
// The original chat handler is registered via addEventListener too —
// we add a parallel one so both fire. Wrap connect() so reconnects
// re-attach our listener on the new socket.
function attachVoiceListener(socket) {
  if (!socket) return;
  socket.addEventListener('message', (ev) => {
    let parsed = null;
    try { parsed = JSON.parse(ev.data); } catch (_) {}
    if (parsed) handleVoiceWsEvent(parsed);
  });
}
const _origConnect = connect;
connect = function() {
  _origConnect();
  attachVoiceListener(ws);
};
// Also attach on the WS that the initial connect() at boot already
// created (this script runs after that boot line).
attachVoiceListener(ws);

function handleVoiceWsEvent(m) {
  if (!m || !m.type) return;
  if (m.type === 'voice_announce') {
    handleVoiceAnnounce(m);
    return;
  }
  if (m.type === 'assistant_text') {
    _ttsBuffer += (m.text || '');
  } else if (m.type === 'done') {
    const text = _ttsBuffer.trim();
    _ttsBuffer = '';
    if (text && lastUserInputMode === 'voice' && voiceState !== 'off') {
      playTtsForReply(text);
    } else if (voiceState === 'chatting') {
      setVoiceState('idle');
    }
    lastUserInputMode = 'text';   // reset for next turn
  } else if (m.type === 'error') {
    if (voiceState === 'chatting' || voiceState === 'recording') {
      setVoiceState('idle');
    }
  }
}

async function playTtsForReply(text) {
  setVoiceState('tts_busy');
  try {
    await playTtsBlob(text);
  } catch (e) {
    appendVoiceError('読み上げ失敗: ' + e.message);
  }
  if (voiceState === 'tts_busy') setVoiceState('idle');
}

async function playTtsBlob(text, voiceOverride, speedOverride) {
  const body = { text };
  if (voiceOverride) body.voice = voiceOverride;
  if (speedOverride) body.speed = speedOverride;
  const resp = await fetch('/api/tts', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || ('http ' + resp.status));
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  return new Promise((resolve, reject) => {
    const audio = new Audio(url);
    currentTtsAudio = audio;
    audio.addEventListener('ended', () => {
      URL.revokeObjectURL(url);
      currentTtsAudio = null;
      resolve();
    });
    audio.addEventListener('error', (e) => {
      URL.revokeObjectURL(url);
      currentTtsAudio = null;
      reject(new Error('audio playback error'));
    });
    audio.play().catch(reject);
  });
}

function stopTts() {
  if (currentTtsAudio) {
    try { currentTtsAudio.pause(); } catch (_) {}
    currentTtsAudio = null;
  }
}

function handleVoiceAnnounce(m) {
  const settings = (_currentSettings && _currentSettings.voice) || {};
  if (settings.notify_enabled === false) return;
  const sevOrder = { info: 0, warning: 1, critical: 2 };
  const min = sevOrder[settings.notify_severity_min || 'critical'] ?? 2;
  const cur = sevOrder[m.severity || 'info'] ?? 0;
  if (cur < min) return;
  const window = (settings.notify_dedupe_window_sec ?? 60) * 1000;
  const now = Date.now();
  const last = announceDedupe.get(m.text) || 0;
  if (now - last < window) return;
  announceDedupe.set(m.text, now);
  // Fire-and-forget — don't block VAD even if TTS takes a sec.
  playTtsBlob(m.text).catch(e => appendVoiceError('通知音声失敗: ' + e.message));
  // Also drop a note in the chat log so the operator has a textual
  // record of what was announced, with severity-coded styling.
  const div = document.createElement('div');
  div.className = 'tool';
  div.dataset.state = m.severity === 'critical' ? 'error' : 'ok';
  div.innerHTML = `📢 <strong>${escapeHtml(m.severity)}</strong> · ${escapeHtml(m.source || '')} — ${escapeHtml(m.text)}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

// Initial settings fetch so the form is ready before first open.
refreshSettingsForm();
</script>
</body>
</html>
"""
