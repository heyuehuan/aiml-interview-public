# Environments

The candidate workspace: what the interviewee actually sees and uses, plus the reverse
proxy that fronts it.

## What's here

- `compose.yaml` — the stack: `caddy` (reverse proxy), `code-server`, `jupyterlab`,
  `portal` (:8000) + `admin` (:8001). Shared `workspace` volume; the `control` volume
  carries the live session to the tools. `problems_seed` is mounted into portal/admin
  only — never into the candidate-reachable `code-server`/`jupyterlab`, where a shell
  could read unreleased problems off it. Only the proxy publishes a host port.
- `Dockerfile.workspace` — python 3.12 + trimmed tier-1 ML stack + code-server +
  JupyterLab (one image, run as two services). Launched by `workspace/entrypoint.sh`
  as a non-root per-session user. Package list: `../docs/base-image-spec.md`.
- `requirements.workspace.txt` — the trimmed tier-1 pin list (unpinned for the sprint).
- `Caddyfile` — routing + the `/api/authz` auth subrequest for `/ide` and `/jupyter`.
- `portal/` — portal session service + admin panel (see `portal/README.md`).
- `workspace/entrypoint.sh` — provisions the non-root candidate user from the portal
  control file and launches the requested tool as that user.

## Run it locally

Prerequisite: **Docker Desktop running** (it provides the daemon + the `docker compose`
plugin). Then:

```
cd environments
cp .env.example .env          # optional; sets the local proxy port (default 8080)
docker compose up --build     # first build pulls the ML stack + code-server (~minutes)
```

Open **http://localhost:8080** → home page. Tiles go to:

| Route | Service |
|---|---|
| `/` | candidate portal: access code → terms → home |
| `/admin/` | admin panel (create/activate/close/export/reset sessions) |
| `/ide/` | VS Code (code-server), integrated terminal inside |
| `/jupyter/` | JupyterLab, same `~/workspace` |

`/ide` and `/jupyter` stay locked until an admin activates a session and the candidate
accepts the terms (the tools are provisioned + launched as the session's non-root user).

Health: `curl http://localhost:8080/healthz` and each service's own `/healthz`.
Stop with `docker compose down`; add `-v` to also wipe the workspace volume.

## Routing notes

- `/ide` is prefix-stripped (code-server serves relative assets); `/jupyter` is passed
  through with `base_url=/jupyter`.
- `/ide` and `/jupyter` are gated by a `forward_auth` subrequest to `/api/authz`. The
  portal stub always allows; the portal makes it enforce real session auth.
- Nothing but `caddy` is host-exposed — every other service is internal-network only.

## Session service

`portal/` is the real session service on `:8000` (routes `/`, `/api/*` incl. a real
`/api/authz`) + the admin panel on `:8001` (`/admin/*`). It owns `platform.db`, drives
the `created→active→closed→exported→reset` lifecycle, and publishes the live session to
the tool containers via `data/control/active.json`, which `workspace/entrypoint.sh`
consumes to provision the non-root user. See `portal/README.md`. Set `PORTAL_SECRET` +
`ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.env` (defaults `admin`/`admin` for local dev).

## Workspace layout as the candidate sees it

```
~/workspace/           # shared by code-server and JupyterLab
├── PROBLEMS.md         # packager writes this
├── <problem-id>/       # PROBLEM.md, data/, starter/
└── (their work)
```

the packager is the only thing that copies problem content, and only `candidate_paths`.
