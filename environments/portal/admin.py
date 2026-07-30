#!/usr/bin/env python3
"""the portal admin panel (admin on :8001, routes `/admin/*`).

Runs the whole session lifecycle: create → activate (provision workspace + LLM key)
→ extend/close → export → reset. Auth is a cookie session over the `admins` table
(real admin accounts, no shared logins). Every transition lands in
events.jsonl via model.*.
"""
from __future__ import annotations

import os
import re

import db
import gitread
import integrations
import model
import registry
import reviews
import views_admin as views
from server import Response, Router, serve

COOKIE = "admin"
router = Router()


def _admin(req):
    token = req.cookies.get(COOKIE)
    return model.verify_admin(token) if token else None


def _require(req):
    who = _admin(req)
    return who, (None if who else Response.redirect("/admin"))


# Session ids are server-generated uuids. Anything else arriving in the path is
# hostile: the router unquotes segments AFTER splitting, so "..%2f..%2f" decodes into
# a traversal once it hits os.path.join. Reject before any filesystem use.
_SID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _bad_sid(sid):
    return not _SID_OK.fullmatch(sid or "")


@router.route("GET", "/healthz")
def healthz(req):
    return Response.text("ok")


UNILLM_MASTER_KEY = os.environ.get("UNILLM_MASTER_KEY", "sk-unillm-dev-change-me")
# Candidate-facing URL printed on the handout — not used for routing.
PUBLIC_URL = os.environ.get("PORTAL_PUBLIC_URL", "https://interview.example.com/")


def _problems_page(who, deliver_report=None, notice=None):
    return Response.html(views.problems_admin_page(
        who, registry.all_problems(), deliver_report=deliver_report, notice=notice))


def _llm_page(who, llm_test=None, notice=None):
    return Response.html(views.llm_admin_page(
        who, UNILLM_MASTER_KEY, llm_test=llm_test,
        models_info=integrations.list_models(), notice=notice))


@router.route("POST", "/admin/problems/validate-data")
def validate_data(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    ids = [p["id"] for p in registry.all_problems()]
    return _problems_page(who, deliver_report=integrations.check_deliverable(ids))


@router.route("POST", "/admin/problems/<pid>/visibility")
def problem_visibility(req, pid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    visible = req.form.get("visible") == "1"
    registry.set_visibility(pid, visible)
    return Response.redirect(
        f"/admin/problems?notice={_q((pid + ' is now ' + ('visible' if visible else 'hidden')))}")


@router.route("GET", "/admin")
def dashboard(req):
    who = _admin(req)
    if not who:
        return Response.html(views.admin_login())
    return Response.html(views.sessions_page(
        who, model.list_sessions(), notice=req.query.get("notice")))


@router.route("GET", "/admin/problems")
def problems_tab(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    return _problems_page(who, notice=req.query.get("notice"))


@router.route("GET", "/admin/llm")
def llm_tab(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    return _llm_page(who, notice=req.query.get("notice"))


# --- Reports tab ---------------------------------
@router.route("GET", "/admin/reports")
def reports_tab(req):
    """Index of every uploaded report — per-session reviews and cross-session comparisons.
    The session list is passed only so each report can be resolved to the session(s) it
    covers; a report whose session is gone is still listed, marked unmatched."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    return Response.html(views.reports_page(
        who, reviews.index(model.list_sessions()), notice=req.query.get("notice")))


@router.route("GET", "/admin/reports/<slug>")
def report_view(req, slug):
    """One report, print-styled, either kind. `slug` is a filename stem — reviews.by_slug
    rejects anything that could name a path, so no filesystem check is needed here."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    c = reviews.report(slug)
    if c is None:
        # Nothing in the app writes reports, so a miss is a hand-typed URL or a file removed
        # between page load and click — say where one comes from rather than a bare 404.
        return Response.text(
            "no such report — reports are Markdown files uploaded to config/reviews/",
            status=404)
    return Response.html(views.report_page(c))


@router.route("GET", "/admin/settings")
def settings_tab(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    return Response.html(views.settings_page(who, notice=req.query.get("notice")))


@router.route("GET", "/admin/sessions/new")
def new_session_form(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    return Response.html(views.session_new_page(who, registry.load_problems()))


@router.route("POST", "/admin/llm/test")
def llm_test(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    return _llm_page(who, llm_test=integrations.gemini_healthcheck())


@router.route("POST", "/admin/login")
def login(req):
    who = model.authenticate_admin(req.form.get("username", ""), req.form.get("password", ""))
    if not who:
        return Response.html(views.admin_login(error="Invalid username or password."), status=401)
    resp = Response.redirect("/admin")
    resp.set_cookie(COOKIE, model.sign_admin(who), max_age=model.COOKIE_MAX_AGE)
    return resp


@router.route("POST", "/admin/logout")
def logout(req):
    who = _admin(req)
    if who:
        # Server-side invalidation: bump the epoch so the just-cleared cookie (and any
        # copy of it) stops verifying, not just the client-side clear.
        model.bump_cookie_epoch(who)
    resp = Response.redirect("/admin")
    resp.set_cookie(COOKIE, "", max_age=0)
    return resp


@router.route("POST", "/admin/password")
def change_password(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    current = req.form.get("current_password", "")
    new = req.form.get("new_password", "").strip()
    confirm = req.form.get("confirm_password", "").strip()
    if not model.authenticate_admin(who, current):
        return Response.html(views.settings_page(who, error="Current password is incorrect."))
    if len(new) < 8:
        return Response.html(views.settings_page(who, error="New password must be at least 8 characters."))
    if new != confirm:
        return Response.html(views.settings_page(who, error="New passwords do not match."))
    model.change_password(who, new)
    # The password change invalidated the current cookie's credential version;
    # re-issue one so the admin who just changed it isn't immediately logged out.
    resp = Response.html(views.settings_page(who, notice="Password changed successfully."))
    resp.set_cookie(COOKIE, model.sign_admin(who), max_age=model.COOKIE_MAX_AGE)
    return resp


@router.route("POST", "/admin/sessions")
def create(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    f = req.form
    try:
        s = model.create_session(
            candidate_name=f.get("candidate_name", "").strip(),
            workspace_user=f.get("workspace_user", "").strip(),
            access_code=f.get("access_code", "").strip() or None,
            duration_minutes=int(f.get("duration_minutes") or 90),
            llm_budget_usd=float(f.get("llm_budget_usd") or 5),
            llm_models=req.getlist("llm_models") or None,
            internet_access=f.get("internet_access", "1") == "1",
            terms_text=(f.get("terms_text") or "").strip() or None,
            problem_ids=req.getlist("problem_ids"),
            actor=who,
        )
    except ValueError as exc:
        return Response.html(views.session_new_page(
            who, registry.load_problems(), error=f"Could not create session: {exc}"))
    return Response.redirect(f"/admin/sessions/{s['id']}")


def _moderation_state(s):
    """Per-problem moderation rows for the session detail page: title, released count,
    total subproblems, and the title of the next question to reveal (for the confirm)."""
    released = model.all_released(s["id"])
    titles = {m["id"]: m["title"] for m in registry.problem_meta(s["problem_ids"])}
    rows = []
    for pid in s["problem_ids"]:
        meta = registry.part_meta(pid)
        r = released.get(pid, 0)
        subs = meta["subs"]
        next_title = subs[r]["title"] if (subs and r < len(subs)) else ""
        rows.append({"id": pid, "title": titles.get(pid, pid), "released": r,
                     "total": meta["total"], "next_title": next_title})
    return rows


@router.route("GET", "/admin/sessions/<sid>")
def detail(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    reactivate = None
    if s["state"] == "closed":
        left = model.minutes_left(s)
        reactivate = {
            "remaining": left,
            "min_minutes": model.REACTIVATE_MIN_MINUTES,
            # A fresh total is required only when the clock started and too little is left.
            "needs_total": left is not None and left < model.REACTIVATE_MIN_MINUTES,
        }
    return Response.html(views.admin_session_detail(
        who, s, moderation=_moderation_state(s), notice=req.query.get("notice"),
        reactivate=reactivate,
        has_review=reviews.exists(sid, s["candidate_name"]),
        comparisons=reviews.comparisons_for(sid),
        llm_spend=model.llm_spend_usd(sid),
        llm_cutoff_usd=s["llm_budget_usd"] * model.LLM_BUDGET_CUTOFF_FACTOR))


@router.route("GET", "/admin/sessions/<sid>/handout")
def handout(req, sid):
    """Print-to-PDF information sheet the interviewer hands the candidate: URL, access
    code, instructions, terms and a one-line summary of each tool. Admin-only — it
    carries the access code, so it must never be candidate-reachable."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    return Response.html(views.session_handout(s, PUBLIC_URL))


# --- AI hiring review (print → PDF) -----------------------------------------
@router.route("GET", "/admin/sessions/<sid>/review")
def review(req, sid):
    """The uploaded AI review for this session, print-styled so the browser's "Save as
    PDF" produces the executive-facing document. Nothing is generated here — the text is
    a Markdown file in `config/reviews/`, matched to the session by id or
    candidate name. Admin-only; reviews are never candidate-reachable."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    c = reviews.content(sid, s["candidate_name"])
    if c is None:
        # The button is disabled without a file, so this is a hand-typed URL or a review
        # deleted between page load and click — say which, rather than a bare 404.
        return Response.text("no review has been uploaded for this session", status=404)
    return Response.html(views.session_review(s, c))


# --- audit review surface: events timeline + snapshot viewer ------
# Both are READ-ONLY renderers over append-only streams (hard rule): nothing on
# these routes writes events.jsonl or shadow.git.
@router.route("GET", "/admin/sessions/<sid>/events")
def events_view(req, sid):
    """Session event timeline — every state transition, moderation release, MCQ change
    and copy action from events.jsonl, newest first, with the transcript viewer's
    filter pattern (event-type dropdown + substring search)."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    event = (req.query.get("event") or "").strip() or None
    query = (req.query.get("q") or "").strip() or None
    data = model.read_events(sid, event=event, query=query, limit=500)
    return Response.html(views.admin_events_page(who, s, data, event=event, query=query))


# A workspace file can be dataset-sized; never inline-render or diff more than this.
SNAPSHOT_MAX_BLOB = 256 * 1024


@router.route("GET", "/admin/sessions/<sid>/snapshots")
def snapshots_view(req, sid):
    """Commit list from the session's shadow.git — the 60 s workspace snapshots the agent
    records. Read with the pure-stdlib gitread module."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    commits, counts, problem = [], {}, None
    if os.path.isdir(model.shadow_git_path(sid)):  # absent = no snapshots yet, not an error
        try:
            repo = gitread.Repo(model.shadow_git_path(sid))
            commits = repo.log(limit=500)
            counts = {c["sha"]: len(repo.diff_summary(c["sha"])) for c in commits}
        except gitread.GitReadError as exc:
            problem = str(exc)
    return Response.html(views.admin_snapshots_page(who, s, commits, counts, problem))


@router.route("GET", "/admin/sessions/<sid>/snapshots/<sha>")
def snapshot_view(req, sid, sha):
    """One snapshot: per-file diff against its parent, or (?file=…) one file's full
    content at that commit."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid) or not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    try:
        repo = gitread.Repo(model.shadow_git_path(sid))
        commit = repo.commit(sha)
    except gitread.GitReadError:
        return Response.not_found()

    path = (req.query.get("file") or "").strip() or None
    if path:
        files = repo.commit_files(sha)
        if path not in files:
            return Response.not_found()
        try:
            blob = repo.blob(files[path][0])
        except gitread.GitReadError:
            return Response.not_found()  # e.g. a gitlink: the object lives in the nested repo
        return Response.html(views.admin_snapshot_file_page(
            who, s, commit, path, blob, binary=gitread.is_binary(blob),
            max_bytes=SNAPSHOT_MAX_BLOB))

    diffs = []
    for status, fpath, old_sha, new_sha in repo.diff_summary(sha):
        entry = {"status": status, "path": fpath, "lines": None, "note": None,
                 "truncated": False, "in_commit": new_sha is not None}
        try:
            old = repo.blob(old_sha) if old_sha else b""
            new = repo.blob(new_sha) if new_sha else b""
        except gitread.GitReadError:
            # A candidate-made nested repo becomes a gitlink entry: the tree names a
            # commit that only exists inside the workspace's own .git, so there is no
            # blob to show. Say so; never 500 the whole snapshot over one entry.
            entry["note"] = ("nested repository link — its content is not captured by "
                             "snapshots (the candidate ran git init/clone here)")
            entry["in_commit"] = False
            diffs.append(entry)
            continue
        if gitread.is_binary(old) or gitread.is_binary(new):
            entry["note"] = f"binary file ({len(new) if new_sha else len(old)} bytes)"
        elif max(len(old), len(new)) > SNAPSHOT_MAX_BLOB:
            entry["note"] = (f"file too large to diff "
                             f"({max(len(old), len(new))} bytes > {SNAPSHOT_MAX_BLOB})")
        else:
            entry["lines"], entry["truncated"] = gitread.unified_diff(old, new, fpath)
        diffs.append(entry)
    return Response.html(views.admin_snapshot_page(who, s, commit, diffs))


# --- LLM transcript viewer --------------------------------------------------
@router.route("GET", "/admin/sessions/<sid>/transcript")
def transcript_view(req, sid):
    """Near-real-time transcript reader: reloads the on-disk JSONL each request (a plain
    Refresh re-reads), with source and substring filters. Source is the proxy's tamper-
    proof attribution — 'api' = candidate's direct workspace call, 'ui' = Gemini
    playground, 'admin-test' = the admin health check."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    source = (req.query.get("source") or "").strip() or None
    query = (req.query.get("q") or "").strip() or None
    data = model.read_transcript(sid, source=source, query=query, limit=500)
    return Response.html(views.admin_transcript_page(who, s, data, source=source, query=query))


# --- multiple-choice answer sheet ----------------
@router.route("GET", "/admin/sessions/<sid>/answers")
def answers_view(req, sid):
    """What the candidate actually selected on every multiple-choice question, plus the
    timestamped trail of how they got there. Selections only — the rubric answer key is
    interviewer material and is never read by this service (visibility contract)."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    saved = model.all_answers(sid)
    trail = model.answer_trail(sid)
    notes = model.mcq_notes(sid)
    released = model.all_released(sid)
    problems = []
    for pid in s["problem_ids"] or []:
        questions = registry.all_question_ids(pid)
        if not questions:
            continue  # not an MCQ-bearing problem
        rows = []
        for q in questions:
            rows.append({**q,
                         "answer": saved.get((pid, q["qid"])),
                         "released": released.get(pid, 0),
                         "trail": [t for t in trail
                                   if t["problem_id"] == pid and t["question_id"] == q["qid"]],
                         "notes": [n for n in notes
                                   if n["problem_id"] == pid and n["question_id"] == q["qid"]]})
        problems.append({"id": pid, "questions": rows})
    return Response.html(views.admin_answers_page(
        who, s, problems, captured=model.mcq_capture_available(s),
        notice=req.query.get("notice"), error=req.query.get("error")))


@router.route("POST", "/admin/sessions/<sid>/answers/note")
def add_answer_note(req, sid):
    """Attach an interviewer note to one question — testimony, not artifact (contracts
    §3). Append-only; the question must belong to an assigned problem."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    pid = (req.form.get("problem_id") or "").strip()
    qid = (req.form.get("question_id") or "").strip()
    back = f"/admin/sessions/{sid}/answers"
    try:
        if pid not in (s["problem_ids"] or []):
            raise ValueError("that problem isn't assigned to this session")
        if qid not in {q["qid"] for q in registry.all_question_ids(pid)}:
            raise ValueError("that question isn't in the problem's statement")
        model.add_mcq_note(sid, pid, qid, req.form.get("note", ""), author=who)
    except ValueError as exc:
        return Response.redirect(f"{back}?error={_q(str(exc))}")
    return Response.redirect(f"{back}?notice={_q('Note recorded as interviewer testimony.')}")


# --- candidate workspace file manager ---------------------------------------
def _workspace_available(s):
    """Whether the live `workspace` volume can be attributed to this session. It is a
    single shared volume for the one candidate at a time: certain for the active session,
    and — until reset, and only while nothing else is live — for a closed/exported one."""
    if s["state"] == "active":
        return True, None
    live = model.active_session()
    if live and live["id"] != s["id"]:
        return False, f"the workspace now belongs to {live['candidate_name']}'s live session"
    if s["state"] in ("closed", "exported"):
        return True, None
    if s["state"] == "reset":
        return False, "this workspace was reset for the next candidate"
    return False, "the workspace isn't provisioned until the session is activated"


@router.route("GET", "/admin/sessions/<sid>/files")
def files(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    ok, reason = _workspace_available(s)
    rel = req.query.get("path", "")
    error = req.query.get("error")
    listing = view = None
    if ok:
        try:
            probe = integrations.list_workspace(rel)
            if probe.get("is_file"):
                view = integrations.read_workspace_file(rel)
            else:
                listing = probe
        except ValueError as exc:
            error = error or str(exc)
            listing = integrations.list_workspace("")
    # Per-assigned-problem: does it ship a dataset the admin can provision/reset? A
    # problem with no data/ (e.g. a code-only exercise) is shown as such, not hidden.
    provision_status = [(pid, integrations.problem_has_seed_data(sid, pid))
                        for pid in (s["problem_ids"] or [])]
    return Response.html(views.admin_files_page(
        who, s, listing=listing, view=view, available=ok, unavailable_reason=reason,
        error=error, notice=req.query.get("notice"), provision_status=provision_status))


def _files_action(fn):
    """Shared plumbing for the workspace mutating actions: auth, sid check, the single-
    tenant availability gate, then redirect back to the current dir with a notice/error."""
    def handler(req, sid):
        who, redirect = _require(req)
        if redirect:
            return redirect
        if _bad_sid(sid):
            return Response.not_found()
        s = model.get_session(sid)
        if not s:
            return Response.not_found()
        cwd = req.form.get("cwd", "")
        try:
            ok, reason = _workspace_available(s)
            if not ok:
                raise ValueError(reason)
            notice = fn(req, sid, who, s)
            return Response.redirect(f"/admin/sessions/{sid}/files?path={_q(cwd)}&notice={_q(notice)}")
        except ValueError as exc:
            return Response.redirect(f"/admin/sessions/{sid}/files?path={_q(cwd)}&error={_q(str(exc))}")
    return handler


def _files_delete(req, sid, who, s):
    deleted = integrations.delete_workspace_path(req.form.get("path", ""))
    model.record_event(sid, who, "workspace_file_deleted", {"path": deleted})
    return f"Removed {deleted}."


def _assigned_targets(req, s):
    pid = (req.form.get("problem_id") or "").strip()
    assigned = s["problem_ids"] or []
    if pid in ("", "all"):
        return assigned
    if pid in assigned:
        return [pid]
    raise ValueError("that problem isn't assigned to this session")


def _no_data_reason(sid, targets, verb):
    """Accurate reason why a provision/reset copied nothing — never blame activation when
    the session is already packaged. Priority: not-packaged > ships-no-dataset > other."""
    if not integrations.session_seed_exists(sid):
        return "this session's problems aren't packaged yet — re-activate the session to package them"
    if not any(integrations.problem_has_seed_data(sid, p) for p in targets):
        which = targets[0] if len(targets) == 1 else "the selected problems"
        return f"{which} ships no dataset, so there's nothing to {verb}"
    return f"nothing to {verb} — the seeded data may be unreadable (check the server logs)"


def _files_provision(req, sid, who, s):
    targets = _assigned_targets(req, s)
    copied = integrations.copy_problems_to_workspace(sid, targets, data_only=True)
    if not copied:
        raise ValueError(_no_data_reason(sid, targets, "provision"))
    model.record_event(sid, who, "workspace_data_provisioned", {"problems": copied})
    skipped = [p for p in targets if p not in copied]
    note = f" (skipped {', '.join(skipped)} — no dataset)" if skipped else ""
    return f"Provisioned data for {', '.join(copied)}.{note}"


def _files_reset(req, sid, who, s):
    targets = _assigned_targets(req, s)
    done = [p for p in targets if integrations.reset_problem_data(sid, p)]
    if not done:
        raise ValueError(_no_data_reason(sid, targets, "reset"))
    model.record_event(sid, who, "workspace_data_reset", {"problems": done})
    skipped = [p for p in targets if p not in done]
    note = f" (skipped {', '.join(skipped)} — no dataset)" if skipped else ""
    return f"Reset data/ to the seeded original for {', '.join(done)}.{note}"


def _files_wipe(req, sid, who, s):
    """Wipe the workspace — delete ALL candidate files, full stop. Does NOT re-provision;
    provisioning problem data is a separate action. Destructive — the UI routes it through
    the confirm overlay."""
    n = integrations.clear_workspace_contents()
    model.record_event(sid, who, "workspace_wiped", {"removed": n})
    return f"Workspace wiped — removed {n} item(s). It is now empty; provision problem data separately if you want it back."


router.add("POST", "/admin/sessions/<sid>/files/delete", _files_action(_files_delete))
router.add("POST", "/admin/sessions/<sid>/files/provision", _files_action(_files_provision))
router.add("POST", "/admin/sessions/<sid>/files/reset", _files_action(_files_reset))
router.add("POST", "/admin/sessions/<sid>/files/wipe", _files_action(_files_wipe))


@router.route("POST", "/admin/sessions/<sid>/moderate/<pid>")
def moderate(req, sid, pid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    if pid not in (s["problem_ids"] or []):
        return Response.redirect(f"/admin/sessions/{sid}?notice={_q('That problem is not assigned to this session.')}")
    total = registry.part_meta(pid)["total"]
    try:
        target = int(req.form.get("released") or 0)
    except ValueError:
        target = 0
    target = max(0, min(target, total))
    model.set_released(sid, pid, target, actor=who)
    return Response.redirect(f"/admin/sessions/{sid}")


@router.route("GET", "/admin/sessions/<sid>/edit")
def edit_form(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    return Response.html(views.admin_edit_session(
        who, s, registry.load_problems(), error=req.query.get("error")))


@router.route("POST", "/admin/sessions/<sid>/edit")
def edit_save(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    if not model.get_session(sid):
        return Response.not_found()
    f = req.form
    try:
        model.update_session(
            sid,
            candidate_name=f.get("candidate_name", "").strip(),
            workspace_user=f.get("workspace_user", "").strip(),
            access_code=f.get("access_code", "").strip() or None,
            duration_minutes=int(f.get("duration_minutes") or 90),
            llm_budget_usd=float(f.get("llm_budget_usd") or 5),
            llm_models=req.getlist("llm_models") or None,
            internet_access=f.get("internet_access", "1") == "1",
            terms_text=(f.get("terms_text") or "").strip() or None,
            problem_ids=req.getlist("problem_ids"),
            actor=who,
        )
    except ValueError as exc:
        return Response.redirect(f"/admin/sessions/{sid}/edit?error={_q(str(exc))}")
    return Response.redirect(f"/admin/sessions/{sid}")


@router.route("POST", "/admin/sessions/<sid>/llm")
def update_llm_limits(req, sid):
    """Mid-interview relief valve: budget/models only, valid on a live
    session, republished to the control file so unillm honours it on the next call."""
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    try:
        s = model.update_llm_limits(
            sid,
            llm_budget_usd=float(req.form.get("llm_budget_usd") or 0),
            llm_models=req.getlist("llm_models") or None,
            actor=who,
        )
    except ValueError as exc:
        return Response.redirect(f"/admin/sessions/{sid}?notice={_q(str(exc))}")
    integrations.refresh_control_session_fields(s)
    return Response.redirect(f"/admin/sessions/{sid}?notice={_q('LLM limits updated.')}")


@router.route("POST", "/admin/sessions/<sid>/delete")
def delete(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    try:
        model.delete_session(sid, actor=who)
    except ValueError as exc:
        return Response.redirect(f"/admin/sessions/{sid}?notice={_q(str(exc))}")
    return Response.redirect(f"/admin?notice={_q('Session deleted.')}")


def _lifecycle(action):
    def handler(req, sid):
        who, redirect = _require(req)
        if redirect:
            return redirect
        if _bad_sid(sid):
            return Response.not_found()
        try:
            action(req, sid, who)
            return Response.redirect(f"/admin/sessions/{sid}")
        except ValueError as exc:
            return Response.redirect(f"/admin/sessions/{sid}?notice={_q(str(exc))}")
    return handler


def _refuse_if_unexported_owner(sid):
    """The workspace changes hands here. If the volume's last owner is a closed session
    with no export bundle, activation's wipe destroys the only copy of its record, and
    reactivating a *different* session makes the snapshot agent commit the owner's
    leftover files into the wrong shadow.git — refuse both until the owner is exported
    or deleted."""
    stranded = model.unexported_workspace_owner(exclude_id=sid)
    if stranded:
        raise ValueError(
            f"the workspace still holds {stranded['candidate_name']}'s closed session "
            f"and no export bundle exists — Export it (or delete the session) first, "
            f"or that record is lost")


def _activate(req, sid, who):
    s = model.get_session(sid)
    if s is None:
        raise ValueError("no such session")
    # Cheap guard first, so we don't package a seed for a session that can't go live.
    live = model.active_session()
    if live and live["id"] != sid:
        raise ValueError(
            f"{live['candidate_name']}'s session is still active — close it before "
            f"activating another (one candidate at a time)")
    _refuse_if_unexported_owner(sid)
    # Provision in the order that fails safely: package first (this is the step that
    # refuses when a problem would ship no data), and only then flip the state. A failure
    # here leaves the session in `created`, so the admin can fix it and hit Activate
    # again — the old order stranded it in `active` with no workspace and no way back.
    integrations.preflight_activate(s)
    s = model.activate(sid, actor=who)
    try:
        # Fresh activation = a new candidate → clean slate. Wipe any leftovers from a
        # prior session BEFORE provisioning: `reset` is manual and export-gated, so
        # without this a workspace that was never reset carries the last candidate's
        # files into the next interview. Reactivate (resume) does
        # NOT wipe — that path keeps the same candidate's work.
        integrations.clear_workspace_contents()
        model.record_event(sid, who, "workspace_cleaned_on_activate")
        integrations.on_activate(s)
    except Exception as exc:
        model.rollback_activation(sid, actor=who, reason=str(exc))
        raise ValueError(f"could not provision the workspace — {exc}")


def _reactivate(req, sid, who):
    """Bring a closed session back to active so the candidate can resume. Re-provisions
    the workspace (re-issues the LLM key + republishes the control file) the same way
    activation does, and follows the same fail-safe order: package first, then flip, then
    provision — a failure rolls the session back to `closed`."""
    s = model.get_session(sid)
    if s is None:
        raise ValueError("no such session")
    if s["state"] != "closed":
        raise ValueError("only a closed session can be reactivated")
    live = model.active_session()
    if live and live["id"] != sid:
        raise ValueError(
            f"{live['candidate_name']}'s session is still active — close it before "
            f"reactivating another (one candidate at a time)")
    _refuse_if_unexported_owner(sid)
    raw_total = (req.form.get("total_minutes") or "").strip()
    total = int(raw_total) if raw_total else None
    integrations.preflight_activate(s)          # re-package (can fail → stays closed)
    s = model.reactivate(sid, actor=who, total_minutes=total)
    try:
        integrations.on_activate(s)
    except Exception as exc:
        model.rollback_reactivation(sid, actor=who, reason=str(exc))
        raise ValueError(f"could not re-provision the workspace — {exc}")


def _seed_workspace(req, sid, who):
    s = model.get_session(sid)
    if not s or s["state"] != "active":
        raise ValueError("workspace is only provisioned while the session is active")
    copied = integrations.copy_problems_to_workspace(sid, s["problem_ids"])
    model.record_event(sid, who, "admin_pushed_problems", {"problems": copied})
    if not copied:
        raise ValueError("no seeded problems to push (re-activate to package them)")


def _extend(req, sid, who):
    model.extend(sid, int(req.form.get("minutes") or 15), actor=who)


def _close(req, sid, who):
    model.close(sid, actor=who)
    integrations.on_close(sid)
    # Safety bundle: a session closed without an export has its only copy on the live
    # workspace volume, which the next activation wipes. Write the
    # bundle now, while the workspace is certainly intact. Best-effort — a failure
    # logs (integrations) and never blocks the close; the state stays `closed`, so the
    # explicit Export action and reactivation are unchanged.
    if integrations.export_session(sid):
        model.record_event(sid, who, "session_safety_exported")


def _export(req, sid, who):
    integrations.export_session(sid)
    model.mark_exported(sid, actor=who)


def _reset(req, sid, who):
    s = model.get_session(sid)
    integrations.reset_workspace(sid)
    integrations.revoke_llm_key(sid)
    integrations.clear_control()
    model.mark_reset(sid, actor=who)


router.add("POST", "/admin/sessions/<sid>/seed-workspace", _lifecycle(_seed_workspace))
router.add("POST", "/admin/sessions/<sid>/activate", _lifecycle(_activate))
router.add("POST", "/admin/sessions/<sid>/reactivate", _lifecycle(_reactivate))
router.add("POST", "/admin/sessions/<sid>/extend", _lifecycle(_extend))
router.add("POST", "/admin/sessions/<sid>/close", _lifecycle(_close))
router.add("POST", "/admin/sessions/<sid>/export", _lifecycle(_export))
router.add("POST", "/admin/sessions/<sid>/reset", _lifecycle(_reset))


@router.route("GET", "/admin/sessions/<sid>/download")
def download(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    if _bad_sid(sid):
        return Response.not_found()
    export_dir = os.path.join(model.DATA_DIR, "sessions", sid, "export")
    bundle = None
    if os.path.isdir(export_dir):
        files = sorted(os.listdir(export_dir))
        bundle = next((f for f in files if f.endswith((".tar.gz", ".tgz", ".zip"))), None)
    if not bundle:
        return Response.redirect(
            f"/admin/sessions/{sid}?notice={_q('No export bundle yet — run Export first.')}")
    with open(os.path.join(export_dir, bundle), "rb") as fh:
        data = fh.read()
    return Response(200, data, "application/octet-stream",
                    [("Content-Disposition", f'attachment; filename="{bundle}"')])


def _q(s):
    import urllib.parse
    return urllib.parse.quote(s)


def main():
    model.assert_boot_config()
    db.init()
    model.seed_admins()
    serve(router, int(os.environ.get("PORT", "8001")), name="admin")


if __name__ == "__main__":
    main()
