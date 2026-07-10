#!/usr/bin/env bash
# Workspace entrypoint. Runs as root, waits for the portal to publish an
# active session in /control/active.json, then creates the non-root candidate account,
# hands it the workspace + injected session env, and launches the requested tool AS
# THAT USER (never root). One image, two roles via WORKSPACE_TOOL=code-server|jupyter.
set -euo pipefail

TOOL="${WORKSPACE_TOOL:?set WORKSPACE_TOOL=code-server|jupyter}"
CONTROL="${CONTROL_FILE:-/control/active.json}"
WORKDIR="${WORKSPACE_DIR:-/data/workspace}"
SEED_ROOT="${PROBLEMS_SEED_DIR:-/problems_seed}"

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
SEED_DIR="$(field seed_dir)"
[ -n "$USER_NAME" ] || USER_NAME="candidate"
log "provisioning session $SID as user '$USER_NAME'"

# Non-root account. Home holds tool config; the shared workspace volume is symlinked in.
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$USER_NAME"
fi
HOME_DIR="/home/$USER_NAME"
mkdir -p "$WORKDIR"
ln -sfn "$WORKDIR" "$HOME_DIR/workspace"

# Seed problems (packager output), if present. Only packager-produced content lands
# here — it already enforces the candidate_paths visibility contract.
if [ -n "$SEED_DIR" ] && [ -d "$SEED_DIR" ]; then
  cp -a "$SEED_DIR/." "$WORKDIR/" && log "seeded problems from $SEED_DIR"
elif [ -d "$SEED_ROOT/$SID" ]; then
  cp -a "$SEED_ROOT/$SID/." "$WORKDIR/" && log "seeded problems from $SEED_ROOT/$SID"
fi

chown -R "$USER_NAME:$USER_NAME" "$WORKDIR" "$HOME_DIR"

export HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY"

# make `localhost:8081` reach the unillm proxy from inside this container, so the
# home-page Gemini examples (and the injected LLM_BASE_URL=http://localhost:8081/v1) work
# verbatim. unillm is on the compose network as unillm:8081; forward loopback → there.
# Prod swaps to domain:8081 with no change here. socat runs for the container's lifetime.
UNILLM_UPSTREAM="${UNILLM_UPSTREAM:-unillm:8081}"
if ! pgrep -f "TCP-LISTEN:8081" >/dev/null 2>&1; then
  log "forwarding localhost:8081 -> $UNILLM_UPSTREAM (unillm)"
  socat TCP-LISTEN:8081,fork,reuseaddr,bind=127.0.0.1 "TCP:$UNILLM_UPSTREAM" &
fi

if [ "$TOOL" = "code-server" ]; then
  USER_DATA="$HOME_DIR/.local/share/code-server"
  mkdir -p "$USER_DATA/User"
  [ -f /opt/cs/settings.json ] && cp /opt/cs/settings.json "$USER_DATA/User/settings.json"
  chown -R "$USER_NAME:$USER_NAME" "$HOME_DIR/.local"
  log "launching code-server as $USER_NAME"
  exec gosu "$USER_NAME" env HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY" \
       code-server --auth none --disable-telemetry \
         --user-data-dir "$USER_DATA" --extensions-dir /opt/cs/extensions \
         --bind-addr 0.0.0.0:8443 "$HOME_DIR/workspace"
else
  log "launching JupyterLab as $USER_NAME"
  exec gosu "$USER_NAME" env HOME="$HOME_DIR" SESSION_ID="$SID" \
       LLM_BASE_URL="$LLM_BASE_URL" LLM_API_KEY="$LLM_API_KEY" \
       OPENAI_BASE_URL="$LLM_BASE_URL" OPENAI_API_KEY="$LLM_API_KEY" \
       jupyter lab --ip=0.0.0.0 --port=8888 --no-browser \
         --ServerApp.base_url=/jupyter --ServerApp.token= --ServerApp.password= \
         --ServerApp.allow_origin='*' --ServerApp.disable_check_xsrf=True \
         --ServerApp.root_dir="$HOME_DIR/workspace"
fi
