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

DEV_HTML = """<!doctype html>
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
      padding: 8px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      flex-shrink: 0;
    }
    header h1 { margin: 0; font-size: 14px; font-weight: 600; color: var(--accent); }
    .status { display: inline-flex; align-items: center; gap: 6px;
              font-size: 12px; color: var(--muted); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #555; }
    .dot.ok { background: #3fb950; }
    .dot.bad { background: #f85149; }
    .grow { flex: 1; }
    header code { font-size: 11px; color: var(--muted);
                  background: rgba(255,255,255,0.04); padding: 1px 6px; border-radius: 3px; }
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
        var(--col-left, 240px) 6px 1fr 6px var(--col-right, 360px);
      width: 100%;
    }
    main.collapse-left  { grid-template-columns: 0 0 1fr 6px var(--col-right, 360px); }
    main.collapse-right { grid-template-columns: var(--col-left, 240px) 6px 1fr 0 0; }
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
      border: 0; border-radius: 6px; cursor: pointer;
      font-weight: 600; font-size: 13px;
    }
    aside .new-btn:hover { filter: brightness(1.15); }
    aside .conv-list {
      flex: 1; overflow-y: auto;
      display: flex; flex-direction: column;
      padding: 0 8px 10px;
    }
    aside .conv-item {
      padding: 8px 10px; border-radius: 6px;
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
    aside .conv-del {
      position: absolute; right: 6px; top: 6px;
      background: transparent; border: 0; color: var(--muted);
      font-size: 13px; cursor: pointer; opacity: 0; transition: opacity 0.15s;
      padding: 2px 6px;
    }
    aside .conv-item:hover .conv-del { opacity: 1; }
    aside .conv-del:hover { color: #f85149; }
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
    .bubble h1, .bubble h2, .bubble h3 { margin: 12px 0 6px; line-height: 1.3; }
    .bubble h1 { font-size: 18px; }
    .bubble h2 { font-size: 16px; }
    .bubble h3 { font-size: 14px; color: var(--accent); }
    .bubble ul, .bubble ol { margin: 6px 0; padding-left: 22px; }
    .bubble li { margin: 2px 0; }
    .bubble a { color: var(--accent); text-decoration: none; border-bottom: 1px dotted; }
    .bubble a:hover { border-bottom-style: solid; }
    .bubble code {
      background: rgba(255,255,255,0.08); padding: 1px 6px;
      border-radius: 3px; font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12.5px;
    }
    .msg.user .bubble code { background: rgba(0,0,0,0.25); }
    .bubble pre {
      background: rgba(0,0,0,0.4); padding: 10px 12px;
      border-radius: 6px; overflow-x: auto;
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
      border-radius: 6px; display: block; margin: 6px 0;
      border: 1px solid var(--border);
    }

    .tool {
      align-self: flex-start;
      background: var(--tool); border: 1px solid var(--tool-border);
      border-radius: 8px; padding: 8px 12px;
      max-width: 78%; margin-left: 38px;
      font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12.5px;
      color: #ffd6a0;
    }
    .tool[data-state="success"] {
      background: var(--tool-ok); border-color: var(--tool-ok-border); color: #c4e8d2;
    }
    .tool[data-state="error"] {
      background: var(--error); border-color: var(--error-border); color: #ffd1d1;
    }
    .tool summary { cursor: pointer; outline: none; user-select: none; }
    .tool summary::-webkit-details-marker { color: var(--muted); }
    .tool .body { margin-top: 6px; padding-top: 6px;
                  border-top: 1px dashed rgba(255,255,255,0.1); }
    .tool pre {
      margin: 0; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;
      font-size: 11.5px;
    }
    .tool .label { font-size: 10.5px; opacity: 0.6; margin-top: 4px; }
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
      font: inherit; padding: 6px 8px;
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
      flex: 1; gap: 6px; color: var(--muted);
    }
    .empty .big { font-size: 16px; color: var(--text); }
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
    .pane-card.live { flex: 1.2; min-height: 200px; }
    .pane-card.bt   { flex: 1; min-height: 180px; }
    .pane-body { flex: 1; min-height: 0; position: relative; }
    .pane-body iframe {
      width: 100%; height: 100%; border: 0;
      background: #05080c;
      display: block;
    }
    .pane-empty {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      height: 100%; gap: 6px; color: var(--muted); font-size: 12px;
      padding: 16px; text-align: center;
    }
    .bt-canvas-wrap {
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
    }

    @media (max-width: 1100px) {
      main { grid-template-columns: var(--col-left, 220px) 1fr 0 !important; }
      .right-pane { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>vlabor_agent</h1>
    <span class="status">
      <span id="wsDot" class="dot"></span>
      <span id="wsLabel">connecting</span>
    </span>
    <span class="grow"></span>
    <code id="serverHost">…</code>
    <button class="icon-btn" id="toggleLeft" title="Toggle history sidebar">📚</button>
    <button class="icon-btn" id="toggleRight" title="Toggle Live View / BT pane">🔍</button>
    <button class="icon-btn" id="resetBtn" title="New chat (current saved)">↺ Reset</button>
  </header>
  <main id="layout">
    <aside>
      <button class="new-btn" id="newChatBtn" type="button">+ New chat</button>
      <div class="conv-list" id="convList">
        <div class="conv-empty">no conversations yet</div>
      </div>
    </aside>
    <div class="resizer" id="resizerLeft" data-edge="left" title="Drag to resize history pane"></div>

    <section class="chat-panel">
      <div id="log">
        <div class="empty" id="emptyState">
          <div class="big">Ask the agent anything</div>
          <div class="small">Tools come from the configured MCP servers. Markdown, tables, and images supported.</div>
        </div>
      </div>
      <div class="composer">
        <textarea id="input" rows="1"
                  placeholder="Type a message — Enter to send, Shift+Enter for newline"></textarea>
        <button id="send" class="send-btn" type="button">Send</button>
      </div>
    </section>
    <div class="resizer" id="resizerRight" data-edge="right" title="Drag to resize Live View / BT pane"></div>

    <div class="right-pane">
      <div class="pane-card live">
        <div class="pane-header">
          Live View
          <span class="pane-host" id="liveHost">—</span>
          <span class="grow"></span>
          <button class="icon-btn" id="liveReload" title="Reload iframe">↻</button>
        </div>
        <div class="pane-body">
          <iframe id="liveFrame" title="Live View" loading="lazy"></iframe>
          <div class="pane-empty" id="liveEmpty" style="display:none;">
            scene_viewer not reachable<br>
            <span style="font-size:11px;">expected at <code id="liveUrl">—</code></span>
          </div>
        </div>
      </div>
      <div class="pane-card bt">
        <div class="pane-header">Behavior Tree
          <span class="pane-host">(placeholder)</span>
        </div>
        <div class="pane-body">
          <div class="pane-empty">
            BT runtime not wired yet (Phase 1).<br>
            <span style="font-size:11px;">live tree view + node status will land here.</span>
          </div>
        </div>
      </div>
    </div>
  </main>

<script>
const log = document.getElementById('log');
const empty = document.getElementById('emptyState');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const wsDot = document.getElementById('wsDot');
const wsLabel = document.getElementById('wsLabel');
const resetBtn = document.getElementById('resetBtn');
const layout = document.getElementById('layout');
const toggleLeft = document.getElementById('toggleLeft');
const toggleRight = document.getElementById('toggleRight');
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
  if (state === 'open') { wsDot.classList.add('ok'); wsLabel.textContent = 'connected'; }
  else if (state === 'closed') { wsDot.classList.add('bad'); wsLabel.textContent = 'disconnected'; }
  else { wsLabel.textContent = state; }
}

// --- WS --------------------------------------------------------------------

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/chat`);
  ws.addEventListener('open', () => setWsStatus('open'));
  ws.addEventListener('close', () => { setWsStatus('closed'); setTimeout(connect, 2000); });
  ws.addEventListener('error', () => setWsStatus('error'));
  ws.addEventListener('message', (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === 'assistant_text') appendAssistantText(m.text);
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
    convList.innerHTML = '<div class="conv-empty">no conversations yet</div>';
    return;
  }
  for (const c of items) {
    const row = document.createElement('div');
    row.className = 'conv-item' + (c.id === conversationId ? ' active' : '');
    row.dataset.id = c.id;
    row.innerHTML = `
      <span class="conv-title">${escapeHtml(c.title || '(untitled)')}</span>
      <span class="conv-meta">${escapeHtml(c.updated_at || '')} · ${c.message_count} msg</span>
      <button class="conv-del" title="Delete">✕</button>`;
    row.addEventListener('click', (e) => {
      if (e.target.classList.contains('conv-del')) return;
      loadConversation(c.id);
    });
    row.querySelector('.conv-del').addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!confirm('Delete this conversation?')) return;
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
toggleLeft.addEventListener('click', () => { layout.classList.toggle('collapse-left'); persistLayoutPrefs(); });
toggleRight.addEventListener('click', () => { layout.classList.toggle('collapse-right'); persistLayoutPrefs(); });

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

// --- boot ------------------------------------------------------------------

connect();
refreshConversationList();
input.focus();
</script>
</body>
</html>
"""
