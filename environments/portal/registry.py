"""Read the problem registry (problems/registry.yaml) for the admin session-create
form. A tiny tolerant parser — we only need id/title/status per problem and don't want
a YAML dependency (minimal deps). Selectable = status active/draft.
"""
from __future__ import annotations

import os

REGISTRY_PATH = os.environ.get("PROBLEMS_REGISTRY", "/srv/problems/registry.yaml")
SELECTABLE = {"active", "draft"}  # hidden/retired are not offered in the panel


def load_problems(path=None):
    path = path or REGISTRY_PATH
    if not os.path.exists(path):
        return []
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
    out = []
    for p in problems:
        if "id" in p and p.get("status", "draft") in SELECTABLE:
            out.append({"id": p["id"], "title": p.get("title", p["id"]),
                        "status": p.get("status", "draft")})
    return out
