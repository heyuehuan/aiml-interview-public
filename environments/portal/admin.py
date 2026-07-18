#!/usr/bin/env python3
"""the portal admin panel (admin on :8001, routes `/admin/*`).

Runs the whole session lifecycle: create → activate (provision workspace + LLM key)
→ extend/close → export → reset. Auth is a cookie session over the `admins` table
(real admin accounts, no shared logins). Every transition lands in
events.jsonl via model.*.
"""
from __future__ import annotations

import os

import db
import integrations
import model
import registry
import views
from server import Response, Router, serve

COOKIE = "admin"
router = Router()


def _admin(req):
    token = req.cookies.get(COOKIE)
    return model.unsign(token) if token else None


def _require(req):
    who = _admin(req)
    return who, (None if who else Response.redirect("/admin"))


@router.route("GET", "/healthz")
def healthz(req):
    return Response.text("ok")


UNILLM_MASTER_KEY = os.environ.get("UNILLM_MASTER_KEY", "sk-unillm-dev-change-me")


def _dashboard(who, notice=None, llm_test=None, deliver_report=None):
    return Response.html(views.admin_dashboard(
        who, model.list_sessions(), registry.load_problems(),
        notice=notice, llm_key=UNILLM_MASTER_KEY, llm_test=llm_test,
        models_info=integrations.list_models(),
        all_problems=registry.all_problems(), deliver_report=deliver_report))


@router.route("POST", "/admin/problems/validate-data")
def validate_data(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    ids = [p["id"] for p in registry.all_problems()]
    return _dashboard(who, deliver_report=integrations.check_deliverable(ids))


@router.route("POST", "/admin/problems/<pid>/visibility")
def problem_visibility(req, pid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    visible = req.form.get("visible") == "1"
    registry.set_visibility(pid, visible)
    return Response.redirect(
        f"/admin?notice={_q((pid + ' is now ' + ('visible' if visible else 'hidden')))}")


@router.route("GET", "/admin")
def dashboard(req):
    who = _admin(req)
    if not who:
        return Response.html(views.admin_login())
    return _dashboard(who, notice=req.query.get("notice"))


@router.route("POST", "/admin/llm/test")
def llm_test(req):
    who, redirect = _require(req)
    if redirect:
        return redirect
    result = integrations.gemini_healthcheck()
    return _dashboard(who, llm_test=result)


@router.route("POST", "/admin/login")
def login(req):
    who = model.authenticate_admin(req.form.get("username", ""), req.form.get("password", ""))
    if not who:
        return Response.html(views.admin_login(error="Invalid username or password."), status=401)
    resp = Response.redirect("/admin")
    resp.set_cookie(COOKIE, model.sign(who), max_age=model.COOKIE_MAX_AGE)
    return resp


@router.route("POST", "/admin/logout")
def logout(req):
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
        return _dashboard(who, notice="Current password is incorrect.")
    if len(new) < 8:
        return _dashboard(who, notice="New password must be at least 8 characters.")
    if new != confirm:
        return _dashboard(who, notice="New passwords do not match.")
    model.change_password(who, new)
    return _dashboard(who, notice="Password changed successfully.")


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
        return Response.redirect(f"/admin?notice={_q('Could not create session: ' + str(exc))}")
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
    return Response.html(views.admin_session_detail(
        who, s, moderation=_moderation_state(s), notice=req.query.get("notice")))


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


@router.route("POST", "/admin/sessions/<sid>/delete")
def delete(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
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
        try:
            action(req, sid, who)
            return Response.redirect(f"/admin/sessions/{sid}")
        except ValueError as exc:
            return Response.redirect(f"/admin/sessions/{sid}?notice={_q(str(exc))}")
    return handler


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
    # Provision in the order that fails safely: package first (this is the step that
    # refuses when a problem would ship no data), and only then flip the state. A failure
    # here leaves the session in `created`, so the admin can fix it and hit Activate
    # again — the old order stranded it in `active` with no workspace and no way back.
    integrations.preflight_activate(s)
    s = model.activate(sid, actor=who)
    try:
        integrations.on_activate(s)
    except Exception as exc:
        model.rollback_activation(sid, actor=who, reason=str(exc))
        raise ValueError(f"could not provision the workspace — {exc}")


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
router.add("POST", "/admin/sessions/<sid>/extend", _lifecycle(_extend))
router.add("POST", "/admin/sessions/<sid>/close", _lifecycle(_close))
router.add("POST", "/admin/sessions/<sid>/export", _lifecycle(_export))
router.add("POST", "/admin/sessions/<sid>/reset", _lifecycle(_reset))


@router.route("GET", "/admin/sessions/<sid>/download")
def download(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
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
