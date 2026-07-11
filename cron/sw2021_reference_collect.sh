#!/bin/bash
# Run only the dedicated SW2021 snapshot collector and publish lifecycle evidence.
TIMEOUT="${SHAREDSIGNALS_SW2021_TIMEOUT:-3600}"
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
LOG_FILE="${LOG_DIR}/sw2021_reference_collect.log"
LOCK_FILE="${LOCK_DIR}/sw2021_reference_collect.lock"
OUTPUT_FILE="${WATCHDOG_INPUT_DIR}/sw2021_reference.json"
TMP_FILE="${OUTPUT_FILE}.$$"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${WATCHDOG_INPUT_DIR}"
trap 'rm -f "${TMP_FILE}"' EXIT

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP sw2021_reference_collect already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"
if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_TAG="$(date -u +%Y%m%dT%H%M%SZ)-$$"
SNAPSHOT_ID="${SHAREDSIGNALS_SW2021_SNAPSHOT_ID:-sw2021-${RUN_TAG}}"
SOURCE_RUN_ID="${SHAREDSIGNALS_SW2021_SOURCE_RUN_ID:-cron-${RUN_TAG}}"

echo "[$(date -Iseconds)] START sw2021_reference_collect snapshot=${SNAPSHOT_ID}" >> "${LOG_FILE}"
set +e
PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" \
  collectors/tushare/sw2021_reference.py \
  "$@" --snapshot-id "${SNAPSHOT_ID}" --source-run-id "${SOURCE_RUN_ID}" \
  >> "${LOG_FILE}" 2>&1
RESULT=$?
set -e

COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ "${RESULT}" -eq 0 ]; then
  STATE="active"
else
  STATE="rejected"
fi

"${PYTHON_BIN}" - "${STATE}" "${RESULT}" "${STARTED_AT}" "${COMPLETED_AT}" \
  "${SNAPSHOT_ID}" "${SOURCE_RUN_ID}" > "${TMP_FILE}" <<'PY'
import json
import sys

state, exit_code, started_at, completed_at, snapshot_id, source_run_id = sys.argv[1:]
print(json.dumps({
    "owner": "SharedSignals",
    "status": state,
    "exit_code": int(exit_code),
    "started_at": started_at,
    "completed_at": completed_at,
    "snapshot_id": snapshot_id,
    "source_run_id": source_run_id,
}, ensure_ascii=False, indent=2, sort_keys=True))
PY
mv "${TMP_FILE}" "${OUTPUT_FILE}"
cat "${OUTPUT_FILE}" >> "${LOG_FILE}"

if [ "${RESULT}" -eq 0 ]; then
  echo "[$(date -Iseconds)] OK sw2021_reference_collect snapshot=${SNAPSHOT_ID}" >> "${LOG_FILE}"
else
  echo "[$(date -Iseconds)] ERROR sw2021_reference_collect exit=${RESULT}" >> "${LOG_FILE}"
fi
exit "${RESULT}"
