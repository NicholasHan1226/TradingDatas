#!/bin/bash
# Send the daily SharedSignals Green Gate operator email.
TIMEOUT="${SHAREDSIGNALS_GREEN_GATE_TIMEOUT:-120}"
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
LOG_FILE="${LOG_DIR}/green_gate_report.log"
LOCK_FILE="${LOCK_DIR}/green_gate_report.lock"
OUTPUT_FILE="${OUTPUT_DIR}/green_gate_report.json"
BODY_FILE="${OUTPUT_DIR}/green_gate_report.html"
TO="${SHAREDSIGNALS_GREEN_GATE_TO:-soc@coze.email}"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${OUTPUT_DIR}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP green_gate_report already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START green_gate_report"
  SHAREDSIGNALS_ROOT="${ROOT}" PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/green_gate_report.py --to "${TO}" --output "${OUTPUT_FILE}" --body-output "${BODY_FILE}" "$@"
  echo "[$(date -Iseconds)] OK green_gate_report"
} >> "${LOG_FILE}" 2>&1
