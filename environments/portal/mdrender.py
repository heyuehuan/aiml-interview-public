"""A tiny, dependency-free Markdown -> HTML renderer for the candidate problems page.

The moderated problems page renders each problem's statement *inline* (so the full
`problem.md` never has to land in the candidate workspace). We only need to handle the
constructs our own problem statements use: headings, paragraphs, ordered/unordered
lists, tables, fenced + inline code, bold/italic, links + autolinks, horizontal rules,
and blockquotes. It is intentionally small and forgiving rather than CommonMark-complete.

Everything is HTML-escaped; the only markup emitted is the tags this module produces,
and link hrefs are scheme-allowlisted (http/https/mailto, or scheme-less relative) —
so rendering untrusted-but-authored problem text can't inject script, including via
`javascript:` link URLs.
"""
from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_ULI = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OLI = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$")

# private-use placeholders so inline tokens survive escaping/emphasis unscathed
_L, _R = "", ""


def render(md: str) -> str:
    """Render a Markdown string to an HTML fragment (no <html>/<body> wrapper)."""
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        # fenced code block
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)[0]
            buf = []
            i += 1
            while i < n and not (lines[i].lstrip().startswith(fence * 3)):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence (or EOF)
            out.append('<pre class="code"><code>' + html.escape("\n".join(buf)) + "</code></pre>")
            continue

        if not line.strip():
            i += 1
            continue

        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            # demote one level so problem headings sit under the page's own <h1>
            lvl = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # table: a header row followed by a |---|---| separator
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            i = _table(lines, i, out)
            continue

        if line.lstrip().startswith(">"):
            i = _blockquote(lines, i, out)
            continue

        if _ULI.match(line) or _OLI.match(line):
            i = _list(lines, i, out)
            continue

        # paragraph: gather until a blank line or a block-level starter
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines, i):
            buf.append(lines[i])
            i += 1
        out.append("<p>" + _inline(" ".join(s.strip() for s in buf)) + "</p>")
    return "\n".join(out)


def inline(text: str) -> str:
    """Render a single line of Markdown to an inline HTML fragment (no block tags).

    For callers that own the surrounding markup — e.g. the multiple-choice options on
    the problems page, which become `<label>`s rather than `<li>`s."""
    return _inline(text or "")


def _is_block_start(lines, i) -> bool:
    line = lines[i]
    return bool(
        _HEADING.match(line) or _HR.match(line) or _FENCE.match(line)
        or _ULI.match(line) or _OLI.match(line) or line.lstrip().startswith(">")
        or ("|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]))
    )


def _split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _table(lines, i, out) -> int:
    header = _split_row(lines[i])
    i += 2  # header + separator
    body = []
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        body.append(_split_row(lines[i]))
        i += 1
    head_html = "".join(f"<th>{_inline(c)}</th>" for c in header)
    rows_html = ""
    for r in body:
        cells = (r + [""] * len(header))[: len(header)]
        rows_html += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>"
    out.append(f"<table><thead><tr>{head_html}</tr></thead><tbody>{rows_html}</tbody></table>")
    return i


def _blockquote(lines, i, out) -> int:
    buf = []
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        buf.append(lines[i].lstrip()[1:].lstrip())
        i += 1
    out.append("<blockquote>" + render("\n".join(buf)) + "</blockquote>")
    return i


def _list(lines, i, out) -> int:
    ordered = bool(_OLI.match(lines[i]))
    items: list[str] = []
    n = len(lines)
    while i < n:
        m = _OLI.match(lines[i]) if ordered else _ULI.match(lines[i])
        if not m:
            # a differently-typed list item ends this list
            if _OLI.match(lines[i]) or _ULI.match(lines[i]) or not lines[i].strip():
                break
            # indented continuation line of the current item
            if items and (lines[i].startswith((" ", "\t"))):
                items[-1] += " " + lines[i].strip()
                i += 1
                continue
            break
        items.append(m.group(3) if ordered else m.group(2))
        i += 1
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>" + "".join(f"<li>{_inline(it.strip())}</li>" for it in items) + f"</{tag}>")
    return i


# --- inline ----------------------------------------------------------------
_SAFE_SCHEME = re.compile(r"^(?:https?|mailto):", re.IGNORECASE)


def _safe_href(url: str) -> bool:
    """Allow http(s)/mailto absolute URLs and scheme-less relative/fragment URLs;
    refuse anything else (javascript:, data:, vbscript:, ...)."""
    if _SAFE_SCHEME.match(url):
        return True
    head = re.split(r"[/?#]", url, maxsplit=1)[0]
    return ":" not in head


def _inline(text: str) -> str:
    tokens: list[str] = []

    def stash(htmlfrag: str) -> str:
        tokens.append(htmlfrag)
        return f"{_L}{len(tokens) - 1}{_R}"

    # 1. backslash escapes -> literal char, hidden from later passes
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", lambda m: stash(html.escape(m.group(1))), text)
    # 2. inline code spans
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text)
    # 3. autolinks <http...>
    text = re.sub(r"<((?:https?|mailto):[^>\s]+)>",
                  lambda m: stash(f'<a href="{html.escape(m.group(1))}" target="_blank" rel="noopener">{html.escape(m.group(1))}</a>'),
                  text)
    # 4. [text](url) links — unsafe schemes render as literal text, not a link
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash(
                      f'<a href="{html.escape(m.group(2))}" target="_blank" rel="noopener">{html.escape(m.group(1))}</a>'
                      if _safe_href(m.group(2)) else html.escape(m.group(0))),
                  text)
    # 5. escape everything else
    text = html.escape(text)
    # 6. emphasis (bold before italic; underscore italics only at word boundaries so
    #    snake_case identifiers survive)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(?=\S)(.+?)(?<=\S)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w])_(?=\S)(.+?)(?<=\S)_(?![\w])", r"<em>\1</em>", text)
    # 7. restore stashed tokens
    return re.sub(f"{_L}(\\d+){_R}", lambda m: tokens[int(m.group(1))], text)
