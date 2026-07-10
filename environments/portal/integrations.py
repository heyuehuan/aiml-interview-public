"""Cross-component side effects, each best-effort so the portal runs standalone when
the packager, proxy, or export scripts are absent.

  * control file  — the live-session handoff the workspace entrypoint reads
  * LLM keys  — POST/DELETE /llm/admin/keys; dev fallback key if absent
  * packager  — python -m problems.package; skipped if missing
  * export/reset — scripts/export_session.sh / reset_workspace.sh
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request

import model

CONTROL_FILE = os.environ.get("CONTROL_FILE", "/control/active.json")
# The candidate volume, mounted into the portal/admin containers so the "copy to
# workspace" button (candidate + admin) can drop seeded problem files in.
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/workspace")
# unillm: one shared master key, not per-session keys.
UNILLM_MASTER_KEY = os.environ.get("UNILLM_MASTER_KEY", "sk-unillm-dev-change-me")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8081/v1")
# Compose-internal URL the admin health check calls (candidates use localhost:8081).
UNILLM_INTERNAL_URL = os.environ.get("UNILLM_INTERNAL_URL", "http://unillm:8081/v1")
HEALTHCHECK_MODEL = "gemini-3.1-flash-lite"
PROBLEMS_SEED_DIR = os.environ.get("PROBLEMS_SEED_DIR", "/problems_seed")
PACKAGER_CWD = os.environ.get("PACKAGER_CWD", "/srv")
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/srv/scripts")


def _log(msg):
    print(f"[integrations] {msg}", flush=True)


# --- LLM key -----------------------------------------------------------
def issue_llm_key(session):
    """One shared unillm master key. unillm has no
    per-session key API in this MVP, so every workspace gets the same key; model
    control is enforced by unillm's config allowlist, not the key."""
    return UNILLM_MASTER_KEY


def revoke_llm_key(session_id):
    """No-op: the shared master key is not per-session, so there is nothing to revoke.
    Access is cut by clearing the control file (workspace tools lock, env is gone)."""
    return


def llm_chat(model_name, prompt, timeout=60):
    """One-shot chat against unillm server-side (from the portal/admin container, so it
    hits unillm:8081 directly with the master key). Powers both the admin 'Test Gemini'
    button and the candidate playground. Returns {ok, model, text}; text is the reply on
    success or a human-readable error otherwise (never raises)."""
    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        f"{UNILLM_INTERNAL_URL}/chat/completions", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {UNILLM_MASTER_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "model": model_name, "text": text}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        return {"ok": False, "model": model_name, "text": f"HTTP {exc.code}: {body}"}
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "model": model_name, "text": f"{type(exc).__name__}: {exc}"}


def gemini_healthcheck(model_name=HEALTHCHECK_MODEL, prompt="Hello"):
    """Admin 'Test Gemini' button."""
    return llm_chat(model_name, prompt, timeout=30)


def list_models(timeout=4):
    """Live model list unillm is currently serving (GET /v1/models). Short timeout so a
    down proxy doesn't stall the admin dashboard. Returns {ok, models:[id,...], error}."""
    req = urllib.request.Request(
        f"{UNILLM_INTERNAL_URL}/models",
        headers={"Authorization": f"Bearer {UNILLM_MASTER_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return {"ok": True, "models": [m.get("id", "") for m in data.get("data", [])], "error": None}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "models": [], "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "models": [], "error": f"{type(exc).__name__}: {exc}"}


# --- problem packager --------------------------------------------------
def package_problems(session):
    """the integration contract: python -m problems.package <session_id> <problem_id>... Writes
    problems_seed/<session_id>/; the workspace entrypoint copies it in. Best-effort."""
    if not session["problem_ids"]:
        return
    try:
        subprocess.run(
            ["python", "-m", "problems.package", session["id"], *session["problem_ids"]],
            cwd=PACKAGER_CWD, check=True, timeout=120,
        )
        _log(f"packaged problems for {session['id']}")
    except (subprocess.SubprocessError, OSError) as exc:
        _log(f"packager unavailable ({exc}); workspace will start without seeded problems")


# --- copy seeded problems into the candidate workspace ----------------------
def _session_seed_dir(session_id):
    return os.path.join(PROBLEMS_SEED_DIR, session_id)


def _world_readable(path):
    """Portal runs as root; the candidate is a non-root user. Make copied problem
    files readable (and dirs traversable) by everyone so the candidate can open them."""
    for root, dirs, files in os.walk(path):
        os.chmod(root, os.stat(root).st_mode | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        for f in files:
            fp = os.path.join(root, f)
            os.chmod(fp, os.stat(fp).st_mode | stat.S_IRGRP | stat.S_IROTH)


def copy_problem_to_workspace(session_id, problem_id, data_only=False):
    """Copy one seeded problem into the candidate workspace at
    ``~/workspace/<problem_id>/`` (the seed already enforces the visibility contract).

    ``data_only=True`` (the candidate button) ships ONLY the problem's ``data/`` dir —
    dataset + data dictionary — and nothing else: not the written ``problem.md`` (they
    read the moderated statement in the browser) and not ``starter/`` (the interviewer
    releases that via the full push). ``data_only=False`` (the admin button) ships the
    whole problem. Returns the destination, or None if there's nothing to copy."""
    src = os.path.join(_session_seed_dir(session_id), problem_id)
    if not os.path.isdir(src):
        _log(f"seed for {problem_id} not found ({src}); did activation package it?")
        return None
    dst = os.path.join(WORKSPACE_DIR, problem_id)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    if data_only:
        data_src = os.path.join(src, "data")
        if not os.path.isdir(data_src):
            _log(f"{problem_id}: no data/ dir to copy (data_only)")
            return None
        shutil.copytree(data_src, os.path.join(dst, "data"), dirs_exist_ok=True, ignore=ignore)
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
    _world_readable(dst)
    return dst


def copy_problems_to_workspace(session_id, problem_ids, data_only=False):
    """Copy every assigned problem into the workspace. ``data_only=True`` (candidate)
    ships each problem's ``data/`` only; ``data_only=False`` (admin) ships the full
    problem plus the ``PROBLEMS.md`` index. Returns the ids actually copied."""
    copied = []
    for pid in problem_ids:
        if copy_problem_to_workspace(session_id, pid, data_only=data_only):
            copied.append(pid)
    if not data_only:
        index = os.path.join(_session_seed_dir(session_id), "PROBLEMS.md")
        if os.path.isfile(index):
            os.makedirs(WORKSPACE_DIR, exist_ok=True)
            shutil.copy2(index, os.path.join(WORKSPACE_DIR, "PROBLEMS.md"))
            try:
                os.chmod(os.path.join(WORKSPACE_DIR, "PROBLEMS.md"), 0o644)
            except OSError:
                pass
    return copied


# --- export / reset ----------------------------------------------------
def _run_script(name, session_id):
    path = os.path.join(SCRIPTS_DIR, name)
    if not os.path.exists(path):
        _log
        return False
    try:
        subprocess.run(["bash", path, session_id], check=True, timeout=300)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        _log(f"{name} failed: {exc}")
        return False


def export_session(session_id):
    return _run_script("export_session.sh", session_id)


def reset_workspace(session_id):
    return _run_script("reset_workspace.sh", session_id)


# --- control file (the live-session handoff) --------------------------------
def write_control(session, llm_api_key):
    """Publish the active session to the workspace containers."""
    os.makedirs(os.path.dirname(CONTROL_FILE), exist_ok=True)
    doc = {
        "state": "active",
        "session_id": session["id"],
        "workspace_user": session["workspace_user"],
        "display_name": session["candidate_name"],
        "seed_dir": os.path.join(PROBLEMS_SEED_DIR, session["id"]),
        "llm_base_url": LLM_BASE_URL,
        "llm_api_key": llm_api_key,
        "llm_models": session["llm_models"],
        "ends_at": session.get("ends_at"),
    }
    _atomic_write(CONTROL_FILE, json.dumps(doc, indent=2))


def clear_control():
    """No active session: workspace tools stay locked."""
    _atomic_write(CONTROL_FILE, json.dumps({"state": "inactive"}, indent=2))


def _atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --- orchestration used by the admin panel ----------------------------------
def on_activate(session):
    """Everything that must happen when a session goes live."""
    package_problems(session)
    key = issue_llm_key(session)
    write_control(session, key)
    model.record_event(session["id"], "system", "workspace_provisioned",
                       {"workspace_user": session["workspace_user"]})


def on_close(session_id):
    revoke_llm_key(session_id)
    clear_control()
