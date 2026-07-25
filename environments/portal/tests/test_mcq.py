"""Tests for multiple-choice answer capture.

Two halves: the structural detection of option runs in a statement (registry), and the
recording of what the candidate selected — every change, with timestamps, plus the final
answer (model + events.jsonl).
"""
import json
import os
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="portal-mcq-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import model  # noqa: E402
import registry  # noqa: E402
import views  # noqa: E402


SID = "session-mcq"


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS mcq_answers;"
                      "DROP TABLE IF EXISTS mcq_answer_events;")
    con.commit()
    con.close()
    db.init()
    # events.jsonl is append-only by design — start each test from an empty stream so
    # counts are the test's own.
    path = model.events_path(SID)
    if os.path.exists(path):
        os.remove(path)



PID = "quiz-001"

STATEMENT = """\
# Quiz

Some background prose.

## Q1. What does this do?

- **A.** Appends new files.
- **B.** Deletes the directory first.
- **C.** Writes a single file.

Pick carefully.

## Q2. Not a multiple choice question

Explain in your own words. Consider:

- the evaluation order
- the write path
"""


@pytest.fixture
def statement(monkeypatch):
    monkeypatch.setattr(registry, "read_problem_md", lambda pid: STATEMENT)


# --- detection --------------------------------------------------------------
def test_option_run_becomes_a_question(statement):
    blocks = registry.released_blocks(PID, 1)
    kinds = [b["kind"] for b in blocks]
    assert "mcq" in kinds, "the A/B/C run should be detected as a question"
    mcq = [b for b in blocks if b["kind"] == "mcq"][0]
    assert mcq["qid"] == "Q1"
    assert [o["key"] for o in mcq["options"]] == ["A", "B", "C"]
    assert "Deletes the directory first." in mcq["options"][1]["html"]
    # prose on both sides of the run survives as ordinary Markdown
    html = "".join(b["html"] for b in blocks if b["kind"] == "md")
    assert "Some background prose." in html and "Pick carefully." in html


def test_ordinary_bullets_are_not_a_question(statement):
    """Q2's bullets don't start A/B/C, so they must stay a plain list."""
    blocks = registry.released_blocks(PID, 2)
    q2 = [b for b in blocks if b["kind"] == "mcq" and b["qid"] == "Q2"]
    assert q2 == []
    assert "<li>the evaluation order</li>" in "".join(
        b["html"] for b in blocks if b["kind"] == "md")


def test_moderation_still_gates_questions(statement):
    """A question the interviewer hasn't released is not offered — and the portal's
    allowlist is what the answer route checks."""
    assert registry.question_ids(PID, 0) == {}
    assert list(registry.question_ids(PID, 1)) == ["Q1"]


def test_render_released_still_returns_html(statement):
    """The plain renderer keeps working for callers that don't build a form."""
    html = registry.render_released(PID, 1)
    assert "<strong>A.</strong>" in html and "Appends new files." in html


def test_options_wrapped_over_several_lines_stay_one_run(monkeypatch):
    """The real statements wrap most options onto indented continuation lines. Reading a
    continuation as the end of the run drops every option after the first."""
    monkeypatch.setattr(registry, "read_problem_md", lambda pid: """\
## Q1. Wrapped

- **A.** Returns the cached result, leaving any existing output in place.
- **B.** Recomputes the result from scratch, then writes
  it back as one or more chunk files under it.
- **C.** Writes a single file.
- **D.** Raises an error.
""")
    q = registry.all_question_ids(PID)[0]
    assert [o["key"] for o in q["options"]] == ["A", "B", "C", "D"]
    assert q["options"][1]["text"].endswith("files under it.")


def test_options_separated_by_blank_lines_stay_one_run(monkeypatch):
    monkeypatch.setattr(registry, "read_problem_md", lambda pid: """\
## Q1. Loose

- **A.** first

- **B.** second

Now some prose that ends the run.
""")
    blocks = registry.released_blocks(PID, 1)
    mcq = [b for b in blocks if b["kind"] == "mcq"][0]
    assert [o["key"] for o in mcq["options"]] == ["A", "B"]
    assert "Now some prose" in "".join(b["html"] for b in blocks if b["kind"] == "md")


def test_run_must_start_at_a(monkeypatch):
    """A bullet list that happens to start 'B.' is prose, not a question."""
    monkeypatch.setattr(registry, "read_problem_md", lambda pid: """\
## Q1. Not options

- **B.** something
- **C.** something else
""")
    assert registry.all_question_ids(PID) == []


def test_second_run_in_one_subproblem_gets_its_own_id(monkeypatch):
    monkeypatch.setattr(registry, "read_problem_md", lambda pid: """\
## Q1. Two parts

- **A.** first
- **B.** second

and then

- **A.** third
- **B.** fourth
""")
    qids = list(registry.question_ids(PID, 1))
    assert qids == ["Q1", "Q1-2"]


# --- recording --------------------------------------------------------------
ALLOWED = ["A", "B", "C"]


def _events():
    path = model.events_path(SID)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_multiple_options_can_be_selected():
    a = model.save_answer(SID, PID, "Q1", ["C", "A"], allowed=ALLOWED)
    # normalised to the statement's own order, so "A,C" and "C,A" compare equal
    assert a["selected"] == ["A", "C"]
    assert a["final"] is False and a["revision"] == 1


def test_invented_options_are_dropped():
    a = model.save_answer(SID, PID, "Q1", ["A", "Z", "", 7], allowed=ALLOWED)
    assert a["selected"] == ["A"]


def test_every_change_is_recorded_with_a_timestamp():
    model.save_answer(SID, PID, "Q1", ["A"], allowed=ALLOWED)
    model.save_answer(SID, PID, "Q1", ["A", "B"], allowed=ALLOWED)
    model.save_answer(SID, PID, "Q1", ["B"], allowed=ALLOWED)

    trail = model.answer_trail(SID, PID, "Q1")
    assert [t["selected"] for t in trail] == [["A"], ["A", "B"], ["B"]]
    assert [t["previous"] for t in trail] == [[], ["A"], ["A", "B"]]
    assert [t["action"] for t in trail] == ["change", "change", "change"]
    assert [t["revision"] for t in trail] == [1, 2, 3]
    assert all(t["ts"] for t in trail), "every entry carries a timestamp"

    # and the same trail lands in the append-only audit stream the export bundles
    changed = [e for e in _events() if e["event"] == "mcq_answer_changed"]
    assert len(changed) == 3
    assert changed[-1]["detail"] == {"problem_id": PID, "question_id": "Q1",
                                     "selected": ["B"], "previous": ["A", "B"],
                                     "revision": 3}
    assert changed[-1]["actor"] == "candidate" and changed[-1]["ts"]


def test_no_op_saves_do_not_pad_the_trail():
    model.save_answer(SID, PID, "Q1", ["A"], allowed=ALLOWED)
    model.save_answer(SID, PID, "Q1", ["A"], allowed=ALLOWED)
    assert len(model.answer_trail(SID, PID, "Q1")) == 1


def test_final_answer_is_recorded_and_editing_reopens_it():
    model.save_answer(SID, PID, "Q1", ["A"], allowed=ALLOWED)
    final = model.save_answer(SID, PID, "Q1", ["A", "B"], allowed=ALLOWED, submit=True)
    assert final["final"] is True and final["final_at"]
    submitted_at = final["final_at"]

    # changing their mind afterwards re-opens the question rather than silently
    # replacing what they said was final
    reopened = model.save_answer(SID, PID, "Q1", ["C"], allowed=ALLOWED)
    assert reopened["final"] is False
    assert reopened["final_at"] == submitted_at, "when they committed is still recoverable"

    actions = [t["action"] for t in model.answer_trail(SID, PID, "Q1")]
    assert actions == ["change", "submit", "reopen"]
    assert [e["event"] for e in _events()][-3:] == [
        "mcq_answer_changed", "mcq_answer_submitted", "mcq_answer_reopened"]

    resubmitted = model.save_answer(SID, PID, "Q1", ["C"], allowed=ALLOWED, submit=True)
    assert resubmitted["final"] is True and resubmitted["selected"] == ["C"]
    # timestamps are second-resolution (platform convention), so re-submitting inside the
    # same second leaves final_at equal — `revision` is what orders the trail.
    assert resubmitted["final_at"] >= submitted_at
    assert resubmitted["revision"] == 4
    assert [t["action"] for t in model.answer_trail(SID, PID, "Q1")][-1] == "submit"


def test_overlapping_saves_get_distinct_revisions():
    """Ticking several boxes quickly fires overlapping autosaves. Read-then-write on
    separate connections would hand two of them the same revision number."""
    import threading

    picks = [["A"], ["B"], ["C"], ["A", "B"], ["B", "C"], ["A", "C"]]
    threads = [threading.Thread(target=model.save_answer,
                                args=(SID, PID, "Q1", p),
                                kwargs={"allowed": ALLOWED})
               for p in picks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    revisions = [t["revision"] for t in model.answer_trail(SID, PID, "Q1")]
    assert len(revisions) == len(set(revisions)), f"duplicate revisions: {revisions}"
    assert sorted(revisions) == list(range(1, len(revisions) + 1))


def test_answers_survive_a_refresh():
    """all_answers feeds the page render, so a reload shows what was already chosen."""
    model.save_answer(SID, PID, "Q1", ["B"], allowed=ALLOWED)
    saved = model.all_answers(SID)
    assert saved[(PID, "Q1")]["selected"] == ["B"]


# --- rendering --------------------------------------------------------------
def test_page_renders_saved_state_as_checked_inputs(statement):
    blocks = registry.released_blocks(PID, 1)
    for b in blocks:
        if b["kind"] == "mcq":
            b["answer"] = {"selected": ["B"], "final": False}
    html = views.problems_page({"candidate_name": "A", "workspace_user": "a"},
                               [{"id": PID, "title": "Quiz", "summary": "",
                                 "released": 1, "blocks": blocks}])
    assert 'type="checkbox" value="B" checked' in html
    assert 'type="checkbox" value="A">' in html, "unselected options stay unchecked"
    assert 'data-qid="Q1"' in html and "Submit answer" in html


def test_submitted_question_says_so(statement):
    blocks = registry.released_blocks(PID, 1)
    for b in blocks:
        if b["kind"] == "mcq":
            b["answer"] = {"selected": ["A"], "final": True}
    html = views.problems_page({"candidate_name": "A", "workspace_user": "a"},
                               [{"id": PID, "title": "Quiz", "summary": "",
                                 "released": 1, "blocks": blocks}])
    assert "Submitted" in html
