# Environments

The candidate workspace: what the interviewee actually sees and uses, plus the reverse
proxy that fronts it.

## What's here

- `compose.yaml` — the stack: `caddy` (reverse proxy), `code-server`, `jupyterlab`,
  `portal-stub`. One shared `workspace` volume; only the proxy publishes a host port.
- `Dockerfile.workspace` — python 3.12 + trimmed tier-1 ML stack + code-server +
  JupyterLab (one image, run as two services). Package list:
  `../infra/images/base-image-spec.md` (torch/tf/spaCy deferred for build speed).
- `requirements.workspace.txt` — the trimmed tier-1 pin list (unpinned for the sprint).
- `Caddyfile` — routing + the `/api/authz` auth subrequest for `/ide` and `/jupyter`.
- `portal-stub/` — the portal stand-in: serves the home page and returns 204 for `/api/authz`.
- `homepage/` — the static home page shell (Problems / Code Editor / Jupyter / Terminal).

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
| `/` | home page shell |
| `/ide/` | VS Code (code-server), integrated terminal inside |
| `/jupyter/` | JupyterLab, same `~/workspace` |

Health: `curl http://localhost:8080/healthz` and each service's own `/healthz`.
Stop with `docker compose down`; add `-v` to also wipe the workspace volume.

## Routing notes

- `/ide` is prefix-stripped (code-server serves relative assets); `/jupyter` is passed
  through with `base_url=/jupyter`.
- `/ide` and `/jupyter` are gated by a `forward_auth` subrequest to `/api/authz`. The
  portal stub always allows; the portal makes it enforce real session auth.
- Nothing but `caddy` is host-exposed — every other service is internal-network only.

## Handoff to the portal

the portal replaces `portal-stub` with the real session service on `:8000` (routes `/`,
`/api/*`, including a real `/api/authz`). The home page template in `homepage/` is the
agreed starting point for the portal's session-aware version. No proxy/route change needed —
the contract addresses (`portal-stub:8000` → the portal service) stay the same.

## Workspace layout as the candidate sees it

```
~/workspace/           # shared by code-server and JupyterLab
├── PROBLEMS.md         # packager writes this
├── <problem-id>/       # PROBLEM.md, data/, starter/
└── (their work)
```

the packager is the only thing that copies problem content, and only `candidate_paths`.
