#!/usr/bin/env bash
# Fail-closed path contract for the loopback-only TradingDatas V1 service.

tradingdatas_path_error() {
  printf '[ERROR] %s\n' "$*" >&2
  return 78
}


tradingdatas_assert_lexical_path() {
  local name="$1" value="$2"
  case "${value}" in
    /*) ;;
    *) tradingdatas_path_error "${name} must be absolute lexical canonical"; return 78 ;;
  esac
  case "${value}" in
    //*|*//*|*/./*|*/../*|*/.|*/..)
      tradingdatas_path_error "${name} must be absolute lexical canonical"
      return 78
      ;;
  esac
  if [ "${value}" != "/" ] && [ "${value%/}" != "${value}" ]; then
    tradingdatas_path_error "${name} must be absolute lexical canonical"
    return 78
  fi
}


tradingdatas_assert_no_symlink_chain() {
  local name="$1" probe="$2"
  while [ -n "${probe}" ] && [ "${probe}" != "/" ]; do
    if [ -L "${probe}" ]; then
      tradingdatas_path_error "${name} parent chain may not be a symlink"
      return 78
    fi
    probe="${probe%/*}"
    [ -n "${probe}" ] || probe="/"
  done
}


tradingdatas_physical_path() {
  local target="$1" probe="$1" suffix="" base parent physical
  while [ ! -e "${probe}" ]; do
    if [ "${probe}" = "/" ] || [ -z "${probe}" ]; then
      tradingdatas_path_error "runtime path has no available ancestor: ${target}"
      return 78
    fi
    base="${probe##*/}"
    suffix="/${base}${suffix}"
    probe="${probe%/*}"
    [ -n "${probe}" ] || probe="/"
  done
  if [ -d "${probe}" ]; then
    physical="$(cd -P -- "${probe}" 2>/dev/null && pwd -P)" || return 78
  else
    parent="${probe%/*}"
    [ -n "${parent}" ] || parent="/"
    base="${probe##*/}"
    physical="$(cd -P -- "${parent}" 2>/dev/null && pwd -P)/${base}" || return 78
  fi
  printf '%s%s\n' "${physical}" "${suffix}"
}


tradingdatas_require_physical_child() {
  local child_name="$1" child="$2" parent_name="$3" parent="$4"
  case "${child}" in
    "${parent}"/*) return 0 ;;
    *)
      tradingdatas_path_error \
        "${child_name} must remain below ${parent_name} (physical containment)"
      return 78
      ;;
  esac
}


tradingdatas_load_runtime_paths() {
  local initial_root initial_env_file line key value seen index
  local candidate_data_root candidate_database candidate_registry candidate_mount
  local candidate_require_mount
  local staged_keys=() staged_values=()
  initial_root="${TRADINGDATAS_ROOT:-/opt/investment/releases/tradingdatas/current}"
  initial_env_file="${TRADINGDATAS_ENV_FILE:-${initial_root}/deploy/tradingdatas_internal.env}"

  tradingdatas_assert_lexical_path TRADINGDATAS_ROOT "${initial_root}" || return 78
  tradingdatas_assert_lexical_path TRADINGDATAS_ENV_FILE "${initial_env_file}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_ROOT "${initial_root}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_ENV_FILE "${initial_env_file}" || return 78

  if [ -e "${initial_env_file}" ]; then
    if [ ! -f "${initial_env_file}" ] || [ ! -r "${initial_env_file}" ]; then
      tradingdatas_path_error \
        "runtime env file is unreadable or unsafe: ${initial_env_file}"
      return 78
    fi
    while IFS= read -r line || [ -n "${line}" ]; do
      case "${line}" in
        ''|'#'*) continue ;;
      esac
      key="${line%%=*}"
      value="${line#*=}"
      if [ "${key}" = "${line}" ] \
        || [[ ! "${key}" =~ ^TRADINGDATAS_[A-Z0-9_]+$ ]]; then
        tradingdatas_path_error \
          "runtime env accepts only literal TRADINGDATAS_* assignments"
        return 78
      fi
      case "${value}" in
        *$'\r'*) tradingdatas_path_error "runtime env value contains a carriage return"; return 78 ;;
      esac
      for seen in "${staged_keys[@]}"; do
        if [ "${seen}" = "${key}" ]; then
          tradingdatas_path_error "runtime env contains duplicate key: ${key}"
          return 78
        fi
      done
      case "${key}" in
        TRADINGDATAS_ROOT)
          if [ "${value}" != "${initial_root}" ]; then
            tradingdatas_path_error \
              "runtime env may not redirect the code root: ${initial_root} -> ${value}"
            return 78
          fi
          ;;
        TRADINGDATAS_ENV_FILE)
          if [ "${value}" != "${initial_env_file}" ]; then
            tradingdatas_path_error "runtime env may not redirect its own source path"
            return 78
          fi
          ;;
      esac
      staged_keys+=("${key}")
      staged_values+=("${value}")
    done < "${initial_env_file}"
  fi

  candidate_data_root="${TRADINGDATAS_DATA_ROOT:-/opt/investment-data/tradingdatas}"
  candidate_database="${TRADINGDATAS_DB_PATH:-${candidate_data_root}/read_model/provider_native.sqlite}"
  candidate_registry="${TRADINGDATAS_REGISTRY_PATH:-${initial_root}/config/provider_native_dataset_registry.yaml}"
  candidate_mount="${TRADINGDATAS_DATA_MOUNT:-/opt/investment-data}"
  candidate_require_mount="${TRADINGDATAS_REQUIRE_MOUNT:-1}"
  for ((index = 0; index < ${#staged_keys[@]}; index++)); do
    case "${staged_keys[index]}" in
      TRADINGDATAS_DATA_ROOT) candidate_data_root="${staged_values[index]}" ;;
      TRADINGDATAS_DB_PATH) candidate_database="${staged_values[index]}" ;;
      TRADINGDATAS_REGISTRY_PATH) candidate_registry="${staged_values[index]}" ;;
      TRADINGDATAS_DATA_MOUNT) candidate_mount="${staged_values[index]}" ;;
      TRADINGDATAS_REQUIRE_MOUNT) candidate_require_mount="${staged_values[index]}" ;;
    esac
  done

  tradingdatas_assert_lexical_path TRADINGDATAS_DATA_ROOT "${candidate_data_root}" || return 78
  tradingdatas_assert_lexical_path TRADINGDATAS_DB_PATH "${candidate_database}" || return 78
  tradingdatas_assert_lexical_path TRADINGDATAS_REGISTRY_PATH "${candidate_registry}" || return 78
  tradingdatas_assert_lexical_path TRADINGDATAS_DATA_MOUNT "${candidate_mount}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_DATA_ROOT "${candidate_data_root}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_DB_PATH "${candidate_database}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_REGISTRY_PATH "${candidate_registry}" || return 78
  tradingdatas_assert_no_symlink_chain TRADINGDATAS_DATA_MOUNT "${candidate_mount}" || return 78
  case "${candidate_require_mount}" in
    0|1) ;;
    *) tradingdatas_path_error "TRADINGDATAS_REQUIRE_MOUNT must be 0 or 1"; return 78 ;;
  esac

  for ((index = 0; index < ${#staged_keys[@]}; index++)); do
    printf -v "${staged_keys[index]}" '%s' "${staged_values[index]}"
    export "${staged_keys[index]}"
  done
  TRADINGDATAS_ROOT="${initial_root}"
  TRADINGDATAS_ENV_FILE="${initial_env_file}"
  TRADINGDATAS_DATA_ROOT="${candidate_data_root}"
  TRADINGDATAS_DB_PATH="${candidate_database}"
  TRADINGDATAS_REGISTRY_PATH="${candidate_registry}"
  TRADINGDATAS_DATA_MOUNT="${candidate_mount}"
  TRADINGDATAS_REQUIRE_MOUNT="${candidate_require_mount}"
  export TRADINGDATAS_ROOT TRADINGDATAS_ENV_FILE TRADINGDATAS_DATA_ROOT
  export TRADINGDATAS_DB_PATH TRADINGDATAS_REGISTRY_PATH
  export TRADINGDATAS_DATA_MOUNT TRADINGDATAS_REQUIRE_MOUNT
}


tradingdatas_assert_runtime_paths() {
  local name value path physical_root physical_data physical_database
  local physical_registry physical_mount
  for name in \
    TRADINGDATAS_ROOT \
    TRADINGDATAS_ENV_FILE \
    TRADINGDATAS_DATA_ROOT \
    TRADINGDATAS_DB_PATH \
    TRADINGDATAS_REGISTRY_PATH \
    TRADINGDATAS_DATA_MOUNT; do
    value="${!name}"
    tradingdatas_assert_lexical_path "${name}" "${value}" || return 78
    tradingdatas_assert_no_symlink_chain "${name}" "${value}" || return 78
  done

  physical_root="$(tradingdatas_physical_path "${TRADINGDATAS_ROOT}")" || return 78
  physical_data="$(tradingdatas_physical_path "${TRADINGDATAS_DATA_ROOT}")" || return 78
  physical_database="$(tradingdatas_physical_path "${TRADINGDATAS_DB_PATH}")" || return 78
  physical_registry="$(tradingdatas_physical_path "${TRADINGDATAS_REGISTRY_PATH}")" || return 78
  physical_mount="$(tradingdatas_physical_path "${TRADINGDATAS_DATA_MOUNT}")" || return 78

  tradingdatas_require_physical_child \
    TRADINGDATAS_DB_PATH "${physical_database}" \
    TRADINGDATAS_DATA_ROOT "${physical_data}" || return 78
  tradingdatas_require_physical_child \
    TRADINGDATAS_REGISTRY_PATH "${physical_registry}" \
    TRADINGDATAS_ROOT "${physical_root}" || return 78
  tradingdatas_require_physical_child \
    TRADINGDATAS_DATA_ROOT "${physical_data}" \
    TRADINGDATAS_DATA_MOUNT "${physical_mount}" || return 78

  case "${TRADINGDATAS_REQUIRE_MOUNT}" in
    0) return 0 ;;
    1) ;;
    *)
      tradingdatas_path_error "TRADINGDATAS_REQUIRE_MOUNT must be 0 or 1"
      return 78
      ;;
  esac
  command -v mountpoint >/dev/null 2>&1 \
    || { tradingdatas_path_error "mountpoint command unavailable"; return 78; }
  mountpoint -q "${TRADINGDATAS_DATA_MOUNT}" \
    || { tradingdatas_path_error "required data mount is absent"; return 78; }
}
