"""Tiny self-contained chat UI served at ``/``.

Phase 0 dev surface — replaced once the real ``web_ui`` ships. Kept
deliberately single-file so the chat backend stays useful even
without a separate frontend build step.
"""

from __future__ import annotations

DEV_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>vlabor_agent</title>
  <style>
    :root {
      --bg: #0d1117;
      --panel: #161b22;
      --panel-soft: #1c232c;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #58a6ff;
      --user: #1f6feb;
      --assistant: #2a2f3a;
      --tool: #3f2f1a;
      --tool-border: #6c4f1f;
      --error: #862a2a;
      --error-border: #a94747;
      --success: #1a3a25;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans",
                   "Noto Sans JP", system-ui, sans-serif;
      font-size: 14px;
      display: flex; flex-direction: column;
    }
    header {
      display: flex; align-items: center; gap: 12px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }
    header h1 { margin: 0; font-size: 14px; font-weight: 600; color: var(--accent); }
    .status {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 12px; color: var(--muted);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #555; }
    .dot.ok { background: #3fb950; }
    .dot.bad { background: #f85149; }
    .grow { flex: 1; }
    .icon-btn {
      background: transparent; border: 1px solid var(--border);
      color: var(--muted); padding: 4px 10px; border-radius: 4px;
      cursor: pointer; font-size: 12px; transition: all 0.15s;
    }
    .icon-btn:hover { color: var(--accent); border-color: var(--accent); }

    main {
      flex: 1; min-height: 0;
      display: flex; flex-direction: column;
      max-width: 880px; width: 100%; margin: 0 auto;
      padding: 16px;
      gap: 12px;
    }
    #log {
      flex: 1; overflow-y: auto;
      display: flex; flex-direction: column; gap: 12px;
      padding-right: 4px;
    }
    .msg { display: flex; gap: 10px; max-width: 100%; }
    .msg.user { justify-content: flex-end; }
    .avatar {
      width: 28px; height: 28px; border-radius: 50%;
      flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; font-weight: 600;
    }
    .avatar.assistant { background: rgba(88,166,255,0.15); color: var(--accent); }
    .avatar.user { background: rgba(63,185,80,0.18); color: #3fb950; }

    .bubble {
      max-width: 75%;
      padding: 10px 14px; border-radius: 10px;
      line-height: 1.55;
      word-wrap: break-word; overflow-wrap: anywhere;
      white-space: pre-wrap;
    }
    .msg.assistant .bubble { background: var(--assistant); }
    .msg.user .bubble {
      background: var(--user); color: #fff;
      border-bottom-right-radius: 2px;
    }
    .msg.assistant .bubble { border-bottom-left-radius: 2px; }
    .bubble code {
      background: rgba(255,255,255,0.08); padding: 1px 6px;
      border-radius: 3px; font-family: ui-monospace, monospace; font-size: 12.5px;
    }
    .bubble pre {
      background: rgba(0,0,0,0.35); padding: 10px 12px;
      border-radius: 6px; overflow-x: auto;
      font-family: ui-monospace, monospace; font-size: 12px;
      margin: 6px 0;
    }
    .bubble pre code { background: transparent; padding: 0; }

    /* Tool calls collapse the noisy detail under a one-line summary. */
    .tool {
      align-self: flex-start;
      background: var(--tool); border: 1px solid var(--tool-border);
      border-radius: 8px; padding: 8px 12px;
      max-width: 75%; margin-left: 38px;
      font-family: ui-monospace, monospace; font-size: 12.5px;
      color: #ffd6a0;
    }
    .tool.error { background: var(--error); border-color: var(--error-border); color: #ffd1d1; }
    .tool.success { color: #c4e8d2; }
    .tool summary { cursor: pointer; outline: none; user-select: none; }
    .tool summary::-webkit-details-marker { color: var(--muted); }
    .tool .body { margin-top: 6px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.1); }
    .tool pre {
      margin: 0; white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;
      font-size: 11.5px; color: #ffe9c2;
    }
    .tool.error pre { color: #ffd1d1; }
    .tool.success pre { color: #c4e8d2; }

    .system {
      align-self: center;
      font-size: 11px; color: var(--muted);
      padding: 4px 10px; background: rgba(255,255,255,0.04);
      border-radius: 999px;
    }

    /* Composer */
    .composer {
      display: flex; gap: 8px; align-items: flex-end;
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 10px; padding: 8px;
    }
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
      border: 0; border-radius: 6px;
      padding: 8px 16px; font-weight: 600;
      cursor: pointer; transition: opacity 0.15s;
      font-size: 13px;
    }
    .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .send-btn:hover:not(:disabled) { filter: brightness(1.1); }

    .hint { font-size: 11px; color: var(--muted); padding: 0 4px; }

    /* Empty state */
    .empty {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      flex: 1; gap: 8px; color: var(--muted);
    }
    .empty .big { font-size: 16px; color: var(--text); }
    .empty .small { font-size: 12px; }
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
    <button class="icon-btn" id="resetBtn" title="Clear chat (also drops history)">↺ Reset</button>
  </header>
  <main>
    <div id="log">
      <div class="empty" id="emptyState">
        <div class="big">Ask the agent anything</div>
        <div class="small">Tools available are pulled from the configured MCP servers.</div>
      </div>
    </div>
    <div class="composer">
      <textarea id="input" rows="1"
                placeholder="Type a message — Enter to send, Shift+Enter for newline"></textarea>
      <button id="send" class="send-btn" type="button">Send</button>
    </div>
    <div class="hint">Connected to <code id="serverHost">…</code> · model picked by backend</div>
  </main>

<script>
const log = document.getElementById('log');
const empty = document.getElementById('emptyState');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const wsDot = document.getElementById('wsDot');
const wsLabel = document.getElementById('wsLabel');
const resetBtn = document.getElementById('resetBtn');
document.getElementById('serverHost').textContent = location.host;

const history = [];
let ws = null;
let inflight = false;
let activeAssistantBubble = null;

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Minimal markdown: ``` fences, **bold**, *italic*, `inline`. We keep
// it small intentionally — the dev page isn't trying to compete with
// the real web_ui.
function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/```([\\s\\S]*?)```/g, (_m, body) =>
    `<pre><code>${body.replace(/^\\n/, '')}</code></pre>`);
  html = html.replace(/`([^`\\n]+?)`/g, (_m, body) => `<code>${body}</code>`);
  html = html.replace(/\\*\\*([^*\\n]+?)\\*\\*/g, '<strong>$1</strong>');
  html = html.replace(/\\*([^*\\n]+?)\\*/g, '<em>$1</em>');
  return html;
}

function clearEmpty() {
  if (empty && empty.parentNode) empty.remove();
}

function addUser(text) {
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg user';
  wrap.innerHTML = `
    <div class="bubble">${escapeHtml(text)}</div>
    <div class="avatar user">U</div>`;
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

function ensureAssistantBubble() {
  if (activeAssistantBubble) return activeAssistantBubble;
  clearEmpty();
  const wrap = document.createElement('div');
  wrap.className = 'msg assistant';
  wrap.innerHTML = `
    <div class="avatar assistant">vA</div>
    <div class="bubble"></div>`;
  log.appendChild(wrap);
  activeAssistantBubble = wrap.querySelector('.bubble');
  log.scrollTop = log.scrollHeight;
  return activeAssistantBubble;
}

function appendAssistantText(text) {
  const bubble = ensureAssistantBubble();
  // Keep raw text in a data attribute so we can re-render the whole
  // turn through markdown when the bubble grows.
  bubble.dataset.raw = (bubble.dataset.raw || '') + text;
  bubble.innerHTML = renderMarkdown(bubble.dataset.raw);
  log.scrollTop = log.scrollHeight;
}

function addToolCall(name, input, id) {
  clearEmpty();
  const tool = document.createElement('details');
  tool.className = 'tool';
  tool.id = `tool-${id}`;
  tool.open = false;
  const argText = (() => {
    try { return JSON.stringify(input, null, 2); } catch (_) { return String(input); }
  })();
  tool.innerHTML = `
    <summary>🔧 <strong>${escapeHtml(name)}</strong> <span style="opacity:0.6">running…</span></summary>
    <div class="body"><pre>${escapeHtml(argText)}</pre></div>`;
  log.appendChild(tool);
  log.scrollTop = log.scrollHeight;
}

function finishToolCall(id, name, isError, summary, content) {
  const tool = document.getElementById(`tool-${id}`);
  if (!tool) return;
  tool.classList.remove('success', 'error');
  tool.classList.add(isError ? 'error' : 'success');
  const icon = isError ? '❌' : '✓';
  const summaryText = summary || (isError ? 'failed' : 'ok');
  // Body: arg JSON (existing) + a result section.
  const argPre = tool.querySelector('.body pre');
  const argHtml = argPre ? argPre.outerHTML : '';
  const resultPre = document.createElement('pre');
  resultPre.textContent = renderResultBlocks(content);
  tool.innerHTML = `
    <summary>${icon} <strong>${escapeHtml(name)}</strong>
      <span style="opacity:0.7"> — ${escapeHtml(summaryText)}</span></summary>
    <div class="body">${argHtml}<div style="margin-top:6px;font-size:11px;opacity:0.7;">result:</div>${resultPre.outerHTML}</div>`;
  log.scrollTop = log.scrollHeight;
}

function renderResultBlocks(blocks) {
  if (!Array.isArray(blocks) || !blocks.length) return '(no content)';
  const parts = [];
  for (const b of blocks) {
    if (b.type === 'text') parts.push(b.text || '');
    else if (b.type === 'image') parts.push('[image returned]');
    else parts.push(JSON.stringify(b));
  }
  return parts.join('\\n');
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

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/chat`);
  ws.addEventListener('open', () => setWsStatus('open'));
  ws.addEventListener('close', () => {
    setWsStatus('closed');
    // Backoff so a server-side error doesn't trigger a tight loop.
    setTimeout(connect, 2000);
  });
  ws.addEventListener('error', () => setWsStatus('error'));
  ws.addEventListener('message', (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === 'assistant_text') {
      appendAssistantText(m.text);
    } else if (m.type === 'tool_use_start') {
      activeAssistantBubble = null;  // next assistant text starts a new bubble
      addToolCall(m.name, m.input, m.id);
    } else if (m.type === 'tool_use_result') {
      finishToolCall(m.id, m.name, m.is_error, m.summary, m.content);
    } else if (m.type === 'done') {
      activeAssistantBubble = null;
      inflight = false;
      sendBtn.disabled = false;
      if (m.stop_reason === 'no_api_key') appendSystem('(no API key — save one and resend)');
    } else if (m.type === 'error') {
      activeAssistantBubble = null;
      inflight = false;
      sendBtn.disabled = false;
      const wrap = document.createElement('details');
      wrap.className = 'tool error';
      wrap.open = true;
      wrap.innerHTML = `<summary>❌ <strong>error</strong> — ${escapeHtml(m.message || 'unknown')}</summary>`;
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
    } else if (m.type === 'transcript') {
      history.length = 0;
      for (const x of m.messages) history.push(x);
    }
  });
}

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
  ws.send(JSON.stringify({ type: 'user_message', text, history }));
}

sendBtn.addEventListener('click', submit);
input.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  submit();
});

resetBtn.addEventListener('click', () => {
  history.length = 0;
  log.innerHTML = '';
  log.appendChild(empty);
  appendSystem('chat cleared');
});

connect();
input.focus();
</script>
</body>
</html>
"""
