#!/bin/bash
# Run bounded SharedSignals-owned SQLite maintenance and publish watchdog evidence.
TIMEOUT="${SHAREDSIGNALS_SQLITE_MAINTENANCE_TIMEOUT:-300}"
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
LOG_FILE="${LOG_DIR}/sqlite_maintenance.log"
LOCK_FILE="${LOCK_DIR}/sqlite_maintenance.lock"
OUTPUT_FILE="${WATCHDOG_INPUT_DIR}/sqlite_maintenance.json"
TMP_FILE="${OUTPUT_FILE}.$$"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${WATCHDOG_INPUT_DIR}"
trap 'rm -f "${TMP_FILE}"' EXIT

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP sqlite_maintenance already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"
if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

echo "[$(date -Iseconds)] START sqlite_maintenance" >> "${LOG_FILE}"
set +e
PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" \
  tools/sqlite_maintenance.py "$@" > "${TMP_FILE}" 2>> "${LOG_FILE}"
RESULT=$?
set -e

if [ -s "${TMP_FILE}" ]; then
  mv "${TMP_FILE}" "${OUTPUT_FILE}"
  cat "${OUTPUT_FILE}" >> "${LOG_FILE}"
else
  echo "[$(date -Iseconds)] ERROR sqlite_maintenance produced no evidence" >> "${LOG_FILE}"
fi

if [ "${RESULT}" -eq 0 ]; then
  echo "[$(date -Iseconds)] OK sqlite_maintenance" >> "${LOG_FILE}"
else
  echo "[$(date -Iseconds)] ERROR sqlite_maintenance exit=${RESULT}" >> "${LOG_FILE}"
fi
exit "${RESULT}"
