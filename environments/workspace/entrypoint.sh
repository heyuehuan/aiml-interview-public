#!/usr/bin/env bash
# Workspace entrypoint. Runs as root, waits for the portal to publish an
# active session in /control/active.json, then creates the non-root candidate account,
# hands it the workspace + injected session env, and launches the requested tool AS
# THAT USER (never root). One image, two roles via WORKSPACE_TOOL=code-server|jupyter.
set -euo pipefail

TOOL="${WORKSPACE_TOOL:?set WORKSPACE_TOOL=code-server|jupyter}"
CONTROL="${CONTROL_FILE:-/control/active.json}"
WORKDIR="${WORKSPACE_DIR:-/data/workspace}"

log() { echo "[workspace:$TOOL] $*" >&2; }

field() {  # field <key> ; reads a string from the control JSON
  python3 - "$CONTROL" "$1" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], "") or "")
except Exception:
    print("")
PY
}

log "waiting for an active session in $CONTROL ..."
while :; do
  if [ -f "$CONTROL" ] && [ "$(field state)" = "active" ] && [ -n "$(field session_id)" ]; then
    break
  fi
  sleep 2
done

SID="$(field session_id)"
USER_NAME="$(field workspace_user)"
LLM_BASE_URL="$(field llm_base_url)"
LLM_API_KEY="$(field llm_api_key)"
# The portal validates workspace_user before it ever reaches the control file, so this
# is a backstop for a control file written by an older portal, not the normal path.
[ -n "$USER_NAME" ] || USER_NAME="candidate"
log "provisioning session $SID as user '$USER_NAME'"

# Non-root account. Home holds tool config; the shared workspace volume is symlinked in.
# An existing login is reused rather than recreated, so refuse a system account outright:
# running the candidate's tools as uid < 1000 (root above all) is the one thing this
# account exists to prevent, and a silent fallback would hide it.
if id "$USER_NAME" >/dev/null 2>&1; then
  EXISTING_UID="$(id -u "$USER_NAME")"
  if [ "$EXISTING_UID" -lt 1000 ]; then
    log "refusing to run the workspace as system account '$USER_NAME' (uid $EXISTING_UID)"
    exit 1
  fi
else
  useradd -m -s /bin/bash "$USER_NAME"
fi
HOME_DIR="/home/$USER_NAME"
mkdir -p "$WORKDIR"
ln -sfn "$WORKDIR" "$HOME_DIR/workspace"

# Problems are NOT copied in here, and the seed volume is NOT mounted in this container.
# The moderator introduces problems one at a time; every path into the workspace is gated
# on the per-problem `released` count (the admin provision/full-push buttons, and the
# candidate's own copy button), all of which run in the portal/admin containers and copy
# from problems_seed there. Mounting the seed here would let a candidate with a terminal
# read every packaged problem — including their own unreleased ones — straight off the
# filesystem, which defeats the gate regardless of what this script copies.
# To hand a candidate everything at once, use the admin full-push button.
log "problems are released by the moderator; no seed is mounted in this container"

# The candidate owns their workspace — except the datasets the platform provisioned,
# which stay root-owned and read-only. This runs on every container start, a restart
# mid-session included, so a blanket `chown -R` here does not just hand the candidate
# write access to the problem's own bytes: ownership is also what keeps those bytes out
# of the audit record (scripts/seeded_data.sh decides by owner), so the next snapshot
# would start committing the whole dataset. Prune the root-owned trees under data/;
# data/ itself is the candidate's, so they can still add their own files beside them.
chown "$USER_NAME:$USER_NAME" "$WORKDIR"
find "$WORKDIR" -mindepth 1 \
     \( -path "$WORKDIR/data/*" -uid 0 -prune \) -o \
     -exec chown -h "$USER_NAME:$USER_NAME" {} +
chown -R "$USER_NAME:$USER_NAME" "$HOME_DIR"

export HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY"

# make `localhost:8081` reach the unillm proxy from inside this container, so the
# home-page Gemini examples (and the injected LLM_BASE_URL=http://localhost:8081/v1) work
# verbatim. unillm is on the compose network as unillm:8081; forward loopback → there.
# Prod is no different: unillm's host port is loopback-only and the candidate never
# leaves this container to reach it. socat runs for the container's lifetime.
UNILLM_UPSTREAM="${UNILLM_UPSTREAM:-unillm:8081}"
if ! pgrep -f "TCP-LISTEN:8081" >/dev/null 2>&1; then
  log "forwarding localhost:8081 -> $UNILLM_UPSTREAM (unillm)"
  socat TCP-LISTEN:8081,fork,reuseaddr,bind=127.0.0.1 "TCP:$UNILLM_UPSTREAM" &
fi

if [ "$TOOL" = "code-server" ]; then
  USER_DATA="$HOME_DIR/.local/share/code-server"
  mkdir -p "$USER_DATA/User"
  [ -f /opt/cs/settings.json ] && cp /opt/cs/settings.json "$USER_DATA/User/settings.json"
  # Always write coder.json so VS Code opens the right folder, not a stale one from
  # a previous session that used a different workspace_user.
  printf '{"query":{"folder":"%s/workspace"}}\n' "$HOME_DIR" > "$USER_DATA/coder.json"
  # Untitled (never-saved) editors exist on disk only as Code-OSS hot-exit backups
  # under the user-data dir — container-local, invisible to the snapshot agent (#2).
  # Point the backup home at the snapshotted workspace volume so those buffers ride
  # shadow.git. Both locations code-server has used across versions are linked; a
  # pre-existing real dir (container restart mid-session) is folded in, not lost.
  BACKUPS_DIR="$WORKDIR/.audit/code-server-backups"
  mkdir -p "$BACKUPS_DIR"
  for d in "$USER_DATA/Backups" "$USER_DATA/User/Backups"; do
    if [ -e "$d" ] && [ ! -L "$d" ]; then
      mv "$d" "$BACKUPS_DIR/migrated-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
    fi
    ln -sfn "$BACKUPS_DIR" "$d"
  done
  chown -R "$USER_NAME:$USER_NAME" "$WORKDIR/.audit"
  chown -R "$USER_NAME:$USER_NAME" "$HOME_DIR/.local"
  log "launching code-server as $USER_NAME"
  gosu "$USER_NAME" env HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY" \
       code-server --auth none --disable-telemetry \
         --user-data-dir "$USER_DATA" --extensions-dir /opt/cs/extensions \
         --bind-addr 0.0.0.0:8443 "$HOME_DIR/workspace" &
else
  log "launching JupyterLab as $USER_NAME"
  # Which origins may drive the candidate's notebook. Auth rests on caddy forward_auth
  # (empty token by design — the session gate lives at the proxy), and xsrf stays
  # disabled because the /jupyter prefix rewrite breaks Jupyter's built-in xsrf cookie
  # check; the origin restriction is what backstops it, so an unrelated site the
  # candidate visits can't drive their notebook. Candidate-attacks-self only — one
  # candidate at a time, no cross-tenant reach.
  #
  # Order: explicit WORKSPACE_ALLOW_ORIGIN, else the origin of PORTAL_PUBLIC_URL, else
  # '*'. Deriving it means a deployment that sets its public URL is restricted without
  # having to know a second variable exists; '*' survives only for local dev, and says
  # so in the log, because a silent '*' in prod is the whole problem.
  ALLOW_ORIGIN="${WORKSPACE_ALLOW_ORIGIN:-}"
  if [ -z "$ALLOW_ORIGIN" ] && [ -n "${PORTAL_PUBLIC_URL:-}" ]; then
    # scheme://host[:port] — strip any path, query or trailing slash.
    ALLOW_ORIGIN="$(printf '%s' "$PORTAL_PUBLIC_URL" | sed -E 's#^([a-zA-Z][a-zA-Z0-9+.-]*://[^/?#]+).*#\1#')"
    log "allow_origin derived from PORTAL_PUBLIC_URL: $ALLOW_ORIGIN"
  fi
  if [ -z "$ALLOW_ORIGIN" ]; then
    ALLOW_ORIGIN="*"
    log "WARNING: allow_origin is '*' — set PORTAL_PUBLIC_URL (or WORKSPACE_ALLOW_ORIGIN) for any non-local deployment"
  fi
  gosu "$USER_NAME" env HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY" \
       jupyter lab --ip=0.0.0.0 --port=8888 --no-browser \
         --ServerApp.base_url=/jupyter --ServerApp.token= --ServerApp.password= \
         --ServerApp.allow_origin="$ALLOW_ORIGIN" --ServerApp.disable_check_xsrf=True \
         --ServerApp.root_dir="$HOME_DIR/workspace" &
fi
TOOL_PID=$!

# Re-provision on session change. The tool is launched ONCE per container start, baking in
# this session's OS user, HOME and SESSION_ID — so when the next candidate is activated we
# must restart, or they inherit the previous candidate's identity and a stale SESSION_ID.
# Exiting is the restart: compose's `restart: unless-stopped` brings the container back and
# this script re-reads the control file from the top.
while :; do
  sleep 5
  if ! kill -0 "$TOOL_PID" 2>/dev/null; then
    log "$TOOL exited; restarting container"
    wait "$TOOL_PID" || true
    exit 1
  fi
  cur_state="$(field state)"
  cur_sid="$(field session_id)"
  if [ "$cur_state" != "active" ] || [ "$cur_sid" != "$SID" ]; then
    log "session changed ($SID -> ${cur_sid:-none}/$cur_state); stopping $TOOL to re-provision"
    kill "$TOOL_PID" 2>/dev/null || true
    wait "$TOOL_PID" 2>/dev/null || true
    exit 0
  fi
done
