#!/bin/bash
# SharedSignals patrol + heal cron wrapper.
# Runs patrol every cycle; if score drops below threshold, triggers heal.
#
# Usage:
#   patrol_heal_cron.sh                           # uses env vars or defaults
#   SHAREDSIGNALS_ROOT=/opt/investment/SharedSignals patrol_heal_cron.sh
#
# Env vars:
#   SHAREDSIGNALS_ROOT      — repo root (default: script dir)
#   SHAREDSIGNALS_VENV_PYTHON — python binary (default: python3)
#   PATROL_SCORE_THRESHOLD  — trigger heal below this score (default: 60)

set -euo pipefail

# ---- Path resolution ----
SHARED_ROOT="${SHAREDSIGNALS_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PYTHON="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
LOG_DIR="${SHARED_ROOT}/logs"
HEAL_LOG="${LOG_DIR}/heal_cron.log"
PATROL_OUTPUT="${LOG_DIR}/patrol_last.json"
SCORE_THRESHOLD="${PATROL_SCORE_THRESHOLD:-60}"
LOCK_FILE="${LOG_DIR}/patrol_heal.lock"

mkdir -p "$LOG_DIR"

# ---- Prevent overlapping runs ----
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date -Iseconds)] SKIP: previous patrol still running" >> "$HEAL_LOG"
    exit 0
fi

# ---- Run patrol ----
cd "$SHARED_ROOT"

echo "[$(date -Iseconds)] patrol started" >> "$HEAL_LOG"
"$VENV_PYTHON" patrol.py --json --check all > "$PATROL_OUTPUT" 2>&1

# ---- Extract score and decide ----
SCORE=$("$VENV_PYTHON" -c "
import json, sys
try:
    with open('$PATROL_OUTPUT') as f:
        d = json.load(f)
    print(d.get('overall_score', 60))
except Exception as e:
    print(0)
    sys.stderr.write(f'patrol parse error: {e}\n')
")

echo "[$(date -Iseconds)] patrol_score=$SCORE threshold=$SCORE_THRESHOLD" >> "$HEAL_LOG"

FAIL_COUNT_FILE="${LOG_DIR}/consecutive_failures.txt"
EMERGENCY_LOG="${LOG_DIR}/emergency_alerts.log"

# Read current consecutive failure count
if [ -f "$FAIL_COUNT_FILE" ]; then
    read -r FAIL_COUNT < "$FAIL_COUNT_FILE" || FAIL_COUNT=0
else
    FAIL_COUNT=0
fi

if [ "$SCORE" -lt "$SCORE_THRESHOLD" ]; then
    echo "[$(date -Iseconds)] score below threshold, triggering heal" >> "$HEAL_LOG"
    set +e
    "$VENV_PYTHON" heal.py --patrol-result "$PATROL_OUTPUT" >> "$HEAL_LOG" 2>&1
    HEAL_RC=$?
    set -e
    echo "[$(date -Iseconds)] heal completed rc=$HEAL_RC" >> "$HEAL_LOG"

    if [ "$HEAL_RC" -ne 0 ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"
        if [ "$FAIL_COUNT" -ge 3 ]; then
            echo "[$(date -Iseconds)] [EMERGENCY] consecutive heal failures: $FAIL_COUNT" >> "$EMERGENCY_LOG"
        fi
    else
        FAIL_COUNT=0
        echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"
    fi
else
    echo "[$(date -Iseconds)] score OK, no heal needed" >> "$HEAL_LOG"
    # Also reset failure count when patrol is healthy (score >= threshold)
    FAIL_COUNT=0
    echo "$FAIL_COUNT" > "$FAIL_COUNT_FILE"
fi
