"""Read the problem registry (problems/registry.yaml) for the admin session-create
form and the candidate problems page. A tiny tolerant parser — we only need
id/title/status per problem and don't want a YAML dependency (minimal
deps).

Admin-controlled visibility: the registry's `status` is the baseline, but an admin can
Show/Hide a problem from the panel. Those overrides persist to
`$DATA_DIR/problem_visibility.json` (writable; the registry file is a read-only mount)
and win over the baseline. Selectable (offered in the create form) = effective status
in {active, draft}.
"""
from __future__ import annotations

import json
import os
import sys

REGISTRY_PATH = os.environ.get("PROBLEMS_REGISTRY", "/srv/problems/registry.yaml")
PROBLEMS_ROOT = os.path.dirname(REGISTRY_PATH)
DATA_DIR = os.environ.get("DATA_DIR", "/data")
VISIBILITY_PATH = os.path.join(DATA_DIR, "problem_visibility.json")
SELECTABLE = {"active", "draft"}  # hidden/retired are not offered in the panel


def _parse_registry(path):
    problems, cur, in_list = [], None, False
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped == "problems:":
                in_list = True
                continue
            if not in_list:
                continue
            # A new top-level key ends the problems block.
            if not line.startswith((" ", "\t")) and stripped.endswith(":"):
                break
            if stripped.startswith("- "):
                if cur:
                    problems.append(cur)
                cur = {}
                stripped = stripped[2:].strip()
            if cur is not None and ":" in stripped:
                key, _, val = stripped.partition(":")
                val = val.split(" #", 1)[0]  # drop inline comments
                cur[key.strip()] = val.strip().strip('"\'')
        if cur:
            problems.append(cur)
    return [p for p in problems if "id" in p]


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


def all_problems(path=None):
    """Every registry problem with its effective (override-applied) status and a
    `visible` flag — for the admin visibility panel."""
    path = path or REGISTRY_PATH
    if not os.path.exists(path):
        return []
    overrides = _load_overrides()
    out = []
    for p in _parse_registry(path):
        eff = _effective_status(p, overrides)
        out.append({"id": p["id"], "title": p.get("title", p["id"]),
                    "status": eff, "base_status": p.get("status", "draft"),
                    "visible": eff in SELECTABLE})
    return out


def load_problems(path=None):
    """Selectable problems for the session-create form (effective status active/draft)."""
    return [{"id": p["id"], "title": p["title"], "status": p["status"]}
            for p in all_problems(path) if p["visible"]]


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
