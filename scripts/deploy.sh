#!/usr/bin/env bash
# Deploy the interview platform to the target host by git-pull (no rsync).
#
# The host holds a git checkout at /opt/interview that tracks `main`. This script
# SSHes in, fast-forwards that checkout to origin/main, and rebuilds the stack.
# Host-local, gitignored files (environments/.env, environments/secrets/) are never
# touched by git, so there is nothing here that can wipe secrets — unlike the old
# `rsync --delete`.
#
# One-time host bootstrap (turns the rsync'd tree into a git checkout) is in
# docs/deploy.md. After that, deploying is just: make deploy
#
# Overridable via env: INTERVIEW_HOST, INTERVIEW_SSH_KEY, INTERVIEW_BRANCH.
set -euo pipefail

HOST="${INTERVIEW_HOST:-user@203.0.113.10}"
KEY="${INTERVIEW_SSH_KEY:-$HOME/.ssh/interview-host.pem}"
BRANCH="${INTERVIEW_BRANCH:-main}"
REPO_DIR="/opt/interview"

echo "→ Deploying origin/${BRANCH} to ${HOST}:${REPO_DIR}"

ssh -i "$KEY" "$HOST" 'bash -s' "$BRANCH" "$REPO_DIR" <<'REMOTE'
set -euo pipefail
BRANCH="$1"; REPO_DIR="$2"

cd "$REPO_DIR"
# Fast-forward the checkout. reset --hard only touches tracked files; the gitignored
# environments/.env and environments/secrets/ survive untouched.
git fetch --quiet origin "$BRANCH"
git reset --hard "origin/${BRANCH}"
echo -n "  now at: "; git --no-pager log -1 --oneline

cd environments
# Preflight: the hardened build fails closed — it refuses to boot without these set
# in the host-local .env. Catch that here with a clear message instead of a crash loop.
missing=""
for v in PORTAL_SECRET UNILLM_MASTER_KEY; do
  grep -qE "^${v}=" .env 2>/dev/null || missing="${missing} ${v}"
done
if ! grep -qE "^ADMIN_PASSWORD=.+" .env 2>/dev/null && ! grep -qE "^ADMIN_PASSWORD_HASH=.+" .env 2>/dev/null; then
  missing="${missing} ADMIN_PASSWORD|ADMIN_PASSWORD_HASH"
fi
if [ -n "$missing" ]; then
  echo "✗ environments/.env is missing required var(s):${missing}" >&2
  echo "  The stack boots fail-closed and would crash. See docs/deploy.md." >&2
  exit 1
fi

# The Vertex key must be a readable FILE. Compose is configured not to create the host
# path, so a missing one aborts the `up` — but say so here, where the message can name
# the fix, rather than letting the operator read a mount error.
KEY_FILE="$(sed -n 's/^GCP_SA_KEY_FILE=//p' .env | tail -n1)"
KEY_FILE="${KEY_FILE:-./secrets/gcp-sa.json}"
if [ ! -f "$KEY_FILE" ]; then
  echo "✗ Vertex service-account key not found at environments/${KEY_FILE#./}" >&2
  if [ -d "$KEY_FILE" ]; then
    echo "  It is a DIRECTORY — an earlier 'docker compose up' created it. Remove it" >&2
    echo "  (sudo rmdir) and copy the real key into place." >&2
  fi
  echo "  Copy the key there, or point GCP_SA_KEY_FILE at it. See docs/deploy.md." >&2
  exit 1
fi

docker compose up -d --build
docker compose ps
REMOTE

echo "✓ Deploy complete."
