# LLM proxy

Managed LLM access for candidates. Implementation: **unillm** (lightweight
LiteLLM-style proxy), running on the platform host.

## Upstream & models

- **Provider:** Google Vertex AI (Gemini). The API key lives only in the proxy's
  host-local config — never visible to the candidate or present in the workspace.
- **Default models:** `gemini-3.7-flash` and `gemini-3.5-flash-lite`.
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

## Implementation

**unillm** (vendored under `proxy/unillm/`, from `github.com/heyuehuan/unillm`) — a minimal
OpenAI-compatible FastAPI proxy for Vertex AI Gemini. Runs as the `unillm` compose service.

- **Endpoint:** published on host `:8081` (candidates call `http://localhost:8081/v1`,
  prod `domain:8081`). OpenAI-compatible: `/v1/chat/completions`, `/v1/completions`,
  `/v1/models`, `/health`.
- **Models (`unillm_config.yaml`):** Gemini only, allowlisted by config — `gemini-3.7-flash`,
  `gemini-3.5-flash-lite` (defaults), `gemini-3.1-pro` (opt-in). All use
  `location: global` (Gemini 3.x is global-endpoint only).
- **Auth:** single shared `UNILLM_MASTER_KEY` (no per-session
  keys). Injected into every workspace as `OPENAI_API_KEY`/`LLM_API_KEY`; shown in admin.
- **Credentials:** Vertex service-account JSON mounted at `GOOGLE_APPLICATION_CREDENTIALS`
  in the unillm container only — gitignored, never candidate-visible.
  endpoint host; KMS handler import made optional (avoids the heavy `vertexai` SDK).

### Run / test locally

```bash
cp environments/.env.example environments/.env   # set UNILLM_MASTER_KEY
# place the Vertex SA JSON at environments/secrets/gcp-sa.json
docker compose -f environments/compose.yaml up -d unillm
curl -H "Authorization: Bearer $UNILLM_MASTER_KEY" http://localhost:8081/v1/models
```

Or use the admin dashboard's **Test Gemini** button.
