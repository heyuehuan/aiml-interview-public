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


def test_is_password_hash_rejects_a_compose_mangled_hash():
    h = model.hash_password("s3cret")
    assert model.is_password_hash(h)
    # What compose leaves behind when the '$' separators in .env are interpolated away.
    scheme, iters, salt, _digest = h.split("$")
    assert not model.is_password_hash(f"{scheme}${iters}${salt}")
    assert not model.is_password_hash(scheme + iters + salt + _digest)
    assert not model.is_password_hash("s3cret")        # plaintext pasted by mistake
    assert not model.is_password_hash(f"bcrypt${iters}${salt}${_digest}")


def test_boot_config_refuses_a_mangled_admin_hash(monkeypatch):
    h = model.hash_password("s3cret")
    monkeypatch.setattr(model, "APP_ENV", "prod")
    monkeypatch.setattr(model, "SECRET", b"a-real-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    monkeypatch.setenv("ADMIN_PASSWORD_HASH", h)
    model.assert_boot_config()                          # well-formed: boots

    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "$".join(h.split("$")[:3]))
    with pytest.raises(SystemExit) as e:
        model.assert_boot_config()
    assert "ADMIN_PASSWORD_HASH" in str(e.value) and "$$" in str(e.value)


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
    # Activation provisions but does NOT start the clock (that happens at terms accept).
    assert s["state"] == "active" and s["ends_at"] is None and s["activated_at"]
    s = model.close(s["id"])
    assert s["state"] == "closed"
    s = model.mark_exported(s["id"])
    assert s["state"] == "exported"
    s = model.mark_reset(s["id"])
    assert s["state"] == "reset"


def test_timer_starts_at_terms_acceptance_not_activation():
    s = _new(duration_minutes=90)
    s = model.activate(s["id"])
    assert s["starts_at"] is None and s["ends_at"] is None   # clock not running yet
    s = model.accept_terms(s["id"])
    assert s["starts_at"] and s["ends_at"]                   # started on first acceptance
    left = model.minutes_left(s)
    assert 88 <= left <= 90                                  # ~full duration from now
    # A repeat acceptance must not restart the clock.
    ends_first = s["ends_at"]
    s = model.accept_terms(s["id"])
    assert s["ends_at"] == ends_first


def test_illegal_transitions_rejected():
    s = _new()
    with pytest.raises(ValueError):
        model.close(s["id"])          # created -> closed not allowed
    model.activate(s["id"])
    with pytest.raises(ValueError):
        model.mark_exported(s["id"])  # active -> exported not allowed


# --- LLM transcript reader --------------------------------------------------
def _write_transcript(sid, entries):
    import json as _json
    path = model.transcript_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(_json.dumps(e) + "\n")
        fh.write("\n")            # a blank/partial line must be tolerated


def test_read_transcript_missing_is_empty():
    s = _new()
    data = model.read_transcript(s["id"])
    assert data == {"entries": [], "total": 0, "shown": 0, "sources": []}


def test_read_transcript_newest_first_with_filters():
    s = _new()
    _write_transcript(s["id"], [
        {"ts": "t1", "source": "api", "prompt": "gradient boosting help", "response": "sure"},
        {"ts": "t2", "source": "ui", "messages": [{"role": "user", "content": "hello there"}]},
        {"ts": "t3", "source": "api", "prompt": "unrelated", "response": "pandas merge"},
    ])
    all_ = model.read_transcript(s["id"])
    assert all_["total"] == 3 and all_["sources"] == ["api", "ui"]
    assert all_["entries"][0]["ts"] == "t3"                      # newest first

    ui = model.read_transcript(s["id"], source="ui")
    assert ui["total"] == 1 and ui["entries"][0]["source"] == "ui"

    hit = model.read_transcript(s["id"], query="PANDAS")          # case-insensitive, over response
    assert hit["total"] == 1 and hit["entries"][0]["ts"] == "t3"

    both = model.read_transcript(s["id"], source="api", query="gradient")
    assert both["total"] == 1 and both["entries"][0]["ts"] == "t1"


def test_extend_only_when_active():
    s = _new()
    with pytest.raises(ValueError):
        model.extend(s["id"], 15)
    model.activate(s["id"])
    model.accept_terms(s["id"])                          # start the clock
    before = model.get_session(s["id"])["ends_at"]
    after = model.extend(s["id"], 30)["ends_at"]
    assert after > before


def test_extend_before_clock_starts_grows_duration():
    s = _new(duration_minutes=60)
    model.activate(s["id"])                              # ends_at still None
    s = model.extend(s["id"], 30)
    assert s["ends_at"] is None and s["duration_minutes"] == 90
    # the grown duration is what the timer uses once the candidate accepts terms
    s = model.accept_terms(s["id"])
    assert 88 <= model.minutes_left(s) <= 90


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


def _edit_kwargs(**over):
    base = dict(candidate_name="Alex Doe", workspace_user="candidate", access_code="ABCDEF",
                duration_minutes=90, llm_budget_usd=5, llm_models=None, internet_access=True,
                terms_text=None, problem_ids=[])
    base.update(over)
    return base


def test_update_session_only_before_activation():
    s = _new(access_code="ABCDEF")
    updated = model.update_session(s["id"], **_edit_kwargs(candidate_name="Sam Roe",
                                                           workspace_user="sam", duration_minutes=60))
    assert updated["candidate_name"] == "Sam Roe"
    assert updated["workspace_user"] == "sam"
    assert updated["duration_minutes"] == 60
    model.activate(s["id"])
    with pytest.raises(ValueError):
        model.update_session(s["id"], **_edit_kwargs())  # active -> not editable


def test_update_session_code_clash_rejected():
    a = _new(access_code="AAAAAA")
    _new(access_code="BBBBBB")
    with pytest.raises(ValueError):
        model.update_session(a["id"], **_edit_kwargs(access_code="BBBBBB"))


def test_delete_session():
    s = _new()
    model.delete_session(s["id"])
    assert model.get_session(s["id"]) is None


def test_delete_active_session_rejected():
    s = _new()
    model.activate(s["id"])
    with pytest.raises(ValueError):
        model.delete_session(s["id"])


def test_workspace_authz_requires_active_and_terms():
    s = _new()
    assert not model.is_workspace_authorized(s["id"])   # created
    model.activate(s["id"])
    assert not model.is_workspace_authorized(s["id"])   # no terms yet
    model.accept_terms(s["id"])
    assert model.is_workspace_authorized(s["id"])
    model.close(s["id"])
    assert not model.is_workspace_authorized(s["id"])   # closed


# --- one candidate at a time ----------------------------
# The platform is single-tenant by construction: one control file, one workspace volume,
# one snapshot agent. If two sessions were activated concurrently, the second would
# silently repoint the control file, and the first candidate's shadow.git would stay
# empty while their work was attributed to the second session.
def test_only_one_session_can_be_active():
    first = _new(candidate_name="First")
    second = _new(candidate_name="Second")
    model.activate(first["id"])
    with pytest.raises(ValueError, match="still active"):
        model.activate(second["id"])
    assert model.get_session(second["id"])["state"] == "created"   # untouched, retryable
    assert model.active_session()["id"] == first["id"]


def test_next_session_activates_once_the_live_one_closes():
    first, second = _new(candidate_name="First"), _new(candidate_name="Second")
    model.activate(first["id"])
    model.close(first["id"])
    model.activate(second["id"])                                    # no longer blocked
    assert model.active_session()["id"] == second["id"]


def test_reactivating_the_same_session_is_not_self_blocked():
    s = _new()
    model.activate(s["id"])
    with pytest.raises(ValueError, match="illegal transition"):     # not "still active"
        model.activate(s["id"])


# The application-level guard in activate() is a check-then-act across two connections,
# so a concurrent activation could slip past it. The real backstop is the partial
# unique index: even if the app check is bypassed entirely, the DB refuses a second
# 'active' row. This asserts that invariant directly.
def test_second_active_row_is_rejected_at_the_db_level():
    import sqlite3
    first, second = _new(candidate_name="First"), _new(candidate_name="Second")
    model.activate(first["id"])
    con = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE sessions SET state='active' WHERE id=?", (second["id"],))
            con.commit()
    finally:
        con.close()
    # The failed write left the first session as the sole active one.
    assert model.active_session()["id"] == first["id"]


# --- activation rollback --------------------------------
# Provisioning (LLM key + control file) runs after the state flips. If it fails, the
# session must fall back to `created` — otherwise it strands in `active` with no
# workspace and no legal transition back, and the admin cannot retry.
def test_rollback_activation_restores_a_retryable_session():
    s = _new()
    model.activate(s["id"])
    assert model.get_session(s["id"])["state"] == "active"

    model.rollback_activation(s["id"], reason="packager blew up")
    back = model.get_session(s["id"])
    assert back["state"] == "created"
    assert back["ends_at"] is None and back["activated_at"] is None
    assert model.active_session() is None       # frees the single-active slot


# --- reactivation: closed -> active ----------------------------
def _closed_with_left(minutes_left, duration=90):
    """A closed session whose ends_at sits `minutes_left` minutes from now."""
    s = _new()
    model.activate(s["id"])
    model.accept_terms(s["id"])                 # starts the clock
    target = (model.now() + timedelta(minutes=minutes_left)).isoformat(timespec="seconds")
    con = db.connect()
    con.execute("UPDATE sessions SET ends_at=? WHERE id=?", (target, s["id"]))
    con.commit()
    con.close()
    model.close(s["id"])
    return model.get_session(s["id"])


def test_reactivate_preserves_ample_remaining_time():
    s = _closed_with_left(75)
    ends_before = s["ends_at"]
    s = model.reactivate(s["id"])
    assert s["state"] == "active"
    assert s["ends_at"] == ends_before          # window untouched
    assert model.active_session()["id"] == s["id"]


def test_reactivate_with_low_time_requires_a_fresh_total():
    s = _closed_with_left(10)                    # below the 30-min threshold
    with pytest.raises(ValueError, match="at least"):
        model.reactivate(s["id"])                # no total supplied
    assert model.get_session(s["id"])["state"] == "closed"   # not flipped
    s = model.reactivate(s["id"], total_minutes=45)
    assert s["state"] == "active"
    assert 43 <= model.minutes_left(s) <= 45


def test_reactivate_rejects_total_below_minimum():
    s = _closed_with_left(5)
    with pytest.raises(ValueError, match="at least"):
        model.reactivate(s["id"], total_minutes=20)


def test_reactivate_not_started_leaves_clock_unset():
    # Candidate never accepted terms, so the clock never started; reactivation keeps it
    # unset and it starts when they reopen the dashboard.
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    assert model.get_session(s["id"])["ends_at"] is None
    s = model.reactivate(s["id"])
    assert s["state"] == "active" and s["ends_at"] is None


def test_reactivate_only_from_closed():
    s = _new()
    with pytest.raises(ValueError, match="closed"):
        model.reactivate(s["id"])                # created
    model.activate(s["id"])
    with pytest.raises(ValueError, match="closed"):
        model.reactivate(s["id"])                # active


def test_reactivate_blocked_while_another_session_is_live():
    first = _closed_with_left(60)
    second = _new(candidate_name="Second")
    model.activate(second["id"])                 # someone else is now live
    with pytest.raises(ValueError, match="still active"):
        model.reactivate(first["id"])
    assert model.get_session(first["id"])["state"] == "closed"


def test_rollback_reactivation_returns_to_closed():
    s = _closed_with_left(60)
    model.reactivate(s["id"])
    assert model.get_session(s["id"])["state"] == "active"
    model.rollback_reactivation(s["id"], reason="provisioning failed")
    assert model.get_session(s["id"])["state"] == "closed"
    assert model.active_session() is None

    model.activate(s["id"])                     # the whole point: retry works
    assert model.get_session(s["id"])["state"] == "active"


def test_rollback_is_recorded_in_the_audit_log():
    s = _new()
    model.activate(s["id"])
    model.rollback_activation(s["id"], reason="boom")
    with open(model.events_path(s["id"])) as fh:
        events = [__import__("json").loads(l)["event"] for l in fh]
    assert "session_activation_rolled_back" in events


# --- break-glass admin key must not have a default ------
def test_admin_master_key_is_disabled_unless_configured():
    """A default value here IS the admin password, and it is public the moment anyone
    reads the source. It must be opt-in via the host .env."""
    assert model.ADMIN_MASTER_KEY == "" or os.environ.get("ADMIN_MASTER_KEY")
