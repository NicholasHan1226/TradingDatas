from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from storage.event_identity import event_content_fingerprint, stable_event_id
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


def test_migration_preserves_valid_fallback_identity_and_appends_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    base = {
        "datetime": "2026-07-11 09:00:00",
        "title": "Fallback identity",
        "content": "v1",
    }
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 1

    conn = sqlite3.connect(db_path)
    before = conn.execute(
        "SELECT event_hash, event_id, revision, raw_json FROM market_events"
    ).fetchone()
    conn.close()
    assert json.loads(before[3])["datetime"] == base["datetime"]

    first = apply_migrations(db_path)
    second = apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    after = conn.execute(
        "SELECT event_hash, event_id, revision, raw_json FROM market_events"
    ).fetchone()
    conn.close()
    assert first["event_identity_backfilled"] == 0
    assert second["event_identity_backfilled"] == 0
    assert after == before
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "news",
        [{**base, "content": "v2"}],
    ) == 1

    conn = sqlite3.connect(db_path)
    revisions = conn.execute(
        "SELECT event_id, revision FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert revisions == [(before[1], 1), (before[1], 2)]


def test_legacy_fallback_rebuild_uses_original_raw_datetime_and_title(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    base = {
        "datetime": "2026-07-11 09:00:00",
        "title": "Fallback identity",
        "content": "v1",
    }
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 1

    conn = sqlite3.connect(db_path)
    expected_id, event_hash = conn.execute(
        "SELECT event_id, event_hash FROM market_events"
    ).fetchone()
    conn.execute("UPDATE market_events SET event_id=event_hash, revision=1")
    conn.commit()
    conn.close()

    result = apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    migrated = conn.execute(
        "SELECT event_hash, event_id, revision FROM market_events"
    ).fetchone()
    conn.close()
    assert result["event_identity_backfilled"] == 1
    assert migrated == (event_hash, expected_id, 1)
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "news",
        [{**base, "content": "v2"}],
    ) == 1

    conn = sqlite3.connect(db_path)
    revisions = conn.execute(
        "SELECT event_id, revision FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert revisions == [(expected_id, 1), (expected_id, 2)]


def test_migration_never_reorders_valid_revisions_and_new_hashes_follow_formula(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    revision_one = {
        "id": "provider-42",
        "provider": "tushare_news",
        "event_type": "news",
        "event_time": "2026-07-12 09:00:00",
        "trade_date": "20260712",
        "title": "A",
        "content": "v1",
        "source": "tushare_news",
    }
    revision_two = {
        **revision_one,
        "event_time": "2026-07-11 09:00:00",
        "trade_date": "20260711",
        "content": "v2",
    }
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [revision_one]) == 1
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [revision_two]) == 1
    event_id = stable_event_id("tushare_news", "news", revision_one)
    expected_hashes = [
        hashlib.sha256(
            f"{event_id}|{revision}|{event_content_fingerprint(row)}".encode()
        ).hexdigest()
        for revision, row in enumerate((revision_one, revision_two), start=1)
    ]

    conn = sqlite3.connect(db_path)
    before = conn.execute(
        "SELECT event_hash, event_id, revision FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert [row[0] for row in before] == expected_hashes

    first = apply_migrations(db_path)
    second = apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    after = conn.execute(
        "SELECT event_hash, event_id, revision FROM market_events ORDER BY revision"
    ).fetchall()
    conn.close()
    assert first["event_identity_backfilled"] == 0
    assert second["event_identity_backfilled"] == 0
    assert after == before


def test_legacy_revision_order_is_stable_across_insertion_order(tmp_path: Path) -> None:
    def migrate_with_order(db_path: Path, hashes: list[str]) -> list[tuple]:
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        for event_hash in hashes:
            content = "v1" if event_hash == "legacy-a" else "v2"
            raw = {
                "id": "provider-42",
                "datetime": "2026-07-11 09:00:00",
                "title": "A",
                "content": content,
            }
            conn.execute(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, source_family, provider,
                    event_type, event_time, collected_at, title, content, raw_json
                ) VALUES (?, ?, 1, 'tushare', 'tushare_news', 'news', ?, ?, 'A', ?, ?)
                """,
                (
                    event_hash,
                    event_hash,
                    "2026-07-11 09:00:00",
                    "2026-07-11T09:01:00+00:00",
                    content,
                    json.dumps(raw, sort_keys=True),
                ),
            )
        conn.commit()
        conn.close()

        result = apply_migrations(db_path)
        assert result["event_identity_backfilled"] == 2
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT event_hash, event_id, revision FROM market_events ORDER BY event_hash"
        ).fetchall()
        conn.close()
        return rows

    forward = migrate_with_order(tmp_path / "forward.sqlite", ["legacy-a", "legacy-b"])
    reverse = migrate_with_order(tmp_path / "reverse.sqlite", ["legacy-b", "legacy-a"])

    assert forward == reverse
    assert [(row[0], row[2]) for row in forward] == [("legacy-a", 1), ("legacy-b", 2)]


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
