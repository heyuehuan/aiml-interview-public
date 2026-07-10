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
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.request

import model

CONTROL_FILE = os.environ.get("CONTROL_FILE", "/control/active.json")
LLM_ADMIN_URL = os.environ.get("LLM_ADMIN_URL", "http://unillm:4000/llm")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://unillm:4000/v1")
PROBLEMS_SEED_DIR = os.environ.get("PROBLEMS_SEED_DIR", "/problems_seed")
PACKAGER_CWD = os.environ.get("PACKAGER_CWD", "/srv")
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/srv/scripts")


def _log(msg):
    print(f"[integrations] {msg}", flush=True)


# --- session LLM key ---------------------------------------------------
def issue_llm_key(session):
    """the integration contract: POST /llm/admin/keys -> {api_key}. Falls back to a local dev key
    so the workspace still gets an env var when the proxy isn't up yet."""
    payload = json.dumps({
        "session_id": session["id"],
        "models": session["llm_models"],
        "budget_usd": session["llm_budget_usd"],
    }).encode()
    try:
        req = urllib.request.Request(f"{LLM_ADMIN_URL}/admin/keys", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            key = json.loads(resp.read()).get("api_key")
            if key:
                return key
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log(f"the proxy key issue failed ({exc}); using dev placeholder key")
    return "sk-dev-" + secrets.token_hex(16)


def revoke_llm_key(session_id):
    try:
        req = urllib.request.Request(f"{LLM_ADMIN_URL}/admin/keys/{session_id}", method="DELETE")
        urllib.request.urlopen(req, timeout=5).close()
    except (urllib.error.URLError, OSError) as exc:
        _log(f"the proxy key revoke skipped ({exc})")


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
