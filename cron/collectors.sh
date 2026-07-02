#!/bin/bash
# Run all SharedSignals Tushare sync_daily tiers.
TIMEOUT="${SHAREDSIGNALS_CRON_TIMEOUT:-3600}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/collectors.log"
LOCK_FILE="${LOCK_DIR}/collectors.lock"
TIERS=(
  P0_trading_5min
  P1_eod_daily
  P2_financial_daily
  P3_reference_daily
  P4_macro_daily
  P5_hk_us_daily
  P6_other_daily
)

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP collectors already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START collectors"
  for tier in "${TIERS[@]}"; do
    echo "[$(date -Iseconds)] RUN sync_daily tier=${tier}"
    PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/tushare/sync_daily.py --tier "${tier}" --exit-on-failure
  done
  echo "[$(date -Iseconds)] OK collectors"
} >> "${LOG_FILE}" 2>&1
