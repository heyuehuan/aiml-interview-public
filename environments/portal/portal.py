#!/usr/bin/env python3
"""the portal candidate portal (portal on :8000, routes `/`, `/api/*`).

Replaces the original portal-stub with the real access-code-gated flow:
    access code → terms acceptance → home page → workspace tools
and serves the proxy's `/api/authz` gate for `/ide` and `/jupyter`.
"""
from __future__ import annotations

import math
import os

import db
import integrations
import model
import views
from server import Response, Router, serve

COOKIE = "sid"
router = Router()


def _current(req):
    """The candidate's session from their signed cookie, if still usable."""
    token = req.cookies.get(COOKIE)
    if not token:
        return None
    sid = model.unsign(token)
    if not sid:
        return None
    s = model.get_session(sid)
    if not s or s["state"] != "active":
        return None
    disabled = model.code_disabled_at(s)
    if disabled and model.now() > disabled:
        return None
    return s


def _remaining_minutes(s):
    if not s.get("ends_at"):
        return None
    delta = model.datetime.fromisoformat(s["ends_at"]) - model.now()
    return max(0, math.ceil(delta.total_seconds() / 60))


@router.route("GET", "/healthz")
def healthz(req):
    return Response.text("ok")


@router.route("GET", "/api/authz")
def authz(req):
    """Proxy subrequest for /ide and /jupyter."""
    token = req.cookies.get(COOKIE)
    sid = model.unsign(token) if token else None
    if sid and model.is_workspace_authorized(sid):
        return Response.no_content()
    return Response.unauthorized()


@router.route("GET", "/")
def index(req):
    s = _current(req)
    if not s:
        return Response.html(views.code_entry())
    if not s["terms_accepted_at"]:
        return Response.redirect("/terms")
    return Response.html(views.home(s, _remaining_minutes(s)))


@router.route("POST", "/api/code")
def submit_code(req):
    session, reason = model.authorize_code(req.form.get("code", ""))
    if not session:
        return Response.html(views.code_entry(error=reason), status=200)
    model.record_event(session["id"], "candidate", "code_accepted")
    resp = Response.redirect("/")
    resp.set_cookie(COOKIE, model.sign(session["id"]), max_age=model.COOKIE_MAX_AGE)
    return resp


@router.route("GET", "/terms")
def terms(req):
    s = _current(req)
    if not s:
        return Response.redirect("/")
    if s["terms_accepted_at"]:
        return Response.redirect("/")
    return Response.html(views.terms(s))


@router.route("POST", "/api/terms")
def accept_terms(req):
    s = _current(req)
    if not s:
        return Response.redirect("/")
    if req.form.get("accept") != "yes":
        return Response.html(views.terms(s, error="You must accept the terms to continue."))
    model.accept_terms(s["id"])
    return Response.redirect("/")


@router.route("POST", "/api/llm/playground")
def llm_playground(req):
    """Candidate playground: proxy a one-shot prompt to unillm server-side so the master
    key never reaches the browser. Gated to an active, terms-accepted session and to the
    session's own model allowlist."""
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return Response.json({"ok": False, "text": "No active session."}, status=401)
    data = req.json_body()
    model_name = (data.get("model") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    if model_name not in (s["llm_models"] or []):
        return Response.json({"ok": False, "text": "That model isn't enabled for this session."}, status=400)
    if not prompt:
        return Response.json({"ok": False, "text": "Enter a prompt first."}, status=400)
    result = integrations.llm_chat(model_name, prompt)
    model.record_event(s["id"], "candidate", "llm_playground", {"model": model_name})
    return Response.json(result)


@router.route("GET", "/problems")
def problems(req):
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return Response.redirect("/")
    return Response.html(views.problems_page(s))


@router.route("GET", "/logout")
def logout(req):
    resp = Response.redirect("/")
    resp.set_cookie(COOKIE, "", max_age=0)
    return resp


def main():
    db.init()
    model.seed_admins()
    serve(router, int(os.environ.get("PORT", "8000")), name="portal")


if __name__ == "__main__":
    main()
