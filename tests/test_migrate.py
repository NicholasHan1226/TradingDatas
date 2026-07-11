from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.migrate import apply_migrations
from storage.migrate import schema_hash
from storage.schema import SCHEMA_SQL


def test_apply_migrations_adds_missing_nullable_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE market_bars_intraday (
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                bar_time TEXT NOT NULL,
                trade_date TEXT,
                interval TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                provider TEXT,
                source_file TEXT,
                collected_at TEXT,
                raw_json TEXT,
                PRIMARY KEY (market, symbol, bar_time, interval, provider)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    result = apply_migrations(db_path)

    assert result["status"] == "ok"
    assert result["added_columns"] >= 6
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(market_bars_intraday)").fetchall()}
    finally:
        conn.close()
    assert {"bid_price", "ask_price", "bid_size", "ask_size", "last_trade_date", "expiry_date"}.issubset(columns)


def test_apply_migrations_repairs_missing_nullable_columns_when_hash_is_current(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE market_bars_intraday (
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                bar_time TEXT NOT NULL,
                trade_date TEXT,
                interval TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                provider TEXT,
                source_file TEXT,
                collected_at TEXT,
                raw_json TEXT,
                PRIMARY KEY (market, symbol, bar_time, interval, provider)
            )
            """
        )
        conn.execute(
            """CREATE TABLE _migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_hash TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                table_count INTEGER,
                notes TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO _migrations (schema_hash, applied_at, table_count, notes) VALUES (?, ?, ?, ?)",
            (schema_hash(SCHEMA_SQL), "2026-07-05T00:00:00+00:00", 2, "simulated prior hash-only migration"),
        )
        conn.commit()
    finally:
        conn.close()

    result = apply_migrations(db_path)

    assert result["status"] == "ok"
    assert result["added_columns"] >= 6
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(market_bars_intraday)").fetchall()}
        repair_note = conn.execute("SELECT notes FROM _migrations ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert {"bid_price", "ask_price", "bid_size", "ask_size", "last_trade_date", "expiry_date"}.issubset(columns)
    assert "repair missing nullable columns" in repair_note


def test_apply_migrations_normalizes_existing_periodic_bar_times(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO market_bars_intraday
            (market, symbol, bar_time, trade_date, interval, provider)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Ashare", "000001.SZ", "20260703", "20260703", "weekly", "tushare_weekly"),
        )
        conn.commit()
    finally:
        conn.close()

    result = apply_migrations(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        value = conn.execute(
            "SELECT bar_time FROM market_bars_intraday WHERE symbol = ?",
            ("000001.SZ",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert result["periodic_bar_times_normalized"] == 1
    assert value == "2026-07-03 00:00:00"


def test_apply_migrations_backfills_legacy_event_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO market_events (event_hash, provider, event_type, title) VALUES (?, ?, ?, ?)",
        ("legacy-hash", "tushare_news", "news", "legacy"),
    )
    conn.commit()
    conn.close()
    result = apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT event_id, revision, source_family FROM market_events WHERE event_hash='legacy-hash'"
    ).fetchone()
    conn.close()
    assert result["event_identity_backfilled"] == 1
    assert row == ("legacy-hash", 1, "tushare")
