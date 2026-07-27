"""Uploaded AI reviews: matching a file to a session, and what the
printed page must always say."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reviews  # noqa: E402
import views_admin  # noqa: E402

SESSION = {"id": "sess-1", "candidate_name": "Ada Lovelace"}

FILE = """---
session_id: sess-1
candidate: Ada Lovelace
rating: Provisional hire
verdict: Example verdict.
confidence: Medium
model: Example model
generated: 2026-01-17
window: 120 min booked · ~95 min effective
---

## Bottom line

Stopped at the time limit.

| Time | What happened |
|---|---|
| 10:05 | window opens |
"""


def _with_dir(tmp_path, files, monkeypatch):
    d = tmp_path / "reviews"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(reviews, "REVIEWS_DIR", str(d))
    monkeypatch.setattr(reviews, "_REPO_DIR", str(tmp_path / "nope"))
    return d


def test_no_file_means_no_review(tmp_path, monkeypatch):
    _with_dir(tmp_path, {}, monkeypatch)
    assert reviews.exists("sess-1", "Ada Lovelace") is False
    assert reviews.content("sess-1", "Ada Lovelace") is None


def test_matches_on_session_id(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": FILE}, monkeypatch)
    c = reviews.content("sess-1", "Someone Else")
    assert c["rating"] == "Provisional hire"
    assert c["model"] == "Example model"
    assert "<h3>Bottom line</h3>" in c["body_html"]
    assert "<table>" in c["body_html"]


def test_matches_on_candidate_name_when_id_differs(tmp_path, monkeypatch):
    """The fallback that survives a session being re-created after the review was
    written — normalised, so spacing and case in the frontmatter don't matter."""
    _with_dir(tmp_path, {"a.md": FILE.replace("session_id: sess-1", "session_id: old-id")
                                     .replace("candidate: Ada Lovelace", "candidate: ada  LOVELACE")},
              monkeypatch)
    assert reviews.exists("sess-1", "Ada Lovelace")
    assert reviews.content("sess-1", "Ada Lovelace")["rating"] == "Provisional hire"


def test_session_id_match_beats_name_match(tmp_path, monkeypatch):
    """Two files claim the same session: the one naming the id wins, regardless of the
    order the directory lists them in."""
    by_name = FILE.replace("session_id: sess-1", "session_id: other").replace(
        "rating: Provisional hire", "rating: WRONG")
    _with_dir(tmp_path, {"a-by-name.md": by_name, "z-by-id.md": FILE}, monkeypatch)
    assert reviews.content("sess-1", "Ada Lovelace")["rating"] == "Provisional hire"


def test_unrelated_file_is_not_offered(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": FILE}, monkeypatch)
    assert reviews.exists("sess-2", "Grace Hopper") is False


def test_directory_docs_are_not_reviews(tmp_path, monkeypatch):
    """`README.md` documents the upload format for whoever adds the next review — it
    must never be offered as one, however many sessions it would otherwise claim."""
    _with_dir(tmp_path, {"README.md": FILE, "_notes.md": FILE}, monkeypatch)
    assert reviews.all_reviews() == []
    assert reviews.exists("sess-1", "Ada Lovelace") is False


def test_unreadable_directory_is_not_fatal(monkeypatch):
    monkeypatch.setattr(reviews, "REVIEWS_DIR", "/nonexistent/reviews")
    monkeypatch.setattr(reviews, "_REPO_DIR", "/also/nonexistent")
    assert reviews.all_reviews() == []
    assert reviews.exists("sess-1", "Ada Lovelace") is False


def test_missing_frontmatter_still_renders(tmp_path, monkeypatch):
    """A file naming only the candidate still matches and renders — every other slot
    falls back to its default rather than printing a blank or raising."""
    _with_dir(tmp_path, {"a.md": "---\ncandidate: Ada Lovelace\n---\n\nbody text\n"},
              monkeypatch)
    c = reviews.content("sess-1", "Ada Lovelace")
    assert c["model"] == reviews.DEFAULTS["model"]
    assert c["rating"] == ""
    assert "body text" in c["body_html"]


# --- the printed page -------------------------------------------------------
def test_page_always_declares_ai_authorship_and_model(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": FILE}, monkeypatch)
    html = views_admin.session_review(SESSION, reviews.content("sess-1", "Ada Lovelace"))
    assert "AI generated" in html
    assert html.count("Example model") >= 2      # banner + footer
    assert "not a human hiring decision" in html  # running footer, on every printed page
    assert "Provisional hire" in html
    assert "120 min booked" in html               # time context prints beside the verdict


def test_page_escapes_frontmatter(tmp_path, monkeypatch):
    _with_dir(tmp_path, {"a.md": FILE.replace("rating: Provisional hire",
                                              "rating: <script>x</script>")}, monkeypatch)
    html = views_admin.session_review(SESSION, reviews.content("sess-1", "Ada Lovelace"))
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_button_is_disabled_without_a_review():
    off = views_admin._review_button("s1", False)
    on = views_admin._review_button("s1", True)
    assert "disabled" in off and "href" not in off
    assert "disabled" not in on and 'href="/admin/sessions/s1/review"' in on


# --- the shipped files ------------------------------------------------------
def test_repo_reviews_parse_and_are_marked():
    """The reviews actually committed under config/reviews/ load, and every one of them
    names its model and a rating — the two things the executive page must never omit."""
    found = reviews.all_reviews()
    assert found, "no reviews in config/reviews/"
    for r in found:
        meta = r["meta"]
        assert meta.get("model"), f"{r['file']} names no model"
        assert meta.get("rating"), f"{r['file']} states no rating"
        assert meta.get("session_id") or meta.get("candidate"), f"{r['file']} matches nothing"
