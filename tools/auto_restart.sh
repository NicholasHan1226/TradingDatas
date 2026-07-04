#!/bin/bash
# Safe SharedSignals API restart helper for watchdog escalation.
set -euo pipefail

ROOT="${SHAREDSIGNALS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEFAULT_PYTHON_BIN="/opt/marketgraph/venv/bin/python3"
if [ -n "${SHAREDSIGNALS_VENV_PYTHON:-}" ]; then
  PYTHON_BIN="${SHAREDSIGNALS_VENV_PYTHON}"
elif [ -x "${DEFAULT_PYTHON_BIN}" ]; then
  PYTHON_BIN="${DEFAULT_PYTHON_BIN}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
API_HOST="${SHAREDSIGNALS_API_HOST:-127.0.0.1}"
API_PORT="${SHAREDSIGNALS_API_PORT:-8082}"
LOCALHOST_BYPASS="${SHAREDSIGNALS_LOCALHOST_BYPASS:-1}"
API_SCRIPT="${SHAREDSIGNALS_API_SCRIPT:-${ROOT}/api_server.py}"
PREVIOUS_BINARY="${SHAREDSIGNALS_API_PREVIOUS_BINARY:-/opt/investment/SharedSignals/releases/previous/api_server.py}"
# Validate previous binary exists before relying on rollback
if [[ -n "${SHAREDSIGNALS_API_PREVIOUS_BINARY:-}" ]] && [[ ! -f "${PREVIOUS_BINARY}" ]]; then
  echo "[WARN] PREVIOUS_BINARY ${PREVIOUS_BINARY} does not exist — rollback disabled" >&2
  PREVIOUS_BINARY=""
fi
LOG_DIR="${ROOT}/logs"
PID_FILE="${LOG_DIR}/api_server.pid"
RESTART_LOG="${LOG_DIR}/auto_restart.jsonl"
FAIL_COUNT_FILE="${LOG_DIR}/auto_restart_failures.count"
API_LOG="${LOG_DIR}/api_server.log"
HEALTH_URL="${SHAREDSIGNALS_API_HEALTH_URL:-http://127.0.0.1:${API_PORT}/health}"
GRACE_SECONDS="${SHAREDSIGNALS_RESTART_GRACE_SECONDS:-10}"
VERIFY_RETRIES="${SHAREDSIGNALS_RESTART_VERIFY_RETRIES:-12}"
VERIFY_SLEEP="${SHAREDSIGNALS_RESTART_VERIFY_SLEEP:-2}"
FORCE_RELOAD=0

usage() {
  cat <<'EOF'
Usage: auto_restart.sh [--force|--force-reload]

Without --force, the helper only restarts when /health is not reachable.
With --force, it restarts even when the API is healthy so a deployed code change
is loaded by the running process.
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --force|--force-reload)
      FORCE_RELOAD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: ${arg}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "${LOG_DIR}"

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

json_log() {
  local status="$1"
  local detail="$2"
  printf '{"timestamp":"%s","status":"%s","detail":%s}\n' "$(now_iso)" "${status}" "${detail}" >> "${RESTART_LOG}"
}

port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${API_PORT}" -sTCP:LISTEN 2>/dev/null || true
  else
    pgrep -f "api_server.py" 2>/dev/null || true
  fi
}

health_ok() {
  curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1
}

read_fail_count() {
  if [ -f "${FAIL_COUNT_FILE}" ]; then
    tr -dc '0-9' < "${FAIL_COUNT_FILE}" || true
  else
    printf "0"
  fi
}

write_fail_count() {
  printf "%s\n" "$1" > "${FAIL_COUNT_FILE}"
}

graceful_stop() {
  local pids
  pids="$(port_pids | tr '\n' ' ')"
  if [ -z "${pids// /}" ]; then
    json_log "no_listener" "{\"port\":${API_PORT}}"
    return 0
  fi
  json_log "stopping" "{\"port\":${API_PORT},\"pids\":\"${pids}\"}"
  # shellcheck disable=SC2086
  kill -TERM ${pids} 2>/dev/null || true
  local waited=0
  while [ "${waited}" -lt "${GRACE_SECONDS}" ]; do
    if [ -z "$(port_pids | tr -d '\n')" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  pids="$(port_pids | tr '\n' ' ')"
  if [ -n "${pids// /}" ]; then
    json_log "force_kill" "{\"port\":${API_PORT},\"pids\":\"${pids}\"}"
    # shellcheck disable=SC2086
    kill -KILL ${pids} 2>/dev/null || true
  fi
}

start_api() {
  local script="$1"
  if [ ! -f "${script}" ]; then
    json_log "start_failed" "{\"reason\":\"script_missing\",\"script\":\"${script}\"}"
    return 1
  fi
  cd "${ROOT}"
  if [ -f "${ROOT}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT}/.env"
    set +a
  fi
  export SHAREDSIGNALS_ROOT="${ROOT}"
  export SHAREDSIGNALS_API_HOST="${SHAREDSIGNALS_API_HOST:-${API_HOST}}"
  export SHAREDSIGNALS_API_PORT="${SHAREDSIGNALS_API_PORT:-${API_PORT}}"
  export SHAREDSIGNALS_LOCALHOST_BYPASS="${SHAREDSIGNALS_LOCALHOST_BYPASS:-${LOCALHOST_BYPASS}}"
  export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
  nohup "${PYTHON_BIN}" "${script}" >> "${API_LOG}" 2>&1 &
  echo "$!" > "${PID_FILE}"
  json_log "started" "{\"script\":\"${script}\",\"pid\":$(cat "${PID_FILE}")}"
}

verify_api() {
  local attempt=1
  while [ "${attempt}" -le "${VERIFY_RETRIES}" ]; do
    if health_ok; then
      json_log "healthy" "{\"attempt\":${attempt},\"url\":\"${HEALTH_URL}\"}"
      return 0
    fi
    sleep "${VERIFY_SLEEP}"
    attempt=$((attempt + 1))
  done
  json_log "verify_failed" "{\"url\":\"${HEALTH_URL}\",\"attempts\":${VERIFY_RETRIES}}"
  return 1
}

main() {
  json_log "begin" "{\"port\":${API_PORT},\"script\":\"${API_SCRIPT}\",\"force_reload\":${FORCE_RELOAD},\"python\":\"${PYTHON_BIN}\"}"

  if [ "${FORCE_RELOAD}" -ne 1 ] && health_ok; then
    json_log "already_healthy" "{\"url\":\"${HEALTH_URL}\"}"
    write_fail_count 0
    exit 0
  fi

  if [ "${FORCE_RELOAD}" -eq 1 ]; then
    json_log "force_reload" "{\"url\":\"${HEALTH_URL}\"}"
  fi

  graceful_stop
  start_api "${API_SCRIPT}"
  if verify_api; then
    write_fail_count 0
    json_log "restart_ok" "{\"rollback\":false}"
    exit 0
  fi

  local failures
  failures="$(read_fail_count)"
  failures=$((failures + 1))
  write_fail_count "${failures}"
  json_log "restart_failed" "{\"failure_count\":${failures}}"

  if [ "${failures}" -ge 3 ] && [ -f "${PREVIOUS_BINARY}" ]; then
    json_log "rollback_attempt" "{\"previous_binary\":\"${PREVIOUS_BINARY}\"}"
    graceful_stop
    start_api "${PREVIOUS_BINARY}"
    if verify_api; then
      write_fail_count 0
      json_log "rollback_ok" "{\"previous_binary\":\"${PREVIOUS_BINARY}\"}"
      exit 0
    fi
    json_log "rollback_failed" "{\"previous_binary\":\"${PREVIOUS_BINARY}\"}"
  fi

  exit 1
}

main "$@"
