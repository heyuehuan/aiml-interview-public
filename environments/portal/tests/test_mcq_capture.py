"""Fixes: (a) an MCQ cell empty because the platform *could not* capture must
never render as "Not answered"; (b) interviewer testimony notes are append-only and
labelled as testimony; (c) closing without exporting must not let the next activation
wipe the only copy of a session's record.
"""
import json
import os
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="portal-issue1-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import model  # noqa: E402
import views_admin  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    model.MCQ_CAPTURE_SINCE = "2026-01-15T00:00:00+00:00"
    con = db.connect()
    con.executescript(
        "DROP TABLE IF EXISTS sessions; DROP TABLE IF EXISTS mcq_notes;"
        "DROP TABLE IF EXISTS mcq_answers; DROP TABLE IF EXISTS mcq_answer_events;")
    con.commit()
    con.close()
    db.init()


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


# --- not-captured vs not-answered --------------------------------------------
def test_session_closed_before_capture_is_not_captured():
    s = {"closed_at": "2026-01-10T10:00:00+00:00"}
    assert model.mcq_capture_available(s) is False


def test_session_closed_after_capture_is_captured():
    s = {"closed_at": "2026-01-20T10:00:00+00:00"}
    assert model.mcq_capture_available(s) is True


def test_capture_falls_back_through_lifecycle_timestamps():
    # No closed_at (never closed): ends_at, then activated_at, then created_at decide.
    assert model.mcq_capture_available(
        {"closed_at": None, "ends_at": "2026-01-12T09:00:00+00:00"}) is False
    assert model.mcq_capture_available(
        {"closed_at": None, "ends_at": None, "activated_at": None,
         "created_at": "2026-01-21T09:00:00+00:00"}) is True


def test_not_captured_renders_as_its_own_state():
    html = views_admin._answer_status(None, captured=False)
    assert "Not captured" in html
    assert "Not answered" not in html
    # A recorded answer still renders as answered even on an old-looking session.
    assert "Answered" in views_admin._answer_status({"selected": ["A"]}, captured=False)


def test_answers_page_banner_when_not_captured():
    s = _new()
    q = {"qid": "Q1", "title": "Q1. Pick one",
         "options": [{"key": "A", "text": "first"}, {"key": "B", "text": "second"}],
         "answer": None, "trail": [], "notes": []}
    page = views_admin.admin_answers_page(
        "root", s, [{"id": "p1", "questions": [q]}], captured=False)
    assert "could not record" in page
    assert "Not captured" in page
    assert "Not answered" not in page
    # The same page for a captured session keeps the plain status.
    page = views_admin.admin_answers_page(
        "root", s, [{"id": "p1", "questions": [q]}], captured=True)
    assert "Not answered" in page


# --- interviewer testimony notes ---------------------------------------------
def test_note_is_stored_labelled_and_event_logged():
    s = _new()
    model.add_mcq_note(s["id"], "p1", "Q1", "answered aloud: C, full marks", author="root")
    notes = model.mcq_notes(s["id"])
    assert len(notes) == 1
    n = notes[0]
    assert n["author"] == "root" and n["note"].startswith("answered aloud")
    with open(model.events_path(s["id"]), encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    added = [e for e in events if e["event"] == "mcq_note_added"]
    assert len(added) == 1
    assert added[0]["detail"]["note"] == "answered aloud: C, full marks"
    # Rendered as testimony, never as a captured artifact.
    q = {"qid": "Q1", "title": "Q1", "options": [], "answer": None, "trail": [],
         "notes": notes}
    html = views_admin._answer_notes(s["id"], "p1", q)
    assert "Interviewer testimony" in html and "not a captured artifact" in html


def test_empty_note_refused():
    s = _new()
    with pytest.raises(ValueError):
        model.add_mcq_note(s["id"], "p1", "Q1", "   ", author="root")
    assert model.mcq_notes(s["id"]) == []


def test_notes_are_ordered_and_filterable():
    s = _new()
    model.add_mcq_note(s["id"], "p1", "Q1", "first", author="root")
    model.add_mcq_note(s["id"], "p1", "Q2", "second", author="root")
    model.add_mcq_note(s["id"], "p1", "Q1", "third", author="root")
    assert [n["note"] for n in model.mcq_notes(s["id"], "p1", "Q1")] == ["first", "third"]
    assert [n["note"] for n in model.mcq_notes(s["id"])] == ["first", "second", "third"]


def test_overlong_note_truncated_not_refused():
    s = _new()
    model.add_mcq_note(s["id"], "p1", "Q1", "x" * (model.MCQ_NOTE_MAX + 100), author="root")
    assert len(model.mcq_notes(s["id"])[0]["note"]) == model.MCQ_NOTE_MAX


# --- export-before-wipe guard -------------------------------------------------
def _bundle(sid):
    # model.DATA_DIR, not this module's _TMP: pytest imports every test module into one
    # process, so model freezes DATA_DIR to whichever module loaded first.
    d = os.path.join(model.DATA_DIR, "sessions", sid, "export")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{sid}_20260730T000000Z.tar.gz")
    with open(path, "wb") as fh:
        fh.write(b"tar")
    return path


def test_closed_unexported_owner_blocks():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    owner = model.unexported_workspace_owner()
    assert owner and owner["id"] == s["id"]


def test_bundle_on_disk_clears_the_guard():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    _bundle(s["id"])
    assert model.export_bundle_exists(s["id"]) is True
    assert model.unexported_workspace_owner() is None


def test_exported_state_clears_the_guard():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    _bundle(s["id"])
    model.mark_exported(s["id"])
    assert model.unexported_workspace_owner() is None


def test_guard_tracks_only_the_latest_workspace_owner():
    # s1 closed + exported long ago; s2 is the volume's current owner, closed
    # without a bundle — s2 blocks. Once s2 has a bundle, nothing blocks.
    s1 = _new(candidate_name="One", access_code="AAAAAA")
    model.activate(s1["id"])
    model.close(s1["id"])
    _bundle(s1["id"])
    s2 = _new(candidate_name="Two", access_code="BBBBBB")
    model.activate(s2["id"])
    model.close(s2["id"])
    owner = model.unexported_workspace_owner()
    assert owner and owner["id"] == s2["id"]
    _bundle(s2["id"])
    assert model.unexported_workspace_owner() is None


def test_reactivating_the_owner_itself_is_not_blocked():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    assert model.unexported_workspace_owner(exclude_id=s["id"]) is None


def test_active_owner_does_not_block():
    s = _new()
    model.activate(s["id"])
    assert model.unexported_workspace_owner() is None
