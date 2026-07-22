# Portal + admin

The candidate portal and admin panel that replace the original `portal-stub`. Stdlib-only
Python (no pip deps, no image build — runs on plain `python:3.12-slim`), server-rendered
HTML. Two processes from one codebase:

| Process | Port | Routes | Auth |
|---|---|---|---|
| `portal.py` | 8000 | `/`, `/api/*` (incl. `/api/authz`) | candidate access code → cookie |
| `admin.py`  | 8001 | `/admin/*` | admin account → cookie |

## Candidate flow

`access code → terms → home → tools`. The 6-letter code (case-insensitive, stored
uppercase) resolves to an **active** session inside its window; the code auto-disables
`ends_at + 60min`. Terms acceptance is timestamped, **starts the countdown** (sets
`starts_at`/`ends_at` on first acceptance — not at activation, so pre-provisioning time
isn't charged to the candidate), and gates the workspace: `/api/authz` (the proxy's
`forward_auth` subrequest for `/ide` and `/jupyter`) returns **204** only for an active,
terms-accepted, in-window session, else **401**.

## Admin lifecycle

Create → **activate** (writes the control file + issues the LLM key + packages problems)
→ extend / close → export → reset, mapped onto the `created→active→closed→exported→reset`
state machine. A **closed** session can be **reactivated** (`closed→active`) so a
candidate can resume: it re-provisions like activation, preserves the remaining time when
≥30 min are left, and otherwise prompts the admin for a fresh total (≥30 min). Every
transition appends to `data/sessions/<id>/events.jsonl`. Admin accounts live in the
`admins` table, seeded from `.env` on first boot.

## Admin review surfaces

From a session's detail page:

- **Workspace files** (`/admin/sessions/<id>/files`) — browse, view, and manage the live
  candidate `workspace` volume: navigate folders, read a file's current contents, remove
  a file/dir, and provision or reset a problem's seeded `data/`. Every candidate-supplied
  path is confined to `WORKSPACE_DIR` by realpath (traversal + symlink guard); mutations
  emit `workspace_file_deleted` / `workspace_data_provisioned` / `workspace_data_reset`
  events. Gated to the single live workspace (the active session, or a not-yet-reset
  closed/exported one when nothing else is live). Never surfaces solutions/rubrics — it
  reads the candidate's own files and provisions only seeded `data/`.
- **LLM transcript** (`/admin/sessions/<id>/transcript`) — near-real-time reader of
  `llm_transcript.jsonl` (Refresh re-reads the file), with a **source** filter
  (Direct API call / UI playground / Admin test) and a substring search over
  prompt/response. Source is the proxy's tamper-proof attribution.

## The non-root workspace

The admin sets a **`workspace_user`** (non-root OS login) per session. On activation the
service publishes `data/control/active.json`; the workspace containers'
`workspace/entrypoint.sh` watches it, creates that Linux user, hands it the workspace +
injected session env (`LLM_*`, `OPENAI_*`, `SESSION_ID`), and launches code-server /
JupyterLab **as that user** via `gosu`. No session active ⇒ tools stay locked. The
portal never touches the docker socket.

## Files

| File | Role |
|---|---|
| `server.py` | tiny router / request / response / cookie plumbing |
| `db.py` | sqlite schema + connection (`platform.db`) |
| `model.py` | code gen, PBKDF2 passwords, signed cookies, state machine, events |
| `integrations.py` | control file + packager / proxy keys / export-reset (best-effort) |
| `registry.py` | reads `problems/registry.yaml` for the create form |
| `views.py` | server-rendered HTML |
| `portal.py` / `admin.py` | the two service entrypoints |
| `hashpw.py` | `python hashpw.py <pw>` → `ADMIN_PASSWORD_HASH` |
| `tests/test_model.py` | state machine + access-code tests (`pytest`) |

## Run / test locally

Normally via `environments/compose.yaml` (`docker compose up --build`). Standalone:

```
cd environments/portal
PORT=8000 PLATFORM_DB=/tmp/p.db DATA_DIR=/tmp/d CONTROL_FILE=/tmp/c/active.json \
  ADMIN_USERNAME=admin ADMIN_PASSWORD=admin PORTAL_SECRET=dev python portal.py
python -m pytest tests/            # state machine + code tests
```

## Config (env)

`PORTAL_SECRET` (cookie signing), `ADMIN_USERNAME` + `ADMIN_PASSWORD` or
`ADMIN_PASSWORD_HASH`, `PLATFORM_DB`, `DATA_DIR`, `CONTROL_FILE`, `PROBLEMS_SEED_DIR`,
`PROBLEMS_REGISTRY`, `LLM_ADMIN_URL`, `LLM_BASE_URL`, `CODE_GRACE_MINUTES` (default 60).
Secrets stay in host `.env` — never committed, never in the workspace (CLAUDE.md).
