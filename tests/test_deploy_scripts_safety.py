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
    pull_position = deploy.index("git pull")
    captured_head_position = deploy.index("DEPLOYED_HEAD=$(git rev-parse HEAD)", pull_position)
    success_log_position = deploy.index('success "Pulled:', pull_position)
    assert captured_head_position < success_log_position


def test_deploy_and_rollback_hold_exclusive_read_model_maintenance_lock() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for script in (deploy, rollback):
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in script
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_HELD" in script
        assert 'flock -w "$MAINTENANCE_LOCK_TIMEOUT" 8' in script
        assert "chmod 0666" not in script
        assert "chmod 0660" in script

    assert "SHAREDSIGNALS_MARKETDATA_DB" in deploy
    assert "SHAREDSIGNALS_MARKETDATA_DB" in rollback


def test_read_model_cron_jobs_take_shared_maintenance_lock() -> None:
    helper = (ROOT / "cron" / "maintenance_lock.sh").read_text(encoding="utf-8")
    assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in helper
    assert "flock -s -n 199" in helper

    for name in MAINTENANCE_GUARDED_CRON_SCRIPTS:
        script = (ROOT / "cron" / name).read_text(encoding="utf-8")
        assert 'source "${SCRIPT_DIR}/maintenance_lock.sh"' in script, name
        assert "acquire_sharedsignals_read_model_lock" in script, name


def test_legacy_root_duckdb_cron_wrapper_is_retired() -> None:
    assert not (ROOT / "duckdb_merge_cron.sh").exists()


def test_deploy_installs_sharedsignals_owned_systemd_service() -> None:
    service = (ROOT / "deploy" / "systemd" / "sharedsignals-api.service").read_text(encoding="utf-8")
    deploy = _read_script("deploy.sh")

    assert "User=marketgraph" in service
    assert "ExecStart=/opt/sharedsignals/venv/bin/python3" in service
    assert "/opt/marketgraph/venv" not in service
    assert "deploy/systemd/sharedsignals-api.service" in deploy
    assert "systemctl daemon-reload" in deploy


def test_deploy_keeps_only_three_validated_sqlite_snapshots_by_default() -> None:
    deploy = _read_script("deploy.sh")

    assert 'SQLITE_BACKUP_RETENTION="${SHAREDSIGNALS_SQLITE_BACKUP_RETENTION:-3}"' in deploy
    assert "SQLITE_BACKUP_RETENTION + 1" in deploy


def test_tunnel_service_templates_keep_secrets_out_of_units_and_ports_on_loopback() -> None:
    relay = (ROOT / "deploy" / "systemd" / "sharedsignals-sg-relay-tunnel.service").read_text(encoding="utf-8")
    connector = (ROOT / "deploy" / "systemd" / "sharedsignals-cloudflared.service").read_text(encoding="utf-8")

    assert "-R 127.0.0.1:8082:127.0.0.1:8082" in relay
    assert "-R 127.0.0.1:80:127.0.0.1:80" in relay
    assert "-R 127.0.0.1:8787" not in relay
    assert "-L 127.0.0.1:18889:127.0.0.1:18888" in relay
    assert "--token-file /etc/cloudflared/sharedsignals.token" in connector
    assert "--token " not in connector
