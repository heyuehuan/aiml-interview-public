# LLM proxy

Managed LLM access for candidates. Implementation: **unillm** (lightweight
LiteLLM-style proxy), running on the platform host.

## Upstream & models

- **Provider:** Google Vertex AI (Gemini). The API key lives only in the proxy's
  host-local config — never visible to the candidate or present in the workspace.
- **Default models:** `gemini-3.5-flash` and `gemini-3.1-flash-lite`.
- **Admin-enabled option:** `gemini-3.1-pro` per session when a problem warrants it.
- **Default budget:** $5/session; budget and model list admin-configurable per session.

## Responsibilities

- **Session keys:** each session gets a scoped key with its model allowlist, budget
  cap, and rate limits. Injected into the workspace as standard env vars
  (`OPENAI_BASE_URL`-style + key) so common SDKs work unmodified against the proxy.
- **Isolation:** provider credentials never leave the proxy process/config.
- **Audit:** every request/response logged with session id into the local audit store
  (`logging/`) — interviewers see exactly how the candidate used AI.
- **Kill switch:** admin can revoke the session key mid-interview; reset always
  revokes it.

## Why this shape

Candidates demonstrate LLM-application skills against the same API surface they'd use
on the job, while spend stays bounded, models stay controlled, and usage is auditable
per candidate.

## Open items

- unillm specifics (deployment form, key/virtual-key model, config format) — pending
  details from the owner; this README stays abstract until then.
