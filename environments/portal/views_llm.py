"""The candidate Gemini page.

Two tabs in one full-height app shell:
  * Chat — Gemini-style playground: conversation sidebar (server-side history),
    streaming replies (NDJSON from /api/llm/chats/<cid>/send), and a settings
    overlay for the generation params unillm forwards (temperature / top_p /
    max_tokens / stop).
  * API access — the session's own key in plain text with copy, endpoint, models,
    parameter reference, and direct-calling examples.

Client JS is vanilla and inlined. The page data rides in one JSON
bootstrap; the static JS/CSS strings below contain no server interpolation.
"""
from __future__ import annotations

import json

import theme
from theme import esc

MAX_OUTPUT_TOKENS = 8192  # unillm's UNILLM_MAX_OUTPUT_TOKENS ceiling

_CSS = """
main.full { min-height: 0; }
.llm-shell { display: flex; flex: 1; min-height: 0; width: 100%; }
.chat-side { width: 264px; flex: none; display: flex; flex-direction: column;
  border-right: 1px solid var(--border-muted); background: var(--bg-subtle); }
.chat-side .side-top { padding: 12px; }
.chat-list { flex: 1; overflow-y: auto; padding: 0 8px 12px; }
.chat-item { display: flex; align-items: center; gap: 4px; border-radius: 6px;
  color: var(--fg); font-size: 13px; }
.chat-item > a { flex: 1; min-width: 0; padding: 6px 8px; color: inherit;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.chat-item > a:hover { text-decoration: none; }
.chat-item:hover { background: var(--btn-hover); }
.chat-item.current { background: var(--accent-subtle); }
.chat-item .del { visibility: hidden; border: 0; background: none; cursor: pointer;
  color: var(--fg-muted); padding: 4px 6px; border-radius: 4px; font-size: 12px; }
.chat-item:hover .del { visibility: visible; }
.chat-item .del:hover { color: var(--danger); }

.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.chat-topbar { display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 0 16px; border-bottom: 1px solid var(--border-muted); }
.chat-topbar .underline-nav { border: 0; padding: 0; background: transparent; }
.chat-topbar .underline-nav a { cursor: pointer; }

.pane { flex: 1; min-height: 0; display: none; }
.pane.current { display: flex; flex-direction: column; }
#pane-api.current { display: block; overflow-y: auto; }
#pane-api .api-inner { max-width: 860px; margin: 0 auto; padding: 24px 16px 48px; }

#thread { flex: 1; overflow-y: auto; }
#thread .thread-inner { max-width: 760px; margin: 0 auto; padding: 24px 16px; }
.hero { text-align: center; margin-top: 14vh; color: var(--fg-muted); }
.hero svg { width: 44px; height: 44px; }
.hero p { font-size: 18px; margin: 12px 0 0; }

.msg { margin: 0 0 20px; display: flex; gap: 12px; }
.msg-user { justify-content: flex-end; }
.msg-user .bubble { background: var(--bg-subtle); border: 1px solid var(--border-muted);
  border-radius: 12px 12px 2px 12px; padding: 8px 14px; max-width: 85%;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.msg-assistant .avatar { flex: none; width: 22px; height: 22px; margin-top: 2px; }
.msg-assistant .body { min-width: 0; flex: 1; font-size: 14px; line-height: 1.6; }
.msg-assistant .body.pending::after { content: '●'; color: var(--accent);
  animation: pulse 1s infinite; margin-left: 2px; font-size: 10px; }
@keyframes pulse { 50% { opacity: .2; } }
.msg .md-mini p { margin: 8px 0; } .msg .md-mini > :first-child { margin-top: 0; }
.msg .md-mini pre { background: var(--bg-inset); border: 1px solid var(--border-muted);
  border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12.5px; margin: 10px 0; }
.msg .md-mini code { background: var(--code-bg); border-radius: 4px; padding: .1em .3em;
  font-size: .88em; }
.msg .md-mini pre code { background: none; padding: 0; }
.msg .md-mini ul, .msg .md-mini ol { margin: 6px 0 6px 22px; padding: 0; }
.msg .md-mini h3, .msg .md-mini h4 { margin: 14px 0 6px; }
.msg-error { color: var(--danger); font-size: 13px; }

.composer-wrap { border-top: 1px solid var(--border-muted); background: var(--bg); }
.composer { max-width: 760px; margin: 0 auto; padding: 12px 16px 16px; }
.composer-box { display: flex; align-items: flex-end; gap: 8px;
  border: 1px solid var(--border); border-radius: 12px; padding: 8px;
  background: var(--bg); }
.composer-box:focus-within { border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring); }
.composer textarea { flex: 1; border: 0; background: none; resize: none; padding: 4px 6px;
  max-height: 200px; min-height: 24px; font: inherit; line-height: 1.5; }
.composer textarea:focus { box-shadow: none; }
.composer-meta { display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-top: 8px; }
.composer-meta select { width: auto; font-size: 12px; padding: 3px 8px; }
#send-btn { border-radius: 8px; }
#send-btn svg { width: 16px; height: 16px; }

.params-grid label { margin-top: 12px; }
.params-grid .rangerow { display: flex; align-items: center; gap: 10px; }
.params-grid .rangerow input[type=range] { flex: 1; accent-color: var(--accent); }
.params-grid .rangerow input[type=number] { width: 5.2rem; }

@media (max-width: 720px) { .chat-side { display: none; } }
"""

_JS = r"""
(function(){
  var B = window.__LLM__;
  var chats = B.chats, current = null, busy = false;
  var params = {temperature: null, top_p: null, max_tokens: null, stop: ''};

  var $ = function(id){ return document.getElementById(id); };
  var threadInner = $('thread-inner'), list = $('chat-list'), input = $('chat-input');

  function escapeHtml(s){
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  function inline(s){
    return s
      .replace(/`([^`\n]+)`/g, function(_, c){ return '<code>' + c + '</code>'; })
      .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<i>$2</i>');
  }
  function mdMini(text){
    var out = [], parts = escapeHtml(text).split(/```(?:[\w+-]*)\n?/);
    for (var i = 0; i < parts.length; i++){
      if (i % 2 === 1){ out.push('<pre><code>' + parts[i].replace(/\n$/, '') + '</code></pre>'); continue; }
      var lines = parts[i].split('\n'), buf = [], mode = null;
      function flush(){
        if (!buf.length) return;
        if (mode === 'ul') out.push('<ul><li>' + buf.join('</li><li>') + '</li></ul>');
        else if (mode === 'ol') out.push('<ol><li>' + buf.join('</li><li>') + '</li></ol>');
        else out.push('<p>' + buf.join('<br>') + '</p>');
        buf = []; mode = null;
      }
      for (var j = 0; j < lines.length; j++){
        var ln = lines[j];
        var h = ln.match(/^(#{1,4})\s+(.*)$/);
        var ul = ln.match(/^\s*[-*]\s+(.*)$/);
        var ol = ln.match(/^\s*\d+[.)]\s+(.*)$/);
        if (!ln.trim()){ flush(); }
        else if (h){ flush(); out.push('<h' + Math.min(4, h[1].length + 2) + '>' + inline(h[2]) + '</h' + Math.min(4, h[1].length + 2) + '>'); }
        else if (ul){ if (mode !== 'ul') flush(); mode = 'ul'; buf.push(inline(ul[1])); }
        else if (ol){ if (mode !== 'ol') flush(); mode = 'ol'; buf.push(inline(ol[1])); }
        else { if (mode) flush(); buf.push(inline(ln)); }
      }
      flush();
    }
    return out.join('');
  }

  // --- sidebar ---------------------------------------------------------------
  function renderSidebar(){
    list.innerHTML = '';
    chats.forEach(function(c){
      var el = document.createElement('div');
      el.className = 'chat-item' + (current && c.id === current.id ? ' current' : '');
      var a = document.createElement('a');
      a.textContent = c.title || 'New chat';
      a.title = c.title || 'New chat';
      a.addEventListener('click', function(){ selectChat(c.id); });
      var del = document.createElement('button');
      del.className = 'del'; del.textContent = '✕'; del.title = 'Delete conversation';
      del.addEventListener('click', function(ev){
        ev.stopPropagation();
        fetch('/api/llm/chats/' + c.id + '/delete', {method: 'POST'}).then(function(){
          chats = chats.filter(function(x){ return x.id !== c.id; });
          if (current && current.id === c.id){ current = null; renderThread(); }
          renderSidebar();
        });
      });
      el.appendChild(a); el.appendChild(del);
      list.appendChild(el);
    });
  }

  // --- thread ----------------------------------------------------------------
  function scrollBottom(){ var t = $('thread'); t.scrollTop = t.scrollHeight; }
  function addUserMsg(text){
    var m = document.createElement('div');
    m.className = 'msg msg-user';
    var b = document.createElement('div'); b.className = 'bubble'; b.textContent = text;
    m.appendChild(b); threadInner.appendChild(m);
  }
  function addAssistantMsg(){
    var m = document.createElement('div');
    m.className = 'msg msg-assistant';
    m.innerHTML = '<div class="avatar">' + B.spark + '</div>' +
                  '<div class="body md-mini pending"></div>';
    threadInner.appendChild(m);
    return m.querySelector('.body');
  }
  function addError(text){
    var m = document.createElement('div');
    m.className = 'msg msg-error';
    m.textContent = text;
    threadInner.appendChild(m);
  }
  function renderThread(){
    threadInner.innerHTML = '';
    if (!current || !current.messages.length){
      threadInner.innerHTML = '<div class="hero">' + B.spark +
        '<p>Ask Gemini anything</p></div>';
      return;
    }
    current.messages.forEach(function(m){
      if (m.role === 'user'){ addUserMsg(m.content); }
      else {
        var body = addAssistantMsg();
        body.classList.remove('pending');
        body.innerHTML = mdMini(m.content);
      }
    });
    scrollBottom();
  }
  function loadParams(p){
    p = p || {};
    params.temperature = (p.temperature != null) ? p.temperature : null;
    params.top_p = (p.top_p != null) ? p.top_p : null;
    params.max_tokens = (p.max_tokens != null) ? p.max_tokens : null;
    params.stop = (p.stop || []).join(', ');
  }
  function selectChat(id){
    fetch('/api/llm/chats/' + id).then(function(r){ return r.json(); }).then(function(d){
      if (!d.chat) return;
      current = d.chat;
      loadParams(current.params);
      renderSidebar(); renderThread();
    });
  }

  // --- sending ---------------------------------------------------------------
  function cleanParams(){
    var out = {};
    if (params.temperature != null && params.temperature !== '') out.temperature = +params.temperature;
    if (params.top_p != null && params.top_p !== '') out.top_p = +params.top_p;
    if (params.max_tokens != null && params.max_tokens !== '') out.max_tokens = +params.max_tokens;
    var stop = (params.stop || '').split(',').map(function(s){ return s.trim(); })
      .filter(Boolean).slice(0, 4);
    if (stop.length) out.stop = stop;
    return out;
  }
  function ensureChat(){
    if (current) return Promise.resolve(current);
    return fetch('/api/llm/chats', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({params: cleanParams()})})
      .then(function(r){ return r.json(); })
      .then(function(d){
        current = d.chat;
        chats.unshift({id: d.chat.id, title: d.chat.title});
        renderSidebar();
        return current;
      });
  }
  function send(){
    var text = input.value.trim();
    if (!text || busy) return;
    busy = true; $('send-btn').disabled = true;
    input.value = ''; autosize();
    ensureChat().then(function(chat){
      if (!current.messages) current.messages = [];
      if (!current.messages.length) threadInner.innerHTML = '';
      addUserMsg(text); scrollBottom();
      var body = addAssistantMsg(); scrollBottom();
      var acc = '';
      current.messages.push({role: 'user', content: text});
      fetch('/api/llm/chats/' + chat.id + '/send', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: $('model-select').value, content: text,
                              params: cleanParams()})
      }).then(function(r){
        if (!r.ok && !r.body) throw new Error('HTTP ' + r.status);
        var reader = r.body.getReader(), dec = new TextDecoder(), tail = '';
        function pump(){
          return reader.read().then(function(step){
            if (step.done) return finish(null);
            tail += dec.decode(step.value, {stream: true});
            var lines = tail.split('\n'); tail = lines.pop();
            lines.forEach(function(ln){
              if (!ln.trim()) return;
              var ev; try { ev = JSON.parse(ln); } catch(e){ return; }
              if (ev.delta){
                acc += ev.delta;
                body.innerHTML = mdMini(acc);
                scrollBottom();
              } else if (ev.error){ finishErr(ev.error); }
              else if (ev.done){ finish(ev.title); }
            });
            return pump();
          });
        }
        return pump();
      }).catch(function(e){ finishErr(String(e)); });
      function finish(title){
        if (!busy) return;
        busy = false; $('send-btn').disabled = false;
        body.classList.remove('pending');
        if (acc) current.messages.push({role: 'assistant', content: acc});
        if (title){
          var c = chats.find(function(x){ return x.id === current.id; });
          if (c && c.title !== title){ c.title = title; current.title = title; renderSidebar(); }
        }
        input.focus();
      }
      function finishErr(msg){
        if (!busy) return;
        busy = false; $('send-btn').disabled = false;
        body.classList.remove('pending');
        if (!acc) body.parentElement.remove();
        addError(msg); scrollBottom();
        input.focus();
      }
    });
  }

  // --- composer --------------------------------------------------------------
  function autosize(){
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', function(e){
    if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
  });
  $('send-btn').addEventListener('click', send);
  $('new-chat').addEventListener('click', function(){
    current = null; loadParams({});
    renderSidebar(); renderThread(); input.focus();
  });

  // --- tabs ------------------------------------------------------------------
  function showTab(name){
    ['chat', 'api'].forEach(function(t){
      $('pane-' + t).classList.toggle('current', t === name);
      $('tab-' + t).toggleAttribute('aria-current', t === name);
    });
  }
  $('tab-chat').addEventListener('click', function(e){ e.preventDefault(); showTab('chat'); });
  $('tab-api').addEventListener('click', function(e){ e.preventDefault(); showTab('api'); });

  // --- settings dialog -------------------------------------------------------
  var dlg = $('settings-overlay');
  function bindPair(range, num, key){
    function set(v){ params[key] = v === '' ? null : v; }
    range.addEventListener('input', function(){ num.value = range.value; set(range.value); });
    num.addEventListener('input', function(){ range.value = num.value || range.value; set(num.value); });
  }
  function openSettings(){
    $('p-temp-n').value = (params.temperature != null ? params.temperature : '');
    $('p-temp').value = params.temperature != null ? params.temperature : 1;
    $('p-topp').value = params.top_p != null ? params.top_p : 0.95;
    $('p-topp-n').value = (params.top_p != null ? params.top_p : '');
    $('p-maxtok').value = (params.max_tokens != null ? params.max_tokens : '');
    $('p-stop').value = params.stop || '';
    dlg.hidden = false;
  }
  $('settings-btn').addEventListener('click', openSettings);
  $('settings-close').addEventListener('click', function(){ dlg.hidden = true; });
  $('settings-reset').addEventListener('click', function(){
    loadParams({}); openSettings();
  });
  dlg.addEventListener('click', function(e){ if (e.target === dlg) dlg.hidden = true; });
  document.addEventListener('keydown', function(e){ if (e.key === 'Escape') dlg.hidden = true; });
  bindPair($('p-temp'), $('p-temp-n'), 'temperature');
  bindPair($('p-topp'), $('p-topp-n'), 'top_p');
  $('p-maxtok').addEventListener('input', function(){
    params.max_tokens = $('p-maxtok').value === '' ? null : +$('p-maxtok').value;
  });
  $('p-stop').addEventListener('input', function(){ params.stop = $('p-stop').value; });

  // --- boot ------------------------------------------------------------------
  renderSidebar(); renderThread();
  if (chats.length) selectChat(chats[0].id);
  input.focus();
})();
"""

_SEND_ICON = (
    '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">'
    '<path d="M.989 8 .064 2.68a1.342 1.342 0 0 1 1.85-1.462l13.402 5.744a1.13 1.13 0 0 1 '
    '0 2.076L1.913 14.782a1.343 1.343 0 0 1-1.85-1.463L.99 8Zm.603-5.288L2.38 7.25h4.87a.75.75 '
    '0 0 1 0 1.5H2.38l-.788 4.538L13.929 8Z"/></svg>'
)


def _api_pane(session, api_key):
    models = session["llm_models"] or []
    default_model = models[0] if models else "gemini-3.1-flash-lite"
    model_labels = " ".join(f'<span class="label mono">{esc(m)}</span>' for m in models)
    base = "http://localhost:8081/v1"
    if api_key:
        key_box = (f'<div class="token-box"><code>{esc(api_key)}</code>'
                   f'{theme.copy_button(api_key)}</div>'
                   f'<p class="field-hint">Valid while your session is active. Already '
                   f'exported in your workspace as <span class="mono">$OPENAI_API_KEY</span> '
                   f'(alias <span class="mono">$LLM_API_KEY</span>).</p>')
    else:
        key_box = '<p class="muted">Key unavailable — your session isn\'t active.</p>'

    py = f"""from openai import OpenAI

# OPENAI_BASE_URL and OPENAI_API_KEY are already set in your workspace.
client = OpenAI()
resp = client.chat.completions.create(
    model="{default_model}",
    messages=[{{"role": "user", "content": "Hello"}}],
    temperature=0.7,        # optional: temperature / top_p / max_tokens / stop
)
print(resp.choices[0].message.content)"""
    py_stream = f"""stream = client.chat.completions.create(
    model="{default_model}",
    messages=[{{"role": "user", "content": "Hello"}}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)"""
    curl = f"""curl {base}/chat/completions \\
  -H "Authorization: Bearer $OPENAI_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"model": "{default_model}", "messages": [{{"role": "user", "content": "Hello"}}]}}'"""

    params_rows = [
        ("temperature", "float, 0 – 2", "randomness; higher = more diverse"),
        ("top_p", "float, 0 – 1", "nucleus sampling"),
        ("max_tokens", f"int, ≤ {MAX_OUTPUT_TOKENS}", "output cap; larger values are clamped"),
        ("stop", "string or list, ≤ 4", "stop sequences"),
        ("stream", "bool", "server-sent events, OpenAI chunk format"),
    ]
    prows = "".join(f'<tr><td class="mono">{esc(k)}</td><td class="mono muted">{esc(t)}</td>'
                    f'<td class="muted">{esc(d)}</td></tr>' for k, t, d in params_rows)

    return f"""<div class="api-inner">
<div class="box">
  <div class="box-header"><h2>API key</h2></div>
  <div class="box-body">{key_box}</div>
</div>
<div class="box">
  <div class="box-header"><h2>Endpoint</h2></div>
  <div class="box-body">
    <div class="token-box"><code>{esc(base)}</code>{theme.copy_button(base)}</div>
    <p class="field-hint">OpenAI-compatible (<span class="mono">/chat/completions</span>,
      <span class="mono">/models</span>) · also set as <span class="mono">$OPENAI_BASE_URL</span>.
      Enabled models: {model_labels}</p>
  </div>
</div>
<div class="box">
  <div class="box-header"><h2>Parameters</h2></div>
  <table class="table"><thead><tr><th>Parameter</th><th>Type</th><th></th></tr></thead>
  <tbody>{prows}</tbody></table>
</div>
<div class="box">
  <div class="box-header"><h2>Direct calling</h2></div>
  <div class="box-body">
    <p class="code-label" style="margin-top:0">Python — OpenAI SDK</p>
    <pre class="code-block">{esc(py)}</pre>
    <p class="code-label">Python — streaming</p>
    <pre class="code-block">{esc(py_stream)}</pre>
    <p class="code-label">curl</p>
    <pre class="code-block">{esc(curl)}</pre>
  </div>
</div>
</div>"""


def _settings_dialog():
    return f"""
<div id="settings-overlay" class="dialog-overlay" hidden>
  <div class="dialog">
    <div class="dialog-header">Generation settings
      <button type="button" class="btn btn-sm btn-invisible" id="settings-reset">Reset</button>
    </div>
    <div class="dialog-body params-grid">
      <label for="p-temp">Temperature</label>
      <div class="rangerow">
        <input type="range" id="p-temp" min="0" max="2" step="0.05" value="1">
        <input type="number" id="p-temp-n" min="0" max="2" step="0.05" placeholder="default">
      </div>
      <label for="p-topp">Top-p</label>
      <div class="rangerow">
        <input type="range" id="p-topp" min="0" max="1" step="0.01" value="0.95">
        <input type="number" id="p-topp-n" min="0" max="1" step="0.01" placeholder="default">
      </div>
      <label for="p-maxtok">Max output tokens</label>
      <input type="number" id="p-maxtok" min="1" max="{MAX_OUTPUT_TOKENS}" placeholder="default (≤ {MAX_OUTPUT_TOKENS})">
      <label for="p-stop">Stop sequences <span class="muted" style="font-weight:400">(comma-separated, up to 4)</span></label>
      <input type="text" id="p-stop" placeholder="e.g. END, ###">
      <p class="field-hint">Applied to the next message; blank = model default. Saved with
        this conversation.</p>
    </div>
    <div class="dialog-footer">
      <button type="button" class="btn btn-primary" id="settings-close">Done</button>
    </div>
  </div>
</div>"""


def llm_page(session, chats=None, api_key=None, remaining_minutes=None):
    models = session["llm_models"] or []
    model_opts = "".join(f'<option value="{esc(m)}">{esc(m)}</option>' for m in models)
    boot = {
        "chats": [{"id": c["id"], "title": c["title"]} for c in (chats or [])],
        "models": models,
        "spark": theme.GEMINI_MARK,
    }
    boot_json = json.dumps(boot).replace("</", "<\\/")

    header_right = f'<span class="label mono">{esc(session["workspace_user"])}</span>'
    if remaining_minutes is not None:
        header_right += f'<span class="label st-active">{remaining_minutes} min left</span>'

    nav = "".join([
        theme.nav_item("/", "Home"),
        theme.nav_item("/problems", "Problems"),
        theme.nav_item("/llm", "Gemini", current=True),
    ])

    body = f"""<div class="llm-shell">
  <aside class="chat-side">
    <div class="side-top">
      <button type="button" class="btn btn-block" id="new-chat">New chat</button>
    </div>
    <div class="chat-list" id="chat-list"></div>
  </aside>
  <section class="chat-main">
    <div class="chat-topbar">
      <nav class="underline-nav">
        <a id="tab-chat" aria-current="page">Chat</a>
        <a id="tab-api">API access</a>
      </nav>
      <div class="row" style="flex-wrap:nowrap">
        <select id="model-select" title="Model">{model_opts}</select>
        <button type="button" class="btn btn-icon" id="settings-btn" title="Generation settings">
          <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0a8.2 8.2 0 0 1 .701.031C9.444.095 9.99.645 10.16 1.29l.288 1.107c.018.066.079.158.212.224.231.114.454.243.668.386.123.082.233.09.299.071l1.103-.303c.644-.176 1.392.021 1.82.63.27.385.506.792.704 1.218.315.675.111 1.422-.364 1.891l-.814.806c-.049.048-.098.147-.088.294.016.257.016.515 0 .772-.01.147.038.246.088.294l.814.806c.475.469.679 1.216.364 1.891a7.977 7.977 0 0 1-.704 1.217c-.428.61-1.176.807-1.82.63l-1.102-.302c-.067-.019-.177-.011-.3.071a5.909 5.909 0 0 1-.668.386c-.133.066-.194.158-.211.224l-.29 1.106c-.168.646-.715 1.196-1.458 1.26a8.006 8.006 0 0 1-1.402 0c-.743-.064-1.289-.614-1.458-1.26l-.289-1.106c-.018-.066-.079-.158-.212-.224a5.738 5.738 0 0 1-.668-.386c-.123-.082-.233-.09-.299-.071l-1.103.303c-.644.176-1.392-.021-1.82-.63a8.12 8.12 0 0 1-.704-1.218c-.315-.675-.111-1.422.363-1.891l.815-.806c.05-.048.098-.147.088-.294a6.214 6.214 0 0 1 0-.772c.01-.147-.038-.246-.088-.294l-.815-.806C.635 6.045.431 5.298.746 4.623a7.92 7.92 0 0 1 .704-1.217c.428-.61 1.176-.807 1.82-.63l1.102.302c.067.019.177.011.3-.071.214-.143.437-.272.668-.386.133-.066.194-.158.211-.224l.29-1.106C6.009.645 6.556.095 7.299.03 7.53.01 7.764 0 8 0Zm-.571 1.525c-.036.003-.108.036-.137.146l-.289 1.105c-.147.561-.549.967-.998 1.189-.173.086-.34.183-.5.29-.417.278-.97.423-1.529.27l-1.103-.303c-.109-.03-.175.016-.195.045-.22.312-.412.644-.573.99-.014.031-.021.11.059.19l.815.806c.411.406.562.957.53 1.456a4.709 4.709 0 0 0 0 .582c.032.499-.119 1.05-.53 1.456l-.815.806c-.081.08-.073.159-.059.19.162.346.353.677.573.989.02.03.085.076.195.046l1.102-.303c.56-.153 1.113-.008 1.53.27.161.107.328.204.501.29.447.222.85.629.997 1.189l.289 1.105c.029.109.101.143.137.146a6.6 6.6 0 0 0 1.142 0c.036-.003.108-.036.137-.146l.289-1.105c.147-.561.549-.967.998-1.189.173-.086.34-.183.5-.29.417-.278.97-.423 1.529-.27l1.103.303c.109.029.175-.016.195-.045.22-.313.411-.644.573-.99.014-.031.021-.11-.059-.19l-.815-.806c-.411-.406-.562-.957-.53-1.456a4.709 4.709 0 0 0 0-.582c-.032-.499.119-1.05.53-1.456l.815-.806c.081-.08.073-.159.059-.19a6.464 6.464 0 0 0-.573-.989c-.02-.03-.085-.076-.195-.046l-1.102.303c-.56.153-1.113.008-1.53-.27a4.44 4.44 0 0 0-.501-.29c-.447-.222-.85-.629-.997-1.189l-.289-1.105c-.029-.11-.101-.143-.137-.146a6.6 6.6 0 0 0-1.142 0ZM11 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM9.5 8a1.5 1.5 0 1 0-3.001.001A1.5 1.5 0 0 0 9.5 8Z"/></svg>
        </button>
      </div>
    </div>
    <div class="pane current" id="pane-chat">
      <div id="thread"><div class="thread-inner" id="thread-inner"></div></div>
      <div class="composer-wrap"><div class="composer">
        <div class="composer-box">
          <textarea id="chat-input" rows="1" placeholder="Ask Gemini anything…"></textarea>
          <button type="button" class="btn btn-primary btn-sm" id="send-btn"
                  title="Send (Enter)">{_SEND_ICON}</button>
        </div>
        <div class="composer-meta">
          <span class="muted small">Enter to send · Shift+Enter for a new line</span>
        </div>
      </div></div>
    </div>
    <div class="pane" id="pane-api">{_api_pane(session, api_key)}</div>
  </section>
</div>
{_settings_dialog()}
<script>window.__LLM__ = {boot_json};</script>
<script>{_JS}</script>
{theme.COPY_SCRIPT}"""

    return theme.page("Gemini", body,
                      header_ctx="Gemini",
                      header_right=header_right,
                      nav=nav, full=True,
                      head_extra=f"<style>{_CSS}</style>")
