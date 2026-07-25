#!/usr/bin/env python3
"""the portal candidate portal (portal on :8000, routes `/`, `/api/*`).

Replaces the original portal-stub with the real access-code-gated flow:
    access code → terms acceptance → home page → workspace tools
and serves the proxy's `/api/authz` gate for `/ide` and `/jupyter`.
"""
from __future__ import annotations

import json
import math
import os

import db
import integrations
import model
import registry
import views
import views_llm
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
    # First acceptance starts the countdown (model sets starts_at/ends_at). Push the now-
    # concrete ends_at into the live control file so the workspace handoff is truthful.
    s = model.accept_terms(s["id"])
    integrations.refresh_control_ends_at(s)
    return Response.redirect("/")


# --- Gemini page + server-side chat history ------
def _llm_gated(req):
    """The Gemini page and chat API share the /problems gate: an active,
    terms-accepted session."""
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return None
    return s


@router.route("GET", "/llm")
def llm_page(req):
    s = _llm_gated(req)
    if not s:
        return Response.redirect("/")
    return Response.html(views_llm.llm_page(
        s, chats=model.list_chats(s["id"]),
        api_key=integrations.get_session_llm_key(s["id"]),
        remaining_minutes=_remaining_minutes(s)))


@router.route("GET", "/api/llm/chats")
def llm_chats(req):
    s = _llm_gated(req)
    if not s:
        return Response.json({"error": "No active session."}, status=401)
    return Response.json({"chats": model.list_chats(s["id"])})


@router.route("POST", "/api/llm/chats")
def llm_chat_create(req):
    s = _llm_gated(req)
    if not s:
        return Response.json({"error": "No active session."}, status=401)
    chat = model.create_chat(s["id"], params=_clean_params(req.json_body().get("params")))
    return Response.json({"chat": chat})


@router.route("GET", "/api/llm/chats/<cid>")
def llm_chat_get(req, cid):
    s = _llm_gated(req)
    if not s:
        return Response.json({"error": "No active session."}, status=401)
    chat = model.get_chat(s["id"], cid)
    if not chat:
        return Response.json({"error": "No such conversation."}, status=404)
    return Response.json({"chat": chat})


@router.route("POST", "/api/llm/chats/<cid>/delete")
def llm_chat_delete(req, cid):
    s = _llm_gated(req)
    if not s:
        return Response.json({"error": "No active session."}, status=401)
    model.delete_chat(s["id"], cid)
    return Response.json({"ok": True})


_clean_params = model.clean_llm_params


@router.route("POST", "/api/llm/chats/<cid>/send")
def llm_chat_send(req, cid):
    """Append a user message and stream the assistant reply as NDJSON
    (`{"delta"}…{"done"}`). The upstream call is server-side with the master key +
    source "ui" (unillm's tee writes the audit transcript); history persists in the
    chats table even if the browser disconnects mid-stream."""
    s = _llm_gated(req)
    if not s:
        return Response.json({"error": "No active session."}, status=401)
    chat = model.get_chat(s["id"], cid)
    if not chat:
        return Response.json({"error": "No such conversation."}, status=404)
    data = req.json_body()
    model_name = (data.get("model") or "").strip()
    content = (data.get("content") or "").strip()
    if model_name not in (s["llm_models"] or []):
        return Response.json({"error": "That model isn't enabled for this session."}, status=400)
    if not content:
        return Response.json({"error": "Enter a message first."}, status=400)
    params = _clean_params(data.get("params"))
    history = [{"role": m["role"], "content": m["content"]}
               for m in chat["messages"] if m.get("role") in ("user", "assistant")]
    upstream = history + [{"role": "user", "content": content}]
    model.record_event(s["id"], "candidate", "llm_chat",
                       {"chat_id": cid, "model": model_name, "params": params})

    def stream():
        parts, err, saved = [], None, None
        try:
            for kind, val in integrations.llm_chat_stream(model_name, upstream, params):
                if kind == "delta":
                    parts.append(val)
                    yield json.dumps({"delta": val}) + "\n"
                else:
                    err = val
                    yield json.dumps({"error": val}) + "\n"
        finally:
            # Persist even on client disconnect (GeneratorExit passes through here;
            # no yields in this block — a closing generator may not yield again).
            new = [{"role": "user", "content": content}]
            if parts:
                new.append({"role": "assistant", "content": "".join(parts),
                            "model": model_name})
            saved = model.append_chat_messages(s["id"], cid, new, params=params)
        if err is None:
            yield json.dumps({"done": True,
                              "title": saved["title"] if saved else None}) + "\n"

    return Response.stream(stream())


@router.route("GET", "/problems")
def problems(req):
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return Response.redirect("/")
    released = model.all_released(s["id"])
    answers = model.all_answers(s["id"])
    items = []
    for m in registry.problem_meta(s["problem_ids"]):
        r = released.get(m["id"], 0)
        if r < 1:
            continue  # not released yet — don't show the problem at all
        blocks = registry.released_blocks(m["id"], r)
        for b in blocks:  # hand each MCQ block its saved state so a refresh doesn't lose it
            if b["kind"] == "mcq":
                b["answer"] = answers.get((m["id"], b["qid"]))
        items.append({**m, "released": r, "blocks": blocks})
    return Response.html(views.problems_page(s, items))


@router.route("POST", "/api/problems/<pid>/answers/<qid>")
def save_answer(req, pid, qid):
    """Candidate saves a multiple-choice selection. Fired on every toggle
    — there is no submit step, the current selection is the answer. Same gate as
    `/problems`, plus: the problem must be assigned and the question actually released,
    so a candidate can't answer ahead of the moderator."""
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return Response.json({"ok": False, "message": "No active session."}, status=401)
    if pid not in (s["problem_ids"] or []):
        return Response.json({"ok": False, "message": "That problem isn't assigned to you."},
                             status=400)
    questions = registry.question_ids(pid, model.all_released(s["id"]).get(pid, 0))
    if qid not in questions:
        return Response.json({"ok": False, "message": "That question isn't released yet."},
                             status=400)
    answer = model.save_answer(s["id"], pid, qid, req.json_body().get("selected"),
                               allowed=questions[qid])
    return Response.json({"ok": True, "selected": answer["selected"],
                          "revision": answer["revision"],
                          "updated_at": answer["updated_at"]})


@router.route("POST", "/api/problems/copy")
def copy_problem(req):
    """Candidate 'copy files to my workspace' button: copy one assigned problem (or
    all) from the session seed into ~/workspace. Gated to the candidate's own active,
    terms-accepted session and to problems actually assigned to it."""
    s = _current(req)
    if not s or not s["terms_accepted_at"]:
        return Response.json({"ok": False, "message": "No active session."}, status=401)
    data = req.json_body()
    pid = (data.get("problem_id") or "").strip()
    assigned = s["problem_ids"] or []
    if pid and pid != "all" and pid not in assigned:
        return Response.json({"ok": False, "message": "That problem isn't assigned to you."}, status=400)
    # Only released problems are copyable — an unreleased problem isn't shown at all.
    released = model.all_released(s["id"])
    live = [p for p in assigned if released.get(p, 0) >= 1]
    targets = live if (pid in ("", "all")) else [pid] if released.get(pid, 0) >= 1 else []
    if not targets:
        return Response.json({"ok": False, "message": "No problems available yet."}, status=400)
    # Candidate copy is the dataset only (data/) — never the written statement or
    # starter. The moderated statement is read in the browser; the interviewer pushes
    # problem.md + starter via the admin full-copy button.
    copied = integrations.copy_problems_to_workspace(s["id"], targets, data_only=True)
    model.record_event(s["id"], "candidate", "problem_data_copied", {"problems": copied})
    if not copied:
        return Response.json({"ok": False,
                              "message": "Files aren't ready yet — ask your interviewer to activate the session."},
                             status=409)
    return Response.json({"ok": True, "copied": copied,
                          "message": f"Copied data for {', '.join(copied)} into ~/workspace/data/."})


@router.route("GET", "/logout")
def logout(req):
    resp = Response.redirect("/")
    resp.set_cookie(COOKIE, "", max_age=0)
    return resp


def main():
    model.assert_boot_config()
    db.init()
    model.seed_admins()
    serve(router, int(os.environ.get("PORT", "8000")), name="portal")


if __name__ == "__main__":
    main()
