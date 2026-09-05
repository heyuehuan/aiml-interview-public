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
  (`llm_transcript.jsonl` under `/data/sessions/<session-id>/`) — interviewers see
  exactly how the candidate used AI.
- **Kill switch:** closing or resetting a session clears the control file, which is
  what invalidates the session key — no call to the proxy is needed.

## Why this shape

Candidates demonstrate LLM-application skills against the same API surface they'd use
on the job, while spend stays bounded, models stay controlled, and usage is auditable
per candidate.

## Implementation

**unillm** (vendored under `proxy/unillm/`, from `github.com/heyuehuan/unillm`) — a minimal
OpenAI-compatible FastAPI proxy for Vertex AI Gemini. Runs as the `unillm` compose service.

- **Endpoint:** OpenAI-compatible — `/v1/chat/completions`, `/v1/completions`,
  `/v1/models`, `/health`. Published on the host as `127.0.0.1:8081` only, for
  server-side callers (the admin **Test Gemini** button, the portal playground); it is
  never internet-exposed, in dev or in prod. Candidates call
  `http://localhost:8081/v1` from inside their own container, where the entrypoint runs
  a loopback forwarder to `unillm:8081` on the candidate compose network.
- **Models (`unillm_config.yaml`):** Gemini only, allowlisted by config — `gemini-3.7-flash`,
  `gemini-3.5-flash-lite` (defaults), `gemini-3.1-pro` (opt-in). All use
  `location: global` (Gemini 3.x is global-endpoint only).
- **Auth:** two kinds of key. `UNILLM_MASTER_KEY` stays server-side and is what the
  admin health check and the portal playground use; it never enters the workspace. The
  candidate gets a per-session `sk-cand-…` key, minted at activation and published in
  the control file, injected into the workspace as `OPENAI_API_KEY`/`LLM_API_KEY`.
  `proxy/unillm/proxy/auth.py` re-reads the control file on every request and accepts
  that key only while the file names an active session, so clearing the file at close or
  reset revokes it immediately — including for a candidate who copied it down.
- **Credentials:** Vertex service-account JSON mounted at `GOOGLE_APPLICATION_CREDENTIALS`
  in the unillm container only — gitignored, never candidate-visible.
- **Local patch:** `llm/vertex_ai.py` picks the un-prefixed `aiplatform.googleapis.com`
  host for `location: global`, and the regional `<region>-aiplatform.googleapis.com`
  otherwise. Gemini 3.x is global-endpoint only, so without this every call 404s.

### Run / test locally

```bash
cp environments/.env.example environments/.env   # set UNILLM_MASTER_KEY
# place the Vertex SA JSON at environments/secrets/gcp-sa.json
docker compose -f environments/compose.yaml up -d unillm
curl -H "Authorization: Bearer $UNILLM_MASTER_KEY" http://localhost:8081/v1/models
```

Or use the admin dashboard's **Test Gemini** button.
