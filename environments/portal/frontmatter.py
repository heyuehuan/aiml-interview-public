"""Shared `--- key: value --- body` parser for the operator-editable Markdown files.

Two documents are authored as Markdown and uploaded rather than deployed: the candidate
handout (`config/handout.md`) and the hiring reviews (`config/reviews/*.md`). Both open
with a small frontmatter block filling fixed slots, so the parsing lives here once.

Deliberately not YAML: no dependency, and the only shapes we accept are `key: value`,
`#` comments, quoted scalars, and `|` / `>` block scalars.
"""
from __future__ import annotations

import re

DELIM = "---"
_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$")


def parse(text: str) -> tuple[dict, str]:
    """Split `--- key: value --- body` into (meta, body). No frontmatter is fine —
    the whole text comes back as the body. Keys are lowercased; unparseable lines are
    skipped rather than raising, so a typo costs one slot, not the document."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != DELIM:
        return {}, text or ""
    meta: dict[str, str] = {}
    i, n = 1, len(lines)
    while i < n and lines[i].strip() != DELIM:
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KEY.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), m.group(2).strip()
        if value in ("|", ">"):  # block scalar: take the indented lines that follow
            fold = value == ">"
            buf = []
            while i < n and lines[i].strip() != DELIM and (
                    not lines[i].strip() or lines[i].startswith((" ", "\t"))):
                buf.append(lines[i].strip())
                i += 1
            value = (" " if fold else "\n").join(buf).strip()
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key] = value
    return meta, "\n".join(lines[i + 1:])
