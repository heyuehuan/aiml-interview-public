# Contributing

How collaboration is orchestrated in this repo — for humans and code agents alike.
(Problem authoring specifically: `problems/CONTRIBUTING.md`.)

## Orientation

every other planning doc.

## The workstream model

- **Claim before you build:** set the ws file's `Status:` header to
  `in_progress — <who> — <UTC timestamp>`. One owner per workstream at a time;
  if it's claimed, pick another or coordinate in that file.
- **Contracts before code:** any change to routes, ports, env vars, schemas, or
  Never adapt silently to a contract violation — fix the contract or flag it.
- **Stay in lane:** edit other workstreams' directories only via an agreed contract
  change or an explicit handoff note in their ws file.

## Branch & commit conventions

  go straight to `main`.
- Small, frequently-merged PRs — during the sprint, merge to `main` as soon as your
  ws acceptance criteria for that slice pass; long-lived branches are how a 12-hour
  integration fails.
  applicable.
- Update your ws checklist (with commit hash) in the same push.

## Definition of done (any slice)

1. Meets the acceptance criteria in the ws file (tick them, don't reinterpret them).
2. Respects every hard rule in `CLAUDE.md` (visibility contract, secrets, append-only
   audit) — these are release-blocking, not advisory.
3. Runs inside the compose stack on 8 GB — "works on my machine" outside compose
   doesn't count.
4. Docs truthful: if you diverged from a planning doc, update it in the same PR.
5. ws file status updated; blockers written down, not carried in your head.

## Requirements baseline

- Python 3.12; keep platform-service dependencies minimal; server-rendered HTML over
  frontend builds.
- No secrets in git — `.env` on the host only. Assume every commit is
  candidate-visible someday.
- All logs JSONL append-only, timestamps UTC ISO-8601, `/healthz` on every service.
- Tests where they pay rent fastest: the visibility packager and session state
  machine must have tests; UI polish must not.
