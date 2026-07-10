#!/bin/bash
# Run SharedSignals CNFutures fut_daily collection for a single trade_date.
# Defaults to today; pass --trade-date YYYYMMDD for backfill.
TIMEOUT="${SHAREDSIGNALS_CRON_TIMEOUT:-1800}"
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
LOG_FILE="${LOG_DIR}/cn_futures_daily.log"
LOCK_FILE="${LOCK_DIR}/cn_futures_daily.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP cn_futures_daily already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START cn_futures_daily python=${PYTHON_BIN} args=$*"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/collect_cn_futures_daily.py "$@"
  echo "[$(date -Iseconds)] OK cn_futures_daily"
} >> "${LOG_FILE}" 2>&1
