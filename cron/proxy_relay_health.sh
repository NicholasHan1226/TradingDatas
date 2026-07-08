#!/bin/bash
# Run Singapore proxy relay health and expose the result to watchdog.
TIMEOUT="${SHAREDSIGNALS_PROXY_RELAY_HEALTH_TIMEOUT:-60}"
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
LOG_FILE="${LOG_DIR}/proxy_relay_health.log"
LOCK_FILE="${LOCK_DIR}/proxy_relay_health.lock"
OUTPUT_FILE="${WATCHDOG_INPUT_DIR}/proxy_relay.json"
TMP_FILE="${OUTPUT_FILE}.$$"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}" "${WATCHDOG_INPUT_DIR}"
exec 2>>"${LOG_FILE}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP proxy_relay_health already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START proxy_relay_health"
  PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/proxy_relay_health.py > "${TMP_FILE}"
  mv "${TMP_FILE}" "${OUTPUT_FILE}"
  cat "${OUTPUT_FILE}"
  echo "[$(date -Iseconds)] OK proxy_relay_health"
} >> "${LOG_FILE}" 2>&1
