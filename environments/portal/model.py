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
DATA_DIR = os.environ.get("DATA_DIR", "/data")
GRACE_MINUTES = int(os.environ.get("CODE_GRACE_MINUTES", "60"))
COOKIE_MAX_AGE = int(os.environ.get("COOKIE_MAX_AGE", str(12 * 3600)))

# Ambiguity-free alphabet: no I or O (look like 1 / 0 even though code is letters-only).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LEN = 6

# created -> active -> closed -> exported -> reset.
TRANSITIONS = {
    "created": {"active"},
    "active": {"closed"},
    "closed": {"exported"},
    "exported": {"reset"},
    "reset": set(),
}
LIVE_STATES = {"created", "active"}  # a code can only map to a not-yet-closed session


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


# --- sessions ---------------------------------------------------------------
DEFAULT_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]


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
                sid, code, candidate_name.strip(), workspace_user.strip(),
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
            (candidate_name.strip(), workspace_user.strip(), code, int(duration_minutes),
             float(llm_budget_usd), json.dumps(llm_models or DEFAULT_MODELS),
             1 if internet_access else 0, terms_text, json.dumps(problem_ids or []), session_id),
        )
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_edited")
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
    starts = now()
    ends = starts + timedelta(minutes=s["duration_minutes"])
    return _transition(
        session_id, "active", actor,
        extra_sql="starts_at=?, ends_at=?, activated_at=?",
        extra_params=(starts.isoformat(timespec="seconds"),
                      ends.isoformat(timespec="seconds"),
                      now_iso()),
        event="session_activated",
        detail={"ends_at": ends.isoformat(timespec="seconds")},
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


def extend(session_id, minutes, actor="admin"):
    s = get_session(session_id)
    if s is None or s["state"] != "active":
        raise ValueError("can only extend an active session")
    ends = datetime.fromisoformat(s["ends_at"]) + timedelta(minutes=int(minutes))
    con = db.connect()
    try:
        con.execute("UPDATE sessions SET ends_at=? WHERE id=?",
                    (ends.isoformat(timespec="seconds"), session_id))
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "session_extended",
                 {"minutes": int(minutes), "ends_at": ends.isoformat(timespec="seconds")})
    return get_session(session_id)


def accept_terms(session_id, actor="candidate"):
    con = db.connect()
    try:
        con.execute("UPDATE sessions SET terms_accepted_at=? WHERE id=? AND terms_accepted_at IS NULL",
                    (now_iso(), session_id))
        con.commit()
    finally:
        con.close()
    record_event(session_id, actor, "terms_accepted")
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
