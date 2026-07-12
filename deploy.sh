#!/bin/bash
# deploy.sh - SharedSignals deployment pipeline
# Backup (git tag + SQLite snapshot) -> pull -> migration -> smoke test -> switch (or rollback)
set -euo pipefail

REPO_DIR="/opt/investment/SharedSignals"
BACKUP_DIR="/opt/investment/SharedSignals/backups"
RUNTIME_DIR="${SHAREDSIGNALS_RUNTIME_ROOT:-/opt/investment/SharedSignals/runtime}"
SQLITE_DB="${SHAREDSIGNALS_MARKETDATA_DB:-${RUNTIME_DIR}/read_model/marketdata.sqlite}"
VENV_PYTHON="${SHAREDSIGNALS_VENV_PYTHON:-/opt/sharedsignals/venv/bin/python3}"
DEPLOY_LOCK_FILE="${SHAREDSIGNALS_DEPLOY_LOCK_FILE:-/var/lock/sharedsignals-deploy.lock}"
MAINTENANCE_LOCK_FILE="${SHAREDSIGNALS_MAINTENANCE_LOCK_FILE:-${REPO_DIR}/logs/locks/read_model_maintenance.lock}"
MAINTENANCE_LOCK_TIMEOUT="${SHAREDSIGNALS_MAINTENANCE_LOCK_TIMEOUT:-300}"
SQLITE_BACKUP_RETENTION="${SHAREDSIGNALS_SQLITE_BACKUP_RETENTION:-3}"
SMOKE_LOG_RETENTION="${SHAREDSIGNALS_SMOKE_LOG_RETENTION:-5}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TAG="deploy-${TIMESTAMP}"
LOG_FILE="${REPO_DIR}/logs/deploy_${TIMESTAMP}.log"
DEPLOYED_HEAD=""

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
success() { echo "[OK] $*" | tee -a "$LOG_FILE"; }
warn() { echo "[WARN] $*" | tee -a "$LOG_FILE"; }
error() { echo "[ERROR] $*" | tee -a "$LOG_FILE"; }

acquire_deploy_lock() {
    mkdir -p "$(dirname "$DEPLOY_LOCK_FILE")"
    exec 9>"$DEPLOY_LOCK_FILE"
    if ! flock -n 9; then
        error "Another SharedSignals deploy or rollback is active; refusing concurrent deployment"
        exit 75
    fi
    export SHAREDSIGNALS_DEPLOY_LOCK_HELD=1
}

acquire_maintenance_lock() {
    mkdir -p "$(dirname "$MAINTENANCE_LOCK_FILE")"
    touch "$MAINTENANCE_LOCK_FILE"
    chgrp marketgraph "$MAINTENANCE_LOCK_FILE" 2>/dev/null || true
    chmod 0660 "$MAINTENANCE_LOCK_FILE"
    exec 8>"$MAINTENANCE_LOCK_FILE"
    if ! flock -w "$MAINTENANCE_LOCK_TIMEOUT" 8; then
        error "Timed out waiting for SharedSignals read model jobs to finish"
        exit 76
    fi
    export SHAREDSIGNALS_MAINTENANCE_LOCK_HELD=1
}

backup_sqlite_database() {
    local source_path="$1"
    local target_path="$2"
    rm -f "$target_path"
    "$VENV_PYTHON" - "$source_path" "$target_path" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1:3]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
target = sqlite3.connect(target_path, timeout=30)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
PY
}

validate_sqlite_snapshot() {
    local path="$1"
    PYTHONPATH="${REPO_DIR}" "$VENV_PYTHON" - "$path" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists() or path.stat().st_size == 0:
    raise SystemExit("snapshot missing or empty")
conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
check = conn.execute("PRAGMA quick_check").fetchone()[0]
if check != "ok":
    raise SystemExit(f"quick_check failed: {check}")
for table in ("market_assets", "market_bars_daily"):
    rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if rows <= 0:
        raise SystemExit(f"{table} is empty")
conn.close()
PY
}

rollback_deploy() {
    error "DEPLOY FAILED - rolling back"
    if [ -f "${REPO_DIR}/rollback.sh" ]; then
        bash "${REPO_DIR}/rollback.sh" "$TAG" "$TIMESTAMP" "${DEPLOYED_HEAD:-}" || true
    else
        error "rollback.sh not found - manual recovery required"
    fi
    exit 1
}

acquire_deploy_lock
acquire_maintenance_lock
trap rollback_deploy ERR

log "=== SharedSignals Deploy ${TIMESTAMP} ==="

# ---- Phase 1: Backup ----
log "Phase 1: Backup"
cd "$REPO_DIR"
DEPLOYED_HEAD=$(git rev-parse HEAD)

# SQLite snapshot
DB_BACKUP=""
if [ -f "$SQLITE_DB" ]; then
    DB_BACKUP="${BACKUP_DIR}/marketdata_${TIMESTAMP}.sqlite"
    DB_BACKUP_TMP="${DB_BACKUP}.tmp"
    DB_SIZE=$(stat -c%s "$SQLITE_DB")
    DB_AVAIL=$(df -PB1 "$BACKUP_DIR" | awk 'NR==2 {print $4}')
    MIN_AVAIL=$((DB_SIZE + 2147483648))
    if [ "$DB_AVAIL" -lt "$MIN_AVAIL" ]; then
        error "Insufficient free space for a validated SQLite snapshot (need ${MIN_AVAIL} bytes, available ${DB_AVAIL}); refusing deployment before pull or migration"
        exit 77
    else
        rm -f "$DB_BACKUP_TMP"
        backup_sqlite_database "$SQLITE_DB" "$DB_BACKUP_TMP"
        validate_sqlite_snapshot "$DB_BACKUP_TMP"
        mv "$DB_BACKUP_TMP" "$DB_BACKUP"
        success "SQLite snapshot saved and validated"
    fi
else
    warn "No SQLite database at $SQLITE_DB - skipping snapshot"
fi

# Create the rollback tag only after a production database has a validated
# snapshot (or when this is a first install with no database yet).  A failed
# space gate must leave both code and database untouched.
git tag "$TAG"
success "Git tag: $TAG"

# Save current HEAD for rollback
git rev-parse HEAD > "${BACKUP_DIR}/pre_deploy_head_${TIMESTAMP}.txt"

# ---- Phase 2: Pull new code ----
log "Phase 2: Pull new code"
git fetch origin
CURRENT=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

if [ "$CURRENT" = "$REMOTE" ]; then
    warn "Already at latest - nothing to pull"
else
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null
    DEPLOYED_HEAD=$(git rev-parse HEAD)
    success "Pulled: $(git log --oneline -1)"
fi
DEPLOYED_HEAD=$(git rev-parse HEAD)

# ---- Phase 3: Install/update dependencies ----
log "Phase 3: Dependencies"
REQUIREMENTS="${REPO_DIR}/requirements.txt"
if [ -f "$REQUIREMENTS" ]; then
    $VENV_PYTHON -m pip install -r "$REQUIREMENTS" --quiet 2>&1 | tee -a "$LOG_FILE"
    success "Dependencies installed"
else
    log "No requirements.txt found - checking core packages"
    $VENV_PYTHON -m pip install duckdb pandas pyyaml requests --quiet 2>&1 | tee -a "$LOG_FILE"
    success "Core packages verified"
fi

# ---- Phase 4: Run migrations ----
log "Phase 4: Run migrations"
MIGRATION_SCRIPT="${REPO_DIR}/storage/migrate.py"
if [ -f "$MIGRATION_SCRIPT" ]; then
    $VENV_PYTHON "$MIGRATION_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    success "Migration complete"
else
    log "No migration script found - skipping"
fi

# ---- Phase 5: Smoke test ----
log "Phase 5: Smoke test"
TEST_LOG="${BACKUP_DIR}/smoke_${TIMESTAMP}.log"

# Run test suite
if $VENV_PYTHON -m pytest "${REPO_DIR}/tests/" -v --timeout=30 --tb=short 2>&1 | tee "$TEST_LOG"; then
    success "Tests passed"
else
    error "Tests FAILED - check $TEST_LOG"
    false  # trigger rollback
fi

# Verify key files exist
for f in "storage/schema.py" "bridge/marketgraph_marketdata_db.py" "reference/market_calendar.py"; do
    if [ ! -f "${REPO_DIR}/${f}" ]; then
        error "Missing critical file: $f"
        false
    fi
done

# Verify Python imports
if $VENV_PYTHON -c "
import sys
sys.path.insert(0, '${REPO_DIR}')
from storage.schema import SCHEMA_SQL
from reference.market_calendar import is_trading_day, clear_cache
print('Imports OK')
" 2>&1; then
    success "Critical imports verified"
else
    error "Import check FAILED"
    false
fi

# ---- Phase 6: Switch ----
log "Phase 6: Switch"

# Install the repository-owned service definition so the API cannot drift back
# to a sibling project's Python environment.
SERVICE_FILE="/etc/systemd/system/sharedsignals-api.service"
SERVICE_TEMPLATE="${REPO_DIR}/deploy/systemd/sharedsignals-api.service"
if [ ! -f "$SERVICE_TEMPLATE" ]; then
    error "Missing SharedSignals systemd service template"
    false
fi
sudo install -m 0644 "$SERVICE_TEMPLATE" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable sharedsignals-api >/dev/null 2>&1
sudo systemctl restart sharedsignals-api
success "SharedSignals-owned service installed and restarted"

# ---- Completion ----
log "=== Deploy ${TIMESTAMP} COMPLETE ==="
success "SharedSignals deployed successfully"
echo "Tag: $TAG"
echo "Backup: ${DB_BACKUP:-none}"
echo "Log: $LOG_FILE"

# Retention is applied only after a successful deploy and validated snapshot.
ls -t "${BACKUP_DIR}"/marketdata_*.sqlite 2>/dev/null | tail -n +$((SQLITE_BACKUP_RETENTION + 1)) | xargs -r rm || true
ls -t "${BACKUP_DIR}"/pre_deploy_head_*.txt 2>/dev/null | tail -n +$((SQLITE_BACKUP_RETENTION + 1)) | xargs -r rm || true
ls -t "${BACKUP_DIR}"/smoke_*.log 2>/dev/null | tail -n +$((SMOKE_LOG_RETENTION + 1)) | xargs -r rm || true
