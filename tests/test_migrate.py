from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.event_identity import stable_event_id
from storage.migrate import apply_migrations
from storage.migrate import schema_hash
from storage.read_model_store import ingest_rows_to_sqlite
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
    assert row == (
        stable_event_id("tushare_news", "news", {"title": "legacy"}),
        1,
        "tushare",
    )


def test_event_identity_migration_preserves_rows_and_resumes_revisions(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    base = {
        "id": "provider-42",
        "datetime": "2026-07-11 09:00:00",
        "title": "A",
        "content": "v1",
    }
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 1

    conn = sqlite3.connect(db_path)
    event_hash = conn.execute("SELECT event_hash FROM market_events").fetchone()[0]
    conn.execute(
        "UPDATE market_events SET event_id = event_hash, revision = 1, source_family = 'tushare'"
    )
    before_count = conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
    conn.commit()
    conn.close()

    result = apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    migrated = conn.execute(
        "SELECT event_hash, event_id, revision, source_family FROM market_events"
    ).fetchone()
    after_count = conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0]
    conn.close()
    expected_id = stable_event_id("tushare_news", "news", base)
    assert result["event_identity_backfilled"] >= 1
    assert before_count == after_count == 1
    assert migrated == (event_hash, expected_id, 1, "tushare")
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 0
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "news",
        [{**base, "content": "v2"}],
    ) == 1

    conn = sqlite3.connect(db_path)
    revisions = conn.execute(
        "SELECT event_id, revision, content FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert revisions == [(expected_id, 1, "v1"), (expected_id, 2, "v2")]


def test_apply_migrations_creates_event_identity_indexes_for_legacy_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE market_events (
            event_hash TEXT,
            provider TEXT,
            event_type TEXT,
            event_time TEXT,
            trade_date TEXT,
            market TEXT,
            symbol TEXT,
            title TEXT,
            content TEXT,
            url TEXT,
            source TEXT,
            source_file TEXT,
            collected_at TEXT,
            raw_json TEXT,
            PRIMARY KEY (event_hash)
        )
        """
    )
    conn.commit()
    conn.close()

    result = apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='market_events'"
        ).fetchall()
    }
    conn.close()
    assert result["status"] == "ok"
    assert indexes >= {"idx_market_events_identity", "idx_market_events_time_identity"}
