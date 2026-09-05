# Which parts of the candidate workspace are provisioned data rather than candidate work.
#
# Sourced by snapshot_agent.sh (alpine/git, busybox sh) and export_session.sh (portal
# image, bash) — keep this POSIX sh, no bashisms.
#
# The portal copies each problem's dataset into ~/workspace/data/<problem-id>/ as a
# read-only tree owned by the portal user (integrations._make_readonly). That copy is
# byte-identical to the problem package it came from and can run to tens of megabytes,
# so recording it as if it were candidate work bloats every snapshot commit and every
# export bundle with something already reproducible from problems/.
#
# "Provisioned" is decided by ownership, not by name: ~/workspace itself belongs to the
# candidate, so a directory under data/ owned by anyone else is one the portal put there
# and the candidate cannot write into. Anything the candidate creates stays in the
# record — including files under data/, if they ever delete a provisioned tree and write
# their own in its place, because those are owned by them. The audit stream stays
# unfilterable by its subject, which is the point of `git add -A -f`.

seeded_data_dirs() {  # <workspace-dir> -> workspace-relative paths, one per line
  _ws="${1:-}"
  [ -d "$_ws/data" ] || return 0
  _owner="$(stat -c %u "$_ws" 2>/dev/null || true)"
  # No owner (no stat, or an unreadable workspace) means no exclusions: record everything.
  [ -n "$_owner" ] || return 0
  for _d in "$_ws"/data/*; do
    if [ -d "$_d" ]; then
      _o="$(stat -c %u "$_d" 2>/dev/null || true)"
      if [ -n "$_o" ] && [ "$_o" != "$_owner" ]; then
        echo "data/$(basename "$_d")"
      fi
    fi
  done
  return 0
}
