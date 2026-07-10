#!/bin/bash
# Run the SharedSignals Tushare event/news lane without running the full P6 tier.
TIMEOUT="${SHAREDSIGNALS_EVENT_CRON_TIMEOUT:-900}"
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
LOG_FILE="${LOG_DIR}/tushare_events_collect.log"
LOCK_FILE="${LOCK_DIR}/tushare_events_collect.lock"

EVENT_APIS="${SHAREDSIGNALS_EVENT_APIS:-anns_d,news,major_news,cctv_news,report_rc}"
LOOKBACK="${SHAREDSIGNALS_EVENT_LOOKBACK_DAYS:-2}"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP tushare_events_collect already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START tushare_events_collect apis=${EVENT_APIS} lookback=${LOOKBACK} python=${PYTHON_BIN}"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/tushare/sync_daily.py \
    --tier P6_other_daily \
    --only-api "${EVENT_APIS}" \
    --lookback "${LOOKBACK}" \
    --exit-on-failure
  echo "[$(date -Iseconds)] OK tushare_events_collect"
} >> "${LOG_FILE}" 2>&1
