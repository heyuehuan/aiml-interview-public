# Technical Interview Platform

A self-hosted platform for technical interviews of AI/ML candidates. It gives each
interviewee a realistic, sandboxed work environment (terminal + VS Code + Jupyter),
curated technical problems with datasets, managed LLM access through a proxy, and a
full audit trail of what the candidate did — so interviewers can assess real technical
depth, not just a final answer.

This is the open-source edition: the platform code as it runs in a real hiring loop,
shipped with **example content only** — two sample problems, placeholder review
reports, a generic instance name, and no candidate data of any kind.

## Repository layout

| Directory | Purpose |
|---|---|
| `problems/` | Interview problems: manifests (the problem index), statements, datasets/generators, starter code, rubrics, reference solutions, and the packager. Ships two examples. |
| `environments/` | The whole running stack: compose file, workspace image (code-server, JupyterLab, ML stack — pinned via `requirements.lock`), and `portal/` — the candidate portal **and** interviewer admin panel (session lifecycle, moderation, audit review). |
| `proxy/` | Managed LLM proxy (unillm) — model allowlist, budget cutoff, rate limits, full request transcript. |
| `scripts/` | Session export/reset, the shadow.git snapshot agent, deploy. |
| `config/` | Operator-editable content (handout wording, uploaded review reports), mounted read-only into portal/admin. |
| `docs/` | Architecture, the workspace base-image spec, and the deploy runbook. |

## How a session works

One persistent server hosts everything; one candidate at a time, admin working
concurrently. Full lifecycle in `docs/architecture.md`.

1. **Admin** configures a session: problems, candidate display name, duration, LLM
   models/budget, terms text; issues an access code.
2. **Candidate** enters the access code, accepts the terms, and lands on a personalized
   home page with tools: Problems, IDE (OSS Code), Jupyter, Terminal.
3. **Logging** continuously records auditable checkpoints on-host: a git snapshot of the
   whole workspace every 60s, every lifecycle event, and every LLM call via the proxy.
   Notebooks are captured as saved files by the snapshots, not as a live feed of cell
   executions; shell history is not captured at all — both live in `$HOME`, outside the
   snapshotted `~/workspace`. See `docs/architecture.md` for what each stream contains.
4. **Admin** moderates live (progress view, hints, extend/terminate) and reviews
   afterwards; at close, the session exports one audit artifact bundle.
5. **Reset** wipes the workspace and revokes the session key before the next candidate.

## Quick start (local)

```bash
cd environments
cp .env.example .env            # dev profile: public dev credentials, plain HTTP
docker compose up --build       # first build pulls the full DS stack; be patient
```

Open `http://localhost:8080/` for the candidate portal and
`http://localhost:8080/admin` for the admin panel (`admin` / `admin` in the dev
profile). Create a session, pick a problem, and enter the access code in another
browser to walk through the candidate side. LLM access needs a Vertex AI
service-account key at `environments/secrets/gcp-sa.json`; everything else works
without one.

Set `PLATFORM_NAME` in `.env` to put your own name in the header, footer, handout and
report pages. Production deployment: `docs/deploy.md`.

## What ships as examples

- **`problems/ml-txn-anomaly-001`** — a modelling task on a synthetic transaction log
  (seeded generator, planted pitfalls, interviewer rubric). The data is generated at
  package time; nothing is committed.
- **`problems/ml-eval-concepts-001`** — a five-question multiple-choice screen showing
  the MCQ format: option runs render as checkboxes and every selection is recorded.
- **`config/reviews/example-*.md`** — placeholder hiring reports for fictional
  candidates, so the Reports tab has something to render. Replace them.

Add your own problems from `problems/_template/`; the manifests are the index.

## Contributing

Each top-level area has its own README with conventions; `CONTRIBUTING.md` has the
repo-wide rules. Problems must never leak solutions into candidate-visible paths — see
the visibility rules in `problems/README.md`.
