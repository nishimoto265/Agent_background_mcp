#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PATH="$ROOT/bin:$PATH"

# Ensure default target exists
agentd-bootstrap >/dev/null 2>&1 || true
TARGET=$(cat "$HOME/.agentd/agent_pane")
[[ -n "$TARGET" ]] || { echo "no default target" >&2; exit 2; }

# Run a no-op job that must complete immediately
TOKEN=$(JOB_TARGET_PANE="$TARGET" JOB_WAIT_SEC=5 job-run ":")
echo "token=$TOKEN"

# Wait for rc up to 5s
RC="$HOME/.agentd/$TOKEN.rc"
for i in {1..25}; do [ -f "$RC" ] && break; sleep 0.2; done
if [[ ! -f "$RC" ]]; then echo "rc missing" >&2; exit 3; fi
cat "$RC"

exit 0

