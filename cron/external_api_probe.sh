#!/bin/bash
# Verify that the public route reaches SharedSignals' authentication boundary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/sharedsignals/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
OUTPUT_DIR="${ROOT}/logs/watchdog_inputs"
LOG_FILE="${LOG_DIR}/external_api_probe.log"
LOCK_FILE="${LOCK_DIR}/external_api_probe.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${OUTPUT_DIR}"
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP external_api_probe already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"
{
  echo "[$(date -Iseconds)] START external_api_probe"
  PYTHONPATH="${ROOT}" "${PYTHON_BIN}" tools/external_api_probe.py --output "${OUTPUT_DIR}/external_api_probe.json"
  echo "[$(date -Iseconds)] OK external_api_probe"
} >> "${LOG_FILE}" 2>&1
