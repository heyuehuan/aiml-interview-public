"""Uploaded AI hiring reports.

A report is one Markdown file in `config/reviews/`, written offline against the captured
session artifacts. That directory rides the existing read-only `config/` -> `/srv/config`
mount, so publishing one is `git pull` on the host — no rebuild, no schema, no admin
upload form to secure. Files are re-read on every request.

Two kinds share the directory, declared by `kind:`:

* `session` (the default) — one candidate's hiring review. Claims a session, so the
  session detail page can offer it as **AI Review**.
* `comparison` — a cross-session document ranking several candidates. Claims no single
  session; it names its subjects in `sessions` and the ids it covers in `session_ids`.

The platform never generates either: it renders what was uploaded, always labelled with
the model that wrote it. Reports are interviewer/executive material and are mounted only
on the portal and admin services, never in a candidate container.

Matching (session kind only). A file claims a session by `session_id` (exact) or, failing
that, `candidate` (normalised: case-folded, punctuation and spacing collapsed). The id is
preferred; the name is the fallback that survives a session being re-created after the
review was written. If two files claim the same session, the id match wins, then the
filename sorts first — deterministic rather than clever.

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

...and for a comparison::

    ---
    kind: comparison
    sessions: Alex Example (s1), Sam Sample (s2)
    session_ids: 00000000-0000-4000-8000-000000000001, 00000000-0000-4000-8000-000000000002
    rating: Alex Example ahead of Sam Sample
    model: Example model
    ---

Provenance and scope are not the uploader's to omit, in either kind:
`views_admin.report_page` always prints the AI-generated banner and the Scope and limits
block. The `scope` key only narrows the sentence naming what was read.
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

KIND_SESSION = "session"
KIND_COMPARISON = "comparison"
KINDS = (KIND_SESSION, KIND_COMPARISON)

# Default page title per kind — `title:` in the file overrides it.
_TITLES = {KIND_SESSION: "AI hiring review", KIND_COMPARISON: "Session comparison"}

# Frontmatter slots the page lays out. Everything else in the file is body Markdown.
DEFAULTS = {
    "title": "AI hiring review",
    "candidate": "",
    # Comparison kind: the subjects, as display labels ("Alex Example (s1), Sam Sample (s2)"), and the
    # session ids they correspond to — the index links the ids that still exist.
    "sessions": "",
    "session_ids": "",
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


def _split(value):
    """A comma-separated frontmatter list, empties dropped."""
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _kind(meta):
    """Which kind of report this file is. `kind:` decides; absent that, a file naming
    several subjects is a comparison — filing it as a session review would leave it
    matching nothing and invisible outside the Reports index."""
    declared = (meta.get("kind") or "").strip().lower()
    if declared in KINDS:
        return declared
    if _split(meta.get("sessions")) or _split(meta.get("session_ids")):
        return KIND_COMPARISON
    return KIND_SESSION


def _load_dir(path):
    """Parse every report `*.md` in one directory. Unreadable files are skipped, not
    fatal — a half-uploaded report must not take the admin panel down."""
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
        out.append({"meta": meta, "body": body, "source": full, "file": name,
                    "slug": name[:-3], "kind": _kind(meta)})
    return out


def all_reports():
    """Every uploaded report of either kind, first directory wins on a duplicate
    filename."""
    found, by_name = [], set()
    for d in _dirs():
        for r in _load_dir(d):
            if r["file"] in by_name:
                continue
            by_name.add(r["file"])
            found.append(r)
    return found


def all_reviews():
    """Every uploaded per-session review. Comparisons are excluded: they claim no session,
    so nothing that matches a review to a session should ever see one."""
    return [r for r in all_reports() if r["kind"] == KIND_SESSION]


def comparisons():
    """Every uploaded cross-session comparison."""
    return [r for r in all_reports() if r["kind"] == KIND_COMPARISON]


# A slug is a filename stem and is used to look one up — it must never be able to name a
# path. Rejected here rather than at the route, so every caller is covered.
_SLUG_OK = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def by_slug(slug):
    """The report whose filename stem is `slug`, or None. A slug that could traverse
    (`..`, a separator, anything outside the pattern) matches nothing."""
    if not slug or not _SLUG_OK.fullmatch(slug) or ".." in slug:
        return None
    return next((r for r in all_reports() if r["slug"] == slug), None)


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


def _rendered(r, candidate_name=None):
    """Everything a report page needs: the frontmatter slots plus `body_html`. Shared by
    both kinds — the page furniture (banner, scope, footer) is identical, so the only
    kind-dependent value here is the default title."""
    out = {k: (r["meta"].get(k) or v) for k, v in DEFAULTS.items()}
    out["kind"] = r["kind"]
    out["slug"] = r["slug"]
    out["file"] = r["file"]
    out["source"] = r["source"]
    out["title"] = r["meta"].get("title") or _TITLES[r["kind"]]
    out["subjects"] = subjects(r)
    out["session_ids"] = _split(r["meta"].get("session_ids"))
    out["body_html"] = mdrender.render(r["body"])
    # A review with no candidate named in its frontmatter still prints the session's.
    out["candidate"] = out["candidate"] or (candidate_name or "")
    return out


def content(session_id, candidate_name=None):
    """The rendered review for one session, or None when nothing claims it — the caller
    renders no page."""
    r = find(session_id, candidate_name)
    return None if r is None else _rendered(r, candidate_name)


def report(slug):
    """The rendered report for one slug, either kind, or None."""
    r = by_slug(slug)
    return None if r is None else _rendered(r)


def subjects(r):
    """Who a report is about, as display labels: one candidate for a session review, the
    `sessions` list for a comparison (falling back to the ids it names, so a file that
    forgot the labels still says what it covers)."""
    meta = r["meta"]
    if r["kind"] == KIND_COMPARISON:
        return _split(meta.get("sessions")) or _split(meta.get("session_ids"))
    name = (meta.get("candidate") or "").strip()
    return [name] if name else []


def comparisons_for(session_id):
    """The comparisons that name this session, as `[{slug, subjects}]` — the reverse of the
    index's links, so a session detail page can offer the documents it appears in. Matched
    on id only: a comparison is about several candidates, so a name match would be a guess.
    """
    out = []
    for r in comparisons():
        if session_id and session_id in _split(r["meta"].get("session_ids")):
            out.append({"slug": r["slug"], "subjects": subjects(r)})
    return sorted(out, key=lambda c: c["slug"])


def index(sessions=None):
    """One row per uploaded report for the Reports index, newest `generated` first.

    `sessions` is `model.list_sessions()`; it is used only to resolve each report to the
    live session(s) it covers, so the index can link them and show their state. A report
    whose session is gone is listed as unmatched rather than dropped — deleting a session
    must not silently retire the hiring record it produced."""
    rows = []
    for r in all_reports():
        meta = r["meta"]
        links = _resolve(r, sessions or [])
        rows.append({
            "slug": r["slug"], "file": r["file"], "kind": r["kind"],
            "title": meta.get("title") or _TITLES[r["kind"]],
            "subjects": subjects(r),
            "session_label": meta.get("session_label", ""),
            "rating": meta.get("rating", ""),
            "model": meta.get("model") or DEFAULTS["model"],
            "generated": meta.get("generated", ""),
            "sessions": links,
            "unmatched": not links,
        })
    # Newest first; filename breaks ties so the order is stable across requests, and an
    # undated report sorts last rather than first.
    rows.sort(key=lambda row: (row["generated"] or "", row["file"]), reverse=True)
    return rows


def _resolve(r, sessions):
    """The live sessions a report covers: `[{id, candidate_name, state}]`. A session review
    resolves through the same id-then-name match the detail page uses; a comparison
    resolves each id in `session_ids` (unknown ids are simply not linked)."""
    if r["kind"] == KIND_SESSION:
        best, rank = None, 0
        for s in sessions:
            got = _claims(r, s["id"], s["candidate_name"])
            if got > rank:
                best, rank = s, got
        found = [best] if best else []
    else:
        want = _split(r["meta"].get("session_ids"))
        by_id = {s["id"]: s for s in sessions}
        found = [by_id[i] for i in want if i in by_id]
    return [{"id": s["id"], "candidate_name": s["candidate_name"], "state": s["state"]}
            for s in found]
