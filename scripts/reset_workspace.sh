#!/usr/bin/env bash
# Reset the workspace between sessions.
#
# Runs INSIDE the portal/admin container, invoked by integrations.reset_workspace ->
# `bash /srv/scripts/reset_workspace.sh <session_id>`. Wipes the candidate workspace so
# the next session starts clean.
#
# Refuses unless an export bundle already exists (never destroy un-exported work). The
# shared unillm master key needs no revoke, and the admin handler already cleared the
# control file (workspace tools lock) — so this script's only job is the filesystem wipe
# behind the export guard.
set -euo pipefail

SID="${1:?usage: reset_workspace.sh <session_id>}"
DATA_DIR="${DATA_DIR:-/data}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
EXPORT_DIR="$DATA_DIR/sessions/$SID/export"

# Guard: an export bundle must exist first.
shopt -s nullglob
bundles=("$EXPORT_DIR"/*.tar.gz "$EXPORT_DIR"/*.tgz "$EXPORT_DIR"/*.zip)
if [ ${#bundles[@]} -eq 0 ]; then
  echo "[reset] refusing: no export bundle in $EXPORT_DIR — run export first" >&2
  exit 1
fi

# Wipe workspace contents (dotfiles included) but keep the volume mount point itself.
if [ -d "$WORKSPACE_DIR" ]; then
  find "$WORKSPACE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
fi

echo "[reset] workspace $WORKSPACE_DIR cleared for the next session (export: ${bundles[0]})" >&2
