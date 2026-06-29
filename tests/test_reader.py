"""test_reader.py — mock storage, test each function return format + metadata + error handling.

Tests read-side functions from storage/schema.py, bridge/ modules,
and reference/market_calendar.py.
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure SharedSignals is importable
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

    def test_schema_contains_all_11_tables(self):
        from storage.schema import SCHEMA_SQL
        required_tables = [
            "market_assets", "market_bars_daily", "market_bars_intraday",
            "market_events", "market_pm_markets", "market_pm_prices",
            "market_factors", "market_ingest_runs", "market_coverage_status",
            "market_backfill_status", "provider_interface_matrix",
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
            "SELECT name FROM sqlite_master WHERE type=table ORDER BY name"
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
            "SELECT name FROM sqlite_master WHERE type=table"
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
        # verify column access by name works (row_factory check)
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
# bridge/marketgraph_runtime_bridge.py tests
# ============================================================================

class TestRuntimeBridge:
    """Test the runtime bridge (staging -> CSV) functions."""

    def test_streams_have_all_6_streams(self):
        from bridge.marketgraph_runtime_bridge import STREAMS
        assert len(STREAMS) == 6
        expected = {
            "event_candidates", "collection_runs",
            "enterprise_relation_source_results",
            "event_candidate_repair_workpack",
            "market_move_observations", "sentiment_signals",
        }
        assert set(STREAMS.keys()) == expected

    def test_stream_spec_has_required_fields(self):
        from bridge.marketgraph_runtime_bridge import STREAMS
        for name, spec in STREAMS.items():
            assert spec.name == name
            assert spec.target is not None
            assert len(spec.key_fields) >= 1
            assert isinstance(spec.boundary, str) and len(spec.boundary) > 0

    def test_read_csv_returns_fieldnames_and_rows(self, tmp_csv_dir: Path):
        from bridge.marketgraph_runtime_bridge import read_csv
        path = tmp_csv_dir / "data" / "intake" / "event_candidates.csv"
        fieldnames, rows = read_csv(path)
        assert isinstance(fieldnames, list)
        assert isinstance(rows, list)
        assert len(fieldnames) >= 4
        assert len(rows) == 2
        assert "candidate_id" in fieldnames
        assert rows[0]["candidate_id"] == "c001"

    def test_read_csv_handles_empty_file(self, tmp_csv_dir: Path):
        from bridge.marketgraph_runtime_bridge import read_csv
        empty = tmp_csv_dir / "data" / "intake" / "empty.csv"
        empty.write_text("col1,col2\n", encoding="utf-8")
        fieldnames, rows = read_csv(empty)
        assert fieldnames == ["col1", "col2"]
        assert rows == []

    def test_read_csv_raises_on_missing(self):
        from bridge.marketgraph_runtime_bridge import read_csv
        with pytest.raises(FileNotFoundError):
            read_csv(Path("/nonexistent/path.csv"))

    def test_write_csv_creates_file(self, tmp_csv_dir: Path):
        from bridge.marketgraph_runtime_bridge import write_csv, read_csv
        path = tmp_csv_dir / "data" / "intake" / "output.csv"
        write_csv(path, ["id", "name"], [
            {"id": "1", "name": "test1"},
            {"id": "2", "name": "test2"},
        ])
        assert path.exists()
        _, rows = read_csv(path)
        assert len(rows) == 2
        assert rows[0]["id"] == "1"

    def test_write_csv_ignores_extra_fields(self, tmp_csv_dir: Path):
        from bridge.marketgraph_runtime_bridge import write_csv, read_csv
        path = tmp_csv_dir / "data" / "intake" / "filtered.csv"
        write_csv(path, ["id"], [
            {"id": "1", "extra": "ignored", "more": "also_ignored"},
        ])
        _, rows = read_csv(path)
        assert "extra" not in rows[0]
        assert rows[0]["id"] == "1"


# ============================================================================
# reference/market_calendar.py tests
# ============================================================================

class TestMarketCalendar:
    """Test market calendar functions with mocked Tushare."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        try:
            from reference.market_calendar import clear_cache
            clear_cache()
        except Exception:
            pass
        yield

    @pytest.fixture
    def mock_tushare_call(self):
        """Mock the _call function to return controlled data."""
        with patch("reference.market_calendar._call") as mock:
            yield mock

    def test_is_trading_day_true_for_weekday(self, mock_tushare_call):
        """Weekday with is_open=1 should return True."""
        from reference.market_calendar import is_trading_day, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260629", "is_open": "1", "exchange": "SSE"}
        ]
        result = is_trading_day(date(2026, 6, 29))
        assert result is True

    def test_is_trading_day_false_for_weekend(self, mock_tushare_call):
        """Weekend with is_open=0 should return False."""
        from reference.market_calendar import is_trading_day, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260628", "is_open": "0", "exchange": "SSE"}
        ]
        result = is_trading_day(date(2026, 6, 28))
        assert result is False

    def test_get_trading_days_returns_list(self, mock_tushare_call):
        """Should return sorted list of date objects."""
        from reference.market_calendar import get_trading_days, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260629", "is_open": "1"},
            {"cal_date": "20260630", "is_open": "1"},
            {"cal_date": "20260701", "is_open": "1"},
        ]
        result = get_trading_days(date(2026, 6, 29), date(2026, 7, 1))
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(d, date) for d in result)

    def test_get_trading_days_swaps_reversed_range(self, mock_tushare_call):
        """Start > end should be swapped."""
        from reference.market_calendar import get_trading_days, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260629", "is_open": "1"},
            {"cal_date": "20260630", "is_open": "1"},
        ]
        result = get_trading_days(date(2026, 6, 30), date(2026, 6, 29))
        assert len(result) == 2

    def test_get_next_trading_day_returns_date_or_none(self, mock_tushare_call):
        """Should return next trading day or None."""
        from reference.market_calendar import get_next_trading_day, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260630", "is_open": "1"},
            {"cal_date": "20260701", "is_open": "1"},
        ]
        result = get_next_trading_day(date(2026, 6, 29))
        assert result == date(2026, 6, 30) or result is None

    def test_get_next_trading_day_include_today(self, mock_tushare_call):
        """include_today=True on trading day should return today."""
        from reference.market_calendar import get_next_trading_day, clear_cache
        clear_cache()
        mock_tushare_call.return_value = [
            {"cal_date": "20260629", "is_open": "1"},
        ]
        # first call for is_trading_day, second for the range
        mock_tushare_call.side_effect = [
            [{"cal_date": "20260629", "is_open": "1"}],  # is_trading_day
            [{"cal_date": "20260629", "is_open": "1"}],  # range
        ]
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

    def test_raises_when_tushare_unavailable(self):
        """When _call is None, should raise RuntimeError."""
        import reference.market_calendar as mc
        saved = mc._call
        mc._call = None
        mc.clear_cache()
        try:
            with pytest.raises(RuntimeError, match="unavailable"):
                mc.is_trading_day(date(2026, 6, 29))
        finally:
            mc._call = saved
            mc.clear_cache()

    def test_raises_on_empty_response(self, mock_tushare_call):
        """Empty API response for a weekday range should raise."""
        from reference.market_calendar import (
            TradingCalendarUnavailableError, get_trading_days, clear_cache,
        )
        clear_cache()
        mock_tushare_call.return_value = []
        with pytest.raises(TradingCalendarUnavailableError):
            get_trading_days(date(2026, 6, 29), date(2026, 7, 1))

    @staticmethod
    def patch(target, **kwargs):
        """Helper to create a unittest patch (imported from mock)."""
        from unittest.mock import patch as _patch
        return _patch(target, **kwargs)


# Import patch from mock module for the fixture
from unittest.mock import patch
