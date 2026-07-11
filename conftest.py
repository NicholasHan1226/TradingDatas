"""pytest fixtures for SharedSignals test suite.

Provides: mock SQLite (in-memory with full schema) and sample data generators.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure SharedSignals root is importable
_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "000001.SZ", "600519.SH", "AAPL", "TSLA",
]

NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# SQLite fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_path() -> str:
    """Return a path to a temp SQLite database (not yet created)."""
    fd, path = tempfile.mkstemp(suffix=".sqlite", prefix="test_sharedsignals_")
    os.close(fd)
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def tmp_db(tmp_db_path: str) -> sqlite3.Connection:
    """In-memory-ish SQLite with full SharedSignals schema initialized."""
    conn = sqlite3.connect(tmp_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    from storage.schema import SCHEMA_SQL
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def tmp_db_with_data(tmp_db: sqlite3.Connection) -> sqlite3.Connection:
    """SQLite with schema + sample rows in key tables."""
    conn = tmp_db
    ts = NOW.isoformat()
    trade_date = "20260629"

    # market_assets
    for sym in ["000001.SZ", "600519.SH", "AAPL", "TSLA", "BTCUSDT"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_assets
            (market, symbol, name, asset_type, exchange, sector, list_date,
             status, provider, source_file, updated_at, raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("Ashare", sym, f"Asset {sym}", "stock", "SSE", "Finance",
             "20000101", "active", "tushare", "batch_001", ts, "{}"),
        )

    # market_bars_daily
    for sym, close in [("000001.SZ", 12.50), ("600519.SH", 1680.0), ("AAPL", 220.0)]:
        conn.execute(
            "INSERT OR REPLACE INTO market_bars_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("Ashare" if sym.endswith((".SZ", ".SH")) else "US",
             sym, trade_date, close - 1.0, close + 0.5, close - 0.3,
             close, 1_000_000, close * 1_000_000,
             "tushare", "batch_001", ts, "{}"),
        )

    # market_events
    import hashlib
    url = "https://example.com/news/1"
    event_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    conn.execute(
        """
        INSERT OR REPLACE INTO market_events
        (event_hash, provider, event_type, event_time, trade_date, market,
         symbol, title, content, url, source, source_file, collected_at, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (event_hash, "rss", "news", ts, trade_date, "Ashare",
         "000001.SZ", "Test Event", "Sample content", url,
         "example_rss", "batch_001", ts, "{}"),
    )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Market data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_ohlcv_rows() -> list[dict[str, Any]]:
    """Sample daily OHLCV rows."""
    return [
        {"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
         "open": 12.0, "high": 12.8, "low": 11.9, "close": 12.5,
         "volume": 50_000_000, "amount": 625_000_000,
         "provider": "tushare", "source_file": "batch_001"},
        {"market": "Crypto", "symbol": "BTCUSDT", "trade_date": "20260629",
         "open": 145000.0, "high": 152000.0, "low": 144000.0, "close": 150000.0,
         "volume": 25_000, "amount": 3_750_000_000,
         "provider": "binance", "source_file": "batch_001"},
    ]


@pytest.fixture
def sample_event_rows() -> list[dict[str, Any]]:
    """Sample event/news rows."""
    return [
        {"event_hash": "abc123", "provider": "rss", "event_type": "news",
         "event_time": NOW.isoformat(), "trade_date": "20260629",
         "market": "Ashare", "symbol": "000001.SZ",
         "title": "Fed holds rates", "content": "The Fed...",
         "url": "https://example.com/news/1", "source": "reuters",
         "source_file": "batch_001", "collected_at": NOW.isoformat(),
         "raw_json": "{}"},
        {"event_hash": "def456", "provider": "tavily", "event_type": "analysis",
         "event_time": NOW.isoformat(), "trade_date": "20260629",
         "market": "US", "symbol": "AAPL",
         "title": "Apple earnings", "content": "Apple reported...",
         "url": "https://example.com/news/2", "source": "tavily",
         "source_file": "batch_001", "collected_at": NOW.isoformat(),
         "raw_json": "{}"},
    ]


# ---------------------------------------------------------------------------
# Bad / edge-case data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bad_data_missing_fields() -> list[dict[str, Any]]:
    """Rows with missing required fields."""
    return [
        {},  # completely empty
        {"trade_date": "20260629"},  # missing OHLCV
        {"market": "Ashare", "symbol": "", "close": None},  # empty/None values
    ]


@pytest.fixture
def bad_data_outliers() -> list[dict[str, Any]]:
    """Rows with outlier / anomalous values."""
    return [
        {"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
         "open": -5.0, "high": 10.0, "low": 10.0, "close": 12.5,
         "volume": 1_000_000},  # negative open
        {"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
         "open": 12.0, "high": 999_999.0, "low": 10.0, "close": 12.5,
         "volume": 1_000_000},  # extreme high
        {"market": "Crypto", "symbol": "BTCUSDT", "trade_date": "20260629",
         "open": 0, "high": 0, "low": 0, "close": 0,
         "volume": 0},  # all zeros
        {"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260629",
         "open": 12.0, "high": 100.0, "low": 10.0, "close": None,
         "volume": 1_000_000},  # None close
    ]


@pytest.fixture
def bad_data_expired() -> list[dict[str, Any]]:
    """Rows with expired/stale timestamps."""
    old = (NOW - timedelta(days=365)).isoformat()
    very_old = "2020-01-01T00:00:00+00:00"
    return [
        {"event_hash": "old1", "provider": "rss", "event_time": old,
         "collected_at": old, "trade_date": "20250101",
         "title": "Old news", "url": "https://example.com/old"},
        {"event_hash": "old2", "provider": "rss", "event_time": very_old,
         "collected_at": very_old, "trade_date": "20200101",
         "title": "Ancient news", "url": "https://example.com/ancient"},
    ]


# ---------------------------------------------------------------------------
# Duplicate data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def duplicate_url_rows() -> list[dict[str, Any]]:
    """Rows with duplicate URLs (same or normalized)."""
    return [
        {"event_hash": "h1", "title": "News A",
         "url": "https://example.com/news/a", "source": "rss_a",
         "event_time": NOW.isoformat()},
        {"event_hash": "h2", "title": "News A duplicate",
         "url": "https://example.com/news/a", "source": "rss_b",
         "event_time": NOW.isoformat()},
        {"event_hash": "h3", "title": "News A variant",
         "url": "https://example.com/news/a?utm_source=twitter", "source": "rss_c",
         "event_time": NOW.isoformat()},
        {"event_hash": "h4", "title": "News B",
         "url": "https://example.com/news/b", "source": "rss_a",
         "event_time": NOW.isoformat()},
    ]
