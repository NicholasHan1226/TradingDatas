#!/bin/bash
# Sync SharedSignals SQLite read model into DuckDB.
TIMEOUT="${SHAREDSIGNALS_DUCKDB_SYNC_TIMEOUT:-600}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"
if [ "$(id -u)" -eq 0 ] && id -u "${RUN_AS_USER}" >/dev/null 2>&1; then
  exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"
fi
VENV_PYTHON="${VENV_PYTHON:-/opt/marketgraph/venv/bin/python3}"
if [ -n "${SHAREDSIGNALS_VENV_PYTHON:-}" ]; then
  PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON}"
elif [ -x "${VENV_PYTHON}" ]; then
  PYTHON_BIN="${VENV_PYTHON}"
elif [ -x "/opt/marketgraph/venv/bin/python" ]; then
  PYTHON_BIN="/opt/marketgraph/venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
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
  if command -v ionice >/dev/null 2>&1; then
    PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" ionice -c3 nice -n 10 "${PYTHON_BIN}" duckdb_merge.py --json
  else
    PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" nice -n 10 "${PYTHON_BIN}" duckdb_merge.py --json
  fi
  echo "[$(date -Iseconds)] OK duckdb_sync"
} >> "${LOG_FILE}" 2>&1
