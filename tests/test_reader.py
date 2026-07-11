"""test_reader.py — mock storage, test each function return format + metadata + error handling.

Tests read-side functions from storage/schema.py, bridge/ modules,
and reference/market_calendar.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


# ============================================================================
# storage/schema.py tests
# ============================================================================

class TestSchemaSQL:
    """Validate the SCHEMA_SQL definition."""

    def test_schema_is_nonempty_string(self):
        from storage.schema import SCHEMA_SQL
        assert isinstance(SCHEMA_SQL, str)
        assert len(SCHEMA_SQL) > 100

    def test_schema_contains_all_expected_tables(self):
        from storage.schema import SCHEMA_SQL
        required_tables = [
            "market_assets", "market_bars_daily", "market_bars_intraday",
            "market_events", "market_pm_markets", "market_pm_prices",
            "market_factors", "market_ingest_runs", "market_coverage_status",
            "market_backfill_status", "provider_interface_matrix",
            "market_relationships", "market_fund_portfolio",
        ]
        schema_upper = SCHEMA_SQL.upper()
        for table in required_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL, \
                f"Missing table: {table}"

    def test_schema_executes_without_error(self, tmp_db: sqlite3.Connection):
        """Schema should execute cleanly."""
        from storage.schema import SCHEMA_SQL
        tmp_db.executescript(SCHEMA_SQL)
        tables = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "market_assets" in table_names
        assert "market_bars_daily" in table_names
        assert "market_events" in table_names

    def test_schema_is_idempotent(self, tmp_db: sqlite3.Connection):
        """Running schema twice should not error."""
        from storage.schema import SCHEMA_SQL
        tmp_db.executescript(SCHEMA_SQL)
        tmp_db.executescript(SCHEMA_SQL)  # second run — no error


# ============================================================================
# bridge/marketgraph_marketdata_db.py tests
# ============================================================================

class TestMarketdataDB:
    """Test the marketdata database bridge functions."""

    def test_connect_returns_connection(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_connect_sets_row_factory(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        assert conn.row_factory is not None
        conn.close()

    def test_connect_creates_schema(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) >= 11
        conn.close()

    def test_query_market_assets_returns_rows(self, tmp_db_with_data: sqlite3.Connection):
        conn = tmp_db_with_data
        rows = conn.execute(
            "SELECT * FROM market_assets WHERE market = ?", ("Ashare",)
        ).fetchall()
        assert len(rows) >= 1
        row = rows[0]
        assert row["symbol"] is not None
        assert row["market"] == "Ashare"
        assert isinstance(row["symbol"], str)

    def test_query_bars_daily_has_ohlcv(self, tmp_db_with_data: sqlite3.Connection):
        conn = tmp_db_with_data
        rows = conn.execute(
            "SELECT * FROM market_bars_daily WHERE symbol = ?", ("000001.SZ",)
        ).fetchall()
        assert len(rows) >= 1
        row = rows[0]
        for field in ("open", "high", "low", "close", "volume"):
            assert field in row.keys()
            assert row[field] is not None


# ============================================================================
# reader event tests
# ============================================================================

class TestReaderEvents:
    def test_event_cursor_is_opaque_endpoint_bound_and_snapshot_checked(self):
        from pagination import decode_cursor, encode_cursor

        cursor = encode_cursor("events", "snap-1", ("2026-07-11T09:30:00Z", "event-1", 2))

        assert "event-1" not in cursor
        assert decode_cursor(cursor, scope="events", snapshot_id="snap-1") == (
            "2026-07-11T09:30:00Z",
            "event-1",
            2,
        )
        with pytest.raises(ValueError, match="^invalid cursor$"):
            decode_cursor(cursor, scope="industry_taxonomy")
        with pytest.raises(ValueError, match="^cursor snapshot mismatch$"):
            decode_cursor(cursor, scope="events", snapshot_id="snap-2")

    @pytest.mark.parametrize("cursor", ["", "not-base64!", "e30"])
    def test_event_cursor_rejects_malformed_payloads(self, cursor: str):
        from pagination import decode_cursor

        with pytest.raises(ValueError, match="^invalid cursor$"):
            decode_cursor(cursor, scope="events")

    def test_events_cursor_has_no_duplicates_across_equal_timestamps(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"h{idx}",
                        1,
                        "unit",
                        "news",
                        "2026-07-11T09:30:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T09:31:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 5)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=2)
        second = reader.get_events_page(limit=2, cursor=first["next_cursor"])
        legacy_first = reader.get_events(limit=2)

        ids = [row["data"]["event_hash"] for row in first["rows"] + second["rows"]]
        assert ids == ["h4", "h3", "h2", "h1"]
        assert len(ids) == len(set(ids))
        assert legacy_first == first["rows"]
        assert first["row_count"] == 2
        assert second == {"rows": second["rows"], "next_cursor": None, "row_count": 2}

    @pytest.mark.parametrize(
        ("legacy_event_id", "legacy_revision"),
        [
            (None, 1),
            ("", 1),
            ("legacy-event-4", None),
        ],
    )
    def test_events_cursor_traverses_legacy_nullable_identity_boundary(
        self,
        tmp_path: Path,
        monkeypatch,
        legacy_event_id: str | None,
        legacy_revision: int | None,
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"legacy-h{idx}",
                        legacy_event_id if idx == 4 else f"event-{idx}",
                        legacy_revision if idx == 4 else 1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{6 - idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 6)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=4)
        assert first["next_cursor"] is not None
        from pagination import decode_cursor

        assert decode_cursor(first["next_cursor"], scope="events") == (
            "2026-07-11T09:32:00+00:00",
            legacy_event_id or "legacy-h4",
            legacy_revision if legacy_revision is not None else 0,
        )
        second = reader.get_events_page(limit=4, cursor=first["next_cursor"])

        event_hashes = [
            row["data"]["event_hash"]
            for row in first["rows"] + second["rows"]
        ]
        assert event_hashes == [f"legacy-h{idx}" for idx in range(1, 6)]
        assert len(event_hashes) == len(set(event_hashes))
        assert second["next_cursor"] is None

    @pytest.mark.parametrize("bad_event_hash", [None, ""])
    def test_events_page_fails_closed_when_cursor_boundary_has_no_stable_identity(
        self, tmp_path: Path, monkeypatch, bad_event_hash: str | None
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        bad_event_hash if idx == 4 else f"stable-h{idx}",
                        None if idx == 4 else f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        "2026-07-11T09:30:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 6)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        page = reader.get_events_page(limit=4)

        assert page["row_count"] == 0
        assert page["next_cursor"] is None
        assert page["rows"][0]["degraded"] is True
        assert "stable event identity" in page["rows"][0]["lineage"]["reason"]

    def test_events_page_preserves_degraded_shape(self, tmp_path: Path, monkeypatch):
        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", tmp_path / "missing_marketdata.sqlite")
        reader.clear_caches()

        page = reader.get_events_page(limit=2)

        assert page["rows"][0]["degraded"] is True
        assert page["rows"][0]["data"] == {}
        assert page["next_cursor"] is None
        assert page["row_count"] == 0

    def test_events_subject_type_filters_before_page_limit_and_allows_missing_type(
        self, tmp_path: Path, monkeypatch
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        json.dumps({"subject_type": subject_type}) if subject_type else "{}",
                    )
                    for idx, subject_type in ((1, None), (2, "stock"), (3, "bond"), (4, "bond"))
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        page = reader.get_events_page(limit=2, subject_type="stock")

        assert [row["data"]["event_hash"] for row in page["rows"]] == ["h2", "h1"]
        assert page["row_count"] == 2
        assert page["next_cursor"] is None

    def test_events_subject_type_cursor_does_not_skip_matching_rows(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        json.dumps({"subject_type": subject_type}),
                    )
                    for idx, subject_type in (
                        (1, "stock"),
                        (2, "bond"),
                        (3, "stock"),
                        (4, "bond"),
                        (5, "bond"),
                        (6, "stock"),
                    )
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=2, subject_type="stock")
        second = reader.get_events_page(
            limit=2,
            subject_type="stock",
            cursor=first["next_cursor"],
        )

        assert [row["data"]["event_hash"] for row in first["rows"]] == ["h6", "h3"]
        assert [row["data"]["event_hash"] for row in second["rows"]] == ["h1"]
        assert first["row_count"] == 2
        assert first["next_cursor"] is not None
        assert second["row_count"] == 1
        assert second["next_cursor"] is None

    @pytest.mark.parametrize(
        "cursor",
        ["not-a-cursor", pytest.param(None, id="cross-scope")],
    )
    def test_events_page_rejects_invalid_cursor_before_reader_degradation(self, cursor, monkeypatch):
        import reader
        from pagination import encode_cursor

        if cursor is None:
            cursor = encode_cursor("industry_taxonomy", "", ("L1", "801010.SI", "n1"))

        with pytest.raises(ValueError, match="^invalid cursor$"):
            reader.get_events_page(limit=2, cursor=cursor)

    def test_get_tushare_fut_basic_reads_futures_assets_not_ashare(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_assets (
                    market, symbol, name, asset_type, exchange, sector, list_date,
                    status, provider, source_file, updated_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "Futures",
                        "RB2609.SHF",
                        "螺纹钢2609",
                        "future",
                        "SHFE",
                        "",
                        "20260101",
                        "listed",
                        "tushare_fut_basic",
                        "fut_basic",
                        "2026-07-08T09:00:00",
                        "{}",
                    ),
                    (
                        "Ashare",
                        "000001.SZ",
                        "平安银行",
                        "stock",
                        "SZSE",
                        "银行",
                        "19910403",
                        "active",
                        "tushare_stock_basic",
                        "stock_basic",
                        "2026-07-08T09:00:00",
                        "{}",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        futures = reader.get_tushare("fut_basic")
        futures_alias = reader.get_tushare("fut_basic", market="CNFutures")
        stocks = reader.get_tushare("stock_basic")

        assert [row["data"]["symbol"] for row in futures] == ["RB2609.SHF"]
        assert [row["data"]["symbol"] for row in futures_alias] == ["RB2609.SHF"]
        assert all(row["data"]["market"] == "Futures" for row in futures)
        assert [row["data"]["symbol"] for row in stocks] == ["000001.SZ"]

    def test_get_tushare_fund_portfolio_reads_dedicated_table(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                """
                INSERT INTO market_fund_portfolio (
                    portfolio_hash, market, symbol, holding_symbol, ann_date, end_date,
                    market_value, amount, stk_mkv_ratio, stk_float_ratio,
                    provider, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "pf-1",
                    "Fund",
                    "000001.OF",
                    "600519.SH",
                    "20260422",
                    "20260331",
                    1200.0,
                    100.0,
                    3.5,
                    0.02,
                    "tushare_fund_portfolio",
                    "fund_portfolio_20260422",
                    "2026-07-09T15:00:00+00:00",
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_tushare("fund_portfolio", ts_code="000001.OF", start_date="20260401", end_date="20260430")

        assert len(rows) == 1
        assert rows[0]["data"]["symbol"] == "000001.OF"
        assert rows[0]["data"]["holding_symbol"] == "600519.SH"
        assert rows[0]["data"]["market_value"] == 1200.0
        assert rows[0]["provenance"]["source_id"] == "tushare_fund_portfolio"
        assert rows[0]["lineage"]["source"] == "db:market_fund_portfolio"

    def test_get_tushare_daily_without_dates_reads_latest_ashare_day(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_bars_daily (
                    market, symbol, trade_date, open, high, low, close,
                    volume, amount, provider, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("Ashare", "000001.SZ", "20260707", 10.0, 10.5, 9.9, 10.2, 1000.0, 999999.0, "tushare_daily", "old.csv", "2026-07-07T08:00:00+00:00", "{}"),
                    ("Ashare", "600000.SH", "20260708", 9.0, 9.1, 8.9, 9.0, 2000.0, 488055.0, "tushare_daily", "latest.csv", "2026-07-08T08:00:00+00:00", "{}"),
                    ("US", "AAPL", "20260708", 200.0, 201.0, 199.0, 200.5, 100.0, 20050.0, "tushare_us_daily", "us.csv", "2026-07-08T08:00:00+00:00", "{}"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_tushare("daily", limit=10)

        assert [row["data"]["symbol"] for row in rows] == ["600000.SH"]
        assert rows[0]["data"]["trade_date"] == "20260708"
        assert rows[0]["data"]["market"] == "Ashare"

    def test_get_events_filters_market_and_code_variants(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        collected_at = datetime.now(timezone.utc).isoformat()
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "evt-1",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "Ashare",
                        "SH600276",
                        "matched",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-2",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "US",
                        "AAPL.US",
                        "other",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-3",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "Futures",
                        "RB2609.SHF",
                        "futures matched",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-4",
                        "polymarket_news",
                        "policy",
                        "20260708",
                        "20260708",
                        "PredictionMarkets",
                        "pm-1",
                        "pm matched",
                        "",
                        "",
                        "polymarket_news",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="Ashare",
            subject_code="600276.SH",
            subject_type="stock",
        )

        assert [row["data"]["event_hash"] for row in rows] == ["evt-1"]

        futures_rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="CNFutures",
        )
        pm_rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="PM",
        )

        assert [row["data"]["event_hash"] for row in futures_rows] == ["evt-3"]
        assert [row["data"]["event_hash"] for row in pm_rows] == ["evt-4"]

    def test_get_events_reads_sqlite_market_events_only(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "event-1",
                    "tushare_anns_d",
                    "anns_d",
                    "20260708",
                    "20260708",
                    "Ashare",
                    "600276.SH",
                    "董事会公告",
                    "公告内容",
                    "https://example.com/ann",
                    "tushare_anns_d",
                    "anns_d_20260708.csv",
                    datetime.now(timezone.utc).isoformat(),
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="anns_d",
            market="Ashare",
            subject_code="600276.SH",
        )

        assert len(rows) == 1
        assert rows[0]["data"]["title"] == "董事会公告"
        assert rows[0]["provenance"]["source_id"] == "tushare_anns_d"
        assert rows[0]["lineage"]["source"] == "sqlite:market_events"

    def test_get_events_honors_reader_limit(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"event-{idx}",
                        "tushare_news",
                        "news",
                        f"2026070{idx}",
                        f"2026070{idx}",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "tushare_news",
                        "unit.csv",
                        datetime.now(timezone.utc).isoformat(),
                        "{}",
                    )
                    for idx in range(1, 4)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(limit=2)

        assert len(rows) == 2
        assert [row["data"]["title"] for row in rows] == ["event 3", "event 2"]

    def test_get_events_pushes_symbol_filter_before_limit(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            rows = []
            for idx in range(10):
                rows.append(
                    (
                        f"newer-{idx}",
                        "sec_edgar",
                        "sec_edgar:4",
                        f"2026-07-{20 + idx:02d}T00:00:00+00:00",
                        f"202607{20 + idx:02d}",
                        "US",
                        "CIK9999999999",
                        f"newer {idx}",
                        "",
                        "",
                        "SEC EDGAR submissions",
                        "sec_edgar_filings",
                        datetime.now(timezone.utc).isoformat(),
                        "{}",
                    )
                )
            rows.append(
                (
                    "target-old",
                    "sec_edgar",
                    "sec_edgar:4",
                    "2026-07-01T00:00:00+00:00",
                    "20260701",
                    "US",
                    "CIK0000320193",
                    "Apple Form 4",
                    "",
                    "",
                    "SEC EDGAR submissions",
                    "sec_edgar_filings",
                    datetime.now(timezone.utc).isoformat(),
                    "{}",
                )
            )
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        result = reader.get_events(
            market="US",
            subject_code="CIK0000320193",
            event_type="sec_edgar:4",
            limit=2,
        )

        assert [row["data"]["event_hash"] for row in result] == ["target-old"]

    def test_degraded_empty_is_stale_and_unfresh(self):
        import reader

        rows = reader._degraded_empty("sqlite:market_events", "missing sqlite db")

        assert rows[0]["degraded"] is True
        assert rows[0]["data"] == {}
        assert rows[0]["freshness"]["stale"] is True
        assert rows[0]["freshness"]["score"] == 0.0

    def test_get_events_preserves_degraded_empty_when_filters_are_present(self, tmp_path: Path, monkeypatch):
        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", tmp_path / "missing_marketdata.sqlite")
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            market="Ashare",
            subject_code="600276.SH",
        )

        assert rows[0]["degraded"] is True
        assert rows[0]["data"] == {}
        assert "missing sqlite db" in rows[0]["lineage"]["reason"]

# ============================================================================
# reference/market_calendar.py tests
# ============================================================================

class TestMarketCalendar:
    """Test market calendar functions with a SharedSignals read-model cache."""

    @pytest.fixture(autouse=True)
    def calendar_db(self, tmp_path, monkeypatch):
        """Clear cache before each test."""
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE market_bars_daily (
                market TEXT,
                symbol TEXT,
                trade_date TEXT,
                close REAL
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_bars_daily VALUES (?, ?, ?, ?)",
            [
                ("Ashare", "000001.SZ", "20260629", 10.0),
                ("Ashare", "000001.SZ", "20260630", 10.1),
                ("Ashare", "000001.SZ", "20260701", 10.2),
            ],
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("SHARED_SIGNALS_DB", str(db_path))
        from reference.market_calendar import clear_cache
        clear_cache()
        yield
        clear_cache()

    def test_is_trading_day_true_for_cached_day(self):
        """Cached A-share daily bar date should return True."""
        from reference.market_calendar import is_trading_day

        result = is_trading_day(date(2026, 6, 29))
        assert result is True

    def test_is_trading_day_false_for_weekend(self):
        """Weekend without cached rows should return False."""
        from reference.market_calendar import is_trading_day

        result = is_trading_day(date(2026, 6, 28))
        assert result is False

    def test_get_trading_days_returns_list(self):
        """Should return sorted list of date objects."""
        from reference.market_calendar import get_trading_days

        result = get_trading_days(date(2026, 6, 29), date(2026, 7, 1))
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(d, date) for d in result)

    def test_get_trading_days_swaps_reversed_range(self):
        """Start > end should be swapped."""
        from reference.market_calendar import get_trading_days

        result = get_trading_days(date(2026, 6, 30), date(2026, 6, 29))
        assert len(result) == 2

    def test_get_next_trading_day_returns_date_or_none(self):
        """Should return next trading day or None."""
        from reference.market_calendar import get_next_trading_day

        result = get_next_trading_day(date(2026, 6, 29))
        assert result == date(2026, 6, 30)

    def test_get_next_trading_day_include_today(self):
        """include_today=True on trading day should return today."""
        from reference.market_calendar import get_next_trading_day

        result = get_next_trading_day(date(2026, 6, 29), include_today=True)
        assert result == date(2026, 6, 29)

    def test_to_date_parses_string_formats(self):
        from reference.market_calendar import _to_date
        d1 = _to_date("2026-06-29")
        d2 = _to_date("2026/06/29")
        d3 = _to_date("20260629")
        assert d1 == d2 == d3 == date(2026, 6, 29)

    def test_to_date_raises_on_invalid(self):
        from reference.market_calendar import _to_date
        with pytest.raises(ValueError):
            _to_date("not a date")
        with pytest.raises(ValueError):
            _to_date("2026-13-01")

    def test_raises_on_uncached_weekday_range(self):
        """Empty cache for a weekday range should raise instead of calling providers."""
        from reference.market_calendar import (
            TradingCalendarUnavailableError, get_trading_days, clear_cache,
        )
        clear_cache()
        with pytest.raises(TradingCalendarUnavailableError):
            get_trading_days(date(2026, 7, 2), date(2026, 7, 3))


class TestPMPriceReader:
    def test_get_pm_prices_reads_market_pm_prices(self, tmp_path, monkeypatch):
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE market_pm_prices (
                price_hash TEXT PRIMARY KEY,
                market_id TEXT,
                token_id TEXT,
                price_time TEXT,
                price REAL,
                provider TEXT,
                source_file TEXT,
                collected_at TEXT,
                raw_json TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_pm_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("h1", "pm-1", "yes", "2026-07-07T00:00:00Z", 0.41, "polymarket", "unit", "2026-07-07T00:00:01Z", "{}"),
                ("h2", "pm-1", "yes", "2026-07-07T00:05:00Z", 0.43, "polymarket", "unit", "2026-07-07T00:05:01Z", "{}"),
                ("h3", "pm-2", "yes", "2026-07-07T00:04:00Z", 0.52, "polymarket", "unit", "2026-07-07T00:04:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_pm_prices(market_id="pm-1", limit=1)

        assert len(rows) == 1
        assert rows[0]["data"]["market_id"] == "pm-1"
        assert rows[0]["data"]["price"] == 0.43
        assert rows[0]["provenance"]["source_tier"] == "polymarket"
        assert rows[0]["lineage"]["table"] == "market_pm_prices"


class TestMarketDataReader:
    def test_get_market_data_supports_intraday_freq(self, tmp_path, monkeypatch):
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO market_bars_intraday (
                market, symbol, bar_time, trade_date, interval,
                open, high, low, close, volume, amount,
                provider, source_file, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Ashare", "000001.SZ", "2026-07-08 09:35:00", "20260708", "5min", 10, 10.2, 9.9, 10.1, 1000, 10100, "tushare_rt_min", "unit.csv", "2026-07-08T09:35:01Z", "{}"),
                ("Ashare", "000001.SZ", "2026-07-08 09:40:00", "20260708", "5min", 10.1, 10.3, 10.0, 10.2, 1100, 11220, "tushare_rt_min", "unit.csv", "2026-07-08T09:40:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_market_data("000001.SZ", "20260708", "20260708", freq="5m")

        assert [row["data"]["bar_time"] for row in rows] == [
            "2026-07-08 09:35:00",
            "2026-07-08 09:40:00",
        ]
        assert rows[0]["provenance"]["source_id"] == "tushare_rt_min"
        assert rows[0]["lineage"]["filters"]["freq"] == "5min"

    def test_get_market_data_intraday_without_dates_uses_latest_trade_date(self, tmp_path, monkeypatch):
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO market_bars_intraday (
                market, symbol, bar_time, trade_date, interval,
                open, high, low, close, volume, amount,
                provider, source_file, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Ashare", "000001.SZ", "2026-07-07 15:00:00", "20260707", "5min", 9, 9, 9, 9, 100, 900, "tushare_rt_min", "unit.csv", "2026-07-07T15:00:01Z", "{}"),
                ("Ashare", "000001.SZ", "2026-07-08 09:35:00", "20260708", "5min", 10, 10.2, 9.9, 10.1, 1000, 10100, "tushare_rt_min", "unit.csv", "2026-07-08T09:35:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_market_data("000001.SZ", None, None, freq="5m")

        assert len(rows) == 1
        assert rows[0]["data"]["trade_date"] == "20260708"
