"""Candidate-facing pages (code entry → terms → home → problems).

All layout comes from theme.py (server-rendered, no build). Admin
pages live in views_admin.py; the Gemini page in views_llm.py.
"""
from __future__ import annotations

import theme
from theme import esc

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


def _candidate_nav(active):
    return "".join([
        theme.nav_item("/", "Home", active == "home"),
        theme.nav_item("/problems", "Problems", active == "problems"),
        theme.nav_item("/llm", "Gemini", active == "llm"),
    ])


def _session_header_right(session, remaining_minutes=None):
    bits = [f'<span class="label mono">{esc(session["workspace_user"])}</span>']
    if remaining_minutes is not None:
        bits.append(f'<span class="label st-active">{remaining_minutes} min left</span>')
    return "".join(bits)


# --- code entry -------------------------------------------------------------
def code_entry(error=None):
    body = f"""{theme.flash(error, "err")}
<div style="text-align:center;margin:48px 0 24px">
  <div style="display:inline-flex;width:40px;height:40px">{theme.BRAND_MARK}</div>
  <h1 class="page-title" style="margin-top:12px">Interview workspace</h1>
</div>
<div class="box"><div class="box-body">
<form method="post" action="/api/code">
  <label for="code">Access code</label>
  <input type="text" class="input-code" id="code" name="code" maxlength="6"
         autocomplete="off" autocapitalize="characters" autofocus placeholder="••••••">
  <button type="submit" class="btn btn-primary btn-block" style="margin-top:16px">Continue</button>
</form>
</div></div>
<p class="muted small" style="text-align:center;margin-top:16px">Your interviewer gave you a 6-letter code.</p>"""
    return theme.page("Interview workspace", body, width="narrow")


# --- terms ------------------------------------------------------------------
def terms(session, error=None):
    text = session.get("terms_text") or DEFAULT_TERMS
    body = f"""{theme.flash(error, "err")}
<h1 class="page-title" style="margin:24px 0 4px">Welcome, {esc(session['candidate_name'])}</h1>
<p class="muted" style="margin:0 0 16px">Review the terms before you begin.</p>
<div class="box">
  <div class="box-body" style="white-space:pre-wrap;font-size:14px;line-height:1.6">{esc(text)}</div>
  <div class="box-row" style="background:var(--bg-subtle);border-radius:0 0 6px 6px">
    <form method="post" action="/api/terms">
      <label class="checkrow" style="margin:0 0 12px">
        <input type="checkbox" name="accept" value="yes"> I have read and accept these terms.
      </label>
      <button type="submit" class="btn btn-primary">Accept &amp; continue</button>
    </form>
  </div>
</div>"""
    return theme.page("Terms", body, width="medium")


# --- home -------------------------------------------------------------------
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
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="color:var(--fg-muted)">'
    '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/></svg>'
)

_TILES = [
    ("/problems", _SVG_PROBLEMS, "Problems", "Your assigned problems.", True),
    ("/llm", theme.GEMINI_MARK, "Gemini", "Chat playground &amp; API access.", True),
    ("/ide/", _SVG_IDE, "IDE", "VS Code in the browser.", True),
    ("/jupyter/", _SVG_JUPYTER, "Jupyter", "JupyterLab notebooks.", True),
    ("/ide/", _SVG_TERMINAL, "Terminal", "A shell, inside the IDE.", True),
]


def home(session, remaining_minutes):
    tiles = "".join(
        f'<a class="tile" href="{href}"{" target=_blank rel=noopener" if newtab else ""}>'
        f'<div class="ico">{ico}</div><h2>{esc(name)}</h2><p>{desc}</p></a>'
        for href, ico, name, desc, newtab in _TILES
    )
    body = f"""<h1 class="page-title" style="margin-bottom:4px">Welcome, {esc(session['candidate_name'])}</h1>
<p class="muted" style="margin:0 0 24px">Your workspace is ready. Pick a tool to get started.</p>
<div class="grid">{tiles}</div>"""
    return theme.page("Workspace", body,
                      header_ctx="Interview workspace",
                      header_right=_session_header_right(session, remaining_minutes),
                      nav=_candidate_nav("home"))


# --- problems ---------------------------------------------------------------
def problems_page(session, items=None):
    """Moderated problems page. ``items`` are the released problems only (each
    ``{id, title, summary, released, html}``) — a problem with nothing released is not
    shown at all. Statements render inline; the copy button ships ``data/`` only."""
    items = items or []
    cards = "".join(
        f"""<div class="box" style="margin-bottom:16px">
  <div class="box-header">
    <div><h2>{esc(p['title'])}</h2>
      <p class="muted small mono" style="margin:2px 0 0">{esc(p['id'])}/</p></div>
    <button type="button" class="btn btn-sm copy-btn" data-pid="{esc(p['id'])}">Copy data to workspace</button>
  </div>
  <div class="box-body md">{p['html']}</div>
</div>"""
        for p in items
    ) or '<div class="box"><div class="blankslate">No problems released yet.<br>Your interviewer will release them as you go — refresh to check.</div></div>'

    copy_all = ('<button type="button" class="btn btn-sm copy-btn" data-pid="all">Copy all data</button>'
                if items else "")
    body = f"""<div class="row row-split" style="margin-bottom:16px">
  <div class="row">
    <a class="btn btn-sm" href="/problems">Refresh</a>
    {copy_all}
  </div>
  <span id="copy-status" class="muted small"></span>
</div>
{cards}
<script>
(function(){{
  var status = document.getElementById('copy-status');
  function say(t){{ status.textContent = t; }}
  document.querySelectorAll('.copy-btn').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      var pid = btn.getAttribute('data-pid'), label = btn.textContent;
      btn.disabled = true; btn.textContent = 'Copying…'; say('');
      fetch('/api/problems/copy', {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{problem_id: pid}})}})
        .then(function(r){{ return r.json(); }})
        .then(function(d){{ say(d && d.message ? d.message : 'Done.');
          btn.textContent = d && d.ok ? 'Copied ✓' : label;
          if(!(d && d.ok)) btn.disabled = false; }})
        .catch(function(e){{ say('Copy failed: ' + e); btn.textContent = label; btn.disabled = false; }});
    }});
  }});
}})();
</script>"""
    return theme.page("Problems", body,
                      header_ctx="Problems",
                      header_right=_session_header_right(session),
                      nav=_candidate_nav("problems"))
