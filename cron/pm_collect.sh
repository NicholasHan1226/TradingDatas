#!/bin/bash
# Collect Polymarket markets and prices into the SharedSignals read model.
set -euo pipefail

TIMEOUT="${SHAREDSIGNALS_PM_TIMEOUT:-300}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"
if [ "$(id -u)" -eq 0 ] && id -u "${RUN_AS_USER}" >/dev/null 2>&1; then
  exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"
fi

PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/sharedsignals/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/pm_collect.log"
LOCK_FILE="${LOCK_DIR}/pm_collect.lock"
LIMIT="${POLYMARKET_MAX_MARKETS:-200}"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP pm_collect already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"

if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

export POLYMARKET_HTTP_PROXIES="${POLYMARKET_HTTP_PROXIES:-${POLYMARKET_HTTP_PROXY:-http://127.0.0.1:7890}}"
export POLYMARKET_FETCH_RETRIES="${POLYMARKET_FETCH_RETRIES:-3}"
export POLYMARKET_REQUEST_TIMEOUT="${POLYMARKET_REQUEST_TIMEOUT:-25}"
export POLYMARKET_DB_RETRIES="${POLYMARKET_DB_RETRIES:-3}"
export POLYMARKET_DIRECT_FALLBACK_ENABLED="${POLYMARKET_DIRECT_FALLBACK_ENABLED:-0}"

{
  echo "[$(date -Iseconds)] START pm_collect limit=${LIMIT} python=${PYTHON_BIN} proxies=${POLYMARKET_HTTP_PROXIES} direct_fallback=${POLYMARKET_DIRECT_FALLBACK_ENABLED}"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/polymarket_collect.py \
    --limit "${LIMIT}" \
    --proxy "${POLYMARKET_HTTP_PROXIES}" \
    --request-timeout "${POLYMARKET_REQUEST_TIMEOUT}" \
    --retries "${POLYMARKET_FETCH_RETRIES}" \
    --db-retries "${POLYMARKET_DB_RETRIES}"
  echo "[$(date -Iseconds)] OK pm_collect"
} >> "${LOG_FILE}" 2>&1
