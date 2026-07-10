"""Tests for the session state machine + access-code logic (CONTRIBUTING: the state
machine must have tests). Pure model layer — no HTTP. Run: `pytest` from this dir.
"""
import os
import sys
import tempfile
from datetime import timedelta

import pytest

# Point the model at a throwaway DB / data dir before importing it (env read at import).
_TMP = tempfile.mkdtemp(prefix="portal-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import model  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions; DROP TABLE IF EXISTS admins;")
    con.commit()
    con.close()
    db.init()


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


# --- access codes -----------------------------------------------------------
def test_gen_code_format():
    for _ in range(200):
        code = model.gen_code()
        assert len(code) == 6
        assert all(c in model.CODE_ALPHABET for c in code)
        assert "I" not in code and "O" not in code


def test_normalize_and_validate():
    assert model.normalize_code("  abcdef ") == "ABCDEF"
    assert model.valid_code_format("ABCDEF")
    assert not model.valid_code_format("ABCDE")     # too short
    assert not model.valid_code_format("ABCDE1")    # digit
    assert not model.valid_code_format("ABCDEI")    # excluded letter


def test_auto_code_is_unique_and_wellformed():
    s = _new()
    assert model.valid_code_format(s["access_code"])


def test_manual_code_uppercased_and_clash_rejected():
    s = _new(access_code="abcdef")
    assert s["access_code"] == "ABCDEF"
    with pytest.raises(ValueError):
        _new(access_code="ABCDEF")  # live clash


# --- passwords & cookies ----------------------------------------------------
def test_password_roundtrip():
    h = model.hash_password("s3cret")
    assert model.verify_password("s3cret", h)
    assert not model.verify_password("wrong", h)


def test_cookie_sign_unsign():
    tok = model.sign("abc-123")
    assert model.unsign(tok) == "abc-123"
    assert model.unsign(tok + "x") is None            # tampered sig
    assert model.unsign(tok, max_age=-1) is None       # expired


# --- state machine ----------------------------------------------------------
def test_full_lifecycle():
    s = _new()
    assert s["state"] == "created"
    s = model.activate(s["id"])
    assert s["state"] == "active" and s["ends_at"]
    s = model.close(s["id"])
    assert s["state"] == "closed"
    s = model.mark_exported(s["id"])
    assert s["state"] == "exported"
    s = model.mark_reset(s["id"])
    assert s["state"] == "reset"


def test_illegal_transitions_rejected():
    s = _new()
    with pytest.raises(ValueError):
        model.close(s["id"])          # created -> closed not allowed
    model.activate(s["id"])
    with pytest.raises(ValueError):
        model.mark_exported(s["id"])  # active -> exported not allowed


def test_extend_only_when_active():
    s = _new()
    with pytest.raises(ValueError):
        model.extend(s["id"], 15)
    model.activate(s["id"])
    before = model.get_session(s["id"])["ends_at"]
    after = model.extend(s["id"], 30)["ends_at"]
    assert after > before


def test_events_written_for_each_transition():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    with open(model.events_path(s["id"]), encoding="utf-8") as fh:
        events = [line for line in fh if line.strip()]
    kinds = {__import__("json").loads(e)["event"] for e in events}
    assert {"session_created", "session_activated", "session_closed"} <= kinds


# --- candidate authorization ------------------------------------------------
def test_authorize_code_paths():
    s = _new(access_code="ABCDEF")
    # not started yet
    got, reason = model.authorize_code("abcdef")
    assert got is None and "hasn't started" in reason
    # bad format / unknown
    assert model.authorize_code("nope")[0] is None
    assert model.authorize_code("ZZZZZZ")[0] is None
    # active -> authorized (case-insensitive)
    model.activate(s["id"])
    got, reason = model.authorize_code("abcdef")
    assert got is not None and reason is None


def test_code_expires_after_grace():
    s = _new(access_code="ABCDEF")
    model.activate(s["id"])
    # push ends_at into the past beyond the grace window
    past = (model.now() - timedelta(minutes=model.GRACE_MINUTES + 5)).isoformat(timespec="seconds")
    con = db.connect()
    con.execute("UPDATE sessions SET ends_at=? WHERE id=?", (past, s["id"]))
    con.commit()
    con.close()
    got, reason = model.authorize_code("ABCDEF")
    assert got is None and "expired" in reason


def test_workspace_authz_requires_active_and_terms():
    s = _new()
    assert not model.is_workspace_authorized(s["id"])   # created
    model.activate(s["id"])
    assert not model.is_workspace_authorized(s["id"])   # no terms yet
    model.accept_terms(s["id"])
    assert model.is_workspace_authorized(s["id"])
    model.close(s["id"])
    assert not model.is_workspace_authorized(s["id"])   # closed
