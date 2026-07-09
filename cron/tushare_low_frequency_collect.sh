#!/bin/bash
# Run low-frequency Tushare reference bars without expanding daily P6 collection.
TIMEOUT="${SHAREDSIGNALS_LOW_FREQ_CRON_TIMEOUT:-1200}"
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
LOG_FILE="${LOG_DIR}/tushare_low_frequency_collect.log"
LOCK_FILE="${LOCK_DIR}/tushare_low_frequency_collect.lock"

LOW_FREQ_APIS="${SHAREDSIGNALS_LOW_FREQ_APIS:-weekly,monthly,index_weekly,index_monthly}"
LOOKBACK="${SHAREDSIGNALS_LOW_FREQ_LOOKBACK_DAYS:-370}"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP tushare_low_frequency_collect already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START tushare_low_frequency_collect apis=${LOW_FREQ_APIS} lookback=${LOOKBACK} python=${PYTHON_BIN}"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/tushare/sync_daily.py \
    --tier P7_low_frequency \
    --only-api "${LOW_FREQ_APIS}" \
    --lookback "${LOOKBACK}" \
    --exit-on-failure
  echo "[$(date -Iseconds)] OK tushare_low_frequency_collect"
} >> "${LOG_FILE}" 2>&1
