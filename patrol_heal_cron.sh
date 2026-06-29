#!/bin/bash
# SharedSignals patrol + heal cron wrapper
# Runs patrol every cycle; if score drops below threshold, triggers heal.

set -euo pipefail
cd /opt/investment/SharedSignals || exit 1

PATROL_OUTPUT=/tmp/patrol_last.json
HEAL_LOG=logs/heal_cron.log
SCORE_THRESHOLD=60

python3 patrol.py --json --check all 2>&1 | tee "$PATROL_OUTPUT"

# Extract overall_score and decide if heal needed
SCORE=$(python3 -c "
import json, sys
with open('$PATROL_OUTPUT') as f:
    d = json.load(f)
print(d.get('overall_score', 60))
")

echo "[$(date -Iseconds)] patrol_score=$SCORE" >> "$HEAL_LOG"

if [ "$SCORE" -lt "$SCORE_THRESHOLD" ]; then
    echo "[$(date -Iseconds)] score below threshold, triggering heal" >> "$HEAL_LOG"
    python3 heal.py --patrol-result "$PATROL_OUTPUT" >> "$HEAL_LOG" 2>&1
fi
