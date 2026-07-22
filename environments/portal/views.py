"""Server-rendered HTML for the portal + admin (no frontend build).

Deliberately plain and dark; the roadmap says clean and
functional beats pretty. All dynamic values pass through esc().
"""
from __future__ import annotations

import html
import json
import urllib.parse
from datetime import datetime, timezone

# Default terms: confidentiality, monitoring notice, code of conduct,
# IT integrity. Admin may override per session (stored on the session row).
DEFAULT_TERMS = """\
By entering this workspace you agree that:

• Confidentiality — the problems, data, and all session materials are confidential. \
Do not copy, share, publish, or retain them after the session.
• Monitoring — this workspace is monitored and recorded for evaluation and audit \
purposes, including your code, terminal activity, and AI assistant usage.
• Code of conduct — work honestly and independently within the rules your interviewer \
has set.
• IT integrity & security — respect basic security and privacy rules. Do not attempt \
to exfiltrate data, attack the platform, or use the workspace for anything other than \
this interview."""


def esc(s):
    return html.escape(str(s if s is not None else ""))


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh;
  font: 16px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  background: #0f1115; color: #e7e9ee;
  display: flex; flex-direction: column; align-items: center;
}
a { color: #6ea3ff; }
header { text-align: center; padding: 2.5rem 1rem 0.5rem; }
header h1 { margin: 0; font-size: 1.5rem; letter-spacing: .01em; }
header p { margin: .4rem 0 0; color: #9aa0ab; }
main { width: 100%; max-width: 900px; padding: 1.5rem 1rem 3rem; }
.card {
  background: #1a1d24; border: 1px solid #262a33; border-radius: 12px;
  padding: 1.5rem; margin: 0 auto; max-width: 460px;
}
.card.wide { max-width: 100%; }
label { display: block; margin: .9rem 0 .3rem; font-size: .9rem; color: #c4c9d2; }
input[type=text], input[type=password], input[type=number], select, textarea {
  width: 100%; padding: .6rem .7rem; border-radius: 8px;
  border: 1px solid #333844; background: #0f1115; color: #e7e9ee; font: inherit;
}
input.code { text-transform: uppercase; letter-spacing: .4em; text-indent: .4em;
  text-align: center; font-size: 1.4rem; padding: .8rem; }
textarea { min-height: 8rem; resize: vertical; }
button, .btn {
  display: inline-block; margin-top: 1rem; padding: .6rem 1.1rem; border: 0;
  border-radius: 8px; background: #3d7dff; color: #fff; font: inherit; font-weight: 600;
  cursor: pointer; text-decoration: none;
}
button.secondary, .btn.secondary { background: #2a2f3a; color: #e7e9ee; }
button.danger, .btn.danger { background: #b3402f; }
.err { background: #3a1d1d; border: 1px solid #6b2b2b; color: #ffb3ac;
  border-radius: 8px; padding: .7rem .9rem; margin-bottom: 1rem; font-size: .92rem; }
.ok { background: #16301f; border: 1px solid #2c5a3a; color: #a9e5bf;
  border-radius: 8px; padding: .7rem .9rem; margin-bottom: 1rem; font-size: .92rem; }
.grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }
a.tile { display: block; text-decoration: none; color: inherit; background: #1a1d24;
  border: 1px solid #262a33; border-radius: 12px; padding: 1.25rem;
  transition: border-color .12s, transform .12s; }
a.tile:hover { border-color: #3d7dff; transform: translateY(-2px); }
a.tile .ico { height: 40px; display: flex; align-items: center; }
a.tile .ico svg { width: 38px; height: 38px; display: block; }
a.tile h2 { margin: .5rem 0 .2rem; font-size: 1.05rem; }
a.tile p { margin: 0; color: #9aa0ab; font-size: .88rem; }
table { width: 100%; border-collapse: collapse; font-size: .92rem; }
th, td { text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #262a33; }
th { color: #9aa0ab; font-weight: 600; }
.pill { display: inline-block; padding: .1rem .55rem; border-radius: 999px;
  font-size: .78rem; border: 1px solid #333844; }
.state-created { color: #d9c26b; } .state-active { color: #7fd7a0; }
.state-closed  { color: #d98c6b; } .state-exported { color: #9aa0ab; }
.state-reset   { color: #6b717c; }
.muted { color: #9aa0ab; } .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.row { display: flex; gap: .6rem; flex-wrap: wrap; align-items: center; }
form.inline { display: inline; }
footer { color: #6b717c; font-size: .8rem; padding-bottom: 2rem; text-align: center; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6);
  display: flex; align-items: center; justify-content: center; z-index: 50; padding: 1rem; }
.modal-overlay[hidden] { display: none; }
.modal-card { background: #1a1d24; border: 1px solid #333844; border-radius: 12px;
  padding: 1.4rem 1.5rem; max-width: 400px; width: 100%; }
.modal-card p { margin: 0 0 1.2rem; }
.modal-card .row { justify-content: flex-end; }
.modal-card button { margin-top: 0; }
.brandhead { display: flex; align-items: center; gap: .6rem; margin: 0 0 .3rem; font-size: 1.15rem; }
.brandhead svg { width: 26px; height: 26px; display: block; }
pre.code { background: #0b0d12; border: 1px solid #262a33; border-radius: 8px;
  padding: .9rem 1rem; overflow-x: auto; margin: .4rem 0 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem;
  line-height: 1.5; color: #c4c9d2; }
.codelabel { margin: 1rem 0 0; font-size: .82rem; color: #9aa0ab; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; }
.kv { font-size: .9rem; color: #c4c9d2; } .kv .mono { color: #9fe0b8; }
select.pg { width: auto; min-width: 11rem; }
#pg-prompt { min-height: 4.5rem; margin-top: .6rem; }
#pg-out { white-space: pre-wrap; margin-top: .8rem; }
#pg-out[hidden] { display: none; }
button.pg-send { margin-top: 0; }
button.pg-send:disabled { opacity: .6; cursor: default; }
details.code-ex { margin-top: 1.2rem; }
details.code-ex > summary { cursor: pointer; color: #9aa0ab; font-size: .9rem; }
/* Inline-rendered problem statement (moderated candidate page). */
.md { color: #d7dbe3; }
.md h2, .md h3, .md h4, .md h5, .md h6 { color: #e7e9ee; line-height: 1.3; margin: 1.3rem 0 .5rem; }
.md h2 { font-size: 1.15rem; } .md h3 { font-size: 1.02rem; } .md h4 { font-size: .95rem; }
.md > :first-child { margin-top: 0; }
.md p { margin: .6rem 0; }
.md ul, .md ol { margin: .5rem 0 .5rem 1.3rem; padding: 0; }
.md li { margin: .25rem 0; }
.md code { background: #0b0d12; border: 1px solid #262a33; border-radius: 5px;
  padding: .05rem .35rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .86em; color: #9fe0b8; }
.md pre.code { margin: .7rem 0; }
.md pre.code code { background: none; border: 0; padding: 0; color: #c4c9d2; }
.md table { margin: .8rem 0; display: block; overflow-x: auto; }
.md th, .md td { border: 1px solid #262a33; vertical-align: top; }
.md hr { border: 0; border-top: 1px solid #262a33; margin: 1.2rem 0; }
.md blockquote { margin: .7rem 0; padding: .1rem .9rem; border-left: 3px solid #333844; color: #b3b9c4; }
.md a { color: #6ea3ff; }
.prob-head { justify-content: space-between; align-items: flex-start; gap: 1rem; }
"""


def page(title, body, subtitle=None):
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{_CSS}</style></head>
<body><header><h1>{esc(title)}</h1>{sub}</header><main>{body}</main>
<footer>&copy; 2026 Technical Interview Platform</footer></body></html>"""


# --- candidate pages --------------------------------------------------------
def code_entry(error=None):
    err = f'<div class="err">{esc(error)}</div>' if error else ""
    body = f"""<div class="card">{err}
<form method="post" action="/api/code">
<label for="code">Access code</label>
<input type="text" class="code" id="code" name="code" maxlength="6" autocomplete="off"
       autocapitalize="characters" autofocus placeholder="ABCDEF">
<button type="submit">Enter workspace</button>
</form>
<p class="muted" style="margin-top:1rem">Enter the 6-letter code.</p>
</div>"""
    return page("Workspace", body)


def terms(session, error=None):
    err = f'<div class="err">{esc(error)}</div>' if error else ""
    text = session.get("terms_text") or DEFAULT_TERMS
    body = f"""<div class="card wide" style="max-width:640px">{err}
<pre class="mono" style="white-space:pre-wrap;background:#0f1115;border:1px solid #262a33;
     border-radius:8px;padding:1rem;color:#c4c9d2">{esc(text)}</pre>
<form method="post" action="/api/terms">
<label class="row" style="cursor:pointer">
  <input type="checkbox" name="accept" value="yes" style="width:auto"> I have read and accept these terms.
</label>
<button type="submit">Accept &amp; continue</button>
</form></div>"""
    return page(f"Welcome, {session['candidate_name']}", body, "Please review before you begin.")


# Inline SVG glyphs (self-contained, no external assets). Ported from the the workspace stack home
# shell so the post-access-code home matches the brand marks: VS Code + Jupyter logos,
# a document mark for problems, a terminal caret for the shell.
_SVG_PROBLEMS = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="#5b8def" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
    '<path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/>'
    '<path d="M9 13h6M9 17h6"/></svg>'
)
_SVG_IDE = (
    '<svg viewBox="0 0 24 24" fill="#0e9dd8" aria-hidden="true">'
    '<path d="M23.15 2.587L18.21.21a1.494 1.494 0 0 0-1.705.29l-9.46 8.63-4.12-3.128a.999.999 0 0 0-1.276.057L.327 7.261A1 1 0 0 0 .326 8.74L3.899 12 .326 15.26a1 1 0 0 0 .001 1.479L1.65 17.94a.999.999 0 0 0 1.276.057l4.12-3.128 9.46 8.63a1.492 1.492 0 0 0 1.704.29l4.942-2.377A1.5 1.5 0 0 0 24 20.06V3.939a1.5 1.5 0 0 0-.85-1.352zm-5.146 14.861L10.826 12l7.178-5.448v10.896z"/></svg>'
)
_SVG_JUPYTER = (
    '<svg viewBox="0 0 24 24" fill="#f37726" aria-hidden="true">'
    '<path d="M7.157 22.201A1.784 1.799 0 0 1 5.374 24a1.784 1.799 0 0 1-1.784-1.799 1.784 1.799 0 0 1 1.784-1.799 1.784 1.799 0 0 1 1.783 1.799zM20.582 1.427a1.415 1.427 0 0 1-1.415 1.428 1.415 1.427 0 0 1-1.416-1.428A1.415 1.427 0 0 1 19.167 0a1.415 1.427 0 0 1 1.415 1.427zM4.992 3.336A1.047 1.056 0 0 1 3.946 4.39a1.047 1.056 0 0 1-1.047-1.055A1.047 1.056 0 0 1 3.946 2.28a1.047 1.056 0 0 1 1.046 1.056zm7.336 1.517c3.769 0 7.06 1.38 8.768 3.424a9.363 9.363 0 0 0-3.393-4.547 9.238 9.238 0 0 0-5.377-1.728A9.238 9.238 0 0 0 6.95 3.73a9.363 9.363 0 0 0-3.394 4.547c1.713-2.04 5.004-3.424 8.772-3.424zm.001 13.295c-3.768 0-7.06-1.381-8.768-3.425a9.363 9.363 0 0 0 3.394 4.547A9.238 9.238 0 0 0 12.33 21a9.238 9.238 0 0 0 5.377-1.729 9.363 9.363 0 0 0 3.393-4.547c-1.712 2.044-5.003 3.425-8.772 3.425Z"/></svg>'
)
_SVG_TERMINAL = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="#9aa0ab" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/></svg>'
)
# Gemini four-point spark (self-contained; brand-blue gradient).
_SVG_GEMINI = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<defs><linearGradient id="gem" x1="0" y1="0" x2="24" y2="24" '
    'gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#4285f4"/><stop offset="0.5" stop-color="#9b72cb"/>'
    '<stop offset="1" stop-color="#d96570"/></linearGradient></defs>'
    '<path fill="url(#gem)" d="M12 0c.34 6.35 5.65 11.66 12 12-6.35.34-11.66 5.65-12 12'
    '-.34-6.35-5.65-11.66-12-12C6.35 11.66 11.66 6.35 12 0z"/></svg>'
)

_TILES = [
    ("/problems", _SVG_PROBLEMS, "Problems", "Your assigned problems (opens in a new tab).", True),
    ("/ide/", _SVG_IDE, "IDE", "VS Code in the browser.", True),
    ("/jupyter/", _SVG_JUPYTER, "Jupyter", "JupyterLab notebooks.", True),
    ("/ide/", _SVG_TERMINAL, "Terminal", "A shell, inside the IDE.", True),
]


def _gemini_block(session):
    """Candidate-facing 'how to call Gemini' block: OpenAI-SDK and HTTP against unillm
    on localhost:8081. Keeps the raw key off the page — examples use the injected
    $OPENAI_API_KEY / $LLM_API_KEY env vars the workspace already exports."""
    models = session["llm_models"] or ["gemini-3.1-flash-lite"]
    default_model = "gemini-3.1-flash-lite" if "gemini-3.1-flash-lite" in models else models[0]
    model_pills = " ".join(f'<span class="pill mono">{esc(m)}</span>' for m in models)
    py = (
        "from openai import OpenAI\n"
        "\n"
        "# OPENAI_BASE_URL and OPENAI_API_KEY are already set in your workspace.\n"
        "client = OpenAI()\n"
        "resp = client.chat.completions.create(\n"
        f'    model="{default_model}",\n'
        '    messages=[{"role": "user", "content": "Hello"}],\n'
        ")\n"
        "print(resp.choices[0].message.content)"
    )
    curl = (
        "curl http://localhost:8081/v1/chat/completions \\\n"
        '  -H "Authorization: Bearer $OPENAI_API_KEY" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        f"""  -d '{{"model": "{default_model}", "messages": [{{"role": "user", "content": "Hello"}}]}}'"""
    )
    model_opts = "".join(
        f'<option value="{esc(m)}"{" selected" if m == default_model else ""}>{esc(m)}</option>'
        for m in models
    )
    return f"""<div class="card wide" style="margin-top:1.5rem">
  <div class="brandhead">{_SVG_GEMINI}<span>Gemini</span></div>
  <p class="kv">Call Gemini through the workspace LLM proxy at
    <span class="mono">http://localhost:8081/v1</span> (OpenAI-compatible). Your key is
    already in your environment as <span class="mono">$OPENAI_API_KEY</span>
    (alias <span class="mono">$LLM_API_KEY</span>). Available models: {model_pills}</p>

  <p class="codelabel">Playground — try it now</p>
  <div class="row" style="align-items:flex-end">
    <div><label for="pg-model" style="margin-top:.4rem">Model</label>
      <select id="pg-model" class="pg">{model_opts}</select></div>
    <button type="button" id="pg-send" class="pg-send">Send</button>
  </div>
  <textarea id="pg-prompt" placeholder="Ask Gemini anything…">Explain gradient boosting in one sentence.</textarea>
  <pre class="code" id="pg-out" hidden></pre>

  <details class="code-ex">
    <summary>Or call it from code (Python / HTTP)</summary>
    <p class="codelabel">Python — OpenAI SDK</p>
    <pre class="code">{esc(py)}</pre>
    <p class="codelabel">HTTP — curl</p>
    <pre class="code">{esc(curl)}</pre>
  </details>
  <script>
  (function(){{
    var send=document.getElementById('pg-send'), out=document.getElementById('pg-out'),
        box=document.getElementById('pg-prompt'), sel=document.getElementById('pg-model');
    function show(t){{ out.hidden=false; out.textContent=t; }}
    send.addEventListener('click', function(){{
      var p=(box.value||'').trim();
      if(!p){{ show('Enter a prompt first.'); return; }}
      send.disabled=true; var label=send.textContent; send.textContent='…';
      show('Thinking…');
      fetch('/api/llm/playground', {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{model: sel.value, prompt: p}})}})
        .then(function(r){{ return r.json(); }})
        .then(function(d){{ show(d && d.text ? d.text : '(no response)'); }})
        .catch(function(e){{ show('Request failed: ' + e); }})
        .finally(function(){{ send.disabled=false; send.textContent=label; }});
    }});
  }})();
  </script>
</div>"""


def home(session, remaining_minutes):
    tiles = "".join(
        f'<a class="tile" href="{href}"{" target=_blank rel=noopener" if newtab else ""}>'
        f'<div class="ico">{ico}</div><h2>{esc(name)}</h2><p>{esc(desc)}</p></a>'
        for href, ico, name, desc, newtab in _TILES
    )
    rem = (f'<span class="pill state-active">⏱ {remaining_minutes} min left</span>'
           if remaining_minutes is not None else "")
    body = f"""<div class="row" style="justify-content:center;margin-bottom:1.2rem">
  <span class="pill mono">{esc(session['workspace_user'])}</span>{rem}</div>
<div class="grid">{tiles}</div>
{_gemini_block(session)}"""
    return page(f"Welcome, {session['candidate_name']}", body,
                "Your workspace is ready. Pick a tool to get started.")


# Light-mode overrides for the problems page (dark is the base in _CSS). Scoped to
# :root[data-theme="light"], which the toggle stamps on <html> and persists.
_THEME_STYLE = """<style>
:root[data-theme="light"] body { background:#f6f7f9; color:#1a1d24; }
:root[data-theme="light"] a, :root[data-theme="light"] .md a { color:#2563eb; }
:root[data-theme="light"] header p { color:#667085; }
:root[data-theme="light"] .card { background:#fff; border-color:#e3e6ea; }
:root[data-theme="light"] .muted { color:#667085; }
:root[data-theme="light"] th { color:#475467; }
:root[data-theme="light"] button.secondary, :root[data-theme="light"] .btn.secondary {
  background:#e9ecf1; color:#1a1d24; }
:root[data-theme="light"] .md { color:#1a1d24; }
:root[data-theme="light"] .md h2, :root[data-theme="light"] .md h3, :root[data-theme="light"] .md h4,
:root[data-theme="light"] .md h5, :root[data-theme="light"] .md h6 { color:#0f1115; }
:root[data-theme="light"] .md code { background:#eef1f4; border-color:#e3e6ea; color:#0b5f8a; }
:root[data-theme="light"] .md pre.code { background:#f0f2f5; border-color:#e3e6ea; }
:root[data-theme="light"] .md pre.code code { color:#1a1d24; }
:root[data-theme="light"] .md th, :root[data-theme="light"] .md td { border-color:#e3e6ea; }
:root[data-theme="light"] .md hr { border-top-color:#e3e6ea; }
:root[data-theme="light"] .md blockquote { border-left-color:#d0d5dd; color:#475467; }
:root[data-theme="light"] .pill { border-color:#d0d5dd; }
:root[data-theme="light"] footer { color:#98a2b3; }
</style>
<script>(function(){try{if(localStorage.getItem('portal-theme')==='light')
document.documentElement.setAttribute('data-theme','light');}catch(e){}})();</script>"""

_THEME_SCRIPT = """<script>
(function(){
  var b=document.getElementById('theme-toggle');
  function light(){ return document.documentElement.getAttribute('data-theme')==='light'; }
  function upd(){ b.textContent = light() ? 'Dark mode' : 'Light mode'; }
  upd();
  b.addEventListener('click', function(){
    if(light()){ document.documentElement.removeAttribute('data-theme');
      try{ localStorage.setItem('portal-theme','dark'); }catch(e){} }
    else{ document.documentElement.setAttribute('data-theme','light');
      try{ localStorage.setItem('portal-theme','light'); }catch(e){} }
    upd();
  });
})();
</script>"""


def problems_page(session, items=None):
    """Moderated problems page. ``items`` are the released problems only (each
    ``{id, title, summary, released, html}``) — a problem with nothing released is not
    shown at all. Statements render inline; the copy button ships ``data/`` only."""
    items = items or []
    cards = "".join(
        f"""<div class="card wide" style="margin-bottom:1rem">
  <div class="row prob-head">
    <div><h2 style="margin:.1rem 0 .3rem;font-size:1.05rem">{esc(p['title'])}</h2>
      <p class="muted mono" style="margin:0">{esc(p['id'])}/</p></div>
    <button type="button" class="copy-btn secondary" data-pid="{esc(p['id'])}">Copy data to my workspace</button>
  </div>
  <div class="md" style="margin-top:1rem">{p['html']}</div>
</div>"""
        for p in items
    ) or '<div class="card wide"><p class="muted">No problems yet.</p></div>'

    copy_all = ('<button type="button" class="copy-btn secondary" data-pid="all">Copy all data to my workspace</button>'
                if items else "")
    body = f"""{_THEME_STYLE}
<div class="row" style="margin-bottom:1.2rem">
  <a class="btn" href="/problems">↻ Refresh</a>
  {copy_all}
  <button type="button" class="btn secondary" id="theme-toggle">Light mode</button>
  <span id="copy-status" class="muted"></span>
</div>
{cards}
{_THEME_SCRIPT}
<script>
(function(){{
  var status=document.getElementById('copy-status');
  function say(t){{ status.textContent=t; }}
  document.querySelectorAll('.copy-btn').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      var pid=btn.getAttribute('data-pid'), label=btn.textContent;
      btn.disabled=true; btn.textContent='Copying…'; say('');
      fetch('/api/problems/copy', {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{problem_id: pid}})}})
        .then(function(r){{ return r.json(); }})
        .then(function(d){{ say(d && d.message ? d.message : 'Done.');
          btn.textContent = d && d.ok ? 'Copied ✓' : label;
          if(!(d && d.ok)) btn.disabled=false; }})
        .catch(function(e){{ say('Copy failed: '+e); btn.textContent=label; btn.disabled=false; }});
    }});
  }});
}})();
</script>"""
    return page("Problems", body)


# --- admin pages ------------------------------------------------------------
def admin_login(error=None):
    err = f'<div class="err">{esc(error)}</div>' if error else ""
    body = f"""<div class="card">{err}
<form method="post" action="/admin/login">
<label for="u">Username</label><input type="text" id="u" name="username" autofocus>
<label for="p">Password</label><input type="password" id="p" name="password">
<button type="submit">Sign in</button></form></div>"""
    return page("Admin sign-in", body)


def _state_pill(state):
    return f'<span class="pill state-{esc(state)}">{esc(state)}</span>'


def _llm_panel(llm_key, llm_test, models_info=None):
    """Global unillm status: the shared master key, the models unillm is currently
    serving (live from /v1/models), and a Gemini health-check button."""
    result = ""
    if llm_test is not None:
        cls = "ok" if llm_test["ok"] else "err"
        head = (f'Gemini replied via {esc(llm_test["model"])}:' if llm_test["ok"]
                else f'Test failed ({esc(llm_test["model"])}):')
        result = (f'<div class="{cls}" style="margin-top:1rem">{head}'
                  f'<pre class="code" style="margin-top:.5rem">{esc(llm_test["text"])}</pre></div>')
    if models_info is None:
        models_line = ""
    elif models_info["ok"] and models_info["models"]:
        pills = " ".join(f'<span class="pill mono">{esc(m)}</span>' for m in models_info["models"])
        models_line = f'<p class="kv" style="margin:.6rem 0 0">Models served: {pills}</p>'
    else:
        why = esc(models_info.get("error") or "no models") if models_info else ""
        models_line = f'<p class="kv muted" style="margin:.6rem 0 0">Models served: unavailable ({why})</p>'
    return f"""<div class="card wide" style="margin-bottom:1.5rem">
  <div class="brandhead">{_SVG_GEMINI}<span>LLM proxy — unillm</span></div>
  <p class="kv">Platform master key (server-side only — never enters a workspace).
    Each session gets its own <span class="mono">$OPENAI_API_KEY</span>, minted at
    activation and revoked at close. Candidates call
    <span class="mono">http://localhost:8081/v1</span> · Gemini only.</p>
  {models_line}
  <p class="kv" style="margin:.6rem 0 0">Master key:
    <code class="mono" style="background:#0b0d12;border:1px solid #262a33;border-radius:6px;
      padding:.15rem .5rem;user-select:all">{esc(llm_key)}</code></p>
  <form method="post" action="/admin/llm/test">
    <button type="submit">Test Gemini (send &ldquo;Hello&rdquo;)</button>
  </form>{result}
</div>"""


def _visibility_panel(all_problems):
    """Admin Show/Hide control: whether each registry problem is offered in the
    session-create form. Overrides persist server-side (registry.set_visibility)."""
    if not all_problems:
        return ""
    rows = ""
    for p in all_problems:
        visible = p["visible"]
        pill = ('<span class="pill state-active">visible</span>' if visible
                else '<span class="pill state-reset">hidden</span>')
        action = "0" if visible else "1"
        label = "Hide" if visible else "Show"
        cls = "danger" if visible else ""
        rows += (
            f'<tr><td>{esc(p["title"])}</td><td class="mono">{esc(p["id"])}</td>'
            f'<td>{pill}</td><td>'
            f'<form class="inline" method="post" action="/admin/problems/{esc(p["id"])}/visibility">'
            f'<input type="hidden" name="visible" value="{action}">'
            f'<button class="{cls} secondary" type="submit" style="margin-top:0">{label}</button>'
            f'</form></td></tr>')
    return f"""<div class="card wide" style="margin-bottom:1.5rem">
  <div class="row" style="justify-content:space-between;align-items:center">
    <h2 style="margin:0;font-size:1.1rem">Problems — visibility</h2>
    <form class="inline" method="post" action="/admin/problems/validate-data">
      <button class="secondary" type="submit" style="margin-top:0">Validate data deliverability</button>
    </form>
  </div>
  <p class="muted" style="margin:.2rem 0 .8rem">Hidden problems are not offered when creating a session.
    &ldquo;Validate data&rdquo; dry-runs the packager for every problem to confirm each would ship a candidate dataset.</p>
  <table><thead><tr><th>Title</th><th>ID</th><th>Status</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def _deliverability_panel(report):
    """Result of the "Validate data deliverability" dry-run: per-problem OK/FAIL and
    the candidate files each would ship (or the reason it would not)."""
    if not report:
        return ""
    if report.get("error") and not report.get("problems"):
        return (f'<div class="card wide" style="margin-bottom:1.5rem">'
                f'<h2 style="margin-top:0;font-size:1.1rem">Data deliverability</h2>'
                f'<div class="err">could not run the check — {esc(report["error"])}</div></div>')
    rows = ""
    for p in report["problems"]:
        if p["ok"]:
            pill = '<span class="pill state-active">deliverable</span>'
            detail = f'<span class="mono muted">{esc(", ".join(p["files"]))}</span>'
        else:
            pill = '<span class="pill state-reset">missing</span>'
            detail = f'<span class="err">{esc(p["error"] or "no candidate data")}</span>'
        rows += (f'<tr><td class="mono">{esc(p["id"])}</td>'
                 f'<td>{pill}</td><td>{detail}</td></tr>')
    banner = ('<div class="ok">All problems would ship a candidate dataset.</div>'
              if report["ok"] else
              '<div class="err">Some problems would start the candidate with missing data — fix before activating.</div>')
    return f"""<div class="card wide" style="margin-bottom:1.5rem">
  <h2 style="margin-top:0;font-size:1.1rem">Data deliverability</h2>
  {banner}
  <table><thead><tr><th>Problem</th><th>Status</th><th>Would ship</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def _change_password_panel():
    return """<div class="card wide" style="margin-bottom:1.5rem">
  <h2 style="margin-top:0;font-size:1.1rem">Change password</h2>
  <form method="post" action="/admin/password" style="max-width:360px">
    <label for="cp">Current password</label>
    <input type="password" id="cp" name="current_password" required autocomplete="current-password">
    <label for="np">New password</label>
    <input type="password" id="np" name="new_password" required autocomplete="new-password" minlength="8">
    <label for="pp">Confirm new password</label>
    <input type="password" id="pp" name="confirm_password" required autocomplete="new-password" minlength="8">
    <button type="submit">Update password</button>
  </form>
</div>"""


def admin_dashboard(admin, sessions, problems, notice=None, llm_key="", llm_test=None,
                    models_info=None, all_problems=None, deliver_report=None):
    note = f'<div class="ok">{esc(notice)}</div>' if notice else ""
    rows = "".join(
        f"""<tr>
<td><a href="/admin/sessions/{esc(s['id'])}">{esc(s['candidate_name'])}</a></td>
<td class="mono">{esc(s['access_code'])}</td>
<td class="mono">{esc(s['workspace_user'])}</td>
<td>{_state_pill(s['state'])}</td>
<td class="muted">{esc(s['ends_at'] or '—')}</td></tr>"""
        for s in sessions
    ) or '<tr><td colspan="5" class="muted">No sessions yet.</td></tr>'
    body = f"""{note}
{_llm_panel(llm_key, llm_test, models_info)}
<div class="card wide" style="margin-bottom:1.5rem">
  <div class="row" style="justify-content:space-between">
    <h2 style="margin:0;font-size:1.1rem">Sessions</h2>
    <form class="inline" method="post" action="/admin/logout">
      <button class="secondary" type="submit">Sign out ({esc(admin)})</button></form>
  </div>
  <table><thead><tr><th>Candidate</th><th>Code</th><th>User</th><th>State</th><th>Ends</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
<div class="card wide">
  <h2 style="margin-top:0;font-size:1.1rem">New session</h2>
  <form method="post" action="/admin/sessions">
    {_session_form_fields(problems)}
    <button type="submit">Create session</button>
  </form>
</div>
{_deliverability_panel(deliver_report)}
{_visibility_panel(all_problems)}
{_change_password_panel()}"""
    return page("Admin", body)


def _session_form_fields(problems, s=None):
    """Shared inputs for the create + edit forms (pre-filled from `s` when editing)."""
    g = (lambda k: esc(s[k]) if s else "")
    dur = s["duration_minutes"] if s else 90
    budget = f'{s["llm_budget_usd"]:g}' if s else "5"
    models = s["llm_models"] if s else ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
    internet = s["internet_access"] if s else True
    terms = esc(s["terms_text"]) if (s and s["terms_text"]) else ""
    sel = s["problem_ids"] if s else []
    code_attr = f' value="{esc(s["access_code"])}"' if s else ' placeholder="auto"'
    ck = lambda m: " checked" if m in models else ""
    opts = "".join(
        f'<label class="row" style="cursor:pointer"><input type="checkbox" name="problem_ids" '
        f'value="{esc(p["id"])}"{" checked" if p["id"] in sel else ""} style="width:auto"> '
        f'<span class="mono">{esc(p["id"])}</span> <span class="muted">— {esc(p["title"])} '
        f'({esc(p["status"])})</span></label>'
        for p in problems
    ) or '<p class="muted">No problems in the registry.</p>'
    return f"""<div class="grid">
      <div><label for="cn">Candidate display name</label>
        <input type="text" id="cn" name="candidate_name" placeholder="Alex Doe" required value="{g('candidate_name')}"></div>
      <div><label for="wu">Workspace username (OS login)</label>
        <input type="text" id="wu" name="workspace_user" placeholder="candidate" required
               pattern="[a-z_][a-z0-9_-]*" title="lowercase, starts with a letter/underscore" value="{g('workspace_user')}"></div>
      <div><label for="ac">Access code{'' if s else ' (blank = auto)'}</label>
        <input type="text" id="ac" name="access_code" maxlength="6"{code_attr}></div>
      <div><label for="dm">Duration (minutes)</label>
        <input type="number" id="dm" name="duration_minutes" value="{dur}" min="5" max="600"></div>
      <div><label for="bg">LLM budget (USD)</label>
        <input type="number" id="bg" name="llm_budget_usd" value="{budget}" min="0" step="0.5"></div>
      <div><label for="net">Internet access</label>
        <select id="net" name="internet_access">
          <option value="1"{' selected' if internet else ''}>Full (default)</option>
          <option value="0"{' selected' if not internet else ''}>Restricted</option></select></div>
    </div>
    <label>Models</label>
    <div class="row">
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.5-flash"{ck('gemini-3.5-flash')} style="width:auto"> gemini-3.5-flash</label>
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.1-flash-lite"{ck('gemini-3.1-flash-lite')} style="width:auto"> gemini-3.1-flash-lite</label>
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.1-pro"{ck('gemini-3.1-pro')} style="width:auto"> gemini-3.1-pro (opt-in)</label>
    </div>
    <label style="margin-top:1rem">Problems</label>{opts}
    <label for="tt" style="margin-top:1rem">Terms (blank = standard default)</label>
    <textarea id="tt" name="terms_text" placeholder="Leave blank to use the standard terms.">{terms}</textarea>"""


def admin_edit_session(admin, s, problems, error=None):
    err = f'<div class="err">{esc(error)}</div>' if error else ""
    sid = esc(s["id"])
    body = f"""{err}
<div class="row" style="margin-bottom:1rem">
  <a class="btn secondary" href="/admin/sessions/{sid}">← Cancel</a></div>
<div class="card wide">
  <h2 style="margin-top:0;font-size:1.1rem">Edit session</h2>
  <form method="post" action="/admin/sessions/{sid}/edit">
    {_session_form_fields(problems, s)}
    <button type="submit">Save changes</button>
  </form>
</div>"""
    return page(f"Edit — {s['candidate_name']}", body)


def _confirm_modal():
    """A styled confirmation overlay that replaces native confirm() for destructive
    actions. Buttons with class `js-confirm` + `data-confirm` open it and, on Confirm,
    submit their enclosing form."""
    return """
<div id="modal" class="modal-overlay" hidden>
  <div class="modal-card">
    <p id="modal-msg"></p>
    <div class="row">
      <button class="secondary" id="modal-cancel" type="button">Cancel</button>
      <button class="danger" id="modal-ok" type="button">Confirm</button>
    </div>
  </div>
</div>
<script>
(function(){
  var overlay=document.getElementById('modal'), msg=document.getElementById('modal-msg'),
      ok=document.getElementById('modal-ok'), cancel=document.getElementById('modal-cancel'), pending=null;
  function hide(){overlay.hidden=true; pending=null;}
  document.querySelectorAll('.js-confirm').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.preventDefault(); pending=btn.closest('form');
      msg.textContent=btn.getAttribute('data-confirm')||'Are you sure?';
      overlay.hidden=false;
    });
  });
  ok.addEventListener('click', function(){ if(pending) pending.submit(); });
  cancel.addEventListener('click', hide);
  overlay.addEventListener('click', function(e){ if(e.target===overlay) hide(); });
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') hide(); });
})();
</script>"""


def _confirm_attrs(cls, confirm):
    """The class + data-confirm attributes shared by every confirm-through-the-modal
    button (a `js-confirm` class routes the submit through the overlay modal, not
    native confirm()). Returns ``(class_attr, extra_attrs)``."""
    cls_attr = f"{cls} js-confirm".strip() if confirm else cls
    extra = f' data-confirm="{esc(confirm)}"' if confirm else ""
    return cls_attr, extra


def _post_form(action, inner):
    return f'<form class="inline" method="post" action="{action}">{inner}</form>'


def _mod_btn(sid, pid, target, label, cls="secondary", confirm=None):
    cls_attr, extra = _confirm_attrs(cls, confirm)
    inner = (f'<input type="hidden" name="released" value="{int(target)}">'
             f'<button class="{cls_attr}" style="margin-top:0"{extra} type="submit">{esc(label)}</button>')
    return _post_form(f"/admin/sessions/{esc(sid)}/moderate/{esc(pid)}", inner)


def _moderation_panel(sid, s, moderation):
    """Interviewer control over which question each problem shows the candidate.
    Only meaningful before the session closes."""
    if s["state"] not in ("created", "active") or not moderation:
        return ""
    rows = ""
    for p in moderation:
        released, total = p["released"], p["total"]
        if released <= 0:
            status = '<span class="pill state-reset">hidden</span>'
        elif released >= total:
            status = f'<span class="pill state-active">all {total} shown</span>'
        else:
            status = f'<span class="pill state-active">showing Q1–Q{released} of {total}</span>' if released > 1 \
                else f'<span class="pill state-active">showing Q1 of {total}</span>'
        acts = []
        if released <= 0:
            acts.append(_mod_btn(sid, p["id"], 1, "Show Q1 to candidate", cls=""))
        else:
            if released < total:
                nxt = p["next_title"] or f"Q{released + 1}"
                acts.append(_mod_btn(sid, p["id"], released + 1, f"Move to next → Q{released + 1}", cls="",
                                     confirm=f"Reveal “{nxt}” to the candidate? "
                                             "They must click Refresh on the Problems page to see it."))
            acts.append(_mod_btn(sid, p["id"], 0, "Hide", cls="secondary"))
        rows += (f'<tr><td>{esc(p["title"])}</td><td class="mono">{esc(p["id"])}</td>'
                 f'<td>{status}</td><td><div class="row">{"".join(acts)}</div></td></tr>')
    return f"""<div class="card wide" style="margin-top:1.2rem">
  <h2 style="margin-top:0;font-size:1.1rem">Problem moderation</h2>
  <p class="muted" style="margin:.2rem 0 .8rem">The candidate sees the background plus the
     released questions, rendered on their Problems page. “Move to next” reveals the next
     question; the candidate clicks Refresh to load it.</p>
  <table><thead><tr><th>Problem</th><th>ID</th><th>Candidate sees</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def admin_session_detail(admin, s, moderation=None, notice=None, reactivate=None):
    note = f'<div class="ok">{esc(notice)}</div>' if notice else ""
    sid = esc(s["id"])
    actions = _actions_for(s, sid, reactivate)
    fields = [
        ("Candidate", s["candidate_name"]),
        ("Workspace user", s["workspace_user"]),
        ("Access code", s["access_code"]),
        ("State", s["state"]),
        ("Problems", ", ".join(s["problem_ids"]) or "—"),
        ("Duration", f"{s['duration_minutes']} min"),
        ("Starts / Ends", f"{s['starts_at'] or '—'} → {s['ends_at'] or '—'}"),
        ("LLM", f"${s['llm_budget_usd']:.2f} · {', '.join(s['llm_models'])}"),
        ("Internet", "full" if s["internet_access"] else "restricted"),
        ("Terms accepted", s["terms_accepted_at"] or "not yet"),
    ]
    rows = "".join(f'<tr><th>{esc(k)}</th><td class="mono">{esc(v)}</td></tr>' for k, v in fields)
    body = f"""{note}
<div class="row" style="justify-content:space-between;margin-bottom:1rem">
  <a class="btn secondary" href="/admin">← All sessions</a>
  {_state_pill(s['state'])}</div>
<div class="row" style="margin-bottom:1rem">
  <a class="btn secondary" href="/admin/sessions/{sid}/files">📁 Workspace files</a>
  <a class="btn secondary" href="/admin/sessions/{sid}/transcript">💬 LLM transcript</a>
</div>
<div class="card wide"><table>{rows}</table></div>
<div class="card wide" style="margin-top:1.2rem"><div class="row">{actions}</div></div>
{_moderation_panel(sid, s, moderation)}
{_confirm_modal()}"""
    return page(f"Session — {s['candidate_name']}", body)


def _reactivate_control(sid, r):
    """Reactivate button for a closed session. When the clock started and little time is
    left (``needs_total``), require the admin to enter a fresh total (>= min_minutes);
    otherwise the remaining window is preserved and a plain button suffices."""
    action = f"/admin/sessions/{sid}/reactivate"
    min_m = int(r.get("min_minutes") or 30)
    left = r.get("remaining")
    if r.get("needs_total"):
        default = max(min_m, 60)
        return (
            f'<form class="inline" method="post" action="{action}">'
            f'<span class="muted" style="margin-right:.4rem">Only {max(0, int(left))} min left — '
            f'reactivate with total</span>'
            f'<input type="number" name="total_minutes" value="{default}" min="{min_m}" '
            f'style="width:5.5rem"> min'
            f'<button class="js-confirm" style="margin-left:.4rem" '
            f'data-confirm="Reactivate this session for a fresh {default}-minute window and let '
            f'the candidate back in?" type="submit">Reactivate</button></form>')
    tip = (f"Reactivate this session? {int(left)} min remain and the candidate regains access."
           if left is not None else
           "Reactivate this session? The candidate regains access; the timer starts when "
           "they reopen the dashboard.")
    return (
        f'<form class="inline" method="post" action="{action}">'
        f'<button class="js-confirm" data-confirm="{esc(tip)}" type="submit">Reactivate</button></form>')


def _actions_for(s, sid, reactivate=None):
    def btn(action, label, cls="", confirm=None):
        cls_attr, extra = _confirm_attrs(cls, confirm)
        inner = f'<button class="{cls_attr}"{extra} type="submit">{label}</button>'
        return _post_form(f"/admin/sessions/{sid}/{action}", inner)
    out = []
    st = s["state"]
    if st == "created":
        out.append(btn("activate", "Activate (provision workspace)"))
        out.append(f'<a class="btn secondary" href="/admin/sessions/{sid}/edit">Edit</a>')
    if st == "active":
        out.append(f'<form class="inline" method="post" action="/admin/sessions/{sid}/seed-workspace">'
                   f'<button class="secondary" type="submit">Copy full problem files (incl. statement .md) to workspace</button></form>')
        out.append('<form class="inline" method="post" action="/admin/sessions/%s/extend">'
                   '<input type="number" name="minutes" value="15" min="5" style="width:5rem">'
                   '<button class="secondary" type="submit">Extend</button></form>' % sid)
        out.append(btn("close", "Close session", "danger",
                       "Close this session? The candidate immediately loses access."))
    if st == "closed":
        out.append(_reactivate_control(sid, reactivate or {}))
        out.append(btn("export", "Export bundle"))
    if st in ("closed", "exported"):
        out.append(f'<a class="btn secondary" href="/admin/sessions/{sid}/download">Download export</a>')
    if st == "exported":
        out.append(btn("reset", "Reset workspace", "danger",
                       "Wipe the workspace for the next candidate?"))
    if st != "active":
        out.append(btn("delete", "Delete", "danger",
                       "Permanently delete this session and its records? This cannot be undone."))
    return "".join(out) or '<span class="muted">No actions in this state.</span>'


# --- LLM transcript viewer --------------------------------------------------
_SOURCE_LABELS = {"api": "Direct API call", "ui": "UI playground", "admin-test": "Admin test",
                  "server": "Server-side"}


def _fmt_ts(ts):
    """ISO-ish timestamp string, shown as-is (already UTC, seconds precision)."""
    return esc((ts or "").replace("T", " ").replace("+00:00", "Z"))


def _fmt_epoch(epoch):
    try:
        return esc(datetime.fromtimestamp(float(epoch), timezone.utc)
                   .isoformat(timespec="seconds").replace("+00:00", "Z"))
    except (TypeError, ValueError):
        return "—"


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _source_pill(src):
    src = src or "api"
    label = _SOURCE_LABELS.get(src, src)
    cls = {"api": "state-active", "ui": "state-created", "admin-test": "state-exported"}.get(src, "")
    return f'<span class="pill {cls}">{esc(label)}</span>'


def _transcript_entry(e):
    src = e.get("source") or "api"
    head_bits = [_source_pill(src), f'<span class="mono muted">{_fmt_ts(e.get("ts"))}</span>',
                 f'<span class="pill mono">{esc(e.get("model") or "?")}</span>']
    if e.get("stream"):
        head_bits.append('<span class="pill">stream</span>')
    if e.get("latency_ms") is not None:
        head_bits.append(f'<span class="muted">{esc(e["latency_ms"])} ms</span>')
    u = e.get("usage") or {}
    if u:
        toks = u.get("total_tokens")
        if toks is None:
            toks = (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        head_bits.append(f'<span class="muted">{esc(toks)} tok</span>')

    def block(label, text):
        return (f'<p class="codelabel">{esc(label)}</p>'
                f'<pre class="code" style="white-space:pre-wrap">{esc(text)}</pre>')

    parts = []
    for m in e.get("messages") or []:
        if isinstance(m, dict):
            parts.append(block(m.get("role") or "message", m.get("content") or ""))
    if e.get("prompt"):
        parts.append(block("prompt", e["prompt"]))
    if e.get("response"):
        parts.append(block("response", e["response"]))
    if e.get("error"):
        parts.append(f'<div class="err" style="margin-top:.6rem">{esc(e["error"])}</div>')
    return (f'<div class="card wide" style="margin-bottom:.9rem">'
            f'<div class="row" style="gap:.5rem;flex-wrap:wrap">{"".join(head_bits)}</div>'
            f'{"".join(parts)}</div>')


def admin_transcript_page(admin, s, data, source=None, query=None):
    sid = esc(s["id"])
    entries = data["entries"]
    # Source filter dropdown: the sources actually present, plus the current selection.
    known = list(dict.fromkeys(list(data["sources"]) + ([source] if source else [])))
    opts = ['<option value="">All sources</option>']
    for src in known:
        sel = " selected" if src == source else ""
        opts.append(f'<option value="{esc(src)}"{sel}>{esc(_SOURCE_LABELS.get(src, src))}</option>')
    shown, total = data["shown"], data["total"]
    cap_note = (f' (showing latest {shown})' if shown < total else "")
    summary = f'{total} call{"s" if total != 1 else ""} match{"" if total == 1 else "es"}{cap_note}.'
    body = "".join(_transcript_entry(e) for e in entries) or \
        '<div class="card wide"><p class="muted">No LLM calls recorded for this session yet.</p></div>'
    return page(f"Transcript — {s['candidate_name']}", f"""
<div class="row" style="justify-content:space-between;margin-bottom:1rem">
  <a class="btn secondary" href="/admin/sessions/{sid}">← Session</a>
  <a class="btn secondary" href="/admin/sessions/{sid}/transcript">↻ Refresh</a>
</div>
<div class="card wide" style="margin-bottom:1rem">
  <form method="get" action="/admin/sessions/{sid}/transcript" class="row" style="align-items:flex-end;gap:.8rem">
    <div><label for="src" style="margin-top:0">Source</label>
      <select id="src" name="source" class="pg">{"".join(opts)}</select></div>
    <div style="flex:1;min-width:12rem"><label for="q" style="margin-top:0">Search text</label>
      <input type="text" id="q" name="q" value="{esc(query or "")}" placeholder="prompt or response contains…"></div>
    <button type="submit">Apply</button>
    <a class="btn secondary" href="/admin/sessions/{sid}/transcript">Clear</a>
  </form>
  <p class="muted" style="margin:.6rem 0 0">{esc(summary)} Source is attributed by the proxy:
    <b>Direct API call</b> = the candidate's own workspace call, <b>UI playground</b> = the
    portal Gemini box. A plain Refresh re-reads the live transcript.</p>
</div>
{body}""")


# --- candidate workspace file manager ---------------------------------------
def _crumbs(sid, rel):
    """Clickable breadcrumb path back to the workspace root."""
    out = [f'<a href="/admin/sessions/{sid}/files">~/workspace</a>']
    acc = []
    for part in [p for p in (rel or "").split("/") if p]:
        acc.append(part)
        href = f"/admin/sessions/{sid}/files?path={urllib.parse.quote('/'.join(acc))}"
        out.append(f'<a href="{href}">{esc(part)}</a>')
    return '<span class="muted mono"> / </span>'.join(out)


def _provision_panel(sid, s, cwd):
    """Provision / reset controls for the session's assigned problem data."""
    assigned = s["problem_ids"] or []
    if not assigned:
        return ""
    opts = '<option value="all">all assigned problems</option>' + "".join(
        f'<option value="{esc(p)}">{esc(p)}</option>' for p in assigned)
    cwd_h = f'<input type="hidden" name="cwd" value="{esc(cwd)}">'
    return f"""<div class="card wide" style="margin-bottom:1rem">
  <h2 style="margin-top:0;font-size:1.05rem">Problem data</h2>
  <p class="muted" style="margin:.2rem 0 .8rem">Provision copies each problem's seeded
    <span class="mono">data/</span> into the workspace; reset restores it to the original,
    discarding candidate edits. Neither ships solutions, rubrics, or generators.</p>
  <div class="row" style="align-items:flex-end;gap:.6rem">
    <div><label for="pdp" style="margin-top:0">Problem</label>
      <select id="pdp" name="problem_id" form="prov-form" class="pg">{opts}</select></div>
    <form id="prov-form" class="inline" method="post" action="/admin/sessions/{sid}/files/provision">{cwd_h}
      <button class="secondary" type="submit" style="margin-top:0">Provision data</button></form>
    <form class="inline" method="post" action="/admin/sessions/{sid}/files/reset">{cwd_h}
      <input type="hidden" name="problem_id" value="all">
      <button class="secondary js-confirm" style="margin-top:0"
        data-confirm="Reset ALL assigned problem data to the seeded original? Candidate edits to data/ are lost."
        type="submit">Reset all data</button></form>
  </div>
</div>"""


def _file_row(sid, e):
    icon = "📁" if e["is_dir"] else "📄"
    href = f"/admin/sessions/{sid}/files?path={urllib.parse.quote(e['rel'])}"
    name = (f'<a href="{href}">{icon} {esc(e["name"])}{"/" if e["is_dir"] else ""}</a>')
    size = "—" if e["is_dir"] else _fmt_bytes(e["size"])
    parent = e["rel"].rsplit("/", 1)[0] if "/" in e["rel"] else ""
    del_form = (f'<form class="inline" method="post" action="/admin/sessions/{sid}/files/delete">'
                f'<input type="hidden" name="path" value="{esc(e["rel"])}">'
                f'<input type="hidden" name="cwd" value="{esc(parent)}">'
                f'<button class="danger secondary js-confirm" style="margin-top:0;padding:.25rem .6rem"'
                f' data-confirm="Delete {esc(e["name"])}{"/ and everything in it" if e["is_dir"] else ""} from the workspace?"'
                f' type="submit">Remove</button></form>')
    return (f'<tr><td>{name}</td><td class="mono muted">{size}</td>'
            f'<td class="mono muted">{_fmt_epoch(e["mtime"])}</td><td>{del_form}</td></tr>')


def admin_files_page(admin, s, listing=None, view=None, available=True,
                     unavailable_reason=None, error=None, notice=None):
    sid = esc(s["id"])
    head = f"""
<div class="row" style="justify-content:space-between;margin-bottom:1rem">
  <a class="btn secondary" href="/admin/sessions/{sid}">← Session</a>
  <a class="btn secondary" href="/admin/sessions/{sid}/files">↻ Refresh</a>
</div>"""
    banners = ""
    if notice:
        banners += f'<div class="ok">{esc(notice)}</div>'
    if error:
        banners += f'<div class="err">{esc(error)}</div>'

    if not available:
        body = (f'{head}{banners}<div class="card wide"><p class="muted">The workspace isn\'t '
                f'available for this session — {esc(unavailable_reason or "not provisioned")}.</p></div>')
        return page(f"Files — {s['candidate_name']}", body)

    if view is not None:
        rel = view["rel"]
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        back = f"/admin/sessions/{sid}/files?path={urllib.parse.quote(parent)}"
        meta = f'{_fmt_bytes(view["size"])}{" · truncated" if view.get("truncated") else ""}'
        if view["binary"]:
            content = '<p class="muted">Binary file — not shown.</p>'
        else:
            content = f'<pre class="code" style="white-space:pre-wrap;max-height:70vh;overflow:auto">{esc(view["text"])}</pre>'
        body = f"""{head}{banners}
<p style="margin:0 0 .6rem">{_crumbs(sid, rel)}</p>
<div class="card wide">
  <div class="row prob-head"><h2 style="margin:.1rem 0;font-size:1.05rem" class="mono">{esc(rel)}</h2>
    <span class="muted mono">{esc(meta)}</span></div>
  <div style="margin-top:.8rem">{content}</div>
  <div class="row" style="margin-top:1rem"><a class="btn secondary" href="{back}">← Back to folder</a></div>
</div>"""
        return page(f"Files — {s['candidate_name']}", body)

    listing = listing or {"path": "", "entries": []}
    cwd = listing.get("path", "")
    rows = "".join(_file_row(sid, e) for e in listing["entries"]) or \
        '<tr><td colspan="4" class="muted">Empty folder.</td></tr>'
    body = f"""{head}{banners}
{_provision_panel(sid, s, cwd)}
<p style="margin:0 0 .6rem">{_crumbs(sid, cwd)}</p>
<div class="card wide">
  <table><thead><tr><th>Name</th><th>Size</th><th>Modified (UTC)</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
{_confirm_modal()}"""
    return page(f"Files — {s['candidate_name']}", body)
