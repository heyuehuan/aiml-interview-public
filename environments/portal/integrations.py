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
import subprocess
import tempfile
import urllib.error
import urllib.request

import model

CONTROL_FILE = os.environ.get("CONTROL_FILE", "/control/active.json")
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


def gemini_healthcheck(model_name=HEALTHCHECK_MODEL, prompt="Hello"):
    """Admin 'Test Gemini' button: send a one-shot chat to unillm server-side (from the
    admin container, so it hits unillm:8081 directly) and report the reply or the error."""
    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        f"{UNILLM_INTERNAL_URL}/chat/completions", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {UNILLM_MASTER_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        return {"ok": True, "model": model_name, "text": text}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        return {"ok": False, "model": model_name, "text": f"HTTP {exc.code}: {body}"}
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError) as exc:
        return {"ok": False, "model": model_name, "text": f"{type(exc).__name__}: {exc}"}


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
