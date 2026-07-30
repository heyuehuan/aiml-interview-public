# Technical Interview Platform

A self-hosted platform for technical interviews of AI/ML candidates. It gives each
interviewee a realistic, sandboxed work environment (terminal + VS Code + Jupyter),
curated technical problems with datasets, managed LLM access through a proxy, and a
full audit trail of what the candidate did — so interviewers can assess real technical
depth, not just a final answer.

## Repository layout

| Directory | Purpose |
|---|---|
| `problems/` | Curated interview problems: manifests (the problem index), statements, datasets/generators, starter code, rubrics, reference solutions, and the packager. |
| `environments/` | The whole running stack: compose file, workspace image (code-server, JupyterLab, ML stack — pinned via `requirements.lock`), and `portal/` — the candidate portal **and** interviewer admin panel (session lifecycle, moderation, audit review). |
| `proxy/` | Managed LLM proxy (unillm) — per-session keys, model allowlist, budget cutoff, full request transcript. |
| `scripts/` | Session export/reset, the shadow.git snapshot agent, deploy. |
| `config/` | Operator-editable content (handout wording, uploaded review reports), mounted read-only into portal/admin. |
| `docs/` | Architecture and the workspace base-image spec. |

## How a session works

One persistent server hosts everything; one candidate at a time, admin working
concurrently. Full lifecycle in `docs/architecture.md`.

1. **Admin** configures a session: problems, candidate display name, duration, LLM
   models/budget, terms text; issues an access code.
2. **Candidate** enters the access code, accepts the terms, and lands on a personalized
   home page with tools: Problems, IDE (OSS Code), Jupyter, Terminal.
3. **Logging** continuously records auditable checkpoints on-host: git snapshots of the
   workspace, shell history, notebook cell executions, and every LLM call via the proxy.
4. **Admin** moderates live (progress view, hints, extend/terminate) and reviews
   afterwards; at close, the session exports one audit artifact bundle.
5. **Reset** wipes the workspace and revokes the session key before the next candidate.

## Status & roadmap

**Deployed** at `https://interview.example.com` (phases 1–4 of the original plan shipped;
phase-5 simulation scenarios remain future work). New work starts from `CLAUDE.md` /
`CONTRIBUTING.md`.

(resolved items summarized at top) and reflected in `docs/architecture.md`.

## Contributing

This is a collaborative repo. Each top-level area has its own README with conventions.
Problems must never leak solutions into candidate-visible paths — see the visibility
rules in `problems/README.md`.
