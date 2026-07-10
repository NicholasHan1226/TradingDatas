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
