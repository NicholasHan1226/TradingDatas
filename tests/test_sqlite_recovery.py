from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from storage.schema import SCHEMA_SQL
from tools.sqlite_recovery import (
    check_sqlite_corruption,
    choose_recovery_source,
    list_candidate_backups,
    recover,
    validate_backup,
)


def _create_db(path: Path) -> sqlite3.Connection:
    """Create a valid SharedSignals SQLite DB at *path* and return open connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    # Make the backup self-contained (no WAL sidecars) for deterministic tests.
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def _insert_sample_data(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO market_assets (market, symbol, name) VALUES (?, ?, ?)",
        ("Ashare", "000001.SZ", "平安银行"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO market_bars_daily "
        "(market, symbol, trade_date, open, high, low, close, volume, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Ashare", "000001.SZ", "20260703", 10.0, 11.0, 9.5, 10.5, 1_000_000, 10_500_000),
    )
    conn.commit()


def _create_duckdb_mirror(path: Path) -> None:
    """Create a DuckDB mirror with the same schema and a small row set."""
    duckdb = pytest.importorskip("duckdb")

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    # Render SQLite-compatible DDL then rewrite INTEGER -> BIGINT is unnecessary here
    # because DuckDB accepts the schema contract rendered for duckdb.
    from storage.duckdb_schema import create_schema

    create_schema(conn)
    conn.execute(
        "INSERT INTO market_assets (market, symbol, name) VALUES (?, ?, ?)",
        ("Ashare", "000001.SZ", "平安银行"),
    )
    conn.execute(
        "INSERT INTO market_bars_daily "
        "(market, symbol, trade_date, open, high, low, close, volume, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Ashare", "000001.SZ", "20260703", 10.0, 11.0, 9.5, 10.5, 1_000_000, 10_500_000),
    )
    conn.commit()
    conn.close()


def _count_rows(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _corrupt_db(path: Path) -> None:
    """Overwrite the file with invalid bytes to simulate media corruption."""
    path.write_bytes(b"NOT A SQLITE DATABASE\x00\x01\x02" * 50)


class TestCorruptionDetection:
    def test_check_sqlite_corruption_ok(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        conn = _create_db(db_path)
        _insert_sample_data(conn)
        conn.close()

        result = check_sqlite_corruption(db_path)
        assert result["status"] == "ok"
        assert result["corrupt"] is False
        assert result["missing"] is False
        assert result["integrity_ok"] is True

    def test_check_sqlite_corruption_empty_file(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        db_path.write_text("")

        result = check_sqlite_corruption(db_path)
        assert result["status"] == "corrupt"
        assert result["corrupt"] is True
        assert result["reason"] == "empty_database_file"

    def test_check_sqlite_corruption_garbage(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)

        result = check_sqlite_corruption(db_path)
        assert result["status"] == "corrupt"
        assert result["corrupt"] is True
        assert result["can_open"] is False

    def test_check_sqlite_corruption_missing(self, tmp_path: Path):
        db_path = tmp_path / "does_not_exist.sqlite"

        result = check_sqlite_corruption(db_path)
        assert result["status"] == "missing"
        assert result["missing"] is True
        assert result["reason"] == "database_not_found"


class TestBackupDiscovery:
    def test_list_candidate_backups_sorted(self, tmp_path: Path):
        backups = tmp_path / "backups"
        backups.mkdir()
        older = backups / "marketdata_20260701T000000Z.sqlite"
        newer = backups / "marketdata_20260705T000000Z.sqlite"
        older.write_bytes(b"x")
        newer.write_bytes(b"x")

        candidates = list_candidate_backups([backups])
        assert len(candidates) == 2
        assert candidates[0]["path"] == str(newer.resolve())
        assert candidates[1]["path"] == str(older.resolve())

    def test_validate_backup_valid(self, tmp_path: Path):
        db_path = tmp_path / "backup.sqlite"
        conn = _create_db(db_path)
        _insert_sample_data(conn)
        conn.close()

        validation = validate_backup(db_path)
        assert validation["valid"] is True
        assert validation["integrity_ok"] is True
        assert validation["table_counts"]["market_bars_daily"] == 1

    def test_validate_backup_missing_table(self, tmp_path: Path):
        db_path = tmp_path / "backup.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.close()

        validation = validate_backup(db_path)
        assert validation["valid"] is False
        assert "missing_tables" in validation["reason"]


class TestRecoverySourceSelection:
    def test_choose_recovery_source_prefers_backup(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)

        backups = tmp_path / "backups"
        backups.mkdir()
        backup_path = backups / "marketdata_20260705T000000Z.sqlite"
        conn = _create_db(backup_path)
        _insert_sample_data(conn)
        conn.close()

        duckdb_path = tmp_path / "marketdata.duckdb"
        _create_duckdb_mirror(duckdb_path)

        source = choose_recovery_source(db_path, duckdb_path=duckdb_path, backup_dirs=[backups])
        assert source is not None
        assert source["source_type"] == "backup"
        assert source["path"] == backup_path

    def test_choose_recovery_source_falls_back_to_duckdb(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)

        duckdb_path = tmp_path / "marketdata.duckdb"
        _create_duckdb_mirror(duckdb_path)

        source = choose_recovery_source(db_path, duckdb_path=duckdb_path, backup_dirs=[])
        assert source is not None
        assert source["source_type"] == "duckdb"

    def test_choose_recovery_source_blocked(self, tmp_path: Path, monkeypatch):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)
        monkeypatch.setattr(
            "tools.sqlite_recovery.default_backup_dirs",
            lambda _path: (_ for _ in ()).throw(AssertionError("explicit [] must not use defaults")),
        )

        source = choose_recovery_source(db_path, duckdb_path=tmp_path / "no.duckdb", backup_dirs=[])
        assert source is None


class TestRecoverFromBackup:
    def test_recover_from_backup_dry_run_does_not_write(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)
        original_bytes = db_path.read_bytes()

        backups = tmp_path / "backups"
        backups.mkdir()
        backup_path = backups / "marketdata_20260705T000000Z.sqlite"
        conn = _create_db(backup_path)
        _insert_sample_data(conn)
        conn.close()

        result = recover(
            db_path=db_path,
            duckdb_path=tmp_path / "no.duckdb",
            backup_dirs=[backups],
            dry_run=True,
        )

        assert result["dry_run"] is True
        assert result["recovered"] is True  # plan says it would recover
        assert result["reason"].startswith("dry_run")
        assert db_path.read_bytes() == original_bytes
        # No quarantine file should appear
        assert len(list(tmp_path.glob("marketdata_corrupt_*.sqlite"))) == 0

    def test_recover_from_backup_apply_quarantines_and_restores(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)

        backups = tmp_path / "backups"
        backups.mkdir()
        backup_path = backups / "marketdata_20260705T000000Z.sqlite"
        conn = _create_db(backup_path)
        _insert_sample_data(conn)
        conn.close()

        # Simulate stale WAL/SHM sidecars from the corrupt DB.
        (tmp_path / "marketdata.sqlite-wal").write_text("wal")
        (tmp_path / "marketdata.sqlite-shm").write_text("shm")

        result = recover(
            db_path=db_path,
            duckdb_path=tmp_path / "no.duckdb",
            backup_dirs=[backups],
            dry_run=False,
            quarantine_dir=tmp_path / "quarantine",
        )

        assert result["recovered"] is True
        assert result["source_type"] == "backup"
        assert result["reason"] == "restored_from_backup"
        assert result["integrity_ok"] is True

        # Bad DB should be in quarantine. SQLite may clean invalid sidecars
        # while probing a corrupt DB on some platforms, so only assert that
        # source sidecars do not survive beside the restored DB.
        quarantine_dir = tmp_path / "quarantine"
        assert quarantine_dir.exists()
        quarantined = list(quarantine_dir.glob("marketdata_corrupt_*.sqlite"))
        assert len(quarantined) == 1
        assert quarantined[0].read_bytes() == b"NOT A SQLITE DATABASE\x00\x01\x02" * 50

        # Restored DB should match backup content and be clean of sidecars.
        assert db_path.exists()
        assert not (tmp_path / "marketdata.sqlite-wal").exists()
        assert not (tmp_path / "marketdata.sqlite-shm").exists()
        assert _count_rows(db_path, "market_bars_daily") == 1
        assert _count_rows(db_path, "market_assets") == 1

    def test_recover_blocked_when_no_source(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)
        original_bytes = db_path.read_bytes()

        result = recover(
            db_path=db_path,
            duckdb_path=tmp_path / "no.duckdb",
            backup_dirs=[],
            dry_run=False,
        )

        assert result["recovered"] is False
        assert result["reason"] == "blocked_no_valid_recovery_source"
        assert db_path.read_bytes() == original_bytes


class TestRecoverFromDuckDB:
    def test_recover_from_duckdb_rebuilds_sqlite(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)

        duckdb_path = tmp_path / "marketdata.duckdb"
        _create_duckdb_mirror(duckdb_path)

        result = recover(
            db_path=db_path,
            duckdb_path=duckdb_path,
            backup_dirs=[],
            source_type="duckdb",
            dry_run=False,
        )

        assert result["recovered"] is True
        assert result["source_type"] == "duckdb"
        assert result["reason"] == "rebuilt_from_duckdb"
        assert result["integrity_ok"] is True
        assert _count_rows(db_path, "market_bars_daily") == 1
        assert _count_rows(db_path, "market_assets") == 1

    def test_recover_from_duckdb_dry_run(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        _corrupt_db(db_path)
        original_bytes = db_path.read_bytes()

        duckdb_path = tmp_path / "marketdata.duckdb"
        _create_duckdb_mirror(duckdb_path)

        result = recover(
            db_path=db_path,
            duckdb_path=duckdb_path,
            backup_dirs=[],
            source_type="duckdb",
            dry_run=True,
        )

        assert result["dry_run"] is True
        assert result["reason"].startswith("dry_run")
        assert db_path.read_bytes() == original_bytes


class TestHealthyDatabase:
    def test_recover_healthy_db_is_no_op(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        conn = _create_db(db_path)
        _insert_sample_data(conn)
        conn.close()

        result = recover(db_path=db_path, dry_run=False)
        assert result["recovered"] is False
        assert result["reason"] == "database_healthy_no_recovery_needed"
        assert _count_rows(db_path, "market_bars_daily") == 1

    def test_recover_healthy_db_with_force(self, tmp_path: Path):
        db_path = tmp_path / "marketdata.sqlite"
        conn = _create_db(db_path)
        _insert_sample_data(conn)
        conn.close()

        backups = tmp_path / "backups"
        backups.mkdir()
        backup_path = backups / "snapshot.sqlite"
        conn = _create_db(backup_path)
        _insert_sample_data(conn)
        conn.close()

        result = recover(db_path=db_path, backup_dirs=[backups], force=True, dry_run=False)
        assert result["recovered"] is True
        assert result["source_type"] == "backup"
        assert _count_rows(db_path, "market_bars_daily") == 1
