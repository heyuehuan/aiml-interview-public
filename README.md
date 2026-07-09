# Technical Interview Platform

A self-hosted platform for technical interviews of AI/ML candidates. It gives each
interviewee a realistic, sandboxed work environment (terminal + VS Code + Jupyter),
curated technical problems with datasets, managed LLM access through a proxy, and a
full audit trail of what the candidate did — so interviewers can assess real technical
depth, not just a final answer.

## Repository layout

| Directory | Purpose |
|---|---|
| `problems/` | Curated interview problems: statements, datasets/generators, starter code, rubrics, reference solutions. **Current focus.** |
| `environments/` | Candidate workspace definition: base image, code-server (VS Code OSS), JupyterLab, terminal, preinstalled ML stack. |
| `infra/` | Deployment: IaC, image build, provisioning/teardown of per-candidate instances on AWS. |
| `proxy/` | Managed LLM proxy — provisions scoped LLM access to candidates with per-session keys, budgets, and request logging. |
| `ui/` | Candidate portal: access-code login, problem display, links into the workspace. |
| `admin/` | Interviewer/admin console: manage access codes, choose which problems a session sees, monitor and moderate live sessions. |
| `logging/` | Audit pipeline: workspace snapshots, shell history, Jupyter execution log, LLM usage — the formal auditable record. |
| `docs/` | Architecture, roadmap, and design decisions. |

## How a session works (target design)

1. **Admin** creates an interview session: picks problems, generates a one-time access code, sets time window and LLM budget.
2. **Infra** provisions (or assigns from a warm pool) a workspace instance from the base image, seeded with the selected problems and datasets.
3. **Candidate** enters the access code in the portal and lands in their workspace (VS Code / Jupyter / terminal) with the problem statement.
4. **Logging** continuously records auditable checkpoints: git snapshots of the workspace, shell command history, notebook cell executions, and every LLM call through the proxy.
5. **Admin** reviews the session live or afterwards: final artifacts plus the intermediate record of how the candidate got there.

## Status & roadmap

- **Phase 1 (now): problems.** Problem format, registry, datasets, rubrics, first problem set. See `problems/README.md`.
- **Phase 2: environment.** Base image + docker-compose workspace (code-server, JupyterLab) sized for small VM.
- **Phase 3: proxy + logging.** LiteLLM-based proxy, audit pipeline.
- **Phase 4: ui + admin.** Portal, session management, moderation.
- **Phase 5: simulation scenarios.** Multi-step, role-realistic simulations (on-call triage, model debugging, ambiguous stakeholder asks).

Open design questions and their proposed defaults live in

## Contributing

This is a collaborative repo. Each top-level area has its own README with conventions.
Problems must never leak solutions into candidate-visible paths — see the visibility
rules in `problems/README.md`.
