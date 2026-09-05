#!/bin/sh
# Snapshot agent: commits the workspace to shadow.git every 60 s.
#
# Runs as its own compose service (alpine/git) so the git dependency stays out of the
# portal image. Every $SNAPSHOT_INTERVAL seconds, if a session is active per the control
# file, commit any changes in the candidate workspace into that session's shadow.git.
#
# The workspace is mounted READ-ONLY here (git reads the work-tree, writes objects only
# into data/sessions/<id>/shadow.git). The agent has no candidate-reachable surface, and
# the candidate has no path to data/sessions/ — audit stays append-only and out of reach.
set -eu

DATA_DIR="${DATA_DIR:-/data}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
CONTROL_FILE="${CONTROL_FILE:-/control/active.json}"
INTERVAL="${SNAPSHOT_INTERVAL:-60}"

# seeded_data_dirs(): the provisioned read-only datasets, which are not candidate work.
. "$(dirname "$0")/seeded_data.sh"

export GIT_AUTHOR_NAME="snapshot-agent"    GIT_AUTHOR_EMAIL="snapshot@interview.local"
export GIT_COMMITTER_NAME="snapshot-agent" GIT_COMMITTER_EMAIL="snapshot@interview.local"
# Workspace is owned by the candidate uid; git runs as root here — trust it explicitly.
git config --global --add safe.directory '*' 2>/dev/null || true

log() { echo "[snapshot] $*" >&2; }

# Extract a top-level string value from the control JSON (written by the portal with indent=2,
# so each key sits on its own line) without needing jq.
json_str() {
  sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONTROL_FILE" 2>/dev/null | head -n1
}

log "watching $CONTROL_FILE (interval ${INTERVAL}s)"
while true; do
  if [ -f "$CONTROL_FILE" ]; then
    state="$(json_str state)"
    sid="$(json_str session_id)"
    # sid comes from the control file, but validate it
    # anyway before building shadow.git paths — a malformed value is skipped, not run.
    case "$sid" in
      *[!A-Za-z0-9_-]*) log "skipping malformed session id: $sid"; sid="";;
    esac
    if [ "$state" = "active" ] && [ -n "$sid" ] && [ -d "$WORKSPACE_DIR" ]; then
      shadow="$DATA_DIR/sessions/$sid/shadow.git"
      if [ ! -d "$shadow" ]; then
        mkdir -p "$shadow"
        git --git-dir="$shadow" init -q --bare
        log "initialized $shadow"
      fi
      # Bare repo + explicit work-tree (the "dotfiles" pattern): add/commit operate on the
      # workspace while history lands cleanly in shadow.git with no nested checkout.
      export GIT_DIR="$shadow" GIT_WORK_TREE="$WORKSPACE_DIR"
      # -f: the workspace is candidate-writable, so a plain add would honor a
      # candidate-written .gitignore — an audit stream the subject can filter (#2).
      # The provisioned datasets are excluded (see seeded_data.sh): they are the portal's
      # own copies of problem data, so committing them adds tens of megabytes of already
      # reproducible bytes to shadow.git and to every export bundle taken from it.
      # ':/' and ':(top,...)' are relative to the work tree, so this works from any cwd.
      set -- ':/'
      while IFS= read -r rel; do
        if [ -n "$rel" ]; then
          set -- "$@" ":(top,exclude)$rel"
        fi
      done <<EOF
$(seeded_data_dirs "$WORKSPACE_DIR")
EOF
      git add -A -f -- "$@" 2>/dev/null || true
      if ! git diff --cached --quiet 2>/dev/null; then
        if git commit -q -m "snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>/dev/null; then
          log "committed workspace snapshot for $sid"
        fi
      fi
      unset GIT_DIR GIT_WORK_TREE
    fi
  fi
  sleep "$INTERVAL"
done
