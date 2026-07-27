"""Content for the printable candidate handout, loaded from `config/handout.md`.

The sheet's layout lives in `views_admin.session_handout`; every word on it lives in
the Markdown file so a wording change is an edit, not a deploy. The file is read on
each request (it is a few KB, and an interviewer editing it mid-day should see the
change on the next print).

Format: an optional `---` frontmatter block of `key: value` lines (`#` comments and
`|` block scalars allowed) filling the fixed slots, then Markdown. Text before the
first `##` is the welcome paragraph; each `##` opens a section.

Session values reach the page as `{url}`, `{access_code}`, `{candidate_name}` and
`{terms}` placeholders, plus `{icon:NAME}` for the home-page icons. They are
substituted *after* Markdown rendering and HTML-escaped there, so nothing a candidate
or an admin typed can inject markup, and a substituted value is never rescanned for
further placeholders.
"""
from __future__ import annotations

import html
import os
import re

import frontmatter
import mdrender
import theme
import views

# Bind-mounted read-only at /srv/config on the portal and admin services only — the
# file names the access-code layout and must never reach a candidate container.
HANDOUT_FILE = os.environ.get("HANDOUT_FILE", "/srv/config/handout.md")
# Fallback for running the app straight from a checkout (tests, `python portal.py`).
_REPO_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "handout.md")

DEFAULTS = {
    "title": "Technical Interview Platform",
    "subtitle": "Candidate information sheet",
    "url_label": "Go to",
    "code_label": "Access code",
    "copyright": "© 2026 Technical Interview Platform",
    "notice": "",
}

# Shared with the candidate home page so paper and screen show the same marks.
ICONS = {
    "problems": views._SVG_PROBLEMS,
    "gemini": theme.GEMINI_MARK,
    "ide": views._SVG_IDE,
    "jupyter": views._SVG_JUPYTER,
    "terminal": views._SVG_TERMINAL,
    "brand": theme.BRAND_MARK,
}

# Shown instead of the sheet's body when the config file is missing or unreadable: the
# three things that make the paper usable at all still print, and the interviewer can
# see why the rest is absent. Deliberately not a second copy of the real content.
_FALLBACK_MD = """\
This sheet's content file (`config/handout.md`) could not be read, so only the
essentials are printed. Tell whoever runs the platform.

## Getting started

Open the URL above in any browser and enter your access code.

## Terms

{terms}
"""

_SECTION = re.compile(r"^##\s", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{(icon:[a-z0-9_]+|url|access_code|candidate_name|terms)\}")
# An icon opening a list item stands in for the bullet (see .content li.ico). The rest of
# the item is wrapped in a <span> so the flex row has exactly two children: icon + text.
# Without the wrapper every <strong> is its own flex item, so `gap` opens a blank beside
# each one and the text runs can no longer wrap as a single paragraph.
_ICON_LI = re.compile(r"<li>\s*(\{icon:[a-z0-9_]+\})\s*(.*?)</li>", re.S)


def _load_file() -> tuple[str, str | None]:
    """Return (text, path). Path is None when no config file could be read."""
    for path in (HANDOUT_FILE, _REPO_FILE):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read(), path
        except OSError:
            continue
    return "", None


def _substitute(rendered: str, values: dict) -> str:
    """Expand placeholders in rendered HTML. Session values are escaped here; icons
    are our own trusted SVG constants. Unknown names collapse to nothing rather than
    printing a stray `{...}` on the paper."""
    def repl(m):
        name = m.group(1)
        if name.startswith("icon:"):
            return ICONS.get(name[5:], "")
        if name == "terms":
            return f'<span class="terms">{html.escape(values.get("terms", ""))}</span>'
        return html.escape(str(values.get(name, "")))

    wrapped = _ICON_LI.sub(r'<li class="ico">\1<span>\2</span></li>', rendered)
    return _PLACEHOLDER.sub(repl, wrapped)


def content(values: dict) -> dict:
    """Everything the handout view needs: the frontmatter slots plus `lead_html` (the
    welcome) and `body_html` (the sections). `values` supplies the placeholders."""
    text, path = _load_file()
    meta, body = frontmatter.parse(text)
    if path is None:
        body = _FALLBACK_MD
        meta = {}

    m = _SECTION.search(body)
    lead_md, sections_md = (body[:m.start()], body[m.start():]) if m else (body, "")

    out = {k: meta.get(k, v) for k, v in DEFAULTS.items()}
    out["lead_html"] = _substitute(mdrender.render(lead_md), values)
    out["body_html"] = _substitute(mdrender.render(sections_md), values)
    out["source"] = path
    return out
