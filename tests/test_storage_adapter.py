from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from storage.schema import SCHEMA_SQL
from storage.storage_adapter import StorageAdapter


def _create_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def test_duckdb_sync_tolerates_empty_numeric_strings(tmp_path: Path):
    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            """
            INSERT INTO market_bars_daily
            (market, symbol, trade_date, open, high, low, close, volume, amount, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Global", "IXIC", "20260701", "", "100", "99", "101", "1000", "", "tushare_index_global"),
        )
        conn.commit()
    finally:
        conn.close()

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    synced = adapter.sync_sqlite_to_duckdb("market_bars_daily")
    rows = adapter.query(
        "SELECT open, high, close, amount FROM market_bars_daily WHERE symbol = 'IXIC'"
    )

    assert synced == 1
    assert rows == [{"open": None, "high": 100.0, "close": 101.0, "amount": None}]


def test_append_only_event_sync_inserts_new_hashes_without_rewriting_history(tmp_path: Path):
    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            """
            INSERT INTO market_events
            (event_hash, provider, event_type, title, collected_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("event-1", "test", "news", "original", "2026-07-10T01:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    assert adapter.sync_sqlite_to_duckdb("market_events") == 1

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("UPDATE market_events SET title = ? WHERE event_hash = ?", ("changed", "event-1"))
        conn.execute(
            """
            INSERT INTO market_events
            (event_hash, provider, event_type, title, collected_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("event-2", "test", "news", "new", "2026-07-10T01:05:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    assert adapter.sync_sqlite_to_duckdb("market_events") == 1
    assert adapter.query("SELECT event_hash, title FROM market_events ORDER BY event_hash") == [
        {"event_hash": "event-1", "title": "original"},
        {"event_hash": "event-2", "title": "new"},
    ]


def test_snapshot_table_sync_removes_rows_deleted_from_sqlite(tmp_path: Path):
    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.executemany(
            "INSERT INTO market_assets (market, symbol, name, provider) VALUES (?, ?, ?, ?)",
            [
                ("Ashare", "000001.SZ", "asset-1", "test"),
                ("Ashare", "000002.SZ", "asset-2", "test"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    assert adapter.sync_sqlite_to_duckdb("market_assets") == 2

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute("DELETE FROM market_assets WHERE symbol = ?", ("000002.SZ",))
        conn.commit()
    finally:
        conn.close()

    adapter.sync_sqlite_to_duckdb("market_assets")

    assert adapter.query("SELECT symbol FROM market_assets ORDER BY symbol") == [
        {"symbol": "000001.SZ"},
    ]


def test_intraday_snapshot_sync_removes_rows_with_retired_primary_keys(tmp_path: Path):
    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            """
            INSERT INTO market_bars_intraday
            (market, symbol, bar_time, trade_date, interval, close, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Ashare", "000001.SZ", "20260710", "20260710", "1w", 10.0, "test"),
        )
        conn.commit()
    finally:
        conn.close()

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    assert adapter.sync_sqlite_to_duckdb("market_bars_intraday") == 1

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.execute(
            "UPDATE market_bars_intraday SET bar_time = ? WHERE bar_time = ?",
            ("2026-07-10 00:00:00", "20260710"),
        )
        conn.commit()
    finally:
        conn.close()

    adapter.sync_sqlite_to_duckdb("market_bars_intraday")

    assert adapter.query(
        "SELECT bar_time FROM market_bars_intraday ORDER BY bar_time"
    ) == [{"bar_time": "2026-07-10 00:00:00"}]


def test_reconcile_counts_reports_table_mismatch(tmp_path: Path):
    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)
    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    adapter.sync_sqlite_to_duckdb("market_assets")

    conn = adapter.duckdb_connect()
    try:
        conn.execute(
            "INSERT INTO market_assets (market, symbol, name, provider) VALUES (?, ?, ?, ?)",
            ["Ashare", "stale.SZ", "stale", "test"],
        )
    finally:
        conn.close()

    reconciliation = adapter.reconcile_counts(["market_assets"])

    assert reconciliation == {
        "market_assets": {
            "sqlite_rows": 0,
            "duckdb_rows": 1,
            "delta": -1,
            "status": "mismatch",
        }
    }
