"""Tiny HTML page served at ``/`` so an operator can poke the WS chat
without spinning up the full web_ui yet.

Phase 0 only: this page goes away (or becomes a redirect to web_ui)
once the real UI ships.
"""

from __future__ import annotations

DEV_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>vlabor_agent chat (dev)</title>
  <style>
    body { font-family: ui-monospace, Menlo, monospace; background: #0d1117; color: #c9d1d9;
           margin: 0; padding: 16px; }
    h1 { font-size: 14px; color: #58a6ff; margin: 0 0 12px; }
    #log { white-space: pre-wrap; height: 60vh; overflow-y: auto; padding: 8px;
           background: #161b22; border: 1px solid #30363d; border-radius: 4px; font-size: 12px; }
    .e { color: #c9d1d9; }
    .e.user { color: #79c0ff; }
    .e.assistant { color: #d2a8ff; }
    .e.tool_use { color: #ffa657; }
    .e.tool_result { color: #7ee787; }
    .e.error { color: #ff7b72; }
    .e.done { color: #8b949e; }
    form { margin-top: 12px; display: flex; gap: 8px; }
    textarea { flex: 1; padding: 6px; font: inherit; background: #161b22; color: inherit;
               border: 1px solid #30363d; border-radius: 4px; }
    button { padding: 6px 14px; background: #238636; color: #fff; border: 0; border-radius: 4px;
             cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .meta { font-size: 11px; color: #8b949e; margin-bottom: 8px; }
  </style>
</head>
<body>
  <h1>vlabor_agent chat (dev page)</h1>
  <div class="meta">
    Backend dev surface. Connects to <code>ws(s)://&lt;host&gt;/chat</code>.
    History is held in this page; reload = fresh chat.
  </div>
  <div id="log"></div>
  <form id="form">
    <textarea id="input" rows="2" placeholder="Ask the agent something — e.g. 'show me the arm joint angles'"></textarea>
    <button id="send" type="submit">Send</button>
  </form>

<script>
const log = document.getElementById('log');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send');
const form = document.getElementById('form');
const history = [];
let ws = null;
let inflight = false;

function append(kind, text) {
  const div = document.createElement('div');
  div.className = 'e ' + kind;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/chat`);
  ws.addEventListener('open', () => append('done', '[connected]'));
  ws.addEventListener('close', () => {
    append('done', '[disconnected — reconnecting in 1s]');
    setTimeout(connect, 1000);
  });
  ws.addEventListener('error', () => append('error', '[ws error]'));
  ws.addEventListener('message', (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (_) { return; }
    if (m.type === 'assistant_text') {
      append('assistant', m.text);
    } else if (m.type === 'tool_use_start') {
      append('tool_use', `→ ${m.name}(${JSON.stringify(m.input)})`);
    } else if (m.type === 'tool_use_result') {
      const tag = m.is_error ? 'error' : 'tool_result';
      append(tag, `← ${m.name}: ${m.summary}`);
    } else if (m.type === 'done') {
      inflight = false;
      sendBtn.disabled = false;
      append('done', `[done — ${m.stop_reason}]`);
    } else if (m.type === 'error') {
      inflight = false;
      sendBtn.disabled = false;
      append('error', `! ${m.message}`);
    } else if (m.type === 'transcript') {
      // Replace history with the authoritative copy from the server.
      history.length = 0;
      for (const x of m.messages) history.push(x);
    }
  });
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = (input.value || '').trim();
  if (!text || inflight || !ws || ws.readyState !== WebSocket.OPEN) return;
  inflight = true;
  sendBtn.disabled = true;
  append('user', `> ${text}`);
  input.value = '';
  ws.send(JSON.stringify({ type: 'user_message', text, history }));
});

connect();
</script>
</body>
</html>
"""
