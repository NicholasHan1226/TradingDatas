from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_script(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_deploy_snapshot_uses_temp_file_space_gate_and_validation() -> None:
    script = _read_script("deploy.sh")

    assert "DB_BACKUP_TMP" in script
    assert "df -PB1" in script
    assert "validate_sqlite_snapshot" in script
    assert "mv \"$DB_BACKUP_TMP\" \"$DB_BACKUP\"" in script
    assert "bash \"${REPO_DIR}/rollback.sh\" \"$TAG\" \"$TIMESTAMP\"" in script


def test_rollback_does_not_fallback_to_unrelated_latest_backup() -> None:
    script = _read_script("rollback.sh")

    assert "head -1" not in script
    assert "No exact SQLite backup found for $TAG" in script
    assert "validate_sqlite_snapshot" in script
    assert "rm -f \"${SQLITE_DB}-wal\" \"${SQLITE_DB}-shm\"" in script
    assert "sharedsignals-api.service" in script
