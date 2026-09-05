# Deploy runbook

One small host (2 vCPU / 8 GB is enough for one candidate at a time), Docker CE with
the compose plugin, everything co-resident via `docker compose`. The host holds a git
checkout of this repository and tracks `origin/main` (git-pull deploy).

## What's on the host

```
/opt/interview/                       # a git checkout tracking origin/main
└── environments/
    ├── .env                          # host-local secrets (NOT in git)
    ├── secrets/gcp-sa.json           # Vertex AI service-account key (NOT in git)
    └── compose.yaml
```

The deploy user must be in the `docker` group. The stack is driven from
`/opt/interview/environments`.

## First bring-up

```bash
cd /opt/interview/environments
cp .env.example .env          # then set APP_ENV=prod and override EVERY credential
docker compose build          # slow: the workspace image pulls the full DS stack
docker compose up -d
docker compose ps             # all services healthy
```

The stack boots fail-closed: with `APP_ENV=prod` it refuses to start on the public
dev credentials, so `PORTAL_SECRET`, `UNILLM_MASTER_KEY` and an admin credential
(`ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`) must be set in `.env`. `PLATFORM_NAME`
sets the instance name shown to candidates and interviewers.

### Setting `ADMIN_PASSWORD_HASH`

Generate the line with `python environments/portal/hashpw.py 'your-password'` and paste
its whole output into `.env`. It prints every `$` as `$$` on purpose. Compose
interpolates `$` in `.env` values, so a hash pasted raw reaches the container with its
separators eaten; the account seeds with a hash no password matches and the correct
password returns 401. The boot check rejects a malformed hash rather than seeding a dead
account, so you find out at `docker compose up`, not at the login screen.

If a dead admin row was already seeded, fixing `.env` is not enough — `seed_admins()` is
`INSERT OR IGNORE` and leaves the existing row alone. Either set `ADMIN_MASTER_KEY` in
`.env` and log in with it, or, on an instance with no sessions worth keeping, drop the
platform volume for a clean first boot:

```bash
docker compose down && docker volume rm interview-workspace_platform_data
docker compose up -d
```

## Edge / TLS

Caddy binds loopback-only (`127.0.0.1:${PROXY_HTTP_PORT:-8080}:80`) and is not
internet-exposed. Put any TLS-terminating reverse proxy in front of it (nginx, Caddy,
a cloud load balancer) and forward `https://<your-domain>` to `http://127.0.0.1:8080`:

```
browser ──https──▶ your TLS edge ──http──▶ Caddy 127.0.0.1:8080 ──▶ portal / ide / jupyter
```

`auto_https off` in the Caddyfile is deliberate — the edge terminates TLS, not Caddy.
Because the browser leg is HTTPS, keep `COOKIE_SECURE=1` (the default). Set
`PORTAL_PUBLIC_URL` to the URL candidates actually type; it is printed on the handout.

The LLM proxy (unillm) is published on `:8081` loopback-only; candidates reach it from
inside the workspace container via the loopback forwarder, so it is never exposed.

## Deploy (git-pull)

From the dev machine:

```bash
INTERVIEW_HOST=user@your-host INTERVIEW_SSH_KEY=~/.ssh/your-key.pem make deploy
```

`scripts/deploy.sh` SSHes in, fast-forwards the checkout to `origin/<branch>`
(`git reset --hard` touches tracked files only, so the gitignored `.env` and
`secrets/` survive), preflights `.env` for the required variables, and runs
`docker compose up -d --build`. Override the target, key and branch with
`INTERVIEW_HOST`, `INTERVIEW_SSH_KEY` and `INTERVIEW_BRANCH`.

Portal and admin bind-mount the app code (`./portal:/app`), so a pure-Python change can
skip the rebuild with `docker compose restart portal admin` on the host; image or
dependency changes need the `--build` that `make deploy` runs.

## One-time host bootstrap

```bash
sudo mkdir -p /opt/interview && sudo chown "$USER" /opt/interview
git clone <your-fork-url> /opt/interview
cd /opt/interview/environments
cp .env.example .env && $EDITOR .env
mkdir -p secrets && cp /path/to/gcp-sa.json secrets/
docker compose up -d --build
```
