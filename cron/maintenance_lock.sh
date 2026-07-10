#!/bin/bash
# Shared lock used by cron readers/writers while deploy or rollback is inactive.

acquire_sharedsignals_read_model_lock() {
  local root="$1"
  local log_file="$2"
  local lock_file="${SHAREDSIGNALS_MAINTENANCE_LOCK_FILE:-${root}/logs/locks/read_model_maintenance.lock}"

  mkdir -p "$(dirname "${lock_file}")"
  exec 199>"${lock_file}"
  if ! flock -s -n 199; then
    echo "[$(date -Iseconds)] SKIP SharedSignals read model maintenance active" >> "${log_file}"
    exit 0
  fi
}
