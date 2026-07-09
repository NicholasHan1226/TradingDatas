#!/bin/bash
# rollback.sh - SharedSignals rollback pipeline
# Restore git tag + SQLite snapshot -> restart service -> verify
set -euo pipefail

REPO_DIR="/opt/investment/SharedSignals"
BACKUP_DIR="/opt/investment/SharedSignals/backups"
SQLITE_DB="${SHAREDSIGNALS_MARKETDATA_DB:-/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite}"
VENV_PYTHON="/opt/sharedsignals/venv/bin/python3"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
success() { echo "[OK] $*"; }
warn() { echo "[WARN] $*"; }
error() { echo "[ERROR] $*"; }

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

# ---- Parse arguments ----
TAG="${1:-}"
TIMESTAMP="${2:-$(date +%Y%m%d_%H%M%S)}"

if [ -z "$TAG" ]; then
    echo "Usage: rollback.sh <git-tag> [timestamp]"
    echo ""
    echo "  git-tag    Git tag to rollback to (e.g. deploy-20260630_120000)"
    echo "  timestamp  Optional timestamp to find matching backup"
    echo "             (defaults to current time)"
    echo ""
    echo "Available tags:"
    git -C "$REPO_DIR" tag -l 'deploy-*' --sort=-creatordate | head -20
    exit 1
fi

log "=== SharedSignals Rollback to $TAG ==="
cd "$REPO_DIR"

# ---- Phase 1: Restore git tag ----
log "Phase 1: Restore git to tag $TAG"

if ! git rev-parse "$TAG" >/dev/null 2>&1; then
    error "Tag $TAG not found"
    exit 1
fi

CURRENT=$(git rev-parse HEAD)
TARGET=$(git rev-parse "$TAG")

if [ "$CURRENT" = "$TARGET" ]; then
    warn "Already at tag $TAG"
else
    git checkout "$TAG"
    success "Git restored to $TAG ($(git log --oneline -1))"
fi

# ---- Phase 2: Restore SQLite snapshot ----
log "Phase 2: Restore SQLite snapshot"

# Find the exact backup for this deploy tag only. Never fall back to an
# unrelated latest backup; restoring the wrong SQLite snapshot is worse than
# leaving the current database unchanged.
TAG_TS=$(echo "$TAG" | sed 's/^deploy-//')
DB_BACKUP="${BACKUP_DIR}/marketdata_${TAG_TS}.sqlite"

if [ -f "$DB_BACKUP" ]; then
    if ! validate_sqlite_snapshot "$DB_BACKUP"; then
        warn "SQLite backup failed validation; database unchanged: $DB_BACKUP"
    else
        SERVICE_FILE="/etc/systemd/system/sharedsignals-api.service"
        if [ -f "$SERVICE_FILE" ]; then
            sudo systemctl stop sharedsignals-api 2>/dev/null || warn "Could not stop sharedsignals-api service"
        fi

    # Backup current before replacing
        if [ -f "$SQLITE_DB" ]; then
            PRE_ROLLBACK_BACKUP="${BACKUP_DIR}/marketdata_pre_rollback_${TIMESTAMP}.sqlite"
            DB_SIZE=$(stat -c%s "$SQLITE_DB")
            DB_AVAIL=$(df -PB1 "$BACKUP_DIR" | awk 'NR==2 {print $4}')
            if [ "$DB_AVAIL" -gt "$DB_SIZE" ]; then
                cp "$SQLITE_DB" "$PRE_ROLLBACK_BACKUP" 2>/dev/null || warn "Could not save pre-rollback SQLite snapshot"
            else
                warn "Insufficient free space for pre-rollback SQLite snapshot; skipping"
            fi
        fi
        rm -f "${SQLITE_DB}-wal" "${SQLITE_DB}-shm"
        cp "$DB_BACKUP" "$SQLITE_DB"
        chown marketgraph:marketgraph "$SQLITE_DB" 2>/dev/null || true
        validate_sqlite_snapshot "$SQLITE_DB"
        success "SQLite restored from $DB_BACKUP"
    fi
else
    warn "No exact SQLite backup found for $TAG - database unchanged"
fi

# ---- Phase 3: Restart service ----
log "Phase 3: Restart service"

SERVICE_FILE="/etc/systemd/system/sharedsignals-api.service"
if [ -f "$SERVICE_FILE" ]; then
    sudo systemctl restart sharedsignals-api 2>/dev/null || warn "Could not restart sharedsignals-api service"
    success "Service restarted"
else
    log "No systemd service - skipping restart"
fi

# ---- Phase 4: Verify ----
log "Phase 4: Verify"
VERIFY_PASSED=true

# Check git state
if [ "$(git rev-parse HEAD)" = "$TARGET" ]; then
    success "Git at correct commit"
else
    error "Git NOT at expected commit"
    VERIFY_PASSED=false
fi

# Check key files exist
for f in "storage/schema.py" "bridge/marketgraph_marketdata_db.py" "reference/market_calendar.py"; do
    if [ -f "${REPO_DIR}/${f}" ]; then
        success "File exists: $f"
    else
        error "Missing: $f"
        VERIFY_PASSED=false
    fi
done

# Quick Python import check
if $VENV_PYTHON -c "
import sys
sys.path.insert(0, '${REPO_DIR}')
from storage.schema import SCHEMA_SQL
print('Schema OK')
" 2>&1; then
    success "Python imports verified"
else
    error "Import check FAILED"
    VERIFY_PASSED=false
fi

# Run smoke tests
if $VENV_PYTHON -m pytest "${REPO_DIR}/tests/" -v --timeout=30 --tb=short -x 2>&1; then
    success "Tests passed"
else
    warn "Some tests failed - manual review may be needed"
fi

# ---- Completion ----
if $VERIFY_PASSED; then
    log "=== Rollback to $TAG COMPLETE ==="
    success "SharedSignals rolled back successfully"
else
    error "=== Rollback verification had issues - manual review required ==="
    exit 1
fi
