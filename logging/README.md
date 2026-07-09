# Logging & audit

The formal, auditable record of each session. **Local-first**: streams
are written append-only on the platform host during the session and leave the host as
one export bundle at close — no external storage dependency for now.

## Audit streams

| Stream | Mechanism | Granularity |
|---|---|---|
| Workspace snapshots | git auto-commit to a shadow repo the candidate cannot rewrite | 1-minute gated cadence (commit only if changed) + on submit |
| Shell history | shell hook → append-only log | every command, timestamped |
| Notebook executions | Jupyter server extension | each executed cell: code, output, timestamp |
| LLM usage | proxy logs | full prompt/completion per request |
| Session events | platform | code entry, terms acceptance, start/submit/timeout, admin actions (hints, extensions, revocations), reset |

Admin actions are part of the same record — the audit covers the process, not just
the candidate.

## Export bundle

At session close, one archive per session containing all five streams plus the final
submission. This bundle is **the durable output of a session** — the admin downloads /
archives it before reset; reset refuses to run until export has completed.

Keyed by session id / access code only — no candidate PII inside the bundle
(the code→name mapping lives in the admin system).

## Integrity

- Streams are append-only during the session; nothing candidate-reachable can rewrite
  them.
- The shadow git repo hash-chains code states — a formal, ordered record of
  intermediate work.

## Retention

Kept simple: retention window and storage location are host-local
configuration (`.env` or similar), proposed 12 months then purge. Off-host archival
is a later hardening step.
