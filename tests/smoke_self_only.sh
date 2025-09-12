#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PATH="$ROOT/bin:$PATH"

require() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 127; }; }
require tmux

TMPDIR=${TMPDIR:-/tmp}
T=$(mktemp -d "$TMPDIR/agentd-test-XXXXXX")
cleanup() {
  tmux kill-session -t "$SES" >/dev/null 2>&1 || true
  rm -rf "$T"
}
trap cleanup EXIT

SES="agentdtest-$$"
RECV="$T/recv.log"

# Start a tmux session with a CLI window that appends stdin to RECV
tmux new-session -d -s "$SES" -n cli "bash -lc 'umask 000; : > $RECV; exec stdbuf -oL cat >> $RECV'"
sleep 0.2

TARGET="$SES:cli.0"
if ! tmux list-panes -t "$TARGET" >/dev/null 2>&1; then
  echo "failed to create target pane: $TARGET" >&2
  exit 1
fi

# Run a short job that exits with rc=9
CMD="printf '[notify] test begin\\n'; echo 'work...'; sleep 1; printf '[notify] test end\\n'; exit 9"
TOKEN=$(JOB_TARGET_PANE="$TARGET" "$ROOT/bin/job-run" "$CMD")
echo "token=$TOKEN"

# Wait for rc file to appear
RC="$HOME/.agentd/$TOKEN.rc"
for i in {1..60}; do
  [[ -f "$RC" ]] && break
  sleep 0.2
done
if [[ ! -f "$RC" ]]; then
  echo "timeout: rc not written: $RC" >&2
  exit 2
fi

RCV=$(cat "$RC")
echo "rc=$RCV"
[[ "$RCV" == "9" ]] || { echo "unexpected rc: $RCV" >&2; exit 3; }

# Verify log file content
LOG="$HOME/.agentd/logs/$TOKEN.log"
[[ -f "$LOG" ]] || { echo "no log file: $LOG" >&2; exit 4; }
grep -F "work..." "$LOG" >/dev/null || { echo "log missing content" >&2; exit 5; }

# Verify completion notify reached the CLI pane (written to RECV)
for i in {1..60}; do
  if grep -F "[notify] job $TOKEN done rc=9" "$RECV" >/dev/null 2>&1; then break; fi
  sleep 0.2
done
grep -F "[notify] job $TOKEN done rc=9" "$RECV" >/dev/null || {
  echo "notify not received in pane ($RECV):" >&2
  tail -n +1 "$RECV" >&2 || true
  exit 6
}

echo "OK: smoke_self_only passed"
exit 0

