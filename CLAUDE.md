# CLAUDE.md — agent onboarding

Interview platform for technical AI/ML hiring: one persistent server gives one
candidate at a time a sandboxed workspace (home page → VS Code + Jupyter + terminal),
curated problems, LLM access via a managed proxy, and an auditable record of their
work.

The code runs a real hiring loop; this repository is its open-source edition and ships
example content only. Treat every change as a change to a live platform.

## Read first, in order

1. `README.md` — what the platform is, layout, quick start.
2. `docs/architecture.md` — target architecture and the session lifecycle.
3. The README of the area you are changing: `environments/README.md`,
   `environments/portal/README.md`, `problems/README.md`, `proxy/README.md`.
4. `CONTRIBUTING.md` — conventions and definition of done.

## Hard rules

- **Candidate visibility contract:** only `candidate_paths` from `problem.yaml` may
  ever reach a candidate workspace. Solutions, rubrics, and data generators must never
  be mounted, copied, served, or logged where a candidate can see them.
- **Secrets** (Vertex AI key, admin credentials) live in host-local `.env` only —
  never committed, never injected into the candidate workspace (candidates get the
  proxy's key, nothing else).
- **Generated datasets are never committed** (`problems/*/data/out/` is gitignored).
- **Audit streams are append-only**; nothing candidate-reachable may write to them.
- **No real people in the repo.** Reports under `config/reviews/` are placeholders;
  `candidate_data/` and `reports/` are host-local and gitignored.
- Keep docs truthful: if implementation diverges from a doc, update the doc in the
  same change.

## Environment facts

- Target host: one small VM (2 vCPU / 8 GB), everything co-resident via docker
  compose. Candidate workload headroom ~5 GB — be frugal.
- LLM upstream: Vertex AI Gemini through the **unillm** proxy (`proxy/`); the key is
  never candidate-visible.
- One candidate at a time; sessions end with audit export, then workspace reset.
- Instance name comes from `PLATFORM_NAME` (default "Technical Interview Platform").
