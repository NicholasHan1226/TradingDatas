#!/bin/bash
# DuckDB merge cron wrapper — syncs SQLite → DuckDB read-model.
#
# Usage:
#   duckdb_merge_cron.sh              # uses env vars or defaults
#   SHAREDSIGNALS_ROOT=/opt/investment/SharedSignals duckdb_merge_cron.sh
#
# Designed to run every 5 minutes from cron:
#   */5 * * * * /opt/investment/SharedSignals/duckdb_merge_cron.sh

set -euo pipefail

# ---- Path resolution ----
SHARED_ROOT="${SHAREDSIGNALS_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
VENV_PYTHON="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
LOG_DIR="${SHARED_ROOT}/logs"
MERGE_LOG="${LOG_DIR}/duckdb_merge_cron.log"
LOCK_FILE="${LOG_DIR}/duckdb_merge.lock"

mkdir -p "$LOG_DIR"

# ---- Prevent overlapping runs ----
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date -Iseconds)] SKIP: previous merge still running" >> "$MERGE_LOG"
    exit 0
fi

# ---- Run ----
cd "$SHARED_ROOT"

START=$(date +%s)
if "$VENV_PYTHON" duckdb_merge.py --json 2>&1; then
    ELAPSED=$(( $(date +%s) - START ))
    echo "[$(date -Iseconds)] OK elapsed=${ELAPSED}s" >> "$MERGE_LOG"
else
    ELAPSED=$(( $(date +%s) - START ))
    echo "[$(date -Iseconds)] FAIL elapsed=${ELAPSED}s" >> "$MERGE_LOG"
    exit 1
fi
