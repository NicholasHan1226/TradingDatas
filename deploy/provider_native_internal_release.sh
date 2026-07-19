#!/usr/bin/env bash
# Isolated release control plane for the loopback-only provider-native V1 API.

set -Eeuo pipefail
umask 077

SERVICE="sharedsignals-v1-internal.service"
LEGACY_SERVICE="sharedsignals-api.service"
RELEASE_BASE="/opt/investment/releases/sharedsignals-v1"
RELEASES_DIR="${RELEASE_BASE}/releases"
CURRENT_LINK="/opt/investment/releases/sharedsignals-v1/current"
STATE_DIR="${RELEASE_BASE}/state"
EVIDENCE_DIR="${RELEASE_BASE}/evidence"
RELEASE_LOCK="/run/lock/sharedsignals-v1-internal-release.lock"
DATABASE="/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite"
DATABASE_LOCK="/opt/investment-data/sharedsignals-v1/read_model/.provider_native.sqlite.read_model_store.lock"
MAINTENANCE_LOCK="/opt/investment-data/sharedsignals-v1/locks/read_model_maintenance.lock"
LEGACY_DATABASE="/opt/investment-data/SharedSignals/runtime/read_model/marketdata.sqlite"
SECRET_ENV="/etc/sharedsignals/provider-native-internal.secrets"
COLLECTOR_SECRET_ENV="/etc/sharedsignals/provider-native-collector.secrets"
PROBE_SECRET_ENV="/etc/sharedsignals/provider-native-probe.secrets"
SECRET_OWNER_UID=0
SECRET_HASH_GROUP_GID=""
UNIT_DIR="/etc/systemd/system"
UNIT_TARGET="${UNIT_DIR}/sharedsignals-v1-internal.service"
PORT="18082"
LEGACY_PORT="8082"
VENV_PYTHON="/opt/sharedsignals/venv/bin/python3"
SYSTEMCTL="/bin/systemctl"
CURL="/usr/bin/curl"
SS="/usr/bin/ss"
SHA256SUM="/usr/bin/sha256sum"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROFILE_RELATIVE="deploy/provider_native_internal.env"
UNIT_RELATIVE="deploy/systemd/sharedsignals-v1-internal.service"
REGISTRY_RELATIVE="config/provider_native_dataset_registry.yaml"
ACTIVATION_RELATIVE="config/provider_native_activation.yaml"
WRAPPER_RELATIVE="tools/serve_provider_native_v1.py"
INIT_RELATIVE="tools/init_provider_native_store.py"
SCHEDULE_RELATIVE="config/provider_native_schedule.yaml"
SCHEDULE_RUNNER_RELATIVE="tools/run_provider_native_schedule.py"
PROBE_RELATIVE="tools/internal_v1_probe.py"
MANIFEST_NAME=".sharedsignals-v1-release.env"
SUMS_NAME=".sharedsignals-v1-SHA256SUMS"
UNIT_NAMES=(
  "sharedsignals-v1-internal.service"
  "sharedsignals-provider-native-collect.service"
  "sharedsignals-provider-native-collect.timer"
  "sharedsignals-v1-probe.service"
  "sharedsignals-v1-probe.timer"
)
UNIT_RELATIVES=(
  "deploy/systemd/sharedsignals-v1-internal.service"
  "deploy/systemd/sharedsignals-provider-native-collect.service"
  "deploy/systemd/sharedsignals-provider-native-collect.timer"
  "deploy/systemd/sharedsignals-v1-probe.service"
  "deploy/systemd/sharedsignals-v1-probe.timer"
)
TIMER_NAMES=(
  "sharedsignals-provider-native-collect.timer"
  "sharedsignals-v1-probe.timer"
)
ONESHOT_NAMES=(
  "sharedsignals-provider-native-collect.service"
  "sharedsignals-v1-probe.service"
)


die() {
  printf '[ERROR] %s\n' "$*" >&2
  return 78
}


require_command() {
  [ -x "$1" ] || die "required executable is unavailable: $1"
}


stat_uid() {
  stat -Lc '%u' -- "$1" 2>/dev/null || stat -f '%u' -- "$1"
}


stat_gid() {
  stat -Lc '%g' -- "$1" 2>/dev/null || stat -f '%g' -- "$1"
}


stat_mode() {
  stat -Lc '%a' -- "$1" 2>/dev/null || stat -f '%Lp' -- "$1"
}


stat_nlink() {
  stat -Lc '%h' -- "$1" 2>/dev/null || stat -f '%l' -- "$1"
}


stat_fingerprint() {
  stat -Lc '%d:%i:%s:%Y:%f:%u:%g' -- "$1" 2>/dev/null \
    || stat -f '%d:%i:%z:%m:%p:%u:%g' -- "$1"
}


stat_identity() {
  stat -Lc '%d:%i' -- "$1" 2>/dev/null || stat -f '%d:%i' -- "$1"
}


canonical_existing_path() {
  local path="$1" canonical
  canonical="$(realpath "$path" 2>/dev/null)" \
    || die "path is unavailable: $path"
  [ -e "$canonical" ] || die "path is unavailable: $path"
  printf '%s' "$canonical"
}


move_directory_no_target() {
  local source="$1" target="$2"
  if mv -T -- "$source" "$target" 2>/dev/null; then
    return 0
  fi
  [ ! -e "$target" ] && [ ! -L "$target" ] \
    || die "release target already exists"
  mv -- "$source" "$target"
}


manifest_value() {
  local manifest="$1" key="$2" line
  line="$(grep -E "^${key}=[^[:space:]]+$" "$manifest" || true)"
  [ -n "$line" ] || die "release manifest is missing ${key}"
  [ "$(printf '%s\n' "$line" | wc -l | tr -d ' ')" = "1" ] \
    || die "release manifest duplicates ${key}"
  printf '%s' "${line#*=}"
}


require_regular_no_link() {
  local path="$1" label="$2"
  [ -f "$path" ] && [ ! -L "$path" ] \
    || die "${label} must be a regular non-link file"
}


validate_secret_env() {
  local mode owner group names unexpected missing malformed entry_count
  local token_hash_file canonical expected_group
  require_regular_no_link "$SECRET_ENV" "runtime credential EnvironmentFile"
  [ "$(canonical_existing_path "$SECRET_ENV")" = "$SECRET_ENV" ] \
    && [ "$(stat_nlink "$SECRET_ENV")" = "1" ] \
    || die "runtime credential EnvironmentFile binding is invalid"
  mode="$(stat_mode "$SECRET_ENV")"
  owner="$(stat_uid "$SECRET_ENV")"
  [ "$mode" = "600" ] || die "runtime credential EnvironmentFile must use mode 0600"
  [ "$owner" = "$SECRET_OWNER_UID" ] \
    || die "runtime credential EnvironmentFile owner is invalid"

  malformed="$(LC_ALL=C awk '
    /^[[:space:]]*($|#)/ { next }
    !/^[A-Z][A-Z0-9_]*=/ { print "invalid"; exit }
    {
      value = substr($0, index($0, "=") + 1)
      if (value == "" || value ~ /[[:space:][:cntrl:]\"]/ || index(value, sprintf("%c", 39)) > 0) {
        print "invalid"
        exit
      }
    }
  ' "$SECRET_ENV")"
  [ -z "$malformed" ] || die "runtime credential EnvironmentFile has invalid syntax"
  names="$(awk -F= '
    /^[[:space:]]*($|#)/ { next }
    { print $1 }
  ' "$SECRET_ENV" | LC_ALL=C sort -u)"
  entry_count="$(awk '
    /^[[:space:]]*($|#)/ { next }
    { count += 1 }
    END { print count + 0 }
  ' "$SECRET_ENV")"
  unexpected="$(comm -13 <(printf '%s\n' \
    SHAREDSIGNALS_CURSOR_SIGNING_KEY \
    SHAREDSIGNALS_TOKEN_HASH_FILE \
    SHAREDSIGNALS_TOKEN_SALT | LC_ALL=C sort) <(printf '%s\n' "$names") || true)"
  missing="$(comm -23 <(printf '%s\n' \
    SHAREDSIGNALS_CURSOR_SIGNING_KEY \
    SHAREDSIGNALS_TOKEN_HASH_FILE \
    SHAREDSIGNALS_TOKEN_SALT | LC_ALL=C sort) <(printf '%s\n' "$names") || true)"
  [ -z "$unexpected" ] || die "runtime credential EnvironmentFile has an unexpected key"
  [ -z "$missing" ] || die "runtime credential EnvironmentFile is missing a required key"
  [ "$entry_count" = "3" ] \
    && [ "$(printf '%s\n' "$names" | sed '/^$/d' | wc -l | tr -d ' ')" = "3" ] \
    || die "runtime credential EnvironmentFile key set is invalid"

  token_hash_file="$(awk -F= '
    /^SHAREDSIGNALS_TOKEN_HASH_FILE=/ {
      print substr($0, index($0, "=") + 1)
    }
  ' "$SECRET_ENV")"
  [[ "$token_hash_file" = /* ]] \
    || die "token hash file path must be absolute and canonical"
  canonical="$(realpath "$token_hash_file" 2>/dev/null || true)"
  [ -n "$canonical" ] && [ "$canonical" = "$token_hash_file" ] \
    || die "token hash file path must be absolute and canonical"
  require_regular_no_link "$token_hash_file" "token hash file"
  [ "$(stat_nlink "$token_hash_file")" = "1" ] \
    || die "token hash file binding is invalid"
  mode="$(stat_mode "$token_hash_file")"
  owner="$(stat_uid "$token_hash_file")"
  group="$(stat_gid "$token_hash_file")"
  expected_group="${SECRET_HASH_GROUP_GID:-}"
  if [ -z "$expected_group" ]; then
    expected_group="$(id -g marketgraph 2>/dev/null)" \
      || die "marketgraph group is unavailable"
  fi
  [ "$mode" = "640" ] && [ "$owner" = "$SECRET_OWNER_UID" ] \
    && [ "$group" = "$expected_group" ] \
    || die "token hash file must be root:marketgraph mode 0640"
}


validate_exact_root_secret_names() {
  local path="$1" expected="$2" label="$3" mode owner names count malformed
  require_regular_no_link "$path" "$label"
  [ "$(canonical_existing_path "$path")" = "$path" ] \
    && [ "$(stat_nlink "$path")" = "1" ] \
    || die "${label} binding is invalid"
  mode="$(stat_mode "$path")"
  owner="$(stat_uid "$path")"
  [ "$mode" = "600" ] && [ "$owner" = "$SECRET_OWNER_UID" ] \
    || die "${label} must be root-owned mode 0600"
  malformed="$(LC_ALL=C awk '
    /^[[:space:]]*($|#)/ { next }
    !/^[A-Z][A-Z0-9_]*=/ { print "invalid"; exit }
    {
      value = substr($0, index($0, "=") + 1)
      if (value == "" || value ~ /[[:space:][:cntrl:]\"]/ || index(value, sprintf("%c", 39)) > 0) {
        print "invalid"
        exit
      }
    }
  ' "$path")"
  [ -z "$malformed" ] || die "${label} has invalid syntax"
  names="$(awk -F= '
    /^[[:space:]]*($|#)/ { next }
    { print $1 }
  ' "$path" | LC_ALL=C sort)"
  count="$(printf '%s\n' "$names" | sed '/^$/d' | wc -l | tr -d ' ')"
  [ "$names" = "$expected" ] \
    && [ "$count" = "$(printf '%s\n' "$expected" | sed '/^$/d' | wc -l | tr -d ' ')" ] \
    || die "${label} key set is invalid"
}


validate_all_secret_envs() {
  validate_secret_env
  validate_exact_root_secret_names \
    "$COLLECTOR_SECRET_ENV" \
    $'QUICKSYNC_API_URL\nQUICKSYNC_TOKEN' \
    "collector credential EnvironmentFile"
  validate_exact_root_secret_names \
    "$PROBE_SECRET_ENV" \
    'SHAREDSIGNALS_INTERNAL_V1_TOKEN' \
    "probe credential EnvironmentFile"
}


validate_profile() {
  local path="$1"
  require_regular_no_link "$path" "Git-owned runtime profile"
  grep -Fx 'REAL_TRADING_ENABLED=false' "$path" >/dev/null \
    || die "runtime profile must keep real trading disabled"
  grep -Fx 'SHAREDSIGNALS_API_HOST=127.0.0.1' "$path" >/dev/null \
    || die "runtime profile must bind loopback"
  grep -Fx 'SHAREDSIGNALS_API_PORT=18082' "$path" >/dev/null \
    || die "runtime profile port is invalid"
  grep -Fx 'SHAREDSIGNALS_API_SURFACE=provider-native-v1-only' "$path" >/dev/null \
    || die "runtime profile surface is invalid"
  grep -Fx 'SHAREDSIGNALS_LOCALHOST_BYPASS=0' "$path" >/dev/null \
    || die "runtime profile must disable localhost authentication bypass"
  grep -Fx "SHAREDSIGNALS_MARKETDATA_DB=${DATABASE}" "$path" >/dev/null \
    || die "runtime profile database path is invalid"
  grep -Fx "SHAREDSIGNALS_DATASET_REGISTRY_PATH=${CURRENT_LINK}/${REGISTRY_RELATIVE}" "$path" >/dev/null \
    || die "runtime profile registry path is invalid"
  if grep -E '(^|_)(TOKEN|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY)=' "$path" >/dev/null; then
    die "Git-owned runtime profile contains a credential key"
  fi
}


validate_api_unit_source() {
  local path="$1"
  require_regular_no_link "$path" "internal systemd unit"
  grep -Fx 'Environment="SHAREDSIGNALS_LOCALHOST_BYPASS=0"' "$path" >/dev/null \
    || die "internal unit must disable localhost authentication bypass"
  grep -Fx "EnvironmentFile=${CURRENT_LINK}/${PROFILE_RELATIVE}" "$path" >/dev/null \
    || die "internal unit profile path is invalid"
  grep -Fx "EnvironmentFile=${SECRET_ENV}" "$path" >/dev/null \
    || die "internal unit credential path is invalid"
  [ "$(grep -c '^EnvironmentFile=' "$path")" = "2" ] \
    || die "internal unit EnvironmentFile set is invalid"
  grep -F -e "$COLLECTOR_SECRET_ENV" -e "$PROBE_SECRET_ENV" "$path" >/dev/null \
    && die "internal unit may not load an operations credential file"
  grep -Fx "ExecStart=${CURRENT_LINK}/deploy/provider_native_internal_release.sh serve" "$path" >/dev/null \
    || die "internal unit entrypoint is invalid"
  grep -Fx 'ReadOnlyPaths=/opt/investment-data/sharedsignals-v1' "$path" >/dev/null \
    || die "internal unit runtime data must be read-only"
  grep -F 'ReadWritePaths=' "$path" >/dev/null \
    && die "internal unit may not receive runtime write access"
  grep -F "$LEGACY_SERVICE" "$path" >/dev/null \
    && die "internal unit may not depend on the legacy service"
  return 0
}


validate_ops_unit_source() {
  local path="$1" name="$2"
  require_regular_no_link "$path" "internal operations unit"
  grep -F "$LEGACY_SERVICE" "$path" >/dev/null \
    && die "internal operations unit may not depend on the legacy service"
  grep -F -e "$LEGACY_DATABASE" -e "127.0.0.1:${LEGACY_PORT}" "$path" >/dev/null \
    && die "internal operations unit may not reference the legacy data lane"
  grep -F 'EnvironmentFile=/opt/investment/SharedSignals/.env' "$path" >/dev/null \
    && die "internal operations unit may not load the legacy EnvironmentFile"
  grep -Ei 'nginx|cloudflared|REAL_TRADING_ENABLED=true' "$path" >/dev/null \
    && die "internal operations unit contains a forbidden dependency"
  case "$name" in
    sharedsignals-provider-native-collect.service)
      grep -Fx "EnvironmentFile=${CURRENT_LINK}/${PROFILE_RELATIVE}" "$path" >/dev/null \
        || die "collector unit public profile path is invalid"
      grep -Fx "EnvironmentFile=${COLLECTOR_SECRET_ENV}" "$path" >/dev/null \
        || die "collector unit credential path is invalid"
      [ "$(grep -c '^EnvironmentFile=' "$path")" = "2" ] \
        || die "collector unit EnvironmentFile set is invalid"
      grep -F -e "$SECRET_ENV" -e "$PROBE_SECRET_ENV" "$path" >/dev/null \
        && die "collector unit may not load another lane credential file"
      grep -F '/tools/run_provider_native_schedule.py --execute' "$path" >/dev/null \
        || die "collector unit entrypoint is invalid"
      grep -Fx 'TimeoutStartSec=900s' "$path" >/dev/null \
        || die "collector unit timeout is invalid"
      ;;
    sharedsignals-provider-native-collect.timer)
      [ "$(grep -c '^EnvironmentFile=' "$path" || true)" = "0" ] \
        || die "collector timer may not load an EnvironmentFile"
      grep -Fx 'Unit=sharedsignals-provider-native-collect.service' "$path" >/dev/null \
        || die "collector timer target is invalid"
      ;;
    sharedsignals-v1-probe.service)
      grep -Fx "EnvironmentFile=${CURRENT_LINK}/${PROFILE_RELATIVE}" "$path" >/dev/null \
        || die "probe unit public profile path is invalid"
      grep -Fx "EnvironmentFile=${PROBE_SECRET_ENV}" "$path" >/dev/null \
        || die "probe unit credential path is invalid"
      [ "$(grep -c '^EnvironmentFile=' "$path")" = "2" ] \
        || die "probe unit EnvironmentFile set is invalid"
      grep -F -e "$SECRET_ENV" -e "$COLLECTOR_SECRET_ENV" "$path" >/dev/null \
        && die "probe unit may not load another lane credential file"
      grep -F '/tools/internal_v1_probe.py ' "$path" >/dev/null \
        || die "probe unit entrypoint is invalid"
      grep -F -- '--startup-policy strict' "$path" >/dev/null \
        || die "probe unit must use strict startup policy"
      grep -Fx 'TimeoutStartSec=120s' "$path" >/dev/null \
        || die "probe unit timeout is invalid"
      ;;
    sharedsignals-v1-probe.timer)
      [ "$(grep -c '^EnvironmentFile=' "$path" || true)" = "0" ] \
        || die "probe timer may not load an EnvironmentFile"
      grep -Fx 'Unit=sharedsignals-v1-probe.service' "$path" >/dev/null \
        || die "probe timer target is invalid"
      ;;
    *) die "unknown internal operations unit" ;;
  esac
  return 0
}


validate_all_unit_sources() {
  local root="$1" index
  validate_api_unit_source "$root/${UNIT_RELATIVES[0]}"
  for index in 1 2 3 4; do
    validate_ops_unit_source "$root/${UNIT_RELATIVES[$index]}" "${UNIT_NAMES[$index]}"
  done
}


validate_activation_registry_pair() {
  local root="$1" registry="$2" activation="$3"
  require_regular_no_link "$registry" "provider-native registry"
  require_regular_no_link "$activation" "provider-native activation manifest"
  PYTHONPATH="$root" "$VENV_PYTHON" - "$registry" "$activation" <<'PY'
import sys
from pathlib import Path

import yaml

from dataset_registry import load_dataset_registry

registry = load_dataset_registry(Path(sys.argv[1]))

class UniqueLoader(yaml.SafeLoader):
    pass

def construct_unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("duplicate activation key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result

UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)
with Path(sys.argv[2]).open("r", encoding="utf-8") as handle:
    manifest = yaml.load(handle, Loader=UniqueLoader)
if type(manifest) is not dict or set(manifest) != {"version", "activations"}:
    raise SystemExit(78)
if manifest["version"] != 1 or type(manifest["activations"]) is not list:
    raise SystemExit(78)
expected_rows = []
for row in manifest["activations"]:
    if type(row) is not dict or set(row) != {
        "dataset_id", "provider", "entitlement_state", "activation_state", "evidence_ref"
    }:
        raise SystemExit(78)
    if row["entitlement_state"] not in {"active", "locked", "unknown", "excluded", "retired"}:
        raise SystemExit(78)
    if row["activation_state"] not in {"active", "paused"}:
        raise SystemExit(78)
    if not all(type(row[key]) is str and row[key] for key in ("dataset_id", "provider")):
        raise SystemExit(78)
    if row["activation_state"] == "active":
        if row["entitlement_state"] != "active":
            raise SystemExit(78)
        if type(row["evidence_ref"]) is not str or not row["evidence_ref"]:
            raise SystemExit(78)
        expected_rows.append((row["dataset_id"], row["provider"]))
    elif row["evidence_ref"] is not None and (
        type(row["evidence_ref"]) is not str or not row["evidence_ref"]
    ):
        raise SystemExit(78)
expected = tuple(sorted(expected_rows))
if not expected or len(expected) != len(set(expected)):
    raise SystemExit(78)
active = tuple(
    sorted(
        (dataset.dataset_id, binding.provider)
        for dataset in registry.datasets
        for binding in dataset.provider_bindings
        if dataset.read_model_adapter.storage_kind == "provider_native_rows"
        and binding.entitlement_state == "active"
        and binding.activation_state == "active"
    )
)
if active != expected:
    raise SystemExit(78)
PY
}


validate_source() {
  local expected_commit="$1" top head origin status
  [[ "$expected_commit" =~ ^[0-9a-f]{40}$ ]] \
    || die "expected commit must be a full lowercase SHA"
  top="$(git -C "$SOURCE_ROOT" rev-parse --show-toplevel 2>/dev/null)" \
    || die "release source is not a Git checkout"
  [ "$(cd "$top" && pwd -P)" = "$(cd "$SOURCE_ROOT" && pwd -P)" ] \
    || die "release source root is not canonical"
  head="$(git -C "$SOURCE_ROOT" rev-parse HEAD)"
  [ "$head" = "$expected_commit" ] || die "release source commit does not match approval"
  origin="$(git -C "$SOURCE_ROOT" rev-parse origin/main 2>/dev/null)" \
    || die "canonical origin/main is unavailable"
  [ "$origin" = "$expected_commit" ] \
    || die "release source is not the approved canonical origin/main"
  status="$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=all)"
  [ -z "$status" ] || die "release source is not clean"
  validate_profile "$SOURCE_ROOT/$PROFILE_RELATIVE"
  validate_all_unit_sources "$SOURCE_ROOT"
  validate_activation_registry_pair \
    "$SOURCE_ROOT" \
    "$SOURCE_ROOT/$REGISTRY_RELATIVE" \
    "$SOURCE_ROOT/$ACTIVATION_RELATIVE"
  require_regular_no_link "$SOURCE_ROOT/api_server.py" "API entrypoint"
  require_regular_no_link "$SOURCE_ROOT/$WRAPPER_RELATIVE" "V1-only API entrypoint"
  require_regular_no_link "$SOURCE_ROOT/$INIT_RELATIVE" "provider-native store initializer"
  require_regular_no_link "$SOURCE_ROOT/$SCHEDULE_RELATIVE" "provider-native schedule"
  require_regular_no_link "$SOURCE_ROOT/$SCHEDULE_RUNNER_RELATIVE" "provider-native schedule runner"
  require_regular_no_link "$SOURCE_ROOT/$PROBE_RELATIVE" "provider-native strict probe"
}


build_release() {
  local commit="$1" final staging tree relative rc
  final="${RELEASES_DIR}/${commit}"
  if [ -e "$final" ] || [ -L "$final" ]; then
    validate_release "$final" "$commit"
    printf '%s' "$final"
    return 0
  fi
  mkdir -p -- "$RELEASES_DIR"
  [ -d "$RELEASES_DIR" ] && [ ! -L "$RELEASES_DIR" ] \
    || die "release directory is unsafe"
  staging="$(mktemp -d "${RELEASES_DIR}/.staging.${commit}.XXXXXX")"
  set +e
  (
    set -Eeuo pipefail
    git -C "$SOURCE_ROOT" archive "$commit" | tar -x -C "$staging"
    if find "$staging" -type l -print -quit | grep -q .; then
      die "release archive contains a link"
    fi
    tree="$(git -C "$SOURCE_ROOT" rev-parse "${commit}^{tree}")"
    : >"$staging/$SUMS_NAME"
    while IFS= read -r -d '' relative; do
      require_regular_no_link "$staging/$relative" "tracked release file"
      (
        cd "$staging"
        "$SHA256SUM" "./$relative"
      ) >>"$staging/$SUMS_NAME"
    done < <(git -C "$SOURCE_ROOT" ls-tree -r --name-only -z "$commit")
    LC_ALL=C sort -o "$staging/$SUMS_NAME" "$staging/$SUMS_NAME"
    cat >"$staging/$MANIFEST_NAME" <<EOF
MANIFEST_VERSION=1
COMMIT=${commit}
TREE=${tree}
PROFILE_SHA256=$("$SHA256SUM" "$staging/$PROFILE_RELATIVE" | awk '{print $1}')
UNIT_SHA256=$("$SHA256SUM" "$staging/$UNIT_RELATIVE" | awk '{print $1}')
REGISTRY_SHA256=$("$SHA256SUM" "$staging/$REGISTRY_RELATIVE" | awk '{print $1}')
ACTIVATION_SHA256=$("$SHA256SUM" "$staging/$ACTIVATION_RELATIVE" | awk '{print $1}')
API_SHA256=$("$SHA256SUM" "$staging/api_server.py" | awk '{print $1}')
WRAPPER_SHA256=$("$SHA256SUM" "$staging/$WRAPPER_RELATIVE" | awk '{print $1}')
INIT_SHA256=$("$SHA256SUM" "$staging/$INIT_RELATIVE" | awk '{print $1}')
SCHEDULE_SHA256=$("$SHA256SUM" "$staging/$SCHEDULE_RELATIVE" | awk '{print $1}')
SCHEDULE_RUNNER_SHA256=$("$SHA256SUM" "$staging/$SCHEDULE_RUNNER_RELATIVE" | awk '{print $1}')
PROBE_SHA256=$("$SHA256SUM" "$staging/$PROBE_RELATIVE" | awk '{print $1}')
COLLECT_SERVICE_SHA256=$("$SHA256SUM" "$staging/${UNIT_RELATIVES[1]}" | awk '{print $1}')
COLLECT_TIMER_SHA256=$("$SHA256SUM" "$staging/${UNIT_RELATIVES[2]}" | awk '{print $1}')
PROBE_SERVICE_SHA256=$("$SHA256SUM" "$staging/${UNIT_RELATIVES[3]}" | awk '{print $1}')
PROBE_TIMER_SHA256=$("$SHA256SUM" "$staging/${UNIT_RELATIVES[4]}" | awk '{print $1}')
EOF
    chmod 0444 "$staging/$MANIFEST_NAME" "$staging/$SUMS_NAME"
    find "$staging" -type d -exec chmod a-w,ugo+rx {} +
    find "$staging" -type f -exec chmod a-w,ugo+r {} +
    move_directory_no_target "$staging" "$final"
  )
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    chmod -R u+w -- "$staging" 2>/dev/null || true
    rm -rf -- "$staging"
    die "release build failed"
  fi
  validate_release "$final" "$commit"
  printf '%s' "$final"
}


validate_release() {
  local release_path="$1" expected_commit="$2" canonical manifest observed path mode
  [ -d "$release_path" ] && [ ! -L "$release_path" ] \
    || die "release path must be a non-link directory"
  canonical="$(canonical_existing_path "$release_path")"
  [ "$canonical" = "$release_path" ] || die "release path is not canonical"
  [ "$(dirname "$release_path")" = "$RELEASES_DIR" ] \
    || die "release path is outside the release directory"
  [ "$(basename "$release_path")" = "$expected_commit" ] \
    || die "release directory does not match its commit"
  if find "$release_path" -type l -print -quit | grep -q .; then
    die "release contains a link"
  fi
  while IFS= read -r -d '' path; do
    mode="$(stat_mode "$path")"
    if (( (8#$mode & 0222) != 0 )); then
      die "release contains a writable artifact"
    fi
  done < <(find "$release_path" -print0)
  manifest="$release_path/$MANIFEST_NAME"
  require_regular_no_link "$manifest" "release manifest"
  require_regular_no_link "$release_path/$SUMS_NAME" "release checksums"
  [ "$(manifest_value "$manifest" MANIFEST_VERSION)" = "1" ] \
    || die "release manifest version is invalid"
  [ "$(manifest_value "$manifest" COMMIT)" = "$expected_commit" ] \
    || die "release manifest commit is invalid"
  (
    cd "$release_path"
    "$SHA256SUM" -c "$SUMS_NAME" >/dev/null 2>&1
  ) || die "release manifest validation failed"
  for pair in \
    "PROFILE_SHA256:$PROFILE_RELATIVE" \
    "UNIT_SHA256:$UNIT_RELATIVE" \
    "REGISTRY_SHA256:$REGISTRY_RELATIVE" \
    "ACTIVATION_SHA256:$ACTIVATION_RELATIVE" \
    "API_SHA256:api_server.py" \
    "WRAPPER_SHA256:$WRAPPER_RELATIVE" \
    "INIT_SHA256:$INIT_RELATIVE" \
    "SCHEDULE_SHA256:$SCHEDULE_RELATIVE" \
    "SCHEDULE_RUNNER_SHA256:$SCHEDULE_RUNNER_RELATIVE" \
    "PROBE_SHA256:$PROBE_RELATIVE" \
    "COLLECT_SERVICE_SHA256:${UNIT_RELATIVES[1]}" \
    "COLLECT_TIMER_SHA256:${UNIT_RELATIVES[2]}" \
    "PROBE_SERVICE_SHA256:${UNIT_RELATIVES[3]}" \
    "PROBE_TIMER_SHA256:${UNIT_RELATIVES[4]}"; do
    observed="$("$SHA256SUM" "$release_path/${pair#*:}" | awk '{print $1}')"
    [ "$observed" = "$(manifest_value "$manifest" "${pair%%:*}")" ] \
      || die "release manifest validation failed"
  done
  validate_profile "$release_path/$PROFILE_RELATIVE"
  validate_all_unit_sources "$release_path"
  validate_activation_registry_pair \
    "$release_path" \
    "$release_path/$REGISTRY_RELATIVE" \
    "$release_path/$ACTIVATION_RELATIVE"
}


require_current_pointer_shape_optional() {
  if [ ! -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ]; then
    return 0
  fi
  [ -L "$CURRENT_LINK" ] || die "current release pointer must be a symbolic link"
}


validate_current_pointer_optional() {
  local current commit
  require_current_pointer_shape_optional
  if [ ! -L "$CURRENT_LINK" ]; then
    return 0
  fi
  current="$(canonical_existing_path "$CURRENT_LINK")"
  commit="$(basename "$current")"
  validate_release "$current" "$commit"
}


runtime_store_presence() {
  local count=0 path
  for path in "$DATABASE" "$DATABASE_LOCK" "$MAINTENANCE_LOCK"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      count=$((count + 1))
    fi
  done
  case "$count" in
    0) printf '%s' absent ;;
    3) printf '%s' complete ;;
    *) die "provider-native runtime store is partially initialized" ;;
  esac
}


require_runtime_store_complete() {
  [ "$(runtime_store_presence)" = "complete" ] \
    || die "provider-native runtime store requires explicit init-store"
  validate_runtime_store
}


validate_runtime_store() {
  local service_uid path mode owner database_identity legacy_identity
  service_uid="$(id -u marketgraph 2>/dev/null)" \
    || die "marketgraph service account is unavailable"
  for path in "$DATABASE" "$DATABASE_LOCK" "$MAINTENANCE_LOCK"; do
    require_regular_no_link "$path" "provider-native runtime artifact"
    mode="$(stat_mode "$path")"
    owner="$(stat_uid "$path")"
    [ "$mode" = "600" ] || die "provider-native runtime artifacts must use mode 0600"
    [ "$owner" = "$service_uid" ] \
      || die "provider-native runtime artifacts must belong to the service account"
  done
  require_regular_no_link "$LEGACY_DATABASE" "legacy database"
  database_identity="$(stat_identity "$DATABASE")"
  legacy_identity="$(stat_identity "$LEGACY_DATABASE")"
  [ "$database_identity" != "$legacy_identity" ] \
    || die "provider-native database aliases the legacy database"
  "$VENV_PYTHON" - "$DATABASE" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve(strict=True)
conn = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
try:
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise SystemExit(78)
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not {"provider_dataset_rows", "market_ingest_runs"}.issubset(tables):
        raise SystemExit(78)
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    required = {
        "provider_dataset_rows_partition_idx",
        "provider_dataset_rows_observed_idx",
        "provider_dataset_rows_quality_idx",
        "provider_dataset_rows_receipt_idx",
    }
    if not required.issubset(indexes):
        raise SystemExit(78)
finally:
    conn.close()
PY
}


service_state() {
  local output
  set +e
  output="$("$SYSTEMCTL" "$1" "$2" 2>/dev/null)"
  set -e
  output="$(printf '%s' "$output" | tr -d '\r\n')"
  if [[ "$output" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    printf '%s' "$output"
  else
    printf '%s' "unknown"
  fi
}


service_load_state() {
  local output
  output="$("$SYSTEMCTL" show -p LoadState --value "$1" 2>/dev/null || true)"
  output="$(printf '%s' "$output" | tr -d '\r\n')"
  if [[ "$output" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
    printf '%s' "$output"
  else
    printf '%s' unknown
  fi
}


service_main_pid() {
  local pid
  pid="$("$SYSTEMCTL" show -p MainPID --value "$1" 2>/dev/null)" \
    || die "service main PID is unavailable"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "service main PID is invalid"
  printf '%s' "$pid"
}


legacy_listener_sha256() {
  local output
  require_command "$SS"
  require_command "$SHA256SUM"
  output="$("$SS" -H -ltnp "sport = :${LEGACY_PORT}" 2>/dev/null)" \
    || die "legacy listener identity is unavailable"
  [ "$(printf '%s\n' "$output" | sed '/^$/d' | wc -l | tr -d ' ')" = "1" ] \
    || die "legacy listener identity is ambiguous"
  printf '%s\n' "$output" | "$SHA256SUM" | awk '{print $1}'
}


capture_legacy_identity() {
  local target="$1" temporary active enabled main_pid
  require_regular_no_link "$LEGACY_DATABASE" "legacy database"
  active="$(service_state is-active "$LEGACY_SERVICE")"
  enabled="$(service_state is-enabled "$LEGACY_SERVICE")"
  [ "$active" != "unknown" ] && [ "$enabled" != "unknown" ] \
    || die "legacy service state is unavailable"
  main_pid="$(service_main_pid "$LEGACY_SERVICE")"
  temporary="${target}.tmp.$$"
  ( umask 077; : >"$temporary" )
  cat >"$temporary" <<EOF
LEGACY_DATABASE_FINGERPRINT=$(stat_fingerprint "$LEGACY_DATABASE")
LEGACY_SERVICE_ACTIVE=${active}
LEGACY_SERVICE_ENABLED=${enabled}
LEGACY_SERVICE_MAIN_PID=${main_pid}
LEGACY_LISTENER_SHA256=$(legacy_listener_sha256)
EOF
  chmod 0600 "$temporary"
  mv -f -- "$temporary" "$target"
}


state_value() {
  local state="$1" key="$2" line
  require_regular_no_link "$state" "release state"
  line="$(grep -E "^${key}=[A-Za-z0-9_./:-]+$" "$state" || true)"
  [ -n "$line" ] || die "release state is missing ${key}"
  [ "$(printf '%s\n' "$line" | wc -l | tr -d ' ')" = "1" ] \
    || die "release state duplicates ${key}"
  printf '%s' "${line#*=}"
}


assert_legacy_identity() {
  local state="$1"
  require_regular_no_link "$LEGACY_DATABASE" "legacy database"
  [ "$(stat_fingerprint "$LEGACY_DATABASE")" = \
    "$(state_value "$state" LEGACY_DATABASE_FINGERPRINT)" ] \
    || die "legacy database fingerprint changed"
  [ "$(service_state is-active "$LEGACY_SERVICE")" = \
    "$(state_value "$state" LEGACY_SERVICE_ACTIVE)" ] \
    || die "legacy service active state changed"
  [ "$(service_state is-enabled "$LEGACY_SERVICE")" = \
    "$(state_value "$state" LEGACY_SERVICE_ENABLED)" ] \
    || die "legacy service enablement changed"
  [ "$(service_main_pid "$LEGACY_SERVICE")" = \
    "$(state_value "$state" LEGACY_SERVICE_MAIN_PID)" ] \
    || die "legacy service main PID changed"
  [ "$(legacy_listener_sha256)" = \
    "$(state_value "$state" LEGACY_LISTENER_SHA256)" ] \
    || die "legacy listener identity changed"
}


assert_internal_pid_not_holding_legacy_database() {
  local pid legacy_identity fd observed found=0
  pid="$(service_main_pid "$SERVICE")"
  legacy_identity="$(stat_identity "$LEGACY_DATABASE")"
  [ -d "/proc/${pid}/fd" ] || die "internal process FD table is unavailable"
  for fd in "/proc/${pid}/fd/"*; do
    [ -e "$fd" ] || continue
    found=1
    observed="$(stat_identity "$fd" 2>/dev/null || true)"
    [ "$observed" != "$legacy_identity" ] \
      || die "internal unit holds the legacy database"
  done
  [ "$found" = "1" ] || die "internal process FD table is empty"
}


require_port_idle_or_owned() {
  local output
  require_command "$SS"
  output="$("$SS" -H -ltnp "sport = :${PORT}" 2>/dev/null)" \
    || die "loopback port ${PORT} state is unavailable"
  if [ -z "$(printf '%s\n' "$output" | sed '/^$/d')" ]; then
    return 0
  fi
  [ "$(service_state is-active "$SERVICE")" = "active" ] \
    || die "loopback port ${PORT} is owned by an unrelated process"
  require_unit_listener
}


require_port_idle() {
  local output
  require_command "$SS"
  output="$("$SS" -H -ltnp "sport = :${PORT}" 2>/dev/null)" \
    || die "loopback port ${PORT} state is unavailable"
  [ -z "$(printf '%s\n' "$output" | sed '/^$/d')" ] \
    || die "loopback port ${PORT} must be idle"
}


installed_unit_target() {
  local name="$1"
  printf '%s/%s' "$UNIT_DIR" "$name"
}


installed_lane_presence() {
  local count=0 name target
  for name in "${UNIT_NAMES[@]}"; do
    target="$(installed_unit_target "$name")"
    if [ -e "$target" ] || [ -L "$target" ]; then
      count=$((count + 1))
    fi
  done
  case "$count" in
    0) printf '%s' absent ;;
    5) printf '%s' complete ;;
    *) die "internal systemd lane is partially installed" ;;
  esac
}


assert_no_absent_lane_residue() {
  local name active enabled load link
  for name in "${UNIT_NAMES[@]}"; do
    active="$(service_state is-active "$name")"
    enabled="$(service_state is-enabled "$name")"
    load="$(service_load_state "$name")"
    [ "$active" = "inactive" ] \
      || die "absent internal unit has residual active state"
    [[ "$enabled" =~ ^(disabled|not-found)$ ]] \
      || die "absent internal unit has residual enablement"
    [ "$load" = "not-found" ] \
      || die "absent internal unit remains loaded"
    while IFS= read -r -d '' link; do
      die "absent internal unit has a residual dependency link"
    done < <(find "$UNIT_DIR" -type l -name "$name" -print0 2>/dev/null)
  done
}


validate_installed_lane_binding() {
  local lane="$1" current commit
  case "$lane" in
    absent)
      [ ! -e "$CURRENT_LINK" ] && [ ! -L "$CURRENT_LINK" ] \
        || die "absent internal lane retains a current release pointer"
      assert_no_absent_lane_residue
      ;;
    complete)
      [ -L "$CURRENT_LINK" ] \
        || die "installed internal lane has no current release pointer"
      current="$(canonical_existing_path "$CURRENT_LINK")"
      commit="$(manifest_value "$current/$MANIFEST_NAME" COMMIT)"
      validate_release "$current" "$commit"
      assert_installed_units_match_release "$current"
      ;;
    *) die "internal lane presence is invalid" ;;
  esac
}


atomic_current_switch() {
  local target="$1" temporary
  validate_release "$target" "$(basename "$target")"
  require_current_pointer_shape_optional
  mkdir -p -- "$(dirname "$CURRENT_LINK")"
  temporary="${CURRENT_LINK}.next.$$"
  rm -f -- "$temporary"
  ln -s -- "$target" "$temporary"
  mv -Tf -- "$temporary" "$CURRENT_LINK"
}


install_unit_atomically() {
  local source="$1" target="${2:-$UNIT_TARGET}" temporary
  require_regular_no_link "$source" "internal unit source"
  [ "$(dirname "$target")" = "$UNIT_DIR" ] \
    || die "installed unit target is outside the systemd directory"
  temporary="${target}.next.$$"
  rm -f -- "$temporary"
  install -o root -g root -m 0644 "$source" "$temporary"
  mv -Tf -- "$temporary" "$target"
}


install_all_units() {
  local release_path="$1" index target
  for index in 0 1 2 3 4; do
    target="$(installed_unit_target "${UNIT_NAMES[$index]}")"
    install_unit_atomically "$release_path/${UNIT_RELATIVES[$index]}" "$target"
  done
}


preflight() {
  local expected_commit="$1" store_state lane_state
  require_command "$SYSTEMCTL"
  require_command "$VENV_PYTHON"
  require_command "$SHA256SUM"
  validate_source "$expected_commit"
  validate_all_secret_envs
  store_state="$(runtime_store_presence)"
  if [ "$store_state" = "complete" ]; then
    validate_runtime_store
  fi
  require_regular_no_link "$LEGACY_DATABASE" "legacy database"
  validate_current_pointer_optional
  lane_state="$(installed_lane_presence)"
  if [ "$lane_state" = "complete" ]; then
    local name target
    for name in "${UNIT_NAMES[@]}"; do
      target="$(installed_unit_target "$name")"
      require_regular_no_link "$target" "installed internal unit"
    done
  fi
  validate_installed_lane_binding "$lane_state"
  require_port_idle_or_owned
  printf '%s\n' \
    "release_decision=proceed" \
    "approved_commit=${expected_commit}" \
    "runtime_store_presence=${store_state}" \
    "installed_lane_presence=${lane_state}" \
    "ops_activation=blocked" \
    "service=${SERVICE}" \
    "endpoint=127.0.0.1:${PORT}" \
    "database=${DATABASE}" \
    "legacy_service_untouched=${LEGACY_SERVICE}" \
    "legacy_database_untouched=${LEGACY_DATABASE}"
}


read_token_from_fd() {
  local descriptor="${SHAREDSIGNALS_V1_READBACK_TOKEN_FD:-}" token
  [[ "$descriptor" =~ ^[0-9]+$ ]] \
    && [ "$descriptor" -ge 3 ] && [ "$descriptor" -le 1023 ] \
    || die "authenticated readback token FD is invalid"
  IFS= read -r token <&"$descriptor" \
    || die "authenticated readback token is unavailable"
  [[ "$token" =~ ^[A-Za-z0-9._~-]{20,4096}$ ]] \
    || die "authenticated readback token is invalid"
  printf '%s' "$token"
}


require_unit_listener() {
  local pid output
  pid="$("$SYSTEMCTL" show -p MainPID --value "$SERVICE")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "internal unit has no main PID"
  output="$("$SS" -H -ltnp "sport = :${PORT}" 2>/dev/null)"
  [ "$(printf '%s\n' "$output" | sed '/^$/d' | wc -l | tr -d ' ')" = "1" ] \
    || die "internal unit must own exactly one listener"
  printf '%s' "$output" | grep -F "127.0.0.1:${PORT}" >/dev/null \
    || die "internal listener is not loopback-only"
  printf '%s' "$output" | grep -F "pid=${pid}," >/dev/null \
    || die "loopback listener does not belong to the internal unit"
}


assert_installed_units_match_release() {
  local release="$1" index target observed expected
  for index in 0 1 2 3 4; do
    target="$(installed_unit_target "${UNIT_NAMES[$index]}")"
    require_regular_no_link "$target" "installed internal unit"
    observed="$("$SHA256SUM" "$target" | awk '{print $1}')"
    expected="$("$SHA256SUM" "$release/${UNIT_RELATIVES[$index]}" | awk '{print $1}')"
    [ "$observed" = "$expected" ] || die "installed internal unit bytes drifted"
  done
}


readback() {
  local state="${1:-${STATE_DIR}/last.env}" current release_commit token
  local unauth_code auth_code legacy_code invalid_method_code
  [ -L "$CURRENT_LINK" ] || die "current release pointer is unavailable"
  current="$(canonical_existing_path "$CURRENT_LINK")"
  release_commit="$(manifest_value "$current/$MANIFEST_NAME" COMMIT)"
  validate_release "$current" "$release_commit"
  require_runtime_store_complete
  assert_installed_units_match_release "$current"
  [ "$(service_state is-active "$SERVICE")" = "active" ] \
    || die "internal unit is not active"
  [ "$(service_state is-enabled "$SERVICE")" = "enabled" ] \
    || die "internal unit is not enabled"
  require_unit_listener
  assert_internal_pid_not_holding_legacy_database
  unauth_code="$("$CURL" --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --max-time 10 \
    "http://127.0.0.1:${PORT}/v1/catalog")"
  [ "$unauth_code" = "401" ] || die "unauthenticated catalog did not fail closed"
  token="$(read_token_from_fd)"
  auth_code="$({
    printf 'header = "Authorization: Bearer %s"\n' "$token"
  } | "$CURL" --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --max-time 15 --config - "http://127.0.0.1:${PORT}/v1/catalog")"
  unset token
  [ "$auth_code" = "200" ] || die "authenticated catalog readback failed"
  legacy_code="$("$CURL" --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --max-time 10 \
    "http://127.0.0.1:${PORT}/health")"
  [ "$legacy_code" = "404" ] || die "legacy HTTP route is exposed on the V1 lane"
  invalid_method_code="$("$CURL" --silent --show-error --output /dev/null \
    --request DELETE --write-out '%{http_code}' --max-time 10 \
    "http://127.0.0.1:${PORT}/v1/catalog")"
  [ "$invalid_method_code" = "405" ] \
    || die "invalid V1 method did not fail closed"
  require_regular_no_link "$state" "release state"
  assert_legacy_identity "$state"
  printf '%s\n' \
    "readback=pass" \
    "commit=${release_commit}" \
    "listener=127.0.0.1:${PORT}" \
    "unauthenticated_catalog=401" \
    "authenticated_catalog=200" \
    "legacy_route=404" \
    "invalid_method=405"
}


capture_release_state() {
  local state="$1" activation="$2" activated_release="$3"
  local index name target backup active enabled sha
  capture_legacy_identity "$state"
  if [ -L "$CURRENT_LINK" ]; then
    printf 'PREVIOUS_RELEASE=%s\nPREVIOUS_RELEASE_PRESENT=1\n' \
      "$(canonical_existing_path "$CURRENT_LINK")" >>"$state"
  else
    printf 'PREVIOUS_RELEASE=none\nPREVIOUS_RELEASE_PRESENT=0\n' >>"$state"
  fi
  printf 'PREVIOUS_LANE_PRESENCE=%s\n' "$(installed_lane_presence)" >>"$state"
  for index in 0 1 2 3 4; do
    name="${UNIT_NAMES[$index]}"
    target="$(installed_unit_target "$name")"
    printf 'UNIT_%s_NAME=%s\n' "$index" "$name" >>"$state"
    if [ -f "$target" ] && [ ! -L "$target" ]; then
      backup="${EVIDENCE_DIR}/${activation}.${name}.before"
      install -o root -g root -m 0600 "$target" "$backup"
      sha="$("$SHA256SUM" "$backup" | awk '{print $1}')"
      active="$(service_state is-active "$name")"
      enabled="$(service_state is-enabled "$name")"
      [[ "$active" =~ ^(active|inactive)$ ]] \
        || die "previous unit active state is unsupported"
      [[ "$enabled" =~ ^(enabled|disabled|static|indirect)$ ]] \
        || die "previous unit enablement state is unsupported"
      printf 'UNIT_%s_PRESENT=1\nUNIT_%s_BACKUP=%s\nUNIT_%s_SHA256=%s\nUNIT_%s_ACTIVE=%s\nUNIT_%s_ENABLED=%s\n' \
        "$index" "$index" "$backup" "$index" "$sha" \
        "$index" "$active" "$index" "$enabled" >>"$state"
    else
      printf 'UNIT_%s_PRESENT=0\nUNIT_%s_BACKUP=none\nUNIT_%s_SHA256=none\nUNIT_%s_ACTIVE=inactive\nUNIT_%s_ENABLED=disabled\n' \
        "$index" "$index" "$index" "$index" "$index" >>"$state"
    fi
  done
  printf 'ACTIVATED_RELEASE=%s\n' "$activated_release" >>"$state"
  chmod 0600 "$state"
}


unit_is_loaded_or_present() {
  local name="$1" target load
  target="$(installed_unit_target "$name")"
  if [ -e "$target" ] || [ -L "$target" ]; then
    return 0
  fi
  load="$("$SYSTEMCTL" show -p LoadState --value "$name" 2>/dev/null || true)"
  [ "$load" != "not-found" ] && [ -n "$load" ]
}


stop_and_disable_lane_strict() {
  local name
  for name in "${TIMER_NAMES[@]}" "$SERVICE" "${ONESHOT_NAMES[@]}"; do
    if unit_is_loaded_or_present "$name"; then
      "$SYSTEMCTL" stop "$name" >/dev/null
    fi
  done
  for name in "${TIMER_NAMES[@]}" "$SERVICE"; do
    if unit_is_loaded_or_present "$name"; then
      "$SYSTEMCTL" disable "$name" >/dev/null
    fi
  done
}


restore_unit_state() {
  local name="$1" expected_active="$2" expected_enabled="$3" observed
  case "$expected_enabled" in
    enabled) "$SYSTEMCTL" enable "$name" >/dev/null ;;
    disabled) "$SYSTEMCTL" disable "$name" >/dev/null ;;
    static|indirect) : ;;
    *) die "previous unit enablement state is invalid" ;;
  esac
  case "$expected_active" in
    active) "$SYSTEMCTL" start "$name" >/dev/null ;;
    inactive) "$SYSTEMCTL" stop "$name" >/dev/null ;;
    *) die "previous unit active state is invalid" ;;
  esac
  observed="$(service_state is-enabled "$name")"
  [ "$observed" = "$expected_enabled" ] \
    || die "restored unit enablement does not match previous state"
  [ "$(service_state is-active "$name")" = "$expected_active" ] \
    || die "restored unit active state does not match previous state"
}


restore_from_state() {
  local state="$1" previous previous_present lane_presence index name target
  local present backup sha expected_active expected_enabled observed_sha
  previous="$(state_value "$state" PREVIOUS_RELEASE)"
  previous_present="$(state_value "$state" PREVIOUS_RELEASE_PRESENT)"
  lane_presence="$(state_value "$state" PREVIOUS_LANE_PRESENCE)"
  [[ "$previous_present" =~ ^[01]$ ]] \
    || die "previous release presence state is invalid"
  [[ "$lane_presence" =~ ^(absent|complete)$ ]] \
    || die "previous lane presence state is invalid"

  stop_and_disable_lane_strict
  if [ "$previous_present" = "1" ]; then
    validate_release "$previous" "$(basename "$previous")"
    atomic_current_switch "$previous"
  else
    require_current_pointer_shape_optional
    rm -f -- "$CURRENT_LINK"
  fi

  for index in 0 1 2 3 4; do
    name="$(state_value "$state" "UNIT_${index}_NAME")"
    [ "$name" = "${UNIT_NAMES[$index]}" ] || die "release state unit name is invalid"
    present="$(state_value "$state" "UNIT_${index}_PRESENT")"
    backup="$(state_value "$state" "UNIT_${index}_BACKUP")"
    sha="$(state_value "$state" "UNIT_${index}_SHA256")"
    target="$(installed_unit_target "$name")"
    case "$present" in
      1)
        require_regular_no_link "$backup" "previous unit backup"
        [ "$("$SHA256SUM" "$backup" | awk '{print $1}')" = "$sha" ] \
          || die "previous unit backup checksum changed"
        install_unit_atomically "$backup" "$target"
        ;;
      0) rm -f -- "$target" ;;
      *) die "previous unit presence state is invalid" ;;
    esac
  done
  "$SYSTEMCTL" daemon-reload

  for index in 0 1 2 3 4; do
    name="${UNIT_NAMES[$index]}"
    target="$(installed_unit_target "$name")"
    present="$(state_value "$state" "UNIT_${index}_PRESENT")"
    if [ "$present" = "1" ]; then
      sha="$(state_value "$state" "UNIT_${index}_SHA256")"
      observed_sha="$("$SHA256SUM" "$target" | awk '{print $1}')"
      [ "$observed_sha" = "$sha" ] || die "restored unit bytes changed"
      expected_active="$(state_value "$state" "UNIT_${index}_ACTIVE")"
      expected_enabled="$(state_value "$state" "UNIT_${index}_ENABLED")"
      restore_unit_state "$name" "$expected_active" "$expected_enabled"
    else
      [ ! -e "$target" ] && [ ! -L "$target" ] \
        || die "absent unit was not removed"
      [ "$(service_state is-active "$name")" != "active" ] \
        || die "absent unit remained active"
      [ "$(service_state is-enabled "$name")" != "enabled" ] \
        || die "absent unit remained enabled"
    fi
  done
  if [ "$lane_presence" = "absent" ]; then
    assert_no_absent_lane_residue
    require_port_idle
  elif [ "$(state_value "$state" UNIT_0_ACTIVE)" = "active" ]; then
    require_unit_listener
  fi
  assert_legacy_identity "$state"
}


handle_apply_error() {
  local primary_rc="$?" state="$1" rollback_rc
  trap - ERR
  set +e
  (
    set -Eeuo pipefail
    restore_from_state "$state"
  )
  rollback_rc=$?
  set -e
  if [ "$rollback_rc" -ne 0 ]; then
    printf '[ERROR] apply failed with rc=%s and automatic rollback failed with rc=%s\n' \
      "$primary_rc" "$rollback_rc" >&2
    exit 79
  fi
  printf '[ERROR] apply failed with rc=%s; automatic rollback completed\n' \
    "$primary_rc" >&2
  exit "$primary_rc"
}


prepare_release_directories() {
  local parent path
  parent="$(dirname "$RELEASE_BASE")"
  [ -d "$parent" ] && [ ! -L "$parent" ] \
    && [ "$(canonical_existing_path "$parent")" = "$parent" ] \
    && [ "$(stat_uid "$parent")" = "0" ] \
    || die "release parent directory is unsafe"
  for path in "$RELEASE_BASE" "$RELEASES_DIR" "$STATE_DIR" "$EVIDENCE_DIR"; do
    [ ! -L "$path" ] || die "release control directory is a link"
  done
  if [ ! -e "$RELEASE_BASE" ]; then
    install -d -o root -g root -m 0755 "$RELEASE_BASE"
  else
    [ -d "$RELEASE_BASE" ] \
      && [ "$(canonical_existing_path "$RELEASE_BASE")" = "$RELEASE_BASE" ] \
      && [ "$(stat_uid "$RELEASE_BASE")" = "0" ] \
      || die "release base directory is unsafe"
  fi
  for path in "$RELEASES_DIR" "$STATE_DIR" "$EVIDENCE_DIR"; do
    if [ ! -e "$path" ]; then
      install -d -o root -g root -m 0700 "$path"
    else
      [ -d "$path" ] && [ "$(canonical_existing_path "$path")" = "$path" ] \
        && [ "$(stat_uid "$path")" = "0" ] \
        || die "release control directory is unsafe"
    fi
  done
  chmod 0755 "$RELEASE_BASE" "$RELEASES_DIR"
  chmod 0700 "$STATE_DIR" "$EVIDENCE_DIR"
  for path in "$RELEASE_BASE" "$RELEASES_DIR" "$STATE_DIR" "$EVIDENCE_DIR"; do
    [ -d "$path" ] && [ ! -L "$path" ] \
      && [ "$(canonical_existing_path "$path")" = "$path" ] \
      && [ "$(stat_uid "$path")" = "0" ] \
      || die "release control directory is unsafe"
  done
}


prepare_runtime_directory() {
  local path="$1" service_uid service_gid
  service_uid="$(id -u marketgraph 2>/dev/null)" \
    || die "marketgraph service account is unavailable"
  service_gid="$(id -g marketgraph 2>/dev/null)" \
    || die "marketgraph service group is unavailable"
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    install -d -o "$service_uid" -g "$service_gid" -m 0700 "$path"
  fi
  [ -d "$path" ] && [ ! -L "$path" ] \
    || die "runtime directory is unsafe"
  [ "$(canonical_existing_path "$path")" = "$path" ] \
    || die "runtime directory is not canonical"
  [ "$(stat_uid "$path")" = "$service_uid" ] \
    && [ "$(stat_mode "$path")" = "700" ] \
    || die "runtime directory ownership or mode is invalid"
}


prepare_runtime_directories() {
  local root
  root="$(dirname "$(dirname "$DATABASE")")"
  prepare_runtime_directory "$root"
  prepare_runtime_directory "$(dirname "$DATABASE")"
  prepare_runtime_directory "$(dirname "$MAINTENANCE_LOCK")"
}


new_activation_id() {
  local commit="$1"
  printf '%s-%s-%s' "$(date -u +%Y%m%dT%H%M%S.%NZ)" "$$" "$commit"
}


publish_last_state() {
  local state="$1" temporary
  temporary="${STATE_DIR}/last.env.next.$$"
  cp -p "$state" "$temporary"
  mv -f -- "$temporary" "${STATE_DIR}/last.env"
}


init_store_release() {
  local expected_commit="$1" release_path activation state output
  [ "$EUID" -eq 0 ] || die "init-store requires root"
  mkdir -p -- "$(dirname "$RELEASE_LOCK")"
  exec 9>"$RELEASE_LOCK"
  flock -n 9 || die "another internal release operation is active"
  preflight "$expected_commit"
  [ "$(runtime_store_presence)" = "absent" ] \
    || die "init-store requires an entirely absent provider-native store"
  prepare_release_directories
  release_path="$(build_release "$expected_commit")"
  validate_release "$release_path" "$expected_commit"
  activation="$(new_activation_id "$expected_commit")"
  state="${EVIDENCE_DIR}/${activation}.init.env"
  capture_legacy_identity "$state"
  printf 'INITIALIZER_RELEASE=%s\nINITIALIZER_SHA256=%s\n' \
    "$release_path" \
    "$("$SHA256SUM" "$release_path/$INIT_RELATIVE" | awk '{print $1}')" >>"$state"
  chmod 0600 "$state"
  prepare_runtime_directories
  output="$(PYTHONPATH="$release_path" "$VENV_PYTHON" "$release_path/tools/init_provider_native_store.py")" \
    || die "provider-native store initialization failed"
  unset output
  require_runtime_store_complete
  assert_legacy_identity "$state"
  printf '%s\n' \
    "init_store=pass" \
    "approved_commit=${expected_commit}" \
    "runtime_store_presence=complete" \
    "evidence=${state}"
}


assert_ops_disabled_after_apply() {
  local name
  for name in "${TIMER_NAMES[@]}"; do
    [ "$(service_state is-active "$name")" != "active" ] \
      || die "operations timer must remain inactive before enable-ops"
    [ "$(service_state is-enabled "$name")" != "enabled" ] \
      || die "operations timer must remain disabled before enable-ops"
  done
  for name in "${ONESHOT_NAMES[@]}"; do
    [ "$(service_state is-active "$name")" != "active" ] \
      || die "operations oneshot must be inactive outside a bounded run"
  done
}


apply_release() {
  local expected_commit="$1" release_path activation state lane_state
  [ "$EUID" -eq 0 ] || die "apply requires root"
  mkdir -p -- "$(dirname "$RELEASE_LOCK")"
  exec 9>"$RELEASE_LOCK"
  flock -n 9 || die "another internal release operation is active"
  preflight "$expected_commit"
  require_runtime_store_complete
  prepare_release_directories
  release_path="$(build_release "$expected_commit")"
  validate_release "$release_path" "$expected_commit"
  activation="$(new_activation_id "$expected_commit")"
  state="${EVIDENCE_DIR}/${activation}.env"
  capture_release_state "$state" "$activation" "$release_path"
  publish_last_state "$state"

  trap 'handle_apply_error "$state"' ERR
  lane_state="$(installed_lane_presence)"
  if [ "$lane_state" = "complete" ]; then
    stop_and_disable_lane_strict
  fi
  install_all_units "$release_path"
  atomic_current_switch "$release_path"
  "$SYSTEMCTL" daemon-reload
  "$SYSTEMCTL" disable --now "${TIMER_NAMES[@]}" >/dev/null
  "$SYSTEMCTL" stop "${ONESHOT_NAMES[@]}" >/dev/null
  "$SYSTEMCTL" enable "$SERVICE" >/dev/null
  "$SYSTEMCTL" restart "$SERVICE"
  readback "$state"
  assert_ops_disabled_after_apply
  trap - ERR
  printf '%s\n' \
    "apply=pass" \
    "release=${release_path}" \
    "ops_activation=blocked" \
    "evidence=${state}"
}


require_oneshot_success() {
  local name="$1" result status
  result="$("$SYSTEMCTL" show -p Result --value "$name" 2>/dev/null)" \
    || die "operations oneshot result is unavailable"
  status="$("$SYSTEMCTL" show -p ExecMainStatus --value "$name" 2>/dev/null)" \
    || die "operations oneshot exit status is unavailable"
  [ "$result" = "success" ] && [ "$status" = "0" ] \
    || die "operations oneshot failed"
  [ "$(service_state is-active "$name")" != "active" ] \
    || die "operations oneshot did not return inactive"
}


verify_expected_facts_and_receipts() {
  local current
  current="$(canonical_existing_path "$CURRENT_LINK")"
  PYTHONPATH="$current" "$VENV_PYTHON" - \
    "$DATABASE" "$current/$REGISTRY_RELATIVE" "$current/$ACTIVATION_RELATIVE" <<'PY'
import sqlite3
import sys
from pathlib import Path
import json
import yaml

database = Path(sys.argv[1]).resolve(strict=True)
with Path(sys.argv[3]).open("r", encoding="utf-8") as handle:
    activation = yaml.safe_load(handle)
expected = sorted(
    row["dataset_id"]
    for row in activation["activations"]
    if row.get("activation_state") == "active"
    and row.get("entitlement_state") == "active"
)
if not expected or len(expected) != len(set(expected)):
    raise SystemExit(78)
conn = sqlite3.connect(f"{database.as_uri()}?mode=ro&immutable=1", uri=True)
try:
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise SystemExit(78)
    for dataset_id in expected:
        facts = conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()[0]
        receipt = conn.execute(
            """SELECT run_id, status, rows_read, rows_written, notes
               FROM market_ingest_runs WHERE source = ?
               ORDER BY finished_at DESC, run_id DESC LIMIT 1""",
            (dataset_id,),
        ).fetchone()
        if facts < 1 or receipt is None or receipt[1] != "success":
            raise SystemExit(78)
        receipt_id, _status, rows_read, rows_written, raw_notes = receipt
        try:
            notes = json.loads(raw_notes)
        except (TypeError, json.JSONDecodeError):
            raise SystemExit(78) from None
        counts = notes.get("counts") if type(notes) is dict else None
        if type(counts) is not dict:
            raise SystemExit(78)
        if (
            notes.get("receipt_id") != receipt_id
            or notes.get("dataset_id") != dataset_id
            or notes.get("status") != "success"
            or notes.get("target_table") != "provider_dataset_rows"
            or counts.get("returned") != rows_read
            or counts.get("committed") != rows_written
            or counts.get("committed")
            != counts.get("inserted", 0) + counts.get("updated", 0)
            or counts.get("returned")
            != counts.get("validated", 0) + counts.get("rejected", 0)
        ):
            raise SystemExit(78)
        linked_facts = conn.execute(
            """SELECT COUNT(*) FROM provider_dataset_rows
               WHERE dataset_id = ? AND receipt_id = ?""",
            (dataset_id, receipt_id),
        ).fetchone()[0]
        if linked_facts != rows_written:
            raise SystemExit(78)
finally:
    conn.close()
PY
}


handle_enable_ops_error() {
  local primary_rc="$?" cleanup_rc=0 name
  trap - ERR
  set +e
  for name in "${TIMER_NAMES[@]}"; do
    "$SYSTEMCTL" disable --now "$name" >/dev/null
    [ "$?" -eq 0 ] || cleanup_rc=1
  done
  set -e
  if [ "$cleanup_rc" -ne 0 ]; then
    printf '[ERROR] enable-ops failed with rc=%s and timer cleanup failed\n' \
      "$primary_rc" >&2
    exit 79
  fi
  printf '[ERROR] enable-ops failed with rc=%s; timers remain disabled\n' \
    "$primary_rc" >&2
  exit "$primary_rc"
}


enable_ops() {
  local expected_commit="$1" current commit state name
  [ "$EUID" -eq 0 ] || die "enable-ops requires root"
  exec 9>"$RELEASE_LOCK"
  flock -n 9 || die "another internal release operation is active"
  preflight "$expected_commit"
  require_runtime_store_complete
  current="$(canonical_existing_path "$CURRENT_LINK")"
  commit="$(manifest_value "$current/$MANIFEST_NAME" COMMIT)"
  [ "$commit" = "$expected_commit" ] \
    || die "active release does not match enable-ops approval"
  state="${STATE_DIR}/last.env"
  readback "$state"
  assert_ops_disabled_after_apply
  trap handle_enable_ops_error ERR
  "$SYSTEMCTL" start "${ONESHOT_NAMES[0]}" >/dev/null
  require_oneshot_success "${ONESHOT_NAMES[0]}"
  verify_expected_facts_and_receipts
  "$SYSTEMCTL" start "${ONESHOT_NAMES[1]}" >/dev/null
  require_oneshot_success "${ONESHOT_NAMES[1]}"
  for name in "${TIMER_NAMES[@]}"; do
    "$SYSTEMCTL" enable --now "$name" >/dev/null
    [ "$(service_state is-active "$name")" = "active" ] \
      || die "operations timer did not become active"
    [ "$(service_state is-enabled "$name")" = "enabled" ] \
      || die "operations timer did not become enabled"
  done
  assert_legacy_identity "$state"
  trap - ERR
  printf '%s\n' \
    "enable_ops=pass" \
    "approved_commit=${expected_commit}" \
    "ops_activation=enabled"
}


rollback_release() {
  local state="${STATE_DIR}/last.env"
  [ "$EUID" -eq 0 ] || die "rollback requires root"
  exec 9>"$RELEASE_LOCK"
  flock -n 9 || die "another internal release operation is active"
  require_regular_no_link "$state" "last release state"
  restore_from_state "$state"
  printf '%s\n' \
    "rollback=pass" \
    "database_preserved=${DATABASE}" \
    "evidence_preserved=${EVIDENCE_DIR}" \
    "releases_preserved=${RELEASES_DIR}"
}


serve() {
  local release_root current_root commit cursor_signing_key
  [ "${SHAREDSIGNALS_LOCALHOST_BYPASS:-}" = "0" ] \
    || die "localhost authentication bypass must remain disabled"
  [ "${SHAREDSIGNALS_API_HOST:-}" = "127.0.0.1" ] \
    || die "internal API must bind loopback"
  [ "${SHAREDSIGNALS_API_PORT:-}" = "$PORT" ] \
    || die "internal API port is invalid"
  [ "${SHAREDSIGNALS_API_SURFACE:-}" = "provider-native-v1-only" ] \
    || die "internal API surface is invalid"
  [ "${SHAREDSIGNALS_MARKETDATA_DB:-}" = "$DATABASE" ] \
    || die "internal API database path is invalid"
  [ "${SHAREDSIGNALS_DATASET_REGISTRY_PATH:-}" = "$CURRENT_LINK/$REGISTRY_RELATIVE" ] \
    || die "internal API registry path is invalid"
  current_root="$(canonical_existing_path "$CURRENT_LINK")"
  release_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  [ "$release_root" = "$current_root" ] \
    || die "service entrypoint is not the active current release"
  commit="$(manifest_value "$release_root/$MANIFEST_NAME" COMMIT)"
  validate_release "$release_root" "$commit"
  validate_runtime_store
  [ -n "${SHAREDSIGNALS_TOKEN_HASH_FILE:-}" ] \
    || die "token hash file configuration is unavailable"
  [ -n "${SHAREDSIGNALS_TOKEN_SALT:-}" ] \
    || die "token salt configuration is unavailable"
  cursor_signing_key="${SHAREDSIGNALS_CURSOR_SIGNING_KEY:-}"
  [ "${#cursor_signing_key}" -ge 32 ] \
    || die "cursor signing key configuration is unavailable"
  unset cursor_signing_key
  export SHAREDSIGNALS_ROOT="$release_root"
  export SHAREDSIGNALS_DATASET_REGISTRY_PATH="$release_root/$REGISTRY_RELATIVE"
  export SHAREDSIGNALS_LOCALHOST_BYPASS=0
  export REAL_TRADING_ENABLED=false
  export PYTHONPATH="$release_root"
  exec "$VENV_PYTHON" "$release_root/$WRAPPER_RELATIVE"
}


usage() {
  printf 'usage: %s {preflight|init-store|apply|enable-ops|readback|rollback|serve} [full-commit-sha]\n' "$0" >&2
  return 64
}


main() {
  local command="${1:-}"
  case "$command" in
    preflight)
      [ "$#" -eq 2 ] || usage
      preflight "$2"
      ;;
    init-store)
      [ "$#" -eq 2 ] || usage
      init_store_release "$2"
      ;;
    apply)
      [ "$#" -eq 2 ] || usage
      apply_release "$2"
      ;;
    enable-ops)
      [ "$#" -eq 2 ] || usage
      enable_ops "$2"
      ;;
    readback)
      [ "$#" -eq 1 ] || usage
      readback
      ;;
    rollback)
      [ "$#" -eq 1 ] || usage
      rollback_release
      ;;
    serve)
      [ "$#" -eq 1 ] || usage
      serve
      ;;
    *) usage ;;
  esac
}


if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
