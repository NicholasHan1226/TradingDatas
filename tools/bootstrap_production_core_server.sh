#!/usr/bin/env bash
set -euo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
umask 077

fail() {
  printf 'bootstrap-production-core-server: %s\n' "$*" >&2
  exit 1
}

assert_root_controlled_dir() {
  local path="$1"
  [[ -d "$path" && ! -L "$path" ]] || fail "trusted runtime directory missing or symlinked: $path"
  [[ "$(stat -c '%U:%G' -- "$path")" == 'root:root' ]] || fail "trusted runtime directory must be root:root: $path"
  local mode
  mode="$(stat -c '%a' -- "$path")"
  (( (8#$mode & 0022) == 0 )) || fail "trusted runtime directory must not be group/other writable: $path"
}

[[ "$EUID" -eq 0 ]] || fail 'must run as root'
[[ $# -eq 1 ]] || fail 'usage: bootstrap_production_core_server.sh <deploy-user>'

deploy_user="$1"
[[ "$deploy_user" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || fail 'invalid deploy user'
id "$deploy_user" >/dev/null 2>&1 || fail "deploy user does not exist: $deploy_user"

shell="$(getent passwd "$deploy_user" | cut -d: -f7)"
case "$shell" in
  ''|*/nologin|*/false) fail "deploy user requires an SSH-capable shell: $shell" ;;
esac

deploy_group="$(id -gn "$deploy_user")"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_helper="$script_dir/production_core_release.py"
source_verifier="$script_dir/release_manifest.py"

installed_helper=/usr/local/sbin/tradingdatas-core-release
trusted_dir=/usr/local/lib/tradingdatas-release
installed_verifier="$trusted_dir/release_manifest.py"
spool=/var/tmp/tradingdatas-core-deploy
release_root=/opt/investment/releases/tradingdatas
manifests_root="$release_root/manifests"
sudoers_file=/etc/sudoers.d/tradingdatas-core-release
python_runtime=/opt/tradingdatas/venv/bin/python3
deploy_auth_dir=/etc/tradingdatas-deploy
deploy_auth_key="$deploy_auth_dir/core-release.hmac"

[[ -x "$python_runtime" ]] || fail "python runtime missing: $python_runtime"
for trusted_runtime_dir in /opt /opt/tradingdatas /opt/tradingdatas/venv /opt/tradingdatas/venv/bin; do
  assert_root_controlled_dir "$trusted_runtime_dir"
done
python_runtime_real="$(readlink -f -- "$python_runtime")"
[[ -n "$python_runtime_real" && -f "$python_runtime_real" && ! -L "$python_runtime_real" ]] \
  || fail "python runtime target missing or unsafe: $python_runtime_real"
[[ "$(stat -c '%U:%G' -- "$python_runtime_real")" == 'root:root' ]] \
  || fail "python runtime target must be root:root: $python_runtime_real"
python_runtime_mode="$(stat -c '%a' -- "$python_runtime_real")"
(( (8#$python_runtime_mode & 0022) == 0 )) \
  || fail "python runtime target must not be group/other writable: $python_runtime_real"

[[ -f "$source_helper" && ! -L "$source_helper" ]] || fail "helper source missing: $source_helper"
[[ -f "$source_verifier" && ! -L "$source_verifier" ]] || fail "verifier source missing: $source_verifier"
[[ "$(head -n 1 -- "$source_helper")" == "#!$python_runtime" ]] \
  || fail "helper shebang must exactly use trusted python runtime: $python_runtime"

[[ -d "$deploy_auth_dir" && ! -L "$deploy_auth_dir" ]] \
  || fail "deployment authorization directory is required: $deploy_auth_dir"
[[ "$(stat -c '%U:%G %a' -- "$deploy_auth_dir")" == 'root:root 700' ]] \
  || fail 'deployment authorization directory must be root:root mode 0700'
[[ -f "$deploy_auth_key" && ! -L "$deploy_auth_key" ]] \
  || fail "deployment authorization key is required: $deploy_auth_key"
[[ "$(stat -c '%U:%G %a %h' -- "$deploy_auth_key")" == 'root:root 400 1' ]] \
  || fail 'deployment authorization key must be root:root mode 0400 with one hard link'
[[ "$(stat -c '%s' -- "$deploy_auth_key")" == '65' ]] \
  || fail 'deployment authorization key must contain 64 lowercase hex characters plus newline'
IFS= read -r deploy_request_key < "$deploy_auth_key" || fail 'cannot read deployment authorization key'
[[ "$deploy_request_key" =~ ^[0-9a-f]{64}$ ]] \
  || fail 'deployment authorization key must contain one 256-bit lowercase hex key'
unset deploy_request_key

[[ -d "$release_root" && ! -L "$release_root" ]] || fail "release root missing or unsafe: $release_root"
[[ "$(stat -c '%U:%G' -- "$release_root")" == 'root:root' ]] || fail 'release root must be root:root'
release_root_mode="$(stat -c '%a' -- "$release_root")"
(( (8#$release_root_mode & 0022) == 0 )) || fail 'release root must not be group/other writable'

[[ -L "$release_root/current" ]] || fail 'current must already be a symlink'
current_target="$(readlink -- "$release_root/current")"
[[ "$current_target" =~ ^[0-9a-f]{40}$ ]] || fail 'current must be normalized to a relative 40-char commit before automation'
[[ -d "$release_root/$current_target" && ! -L "$release_root/$current_target" ]] || fail 'current immutable release target is missing'

[[ -d "$manifests_root" && ! -L "$manifests_root" ]] || fail "existing manifest directory is required: $manifests_root"
[[ "$(stat -c '%U:%G' -- "$manifests_root")" == 'root:root' ]] || fail 'manifest directory must be root:root'
manifests_root_mode="$(stat -c '%a' -- "$manifests_root")"
(( (8#$manifests_root_mode & 0022) == 0 )) || fail 'manifest directory must not be group/other writable'
current_manifest="$manifests_root/$current_target.json"
[[ -f "$current_manifest" && ! -L "$current_manifest" ]] || fail "current rollback manifest is required: $current_manifest"

# Validate the existing rollback authority with the approved checkout before
# installing any new privileged deployment trust boundary on the server.
"$python_runtime" "$source_verifier" verify-current \
  --releases-root "$release_root" \
  --manifest "$current_manifest" \
  --expected-uid 0 --expected-gid 0 >/dev/null

install -d -o root -g root -m 0755 "$trusted_dir"
install -o root -g root -m 0444 "$source_verifier" "$installed_verifier"
install -o root -g root -m 0755 "$source_helper" "$installed_helper"

# Read back the installed trusted verifier against the same current authority.
"$python_runtime" "$installed_verifier" verify-current \
  --releases-root "$release_root" \
  --manifest "$current_manifest" \
  --expected-uid 0 --expected-gid 0 >/dev/null

install -d -o "$deploy_user" -g "$deploy_group" -m 0700 "$spool"
spool_entry="$(find "$spool" -mindepth 1 -maxdepth 1 -print -quit)"
[[ -z "$spool_entry" ]] || fail "deployment spool is not empty: $spool_entry"

sudoers_tmp="$(mktemp /etc/sudoers.d/.tradingdatas-core-release.XXXXXX)"
cleanup() {
  rm -f -- "$sudoers_tmp"
}
trap cleanup EXIT
printf '%s ALL=(root) NOPASSWD: %s\n' "$deploy_user" "$installed_helper" > "$sudoers_tmp"
chmod 0440 "$sudoers_tmp"
visudo -cf "$sudoers_tmp" >/dev/null
mv -f -- "$sudoers_tmp" "$sudoers_file"
chmod 0440 "$sudoers_file"
chown root:root "$sudoers_file"
visudo -cf "$sudoers_file" >/dev/null
trap - EXIT

[[ "$(stat -c '%U:%G %a' -- "$installed_helper")" == 'root:root 755' ]] \
  || fail 'installed helper ownership/mode verification failed'
[[ "$(stat -c '%U:%G %a' -- "$installed_verifier")" == 'root:root 444' ]] \
  || fail 'installed verifier ownership/mode verification failed'
[[ "$(stat -c '%U %a' -- "$spool")" == "$deploy_user 700" ]] \
  || fail 'deployment spool ownership/mode verification failed'

printf 'TradingDatas core deployment bootstrap complete.\n'
printf 'deploy_user=%s\n' "$deploy_user"
printf 'current=%s\n' "$current_target"
printf 'python_runtime=%s\n' "$python_runtime_real"
printf 'helper_sha256=%s\n' "$(sha256sum "$installed_helper" | awk '{print $1}')"
printf 'verifier_sha256=%s\n' "$(sha256sum "$installed_verifier" | awk '{print $1}')"
printf 'Keep repository variable TRADINGDATAS_CORE_DEPLOY_ENABLED=false until GitHub secrets are configured.\n'
