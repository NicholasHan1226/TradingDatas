"""pytest fixtures for SharedSignals test suite.

Provides: mock SQLite (in-memory with full schema), mock CSV dirs,
mock RSS feed configs, and sample data generators.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
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
            "INSERT OR REPLACE INTO market_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
        "INSERT OR REPLACE INTO market_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_hash, "rss", "news", ts, trade_date, "Ashare",
         "000001.SZ", "Test Event", "Sample content", url,
         "example_rss", "batch_001", ts, "{}"),
    )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_csv_dir() -> Path:
    """Temp directory with sample CSV files mimicking the intake structure."""
    with tempfile.TemporaryDirectory(prefix="test_csv_") as d:
        root = Path(d)
        intake = root / "data" / "intake"
        intake.mkdir(parents=True)

        # event_candidates.csv
        _write_csv(intake / "event_candidates.csv",
                   ["candidate_id", "title", "url", "source", "status", "collected_at"],
                   [{"candidate_id": "c001", "title": "Fed Meeting",
                     "url": "https://example.com/fed", "source": "rss",
                     "status": "needs_review", "collected_at": NOW.isoformat()},
                    {"candidate_id": "c002", "title": "Earnings Beat",
                     "url": "https://example.com/earn", "source": "rss",
                     "status": "verified", "collected_at": NOW.isoformat()}])

        # sentiment_signals.csv
        _write_csv(intake / "sentiment_signals.csv",
                   ["signal_id", "title", "sentiment", "source", "collected_at"],
                   [{"signal_id": "s001", "title": "Bullish crypto",
                     "sentiment": "positive", "source": "rss",
                     "collected_at": NOW.isoformat()}])

        # collection_runs.csv
        _write_csv(intake / "collection_runs.csv",
                   ["run_id", "started_at", "finished_at", "status", "rows_read", "rows_written"],
                   [{"run_id": "r001", "started_at": NOW.isoformat(),
                     "finished_at": NOW.isoformat(), "status": "success",
                     "rows_read": "100", "rows_written": "95"}])

        yield root


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# RSS fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_rss_feed_config() -> dict[str, Any]:
    """Sample RSS feed configuration."""
    return {
        "feeds": [
            {"name": "reuters_top", "url": "https://example.com/rss/reuters",
             "category": "news", "health": "healthy", "priority": 1},
            {"name": "bloomberg_markets", "url": "https://example.com/rss/bloomberg",
             "category": "markets", "health": "healthy", "priority": 2},
            {"name": "coindesk_crypto", "url": "https://example.com/rss/coindesk",
             "category": "crypto", "health": "intermittent", "priority": 3},
        ],
        "fallback_order": ["reuters_top", "bloomberg_markets", "coindesk_crypto"],
    }


@pytest.fixture
def mock_rss_items() -> list[dict[str, Any]]:
    """Sample RSS feed items as dicts."""
    return [
        {"title": "Fed holds rates steady",
         "link": "https://example.com/news/fed",
         "description": "The Federal Reserve held interest rates...",
         "published": "Mon, 29 Jun 2026 14:00:00 GMT",
         "source": "reuters_top"},
        {"title": "Bitcoin surges past $150k",
         "link": "https://example.com/news/btc",
         "description": "Bitcoin reached new all-time high...",
         "published": "Mon, 29 Jun 2026 15:30:00 GMT",
         "source": "coindesk_crypto"},
        {"title": "S&P 500 closes at record",
         "link": "https://example.com/news/sp500",
         "description": "The S&P 500 index closed at a record high...",
         "published": "Mon, 29 Jun 2026 16:00:00 GMT",
         "source": "bloomberg_markets"},
    ]


@pytest.fixture
def mock_rss_xml() -> str:
    """Sample RSS 2.0 XML feed."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>Test RSS feed for SharedSignals</description>
    <item>
      <title>Fed holds rates steady</title>
      <link>https://example.com/news/fed</link>
      <description>The Federal Reserve held interest rates steady</description>
      <pubDate>Mon, 29 Jun 2026 14:00:00 GMT</pubDate>
      <guid>https://example.com/news/fed</guid>
    </item>
    <item>
      <title>Bitcoin surges</title>
      <link>https://example.com/news/btc</link>
      <description>Bitcoin reached new highs</description>
      <pubDate>Mon, 29 Jun 2026 15:30:00 GMT</pubDate>
      <guid>https://example.com/news/btc</guid>
    </item>
  </channel>
</rss>"""


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
