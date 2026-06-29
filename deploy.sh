#!/bin/bash
# deploy.sh - SharedSignals deployment pipeline
# Backup (git tag + SQLite snapshot) -> pull -> migration -> smoke test -> switch (or rollback)
set -euo pipefail

REPO_DIR="/opt/investment/SharedSignals"
BACKUP_DIR="/opt/investment/SharedSignals/backups"
SQLITE_DB="/opt/investment/SharedSignals/storage/marketdata.sqlite"
VENV_PYTHON="/opt/marketgraph/venv/bin/python3"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TAG="deploy-${TIMESTAMP}"
LOG_FILE="${REPO_DIR}/logs/deploy_${TIMESTAMP}.log"

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
success() { echo "[OK] $*" | tee -a "$LOG_FILE"; }
warn() { echo "[WARN] $*" | tee -a "$LOG_FILE"; }
error() { echo "[ERROR] $*" | tee -a "$LOG_FILE"; }

rollback_deploy() {
    error "DEPLOY FAILED - rolling back"
    if [ -f "${REPO_DIR}/rollback.sh" ]; then
        bash "${REPO_DIR}/rollback.sh" "$TAG" || true
    else
        error "rollback.sh not found - manual recovery required"
    fi
    exit 1
}

trap rollback_deploy ERR

log "=== SharedSignals Deploy ${TIMESTAMP} ==="

# ---- Phase 1: Backup ----
log "Phase 1: Backup"
cd "$REPO_DIR"

# Git tag
git tag "$TAG"
success "Git tag: $TAG"

# SQLite snapshot
DB_BACKUP=""
if [ -f "$SQLITE_DB" ]; then
    DB_BACKUP="${BACKUP_DIR}/marketdata_${TIMESTAMP}.sqlite"
    cp "$SQLITE_DB" "$DB_BACKUP"
    success "SQLite snapshot saved"
else
    warn "No SQLite database at $SQLITE_DB - skipping snapshot"
fi

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
    success "Pulled: $(git log --oneline -1)"
fi

# ---- Phase 3: Run migrations ----
log "Phase 3: Run migrations"
MIGRATION_SCRIPT="${REPO_DIR}/storage/migrate.py"
if [ -f "$MIGRATION_SCRIPT" ]; then
    $VENV_PYTHON "$MIGRATION_SCRIPT" 2>&1 | tee -a "$LOG_FILE"
    success "Migration complete"
else
    log "No migration script found - skipping"
fi

# ---- Phase 4: Smoke test ----
log "Phase 4: Smoke test"
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

# ---- Phase 5: Switch ----
log "Phase 5: Switch"

# Restart any services if needed
SERVICE_FILE="/etc/systemd/system/sharedsignals.service"
if [ -f "$SERVICE_FILE" ]; then
    sudo systemctl restart sharedsignals 2>/dev/null || warn "Could not restart sharedsignals service"
    success "Service restarted"
else
    log "No systemd service found - skipping restart"
fi

# ---- Completion ----
log "=== Deploy ${TIMESTAMP} COMPLETE ==="
success "SharedSignals deployed successfully"
echo "Tag: $TAG"
echo "Backup: ${DB_BACKUP:-none}"
echo "Log: $LOG_FILE"

# Clean up old backups (keep last 10)
ls -t "${BACKUP_DIR}"/marketdata_*.sqlite 2>/dev/null | tail -n +11 | xargs -r rm || true
ls -t "${BACKUP_DIR}"/pre_deploy_head_*.txt 2>/dev/null | tail -n +11 | xargs -r rm || true
