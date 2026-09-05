# Uploaded AI hiring reports

Two kinds of Markdown file live here:

- **`kind: session`** (the default) — one candidate's hiring review. Drop a file here,
  deploy, and the admin panel picks it up on the next request: that session's
  **AI Review** button goes live (`GET /admin/sessions/<sid>/review`).
- **`kind: comparison`** — a cross-session document ranking several candidates. It claims
  no session, so it is reached from the **Reports** tab rather than from a session.

Both are listed in **Reports** (`/admin/reports`) and both render on the same print-styled
page (`/admin/reports/<slug>`, where the slug is the filename without `.md`) for the
browser's Save as PDF.

Nothing here is generated on the host. Reports are written offline against the captured
session artifacts under `candidate_data/<session>/` and uploaded as the trimmed,
executive-facing version. `README.md` and `_`-prefixed files are ignored by the loader.

**The two `example-*.md` files are placeholders.** They exist so a fresh checkout has
something to render and so the loader's tests have real files to parse. They describe
fictional candidates and sessions; replace them with your own reports (or delete them)
before the platform is used for real hiring.

**Reports are confidential hiring material.** `config/` is mounted read-only on the
portal and admin services only — never into a candidate container — and there is no
portal route that serves them.

## Format

```markdown
---
session_id: 00000000-0000-4000-8000-000000000001
candidate: Alex Example
title: AI hiring review
session_label: Example session · 2026-09-01
rating: Placeholder rating
verdict: >
  One or two sentences. Prints under the rating.
confidence: Low — and why
window: 120 min booked · ~90 min effective
evidence: N workspace snapshots · N-cell notebook · N LLM proxy calls
scope: >
  what this review actually read — and what is absent from the record
model: Example model
generated: 2026-09-01
---

## Bottom line

Body Markdown — headings, paragraphs, lists, tables, bold, code, blockquotes.
```

| Key | Required | Prints as |
|---|---|---|
| `session_id` | one of these two | not shown — matches the file to a session |
| `candidate` | one of these two | page subtitle + facts row; fallback match, case/space insensitive |
| `rating` | yes | the large verdict line |
| `model` | yes | the AI-generated banner **and** the running footer |
| `verdict` | recommended | sentence under the rating |
| `confidence` | recommended | line under the verdict |
| `scope` | recommended | narrows one sentence of the Scope and limits block |
| `window`, `evidence`, `generated`, `session_label` | recommended | the facts block above the body |
| `title`, `copyright` | no | page furniture; sensible defaults |

`session_id` is the preferred match; `candidate` is the fallback that survives a session
being re-created after the review was written. A session review must carry the headings
`## Strengths`, `## Watch-items` and `## Position for the next round`.

A comparison adds `kind: comparison`, names its subjects in `sessions` (display labels,
e.g. `Alex Example (s1), Sam Sample (s2)`) and the ids it covers in `session_ids`, and
must carry `## Bottom line` and `## Recommendation`.
