from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

import duckdb_merge
from storage.schema import SCHEMA_SQL
from storage.schema import TABLE_NAMES
from storage.sqlite_snapshot import (
    DEFAULT_STALE_SECONDS,
    SQLiteSnapshotError,
    _logical_database_bytes,
    cleanup_stale_snapshots,
    create_sqlite_snapshot,
)
from storage.storage_adapter import StorageAdapter


def _create_source(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def test_continuous_writer_snapshot_sync_and_reconcile_share_one_source(tmp_path: Path) -> None:
    source = tmp_path / "authority.sqlite"
    mirror = tmp_path / "mirror.duckdb"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    stop = threading.Event()
    inserted = threading.Event()

    def writer() -> None:
        conn = sqlite3.connect(source, timeout=10)
        index = 0
        try:
            while not stop.is_set():
                index += 1
                conn.execute(
                    "INSERT INTO market_assets (market, symbol, name, provider) VALUES (?, ?, ?, ?)",
                    ("Ashare", f"{index:06d}.SZ", f"asset-{index}", "test"),
                )
                conn.commit()
                inserted.set()
                time.sleep(0.001)
        finally:
            conn.close()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert inserted.wait(timeout=5)
    snapshot = create_sqlite_snapshot(
        source,
        snapshot_root=snapshots,
        reserve_bytes=0,
        required_tables=["market_assets"],
    )
    try:
        adapter = StorageAdapter(str(snapshot.path), str(mirror))
        adapter.sync_sqlite_to_duckdb("market_assets")
        snapshot_count = sqlite3.connect(snapshot.path).execute(
            "SELECT COUNT(*) FROM market_assets"
        ).fetchone()[0]
        time.sleep(0.02)
        reconciliation = adapter.reconcile_counts(["market_assets"])
        live_count = sqlite3.connect(source).execute(
            "SELECT COUNT(*) FROM market_assets"
        ).fetchone()[0]

        assert reconciliation["market_assets"] == {
            "sqlite_rows": snapshot_count,
            "duckdb_rows": snapshot_count,
            "delta": 0,
            "status": "ok",
        }
        assert live_count >= snapshot_count
        assert snapshot.metadata["source_before"]["database"]["inode"] == source.stat().st_ino
        assert snapshot.metadata["source_before"]["wal"]["exists"] is True
        assert snapshot.metadata["mode"] == 0o600
        assert snapshots.stat().st_mode & 0o777 == 0o700
    finally:
        stop.set()
        thread.join(timeout=5)
        cleanup = snapshot.cleanup()
    assert cleanup["status"] == "ok"
    assert not snapshot.path.exists()


def test_real_full_merge_preserves_two_table_transaction_invariant_with_writer(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "authority.sqlite"
    mirror = tmp_path / "mirror.duckdb"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    stop = threading.Event()
    inserted = threading.Event()

    def writer() -> None:
        conn = sqlite3.connect(source, timeout=10)
        index = 0
        try:
            while not stop.is_set():
                index += 1
                symbol = f"{index:06d}.SZ"
                conn.execute("BEGIN")
                conn.execute(
                    "INSERT INTO market_assets (market, symbol, name, provider) VALUES (?, ?, ?, ?)",
                    ("Ashare", symbol, f"asset-{index}", "test"),
                )
                conn.execute(
                    """
                    INSERT INTO market_bars_daily
                    (market, symbol, trade_date, close, provider)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("Ashare", symbol, "20260713", float(index), "test"),
                )
                conn.commit()
                inserted.set()
                time.sleep(0.001)
        finally:
            conn.close()

    class _BoundAdapter(StorageAdapter):
        def __init__(self, sqlite_path=str(source), duckdb_path=str(mirror)):
            super().__init__(sqlite_path=sqlite_path, duckdb_path=duckdb_path)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert inserted.wait(timeout=5)
    monkeypatch.setattr(duckdb_merge, "StorageAdapter", _BoundAdapter)
    monkeypatch.setenv("SHAREDSIGNALS_DUCKDB_SNAPSHOT_DIR", str(snapshots))
    monkeypatch.setenv("SHAREDSIGNALS_DUCKDB_SNAPSHOT_RESERVE_BYTES", "0")

    try:
        result = duckdb_merge.run_merge()
    finally:
        stop.set()
        thread.join(timeout=5)

    assert result["status"] == "ok", result.get("error")
    assert len(result["reconciliation"]) == len(TABLE_NAMES)
    asset_rows = result["reconciliation"]["market_assets"]["sqlite_rows"]
    bar_rows = result["reconciliation"]["market_bars_daily"]["sqlite_rows"]
    assert asset_rows == bar_rows
    assert result["reconciliation"]["market_assets"]["status"] == "ok"
    assert result["reconciliation"]["market_bars_daily"]["status"] == "ok"
    assert result["snapshot_cleanup"]["status"] == "ok"
    assert list(snapshots.iterdir()) == []


def test_insufficient_space_fails_before_snapshot_file_creation(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    monkeypatch.setattr(
        "storage.sqlite_snapshot._filesystem_space",
        lambda _path: {
            "total_bytes": 100,
            "available_bytes": 1,
            "used_bytes": 99,
            "usage_percent": 99.0,
            "device": 1,
            "path": str(_path),
        },
    )

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=source.stat().st_size,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "insufficient_space"
    assert list(snapshots.iterdir()) == []


def test_backup_timeout_is_classified_and_temp_is_cleaned(tmp_path: Path) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    _create_source(source)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=0,
            timeout_seconds=1e-12,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "snapshot_timeout"
    assert list(snapshots.iterdir()) == []


def test_wal_logical_size_drives_space_preflight_before_temp_creation(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "wal-heavy.sqlite"
    snapshots = tmp_path / "snapshots"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE wal_rows (id INTEGER PRIMARY KEY, payload BLOB)")
        conn.commit()
        conn.executemany(
            "INSERT INTO wal_rows(payload) VALUES (?)",
            [(b"x" * 4096,) for _ in range(512)],
        )
        conn.commit()
        logical = _logical_database_bytes(source)["logical_bytes"]
        main_size = source.stat().st_size
        assert logical > main_size
        monkeypatch.setattr(
            "storage.sqlite_snapshot._filesystem_space",
            lambda _path: {
                "total_bytes": logical * 4,
                "available_bytes": logical - 1,
                "used_bytes": logical * 3 + 1,
                "usage_percent": 75.0,
                "device": 1,
                "path": str(_path),
            },
        )

        with pytest.raises(SQLiteSnapshotError) as exc_info:
            create_sqlite_snapshot(
                source,
                snapshot_root=snapshots,
                reserve_bytes=0,
                required_tables=["wal_rows"],
            )
    finally:
        conn.close()

    assert exc_info.value.error_class == "insufficient_space"
    preflight = exc_info.value.metadata["space_preflight"]
    assert preflight["source_logical_bytes"] == logical
    assert preflight["estimated_backup_bytes"] == logical
    assert list(snapshots.iterdir()) == []


def test_projected_filesystem_usage_ceiling_fails_before_temp(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    logical = _logical_database_bytes(source)["logical_bytes"]
    total = logical * 10
    monkeypatch.setattr(
        "storage.sqlite_snapshot._filesystem_space",
        lambda _path: {
            "total_bytes": total,
            "available_bytes": logical * 2,
            "used_bytes": logical * 9,
            "usage_percent": 90.0,
            "device": 1,
            "path": str(_path),
        },
    )

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=0,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "insufficient_space"
    assert exc_info.value.metadata["space_preflight"]["projected_usage_percent"] > 90
    assert list(snapshots.iterdir()) == []


def test_distinct_duckdb_work_filesystem_must_keep_reserve(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    work = tmp_path / "duckdb-work"
    work.mkdir()
    _create_source(source)
    logical = _logical_database_bytes(source)["logical_bytes"]

    def fake_space(path: Path) -> dict:
        is_work = Path(path) == work
        return {
            "total_bytes": logical * 100,
            "available_bytes": 50 if is_work else logical * 50,
            "used_bytes": logical * 50,
            "usage_percent": 50.0,
            "device": 2 if is_work else 1,
            "path": str(path),
        }

    monkeypatch.setattr("storage.sqlite_snapshot._filesystem_space", fake_space)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=100,
            required_tables=["market_assets"],
            working_paths=[work],
        )

    assert exc_info.value.error_class == "insufficient_space"
    work_filesystems = exc_info.value.metadata["space_preflight"]["work_filesystems"]
    assert work_filesystems[0]["device"] == 2
    assert list(snapshots.iterdir()) == []


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [
        ("SHAREDSIGNALS_DUCKDB_SNAPSHOT_RESERVE_BYTES", "bad"),
        ("SHAREDSIGNALS_DUCKDB_SNAPSHOT_RESERVE_BYTES", "-1"),
        ("SHAREDSIGNALS_DUCKDB_SNAPSHOT_TIMEOUT", "nan"),
        ("SHAREDSIGNALS_DUCKDB_SNAPSHOT_MAX_FS_USAGE_PCT", "101"),
    ],
)
def test_invalid_snapshot_configuration_is_classified(
    tmp_path: Path, monkeypatch, env_name: str, env_value: str
) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    monkeypatch.setenv(env_name, env_value)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "invalid_configuration"
    assert exc_info.value.metadata["snapshot_id"]
    assert exc_info.value.metadata["source_before"]["database"]["exists"] is True
    assert list(snapshots.iterdir()) == []


def test_temp_replacement_is_refused_and_preserves_prior_error(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    replacement_target = tmp_path / "replacement"
    replacement_target.write_text("keep")
    _create_source(source)

    def replace_temp(path: Path, _required_tables) -> dict:
        path.unlink()
        path.symlink_to(replacement_target)
        raise SQLiteSnapshotError("snapshot_validation_failed", "validation injected")

    monkeypatch.setattr("storage.sqlite_snapshot._validate_snapshot", replace_temp)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=0,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "cleanup_failed"
    assert exc_info.value.metadata["prior_error"]["error_class"] == "snapshot_validation_failed"
    residuals = list(snapshots.iterdir())
    assert len(residuals) == 1 and residuals[0].is_symlink()
    assert replacement_target.read_text() == "keep"


def test_post_publish_metadata_failure_exactly_cleans_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    _create_source(source)
    from storage import sqlite_snapshot

    original = sqlite_snapshot.source_metadata
    calls = 0

    def fail_second_call(path: Path) -> dict:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("metadata injected")
        return original(path)

    monkeypatch.setattr(sqlite_snapshot, "source_metadata", fail_second_call)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=0,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "snapshot_metadata_failed"
    assert exc_info.value.metadata["published_cleanup"]["status"] == "removed"
    assert list(snapshots.iterdir()) == []


def test_validation_failure_is_classified_and_temp_is_cleaned(tmp_path: Path) -> None:
    source = tmp_path / "authority.sqlite"
    snapshots = tmp_path / "snapshots"
    sqlite3.connect(source).close()

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(
            source,
            snapshot_root=snapshots,
            reserve_bytes=0,
            required_tables=["market_assets"],
        )

    assert exc_info.value.error_class == "snapshot_validation_failed"
    assert list(snapshots.iterdir()) == []


def test_stale_cleanup_removes_only_old_regular_owned_prefix(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    root.mkdir()
    old = root / "duckdb-sync-old.sqlite.tmp"
    fresh = root / "duckdb-sync-fresh.sqlite.tmp"
    unrelated = root / "keep.sqlite"
    symlink = root / "duckdb-sync-link.sqlite.tmp"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    unrelated.write_bytes(b"keep")
    symlink.symlink_to(unrelated)
    now = time.time()
    os.utime(old, (now - 7200, now - 7200))

    result = cleanup_stale_snapshots(root, stale_after_seconds=3600, now=now)

    assert result["removed"] == [str(old)]
    assert not old.exists()
    assert fresh.exists()
    assert unrelated.exists()
    assert symlink.is_symlink()


def test_next_cycle_cleans_residual_older_than_two_outer_timeouts(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    root.mkdir()
    residual = root / "duckdb-sync-killed.sqlite.tmp"
    residual.write_bytes(b"orphan")
    now = time.time()
    os.utime(
        residual,
        (now - DEFAULT_STALE_SECONDS - 1, now - DEFAULT_STALE_SECONDS - 1),
    )

    result = cleanup_stale_snapshots(root, now=now)

    assert result["removed"] == [str(residual)]
    assert not residual.exists()


def test_source_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "authority.sqlite"
    link = tmp_path / "authority-link.sqlite"
    _create_source(source)
    link.symlink_to(source)

    with pytest.raises(SQLiteSnapshotError) as exc_info:
        create_sqlite_snapshot(link, reserve_bytes=0)

    assert exc_info.value.error_class == "source_unavailable"
    assert exc_info.value.metadata["source_before"]["database"]["is_symlink"] is True
