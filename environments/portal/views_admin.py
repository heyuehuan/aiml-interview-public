"""Admin panel pages — GitHub-style top tabs: Sessions / Problems / LLM proxy /
Settings. Session detail has its own sub-nav (Overview / Files / Answers / Transcript).

All layout comes from theme.py. Routes live in admin.py; every dynamic value
passes through esc().
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

import handout
import theme
import views
from theme import esc


# --- shell ------------------------------------------------------------------
def _tabs(active):
    return "".join([
        theme.nav_item("/admin", "Sessions", active == "sessions"),
        theme.nav_item("/admin/problems", "Problems", active == "problems"),
        theme.nav_item("/admin/llm", "LLM proxy", active == "llm"),
        theme.nav_item("/admin/settings", "Settings", active == "settings"),
    ])


def _page(title, body, who=None, tab=None, header_ctx=""):
    right = ""
    if who:
        right = (f'<span class="label mono">{esc(who)}</span>'
                 f'<form class="inline" method="post" action="/admin/logout">'
                 f'<button class="btn btn-sm" type="submit">Sign out</button></form>')
    return theme.page(title, body, brand="Interview Admin", brand_href="/admin",
                      header_ctx=header_ctx, header_right=right,
                      nav=_tabs(tab) if tab else "")


def admin_login(error=None):
    body = f"""{theme.flash(error, "err")}
<div style="text-align:center;margin:48px 0 24px">
  <div style="display:inline-flex;width:40px;height:40px">{theme.BRAND_MARK}</div>
  <h1 class="page-title" style="margin-top:12px">Admin sign-in</h1>
</div>
<div class="box"><div class="box-body">
<form method="post" action="/admin/login">
  <label for="u">Username</label><input type="text" id="u" name="username" autofocus>
  <label for="p">Password</label><input type="password" id="p" name="password">
  <button type="submit" class="btn btn-primary btn-block" style="margin-top:16px">Sign in</button>
</form>
</div></div>"""
    return theme.page("Admin sign-in", body, brand="Interview Admin",
                      brand_href="/admin", width="narrow")


# --- Sessions tab -----------------------------------------------------------
def sessions_page(who, sessions, notice=None):
    rows = "".join(
        f"""<tr>
<td><a href="/admin/sessions/{esc(s['id'])}">{esc(s['candidate_name'])}</a></td>
<td class="mono">{esc(s['access_code'])}</td>
<td class="mono">{esc(s['workspace_user'])}</td>
<td>{theme.state_label(s['state'])}</td>
<td class="muted small">{esc(s['ends_at'] or '—')}</td></tr>"""
        for s in sessions
    ) or '<tr><td colspan="5"><div class="blankslate">No sessions yet.</div></td></tr>'
    body = f"""{theme.flash(notice)}
<div class="subhead">
  <h2>Sessions</h2>
  <a class="btn btn-primary btn-sm" href="/admin/sessions/new">New session</a>
</div>
<div class="box">
<table class="table">
<thead><tr><th>Candidate</th><th>Code</th><th>User</th><th>State</th><th>Ends (UTC)</th></tr></thead>
<tbody>{rows}</tbody></table>
</div>"""
    return _page("Sessions · Admin", body, who, tab="sessions")


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
        f'<label class="checkrow"><input type="checkbox" name="problem_ids" '
        f'value="{esc(p["id"])}"{" checked" if p["id"] in sel else ""}> '
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
      <label class="checkrow" style="margin:0"><input type="checkbox" name="llm_models"
        value="gemini-3.5-flash"{ck('gemini-3.5-flash')}> gemini-3.5-flash</label>
      <label class="checkrow" style="margin:0"><input type="checkbox" name="llm_models"
        value="gemini-3.1-flash-lite"{ck('gemini-3.1-flash-lite')}> gemini-3.1-flash-lite</label>
      <label class="checkrow" style="margin:0"><input type="checkbox" name="llm_models"
        value="gemini-3.1-pro"{ck('gemini-3.1-pro')}> gemini-3.1-pro (opt-in)</label>
    </div>
    <label>Problems</label>{opts}
    <label for="tt">Terms <span class="muted" style="font-weight:400">(blank = standard default)</span></label>
    <textarea id="tt" name="terms_text" placeholder="Leave blank to use the standard terms.">{terms}</textarea>"""


def session_new_page(who, problems, error=None):
    body = f"""{theme.flash(error, "err")}
<div class="subhead"><h2>New session</h2>
  <a class="btn btn-sm" href="/admin">Cancel</a></div>
<div class="box"><div class="box-body">
<form method="post" action="/admin/sessions">
  {_session_form_fields(problems)}
  <button type="submit" class="btn btn-primary" style="margin-top:16px">Create session</button>
</form>
</div></div>"""
    return _page("New session · Admin", body, who, tab="sessions")


def admin_edit_session(who, s, problems, error=None):
    sid = esc(s["id"])
    body = f"""{theme.flash(error, "err")}
<div class="subhead"><h2>Edit session — {esc(s['candidate_name'])}</h2>
  <a class="btn btn-sm" href="/admin/sessions/{sid}">Cancel</a></div>
<div class="box"><div class="box-body">
<form method="post" action="/admin/sessions/{sid}/edit">
  {_session_form_fields(problems, s)}
  <button type="submit" class="btn btn-primary" style="margin-top:16px">Save changes</button>
</form>
</div></div>"""
    return _page(f"Edit — {s['candidate_name']}", body, who, tab="sessions")


# --- session detail ---------------------------------------------------------
def _detail_nav(sid, active):
    return "".join([
        theme.nav_item(f"/admin/sessions/{sid}", "Overview", active == "overview"),
        theme.nav_item(f"/admin/sessions/{sid}/files", "Files", active == "files"),
        theme.nav_item(f"/admin/sessions/{sid}/answers", "Answers", active == "answers"),
        theme.nav_item(f"/admin/sessions/{sid}/transcript", "Transcript", active == "transcript"),
    ])


def _detail_page(title, body, who, s, active):
    sid = esc(s["id"])
    head = f"""<div class="row" style="margin-bottom:12px">
  <a class="btn btn-sm" href="/admin">← Sessions</a>
  <h1 class="page-title">{esc(s['candidate_name'])}</h1>
  {theme.state_label(s['state'])}
</div>
<nav class="underline-nav" style="padding:0;background:transparent;margin-bottom:16px">
  {_detail_nav(sid, active)}
</nav>"""
    return _page(title, head + body, who, tab="sessions")


def _post_form(action, inner):
    return f'<form class="inline" method="post" action="{action}">{inner}</form>'


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
            f'<form class="inline row" style="gap:6px" method="post" action="{action}">'
            f'<span class="muted small">only {max(0, int(left))} min left — new total</span>'
            f'<input type="number" name="total_minutes" value="{default}" min="{min_m}" '
            f'style="width:5.5rem"><span class="muted small">min</span>'
            f'<button class="btn js-confirm" '
            f'data-confirm="Reactivate this session for a fresh {default}-minute window and let '
            f'the candidate back in?" type="submit">Reactivate</button></form>')
    tip = (f"Reactivate this session? {int(left)} min remain and the candidate regains access."
           if left is not None else
           "Reactivate this session? The candidate regains access; the timer starts when "
           "they reopen the dashboard.")
    return (
        f'<form class="inline" method="post" action="{action}">'
        f'<button class="btn js-confirm" data-confirm="{esc(tip)}" type="submit">Reactivate</button></form>')


def _actions_for(s, sid, reactivate=None):
    def btn(action, label, cls="btn", confirm=None):
        cls_attr, extra = theme.confirm_attrs(cls, confirm)
        inner = f'<button class="{cls_attr}"{extra} type="submit">{label}</button>'
        return _post_form(f"/admin/sessions/{sid}/{action}", inner)
    out = []
    st = s["state"]
    if st == "created":
        out.append(btn("activate", "Activate (provision workspace)", "btn btn-primary"))
        out.append(f'<a class="btn" href="/admin/sessions/{sid}/edit">Edit</a>')
    if st == "active":
        out.append(f'<form class="inline" method="post" action="/admin/sessions/{sid}/seed-workspace">'
                   f'<button class="btn" type="submit">Push full problem files to workspace</button></form>')
        out.append('<form class="inline row" style="gap:6px" method="post" action="/admin/sessions/%s/extend">'
                   '<input type="number" name="minutes" value="15" min="5" style="width:5rem">'
                   '<button class="btn" type="submit">Extend</button></form>' % sid)
        out.append(btn("close", "Close session", "btn btn-danger",
                       "Close this session? The candidate immediately loses access."))
    if st == "closed":
        out.append(_reactivate_control(sid, reactivate or {}))
        out.append(btn("export", "Export bundle", "btn btn-primary"))
    if st in ("closed", "exported"):
        out.append(f'<a class="btn" href="/admin/sessions/{sid}/download">Download export</a>')
    if st == "exported":
        out.append(btn("reset", "Reset workspace", "btn btn-danger",
                       "Wipe the workspace for the next candidate?"))
    if st != "active":
        out.append(btn("delete", "Delete", "btn btn-danger",
                       "Permanently delete this session and its records? This cannot be undone."))
    return "".join(out) or '<span class="muted">No actions in this state.</span>'


def _moderation_panel(sid, s, moderation):
    """Interviewer control over which question each problem shows the candidate.
    Only meaningful before the session closes."""
    if s["state"] not in ("created", "active") or not moderation:
        return ""

    def mod_btn(pid, target, label, cls="btn btn-sm", confirm=None):
        cls_attr, extra = theme.confirm_attrs(cls, confirm)
        inner = (f'<input type="hidden" name="released" value="{int(target)}">'
                 f'<button class="{cls_attr}"{extra} type="submit">{esc(label)}</button>')
        return _post_form(f"/admin/sessions/{esc(sid)}/moderate/{esc(pid)}", inner)

    rows = ""
    for p in moderation:
        released, total = p["released"], p["total"]
        if released <= 0:
            status = '<span class="label st-reset">hidden</span>'
        elif released >= total:
            status = f'<span class="label st-active">all {total} shown</span>'
        else:
            status = f'<span class="label st-active">showing Q1–Q{released} of {total}</span>' if released > 1 \
                else f'<span class="label st-active">showing Q1 of {total}</span>'
        acts = []
        if released <= 0:
            acts.append(mod_btn(p["id"], 1, "Show Q1", cls="btn btn-sm btn-primary"))
        else:
            if released < total:
                nxt = p["next_title"] or f"Q{released + 1}"
                acts.append(mod_btn(p["id"], released + 1, f"Next → Q{released + 1}",
                                    cls="btn btn-sm btn-primary",
                                    confirm=f"Reveal “{nxt}” to the candidate? "
                                            "They must click Refresh on the Problems page to see it."))
            acts.append(mod_btn(p["id"], 0, "Hide"))
        rows += (f'<tr><td>{esc(p["title"])}<div class="muted small mono">{esc(p["id"])}</div></td>'
                 f'<td>{status}</td><td><div class="row">{"".join(acts)}</div></td></tr>')
    return f"""<div class="box">
  <div class="box-header"><h2>Problem moderation</h2>
    <span class="muted small">the candidate refreshes their Problems page to see changes</span></div>
  <table class="table"><thead><tr><th>Problem</th><th>Candidate sees</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def _review_button(sid, has_review):
    """Live only when an uploaded review claims this session. Nothing in
    the app writes reviews — they arrive as Markdown in `config/reviews/`, so with no
    file the honest control is a disabled button that says where one would come from."""
    if has_review:
        return (f'<a class="btn btn-sm" href="/admin/sessions/{sid}/review" target="_blank" '
                f'rel="noopener" title="Open the uploaded AI review for this session, '
                f'print-styled for PDF">AI Review</a>')
    return ('<button class="btn btn-sm" type="button" disabled '
            'title="No review has been uploaded for this session — add a Markdown file '
            'to config/reviews/ naming this session id or candidate.">AI Review</button>')


def admin_session_detail(who, s, moderation=None, notice=None, reactivate=None,
                         has_review=False):
    sid = esc(s["id"])
    fields = [
        ("Candidate", s["candidate_name"]),
        ("Workspace user", s["workspace_user"]),
        ("Access code", s["access_code"]),
        ("Problems", ", ".join(s["problem_ids"]) or "—"),
        ("Duration", f"{s['duration_minutes']} min"),
        ("Starts / ends", f"{s['starts_at'] or '—'} → {s['ends_at'] or '—'}"),
        ("LLM", f"${s['llm_budget_usd']:.2f} · {', '.join(s['llm_models'])}"),
        ("Internet", "full" if s["internet_access"] else "restricted"),
        ("Terms accepted", s["terms_accepted_at"] or "not yet"),
    ]
    dl = "".join(f'<dt>{esc(k)}</dt><dd class="mono">{esc(v)}</dd>' for k, v in fields)
    body = f"""{theme.flash(notice)}
<div class="box">
  <div class="box-header"><h2>Details</h2>
    <div class="row">
      {_review_button(sid, has_review)}
      <a class="btn btn-sm" href="/admin/sessions/{sid}/handout" target="_blank" rel="noopener"
         title="Print the candidate's URL, access code, instructions and terms">Export PDF handout</a>
    </div>
  </div>
  <div class="box-body"><dl class="dl-grid">{dl}</dl></div>
</div>
<div class="box">
  <div class="box-header"><h2>Actions</h2></div>
  <div class="box-body"><div class="row">{_actions_for(s, sid, reactivate)}</div></div>
</div>
{_moderation_panel(sid, s, moderation)}
{theme.confirm_dialog()}"""
    return _detail_page(f"{s['candidate_name']} · Admin", body, who, s, "overview")


# --- candidate handout (print → PDF) ----------------------------------------
# Wording lives in config/handout.md; handout.py reads it per request.
# Only the sheet's layout is here.
#
# Deliberately standalone (no dark theme, no app chrome): this document exists to be
# printed to PDF, so it is sized to one page and styled black-on-white.
_HANDOUT_CSS = """
/* No `size:` — the sheet fits A4 and Letter, so let the printer's paper win. */
@page { margin: 13mm; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f8fa; color: #111;
  font: 10.5pt/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.sheet { background: #fff; max-width: 190mm; margin: 16px auto; padding: 14mm; }
.toolbar { max-width: 190mm; margin: 16px auto -8px; display: flex; gap: 8px;
  justify-content: flex-end; }
.toolbar a, .toolbar button { font: inherit; font-size: 9.5pt; padding: 5px 14px;
  border-radius: 6px; border: 1px solid #d0d7de; background: #fff; color: #111;
  text-decoration: none; cursor: pointer; }
.toolbar button { background: #1f883d; border-color: #1a7f37; color: #fff; }

.head { display: flex; align-items: center; gap: 10px;
  border-bottom: 2px solid #111; padding-bottom: 9px; }
.head svg { width: 30px; height: 30px; color: #111; }
.head h1 { font-size: 15pt; font-weight: 700; margin: 0; letter-spacing: -.01em; }
.head .sub { margin: 1px 0 0; font-size: 9pt; color: #57606a; }

.lead { margin: 12px 0 0; font-size: 11pt; }
.lead p { margin: 0 0 4px; }

.keys { display: flex; flex-direction: column; gap: 8px; margin: 12px 0 0; }
.keybox { border: 2px solid #111; border-radius: 8px; padding: 9px 16px; text-align: center; }
.keybox .cap { font-size: 8pt; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: #57606a; margin: 0 0 3px; }
.keybox .url { font-size: 18pt; font-weight: 700; line-height: 1.2;
  overflow-wrap: break-word; }
.keybox .code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 30pt; font-weight: 700; letter-spacing: .18em; text-indent: .18em;
  line-height: 1.15; }

/* Everything below styles what mdrender emits from config/handout.md. `##` in that
   file arrives here as <h3> (mdrender demotes one level); h2/h4 are styled the same
   so a `#` or `###` heading still reads as a section rule. */
.content h2, .content h3, .content h4 { font-size: 9pt; font-weight: 700;
  letter-spacing: .09em; text-transform: uppercase; color: #57606a; margin: 15px 0 6px;
  padding-bottom: 4px; border-bottom: 1px solid #d0d7de; }
.content p { margin: 5px 0; }
.content ol, .content ul { margin: 0; padding-left: 18px; }
.content li { margin: 4px 0; }
/* A list item opening with {icon:…}: the icon replaces the bullet. Exactly two flex
   children — icon, then a <span> holding all the text (handout._ICON_LI adds it), so the
   8px gap lands once and the prose wraps as one paragraph. */
.content li.ico { list-style: none; margin-left: -18px; display: flex;
  align-items: flex-start; gap: 8px; }
.content li.ico > span { flex: 1; min-width: 0; }
.content svg { width: 16px; height: 16px; flex: none; margin-top: 1px; }
.content code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9.5pt; }

.terms { display: block; white-space: pre-wrap; font-size: 9pt; line-height: 1.4;
  color: #24292f; }

.foot { margin-top: 16px; border-top: 1px solid #d0d7de; padding-top: 8px;
  display: flex; justify-content: space-between; gap: 12px; font-size: 8.5pt;
  color: #57606a; }
.foot .cr { white-space: nowrap; }
.foot .note { font-weight: 700; color: #111; text-align: right; }

@media print {
  body { background: #fff; }
  .toolbar { display: none; }
  .sheet { margin: 0; padding: 0; max-width: none; }
}
"""


def session_handout(s, url):
    """Printable one-page information sheet for the candidate: where to go, the access
    code, what to do, what they get, and the terms (informational — acceptance still
    happens in the portal). Print-to-PDF from the browser; no PDF dependency.

    The wording comes from config/handout.md via handout.content(); this function owns
    only the frame around it — brand mark, the URL/access-code boxes, and the footer."""
    c = handout.content({
        "url": url,
        "access_code": s["access_code"],
        "candidate_name": s["candidate_name"],
        "terms": s.get("terms_text") or views.DEFAULT_TERMS,
    })
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Interview handout — {esc(s['candidate_name'])}</title>
<style>{_HANDOUT_CSS}</style></head>
<body>
<div class="toolbar">
  <a href="/admin/sessions/{esc(s['id'])}">← Back to session</a>
  <button type="button" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="sheet">
  <div class="head">
    {theme.BRAND_MARK}
    <div><h1>{esc(c['title'])}</h1>
      <p class="sub">{esc(c['subtitle'])}</p></div>
  </div>

  <div class="lead">{c['lead_html']}</div>

  <div class="keys">
    <div class="keybox"><p class="cap">{esc(c['url_label'])}</p>
      <div class="url">{esc(url)}</div></div>
    <div class="keybox"><p class="cap">{esc(c['code_label'])}</p>
      <div class="code">{esc(s['access_code'])}</div></div>
  </div>

  <div class="content">{c['body_html']}</div>

  <div class="foot">
    <span class="cr">{esc(c['copyright'])}</span>
    <span class="note">{esc(c['notice'])}</span>
  </div>
</div>
<script>window.addEventListener('load', function(){{ window.print(); }});</script>
</body></html>"""


# --- AI hiring review (print → PDF) -----------------------------------------
# The text lives in config/reviews/<file>.md; reviews.py reads it per
# request. Only the frame is here: the AI-generated banner, the verdict block, and the
# page furniture.
#
# Standalone like the handout — black-on-white, print-first — but multi-page: it is read
# by executives, so the rules are "the verdict is visible without scrolling" and "every
# printed page carries the AI-generated mark" (the running footer below).
_REVIEW_CSS = """
@page { margin: 15mm 14mm; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f8fa; color: #111;
  font: 10.5pt/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.sheet { background: #fff; max-width: 190mm; margin: 16px auto; padding: 14mm; }
.toolbar { max-width: 190mm; margin: 16px auto -8px; display: flex; gap: 8px;
  justify-content: flex-end; }
.toolbar a, .toolbar button { font: inherit; font-size: 9.5pt; padding: 5px 14px;
  border-radius: 6px; border: 1px solid #d0d7de; background: #fff; color: #111;
  text-decoration: none; cursor: pointer; }
.toolbar button { background: #1f883d; border-color: #1a7f37; color: #fff; }

.head { display: flex; align-items: center; gap: 10px;
  border-bottom: 2px solid #111; padding-bottom: 9px; }
.head svg { width: 30px; height: 30px; color: #111; }
.head h1 { font-size: 15pt; font-weight: 700; margin: 0; letter-spacing: -.01em; }
.head .sub { margin: 1px 0 0; font-size: 9pt; color: #57606a; }

/* The provenance mark. Deliberately the first thing on the page and impossible to read
   as decoration: this document is machine-written and must never pass as a sign-off. */
.ai { margin: 12px 0 0; border: 1.5px solid #111; border-radius: 8px;
  padding: 8px 12px; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.ai .tag { font-size: 8pt; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; background: #111; color: #fff; padding: 3px 8px;
  border-radius: 4px; white-space: nowrap; }
.ai .txt { font-size: 9pt; color: #24292f; flex: 1; min-width: 12rem; }
.ai .model { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700; color: #111; }

/* Scope and limits — the second half of the same disclaimer, kept visually attached to
   the banner and above the verdict so it cannot be skimmed past. Emitted by the layout,
   so no uploaded file can drop it. */
.limits { margin: 6px 0 0; border: 1px solid #d0d7de; border-radius: 8px;
  padding: 8px 12px; font-size: 8.5pt; line-height: 1.45; color: #24292f; }
.limits .cap { font-size: 8pt; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: #57606a; margin: 0 0 3px; }
.limits p { margin: 0 0 3px; }
.limits p:last-child { margin-bottom: 0; }
.limits strong { color: #111; }

.verdict { margin: 12px 0 0; border: 2px solid #111; border-radius: 8px; padding: 11px 16px; }
.verdict .cap { font-size: 8pt; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: #57606a; margin: 0 0 3px; }
.verdict .rating { font-size: 19pt; font-weight: 700; line-height: 1.15;
  letter-spacing: -.01em; }
.verdict .line { margin: 5px 0 0; font-size: 10pt; }
.verdict .conf { margin: 3px 0 0; font-size: 9pt; color: #57606a; }

.facts { margin: 12px 0 0; display: grid; grid-template-columns: max-content 1fr;
  gap: 3px 14px; font-size: 9pt; }
.facts dt { font-weight: 700; color: #57606a; }
.facts dd { margin: 0; }

/* Body Markdown from reviews.py. `##` in the file arrives as <h3> (mdrender demotes one
   level); h2/h4 match so any heading depth still reads as a section rule. */
.content { margin-top: 4px; }
.content h2, .content h3, .content h4 { font-size: 9pt; font-weight: 700;
  letter-spacing: .09em; text-transform: uppercase; color: #57606a; margin: 16px 0 6px;
  padding-bottom: 4px; border-bottom: 1px solid #d0d7de; break-after: avoid;
  page-break-after: avoid; }
.content p { margin: 6px 0; }
.content ol, .content ul { margin: 6px 0; padding-left: 18px; }
.content li { margin: 3px 0; }
.content strong { color: #111; }
.content hr { border: 0; border-top: 1px solid #d0d7de; margin: 14px 0; }
.content blockquote { margin: 8px 0; padding: 2px 0 2px 12px;
  border-left: 3px solid #d0d7de; color: #24292f; }
.content code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9pt; }
.content table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt;
  break-inside: avoid; page-break-inside: avoid; }
.content th, .content td { border: 1px solid #d0d7de; padding: 4px 8px;
  text-align: left; vertical-align: top; }
.content th { background: #f6f8fa; font-size: 8.5pt; letter-spacing: .04em;
  text-transform: uppercase; color: #57606a; }

.foot { margin-top: 18px; border-top: 1px solid #d0d7de; padding-top: 8px;
  display: flex; justify-content: space-between; gap: 12px; font-size: 8.5pt;
  color: #57606a; }
.foot .cr { white-space: nowrap; }
.foot .note { font-weight: 700; color: #111; text-align: right; }

/* Running footer: repeats the provenance on every sheet that comes off the printer, so
   a page separated from the stack still says what wrote it. */
.runfoot { display: none; }
@media print {
  body { background: #fff; }
  .toolbar { display: none; }
  .sheet { margin: 0; padding: 0; max-width: none; }
  .runfoot { display: block; position: fixed; bottom: -10mm; left: 0; right: 0;
    font-size: 7.5pt; color: #57606a; border-top: .5pt solid #d0d7de; padding-top: 3px; }
}
"""


def session_review(s, c):
    """Printable AI hiring review for one session. `c` is `reviews.content(...)` — the
    uploaded Markdown plus its frontmatter; this function owns only the frame.

    Provenance and scope are emitted here rather than left to the file: an
    uploader can narrow the `scope` sentence but cannot drop the AI-generated banner, the
    Scope and limits block, or the running footer. Both sit above the verdict, because a
    reader who skims one block should not be the one who misses the caveat.

    The rest of the ordering is deliberate too: the verdict sits above the fold, and the
    session's own timeline facts (window, evidence) print beside it so a reader can weigh
    the verdict against how much time the candidate actually had."""
    def fact(label, value):
        return (f"<dt>{esc(label)}</dt><dd>{esc(value)}</dd>") if value else ""

    facts = "".join([
        fact("Candidate", c["candidate"] or s["candidate_name"]),
        fact("Session", c["session_label"]),
        fact("Working window", c["window"]),
        fact("Evidence", c["evidence"]),
        fact("Generated", c["generated"]),
    ])
    conf = (f'<p class="conf">Confidence: {esc(c["confidence"])}</p>'
            if c["confidence"] else "")
    verdict = f'<p class="line">{esc(c["verdict"])}</p>' if c["verdict"] else ""
    rating = c["rating"] or "See review"
    model = esc(c["model"])
    scope = esc(c["scope"])
    name = esc(c["candidate"] or s["candidate_name"])
    subtitle = name + (f' · {esc(c["session_label"])}' if c["session_label"] else "")
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI review — {name}</title>
<style>{_REVIEW_CSS}</style></head>
<body>
<div class="toolbar">
  <a href="/admin/sessions/{esc(s['id'])}">← Back to session</a>
  <button type="button" onclick="window.print()">Print / Save as PDF</button>
</div>
<div class="sheet">
  <div class="head">
    {theme.BRAND_MARK}
    <div><h1>{esc(c['title'])}</h1>
      <p class="sub">{subtitle}</p></div>
  </div>

  <div class="ai">
    <span class="tag">AI generated</span>
    <span class="txt">Written by <span class="model">{model}</span> from the captured
      session artifact. Not a human hiring decision — read it as evidence, alongside the
      interviewer's own notes.</span>
  </div>

  <div class="limits">
    <p class="cap">Scope and limits</p>
    <p>This analysis read <strong>only part of</strong> the tracked workspace —
      {scope}. It did not observe the session live.</p>
    <p>Anything spoken, shown on screen, or reasoned aloud left no trace in the record,
      and problems that were never released were never assessed. Absence of evidence here
      is often absence of capture, not absence of ability.</p>
    <p><strong>For reference only.</strong> Use it to decide what to probe next — not as
      a decision record, and not as a substitute for the interviewer's own judgement.</p>
  </div>

  <div class="verdict">
    <p class="cap">Recommendation</p>
    <div class="rating">{esc(rating)}</div>
    {verdict}{conf}
  </div>

  <dl class="facts">{facts}</dl>

  <div class="content">{c['body_html']}</div>

  <div class="foot">
    <span class="cr">{esc(c['copyright'])}</span>
    <span class="note">AI generated · {model} · reference only</span>
  </div>
</div>
<div class="runfoot">AI-generated hiring review · {model} · {name} ·
  partial view of the tracked workspace · reference only, not a human hiring decision</div>
</body></html>"""


# --- Problems tab -----------------------------------------------------------
def _deliverability_panel(report):
    """Result of the "Validate data deliverability" dry-run: per-problem OK/FAIL and
    the candidate files each would ship (or the reason it would not)."""
    if not report:
        return ""
    if report.get("error") and not report.get("problems"):
        return (f'<div class="box"><div class="box-header"><h2>Data deliverability</h2></div>'
                f'<div class="box-body"><div class="flash flash-err" style="margin:0">'
                f'could not run the check — {esc(report["error"])}</div></div></div>')
    rows = ""
    for p in report["problems"]:
        if p["ok"]:
            pill = '<span class="label st-active">deliverable</span>'
            detail = f'<span class="mono muted small">{esc(", ".join(p["files"]))}</span>'
        else:
            pill = '<span class="label st-closed">missing</span>'
            detail = f'<span style="color:var(--danger)">{esc(p["error"] or "no candidate data")}</span>'
        rows += (f'<tr><td class="mono">{esc(p["id"])}</td>'
                 f'<td>{pill}</td><td>{detail}</td></tr>')
    banner = (theme.flash("All problems would ship a candidate dataset.")
              if report["ok"] else
              theme.flash("Some problems would start the candidate with missing data — fix before activating.", "err"))
    return f"""<div class="box">
  <div class="box-header"><h2>Data deliverability</h2></div>
  <div class="box-body" style="padding-bottom:0">{banner}</div>
  <table class="table"><thead><tr><th>Problem</th><th>Status</th><th>Would ship</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""


def problems_admin_page(who, all_problems, deliver_report=None, notice=None):
    rows = ""
    for p in all_problems or []:
        visible = p["visible"]
        pill = ('<span class="label st-active">visible</span>' if visible
                else '<span class="label st-reset">hidden</span>')
        action = "0" if visible else "1"
        label = "Hide" if visible else "Show"
        rows += (
            f'<tr><td>{esc(p["title"])}<div class="muted small mono">{esc(p["id"])}</div></td>'
            f'<td>{pill}</td><td style="text-align:right">'
            f'<form class="inline" method="post" action="/admin/problems/{esc(p["id"])}/visibility">'
            f'<input type="hidden" name="visible" value="{action}">'
            f'<button class="btn btn-sm" type="submit">{label}</button>'
            f'</form></td></tr>')
    table = (f'<table class="table"><thead><tr><th>Problem</th><th>Status</th><th></th></tr></thead>'
             f'<tbody>{rows}</tbody></table>') if rows else \
        '<div class="blankslate">No problems in the registry.</div>'
    body = f"""{theme.flash(notice)}
<div class="subhead">
  <h2>Problem registry</h2>
  <form class="inline" method="post" action="/admin/problems/validate-data">
    <button class="btn btn-sm" type="submit">Validate data deliverability</button>
  </form>
</div>
<p class="muted small" style="margin:-8px 0 16px">Hidden problems are not offered when
creating a session. Validation dry-runs the packager to confirm each problem would ship
a candidate dataset.</p>
<div class="box">{table}</div>
{_deliverability_panel(deliver_report)}"""
    return _page("Problems · Admin", body, who, tab="problems")


# --- LLM proxy tab ----------------------------------------------------------
def llm_admin_page(who, llm_key, llm_test=None, models_info=None, notice=None):
    result = ""
    if llm_test is not None:
        kind = "ok" if llm_test["ok"] else "err"
        head = (f'Gemini replied via {esc(llm_test["model"])}' if llm_test["ok"]
                else f'Test failed ({esc(llm_test["model"])})')
        result = (f'<div class="flash flash-{kind}" style="margin:16px 0 0">{head}'
                  f'<pre class="code-block">{esc(llm_test["text"])}</pre></div>')
    if models_info is None:
        models_line = ""
    elif models_info["ok"] and models_info["models"]:
        pills = " ".join(f'<span class="label mono">{esc(m)}</span>' for m in models_info["models"])
        models_line = f'<div class="row" style="margin-top:8px">{pills}</div>'
    else:
        why = esc(models_info.get("error") or "no models") if models_info else ""
        models_line = f'<p class="muted small" style="margin:8px 0 0">Models served: unavailable ({why})</p>'
    body = f"""{theme.flash(notice)}
<div class="subhead"><h2>unillm proxy</h2></div>
<div class="box">
  <div class="box-header"><h2>Status</h2>
    <form class="inline" method="post" action="/admin/llm/test">
      <button class="btn btn-sm" type="submit">Test Gemini</button>
    </form>
  </div>
  <div class="box-body">
    <p style="margin:0" class="muted small">Candidates call
      <span class="mono">http://localhost:8081/v1</span> with their per-session key ·
      Gemini models only.</p>
    {models_line}{result}
  </div>
</div>
<div class="box">
  <div class="box-header"><h2>Platform master key</h2></div>
  <div class="box-body">
    <p class="muted small" style="margin:0 0 8px">Server-side only — never enters a
      workspace. Each session gets its own key, minted at activation and revoked at close.</p>
    <div class="token-box"><code>{esc(llm_key)}</code>{theme.copy_button(llm_key)}</div>
  </div>
</div>
{theme.COPY_SCRIPT}"""
    return _page("LLM proxy · Admin", body, who, tab="llm")


# --- Settings tab -----------------------------------------------------------
def settings_page(who, notice=None, error=None):
    body = f"""{theme.flash(notice)}{theme.flash(error, "err")}
<div class="subhead"><h2>Settings</h2></div>
<div class="box" style="max-width:440px">
  <div class="box-header"><h2>Change password</h2></div>
  <div class="box-body">
  <form method="post" action="/admin/password">
    <label for="cp">Current password</label>
    <input type="password" id="cp" name="current_password" required autocomplete="current-password">
    <label for="np">New password</label>
    <input type="password" id="np" name="new_password" required autocomplete="new-password" minlength="8">
    <label for="pp">Confirm new password</label>
    <input type="password" id="pp" name="confirm_password" required autocomplete="new-password" minlength="8">
    <button type="submit" class="btn btn-primary" style="margin-top:16px">Update password</button>
  </form>
  </div>
</div>"""
    return _page("Settings · Admin", body, who, tab="settings")


# --- multiple-choice answer sheet ----------------
def _answer_status(a):
    """Where a question stands. There is no submit step, so this is binary — answered or
    not — and 'answered' includes deliberately clearing every box."""
    if not a:
        return '<span class="label">Not answered</span>'
    return '<span class="label st-active">Answered</span>'


def _answer_trail(trail):
    if not trail:
        return '<p class="muted small" style="margin:8px 0 0">No activity recorded.</p>'
    rows = "".join(
        f'<tr><td class="mono small">{_fmt_ts(t["ts"])}</td>'
        f'<td class="mono small">{esc(", ".join(t["previous"]) or "—")}</td>'
        f'<td class="mono small"><strong>{esc(", ".join(t["selected"]) or "—")}</strong></td></tr>'
        for t in trail
    )
    return f"""<details style="margin-top:10px">
  <summary class="muted small">Edit trail — {len(trail)} change{"" if len(trail) == 1 else "s"}</summary>
  <table class="table" style="margin-top:8px">
    <thead><tr><th>When (UTC)</th><th>From</th><th>To</th></tr></thead>
    <tbody>{rows}</tbody></table>
</details>"""


def _answer_question(q):
    a = q.get("answer")
    chosen = set((a or {}).get("selected") or [])
    opts = "".join(
        f'<li class="{"mcq-picked" if o["key"] in chosen else "muted"}">'
        f'<strong>{esc(o["key"])}.</strong> {esc(o["text"])}'
        f'{" ←" if o["key"] in chosen else ""}</li>'
        for o in q["options"]
    )
    picked = ", ".join(sorted(chosen)) or "—"
    when = _fmt_ts((a or {}).get("updated_at")) if a else "—"
    revs = (a or {}).get("revision") or 0
    return f"""<div class="box" style="margin-bottom:12px">
  <div class="box-header">
    <div><h2>{esc(q["title"])}</h2>
      <p class="muted small mono" style="margin:2px 0 0">{esc(q["qid"])}</p></div>
    {_answer_status(a)}
  </div>
  <div class="box-body">
    <p style="margin:0 0 8px"><span class="muted small">Selected</span>
      <span class="mono" style="font-size:16px;font-weight:600">{esc(picked)}</span>
      <span class="muted small">· {revs} change{"" if revs == 1 else "s"} · last {when}</span></p>
    <ul style="margin:0;padding-left:20px;line-height:1.6">{opts}</ul>
    {_answer_trail(q["trail"])}
  </div>
</div>"""


def admin_answers_page(who, s, problems):
    """The interviewer's answer sheet. Shows what was selected and when it changed —
    never a rubric key, which this service does not read."""
    if not problems:
        body = ('<div class="box"><div class="blankslate">'
                'None of this session\'s problems have multiple-choice questions.'
                '</div></div>')
    else:
        body = ""
        for p in problems:
            answered = sum(1 for q in p["questions"] if q.get("answer"))
            body += (f'<h2 class="page-title" style="font-size:16px;margin:16px 0 8px">'
                     f'{esc(p["id"])} <span class="muted small">— {answered} of '
                     f'{len(p["questions"])} answered</span></h2>')
            body += "".join(_answer_question(q) for q in p["questions"])
    return _detail_page("Answers", body, who, s, "answers")


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
    cls = {"api": "st-active", "ui": "st-created", "admin-test": "st-exported"}.get(src, "")
    return f'<span class="label {cls}">{esc(label)}</span>'


def _transcript_entry(e):
    src = e.get("source") or "api"
    head_bits = [_source_pill(src), f'<span class="mono muted small">{_fmt_ts(e.get("ts"))}</span>',
                 f'<span class="label mono">{esc(e.get("model") or "?")}</span>']
    if e.get("stream"):
        head_bits.append('<span class="label">stream</span>')
    if e.get("latency_ms") is not None:
        head_bits.append(f'<span class="muted small">{esc(e["latency_ms"])} ms</span>')
    u = e.get("usage") or {}
    if u:
        toks = u.get("total_tokens")
        if toks is None:
            toks = (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        head_bits.append(f'<span class="muted small">{esc(toks)} tok</span>')

    def block(label, text):
        return (f'<p class="code-label">{esc(label)}</p>'
                f'<pre class="code-block" style="white-space:pre-wrap">{esc(text)}</pre>')

    parts = []
    for m in e.get("messages") or []:
        if isinstance(m, dict):
            parts.append(block(m.get("role") or "message", m.get("content") or ""))
    if e.get("prompt"):
        parts.append(block("prompt", e["prompt"]))
    if e.get("response"):
        parts.append(block("response", e["response"]))
    if e.get("error"):
        parts.append(f'<div class="flash flash-err" style="margin:8px 0 0">{esc(e["error"])}</div>')
    return (f'<div class="box"><div class="box-body">'
            f'<div class="row">{"".join(head_bits)}</div>'
            f'{"".join(parts)}</div></div>')


def admin_transcript_page(who, s, data, source=None, query=None):
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
    summary = f'{total} call{"s" if total != 1 else ""}{cap_note}'
    entries_html = "".join(_transcript_entry(e) for e in entries) or \
        '<div class="box"><div class="blankslate">No LLM calls recorded for this session yet.</div></div>'
    body = f"""<div class="box" style="margin-bottom:16px"><div class="box-body">
  <form method="get" action="/admin/sessions/{sid}/transcript" class="row" style="align-items:flex-end">
    <div><label for="src" style="margin-top:0">Source</label>
      <select id="src" name="source" style="width:auto;min-width:10rem">{"".join(opts)}</select></div>
    <div style="flex:1;min-width:12rem"><label for="q" style="margin-top:0">Search</label>
      <input type="text" id="q" name="q" value="{esc(query or "")}" placeholder="prompt or response contains…"></div>
    <button type="submit" class="btn">Apply</button>
    <a class="btn" href="/admin/sessions/{sid}/transcript">Clear</a>
  </form>
  <p class="muted small" style="margin:8px 0 0">{esc(summary)} · source is attributed by
    the proxy from the authenticating key: <b>Direct API call</b> = the candidate's own
    workspace call, <b>UI playground</b> = the portal Gemini page. Refresh re-reads the
    live transcript.</p>
</div></div>
{entries_html}"""
    return _detail_page(f"Transcript — {s['candidate_name']}", body, who, s, "transcript")


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


def _provision_panel(sid, s, cwd, provision_status=None):
    """Per-problem provision / reset controls for ALL of the session's assigned problems.
    A problem that ships no dataset (no ``data/`` in the seed) is listed and labelled as
    such — never silently dropped. ``provision_status`` is a list of (problem_id, has_data).
    """
    status = provision_status if provision_status is not None else \
        [(p, True) for p in (s["problem_ids"] or [])]
    if not status:
        return ""
    cwd_h = f'<input type="hidden" name="cwd" value="{esc(cwd)}">'
    any_data = any(has for _, has in status)

    def form(action, pid, label, cls="btn btn-sm", confirm=None):
        cls_attr, extra = theme.confirm_attrs(cls, confirm)
        return (f'<form class="inline" method="post" action="/admin/sessions/{sid}/files/{action}">'
                f'{cwd_h}<input type="hidden" name="problem_id" value="{esc(pid)}">'
                f'<button class="{cls_attr}"{extra} type="submit">{esc(label)}</button></form>')

    rows = ""
    for p, has in status:
        if has:
            actions = (f'<div class="row" style="justify-content:flex-end">{form("provision", p, "Provision")}'
                       f'{form("reset", p, "Reset", confirm=f"Reset data/{p}/ to the seeded original? Candidate edits to that data are lost.")}</div>')
            folder = f'data/{esc(p)}'
        else:
            actions = '<span class="muted small">ships no dataset — nothing to provision</span>'
            folder = esc(p)
        rows += f'<tr><td class="mono">{folder}</td><td style="text-align:right">{actions}</td></tr>'

    bulk = ""
    if any_data:
        bulk = (f'{form("provision", "all", "Provision all")}'
                f'{form("reset", "all", "Reset all data", confirm="Reset ALL assigned problem data/ to the seeded original? Candidate edits to data/ are lost.")}')

    wipe = (f'<form class="inline" method="post" action="/admin/sessions/{sid}/files/wipe">{cwd_h}'
            f'<button class="btn btn-sm btn-danger js-confirm" '
            f'data-confirm="WIPE the entire workspace — delete the candidate\'s notebooks, code, and '
            f'every file. This does NOT re-provision anything; the workspace will be empty. '
            f'This cannot be undone." type="submit">Wipe workspace</button></form>')

    return f"""<div class="box" style="margin-bottom:16px">
  <div class="box-header"><h2>Problem data ({len(status)} assigned)</h2>
    <div class="row">{bulk}{wipe}</div></div>
  <table class="table"><tbody>{rows}</tbody></table>
  <div class="box-row muted small">Provision copies a problem's seeded dataset
    <strong>read-only</strong> into <span class="mono">~/workspace/data/&lt;problem&gt;/</span>
    (the candidate can read but not overwrite it); reset restores it to the original,
    discarding candidate edits. Neither ships solutions, rubrics, or generators.</div>
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
                f'<button class="btn btn-sm btn-danger js-confirm"'
                f' data-confirm="Delete {esc(e["name"])}{"/ and everything in it" if e["is_dir"] else ""} from the workspace?"'
                f' type="submit">Remove</button></form>')
    return (f'<tr><td>{name}</td><td class="mono muted small">{size}</td>'
            f'<td class="mono muted small">{_fmt_epoch(e["mtime"])}</td>'
            f'<td style="text-align:right">{del_form}</td></tr>')


def admin_files_page(who, s, listing=None, view=None, available=True,
                     unavailable_reason=None, error=None, notice=None,
                     provision_status=None):
    sid = esc(s["id"])
    banners = theme.flash(notice) + theme.flash(error, "err")
    refresh = (f'<div class="row row-split" style="margin-bottom:12px">'
               f'<span></span><a class="btn btn-sm" href="/admin/sessions/{sid}/files">Refresh</a></div>')

    if not available:
        body = (f'{banners}<div class="box"><div class="blankslate">The workspace isn\'t '
                f'available for this session — {esc(unavailable_reason or "not provisioned")}.</div></div>')
        return _detail_page(f"Files — {s['candidate_name']}", body, who, s, "files")

    if view is not None:
        rel = view["rel"]
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        back = f"/admin/sessions/{sid}/files?path={urllib.parse.quote(parent)}"
        meta = f'{_fmt_bytes(view["size"])}{" · truncated" if view.get("truncated") else ""}'
        if view["binary"]:
            content = '<div class="blankslate">Binary file — not shown.</div>'
        else:
            content = f'<pre class="code-block" style="white-space:pre-wrap;max-height:70vh;overflow:auto;margin:0;border:0;border-radius:0 0 6px 6px">{esc(view["text"])}</pre>'
        body = f"""{banners}
<p style="margin:0 0 8px">{_crumbs(sid, rel)}</p>
<div class="box">
  <div class="box-header"><h2 class="mono">{esc(rel)}</h2>
    <span class="muted small mono">{esc(meta)}</span></div>
  {content}
</div>
<div class="row" style="margin-top:12px"><a class="btn btn-sm" href="{back}">← Back to folder</a></div>"""
        return _detail_page(f"Files — {s['candidate_name']}", body, who, s, "files")

    listing = listing or {"path": "", "entries": []}
    cwd = listing.get("path", "")
    rows = "".join(_file_row(sid, e) for e in listing["entries"]) or \
        '<tr><td colspan="4"><div class="blankslate">Empty folder.</div></td></tr>'
    body = f"""{banners}
{_provision_panel(sid, s, cwd, provision_status)}
<div class="row row-split" style="margin-bottom:8px">
  <p style="margin:0">{_crumbs(sid, cwd)}</p>
  <a class="btn btn-sm" href="/admin/sessions/{sid}/files?path={urllib.parse.quote(cwd)}">Refresh</a>
</div>
<div class="box">
  <table class="table"><thead><tr><th>Name</th><th>Size</th><th>Modified (UTC)</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>
{theme.confirm_dialog()}"""
    return _detail_page(f"Files — {s['candidate_name']}", body, who, s, "files")
