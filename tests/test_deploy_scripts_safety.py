from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_GUARDED_CRON_SCRIPTS = (
    "capability_scan.sh",
    "cn_futures_5min.sh",
    "cn_futures_daily.sh",
    "collectors.sh",
    "crypto_collect.sh",
    "duckdb_sync.sh",
    "green_gate_report.sh",
    "health_sla.sh",
    "opening_gate.sh",
    "patrol.sh",
    "pm_collect.sh",
    "source_governance_monitor.sh",
    "tushare_events_collect.sh",
    "tushare_low_frequency_collect.sh",
    "watchdog.sh",
)


def _read_script(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_deploy_snapshot_uses_temp_file_space_gate_and_validation() -> None:
    script = _read_script("deploy.sh")

    assert "DB_BACKUP_TMP" in script
    assert "df -PB1" in script
    assert "validate_sqlite_snapshot" in script
    assert "backup_sqlite_database" in script
    assert "source.backup(target)" in script
    assert 'cp "$SQLITE_DB" "$DB_BACKUP_TMP"' not in script
    assert "mv \"$DB_BACKUP_TMP\" \"$DB_BACKUP\"" in script
    assert (
        "bash \"${REPO_DIR}/rollback.sh\" \"$TAG\" \"$TIMESTAMP\" "
        "\"${DEPLOYED_HEAD:-}\"" in script
    )


def test_rollback_does_not_fallback_to_unrelated_latest_backup() -> None:
    script = _read_script("rollback.sh")

    assert "head -1" not in script
    assert "No exact SQLite backup found for $TAG" in script
    assert "validate_sqlite_snapshot" in script
    assert "backup_sqlite_database" in script
    assert "RESTORE_TMP" in script
    assert 'mv -f "$RESTORE_TMP" "$SQLITE_DB"' in script
    assert "rm -f \"${SQLITE_DB}-wal\" \"${SQLITE_DB}-shm\"" in script
    assert "sharedsignals-api.service" in script


def test_deploy_and_manual_rollback_share_a_nonblocking_lock() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for script in (deploy, rollback):
        assert "SHAREDSIGNALS_DEPLOY_LOCK_FILE" in script
        assert "flock -n 9" in script

    assert "SHAREDSIGNALS_DEPLOY_LOCK_HELD=1" in deploy
    assert '"${SHAREDSIGNALS_DEPLOY_LOCK_HELD:-0}" = "1"' in rollback


def test_rollback_refuses_to_overwrite_a_newer_deployment() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    assert "DEPLOYED_HEAD=$(git rev-parse HEAD)" in deploy
    assert 'EXPECTED_CURRENT_HEAD="${3:-}"' in rollback
    assert '"$CURRENT" != "$EXPECTED_CURRENT_HEAD"' in rollback
    assert '"$CURRENT" != "$TARGET"' in rollback
    assert "Stale rollback refused" in rollback


def test_deploy_and_rollback_hold_exclusive_read_model_maintenance_lock() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for script in (deploy, rollback):
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in script
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_HELD" in script
        assert 'flock -w "$MAINTENANCE_LOCK_TIMEOUT" 8' in script


def test_read_model_cron_jobs_take_shared_maintenance_lock() -> None:
    helper = (ROOT / "cron" / "maintenance_lock.sh").read_text(encoding="utf-8")
    assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in helper
    assert "flock -s -n 199" in helper

    for name in MAINTENANCE_GUARDED_CRON_SCRIPTS:
        script = (ROOT / "cron" / name).read_text(encoding="utf-8")
        assert 'source "${SCRIPT_DIR}/maintenance_lock.sh"' in script, name
        assert "acquire_sharedsignals_read_model_lock" in script, name
