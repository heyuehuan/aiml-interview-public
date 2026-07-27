"""Uploaded AI hiring reviews.

A review is one Markdown file per session, written offline against the captured session
artifact and dropped into `config/reviews/`. That directory rides the existing read-only
`config/` -> `/srv/config` mount, so publishing a review is `git pull` on the host — no
rebuild, no schema, no admin upload form to secure. Files are re-read on every request.

The platform never generates these: it renders what was uploaded, always labelled with
the model that wrote it. Reviews are interviewer/executive material and are mounted only
on the portal and admin services, never in a candidate container.

Matching. A file claims a session by `session_id` (exact) or, failing that, `candidate`
(normalised: case-folded, punctuation and spacing collapsed). The id is preferred; the
name is the fallback that survives a session being re-created after the review was
written. If two files claim the same session, the id match wins, then the filename sorts
first — deterministic rather than clever.

Format::

    ---
    session_id: 00000000-0000-4000-8000-000000000001
    candidate: Alex Example
    rating: Provisional hire
    model: Example model
    generated: 2026-01-17
    ---
    ## Bottom line
    ...

Provenance and scope are not the uploader's to omit: `views_admin.session_review` always
prints the AI-generated banner and the Scope and limits block. The `scope` key only
narrows the sentence naming what was read.
"""
from __future__ import annotations

import os
import re

import frontmatter
import mdrender

# Mounted read-only at /srv/config on portal + admin only.
REVIEWS_DIR = os.environ.get("REVIEWS_DIR", "/srv/config/reviews")
# Fallback for running the app straight from a checkout (tests, `python admin.py`).
_REPO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "reviews")

# Frontmatter slots the page lays out. Everything else in the file is body Markdown.
DEFAULTS = {
    "title": "AI hiring review",
    "candidate": "",
    "session_label": "",
    "rating": "",
    "verdict": "",
    "confidence": "",
    "window": "",
    "evidence": "",
    # What this particular review actually read, as a noun phrase: the layout wraps it in
    # "This analysis read only part of the tracked workspace — {scope}. It did not observe
    # the session live." It can narrow the claim, never remove the block.
    "scope": "its machine-readable contents only — snapshot history, notebooks and "
             "session logs",
    "model": "unspecified model",
    "generated": "",
    "copyright": "© 2026 Technical Interview Platform — confidential hiring material",
}

_NORM = re.compile(r"[^a-z0-9]+")


def _norm(name: str) -> str:
    return _NORM.sub("", (name or "").lower())


def _dirs():
    """Search path, in priority order. The mount wins; the checkout is the dev fallback."""
    seen = []
    for d in (REVIEWS_DIR, _REPO_DIR):
        if d and d not in seen:
            seen.append(d)
    return seen


def _is_review_file(name):
    """`README.md` and `_`-prefixed files are the directory's own documentation, not
    reviews. Everything else ending `.md` is a candidate for matching."""
    return (name.endswith(".md") and not name.startswith(("_", "."))
            and name.lower() != "readme.md")


def _load_dir(path):
    """Parse every review `*.md` in one directory. Unreadable files are skipped, not
    fatal — a half-uploaded review must not take the admin panel down."""
    try:
        names = sorted(n for n in os.listdir(path) if _is_review_file(n))
    except OSError:
        return []
    out = []
    for name in names:
        full = os.path.join(path, name)
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        meta, body = frontmatter.parse(text)
        out.append({"meta": meta, "body": body, "source": full, "file": name})
    return out


def all_reviews():
    """Every uploaded review, first directory wins on a duplicate filename."""
    found, by_name = [], set()
    for d in _dirs():
        for r in _load_dir(d):
            if r["file"] in by_name:
                continue
            by_name.add(r["file"])
            found.append(r)
    return found


def _claims(r, session_id, candidate_name):
    """0 = no match, 2 = matched on session id, 1 = matched on candidate name."""
    meta = r["meta"]
    if session_id and meta.get("session_id", "").strip() == session_id:
        return 2
    if candidate_name and _norm(meta.get("candidate", "")) == _norm(candidate_name):
        return 1
    return 0


def find(session_id, candidate_name=None):
    """The review for one session, or None. Id match beats name match; ties break on
    filename so the same file wins on every request."""
    best, best_rank = None, 0
    for r in all_reviews():
        rank = _claims(r, session_id, candidate_name)
        if rank > best_rank:
            best, best_rank = r, rank
    return best


def exists(session_id, candidate_name=None) -> bool:
    """Whether the AI Review button should be live for this session."""
    return find(session_id, candidate_name) is not None


def content(session_id, candidate_name=None):
    """Everything the review page needs: the frontmatter slots plus `body_html`.
    Returns None when nothing claims this session — the caller renders no page."""
    r = find(session_id, candidate_name)
    if r is None:
        return None
    out = {k: (r["meta"].get(k) or v) for k, v in DEFAULTS.items()}
    out["body_html"] = mdrender.render(r["body"])
    out["source"] = r["source"]
    out["file"] = r["file"]
    # A review with no candidate named in its frontmatter still prints the session's.
    out["candidate"] = out["candidate"] or (candidate_name or "")
    return out
