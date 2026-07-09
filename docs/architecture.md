# Architecture

## Components

```
                        ┌─────────────────────────────────────────────┐
                        │              Admin console (admin/)          │
                        │  access codes · problem visibility ·         │
                        │  session moderation · audit review           │
                        └───────────────┬─────────────────────────────┘
                                        │ session config
┌──────────────┐   access code  ┌───────▼───────────┐
│  Candidate   ├───────────────►│  Portal (ui/)     │
└──────┬───────┘                └───────┬───────────┘
       │                                │ provisions / routes
       │        ┌───────────────────────▼──────────────────────────┐
       │        │        Workspace instance (small VM)        │
       └───────►│  ┌─────────────┐ ┌────────────┐ ┌─────────────┐  │
                │  │ code-server │ │ JupyterLab │ │  terminal   │  │
                │  └─────────────┘ └────────────┘ └─────────────┘  │
                │  problems mounted read-only · workspace volume    │
                └──────┬──────────────────────────────┬─────────────┘
                       │ LLM calls                    │ audit streams
                ┌──────▼───────────┐          ┌───────▼─────────────┐
                │ LLM proxy        │          │ Logging (logging/)  │
                │ (proxy/, LiteLLM)│──logs───►│ S3 / CloudWatch     │
                │ per-session keys │          │ git snapshots ·     │
                │ budgets · audit  │          │ shell · notebook ·  │
                └──────┬───────────┘          │ LLM transcripts     │
                       │                      └─────────────────────┘
                ┌──────▼───────────┐
                │ Upstream LLMs    │
                │ Bedrock / OpenAI │
                │ / Anthropic      │
                └──────────────────┘
```

## Design principles

1. **Problems are data, platform is code.** A problem is a self-describing directory
   (manifest + statement + dataset generator + rubric + solution). The platform
   consumes the manifest; adding a problem never requires platform changes.
2. **Candidate-visible vs interviewer-only is enforced by packaging, not discipline.**
   The provisioner copies only whitelisted paths (`problem.md`, `starter/`, generated
   `data/`) into the workspace. `solution/`, `rubric.md`, and generator internals never
   reach the instance.
3. **Audit is off-instance and append-only.** Everything auditable (git snapshots,
   shell history, notebook executions, LLM transcripts) ships to S3/CloudWatch as it
   happens. Nothing on the instance is the system of record.
4. **The workspace is containerized.** Host OS runs Docker + an agent; the actual
   candidate environment is an image (`environments/`). This makes the host OS choice
   low-stakes, images testable in CI, and local development of problems trivial
   (`docker compose up` gives you exactly what the candidate sees).
5. **LLM access is provisioned, never shared.** Candidates get a per-session virtual
   key from the proxy with a model allowlist and budget. Raw provider keys exist only
   in the proxy.
6. **Sessions are cattle.** Instance is provisioned for a session, seeded, used,
   archived, destroyed. No state survives on the instance.

## Resource budget (small VM: 2 vCPU, 8 GB)

| Component | RAM (steady) |
|---|---|
| Host OS + Docker + agents | ~0.8 GB |
| code-server | ~0.4–0.7 GB |
| JupyterLab server | ~0.3 GB |
| Candidate kernel/workload headroom | ~5–6 GB |

One candidate per instance. Training a small torch model or a scikit-learn pipeline on
a ≤100 MB dataset fits with room to spare; problems must be sized to this budget
(problem manifests declare expected peak RAM).

## Phases

| Phase | Deliverable | Depends on |
|---|---|---|
| 1. Problems | Format, registry, 2 polished problems with datasets & rubrics | — |
| 2. Environment | Base image + compose file; run any problem locally | 1 |
| 3. Proxy + logging | LiteLLM deployment, audit streams to S3 | 2 |
| 4. UI + admin | Portal, access codes, session lifecycle, moderation | 3 |
| 5. Simulation | Multi-stage scenarios (on-call triage, model debugging, evolving requirements) | 1–4 |

## Extension target: simulation environments

Phase 5 generalizes a "problem" into a **scenario**: a sequence of stages with
triggers (time-based, event-based, or admin-injected). Examples: an alert-triage
simulation where new alerts stream in mid-session; a model-debugging scenario where
the interviewer injects a data drift halfway through. The problem manifest schema
already reserves a `stages:` field so today's single-stage problems are just
one-stage scenarios.
