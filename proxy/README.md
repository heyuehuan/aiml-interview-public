# LLM proxy

Managed LLM access for candidates. Planned implementation: **LiteLLM proxy** (one
shared deployment, not per-instance).

## Responsibilities

- **Provisioning:** admin creates a session → proxy issues a session-scoped virtual
  key with model allowlist, USD budget cap, and rate limits. Key is injected into the
  workspace as `OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL` + key env vars, so the standard
  SDKs work unmodified.
- **Isolation:** raw provider credentials (Bedrock IAM / OpenAI / Anthropic keys —
- **Audit:** every request/response logged with session id → shipped to logging/
  as part of the formal record. Interviewers see exactly how the candidate used AI.
- **Kill switch:** admin can revoke a session key mid-interview.

## Why this shape

Candidates should demonstrate LLM-application skills against the same API surface
they'd use on the job, while we keep spend bounded, models controlled, and usage
auditable per candidate.
