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

One persistent server hosts everything; one candidate at a time, admin working
concurrently. Full lifecycle in `docs/architecture.md`.

1. **Admin** configures a session: problems, candidate display name, duration, LLM
   models/budget, terms text, internet policy; issues an access code.
2. **Candidate** enters the access code, accepts the terms, and lands on a personalized
   home page with tools: Problems, IDE (OSS Code), Jupyter, Terminal.
3. **Logging** continuously records auditable checkpoints on-host: git snapshots of the
   workspace, shell history, notebook cell executions, and every LLM call via the proxy.
4. **Admin** moderates live (progress view, hints, extend/terminate) and reviews
   afterwards; at close, the session exports one audit artifact bundle.
5. **Reset** wipes the workspace and revokes the session key before the next candidate.

## Status & roadmap

- **Phase 1 (now): problems.** Problem format, registry, template, contribution guide.
  Dataset production is deferred and handled separately. See `problems/README.md`.
- **Phase 2: environment.** Workspace image + docker-compose (code-server, JupyterLab)
  sized for small VM, with the between-candidates reset flow.
- **Phase 3: proxy + logging.** unillm proxy over Vertex AI (Gemini), audit streams,
  session export bundle.
- **Phase 4: ui + admin.** Entry flow (access code → terms → home page), session
  management, live moderation.
- **Phase 5: simulation scenarios.** Multi-step, role-realistic simulations (on-call
  triage, model debugging, ambiguous stakeholder asks).

(resolved items summarized at top) and reflected in `docs/architecture.md`.

## Contributing

This is a collaborative repo. Each top-level area has its own README with conventions.
Problems must never leak solutions into candidate-visible paths — see the visibility
rules in `problems/README.md`.
