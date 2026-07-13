#!/bin/bash
# Shared path and mount contract for deploy.sh and rollback.sh.

sharedsignals_path_error() {
  echo "[ERROR] $*" >&2
  return 1
}

sharedsignals_load_runtime_paths() {
  local allexport_was_set=0
  local initial_repo_dir
  REPO_DIR="${SHAREDSIGNALS_REPO_DIR:-/opt/investment/SharedSignals}"
  initial_repo_dir="${REPO_DIR}"
  ENV_FILE="${SHAREDSIGNALS_ENV_FILE:-${REPO_DIR}/.env}"
  if [ -e "${ENV_FILE}" ]; then
    if [ ! -f "${ENV_FILE}" ] || [ -L "${ENV_FILE}" ] || [ ! -r "${ENV_FILE}" ]; then
      sharedsignals_path_error "runtime env file missing, unreadable or unsafe: ${ENV_FILE}"
      return 78
    fi
    case "$-" in *a*) allexport_was_set=1 ;; esac
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    if [ "${allexport_was_set}" = "0" ]; then
      set +a
    fi
    REPO_DIR="${SHAREDSIGNALS_REPO_DIR:-${REPO_DIR}}"
    if [ "${REPO_DIR}" != "${initial_repo_dir}" ]; then
      sharedsignals_path_error \
        "runtime env may not redirect the repository root: ${initial_repo_dir} -> ${REPO_DIR}"
      return 78
    fi
  fi
  RUNTIME_DIR="${SHAREDSIGNALS_RUNTIME_ROOT:-${REPO_DIR}/runtime}"
  READ_MODEL_DIR="${SHAREDSIGNALS_READ_MODEL_DIR:-${RUNTIME_DIR}/read_model}"
  SQLITE_DB="${SHAREDSIGNALS_MARKETDATA_DB:-${READ_MODEL_DIR}/marketdata.sqlite}"
  BACKUP_DIR="${SHAREDSIGNALS_BACKUP_DIR:-${REPO_DIR}/backups}"
  RUNTIME_BACKUP_DIR="${SHAREDSIGNALS_RUNTIME_BACKUP_DIR:-/opt/investment/runtime-backups}"
  DATA_MOUNT="${SHAREDSIGNALS_DATA_MOUNT:-/opt/investment-data}"
  DATA_UUID="${SHAREDSIGNALS_DATA_UUID:-3f7cbf99-b15e-4c54-94cc-a57e38412874}"
  SERVICE_MOUNT_GUARD="${SHAREDSIGNALS_SERVICE_MOUNT_GUARD:-/etc/systemd/system/sharedsignals-api.service.d/20-finance-data-mount.conf}"
  REQUIRE_MOUNTS="${SHAREDSIGNALS_REQUIRE_MOUNTS:-1}"
  export REPO_DIR ENV_FILE RUNTIME_DIR READ_MODEL_DIR SQLITE_DB BACKUP_DIR
  export RUNTIME_BACKUP_DIR DATA_MOUNT DATA_UUID SERVICE_MOUNT_GUARD REQUIRE_MOUNTS
}

sharedsignals_assert_runtime_paths() {
  local name value path mounted_uuid
  for name in REPO_DIR RUNTIME_DIR READ_MODEL_DIR SQLITE_DB BACKUP_DIR RUNTIME_BACKUP_DIR DATA_MOUNT SERVICE_MOUNT_GUARD; do
    value="${!name}"
    case "${value}" in
      /*) ;;
      *) sharedsignals_path_error "${name} must be absolute: ${value}" || return 78 ;;
    esac
  done

  case "${SQLITE_DB}" in
    "${READ_MODEL_DIR}"/*) ;;
    *) sharedsignals_path_error "SQLite authority must remain below READ_MODEL_DIR" || return 78 ;;
  esac

  for path in "${READ_MODEL_DIR}" "${SQLITE_DB}" "${BACKUP_DIR}" "${RUNTIME_BACKUP_DIR}"; do
    if [ -L "${path}" ]; then
      sharedsignals_path_error "runtime authority path may not be a symlink: ${path}" || return 78
    fi
  done

  if [ "${REPO_DIR}" = "/opt/investment/SharedSignals" ] \
    && [ "${REQUIRE_MOUNTS}" != "1" ]; then
    sharedsignals_path_error "production repository may not disable mount checks" || return 78
  fi

  case "${REQUIRE_MOUNTS}" in
    0) return 0 ;;
    1) ;;
    *) sharedsignals_path_error "SHAREDSIGNALS_REQUIRE_MOUNTS must be 0 or 1" || return 78 ;;
  esac
  command -v mountpoint >/dev/null 2>&1 \
    || { sharedsignals_path_error "mountpoint command unavailable"; return 78; }
  command -v findmnt >/dev/null 2>&1 \
    || { sharedsignals_path_error "findmnt command unavailable"; return 78; }
  for path in "${DATA_MOUNT}" "${READ_MODEL_DIR}" "${BACKUP_DIR}" "${RUNTIME_BACKUP_DIR}"; do
    if ! mountpoint -q "${path}"; then
      sharedsignals_path_error "required production mount is absent: ${path}" || return 78
    fi
  done
  mounted_uuid="$(findmnt -n -o UUID --target "${DATA_MOUNT}" 2>/dev/null || true)"
  if [ -z "${DATA_UUID}" ] || [ "${mounted_uuid}" != "${DATA_UUID}" ]; then
    sharedsignals_path_error \
      "data mount UUID mismatch: expected ${DATA_UUID}, got ${mounted_uuid:-none}" || return 78
  fi
  if [ ! -f "${SERVICE_MOUNT_GUARD}" ] || [ -L "${SERVICE_MOUNT_GUARD}" ]; then
    sharedsignals_path_error "service mount guard missing or unsafe: ${SERVICE_MOUNT_GUARD}" || return 78
  fi
  for path in "${DATA_MOUNT}" "${READ_MODEL_DIR}" "${BACKUP_DIR}"; do
    if ! grep -F -- "${path}" "${SERVICE_MOUNT_GUARD}" >/dev/null 2>&1; then
      sharedsignals_path_error "service mount guard does not reference ${path}" || return 78
    fi
  done
}
