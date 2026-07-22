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
    """Mint the per-session candidate key (the integration contract; supersedes the
    shared-master-key model). It reaches the workspace via the control file; unillm
    accepts it only while the control file names this session active. The platform
    master key stays server-side (admin health check, playground) and never enters
    the candidate env."""
    return "sk-cand-" + secrets.token_hex(16)


def revoke_llm_key(session_id):
    """Revocation is effected by clear_control(): unillm validates the candidate key
    against the live control file, so once the file no longer names this session
    active the key stops working — including for a candidate who saved it. Extending
    a session leaves the control file (and so the key) intact; re-activation simply
    mints a fresh key."""
    return


def llm_chat(model_name, prompt, timeout=60, source=None):
    """One-shot chat against unillm server-side (from the portal/admin container, so it
    hits unillm:8081 directly with the master key). Powers both the admin 'Test Gemini'
    button and the candidate playground. Returns {ok, model, text}; text is the reply on
    success or a human-readable error otherwise (never raises).

    ``source`` (e.g. "ui", "admin-test") is forwarded so the proxy tags the transcript
    entry. It is honoured only because this call uses the master key — a candidate's
    direct call carries the session key and is always attributed "api" (see proxy)."""
    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {UNILLM_MASTER_KEY}"}
    if source:
        headers["X-Unillm-Source"] = source
    req = urllib.request.Request(
        f"{UNILLM_INTERNAL_URL}/chat/completions", data=payload, method="POST",
        headers=headers)
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
    return llm_chat(model_name, prompt, timeout=30, source="admin-test")


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
    problems_seed/<session_id>/; the workspace entrypoint copies it in.

    Tolerant of the packager being genuinely absent (tooling not deployed), but a
    packager that *ran and failed* — e.g. a problem that would ship a candidate an
    empty data dir — raises ValueError so activation surfaces it as an admin notice
    instead of quietly going live with missing data."""
    if not session["problem_ids"]:
        return
    try:
        proc = subprocess.run(
            ["python", "-m", "problems.package", session["id"], *session["problem_ids"]],
            cwd=PACKAGER_CWD, check=True, timeout=120, capture_output=True, text=True,
        )
        _log(f"packaged problems for {session['id']}")
        return proc
    except subprocess.CalledProcessError as exc:
        # The packager ran and refused (e.g. missing dataset). Surface it loudly.
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {exc.returncode}"
        _log(f"packager FAILED for {session['id']}: {tail}")
        raise ValueError(f"problem packaging failed — {tail}")
    except (subprocess.SubprocessError, OSError) as exc:
        _log(f"packager unavailable ({exc}); workspace will start without seeded problems")


def check_deliverable(problem_ids):
    """Dry-run the packager (`--check-json`) to confirm each problem would actually
    ship a candidate dataset — the admin "validate data" button. Never writes a seed.
    Returns ``{ok, problems: [{id, ok, files, error}], error}``; ``ok`` is True only
    when every problem delivers data. A missing/unrunnable packager reports ``error``
    rather than raising, so the panel can render a clear message."""
    if not problem_ids:
        return {"ok": True, "problems": [], "error": None}
    try:
        proc = subprocess.run(
            ["python", "-m", "problems.package", "--check-json", *problem_ids],
            cwd=PACKAGER_CWD, timeout=120, capture_output=True, text=True,
        )
        report = json.loads((proc.stdout or "").strip() or "[]")
        return {"ok": all(p["ok"] for p in report), "problems": report, "error": None}
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        _log(f"deliverability check failed to run: {exc}")
        return {"ok": False, "problems": [], "error": f"{type(exc).__name__}: {exc}"}


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


def _make_readonly(path):
    """Make a seeded tree read-only to the candidate: dirs ``0555``, files ``0444``
    (readable and traversable by everyone, writable by no one). The portal runs as root
    and owns these copies, so the non-root candidate can read the data but cannot edit or
    delete a file inside it; admin reset / re-provision (also root) still replaces it.
    Note: the candidate owns ``~/workspace`` itself, so a deliberate ``rm -rf
    ~/workspace/data`` remains possible — reset restores it — but accidental in-place
    corruption (an overwriting script, an edited CSV) is prevented."""
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o444)
            except OSError:
                pass
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o555)
            except OSError:
                pass
    try:
        os.chmod(path, 0o555)
    except OSError:
        pass


def _restore_writable(path):
    """Re-add owner write across a tree so it can be dropped/replaced. Seed copies are
    made read-only (``_make_readonly``); reset / re-provision / wipe must still be able to
    remove them. Root (production) bypasses perms anyway, but this keeps removal working
    for a non-root owner too (tests, and defence in depth)."""
    for root, dirs, files in os.walk(path):
        for name in (root, *(os.path.join(root, d) for d in dirs)):
            try:
                os.chmod(name, 0o755)
            except OSError:
                pass
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o644)
            except OSError:
                pass


def _candidate_data_dst(problem_id):
    """Where a problem's read-only candidate dataset lives in the workspace:
    ``~/workspace/data/<problem_id>/`` — one clean, namespaced data root (matches the
    path every ``problem.md`` advertises, and keeps same-named files from colliding
    across problems, e.g. two ``transactions.csv``)."""
    return os.path.join(WORKSPACE_DIR, "data", problem_id)


def copy_problem_to_workspace(session_id, problem_id, data_only=False):
    """Provision one seeded problem into the candidate workspace.

    The **dataset** always lands read-only at ``~/workspace/data/<problem_id>/`` — the
    dataset files plus the minimal ``README.md`` data dictionary, nothing else. The
    candidate can read it but not overwrite or delete it (see ``_make_readonly``); a
    fresh copy replaces any existing one, so this doubles as reset.

    ``data_only=True`` (candidate + admin "provision data" buttons) ships ONLY that data.
    ``data_only=False`` (admin "release starter" full push) additionally copies the
    problem's *writable* working files (``problem.md``, ``starter/`` — never a second
    copy of the data) to ``~/workspace/<problem_id>/``. Returns a destination path, or
    None if there was nothing to copy."""
    src = os.path.join(_session_seed_dir(session_id), problem_id)
    if not os.path.isdir(src):
        _log(f"seed for {problem_id} not found ({src}); did activation package it?")
        return None
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    copied = None

    # dataset → read-only ~/workspace/data/<problem_id>/ (fresh copy each time)
    data_src = os.path.join(src, "data")
    if os.path.isdir(data_src):
        data_dst = _candidate_data_dst(problem_id)
        os.makedirs(os.path.dirname(data_dst), exist_ok=True)
        if os.path.isdir(data_dst):
            _restore_writable(data_dst)
            shutil.rmtree(data_dst, ignore_errors=True)
        shutil.copytree(data_src, data_dst, ignore=ignore)
        _make_readonly(data_dst)
        copied = data_dst
    elif data_only:
        _log(f"{problem_id}: no data/ dir to copy (data_only)")

    # full push: writable working files (never the data) → ~/workspace/<problem_id>/
    if not data_only:
        work_dst = os.path.join(WORKSPACE_DIR, problem_id)
        os.makedirs(work_dst, exist_ok=True)
        for name in sorted(os.listdir(src)):
            if name == "data":
                continue
            s = os.path.join(src, name)
            d = os.path.join(work_dst, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True, ignore=ignore)
            else:
                shutil.copy2(s, d)
        _world_readable(work_dst)
        copied = copied or work_dst

    return copied


def copy_problems_to_workspace(session_id, problem_ids, data_only=False):
    """Copy every assigned problem into the workspace. ``data_only=True`` (candidate)
    ships each problem's read-only dataset into ``~/workspace/data/<id>/`` only;
    ``data_only=False`` (admin) additionally ships the writable working files plus the
    ``PROBLEMS.md`` index. Returns the ids actually copied."""
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


# --- admin file manager over the candidate workspace ------------------------
# The admin panel can browse, view, and manage the single live candidate workspace
# (the `workspace` volume, mounted RW here). Every candidate-supplied path is confined
# to WORKSPACE_DIR by realpath (traversal/symlink guard) before any fs op.
MAX_VIEW_BYTES = int(os.environ.get("WS_FILE_VIEW_MAX_BYTES", str(256 * 1024)))


def _safe_workspace_path(rel):
    """Resolve a workspace-relative path, confined to WORKSPACE_DIR. Rejects traversal
    and symlink escapes; returns an absolute realpath under the workspace or raises."""
    rel = (rel or "").strip().lstrip("/")
    base = os.path.realpath(WORKSPACE_DIR)
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("path is outside the workspace")
    return target, base


def list_workspace(rel=""):
    """List a directory inside the candidate workspace. Returns a dict with the resolved
    relative ``path`` and its ``entries`` (name, rel, is_dir, size, mtime), dirs first."""
    target, base = _safe_workspace_path(rel)
    disp = "" if target == base else os.path.relpath(target, base)
    if not os.path.exists(target):
        return {"path": disp, "exists": False, "is_file": False, "entries": []}
    if os.path.isfile(target):
        return {"path": disp, "exists": True, "is_file": True, "entries": []}
    entries = []
    for name in os.listdir(target):
        p = os.path.join(target, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        is_dir = os.path.isdir(p)
        entries.append({"name": name, "rel": os.path.relpath(p, base), "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime})
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {"path": disp, "exists": True, "is_file": False, "entries": entries}


def read_workspace_file(rel):
    """Return {rel, size, text, binary, truncated} for a workspace file (confined).
    Reads at most MAX_VIEW_BYTES; flags binary content rather than dumping it."""
    target, base = _safe_workspace_path(rel)
    if not os.path.isfile(target):
        raise ValueError("not a file")
    size = os.path.getsize(target)
    with open(target, "rb") as fh:
        raw = fh.read(MAX_VIEW_BYTES + 1)
    truncated = len(raw) > MAX_VIEW_BYTES
    raw = raw[:MAX_VIEW_BYTES]
    disp = os.path.relpath(target, base)
    if b"\x00" in raw:
        return {"rel": disp, "size": size, "binary": True, "text": None, "truncated": truncated}
    return {"rel": disp, "size": size, "binary": False,
            "text": raw.decode("utf-8", "replace"), "truncated": truncated}


def delete_workspace_path(rel):
    """Delete a file or directory inside the workspace (confined). Refuses the workspace
    root itself. Returns the deleted relative path."""
    target, base = _safe_workspace_path(rel)
    if target == base:
        raise ValueError("refusing to delete the workspace root")
    if not os.path.exists(target) and not os.path.islink(target):
        raise ValueError("no such path")
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return os.path.relpath(target, base)


def reset_problem_data(session_id, problem_id):
    """Restore one problem's read-only dataset at ``~/workspace/data/<problem_id>/`` to the
    seeded original. ``copy_problem_to_workspace`` already drops the current copy and
    re-copies fresh, so reset is just a re-provision. Returns the destination or None."""
    return copy_problem_to_workspace(session_id, problem_id, data_only=True)


def clear_workspace_contents():
    """Remove everything under WORKSPACE_DIR (dotfiles included) but keep the mount point
    itself. Confined to WORKSPACE_DIR — never removes the directory or anything outside.
    This is the in-container equivalent of the reset script's wipe, usable mid-session
    (the script is export-gated and lifecycle-only). Returns the count of top-level
    entries removed."""
    base = os.path.realpath(WORKSPACE_DIR)
    if not os.path.isdir(base):
        return 0
    removed = 0
    for name in os.listdir(base):
        p = os.path.join(base, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                _restore_writable(p)              # read-only seed data must still wipe
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            removed += 1
        except OSError:
            pass
    return removed


def problem_has_seed_data(session_id, problem_id):
    """True if this problem ships a candidate dataset — a ``data/`` dir in the session
    seed. Some problems (e.g. a code-only exercise) ship none, so there is simply
    nothing to provision or reset for them; the UI shows that rather than hiding them."""
    return os.path.isdir(os.path.join(_session_seed_dir(session_id), problem_id, "data"))


def session_seed_exists(session_id):
    """True once this session's problems have been packaged into the seed (activation's
    packaging step ran). Distinguishes 'not activated / packaging failed' from 'this
    problem simply ships no dataset' — so provision/reset errors can say which."""
    return os.path.isdir(_session_seed_dir(session_id))


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


def refresh_control_ends_at(session):
    """Rewrite the live control file's ``ends_at`` to match the session — used when the
    clock starts at terms-acceptance (after activation wrote ends_at=None). No-op unless
    the control file already names this session active, so a stale/other session's
    handoff is never clobbered. Informational: ends_at gates only on the portal side."""
    try:
        with open(CONTROL_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (FileNotFoundError, ValueError):
        return
    if doc.get("state") != "active" or doc.get("session_id") != session["id"]:
        return
    doc["ends_at"] = session.get("ends_at")
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
def preflight_activate(session):
    """The part of activation that can legitimately FAIL — run it *before* the session
    state flips to `active`, so a failure leaves the session in `created` and retryable.

    Packaging is the risky step (a problem whose data won't ship makes it raise). It
    needs nothing from the activation itself, so it is safe to do first."""
    package_problems(session)


def on_activate(session):
    """The part of activation that must happen *after* the state flips — the control file
    carries `ends_at`, which only exists once the session is active."""
    key = issue_llm_key(session)
    write_control(session, key)
    model.record_event(session["id"], "system", "workspace_provisioned",
                       {"workspace_user": session["workspace_user"]})


def on_close(session_id):
    revoke_llm_key(session_id)
    clear_control()
