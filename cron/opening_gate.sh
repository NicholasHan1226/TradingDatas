#!/bin/bash
# Run one lightweight market-session readiness gate and publish its JSON artifact.
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
LOG_FILE="${LOG_DIR}/opening_gate.log"
LOCK_FILE="${LOCK_DIR}/opening_gate.lock"

if [ "$#" -ne 2 ] || [ "$1" != "--phase" ]; then
  echo "usage: $0 --phase preopen|morning_first_sample|afternoon_resume|close_check" >&2
  exit 2
fi

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP opening_gate already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START opening_gate $*"
  SHAREDSIGNALS_ROOT="${ROOT}" PYTHONPATH="${ROOT}" timeout "${SHAREDSIGNALS_OPENING_GATE_TIMEOUT:-20}" "${PYTHON_BIN}" tools/opening_gate.py "$@"
  echo "[$(date -Iseconds)] OK opening_gate $*"
} >> "${LOG_FILE}" 2>&1
