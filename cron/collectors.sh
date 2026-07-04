#!/bin/bash
# Run SharedSignals Tushare sync_daily tiers.
TIMEOUT="${SHAREDSIGNALS_CRON_TIMEOUT:-3600}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/marketgraph/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/collectors.log"
DEFAULT_TIERS=(
  P0_trading_5min
  P1_eod_daily
  P2_financial_daily
  P3_reference_daily
  P4_macro_daily
  P5_hk_us_daily
  P6_other_daily
)
TIERS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      TIERS=("${DEFAULT_TIERS[@]}")
      shift
      ;;
    --tier)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --tier" >&2
        exit 2
      fi
      IFS=',' read -r -a requested_tiers <<< "$2"
      TIERS+=("${requested_tiers[@]}")
      shift 2
      ;;
    *)
      TIERS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#TIERS[@]} -eq 0 ]]; then
  TIERS=("${DEFAULT_TIERS[@]}")
fi

for tier in "${TIERS[@]}"; do
  if [[ ! " ${DEFAULT_TIERS[*]} " =~ " ${tier} " ]]; then
    echo "unknown SharedSignals Tushare tier: ${tier}" >&2
    exit 2
  fi
done
LOCK_SUFFIX="$(printf '%s_' "${TIERS[@]}" | tr -cd 'A-Za-z0-9_-')"
LOCK_FILE="${LOCK_DIR}/collectors_${LOCK_SUFFIX:-all}.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP collectors tiers=${TIERS[*]} already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"

if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  python3 -c "from env_bootstrap import bootstrap_sharedsignals_env; bootstrap_sharedsignals_env()"
  set +a
fi

{
  echo "[$(date -Iseconds)] START collectors tiers=${TIERS[*]} python=${PYTHON_BIN}"
  for tier in "${TIERS[@]}"; do
    echo "[$(date -Iseconds)] RUN sync_daily tier=${tier}"
    PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/tushare/sync_daily.py --tier "${tier}" --exit-on-failure
  done
  echo "[$(date -Iseconds)] OK collectors"
} >> "${LOG_FILE}" 2>&1
