#!/bin/bash
# Refresh SharedSignals capability registry for /capabilities.
TIMEOUT="${SHAREDSIGNALS_CAPABILITY_SCAN_TIMEOUT:-600}"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"
if [ "$(id -u)" -eq 0 ] && id -u "${RUN_AS_USER}" >/dev/null 2>&1; then
  exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"
fi
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-/opt/marketgraph/venv/bin/python3}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/capability_scan.log"
LOCK_FILE="${LOCK_DIR}/capability_scan.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP capability_scan already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START capability_scan"
  if PYTHONPATH="${ROOT}" timeout "${TIMEOUT}" "${PYTHON_BIN}" tools/capability_scan.py --no-doc; then
    echo "[$(date -Iseconds)] OK capability_scan"
  else
    rc=$?
    if [ -f "${ROOT}/tools/capability_registry.json" ]; then
      echo "[$(date -Iseconds)] WARN capability_scan completed with degraded endpoints rc=${rc}; registry refreshed"
      exit 0
    fi
    echo "[$(date -Iseconds)] FAILED capability_scan rc=${rc}; registry missing"
    exit "${rc}"
  fi
} >> "${LOG_FILE}" 2>&1
