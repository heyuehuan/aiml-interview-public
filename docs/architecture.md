# Architecture

Planning-stage document: shapes and contracts, not implementation.

## Deployment model

**One persistent server** (small VM — 2 vCPU, 8 GB, RHEL8-family OS) hosts the
entire platform. **One candidate at a time**; between candidates the workspace is
reset and the session's artifacts are exported. The **admin console runs concurrently**
on the same host so the interviewer can moderate a live session.

```
┌────────────────────────── single small VM ──────────────────────────┐
│                                                                                   │
│  ┌ Reverse proxy / portal (ui/) ┐        ┌ Admin console (admin/) ┐               │
│  │ access code → terms → home   │        │ sessions · codes ·     │◄── interviewer│
│  │ page (Problems·IDE·Jupyter·  │        │ hints · moderation ·   │    (admin acct)│
│  │ Terminal)                    │        │ audit review           │               │
│  └──────────────┬───────────────┘        └──────────┬─────────────┘               │
│                 │ candidate (access code)           │ controls                    │
│  ┌──────────────▼──────────────────────────────────▼─────────────┐               │
│  │            Workspace (containers, environments/)               │               │
│  │   code-server (OSS Code) · JupyterLab · terminal               │               │
│  │   problems mounted read-only · resettable work volume          │               │
│  └───────┬────────────────────────────────────────┬───────────────┘               │
│          │ LLM calls (session key)                │ audit streams                 │
│  ┌───────▼────────────┐                  ┌────────▼───────────────┐               │
│  │ LLM proxy (proxy/) │──transcripts────►│ Local audit store      │               │
│  │ unillm · provider  │                  │ (logging/): shadow git  │               │
│  │ key never exposed  │                  │ + append-only logs      │               │
│  └───────┬────────────┘                  │ → export bundle at end  │               │
│          │                               └────────────────────────┘               │
└──────────┼────────────────────────────────────────────────────────────────────────┘
           ▼
   Vertex AI (Gemini)   ← only external dependency in steady state
```

## Session lifecycle

```
configure → issue code → candidate entry → live session → close → export → reset
```

1. **Configure (admin):** pick problems for this session, candidate display name,
   duration, model tier & budget, internet policy, terms text (or default).
2. **Entry (candidate):** access code → terms acceptance → personalized home page →
   tools (Problems, IDE, Jupyter, Terminal).
3. **Live (both):** candidate works; audit streams record continuously; admin watches
   progress, delivers hints, extends time, or terminates. All admin actions are part
   of the audit record.
4. **Close:** on submit or timeout. Access code auto-disables 1 hour after session
   end (admin-adjustable); code stays reusable during the session for reconnects.
5. **Export:** one artifact bundle per session — `MANIFEST.txt`, the workspace
   shadow-repo, a copy of the final workspace, `llm_transcript.jsonl` and
   `events.jsonl`. The provisioned problem datasets are left out of both the shadow-repo
   and the workspace copy — they are the problem package's own bytes, re-created by
   packaging the problem, and they otherwise dominate the archive; `MANIFEST.txt` names
   what was omitted. Downloaded / archived by the admin.
6. **Reset:** workspace containers and volumes wiped, session key revoked, host ready
   for the next candidate.

### What the audit streams actually contain

Three streams, all under `data/sessions/<session-id>/` on the host, none of them
reachable from the candidate's containers:

| Stream | Written by | Contents |
|---|---|---|
| `shadow.git` | `scripts/snapshot_agent.sh`, every 60s | a commit per change to `~/workspace`, taken with `git add -A -f` so a candidate-written `.gitignore` cannot filter the record; the provisioned read-only datasets under `data/` are the one exclusion (`scripts/seeded_data.sh`), decided by ownership so anything the candidate writes is still recorded |
| `llm_transcript.jsonl` | unillm, per call | model, messages, response, tokens, cost, latency, and whether the call came from the workspace or the portal's chat page |
| `events.jsonl` | portal + admin | every lifecycle transition and admin action, with `actor` |

The boundary worth knowing: the snapshot agent mounts only `~/workspace`, read-only.
Anything the candidate does that never lands in a file there is not recorded. In
particular **shell history is not captured** (`.bash_history` is in `$HOME`, one level
up), and **there is no cell-execution feed** — a notebook enters the record when it is
saved, so a cell run and never saved leaves no trace beyond its effect on the
filesystem. Capturing either properly needs a sink outside the workspace, since anything
inside it is writable by the person being recorded.

## Design principles

1. **Problems are data, platform is code.** A problem is a self-describing directory
   (manifest + statement + rubric + solution). Adding a problem never requires
   platform changes. Dataset tooling is deferred — the template and
   contribution guide define the contract now.
2. **Candidate-visible vs interviewer-only is enforced by packaging.** Only manifest-
   whitelisted paths reach the workspace; rubrics and solutions never do.
3. **The audit bundle is the durable output of a session.** Local-first (no off-host
   storage dependency for now), append-only during the session, exported at close.
   The shadow git repo hash-chains code states — a formal record of intermediate work.
4. **The workspace is containerized and resettable.** Host OS stays thin; reset is
   "destroy containers + volumes, re-seed", never manual cleanup. Local
   `docker compose up` gives contributors exactly what the candidate sees.
5. **LLM access is provisioned, never shared.** The provider key lives only in the
   proxy; candidates get a session-scoped key with model allowlist and budget.
6. **Live-first, pair-ready.** v1 supports live moderated sessions only;
   nothing in the session model may assume exactly one human in the workspace, so a
   pair session is an additive change later. No take-home mode.
7. **Everything the candidate experiences is admin-configurable with sane defaults:**
   terms text, internet policy (default: open), model tier, budget, code expiry.

## Resource budget (2 vCPU, 8 GB, everything co-resident)

| Component | RAM (steady) |
|---|---|
| Host OS + container runtime + agents | ~0.8 GB |
| Portal + admin console + proxy (all thin services) | ~0.5 GB |
| code-server | ~0.5–0.7 GB |
| JupyterLab server | ~0.3 GB |
| Candidate kernel/workload headroom | ~5 GB |

Single-candidate serialization is what makes this fit. Problems declare
`expected_peak_ram_gb`; verify against ~5 GB headroom.

## Phases

| Phase | Deliverable | Depends on |
|---|---|---|
| 1. Problems | Format, registry, template, contribution guide, seed problems | — |
| 2. Environment | Workspace image + compose; run any problem locally; reset flow | 1 |
| 3. Proxy + logging | unillm + Vertex AI wiring; audit streams + export bundle | 2 |
| 4. UI + admin | Entry flow (code → terms → home), session lifecycle, moderation | 3 |
| 5. Simulation | Multi-stage scenarios (staged triggers, injected events) | 1–4 |

## Extension target: simulation environments

Phase 5 generalizes a problem into a **scenario**: stages with triggers (time-based,
event-based, admin-injected) — e.g. alert-triage with alerts streaming in mid-session,
or a debugging scenario where drift is injected halfway. The manifest reserves a
`stages:` field so today's problems are one-stage scenarios; the admin console's
"deliver hint" action is the primitive that grows into stage injection.
