#!/bin/bash
# Run SharedSignals Tushare sync_daily tiers.
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
LOG_FILE="${LOG_DIR}/collectors.log"
SUPPORTED_TIERS=(
  P0_trading_5min
  P1_eod_daily
  P3_reference_daily
  P4_macro_daily
  P5_hk_us_daily
  P6_other_daily
)
DEFAULT_TIERS=(
  P0_trading_5min
  P1_eod_daily
  P3_reference_daily
  P4_macro_daily
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
  if [[ ! " ${SUPPORTED_TIERS[*]} " =~ " ${tier} " ]]; then
    echo "unknown SharedSignals Tushare tier: ${tier}" >&2
    exit 2
  fi
done
LOCK_SUFFIX="$(printf '%s_' "${TIERS[@]}" | tr -cd 'A-Za-z0-9_-')"
LOCK_FILE="${LOCK_DIR}/collectors_${LOCK_SUFFIX:-all}.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/maintenance_lock.sh"
acquire_sharedsignals_read_model_lock "${ROOT}" "${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP collectors tiers=${TIERS[*]} already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START collectors tiers=${TIERS[*]} python=${PYTHON_BIN}"
  for tier in "${TIERS[@]}"; do
    echo "[$(date -Iseconds)] RUN sync_daily tier=${tier}"
    TIMEOUT="${SHAREDSIGNALS_CRON_TIMEOUT:-3600}"
    EXTRA_ARGS=()
    RUNNER=("${PYTHON_BIN}")
    if [ "${tier}" = "P2_financial_daily" ]; then
      TIMEOUT="${SHAREDSIGNALS_P2_TIMEOUT:-900}"
      EXTRA_ARGS=(
        --max-provider-calls "${SHAREDSIGNALS_P2_MAX_PROVIDER_CALLS:-2500}"
        --max-rows-admitted "${SHAREDSIGNALS_P2_MAX_ROWS_ADMITTED:-100000}"
        --deadline-seconds "${SHAREDSIGNALS_P2_DEADLINE_SECONDS:-840}"
      )
      if command -v ionice >/dev/null 2>&1; then
        RUNNER=(ionice -c3 nice -n 10 "${PYTHON_BIN}")
      else
        RUNNER=(nice -n 10 "${PYTHON_BIN}")
      fi
    fi
    PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${RUNNER[@]}" \
      collectors/tushare/sync_daily.py --tier "${tier}" --exit-on-failure "${EXTRA_ARGS[@]}"
  done
  echo "[$(date -Iseconds)] OK collectors"
} >> "${LOG_FILE}" 2>&1
