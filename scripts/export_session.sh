#!/usr/bin/env bash
# Export a session's audit record.
#
# Runs INSIDE the portal/admin container (python:3.12-slim), invoked by
# integrations.export_session -> `bash /srv/scripts/export_session.sh <session_id>`.
# Bundles every audit stream plus a final copy of the candidate workspace into one
# archive under data/sessions/<sid>/export/. The archive step uses python3 (always
# present in the portal image) so we depend on neither `tar` nor `git` here.
#
# Tolerates a missing llm_transcript.jsonl: the the proxy stream may lag, and a reviewer
# still wants the code + events. Missing streams are recorded in MANIFEST.txt.
set -euo pipefail

SID="${1:?usage: export_session.sh <session_id>}"
DATA_DIR="${DATA_DIR:-/data}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"

SESS_DIR="$DATA_DIR/sessions/$SID"
EXPORT_DIR="$SESS_DIR/export"
[ -d "$SESS_DIR" ] || { echo "[export] no session dir: $SESS_DIR" >&2; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$SID"
mkdir -p "$ROOT"

have=()
miss=()
copy_stream() {  # copy_stream <src-path> <name-in-bundle>
  if [ -e "$1" ]; then
    cp -a "$1" "$ROOT/$2"
    have+=("$2")
  else
    miss+=("$2")
  fi
}

copy_stream "$SESS_DIR/events.jsonl"         events.jsonl
copy_stream "$SESS_DIR/llm_transcript.jsonl" llm_transcript.jsonl
copy_stream "$SESS_DIR/shadow.git"           shadow.git   # bare repo; `git clone` restores history

# Final workspace tree (git history is already in shadow.git; this is the flat "as-left" copy).
if [ -d "$WORKSPACE_DIR" ]; then
  mkdir -p "$ROOT/workspace"
  cp -a "$WORKSPACE_DIR/." "$ROOT/workspace/" 2>/dev/null || true
  have+=("workspace/")
fi

{
  echo "session_id: $SID"
  echo "exported_at: $TS"
  echo "streams_present: ${have[*]:-none}"
  echo "streams_missing: ${miss[*]:-none}"
} > "$ROOT/MANIFEST.txt"

mkdir -p "$EXPORT_DIR"
OUT="$EXPORT_DIR/${SID}_${TS}.tar.gz"
python3 - "$STAGE" "$SID" "$OUT" <<'PY'
import os, sys, tarfile
stage, sid, out = sys.argv[1:4]
with tarfile.open(out, "w:gz") as tar:
    tar.add(os.path.join(stage, sid), arcname=sid)
PY

echo "[export] wrote $OUT (streams: ${have[*]:-none}; missing: ${miss[*]:-none})" >&2
echo "$OUT"
