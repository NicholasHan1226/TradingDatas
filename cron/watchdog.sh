#!/bin/bash
# Run SharedSignals watchdog every 5 minutes from cron.
TIMEOUT="${SHAREDSIGNALS_WATCHDOG_TIMEOUT:-300}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/marketgraph/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/watchdog.log"
LOCK_FILE="${LOCK_DIR}/watchdog.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP watchdog already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START watchdog"
  SHAREDSIGNALS_ROOT="${ROOT}" PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/watchdog.py --once
  echo "[$(date -Iseconds)] OK watchdog"
} >> "${LOG_FILE}" 2>&1
