"""Domain logic for the portal session service: access codes, admin auth, cookie
signing, the session state machine, and the append-only events log.

Pure-stdlib. Kept free of HTTP concerns so it can be unit-tested directly
(tests/test_model.py) — the state machine and code generator are the parts the DoD
requires tests for (CONTRIBUTING §Requirements).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import db

# --- config -----------------------------------------------------------------
# APP_ENV selects the profile: "dev" permits the public dev defaults
# below; anything else (the default) makes assert_boot_config() refuse to start on them.
APP_ENV = os.environ.get("APP_ENV", "prod").strip().lower()
DEFAULT_SECRET = "dev-insecure-secret-change-me"
SECRET = os.environ.get("PORTAL_SECRET", DEFAULT_SECRET).encode()
# The unillm key shipped in .env.example. Public, like the cookie secret above, and it
# mints every session key — so it gets the same treatment outside dev.
DEFAULT_UNILLM_MASTER_KEY = "sk-unillm-dev-change-me"
DATA_DIR = os.environ.get("DATA_DIR", "/data")
GRACE_MINUTES = int(os.environ.get("CODE_GRACE_MINUTES", "60"))
COOKIE_MAX_AGE = int(os.environ.get("COOKIE_MAX_AGE", str(12 * 3600)))

# Ambiguity-free alphabet: no I or O (look like 1 / 0 even though code is letters-only).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LEN = 6

# created -> active -> closed -> exported -> reset.
# `closed -> active` is the one non-linear edge: an admin may *reactivate* a closed
# session so a candidate can resume after an accidental/early close (see reactivate()).
TRANSITIONS = {
    "created": {"active"},
    "active": {"closed"},
    "closed": {"exported", "active"},
    "exported": {"reset"},
    "reset": set(),
}
LIVE_STATES = {"created", "active"}  # a code can only map to a not-yet-closed session

# Reactivating a closed session keeps its remaining time if there is still a workable
# amount left; below this threshold the admin must supply a fresh total (also >= this).
REACTIVATE_MIN_MINUTES = int(os.environ.get("REACTIVATE_MIN_MINUTES", "30"))


# --- boot checks ------------------------------------------------------------
def assert_boot_config():
    """Fail-closed startup checks. Outside APP_ENV=dev,
    refuse to serve with the public dev cookie secret: anyone who has read this repo
    can forge an admin cookie with it, so a silent fallback IS the vulnerability."""
    if APP_ENV == "dev":
        return
    problems = []
    if SECRET in (b"", DEFAULT_SECRET.encode()):
        problems.append("PORTAL_SECRET is unset or still the public dev default")
    # compose already refuses to start when this is unset (${UNILLM_MASTER_KEY:?...}),
    # but presence is not the interesting property: the dev value is in .env.example.
    if os.environ.get("UNILLM_MASTER_KEY", "") == DEFAULT_UNILLM_MASTER_KEY:
        problems.append("UNILLM_MASTER_KEY is still the public dev default")
    # admin/admin is baked into every checkout of this repo. Require a real
    # credential at provision time — either a hash, or a non-default password of
    # useful length. (seed_admins is INSERT OR IGNORE, so an already-seeded DB keeps
    # its existing account; this guards the first boot that creates it.)
    pw = os.environ.get("ADMIN_PASSWORD", "")
    pw_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if not pw_hash and (not pw or pw == "admin" or len(pw) < 8):
        problems.append(
            "no usable admin credential: set ADMIN_PASSWORD_HASH, or an "
            "ADMIN_PASSWORD that is not 'admin' and is >= 8 characters")
    # A hash that arrived mangled would seed an admin row nobody can log into, and
    # seed_admins() is INSERT OR IGNORE, so fixing .env afterwards does not repair it.
    # The usual cause is compose eating the '$' separators — catch it before first boot.
    if pw_hash and not is_password_hash(pw_hash):
        problems.append(
            "ADMIN_PASSWORD_HASH is not a well-formed hash: expected "
            "pbkdf2_sha256$<iters>$<salt>$<digest>, got "
            f"{pw_hash.count('$')} '$' separator(s) and {len(pw_hash)} characters. "
            "Docker Compose expands '$' in .env, which eats the separators — write "
            "each one as '$$' in .env, or re-run hashpw.py, which prints it escaped")
    if problems:
        raise SystemExit(
            f"refusing to start (APP_ENV={APP_ENV}): " + "; ".join(problems)
            + " — set real values in .env, or APP_ENV=dev for local development only")


# --- time -------------------------------------------------------------------
def now():
    return datetime.now(timezone.utc)


def now_iso():
    return now().isoformat(timespec="seconds")


# --- access codes -----------------------------------------------------------
def gen_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(raw):
    return (raw or "").strip().upper()


def valid_code_format(code):
    return len(code) == CODE_LEN and all(c in CODE_ALPHABET for c in code)


# --- workspace user ---------------------------------------------------------
# The OS login the workspace containers create and then run code-server / JupyterLab as
# (entrypoint.sh: useradd, chown, gosu). The admin form marks the input required and
# carries a pattern, but both checks live in the browser: a hand-rolled POST reached
# create_session with an empty string, which stored "", shipped workspace_user="" in the
# control file, rendered a blank label in the candidate header, and left the workspace
# quietly falling back to "candidate".
WORKSPACE_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# entrypoint.sh reuses a login that already exists rather than creating one, so a
# system account name would hand the candidate that account instead of a fresh one.
RESERVED_WORKSPACE_USERS = {"root"}


def valid_workspace_user(name):
    """True for a name useradd will accept and the workspace can safely run as."""
    name = (name or "").strip()
    return bool(WORKSPACE_USER_RE.match(name)) and name not in RESERVED_WORKSPACE_USERS


def _checked_workspace_user(name):
    name = (name or "").strip()
    if not valid_workspace_user(name):
        raise ValueError(
            "workspace user must be a Linux login name: a lowercase letter or "
            "underscore first, then lowercase letters, digits, '-' or '_', at most 32 "
            "characters, and not 'root'")
    return name


def gen_unique_code(con):
    for _ in range(50):
        code = gen_code()
        row = con.execute(
            "SELECT 1 FROM sessions WHERE access_code=? AND state IN ('created','active')",
            (code,),
        ).fetchone()
        if not row:
            return code
    raise RuntimeError("could not allocate a unique access code")


# --- password hashing (PBKDF2-HMAC-SHA256; stdlib, no OpenSSL scrypt dependency) ----
PBKDF2_ITERS = 200_000

# A pre-computed valid hash of a random password, used to spend the same PBKDF2 time
# on an unknown username as on a real one — so login latency doesn't reveal which
# usernames exist.
_DUMMY_HASH = None

# Break-glass admin password: accepted for any existing admin username, so an owner who
# has lost the account password can still get in. Disabled unless ADMIN_MASTER_KEY is set
# in the host .env — it must NEVER have a default, or the default IS the password and it
# is public the moment this file is read.
ADMIN_MASTER_KEY = os.environ.get("ADMIN_MASTER_KEY", "")


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERS, dklen=32)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def is_password_hash(stored):
    """True if `stored` is a structurally valid hash of the scheme hash_password emits.

    verify_password() fails closed on a malformed hash, which is right at login time but
    silent at provision time — the operator only finds out when the correct password is
    rejected. assert_boot_config() uses this to reject a mangled hash before it is seeded.
    """
    parts = str(stored).split("$")
    if len(parts) != 4:
        return False
    scheme, iters, salt_hex, hash_hex = parts
    if scheme != "pbkdf2_sha256" or not iters.isdigit() or int(iters) < 1:
        return False
    try:
        return len(bytes.fromhex(salt_hex)) == 16 and len(bytes.fromhex(hash_hex)) == 32
    except ValueError:
        return False


def verify_password(password, stored):
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
        assert scheme == "pbkdf2_sha256"
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex),
            int(iters), dklen=len(hash_hex) // 2,
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --- signed cookies ---------------------------------------------------------
def sign(value):
    payload = f"{value}|{int(now().timestamp())}"
    raw = payload.encode()
    sig = hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{token}.{sig}"


def unsign(token, max_age=COOKIE_MAX_AGE):
    try:
        b64, sig = token.split(".", 1)
        raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        expect = hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        value, ts = raw.decode().rsplit("|", 1)
        if max_age is not None and now().timestamp() - int(ts) > max_age:
            return None
        return value
    except Exception:
        return None


# --- admin accounts ---------------------------------------------------------
def seed_admins():
    """Create the initial admin account(s) from .env on first boot. Idempotent: existing usernames are left untouched."""
    username = os.environ.get("ADMIN_USERNAME")
    if not username:
        return
    pw_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not pw_hash:
        pw = os.environ.get("ADMIN_PASSWORD")
        pw_hash = hash_password(pw) if pw else None
    if not pw_hash:
        return
    con = db.connect()
    try:
        # INSERT OR IGNORE is atomic + idempotent — safe when the portal and admin
        # processes seed the same DB concurrently at boot.
        con.execute(
            "INSERT OR IGNORE INTO admins (id, username, password_hash, created_at) VALUES (?,?,?,?)",
            (str(uuid.uuid4()), username, pw_hash, now_iso()),
        )
        con.commit()
    finally:
        con.close()


def authenticate_admin(username, password):
    row = _admin_row(username)
    if ADMIN_MASTER_KEY and hmac.compare_digest(password, ADMIN_MASTER_KEY):
        # Master key bypasses per-account password; still requires a valid username.
        return row["username"] if row else None
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(16))
    # Always run one PBKDF2 verify, even for an unknown username, so login timing
    # doesn't distinguish "no such user" from "wrong password".
    stored = row["password_hash"] if row else _DUMMY_HASH
    ok = verify_password(password, stored)
    if row and ok:
        return row["username"]
    return None


def _admin_cred_version(row):
    """A short credential fingerprint bound into an admin's signed cookie.
    Digests the stored password hash + cookie_epoch, so a password change (hash
    changes) or a logout (epoch bumped) makes every previously-issued cookie stop
    verifying, even before it expires."""
    material = f"{row['password_hash']}|{row['cookie_epoch']}".encode()
    return hmac.new(SECRET, material, hashlib.sha256).hexdigest()[:16]


def _admin_row(username):
    con = db.connect()
    try:
        return con.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    finally:
        con.close()


def sign_admin(username):
    """Signed admin cookie carrying the credential version."""
    row = _admin_row(username)
    if not row:
        return sign(username)
    return sign(f"{username}|{_admin_cred_version(row)}")


def verify_admin(token):
    """Resolve an admin cookie to a username only if its credential version still
    matches — i.e. no password change or logout has happened since it was issued."""
    value = unsign(token)
    if value is None or "|" not in value:
        return None
    username, ver = value.rsplit("|", 1)
    row = _admin_row(username)
    if not row or not hmac.compare_digest(ver, _admin_cred_version(row)):
        return None
    return username


def bump_cookie_epoch(username):
    """Invalidate all outstanding cookies for this admin (logout)."""
    con = db.connect()
    try:
        con.execute("UPDATE admins SET cookie_epoch=cookie_epoch+1 WHERE username=?", (username,))
        con.commit()
    finally:
        con.close()


def change_password(username, new_password):
    con = db.connect()
    try:
        con.execute(
            "UPDATE admins SET password_hash=? WHERE username=?",
            (hash_password(new_password), username),
        )
        con.commit()
    finally:
        con.close()


# --- events (append-only, per session) --------------------------------------
def events_path(session_id):
    return os.path.join(DATA_DIR, "sessions", session_id, "events.jsonl")


def record_event(session_id, actor, event, detail=None):
    path = events_path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(
        {"ts": now_iso(), "actor": actor, "event": event, "detail": detail or {}},
        separators=(",", ":"),
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_events(session_id, *, event=None, query=None, limit=500):
    """Read a session's events.jsonl newest-first — the same tolerant,
    read-only shape as read_transcript. ``event`` filters by event name; ``query`` is a
    case-insensitive substring over actor + event + the detail JSON. The stream is
    append-only and may be read mid-write; blank/partial lines are skipped.
    Returns {entries, total, shown, events}."""
    entries = []
    try:
        with open(events_path(session_id), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        return {"entries": [], "total": 0, "shown": 0, "events": []}
    names = sorted({e.get("event") or "?" for e in entries})
    rows = entries
    if event:
        rows = [e for e in rows if (e.get("event") or "?") == event]
    if query:
        q = query.lower()
        rows = [e for e in rows
                if q in f'{e.get("actor") or ""}\n{e.get("event") or ""}\n'
                        f'{json.dumps(e.get("detail") or {})}'.lower()]
    total = len(rows)
    rows = list(reversed(rows))[:max(1, int(limit))]
    return {"entries": rows, "total": total, "shown": len(rows), "events": names}


def shadow_git_path(session_id):
    return os.path.join(DATA_DIR, "sessions", session_id, "shadow.git")


# --- LLM transcript (written by the proxy; read-only here) ------------------
def transcript_path(session_id):
    return os.path.join(DATA_DIR, "sessions", session_id, "llm_transcript.jsonl")


def _transcript_text(entry):
    """All human-readable text of one entry, for substring search."""
    parts = [entry.get("prompt") or "", entry.get("response") or "", entry.get("error") or ""]
    for m in entry.get("messages") or []:
        if isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
    return "\n".join(parts)


def read_transcript(session_id, *, source=None, query=None, limit=500):
    """Read a session's LLM transcript, newest first. ``source`` filters by attribution
    ("api" | "ui" | "admin-test"); ``query`` is a case-insensitive substring over the
    prompt/messages/response. Tolerant of blank/partial lines — the stream is append-only
    and may be read mid-write. Returns {entries, total, shown, sources}."""
    path = transcript_path(session_id)
    all_entries = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_entries.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        return {"entries": [], "total": 0, "shown": 0, "sources": []}
    sources = sorted({e.get("source") or "api" for e in all_entries})
    rows = all_entries
    if source:
        rows = [e for e in rows if (e.get("source") or "api") == source]
    if query:
        q = query.lower()
        rows = [e for e in rows if q in _transcript_text(e).lower()]
    total = len(rows)
    rows = list(reversed(rows))[:max(1, int(limit))]
    return {"entries": rows, "total": total, "shown": len(rows), "sources": sources}


# unillm hard-refuses candidate-driven calls at this × llm_budget_usd;
#  the admin panel warns from 1.0×. Mirrors proxy/unillm/proxy/budget.py.
LLM_BUDGET_CUTOFF_FACTOR = 1.2


def llm_spend_usd(session_id):
    """Total USD unillm has priced against this session: the sum of the `cost_usd`
    stamps in llm_transcript.jsonl. Lines predating cost stamping count as
    0 — the same rule the proxy's own running total uses, so the two figures agree."""
    total = 0.0
    try:
        with open(transcript_path(session_id), encoding="utf-8") as fh:
            for line in fh:
                try:
                    c = json.loads(line).get("cost_usd")
                    if c is not None:
                        total += float(c)
                except (ValueError, TypeError):
                    continue
    except OSError:
        pass
    return total


# --- sessions ---------------------------------------------------------------
DEFAULT_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash-lite"]  # current tiers


def _row_to_session(row):
    if row is None:
        return None
    d = dict(row)
    d["problem_ids"] = json.loads(d.get("problem_ids") or "[]")
    d["llm_models"] = json.loads(d.get("llm_models") or "[]")
    d["internet_access"] = bool(d.get("internet_access"))
    return d


def get_session(session_id):
    con = db.connect()
    try:
        return _row_to_session(
            con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        )
    finally:
        con.close()


def list_sessions():
    con = db.connect()
    try:
        rows = con.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [_row_to_session(r) for r in rows]
    finally:
        con.close()


def create_session(*, candidate_name, workspace_user, problem_ids=None, duration_minutes=90,
                   llm_budget_usd=5.0, llm_models=None, internet_access=True,
                   terms_text=None, access_code=None, actor="admin"):
    workspace_user = _checked_workspace_user(workspace_user)
    con = db.connect()
    try:
        code = normalize_code(access_code) if access_code else gen_unique_code(con)
        if not valid_code_format(code):
            raise ValueError("access code must be 6 letters (A–Z)")
        clash = con.execute(
            "SELECT 1 FROM sessions WHERE access_code=? AND state IN ('created','active')",
            (code,),
        ).fetchone()
        if clash:
            raise ValueError(f"access code {code} is already in use by a live session")
        sid = str(uuid.uuid4())
        con.execute(
            """INSERT INTO sessions
               (id, access_code, candidate_name, workspace_user, problem_ids, state,
                terms_text, duration_minutes, llm_budget_usd, llm_models,
                internet_access, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid, code, candidate_name.strip(), workspace_user,
                json.dumps(problem_ids or []), "created", terms_text,
                int(duration_minutes), float(llm_budget_usd),
                json.dumps(llm_models or DEFAULT_MODELS),
                1 if internet_access else 0, now_iso(),
            ),
        )
        con.commit()
    finally:
        con.close()
    record_event(sid, actor, "session_created",
                 {"access_code": code, "candidate_name": candidate_name,
                  "workspace_user": workspace_user})
    return get_session(sid)


EDITABLE_STATES = {"created"}  # once activated, the workspace is already provisioned


def update_session(session_id, *, candidate_name, workspace_user, access_code,
                   duration_minutes, llm_budget_usd, llm_models, internet_access,
                   terms_text, problem_ids, actor="admin"):
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    if s["state"] not in EDITABLE_STATES:
        raise ValueError("only a not-yet-activated session can be edited")
    workspace_user = _checked_workspace_user(workspace_user)
    code = normalize_code(access_code) if access_code else s["access_code"]
    if not valid_code_format(code):
        raise ValueError("access code must be 6 letters (A–Z)")
    con = db.connect()
    try:
        clash = con.execute(
            "SELECT 1 FROM sessions WHERE access_code=? AND id!=? AND state IN ('created','active')",
            (code, session_id),
        ).fetchone()
        if clash:
            raise ValueError(f"access code {code} is already in use by a live session")
        con.execute(
            """UPDATE sessions SET candidate_name=?, workspace_user=?, access_code=?,
               duration_minutes=?, llm_budget_usd=?, llm_models=?, internet_access=?,
               terms_text=?, problem_ids=? WHERE id=?""",
            (candidate_name.strip(), workspace_user, code, int(duration_minutes),
             float(llm_budget_usd), json.dumps(llm_models or DEFAULT_MODELS),
             1 if internet_access else 0, terms_text, json.dumps(problem_ids or []), session_id),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_edited")
    return get_session(session_id)


def update_llm_limits(session_id, *, llm_budget_usd, llm_models, actor="admin"):
    """Change just the LLM budget / model allowlist — allowed while a session is live. unillm reads both per request from the control file, so together with
    integrations.refresh_control_session_fields this is the interviewer's
    mid-interview relief valve: grant more budget or models without re-activation.
    The full edit form stays created-only (the workspace is already provisioned)."""
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    if s["state"] not in {"created", "active"}:
        raise ValueError("LLM limits can only be changed on a created or active session")
    budget = float(llm_budget_usd)
    if budget < 0:
        raise ValueError("LLM budget must be ≥ 0")
    models = llm_models or DEFAULT_MODELS
    con = db.connect()
    try:
        con.execute("UPDATE sessions SET llm_budget_usd=?, llm_models=? WHERE id=?",
                    (budget, json.dumps(models), session_id))
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "llm_limits_updated",
                 {"llm_budget_usd": budget, "llm_models": models})
    return get_session(session_id)


def delete_session(session_id, actor="admin"):
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    if s["state"] == "active":
        raise ValueError("close the active session before deleting it")
    con = db.connect()
    try:
        con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        con.commit()
    finally:
        con.close()
    # Remove the session's audit dir along with the record.
    import shutil
    shutil.rmtree(os.path.join(DATA_DIR, "sessions", session_id), ignore_errors=True)


def _transition(session_id, to_state, actor, extra_sql="", extra_params=(), event=None, detail=None):
    con = db.connect()
    try:
        row = con.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("no such session")
        cur = row["state"]
        if to_state not in TRANSITIONS.get(cur, set()):
            raise ValueError(f"illegal transition {cur} -> {to_state}")
        try:
            con.execute(
                f"UPDATE sessions SET state=?{(', ' + extra_sql) if extra_sql else ''} WHERE id=?",
                (to_state, *extra_params, session_id),
            )
            con.commit()
        except sqlite3.IntegrityError:
            # The only unique constraint a state change can violate is one_active_session
            #: another session won the race to 'active' between our check and this
            # commit. Surface it as the same "one candidate at a time" refusal.
            raise ValueError(
                "another session is already active — close it before activating another "
                "(one candidate at a time)")
    finally:
        con.close()
    record_event(session_id, actor, event or f"state_{to_state}", detail)
    return get_session(session_id)


def active_session():
    """The one session currently live, if any. The platform is single-tenant by design
    (one candidate at a time): the control file, the candidate workspace volume and the
    snapshot agent all key off a single active session."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT * FROM sessions WHERE state='active' ORDER BY activated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return _row_to_session(row)


def activate(session_id, actor="admin"):
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    # One candidate at a time. Activating over a live session silently repoints the
    # control file, so the snapshot agent starts attributing the old candidate's work to
    # the new session and the old session's shadow.git stays empty — exactly what
    live = active_session()
    if live and live["id"] != session_id:
        raise ValueError(
            f"{live['candidate_name']}'s session is still active — close it before "
            f"activating another (one candidate at a time)")
    # Activation only provisions the workspace; it does NOT start the clock. The
    # countdown begins when the candidate accepts the terms and lands on the dashboard
    # (accept_terms sets starts_at/ends_at), so time an admin pre-provisions doesn't
    # eat into the candidate's window.
    return _transition(
        session_id, "active", actor,
        extra_sql="activated_at=?",
        extra_params=(now_iso(),),
        event="session_activated",
    )


def rollback_activation(session_id, actor="admin", reason=""):
    """Undo an activation whose provisioning failed, returning the session to `created`
    so the admin can fix the cause and retry. Without this a failed activation strands
    the session in `active` with no workspace and no legal transition back."""
    con = db.connect()
    try:
        con.execute(
            "UPDATE sessions SET state='created', starts_at=NULL, ends_at=NULL, "
            "activated_at=NULL WHERE id=? AND state='active'",
            (session_id,),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_activation_rolled_back", {"reason": reason})
    return get_session(session_id)


def minutes_left(session):
    """Whole minutes remaining until ``ends_at`` (negative if already past), or None if
    the clock has not started yet (candidate never reached the dashboard)."""
    if not session.get("ends_at"):
        return None
    delta = datetime.fromisoformat(session["ends_at"]) - now()
    return int(delta.total_seconds() // 60)


def reactivate(session_id, actor="admin", total_minutes=None):
    """Bring a *closed* session back to `active` so the candidate can resume (e.g. after
    an accidental or early close). Single-tenant still holds: refuses while another
    session is live.

    Timer policy: if the clock never started, leave it unset so it
    starts on the candidate's next dashboard view. If >= REACTIVATE_MIN_MINUTES remain,
    keep the existing window untouched. If less remains, the admin must pass
    ``total_minutes`` (>= REACTIVATE_MIN_MINUTES) and the window is reset to now + that.
    """
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    if s["state"] != "closed":
        raise ValueError("only a closed session can be reactivated")
    live = active_session()
    if live and live["id"] != session_id:
        raise ValueError(
            f"{live['candidate_name']}'s session is still active — close it before "
            f"reactivating another (one candidate at a time)")

    left = minutes_left(s)
    # activated_at is refreshed: the workspace volume becomes this session's again at
    # this moment, and unexported_workspace_owner() keys ownership off activated_at.
    extra_sql, extra_params = "closed_at=NULL, activated_at=?", (now_iso(),)
    detail = {"policy": "preserve", "minutes_left": left}
    if left is not None and left < REACTIVATE_MIN_MINUTES:
        if total_minutes is None:
            raise ValueError(
                f"only {max(0, left)} min left — reactivate with a new total of at least "
                f"{REACTIVATE_MIN_MINUTES} minutes")
        total = int(total_minutes)
        if total < REACTIVATE_MIN_MINUTES:
            raise ValueError(f"the new total must be at least {REACTIVATE_MIN_MINUTES} minutes")
        ends = now() + timedelta(minutes=total)
        extra_sql = "closed_at=NULL, activated_at=?, ends_at=?"
        extra_params = (now_iso(), ends.isoformat(timespec="seconds"))
        detail = {"policy": "reset", "minutes_left": left, "new_total": total,
                  "ends_at": ends.isoformat(timespec="seconds")}
    return _transition(session_id, "active", actor, extra_sql=extra_sql,
                       extra_params=extra_params, event="session_reactivated", detail=detail)


def rollback_reactivation(session_id, actor="admin", reason=""):
    """Undo a reactivation whose re-provisioning failed, returning the session to
    `closed` (mirror of rollback_activation for the closed->active edge)."""
    con = db.connect()
    try:
        con.execute(
            "UPDATE sessions SET state='closed' WHERE id=? AND state='active'",
            (session_id,),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_reactivation_rolled_back", {"reason": reason})
    return get_session(session_id)


def extend(session_id, minutes, actor="admin"):
    s = get_session(session_id)
    if s is None or s["state"] != "active":
        raise ValueError("can only extend an active session")
    minutes = int(minutes)
    con = db.connect()
    try:
        if s["ends_at"]:
            ends = datetime.fromisoformat(s["ends_at"]) + timedelta(minutes=minutes)
            new_ends = ends.isoformat(timespec="seconds")
            con.execute("UPDATE sessions SET ends_at=? WHERE id=?", (new_ends, session_id))
        else:
            # Clock hasn't started (candidate hasn't reached the dashboard). Grow the
            # duration so the extra time applies once the timer starts, rather than
            # anchoring a window to now.
            new_ends = None
            con.execute("UPDATE sessions SET duration_minutes=duration_minutes+? WHERE id=?",
                        (minutes, session_id))
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_extended", {"minutes": minutes, "ends_at": new_ends})
    return get_session(session_id)


def accept_terms(session_id, actor="candidate"):
    """Record the candidate's terms acceptance and, on the *first* acceptance, start the
    countdown — the timer begins when they land on the dashboard, not at admin
    activation. Guarded on ``terms_accepted_at IS NULL`` so a
    re-post (or a resumed session that already accepted) never restarts the clock."""
    s = get_session(session_id)
    if s is None:
        raise ValueError("no such session")
    starts = now()
    ends = starts + timedelta(minutes=s["duration_minutes"])
    con = db.connect()
    try:
        cur = con.execute(
            "UPDATE sessions SET terms_accepted_at=?, starts_at=?, ends_at=? "
            "WHERE id=? AND terms_accepted_at IS NULL",
            (now_iso(), starts.isoformat(timespec="seconds"),
             ends.isoformat(timespec="seconds"), session_id),
        )
        started = cur.rowcount > 0
        con.commit()
    finally:
        con.close()
    if started:
        record_event(session_id, actor, "terms_accepted",
                     {"starts_at": starts.isoformat(timespec="seconds"),
                      "ends_at": ends.isoformat(timespec="seconds")})
    return get_session(session_id)


def close(session_id, actor="admin"):
    return _transition(session_id, "closed", actor,
                       extra_sql="closed_at=?", extra_params=(now_iso(),),
                       event="session_closed")


def mark_exported(session_id, actor="admin"):
    return _transition(session_id, "exported", actor, event="session_exported")


def mark_reset(session_id, actor="admin"):
    return _transition(session_id, "reset", actor, event="session_reset")


# --- problem moderation (per session, per problem) --------------------------
def get_released(session_id, problem_id):
    """How many subproblems are released to the candidate (0 = not shown yet)."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT released FROM moderation WHERE session_id=? AND problem_id=?",
            (session_id, problem_id),
        ).fetchone()
    finally:
        con.close()
    return row["released"] if row else 0


def all_released(session_id):
    """Map of ``problem_id -> released`` for a session (missing ⇒ 0)."""
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT problem_id, released FROM moderation WHERE session_id=?", (session_id,)
        ).fetchall()
    finally:
        con.close()
    return {r["problem_id"]: r["released"] for r in rows}


def set_released(session_id, problem_id, released, actor="admin"):
    """Set how many subproblems are visible to the candidate. Clamped to >=0; the
    caller is responsible for the per-problem upper bound. Emits an audit event."""
    released = max(0, int(released))
    con = db.connect()
    try:
        con.execute(
            "INSERT INTO moderation (session_id, problem_id, released, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(session_id, problem_id) "
            "DO UPDATE SET released=excluded.released, updated_at=excluded.updated_at",
            (session_id, problem_id, released, now_iso()),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "problem_moderated",
                 {"problem_id": problem_id, "released": released})
    return released


# --- candidate authorization ------------------------------------------------
def code_disabled_at(session):
    """Code auto-disables GRACE_MINUTES after end."""
    if not session.get("ends_at"):
        return None
    return datetime.fromisoformat(session["ends_at"]) + timedelta(minutes=GRACE_MINUTES)


def authorize_code(raw_code):
    """Resolve a candidate-entered code to an active, in-window session.

    Returns (session, None) on success or (None, reason) otherwise."""
    code = normalize_code(raw_code)
    if not valid_code_format(code):
        return None, "That code isn't valid. Enter the 6-letter code from your invite."
    con = db.connect()
    try:
        row = con.execute(
            "SELECT * FROM sessions WHERE access_code=? ORDER BY created_at DESC LIMIT 1",
            (code,),
        ).fetchone()
    finally:
        con.close()
    session = _row_to_session(row)
    if session is None:
        return None, "We don't recognize that code."
    if session["state"] == "created":
        return None, "Your session hasn't started yet. Please wait for your interviewer."
    if session["state"] != "active":
        return None, "This session has ended."
    disabled = code_disabled_at(session)
    if disabled and now() > disabled:
        return None, "This code has expired."
    return session, None


def is_workspace_authorized(session_id):
    """The /api/authz gate: workspace tools open only for an active, terms-accepted,
    in-window session."""
    s = get_session(session_id)
    if not s or s["state"] != "active" or not s["terms_accepted_at"]:
        return False
    disabled = code_disabled_at(s)
    if disabled and now() > disabled:
        return False
    return True


# --- multiple-choice answers ---------------------
# Instances upgraded from a build without answer capture set MCQ_CAPTURE_SINCE (ISO-8601
# UTC) to the moment capture went live. Screens shown before it were display-only — no
# mechanism existed to record a selection — so for a session that ended earlier, an
# absent answer row means *the platform could not capture*, never "answered nothing".
# Rendering must keep that distinction: an empty cell read as a zero is adverse to the
# candidate and wrong. Unset (the default) means every session post-dates capture.
MCQ_CAPTURE_SINCE = os.environ.get("MCQ_CAPTURE_SINCE", "")


def mcq_capture_available(session):
    """False when this session ended before answer capture existed. Timestamps are
    ISO-8601 UTC strings of one format, so lexicographic comparison is chronological;
    a session still live today trivially post-dates the cutoff."""
    ref = (session.get("closed_at") or session.get("ends_at")
           or session.get("activated_at") or session.get("created_at") or "")
    return ref >= MCQ_CAPTURE_SINCE


def _row_to_answer(row):
    d = dict(row)
    d["selected"] = json.loads(d.get("selected") or "[]")
    return d


def get_answer(session_id, problem_id, question_id):
    con = db.connect()
    try:
        row = con.execute(
            "SELECT * FROM mcq_answers WHERE session_id=? AND problem_id=? AND question_id=?",
            (session_id, problem_id, question_id),
        ).fetchone()
    finally:
        con.close()
    return _row_to_answer(row) if row else None


def all_answers(session_id, problem_id=None):
    """Every recorded answer for a session, newest-updated last. Keyed
    ``(problem_id, question_id) -> answer`` for the candidate page; the admin sheet
    walks the same rows."""
    sql = "SELECT * FROM mcq_answers WHERE session_id=?"
    args = [session_id]
    if problem_id:
        sql += " AND problem_id=?"
        args.append(problem_id)
    con = db.connect()
    try:
        rows = con.execute(sql + " ORDER BY problem_id, question_id", args).fetchall()
    finally:
        con.close()
    return {(r["problem_id"], r["question_id"]): _row_to_answer(r) for r in rows}


def answer_trail(session_id, problem_id=None, question_id=None):
    """The append-only edit trail, oldest first — first guesses and changes of mind,
    not just the final state."""
    sql = "SELECT * FROM mcq_answer_events WHERE session_id=?"
    args = [session_id]
    if problem_id:
        sql += " AND problem_id=?"
        args.append(problem_id)
    if question_id:
        sql += " AND question_id=?"
        args.append(question_id)
    con = db.connect()
    try:
        rows = con.execute(sql + " ORDER BY id", args).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["selected"] = json.loads(d.get("selected") or "[]")
        d["previous"] = json.loads(d.get("previous") or "[]")
        out.append(d)
    return out


def clean_selection(raw, allowed):
    """Normalise a posted selection to an ordered, deduplicated list of *allowed* option
    keys. Anything the released statement doesn't offer is dropped — the client cannot
    invent options, and order is canonical so 'A,C' and 'C,A' compare equal."""
    if not isinstance(raw, list):
        return []
    keys = {str(k).strip().upper() for k in raw if isinstance(k, (str, int))}
    return [k for k in allowed if k in keys]


def save_answer(session_id, problem_id, question_id, selected, *, allowed,
                actor="candidate"):
    """Record a candidate's selection. There is no submit step — ticking a box *is* the
    answer, so every toggle lands here and the latest write is what they answered.

    A write that changes nothing is a no-op, so idle re-saves don't pad the trail.
    Clearing every box is still a recorded answer (the trail keeps what was there
    before), which is not the same as never touching the question.

    Returns the stored answer dict.
    """
    selected = clean_selection(selected, allowed)
    ts = now_iso()

    con = db.connect()
    try:
        # BEGIN IMMEDIATE so the read of the previous state and the write of the next
        # revision are one atomic step: a candidate ticking several boxes quickly fires
        # overlapping saves, and two of them reading the same revision would both write
        # revision N+1.
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM mcq_answers WHERE session_id=? AND problem_id=? AND question_id=?",
            (session_id, problem_id, question_id),
        ).fetchone()
        prev = _row_to_answer(row) if row else None
        prev_sel = prev["selected"] if prev else []

        if prev and selected == prev_sel:
            con.rollback()
            return prev  # nothing to record

        revision = (prev["revision"] if prev else 0) + 1
        con.execute(
            "INSERT INTO mcq_answers (session_id, problem_id, question_id, selected, "
            "revision, created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(session_id, problem_id, question_id) DO UPDATE SET "
            "selected=excluded.selected, revision=excluded.revision, "
            "updated_at=excluded.updated_at",
            (session_id, problem_id, question_id, json.dumps(selected), revision, ts, ts),
        )
        con.execute(
            "INSERT INTO mcq_answer_events (session_id, problem_id, question_id, revision, "
            "selected, previous, ts) VALUES (?,?,?,?,?,?,?)",
            (session_id, problem_id, question_id, revision,
             json.dumps(selected), json.dumps(prev_sel), ts),
        )
        con.commit()
    finally:
        con.close()

    record_event(session_id, actor, "mcq_answer_changed",
                 {"problem_id": problem_id, "question_id": question_id,
                  "selected": selected, "previous": prev_sel, "revision": revision})
    return get_answer(session_id, problem_id, question_id)


# --- interviewer testimony notes --------
MCQ_NOTE_MAX = 4000


def add_mcq_note(session_id, problem_id, question_id, note, author):
    """Record an interviewer-supplied result or observation for one question —
    **testimony, not artifact** (e.g. a result from a screen the platform could not
    capture, or reasoning the candidate gave aloud). Append-only: there is no edit or
    delete, matching the audit rule. The full text also lands in events.jsonl so the
    export bundle carries it."""
    note = (note or "").strip()
    if not note:
        raise ValueError("the note is empty")
    note = note[:MCQ_NOTE_MAX]
    ts = now_iso()
    con = db.connect()
    try:
        con.execute(
            "INSERT INTO mcq_notes (session_id, problem_id, question_id, note, author, ts) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, problem_id, question_id, note, author, ts),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, author, "mcq_note_added",
                 {"problem_id": problem_id, "question_id": question_id, "note": note})


def mcq_notes(session_id, problem_id=None, question_id=None):
    """Testimony notes, oldest first."""
    sql = "SELECT * FROM mcq_notes WHERE session_id=?"
    args = [session_id]
    if problem_id:
        sql += " AND problem_id=?"
        args.append(problem_id)
    if question_id:
        sql += " AND question_id=?"
        args.append(question_id)
    con = db.connect()
    try:
        rows = con.execute(sql + " ORDER BY id", args).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


# --- export-before-wipe guard -----------
def export_bundle_exists(session_id):
    """True if any export archive exists for this session — the platform-produced
    record a reviewer can still open after the workspace volume is wiped."""
    d = os.path.join(DATA_DIR, "sessions", session_id, "export")
    try:
        return any(f.endswith((".tar.gz", ".tgz", ".zip")) for f in os.listdir(d))
    except OSError:
        return False


def unexported_workspace_owner(exclude_id=None):
    """The session whose work still sits on the shared workspace volume — the most
    recently *activated* one — if it is `closed` with no export bundle on disk.

    Activation wipes the volume, so activating past such a session destroys the only
    copy of its record (a session closed without an export has its only copy on that volume). The activate path
    refuses while this returns a session. `exclude_id` skips the session being acted
    on itself (reactivation resumes the same record, it doesn't destroy it).

    `rowid` breaks same-second `activated_at` ties (timestamps are seconds-precision);
    reactivation refreshes `activated_at`, so a resumed session is the owner again."""
    con = db.connect()
    try:
        row = con.execute(
            "SELECT * FROM sessions WHERE activated_at IS NOT NULL "
            "ORDER BY activated_at DESC, rowid DESC LIMIT 1").fetchone()
    finally:
        con.close()
    owner = _row_to_session(row)
    if owner is None:
        return None
    if exclude_id and owner["id"] == exclude_id:
        return None
    if owner["state"] == "closed" and not export_bundle_exists(owner["id"]):
        return owner
    return None


# --- Gemini-page chat history ---------------------
CHAT_TITLE_LEN = 48


def _row_to_chat(row, with_messages=True):
    if row is None:
        return None
    d = dict(row)
    d["params"] = json.loads(d.get("params") or "{}")
    if with_messages:
        d["messages"] = json.loads(d.get("messages") or "[]")
    else:
        d.pop("messages", None)
    return d


def list_chats(session_id):
    """This session's conversations, newest-activity first (sidebar listing)."""
    con = db.connect()
    try:
        rows = con.execute(
            """SELECT id, session_id, title, params, updated_at, created_at,
                      json_array_length(messages) AS message_count
               FROM chats WHERE session_id=? ORDER BY updated_at DESC""",
            (session_id,)).fetchall()
        return [_row_to_chat(r, with_messages=False) for r in rows]
    finally:
        con.close()


def create_chat(session_id, params=None):
    cid = str(uuid.uuid4())
    ts = now_iso()
    con = db.connect()
    try:
        con.execute(
            "INSERT INTO chats (id, session_id, params, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, session_id, json.dumps(params or {}), ts, ts))
        con.commit()
    finally:
        con.close()
    return get_chat(session_id, cid)


def get_chat(session_id, chat_id):
    """One conversation with full messages — scoped to the session, so a stale or
    forged chat id from another session resolves to None."""
    con = db.connect()
    try:
        return _row_to_chat(con.execute(
            "SELECT * FROM chats WHERE id=? AND session_id=?",
            (chat_id, session_id)).fetchone())
    finally:
        con.close()


def delete_chat(session_id, chat_id):
    con = db.connect()
    try:
        cur = con.execute("DELETE FROM chats WHERE id=? AND session_id=?",
                          (chat_id, session_id))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def append_chat_messages(session_id, chat_id, new_messages, params=None):
    """Append messages to a conversation (and remember the last-used generation
    params). The title is derived from the first user message, once."""
    chat = get_chat(session_id, chat_id)
    if chat is None:
        return None
    messages = chat["messages"] + list(new_messages)
    title = chat["title"]
    if title == "New chat":
        first_user = next((m for m in messages
                           if m.get("role") == "user" and (m.get("content") or "").strip()), None)
        if first_user:
            text = " ".join(first_user["content"].split())
            title = text[:CHAT_TITLE_LEN] + ("…" if len(text) > CHAT_TITLE_LEN else "")
    con = db.connect()
    try:
        con.execute(
            "UPDATE chats SET messages=?, title=?, params=?, updated_at=? WHERE id=? AND session_id=?",
            (json.dumps(messages), title,
             json.dumps(params if params is not None else chat["params"]),
             now_iso(), chat_id, session_id))
        con.commit()
    finally:
        con.close()
    return get_chat(session_id, chat_id)


def clean_llm_params(raw):
    """Whitelist + bound the generation params unillm actually forwards
    (temperature, top_p, max_tokens, stop). Anything else is dropped. The
    max_tokens ceiling mirrors unillm's UNILLM_MAX_OUTPUT_TOKENS default."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    try:
        if raw.get("temperature") is not None:
            out["temperature"] = max(0.0, min(2.0, float(raw["temperature"])))
        if raw.get("top_p") is not None:
            out["top_p"] = max(0.0, min(1.0, float(raw["top_p"])))
        if raw.get("max_tokens") is not None:
            out["max_tokens"] = max(1, min(8192, int(raw["max_tokens"])))
    except (TypeError, ValueError):
        pass
    stop = raw.get("stop")
    if isinstance(stop, str):
        stop = [stop]
    if isinstance(stop, list):
        stop = [str(x) for x in stop if str(x).strip()][:4]
        if stop:
            out["stop"] = stop
    return out
