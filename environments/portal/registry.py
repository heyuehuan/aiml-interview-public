"""Read the problem index for the admin session-create form and the candidate
problems page. The index IS the manifests: `registry.yaml` was collapsed into them — we scan `$PROBLEMS_ROOT/*/problem.yaml` for id/title/status
with a tiny tolerant parser.

Admin-controlled visibility: each manifest's `status` is the baseline, but an admin
can Show/Hide a problem from the panel. Those overrides persist to
`$DATA_DIR/problem_visibility.json` (writable; the problems mount is read-only) and
win over the baseline. Selectable (offered in the create form) = effective status
in {active, draft}.
"""
from __future__ import annotations

import json
import os
import re
import sys

import mdrender

# PROBLEMS_ROOT is the contract now; PROBLEMS_REGISTRY (a file path inside
# that root) is honoured for back-compat with pre-collapse deployments and tests.
_REGISTRY_COMPAT = os.environ.get("PROBLEMS_REGISTRY")
PROBLEMS_ROOT = os.environ.get("PROBLEMS_ROOT") or (
    os.path.dirname(_REGISTRY_COMPAT) if _REGISTRY_COMPAT else "/srv/problems")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
VISIBILITY_PATH = os.path.join(DATA_DIR, "problem_visibility.json")
SELECTABLE = {"active", "draft"}  # hidden/retired are not offered in the panel

# The manifest scanner below and the packager's problem.yaml parser share how they
# de-comment/unquote a scalar. Reuse the packager's helper so the two agree; the
# packager is a sibling package whose mount may not be importable at load time, so fall
# back to a local copy rather than hard-depending on it.
try:
    sys.path.insert(0, os.path.dirname(PROBLEMS_ROOT))
    from problems.package import clean_scalar as _clean_scalar
except Exception:  # pragma: no cover - packager not importable in this layout
    def _clean_scalar(val):
        return val.split(" #", 1)[0].strip().strip("\"'")


def _manifest_head(path):
    """Top-level `id`/`title`/`status` scalars from one problem.yaml. Indented lines
    (nested blocks, folded summaries, list items) can't be top-level keys and are
    skipped wholesale, so this stays correct however the rest of the file grows."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line[:1] in (" ", "\t") or line.startswith("#"):
                continue
            key, sep, val = line.partition(":")
            if sep and key.strip() in ("id", "title", "status"):
                out[key.strip()] = _clean_scalar(val)
    return out


def _scan_manifests(root):
    """Every `<root>/<dir>/problem.yaml`, sorted by directory name for a stable form
    order. `_template/` (underscore) and non-problem dirs are skipped; an unreadable
    manifest skips that problem rather than taking the panel down."""
    problems = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    for name in names:
        if name.startswith(("_", ".")):
            continue
        path = os.path.join(root, name, "problem.yaml")
        if not os.path.isfile(path):
            continue
        try:
            head = _manifest_head(path)
        except OSError:  # pragma: no cover - unreadable mount entry
            continue
        if head.get("id"):
            problems.append(head)
    return problems


# --- admin visibility overrides ---------------------------------------------
def _load_overrides():
    try:
        with open(VISIBILITY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_visibility(problem_id, visible):
    """Admin Show/Hide: map a problem to 'active' (visible/selectable) or 'hidden'."""
    overrides = _load_overrides()
    overrides[problem_id] = "active" if visible else "hidden"
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = VISIBILITY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(overrides, fh, indent=2)
    os.replace(tmp, VISIBILITY_PATH)


def _effective_status(p, overrides):
    return overrides.get(p["id"], p.get("status", "draft"))


def all_problems(root=None):
    """Every problem (from the manifests) with its effective (override-applied)
    status and a `visible` flag — for the admin visibility panel."""
    overrides = _load_overrides()
    out = []
    for p in _scan_manifests(root or PROBLEMS_ROOT):
        eff = _effective_status(p, overrides)
        out.append({"id": p["id"], "title": p.get("title", p["id"]),
                    "status": eff, "base_status": p.get("status", "draft"),
                    "visible": eff in SELECTABLE})
    return out


def load_problems(root=None):
    """Selectable problems for the session-create form (effective status active/draft)."""
    return [{"id": p["id"], "title": p["title"], "status": p["status"]}
            for p in all_problems(root) if p["visible"]]


# --- per-problem metadata (title + summary) for the candidate page ----------
def _parse_manifest(problem_id):
    try:
        sys.path.insert(0, os.path.dirname(PROBLEMS_ROOT))  # so `problems.package` imports
        from problems.package import parse_manifest  # reuse the packager's reader
        return parse_manifest(os.path.join(PROBLEMS_ROOT, problem_id, "problem.yaml"))
    except Exception:
        return {"id": problem_id, "title": problem_id, "summary": ""}


def problem_meta(problem_ids):
    """Title + one-paragraph summary for each assigned problem (candidate page)."""
    by_id = {p["id"]: p for p in all_problems()}
    out = []
    for pid in problem_ids:
        man = _parse_manifest(pid)
        title = (by_id.get(pid) or {}).get("title") or man.get("title") or pid
        out.append({"id": pid, "title": title, "summary": man.get("summary", "")})
    return out


# --- moderated problem statement (split into background + subproblems) -------
# A subproblem starts at a heading whose text begins Qn / Task n / Part n (the
# convention all our statements follow). Everything before the first such heading is
# the always-shown "background". The moderated candidate page reveals the background
# plus the first N subproblems, where N is set per session by the admin.
_SUBPROBLEM_RE = re.compile(r"^(#{1,6})\s+((?:Q|Task\s*|Part\s*)\d+)\b", re.IGNORECASE)


def read_problem_md(problem_id):
    """Read a problem's candidate-facing statement. Reads ONLY ``problem.md`` — never
    ``solution/`` or ``rubric.md`` — so it can't leak interviewer material (visibility
    contract). Returns "" if the file is absent."""
    path = os.path.join(PROBLEMS_ROOT, problem_id, "problem.md")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split_subproblems(md):
    """Split statement Markdown into ``(background, subproblems)``.

    ``subproblems`` is a list of ``{"title", "body"}`` in document order. If the
    statement has no Qn headings the whole document is the background and the list is
    empty (a single-part problem). The leading top-level ``# Title`` line is dropped
    from the background — the page already shows the title separately."""
    lines = md.splitlines()
    heads = [i for i, ln in enumerate(lines) if _SUBPROBLEM_RE.match(ln)]
    if not heads:
        bg = md.strip()
    else:
        bg = "\n".join(lines[: heads[0]]).strip()
    bg_lines = bg.splitlines()
    if bg_lines and bg_lines[0].lstrip().startswith("# "):
        bg = "\n".join(bg_lines[1:]).strip()
    subs = []
    for j, start in enumerate(heads):
        end = heads[j + 1] if j + 1 < len(heads) else len(lines)
        title = lines[start].lstrip("#").strip()
        subs.append({"title": title, "body": "\n".join(lines[start:end]).strip()})
    return bg, subs


def part_meta(problem_id):
    """Moderation metadata for a problem: subproblem count + titles. ``total`` is the
    number of releasable steps (>=1; a single-part problem counts as 1)."""
    bg, subs = split_subproblems(read_problem_md(problem_id))
    return {"total": max(1, len(subs)), "subs": subs, "has_background": bool(bg.strip())}


# --- multiple-choice questions -------------------
# Conceptual MCQ screens used to leave no record at all — the candidate read the options
# and answered out loud. We detect option runs structurally so the answers can be
# captured, without adding a problem.yaml field or rewriting any statement.
#
# An option bullet is `- **A.** text` / `- A) text`. A *run* qualifies as a question only
# when it has >=2 items whose keys are exactly A, B, C, ... in order — that guard makes a
# false positive on ordinary prose bullets essentially impossible.
_MCQ_OPTION_RE = re.compile(r"^\s*[-*+]\s+(?:\*\*|__)?([A-Z])[.)](?:\*\*|__)?\s+(\S.*)$")
_QID_RE = re.compile(r"[^A-Za-z0-9]+")


def _qid(title):
    """Question key from a subproblem heading: 'Q1. What does…' -> 'Q1'."""
    m = _SUBPROBLEM_RE.match("# " + title)
    token = m.group(2) if m else title
    return _QID_RE.sub("", token).upper() or "Q"


def _next_key(opts):
    return chr(ord("A") + len(opts))


def _mcq_runs(body):
    """Find option runs in a subproblem body.

    Returns ``[(start, end, [(key, text), ...]), ...]`` with line indices into
    ``body.splitlines()``, in document order. Most real options wrap onto indented
    continuation lines and some statements space their options out with blank lines, so
    both have to hold a run together — otherwise a four-option question is read as one
    option and dropped."""
    lines = body.splitlines()
    runs, i, n = [], 0, len(lines)
    while i < n:
        m = _MCQ_OPTION_RE.match(lines[i])
        if not m or m.group(1) != "A":  # a run always starts at A
            i += 1
            continue
        start, opts, j = i, [], i
        while j < n:
            m = _MCQ_OPTION_RE.match(lines[j])
            if m:
                # keys must run A, B, C, ... — anything else is an ordinary bullet list
                if m.group(1) != _next_key(opts):
                    break
                opts.append([m.group(1), m.group(2).strip()])
                j += 1
                continue
            if opts and lines[j].strip() and lines[j][:1] in (" ", "\t"):
                opts[-1][1] += " " + lines[j].strip()  # wrapped continuation line
                j += 1
                continue
            if opts and not lines[j].strip():  # blank line between options (loose list)
                k = j
                while k < n and not lines[k].strip():
                    k += 1
                nxt = _MCQ_OPTION_RE.match(lines[k]) if k < n else None
                if nxt and nxt.group(1) == _next_key(opts):
                    j = k
                    continue
            break
        if len(opts) >= 2:
            runs.append((start, j, [(k, t) for k, t in opts]))
            i = j
        else:
            i = start + 1
    return runs


def released_blocks(problem_id, released):
    """The candidate-visible slice of a statement, as ordered blocks.

    Each block is either ``{"kind": "md", "html": ...}`` or
    ``{"kind": "mcq", "qid": "Q1", "options": [{"key", "html"}, ...]}``. The caller turns
    mcq blocks into real inputs (candidate page) or a static list (plain render).
    Returns ``[]`` when nothing is released yet."""
    if released < 1:
        return []
    bg, subs = split_subproblems(read_problem_md(problem_id))
    blocks = []

    def add_md(text):
        if text and text.strip():
            blocks.append({"kind": "md", "html": mdrender.render(text)})

    add_md(bg)
    for sub in (subs[:released] if subs else []):
        body = sub["body"]
        runs = _mcq_runs(body)
        if not runs:
            add_md(body)
            continue
        lines = body.splitlines()
        base, cursor = _qid(sub["title"]), 0
        for idx, (start, end, opts) in enumerate(runs):
            add_md("\n".join(lines[cursor:start]))
            qid = base if idx == 0 else f"{base}-{idx + 1}"
            blocks.append({"kind": "mcq", "qid": qid,
                           "options": [{"key": k, "html": mdrender.inline(t)} for k, t in opts]})
            cursor = end
        add_md("\n".join(lines[cursor:]))
    return blocks


def question_ids(problem_id, released):
    """``{question_id: [option keys]}`` for every MCQ question currently released —
    the portal's allowlist when a candidate posts an answer."""
    return {b["qid"]: [o["key"] for o in b["options"]]
            for b in released_blocks(problem_id, released) if b["kind"] == "mcq"}


def all_question_ids(problem_id):
    """Every MCQ question in the whole statement (admin answer sheet), with the
    subproblem title it belongs to and its option text."""
    _, subs = split_subproblems(read_problem_md(problem_id))
    out = []
    for sub in subs or []:
        base = _qid(sub["title"])
        for idx, (_s, _e, opts) in enumerate(_mcq_runs(sub["body"])):
            out.append({"qid": base if idx == 0 else f"{base}-{idx + 1}",
                        "title": sub["title"],
                        "options": [{"key": k, "text": t} for k, t in opts]})
    return out


def render_released(problem_id, released):
    """Render the candidate-visible slice of a statement as one HTML fragment, with
    option runs as a static list. Returns None when nothing is released yet."""
    if released < 1:
        return None
    parts = []
    for b in released_blocks(problem_id, released):
        if b["kind"] == "md":
            parts.append(b["html"])
        else:
            parts.append("<ul>" + "".join(
                f'<li><strong>{o["key"]}.</strong> {o["html"]}</li>' for o in b["options"]
            ) + "</ul>")
    return "\n".join(parts)
