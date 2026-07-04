#!/bin/bash
# Collect Binance crypto data through the SharedSignals collector lifecycle.
set -euo pipefail

TIMEOUT="${SHAREDSIGNALS_CRYPTO_TIMEOUT:-300}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"
if [ "$(id -u)" -eq 0 ] && id -u "${RUN_AS_USER}" >/dev/null 2>&1; then
  exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"
fi

PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/marketgraph/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/crypto_collect.log"
LOCK_FILE="${LOCK_DIR}/crypto_collect.lock"
MODE="${SHAREDSIGNALS_CRYPTO_MODE:-ticker}"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP crypto_collect already running" >> "${LOG_FILE}"
  exit 0
fi

cd "${ROOT}"

if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

export BINANCE_HTTP_PROXY="${BINANCE_HTTP_PROXY:-http://127.0.0.1:7890}"

{
  echo "[$(date -Iseconds)] START crypto_collect mode=${MODE} python=${PYTHON_BIN}"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" collectors/crypto/binance_collect.py --mode "${MODE}"
  echo "[$(date -Iseconds)] OK crypto_collect"
} >> "${LOG_FILE}" 2>&1
