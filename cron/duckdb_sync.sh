#!/bin/bash
# Sync SharedSignals SQLite read model into DuckDB.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/duckdb_sync.log"
LOCK_FILE="${LOCK_DIR}/duckdb_sync.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP duckdb_sync already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"

if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

{
  echo "[$(date -Iseconds)] START duckdb_sync"
  PYTHONPATH="${ROOT}" "${PYTHON_BIN}" duckdb_merge.py --json
  echo "[$(date -Iseconds)] OK duckdb_sync"
} >> "${LOG_FILE}" 2>&1
