#!/bin/bash
# Generate the SharedSignals source governance status report.
TIMEOUT="${SHAREDSIGNALS_SOURCE_GOVERNANCE_TIMEOUT:-120}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"
if [ "$(id -u)" -eq 0 ] && id -u "${RUN_AS_USER}" >/dev/null 2>&1; then
  exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"
fi

PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/sharedsignals/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
OUTPUT_DIR="${ROOT}/logs/watchdog_inputs"
LOG_FILE="${LOG_DIR}/source_governance_monitor.log"
LOCK_FILE="${LOCK_DIR}/source_governance_monitor.lock"
OUTPUT_FILE="${OUTPUT_DIR}/source_governance.json"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${OUTPUT_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP source_governance_monitor already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"

{
  echo "[$(date -Iseconds)] START source_governance_monitor"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/source_governance_monitor.py --output "${OUTPUT_FILE}"
  echo "[$(date -Iseconds)] OK source_governance_monitor"
} >> "${LOG_FILE}" 2>&1
