"""The admin Reports section: the two report kinds sharing
`config/reviews/`, the index that aggregates them, and the page a comparison prints.

Per-session review matching and the print furniture are covered by test_reviews.py; this
file covers what the Reports section adds — and the invariant that keeps the two kinds
from contaminating each other.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reviews  # noqa: E402
import views_admin  # noqa: E402

REVIEW = """---
session_id: sess-1
candidate: Ada Lovelace
rating: Provisional hire
model: Example model
generated: 2026-01-10
---

## Bottom line

Stopped at the time limit.
"""

COMPARISON = """---
kind: comparison
sessions: Ada (s1), Grace (s2)
session_ids: sess-1, sess-2
rating: Ada ahead of Grace
verdict: Example comparison verdict.
window: 95 min vs 105 min effective
model: Example model
generated: 2026-01-18
---

## Bottom line

Ada leads on the example axis.
"""

SESSIONS = [
    {"id": "sess-1", "candidate_name": "Ada Lovelace", "state": "exported"},
    {"id": "sess-2", "candidate_name": "Grace Hopper", "state": "closed"},
]


def _with_dir(tmp_path, files, monkeypatch):
    d = tmp_path / "reviews"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(reviews, "REVIEWS_DIR", str(d))
    monkeypatch.setattr(reviews, "_REPO_DIR", str(tmp_path / "nope"))
    return d


# --- kinds ------------------------------------------------------------------
def test_kind_defaults_to_session_and_comparison_is_declared(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    kinds = {r["slug"]: r["kind"] for r in reviews.all_reports()}
    assert kinds == {"a": "session", "c": "comparison"}


def test_kind_is_inferred_when_the_file_names_several_subjects(tmp_path, monkeypatch):
    """An uploader who lists `sessions` but forgets `kind:` gets a comparison anyway —
    filing it as a session review would leave it matching nothing and reachable nowhere."""
    _with_dir(tmp_path, {"c.md": COMPARISON.replace("kind: comparison\n", "")}, monkeypatch)
    assert reviews.all_reports()[0]["kind"] == "comparison"


def test_a_comparison_never_claims_a_session(tmp_path, monkeypatch):
    """The invariant. A comparison names session ids, but the session detail page must not
    offer one as that candidate's AI Review — it is about several people."""
    _with_dir(tmp_path, {"c.md": COMPARISON}, monkeypatch)
    assert reviews.all_reviews() == []
    assert reviews.find("sess-1", "Ada Lovelace") is None
    assert reviews.exists("sess-1", "Ada Lovelace") is False
    assert reviews.content("sess-1", "Ada Lovelace") is None


def test_subjects_fall_back_to_the_ids_when_labels_are_missing(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"c.md": COMPARISON.replace("sessions: Ada (s1), Grace (s2)\n", "")},
              monkeypatch)
    assert reviews.report("c")["subjects"] == ["sess-1", "sess-2"]


# --- slug lookup ------------------------------------------------------------
def test_by_slug_finds_either_kind(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    assert reviews.by_slug("a")["kind"] == "session"
    assert reviews.report("c")["rating"] == "Ada ahead of Grace"


def test_slug_cannot_name_a_path(tmp_path, monkeypatch):
    """`/admin/reports/<slug>` is the only untrusted input in the section. The router
    unquotes path segments, so an encoded traversal arrives decoded — it must die here,
    before anything joins it to a directory."""
    _with_dir(tmp_path, {"a.md": REVIEW}, monkeypatch)
    (tmp_path / "secret.md").write_text(REVIEW, encoding="utf-8")
    for bad in ("../secret", "../../etc/passwd", "/etc/passwd", "a/../a", "a.md",
                "", None, "..", "a" * 129):
        assert reviews.by_slug(bad) is None, bad
        assert reviews.report(bad) is None, bad


def test_directory_docs_are_not_reports(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"README.md": REVIEW, "_draft.md": COMPARISON}, monkeypatch)
    assert reviews.all_reports() == []
    assert reviews.report("README") is None and reviews.report("_draft") is None


# --- the index --------------------------------------------------------------
def test_index_rows_carry_both_kinds_newest_first(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    rows = reviews.index(SESSIONS)
    assert [r["slug"] for r in rows] == ["c", "a"]        # 07-28 before 07-20
    assert [r["kind"] for r in rows] == ["comparison", "session"]
    assert rows[0]["subjects"] == ["Ada (s1)", "Grace (s2)"]
    assert rows[0]["rating"] == "Ada ahead of Grace"
    assert rows[1]["subjects"] == ["Ada Lovelace"]


def test_index_resolves_the_sessions_a_report_covers(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    by_slug = {r["slug"]: r for r in reviews.index(SESSIONS)}
    assert [s["candidate_name"] for s in by_slug["c"]["sessions"]] == [
        "Ada Lovelace", "Grace Hopper"]
    assert by_slug["a"]["sessions"] == [
        {"id": "sess-1", "candidate_name": "Ada Lovelace", "state": "exported"}]
    assert by_slug["a"]["unmatched"] is False


def test_index_keeps_a_report_whose_session_is_gone(tmp_path, monkeypatch):
    """Deleting a session must not silently retire the hiring record it produced: the
    report is listed, marked unmatched, and still opens."""
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    rows = reviews.index([])
    assert len(rows) == 2
    assert all(r["unmatched"] and r["sessions"] == [] for r in rows)
    html = views_admin.reports_page("admin", rows)
    assert "unmatched" in html
    assert '/admin/reports/c' in html and '/admin/reports/a' in html


def test_index_ignores_session_ids_it_does_not_know(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"c.md": COMPARISON}, monkeypatch)
    row = reviews.index([SESSIONS[1]])[0]
    assert [s["id"] for s in row["sessions"]] == ["sess-2"]
    assert row["unmatched"] is False


# --- the index page ---------------------------------------------------------
def test_reports_page_separates_per_session_from_comparisons(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    html = views_admin.reports_page("admin", reviews.index(SESSIONS))
    assert "Per session" in html and "Sessions compared" in html
    assert "Ada (s1), Grace (s2)" in html                  # the comparison reads as its subjects
    assert '<a href="/admin/sessions/sess-2">Grace Hopper</a>' in html
    assert "Reports" in html


def test_reports_page_says_where_a_missing_report_comes_from(tmp_path, monkeypatch):
    """Nothing in the app writes reports, so an empty section must not imply an upload
    form exists — it names the directory instead."""
    _with_dir(tmp_path, {}, monkeypatch)
    html = views_admin.reports_page("admin", reviews.index(SESSIONS))
    assert "No session reviews uploaded yet." in html
    assert "No comparisons uploaded yet." in html
    assert "config/reviews/" in html


def test_each_session_gets_its_own_line(tmp_path, monkeypatch):
    """A comparison covers several sessions. Flowed inline they wrap wherever the column
    ends, which can strand a state label under the wrong candidate."""
    _with_dir(tmp_path, {"c.md": COMPARISON}, monkeypatch)
    html = views_admin.reports_page("admin", reviews.index(SESSIONS))
    assert html.count('<div class="session-link">') == 2   # both subjects of the comparison
    assert ('<div class="session-link"><a href="/admin/sessions/sess-1">Ada Lovelace</a>'
            in html)
    assert "session-link" in views_admin.theme.CSS         # the rule that breaks the line


def test_index_withholds_the_verdict_until_asked(tmp_path, monkeypatch):
    """The verdict text still ships in the HTML — this hides it from the room, not from
    the admin who already has the report open — but no row renders it visibly without a
    click, and each table carries its own Show all."""
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    html = views_admin.reports_page("admin", reviews.index(SESSIONS))
    assert html.count('<td class="reveal">') == 2          # one review + one comparison
    assert '<span class="reveal-text">Provisional hire</span>' in html
    assert '<span class="reveal-text">Ada ahead of Grace</span>' in html
    assert html.count(">Show all</button>") == 2           # per table, not per page
    assert html.count(">Show</button>") == 2               # ...and per row
    assert "reveal-text" in views_admin.theme.CSS          # the rule that hides it


def test_show_all_is_absent_when_no_row_has_a_verdict(tmp_path, monkeypatch):
    """A control that toggles nothing is noise. An empty table gets neither it nor a
    reveal cell."""
    _with_dir(tmp_path, {"a.md": REVIEW.replace("rating: Provisional hire\n", "")},
              monkeypatch)
    html = views_admin.reports_page("admin", reviews.index(SESSIONS))
    assert ">Show all</button>" not in html
    assert '<td class="reveal">' not in html
    assert "No comparisons uploaded yet." in html


def test_reports_is_a_top_level_tab_and_can_be_current():
    assert 'href="/admin/reports"' in views_admin._tabs("sessions")
    assert '<a href="/admin/reports" aria-current="page">' in views_admin._tabs("reports")


# --- back-links from a session ----------------------------------------------
def test_a_session_finds_the_comparisons_it_appears_in(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    assert reviews.comparisons_for("sess-2") == [
        {"slug": "c", "subjects": ["Ada (s1)", "Grace (s2)"]}]
    assert reviews.comparisons_for("sess-3") == []
    assert reviews.comparisons_for("") == []


def test_comparison_matching_is_by_id_not_by_name(tmp_path, monkeypatch):
    """A comparison ranks several candidates, so `candidate`-style name matching would be a
    guess about which one the page belongs to. Only the ids it lists count."""
    _with_dir(tmp_path, {"c.md": COMPARISON.replace("session_ids: sess-1, sess-2\n", "")},
              monkeypatch)
    assert reviews.comparisons_for("sess-1") == []


def test_session_detail_links_its_comparisons(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": REVIEW, "c.md": COMPARISON}, monkeypatch)
    html = views_admin.admin_session_detail(
        "admin", _session_row(), has_review=True,
        comparisons=reviews.comparisons_for("sess-1"))
    assert 'href="/admin/reports/c"' in html
    assert "Ada (s1) vs Grace (s2)" in html
    # ...and a session in no comparison gets no stray control.
    bare = views_admin.admin_session_detail("admin", _session_row(), comparisons=[])
    assert "/admin/reports/" not in bare


def _session_row():
    """The subset of a session row the detail page reads."""
    return {"id": "sess-1", "candidate_name": "Ada Lovelace", "workspace_user": "ada",
            "access_code": "ABCDEF", "problem_ids": ["p1"], "duration_minutes": 90,
            "starts_at": None, "ends_at": None, "llm_budget_usd": 5.0,
            "llm_models": ["gemini-3.5-flash"], "internet_access": True,
            "terms_accepted_at": None, "state": "closed"}


# --- the printed comparison -------------------------------------------------
def test_comparison_page_prints_a_ranking_and_all_its_subjects(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"c.md": COMPARISON}, monkeypatch)
    html = views_admin.report_page(reviews.report("c"))
    assert "Ranking" in html and "Recommendation" not in html
    assert "Ada (s1), Grace (s2)" in html
    assert "<dt>Sessions</dt>" in html and "<dt>Working windows</dt>" in html
    assert "Session comparison" in html                    # kind's default title
    assert '<a href="/admin/reports">← Reports</a>' in html


def test_comparison_page_carries_the_same_disclaimer_furniture(tmp_path, monkeypatch):
    """the banner, the Scope and limits block and the per-page footer are
    kind-independent — a comparison cannot print without them either."""
    _with_dir(tmp_path, {"c.md": COMPARISON}, monkeypatch)
    html = views_admin.report_page(reviews.report("c"))
    assert "AI generated" in html
    assert html.count("Example model") >= 2
    assert "Scope and limits" in html and "For reference only" in html
    assert "did not observe the sessions live" in html     # plural for two sessions
    assert "not a human hiring decision" in html.split('class="runfoot"')[1]
    assert "'Page ' + (p + 1) + ' of ' + built.length" in html


def test_session_review_still_returns_to_its_session(tmp_path, monkeypatch):
    """The per-session entry point is unchanged: same document, but the toolbar goes back
    to the session rather than to the Reports index."""
    _with_dir(tmp_path, {"a.md": REVIEW}, monkeypatch)
    html = views_admin.session_review(
        {"id": "sess-1", "candidate_name": "Ada Lovelace"},
        reviews.content("sess-1", "Ada Lovelace"))
    assert '<a href="/admin/sessions/sess-1">← Back to session</a>' in html
    assert "Recommendation" in html and "did not observe the session live" in html


# --- the shipped files ------------------------------------------------------
def test_repo_comparisons_name_their_subjects_and_their_model():
    """The comparisons committed under config/reviews/ load, and each one says who it
    ranks, which sessions it covers, and which model wrote it."""
    found = reviews.comparisons()
    assert found, "no comparisons in config/reviews/"
    for r in found:
        meta = r["meta"]
        assert meta.get("model"), f"{r['file']} names no model"
        assert meta.get("rating"), f"{r['file']} states no ranking"
        assert len(reviews.subjects(r)) >= 2, f"{r['file']} compares fewer than two sessions"
        assert len(meta.get("session_ids", "").split(",")) >= 2, \
            f"{r['file']} does not name the session ids it covers"
        for heading in ("## Bottom line", "## Recommendation"):
            assert heading in r["body"], f"{r['file']} is missing {heading}"


def test_repo_reports_have_unique_slugs():
    slugs = [r["slug"] for r in reviews.all_reports()]
    assert len(slugs) == len(set(slugs))
