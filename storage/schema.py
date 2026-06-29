"""SharedSignals storage schema documentation.

This module documents the existing marketdata.sqlite schema used by the
MarketGraph market-data database. It is a read-only reference for the
shared storage layer: callers should not redefine these tables.

The canonical schema is created by
``MarketGraph/08-Market-Interfaces/tools/marketgraph_marketdata_db.py``
(``init_schema``). The definitions below mirror that source so that
collectors and consumers share one consistent view of the storage shape.

Tables (11):
    market_assets            — instrument master (one row per market+symbol)
    market_bars_daily        — daily OHLCV bars
    market_bars_intraday     — intraday OHLCV bars (minute/hourly)
    market_events            — news / event stream
    market_pm_markets        — prediction-market market metadata
    market_pm_prices         — prediction-market price snapshots
    market_factors           — derived factor values
    market_ingest_runs       — ingest run audit log
    market_coverage_status   — per-symbol per-day coverage state
    market_backfill_status   — per-dataset per-day backfill state
    provider_interface_matrix — provider/interface capability registry
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Table definitions (mirrors init_schema in marketgraph_marketdata_db.py)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Instrument master: one row per (market, symbol).
CREATE TABLE IF NOT EXISTS market_assets (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    asset_type TEXT,
    exchange TEXT,
    sector TEXT,
    list_date TEXT,
    status TEXT,
    provider TEXT,
    source_file TEXT,
    updated_at TEXT,
    raw_json TEXT,
    PRIMARY KEY (market, symbol)
);

-- Daily OHLCV bars.
CREATE TABLE IF NOT EXISTS market_bars_daily (
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
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
    PRIMARY KEY (market, symbol, trade_date, provider)
);

-- Intraday OHLCV bars (minute/hourly).
CREATE TABLE IF NOT EXISTS market_bars_intraday (
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
);

-- News / event stream.
CREATE TABLE IF NOT EXISTS market_events (
    event_hash TEXT PRIMARY KEY,
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
    raw_json TEXT
);

-- Prediction-market market metadata.
CREATE TABLE IF NOT EXISTS market_pm_markets (
    market_id TEXT PRIMARY KEY,
    question TEXT,
    slug TEXT,
    end_date TEXT,
    volume REAL,
    liquidity REAL,
    active TEXT,
    closed TEXT,
    provider TEXT,
    source_file TEXT,
    collected_at TEXT,
    raw_json TEXT
);

-- Prediction-market price snapshots.
CREATE TABLE IF NOT EXISTS market_pm_prices (
    price_hash TEXT PRIMARY KEY,
    market_id TEXT,
    token_id TEXT,
    price_time TEXT,
    price REAL,
    provider TEXT,
    source_file TEXT,
    collected_at TEXT,
    raw_json TEXT
);

-- Derived factor values.
CREATE TABLE IF NOT EXISTS market_factors (
    factor_hash TEXT PRIMARY KEY,
    market TEXT,
    symbol TEXT,
    factor_name TEXT,
    event_time TEXT,
    value REAL,
    provider TEXT,
    source_file TEXT,
    collected_at TEXT,
    raw_json TEXT
);

-- Ingest run audit log.
CREATE TABLE IF NOT EXISTS market_ingest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    source TEXT,
    rows_read INTEGER,
    rows_written INTEGER,
    notes TEXT
);

-- Per-symbol per-day coverage state.
CREATE TABLE IF NOT EXISTS market_coverage_status (
    market TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    coverage_status TEXT NOT NULL,
    reason TEXT,
    provider TEXT,
    source_file TEXT,
    updated_at TEXT,
    raw_json TEXT,
    PRIMARY KEY (market, trade_date, symbol)
);

-- Per-dataset per-day backfill state.
CREATE TABLE IF NOT EXISTS market_backfill_status (
    market TEXT NOT NULL,
    dataset TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_read INTEGER,
    rows_written INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (market, dataset, trade_date)
);

-- Provider/interface capability registry.
CREATE TABLE IF NOT EXISTS provider_interface_matrix (
    matrix_id TEXT PRIMARY KEY,
    layer TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    provider TEXT,
    source_family TEXT,
    mcp_tool TEXT,
    collector_scripts TEXT,
    collection_schedule TEXT,
    storage_kind TEXT,
    storage_path TEXT,
    read_model_table TEXT,
    actual_state TEXT,
    updated_at TEXT NOT NULL
);

-- Indexes for common lookup paths.
CREATE INDEX IF NOT EXISTS idx_market_bars_daily_lookup
    ON market_bars_daily (market, symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_market_bars_intraday_lookup
    ON market_bars_intraday (market, symbol, trade_date, interval);
CREATE INDEX IF NOT EXISTS idx_market_events_lookup
    ON market_events (provider, event_type, event_time);
CREATE INDEX IF NOT EXISTS idx_market_pm_prices_lookup
    ON market_pm_prices (market_id, price_time);
CREATE INDEX IF NOT EXISTS idx_market_coverage_status_lookup
    ON market_coverage_status (market, trade_date, coverage_status);
CREATE INDEX IF NOT EXISTS idx_market_backfill_status_lookup
    ON market_backfill_status (market, dataset, status);
CREATE INDEX IF NOT EXISTS idx_provider_interface_matrix_lookup
    ON provider_interface_matrix (provider, layer, interface_name);
"""


TABLE_NAMES = [
    "market_assets",
    "market_bars_daily",
    "market_bars_intraday",
    "market_events",
    "market_pm_markets",
    "market_pm_prices",
    "market_factors",
    "market_ingest_runs",
    "market_coverage_status",
    "market_backfill_status",
    "provider_interface_matrix",
]


def schema_sql() -> str:
    """Return the full schema DDL string (CREATE TABLE + CREATE INDEX)."""
    return SCHEMA_SQL


def table_names() -> list[str]:
    """Return the list of table names in dependency-safe order."""
    return list(TABLE_NAMES)
