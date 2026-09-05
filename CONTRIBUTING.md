# Contributing

How work is organised in this repo — for humans and code agents alike.
(Problem authoring specifically: `problems/CONTRIBUTING.md`.)

## Orientation

Read, in order: `README.md` → `docs/architecture.md` → the README of the area you are
changing (`environments/`, `environments/portal/`, `problems/`, `proxy/`).

## Areas

- `environments/` — the compose stack, the workspace image, and `portal/` (candidate
  portal + admin panel). The portal is server-rendered Python with no frontend build.
- `problems/` — problem content and the packager that enforces candidate visibility.
- `proxy/` — the vendored LLM proxy and its local patches.
- `scripts/` — host-side operations (export, reset, snapshot agent, deploy).

Routes, ports, env vars and the session schema are the integration surface between
these areas. Changing one is a documented change (update the area README and
`environments/.env.example` in the same commit), never a silent adaptation.

## Branch & commit conventions

- Branches: `<area>/<short-slug>` (e.g. `portal/access-code-auth`); docs-only changes
  may go straight to `main`.
- Small, frequently-merged changes. Long-lived branches are how integration fails.
- Commit messages: imperative summary line, prefixed with the area (`portal:`,
  `problems:`, `proxy:`, `docs:`) when applicable.

## Definition of done (any slice)

1. Respects every hard rule in `CLAUDE.md` (visibility contract, secrets, append-only
   audit) — these are release-blocking, not advisory.
2. Runs inside the compose stack on 8 GB — "works on my machine" outside compose
   doesn't count.
3. Docs truthful: if you diverged from a doc, update it in the same change.
4. Tests pass:

   ```bash
   python -m pytest environments/portal/tests problems/tests   # stdlib-only
   python -m pytest proxy/tests                                  # needs proxy/requirements_unillm.txt
   ```

## Requirements baseline

- Python 3.12; keep platform-service dependencies minimal; server-rendered HTML over
  frontend builds.
- No secrets in git — `.env` on the host only. Assume every commit is
  candidate-visible someday.
- All logs JSONL append-only, timestamps UTC ISO-8601, `/healthz` on every service.
- Tests where they pay rent fastest: the visibility packager and session state
  machine must have tests; UI polish must not.
