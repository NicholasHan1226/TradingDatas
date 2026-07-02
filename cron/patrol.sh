#!/bin/bash
# Run SharedSignals patrol and trigger heal when the score is below threshold.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON:-python3}"
THRESHOLD="${PATROL_SCORE_THRESHOLD:-60}"
LOG_DIR="${ROOT}/logs/cron"
LOCK_DIR="${ROOT}/logs/locks"
LOG_FILE="${LOG_DIR}/patrol.log"
PATROL_OUTPUT="${LOG_DIR}/patrol_last.json"
LOCK_FILE="${LOCK_DIR}/patrol.lock"

mkdir -p "${LOG_DIR}" "${LOCK_DIR}"

exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] SKIP patrol already running" >> "${LOG_FILE}"
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
  echo "[$(date -Iseconds)] START patrol threshold=${THRESHOLD}"
  PYTHONPATH="${ROOT}" "${PYTHON_BIN}" patrol.py --json --check all > "${PATROL_OUTPUT}"
  SCORE="$(PYTHONPATH="${ROOT}" "${PYTHON_BIN}" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("overall_score", 0))' "${PATROL_OUTPUT}")"
  SHOULD_HEAL="$(PYTHONPATH="${ROOT}" "${PYTHON_BIN}" -c 'import sys; print("1" if float(sys.argv[1]) < float(sys.argv[2]) else "0")' "${SCORE}" "${THRESHOLD}")"
  echo "[$(date -Iseconds)] patrol_score=${SCORE}"
  if [ "${SHOULD_HEAL}" = "1" ]; then
    echo "[$(date -Iseconds)] RUN heal"
    PYTHONPATH="${ROOT}" "${PYTHON_BIN}" heal.py --patrol-result "${PATROL_OUTPUT}"
  fi
  echo "[$(date -Iseconds)] OK patrol"
} >> "${LOG_FILE}" 2>&1
