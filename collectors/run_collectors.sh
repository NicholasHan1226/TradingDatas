#!/bin/bash
# SharedSignals collector orchestration entry point.
# Starts the Orchestrator in continuous loop mode.
#
# Usage:
#   collectors/run_collectors.sh
#   SHAREDSIGNALS_VENV_PYTHON=/path/to/python3 collectors/run_collectors.sh
#
# Env vars:
#   SHAREDSIGNALS_ROOT        - repo root (default: script dir parent)
#   SHAREDSIGNALS_VENV_PYTHON - python binary (default: python3)
#   COLLECTOR_INTERVAL_SEC    - loop interval in seconds (default: 60)

set -euo pipefail

SHARED_ROOT="${SHAREDSIGNALS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_PYTHON="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
INTERVAL="${COLLECTOR_INTERVAL_SEC:-60}"
LOCK_FILE="${SHARED_ROOT}/logs/run_collectors.lock"
LOG_FILE="${SHARED_ROOT}/logs/run_collectors.log"

mkdir -p "${SHARED_ROOT}/logs"

# Prevent overlapping runs
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date -Iseconds)] SKIP: previous collector run still active" >> "$LOG_FILE"
    exit 0
fi

cd "$SHARED_ROOT"

echo "[$(date -Iseconds)] collector orchestrator starting (interval=${INTERVAL}s)" >> "$LOG_FILE"

exec "$VENV_PYTHON" -c "
import sys
sys.path.insert(0, '${SHARED_ROOT}')
from collectors.orchestrator import Orchestrator
o = Orchestrator()
o.run_loop(interval_sec=${INTERVAL})
" >> "$LOG_FILE" 2>&1
