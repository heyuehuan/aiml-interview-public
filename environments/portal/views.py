"""Server-rendered HTML for the portal + admin (no frontend build).

Deliberately plain and dark; the roadmap says clean and
functional beats pretty. All dynamic values pass through esc().
"""
from __future__ import annotations

import html
import json

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
input.code { text-transform: uppercase; letter-spacing: .5em; text-align: center;
  font-size: 1.6rem; padding: .8rem; }
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
a.tile .ico { font-size: 1.8rem; }
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
"""


def page(title, body, subtitle=None):
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{_CSS}</style></head>
<body><header><h1>{esc(title)}</h1>{sub}</header><main>{body}</main>
<footer>&copy; 2026 Technical Interview Platform — monitored &amp; recorded for evaluation</footer></body></html>"""


# --- candidate pages --------------------------------------------------------
def code_entry(error=None):
    err = f'<div class="err">{esc(error)}</div>' if error else ""
    body = f"""<div class="card">{err}
<form method="post" action="/api/code">
<label for="code">Access code</label>
<input class="code" id="code" name="code" maxlength="6" autocomplete="off"
       autocapitalize="characters" autofocus placeholder="ABCDEF">
<button type="submit">Enter workspace</button>
</form>
<p class="muted" style="margin-top:1rem">Enter the 6-letter code from your interview invite.</p>
</div>"""
    return page("Interview workspace", body, "Welcome — let's get you set up.")


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


_TILES = [
    ("/problems", "📄", "Problems", "Your assigned problems (opens in a new tab).", True),
    ("/ide/", "🧩", "IDE", "VS Code in the browser.", True),
    ("/jupyter/", "📊", "Jupyter", "JupyterLab notebooks.", True),
    ("/ide/", "⌨️", "Terminal", "A shell, inside the IDE.", True),
]


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
<div class="grid">{tiles}</div>"""
    return page(f"Welcome, {session['candidate_name']}", body,
                "Your workspace is ready. Pick a tool to get started.")


def problems_page(session):
    items = "".join(f"<li class='mono'>{esc(pid)}</li>" for pid in session["problem_ids"]) \
        or "<li class='muted'>No problems assigned yet — check with your interviewer.</li>"
    body = f"""<div class="card wide">
<p>Your problem files are in the workspace at <span class="mono">~/workspace/</span>
(open <span class="mono">PROBLEMS.md</span> in the IDE or Jupyter). Assigned:</p>
<ul>{items}</ul></div>"""
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


def admin_dashboard(admin, sessions, problems, notice=None):
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
    opts = "".join(
        f'<label class="row" style="cursor:pointer"><input type="checkbox" name="problem_ids" '
        f'value="{esc(p["id"])}" style="width:auto"> '
        f'<span class="mono">{esc(p["id"])}</span> <span class="muted">— {esc(p["title"])} '
        f'({esc(p["status"])})</span></label>'
        for p in problems
    ) or '<p class="muted">No problems in the registry.</p>'
    body = f"""{note}
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
    <div class="grid">
      <div><label for="cn">Candidate display name</label>
        <input type="text" id="cn" name="candidate_name" placeholder="Alex Doe" required></div>
      <div><label for="wu">Workspace username (OS login)</label>
        <input type="text" id="wu" name="workspace_user" placeholder="candidate" required
               pattern="[a-z_][a-z0-9_-]*" title="lowercase, starts with a letter/underscore"></div>
      <div><label for="ac">Access code (blank = auto)</label>
        <input type="text" id="ac" name="access_code" maxlength="6" placeholder="auto"></div>
      <div><label for="dm">Duration (minutes)</label>
        <input type="number" id="dm" name="duration_minutes" value="90" min="5" max="600"></div>
      <div><label for="bg">LLM budget (USD)</label>
        <input type="number" id="bg" name="llm_budget_usd" value="5" min="0" step="0.5"></div>
      <div><label for="net">Internet access</label>
        <select id="net" name="internet_access"><option value="1">Full (default)</option>
        <option value="0">Restricted</option></select></div>
    </div>
    <label>Models</label>
    <div class="row">
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.5-flash" checked style="width:auto"> gemini-3.5-flash</label>
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.1-flash-lite" checked style="width:auto"> gemini-3.1-flash-lite</label>
      <label class="row" style="cursor:pointer"><input type="checkbox" name="llm_models"
        value="gemini-3.1-pro" style="width:auto"> gemini-3.1-pro (opt-in)</label>
    </div>
    <label style="margin-top:1rem">Problems</label>{opts}
    <label for="tt" style="margin-top:1rem">Terms (blank = standard default)</label>
    <textarea id="tt" name="terms_text" placeholder="Leave blank to use the standard terms."></textarea>
    <button type="submit">Create session</button>
  </form>
</div>"""
    return page("Admin", body)


def admin_session_detail(admin, s, notice=None):
    note = f'<div class="ok">{esc(notice)}</div>' if notice else ""
    sid = esc(s["id"])
    actions = _actions_for(s, sid)
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
<div class="card wide"><table>{rows}</table></div>
<div class="card wide" style="margin-top:1.2rem"><div class="row">{actions}</div></div>"""
    return page(f"Session — {s['candidate_name']}", body)


def _actions_for(s, sid):
    def btn(action, label, cls="", confirm=None):
        c = f' onsubmit="return confirm(\'{confirm}\')"' if confirm else ""
        return (f'<form class="inline" method="post" action="/admin/sessions/{sid}/{action}"{c}>'
                f'<button class="{cls}" type="submit">{label}</button></form>')
    out = []
    st = s["state"]
    if st == "created":
        out.append(btn("activate", "Activate (provision workspace)"))
    if st == "active":
        out.append('<form class="inline" method="post" action="/admin/sessions/%s/extend">'
                   '<input type="number" name="minutes" value="15" min="5" style="width:5rem">'
                   '<button class="secondary" type="submit">Extend</button></form>' % sid)
        out.append(btn("close", "Close session", "danger", "Close this session?"))
    if st == "closed":
        out.append(btn("export", "Export bundle"))
    if st in ("closed", "exported"):
        out.append(f'<a class="btn secondary" href="/admin/sessions/{sid}/download">Download export</a>')
    if st == "exported":
        out.append(btn("reset", "Reset workspace", "danger", "Wipe the workspace for the next candidate?"))
    return "".join(out) or '<span class="muted">No actions in this state.</span>'
