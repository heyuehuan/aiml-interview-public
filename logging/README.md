# Logging & audit

The formal, auditable record of each session. Off-instance, append-only, keyed by
session id (access code) — no PII in the streams.

## Audit streams

| Stream | Mechanism | Granularity |
|---|---|---|
| Workspace snapshots | git auto-commit to a shadow repo, pushed off-instance | every 3 min + on save-burst + on submit (code-level diffs, not keystrokes) |
| Shell history | shell hook → log shipper | every command, timestamped |
| Notebook executions | Jupyter server extension | each executed cell: code, output, timestamp |
| LLM usage | proxy logs | full prompt/completion per request |
| Session events | platform | provision, start, pause, submit, teardown, admin actions |

Admin actions (hints injected, extensions granted, kill switch) are part of the same
record — the audit covers the process, not just the candidate.

## Storage

S3 (versioned, write-once lifecycle) + CloudWatch for live tail. Retention per

## Integrity

- Instance role can only append to its own session prefix; nothing on the instance
  can rewrite history.
- The shadow git repo gives cryptographic (hash-chained) ordering of code states —
  suitable as a formal record of intermediate work.
