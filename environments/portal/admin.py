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


def _dashboard(who, notice=None, llm_test=None):
    return Response.html(views.admin_dashboard(
        who, model.list_sessions(), registry.load_problems(),
        notice=notice, llm_key=UNILLM_MASTER_KEY, llm_test=llm_test,
        models_info=integrations.list_models()))


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


@router.route("GET", "/admin/sessions/<sid>")
def detail(req, sid):
    who, redirect = _require(req)
    if redirect:
        return redirect
    s = model.get_session(sid)
    if not s:
        return Response.not_found()
    return Response.html(views.admin_session_detail(who, s, notice=req.query.get("notice")))


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
    s = model.activate(sid, actor=who)
    integrations.on_activate(s)


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
    db.init()
    model.seed_admins()
    serve(router, int(os.environ.get("PORT", "8001")), name="admin")


if __name__ == "__main__":
    main()
