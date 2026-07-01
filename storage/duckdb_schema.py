"""DuckDB schema — shadow read-model mirroring the SQLite marketdata schema.

Strategy (from Codex architecture review):
  - SQLite continues as authoritative write model
  - DuckDB provides a fast read-only analytics copy
  - Single-writer batch-merges from NDJSON staging files
  - Per-thread duckdb.connect() — never global duckdb.sql()

All 11 tables defined here match the SQLite schema in storage/schema.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DuckDB DDL (mirrors SCHEMA_SQL from storage/schema.py)
# ---------------------------------------------------------------------------

DUCKDB_SCHEMA_SQL = """
-- Instrument master
CREATE TABLE IF NOT EXISTS market_assets (
    market VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    name VARCHAR,
    asset_type VARCHAR,
    exchange VARCHAR,
    sector VARCHAR,
    list_date VARCHAR,
    status VARCHAR,
    provider VARCHAR,
    source_file VARCHAR,
    updated_at VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (market, symbol)
);

-- Daily OHLCV bars
CREATE TABLE IF NOT EXISTS market_bars_daily (
    market VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    trade_date VARCHAR NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    amount DOUBLE,
    provider VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (market, symbol, trade_date, provider)
);

-- Intraday OHLCV bars
CREATE TABLE IF NOT EXISTS market_bars_intraday (
    market VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    bar_time VARCHAR NOT NULL,
    trade_date VARCHAR,
    interval VARCHAR,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    amount DOUBLE,
    provider VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (market, symbol, bar_time, interval, provider)
);

-- News / event stream
CREATE TABLE IF NOT EXISTS market_events (
    event_hash VARCHAR PRIMARY KEY,
    provider VARCHAR,
    event_type VARCHAR,
    event_time VARCHAR,
    trade_date VARCHAR,
    market VARCHAR,
    symbol VARCHAR,
    title VARCHAR,
    content VARCHAR,
    url VARCHAR,
    source VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR
);

-- Prediction-market market metadata
CREATE TABLE IF NOT EXISTS market_pm_markets (
    market_id VARCHAR PRIMARY KEY,
    question VARCHAR,
    slug VARCHAR,
    end_date VARCHAR,
    volume DOUBLE,
    liquidity DOUBLE,
    active VARCHAR,
    closed VARCHAR,
    provider VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR
);

-- Prediction-market price snapshots
CREATE TABLE IF NOT EXISTS market_pm_prices (
    price_hash VARCHAR PRIMARY KEY,
    market_id VARCHAR,
    token_id VARCHAR,
    price_time VARCHAR,
    price DOUBLE,
    provider VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR
);

-- Derived factor values
CREATE TABLE IF NOT EXISTS market_factors (
    factor_hash VARCHAR PRIMARY KEY,
    market VARCHAR,
    symbol VARCHAR,
    factor_name VARCHAR,
    event_time VARCHAR,
    value DOUBLE,
    provider VARCHAR,
    source_file VARCHAR,
    collected_at VARCHAR,
    raw_json VARCHAR
);

-- Ingest run audit log
CREATE TABLE IF NOT EXISTS market_ingest_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at VARCHAR,
    finished_at VARCHAR,
    status VARCHAR,
    source VARCHAR,
    rows_read BIGINT,
    rows_written BIGINT,
    notes VARCHAR
);

-- Per-symbol per-day coverage state
CREATE TABLE IF NOT EXISTS market_coverage_status (
    market VARCHAR NOT NULL,
    trade_date VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    coverage_status VARCHAR NOT NULL,
    reason VARCHAR,
    provider VARCHAR,
    source_file VARCHAR,
    updated_at VARCHAR,
    raw_json VARCHAR,
    PRIMARY KEY (market, trade_date, symbol)
);

-- Per-dataset per-day backfill state
CREATE TABLE IF NOT EXISTS market_backfill_status (
    market VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    trade_date VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    rows_read BIGINT,
    rows_written BIGINT,
    error VARCHAR,
    updated_at VARCHAR NOT NULL,
    PRIMARY KEY (market, dataset, trade_date)
);

-- Provider/interface capability registry
CREATE TABLE IF NOT EXISTS provider_interface_matrix (
    matrix_id VARCHAR PRIMARY KEY,
    layer VARCHAR NOT NULL,
    interface_name VARCHAR NOT NULL,
    provider VARCHAR,
    source_family VARCHAR,
    mcp_tool VARCHAR,
    collector_scripts VARCHAR,
    collection_schedule VARCHAR,
    storage_kind VARCHAR,
    storage_path VARCHAR,
    read_model_table VARCHAR,
    actual_state VARCHAR,
    updated_at VARCHAR NOT NULL
);
"""

# DuckDB-specific table-to-SQLite mapping for merge operations
TABLE_PRIMARY_KEYS: dict[str, list[str]] = {
    "market_assets": ["market", "symbol"],
    "market_bars_daily": ["market", "symbol", "trade_date", "provider"],
    "market_bars_intraday": ["market", "symbol", "bar_time", "interval", "provider"],
    "market_events": ["event_hash"],
    "market_pm_markets": ["market_id"],
    "market_pm_prices": ["price_hash"],
    "market_factors": ["factor_hash"],
    "market_ingest_runs": ["run_id"],
    "market_coverage_status": ["market", "trade_date", "symbol"],
    "market_backfill_status": ["market", "dataset", "trade_date"],
    "provider_interface_matrix": ["matrix_id"],
}

TABLE_NAMES = list(TABLE_PRIMARY_KEYS.keys())


def create_schema(conn: Any) -> None:
    """Create all DuckDB tables if they don't exist."""
    conn.execute(DUCKDB_SCHEMA_SQL)


def merge_from_ndjson(conn: Any, table: str, ndjson_path: str) -> int:
    """Merge rows from an NDJSON staging file into a DuckDB table.

    Uses INSERT OR REPLACE (via ON CONFLICT) pattern.
    Returns number of rows merged.
    """
    import json

    pk = TABLE_PRIMARY_KEYS.get(table, [])
    cols = _table_columns(conn, table)
    if not cols:
        logger.warning("merge_from_ndjson: unknown table %s", table)
        return 0

    # Read NDJSON
    rows = []
    with open(ndjson_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        return 0

    # Build ON CONFLICT clause
    conflict_clause = ""
    if pk:
        pk_str = ", ".join(pk)
        conflict_clause = f" ON CONFLICT ({pk_str}) DO UPDATE SET " + ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols if c not in pk
        )
    else:
        conflict_clause = " ON CONFLICT DO NOTHING"

    # Column list — only include columns that exist in the table
    col_names = [c for c in rows[0].keys() if c in cols]
    placeholders = ", ".join(["?" for _ in col_names])
    col_str = ", ".join(col_names)

    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}){conflict_clause}"
    data = [[row.get(c) for c in col_names] for row in rows]

    conn.executemany(sql, data)
    logger.info("duckdb merge: %s ← %d rows from %s", table, len(rows), Path(ndjson_path).name)
    return len(rows)


def _table_columns(conn: Any, table: str) -> list[str]:
    """Return column names for a DuckDB table."""
    try:
        result = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
        return [r[0] for r in result]
    except Exception:
        return []
