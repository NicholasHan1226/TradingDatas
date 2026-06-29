"""test_api.py — test client, test each endpoint returns 200 + correct format.

Tests module-level "API" functions (public interfaces):
collectors, bridge query functions, calendar queries.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# Crypto collector API
# ============================================================================

class TestCryptoCollector:
    """Test crypto_binance_collector public interface."""

    def test_sample_market_data_returns_correct_keys(self):
        from collectors.crypto_binance_collector import sample_market_data
        result = sample_market_data(
            symbols=["BTCUSDT", "ETHUSDT"],
            workflow_result_path="/tmp/test_collect.json",
            days=3,
        )
        required_keys = {"klines", "order_book_tickers", "funding_rates",
                         "open_interest", "health"}
        assert required_keys.issubset(set(result.keys()))

    def test_sample_klines_have_required_fields(self):
        from collectors.crypto_binance_collector import sample_market_data
        result = sample_market_data(
            symbols=["BTCUSDT"],
            workflow_result_path="/tmp/test_collect.json",
            days=3,
        )
        klines = result["klines"]
        assert len(klines) > 0
        for k in klines:
            for field in ("symbol", "open", "high", "low", "close",
                          "volume", "source", "status", "capital_layer",
                          "workflow_result_path"):
                assert field in k, f"Missing field: {field}"

    def test_sample_health_rows_have_status(self):
        from collectors.crypto_binance_collector import sample_market_data
        result = sample_market_data(
            symbols=["BTCUSDT", "ETHUSDT"],
            workflow_result_path="/tmp/test_collect.json",
        )
        for h in result["health"]:
            assert h["status"] == "ok"
            assert "dataset" in h
            assert h["capital_layer"] == "shadow"

    def test_sample_data_metadata_is_correct(self):
        from collectors.crypto_binance_collector import sample_market_data
        result = sample_market_data(
            symbols=["SOLUSDT"],
            workflow_result_path="/tmp/test_collect.json",
        )
        for dataset_name, rows in result.items():
            if dataset_name == "health":
                continue
            for row in rows:
                assert row["capital_layer"] == "shadow", \
                    f"Wrong capital_layer in {dataset_name}"
                assert row["status"] == "ok", \
                    f"Wrong status in {dataset_name}"


# ============================================================================
# Polymarket collector API
# ============================================================================

class TestPMCollector:
    """Test pm_polymarket_collector public interface."""

    def test_sample_market_data_returns_correct_keys(self):
        from collectors.pm_polymarket_collector import sample_market_data
        result = sample_market_data(
            event_tags=["crypto", "politics"],
            workflow_result_path="/tmp/test_pm.json",
        )
        required_keys = {"events", "markets", "market_prices",
                         "order_books", "prices_history", "health"}
        assert required_keys.issubset(set(result.keys()))

    def test_sample_events_have_required_fields(self):
        from collectors.pm_polymarket_collector import sample_market_data
        result = sample_market_data(
            event_tags=["crypto"],
            workflow_result_path="/tmp/test_pm.json",
        )
        events = result["events"]
        assert len(events) > 0
        for ev in events:
            for field in ("event_id", "title", "tags", "source",
                          "status", "capital_layer", "is_real_money"):
                assert field in ev, f"Missing field: {field}"
            assert ev["is_real_money"] == "N"
            assert ev["capital_layer"] == "shadow"

    def test_sample_markets_have_required_fields(self):
        from collectors.pm_polymarket_collector import sample_market_data
        result = sample_market_data(
            event_tags=["crypto"],
            workflow_result_path="/tmp/test_pm.json",
        )
        markets = result["markets"]
        assert len(markets) > 0
        for m in markets:
            for field in ("market_id", "event_id", "question", "token_id",
                          "volume", "liquidity", "status", "is_real_money"):
                assert field in m, f"Missing field: {field}"
            assert m["is_real_money"] == "N"

    def test_sample_health_has_ok_status(self):
        from collectors.pm_polymarket_collector import sample_market_data
        result = sample_market_data(
            event_tags=["sports"],
            workflow_result_path="/tmp/test_pm.json",
        )
        for h in result["health"]:
            assert h["health"] == "ok"
            assert "dataset" in h

    def test_parse_market_with_none_id_returns_none(self):
        from collectors.pm_polymarket_collector import _parse_market
        result = _parse_market({}, "ev1", NOW.isoformat(), "/tmp/test")
        assert result is None

    def test_market_price_from_data_with_valid_bid_ask(self):
        from collectors.pm_polymarket_collector import _market_price_from_data
        price = _market_price_from_data({
            "bestBid": 0.45,
            "bestAsk": 0.47,
        })
        assert price == pytest.approx(0.46, abs=0.001)

    def test_market_price_from_data_with_none(self):
        from collectors.pm_polymarket_collector import _market_price_from_data
        result = _market_price_from_data({})
        assert result is None

    def test_to_bool_variants(self):
        from collectors.pm_polymarket_collector import _to_bool
        assert _to_bool(True) is True
        assert _to_bool(False) is False
        assert _to_bool("true") is True
        assert _to_bool("TRUE") is True
        assert _to_bool("yes") is True
        assert _to_bool("1") is True
        assert _to_bool("false") is False
        assert _to_bool("no") is False
        assert _to_bool("0") is False
        assert _to_bool(0) is False
        assert _to_bool(1) is True

    def test_normalize_tags_returns_pipe_separated(self):
        from collectors.pm_polymarket_collector import _normalize_tags
        tags = [{"label": "Crypto"}, {"label": "Finance"}]
        result = _normalize_tags(tags)
        assert result == "Crypto|Finance"

    def test_normalize_tags_empty(self):
        from collectors.pm_polymarket_collector import _normalize_tags
        assert _normalize_tags([]) == ""

    def test_stringify_float(self):
        from collectors.pm_polymarket_collector import stringify_float
        assert stringify_float(3.14159) == "3.14159"
        assert stringify_float(0) == "0"
        assert stringify_float(None) == "0"
        assert stringify_float("invalid") == "0"


# ============================================================================
# Parquet loader API
# ============================================================================

class TestParquetLoader:
    """Test pm_parquet_loader public interface."""

    def test_parse_outcome_prices_json_format(self):
        from collectors.pm_parquet_loader import parse_outcome_prices
        p1, p2 = parse_outcome_prices([0.95, 0.05])
        assert p1 == pytest.approx(0.95)
        assert p2 == pytest.approx(0.05)

    def test_parse_outcome_prices_python_format(self):
        from collectors.pm_parquet_loader import parse_outcome_prices
        p1, p2 = parse_outcome_prices("[1, 0]")
        assert p1 == pytest.approx(1.0)
        assert p2 == pytest.approx(0.0)

    def test_parse_outcome_prices_none(self):
        from collectors.pm_parquet_loader import parse_outcome_prices
        assert parse_outcome_prices(None) == (None, None)
        assert parse_outcome_prices("") == (None, None)
        assert parse_outcome_prices("None") == (None, None)

    def test_parse_outcome_prices_single_element(self):
        from collectors.pm_parquet_loader import parse_outcome_prices
        result = parse_outcome_prices([0.5])
        assert result == (None, None)

    def test_compute_dataset_stats_no_data(self):
        from collectors.pm_parquet_loader import compute_dataset_stats
        result = compute_dataset_stats(Path("/nonexistent/markets.parquet"))
        assert result["status"] == "no_data"


# ============================================================================
# Calendar query API
# ============================================================================

class TestCalendarAPI:
    """Test calendar queries as if they were API endpoints."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        try:
            from reference.market_calendar import clear_cache
            clear_cache()
        except Exception:
            pass
        yield

    def test_is_trading_day_returns_bool(self):
        """Return type must be bool."""
        with patch("reference.market_calendar._call") as mock:
            from reference.market_calendar import is_trading_day, clear_cache
            clear_cache()
            mock.return_value = [{"cal_date": "20260629", "is_open": "1"}]
            result = is_trading_day(date(2026, 6, 29))
            assert isinstance(result, bool)

    def test_get_trading_days_returns_dates(self):
        with patch("reference.market_calendar._call") as mock:
            from reference.market_calendar import get_trading_days, clear_cache
            clear_cache()
            mock.return_value = [
                {"cal_date": "20260629", "is_open": "1"},
                {"cal_date": "20260630", "is_open": "1"},
            ]
            result = get_trading_days("20260629", "20260630")
            assert len(result) == 2
            assert all(isinstance(d, date) for d in result)

    def test_get_next_trading_day_format(self):
        with patch("reference.market_calendar._call") as mock:
            from reference.market_calendar import get_next_trading_day, clear_cache
            clear_cache()
            mock.return_value = [
                {"cal_date": "20260701", "is_open": "1"},
            ]
            result = get_next_trading_day(date(2026, 6, 29))
            assert result is None or isinstance(result, date)


# ============================================================================
# DB read API
# ============================================================================

class TestDBReadAPI:
    """Test the SQLite read-model queries as API endpoints."""

    def test_query_assets_returns_list(self, tmp_db_with_data):
        conn = tmp_db_with_data
        rows = conn.execute("SELECT * FROM market_assets").fetchall()
        assert isinstance(rows, list)
        assert len(rows) >= 1

    def test_query_bars_returns_list(self, tmp_db_with_data):
        conn = tmp_db_with_data
        rows = conn.execute(
            "SELECT * FROM market_bars_daily WHERE trade_date = ?",
            ("20260629",)
        ).fetchall()
        assert len(rows) >= 1

    def test_query_events_returns_list(self, tmp_db_with_data):
        conn = tmp_db_with_data
        rows = conn.execute("SELECT * FROM market_events").fetchall()
        assert len(rows) >= 1

    def test_row_factory_gives_dict_access(self, tmp_db_with_data):
        conn = tmp_db_with_data
        row = conn.execute(
            "SELECT * FROM market_assets LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["symbol"] is not None  # dict-style access
        assert row["market"] is not None
