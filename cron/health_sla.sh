#!/bin/bash
# Run per-table SharedSignals freshness SLA and expose the result to watchdog.
TIMEOUT="${SHAREDSIGNALS_HEALTH_SLA_TIMEOUT:-120}"
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
WATCHDOG_INPUT_DIR="${WATCHDOG_INPUT_DIR:-${ROOT}/logs/watchdog_inputs}"
LOG_FILE="${LOG_DIR}/health_sla.log"
LOCK_FILE="${LOCK_DIR}/health_sla.lock"
OUTPUT_FILE="${WATCHDOG_INPUT_DIR}/health_sla.json"
TMP_FILE="${OUTPUT_FILE}.$$"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${WATCHDOG_INPUT_DIR}"
exec 2>>"${LOG_FILE}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP health_sla already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START health_sla"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/health_sla.py > "${TMP_FILE}"
  mv "${TMP_FILE}" "${OUTPUT_FILE}"
  cat "${OUTPUT_FILE}"
  echo "[$(date -Iseconds)] OK health_sla"
} >> "${LOG_FILE}" 2>&1
