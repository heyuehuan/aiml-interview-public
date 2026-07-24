---
# Printable candidate handout — Admin → Sessions → a session → "Export PDF handout".
#
# Edit this file to change what the paper says. It is re-read on every request, so a
# save shows up on the next print: no rebuild, no restart. Only the layout lives in
# code (environments/portal/handout.py + views_admin.session_handout).
#
# Frontmatter below fills the fixed slots (heading, box captions, footer). Everything
# after the closing `---` is Markdown:
#   * the text before the first `##` is the welcome paragraph, set slightly larger;
#   * each `##` starts a new section with an underlined header.
#
# Placeholders, substituted after rendering and HTML-escaped:
#   {url}            the candidate-facing URL (from PORTAL_PUBLIC_URL)
#   {access_code}    this session's access code
#   {candidate_name} the candidate's name
#   {terms}          this session's terms text (from the session row, not this file)
#   {icon:NAME}      an inline icon; NAME = problems | gemini | ide | jupyter |
#                    terminal | brand. At the start of a list item it replaces the
#                    bullet.
#
# Keep it to one page — nothing here paginates for you. Anyone who can read this file
# can change what a candidate is told, so treat it as reviewed content, not scratch.

title: Technical Interview Platform
subtitle: Candidate Information Sheet
url_label: Go to
code_label: Access code
copyright: © 2026 Technical Interview Platform
notice: |
  Please CLOSE all pages once the interview concludes,
  and do not take this paper with you.
---

Welcome, and thank you for joining us. Everything you need for today's session runs in
your browser — nothing to set up or download. Please take a moment to read this page
before you start.

## Getting started

1. Open the URL above in any browser.
2. Enter your access code, then read and accept the terms to begin. **Your time starts
   when you accept.**
3. Pick a tool from the home page and start working.
4. Problems appear as your interviewer releases them — press **Refresh** on the Problems
   page to see new ones.
5. Save your work in the IDE or Jupyter as you go, and ask your interviewer if anything
   is unclear.

## What's provided

- {icon:problems} **Problems** — Your tasks for this interview, released by your
  interviewer as you progress.
- {icon:gemini} **Gemini** — Chat playground, **and a Gemini API key that is already
  provided**. Call it from your own code; no key or account of your own is needed.
- {icon:ide} **IDE** — VS Code, in the browser.
- {icon:jupyter} **Jupyter** — JupyterLab notebooks.
- {icon:terminal} **Terminal** — A shell, inside the IDE.

## Terms

{terms}
