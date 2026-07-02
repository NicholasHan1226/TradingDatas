"""CSV-to-SQLite bridge for SharedSignals storage tables."""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
from pathlib import Path

from storage.schema_contract import table_primary_keys

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = (
    Path(os.environ.get("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime"))
    / "read_model"
    / "marketdata.sqlite"
)

CSV_TO_TABLE_MAP = {
    "daily": "market_bars_daily",
    "hk_daily": "market_bars_daily",
    "us_daily": "market_bars_daily",
    "stock_basic": "market_assets",
    "hk_basic": "market_assets",
    "us_basic": "market_assets",
    "weekly": "market_bars_intraday",
    "monthly": "market_bars_intraday",
}


def _quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def _table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()
    return [row[1] for row in rows]


def _api_name_from_path(csv_path):
    parent = csv_path.parent.parent.name
    return parent if parent in CSV_TO_TABLE_MAP else ""


def _market_for(api_name, symbol):
    if api_name in ("daily", "stock_basic", "weekly", "monthly"):
        return "Ashare"
    if api_name in ("hk_daily", "hk_basic"):
        return "HK"
    if api_name in ("us_daily", "us_basic"):
        return "US"

    symbol = str(symbol or "")
    if symbol.endswith((".SZ", ".SH", ".BJ")):
        return "Ashare"
    if symbol.endswith(".HK"):
        return "HK"
    return ""


def _columns_for_insert(table, csv_columns, target_columns, api_name):
    columns = [col for col in csv_columns if col in target_columns]
    csv_column_set = set(csv_columns)

    derived_columns = []
    if "ts_code" in csv_column_set and "symbol" in target_columns:
        derived_columns.append("symbol")
    if "vol" in csv_column_set and "volume" in target_columns:
        derived_columns.append("volume")
    if "market" in target_columns and (
        api_name or "ts_code" in csv_column_set or "symbol" in csv_column_set
    ):
        derived_columns.append("market")
    if table == "market_bars_intraday":
        if "trade_date" in csv_column_set and "bar_time" in target_columns:
            derived_columns.append("bar_time")
        if api_name in ("weekly", "monthly") and "interval" in target_columns:
            derived_columns.append("interval")
    if "source_file" in target_columns:
        derived_columns.append("source_file")

    for col in derived_columns:
        if col not in columns:
            columns.append(col)
    return columns


def _canonical_row(table, row, api_name, csv_path):
    symbol = row.get("ts_code") or row.get("symbol")
    if symbol:
        row["symbol"] = symbol

    if "vol" in row and "volume" not in row:
        row["volume"] = row.get("vol")

    market = _market_for(api_name, symbol)
    if market:
        row["market"] = market

    if table == "market_bars_intraday":
        if row.get("trade_date") and not row.get("bar_time"):
            row["bar_time"] = row.get("trade_date")
        if api_name in ("weekly", "monthly"):
            row["interval"] = api_name

    if not row.get("source_file"):
        row["source_file"] = csv_path.name

    return row


def _insert_sql(table, columns, pk_columns):
    quoted_table = _quote_identifier(table)
    col_sql = ", ".join(_quote_identifier(col) for col in columns)
    placeholders = ", ".join("?" for _ in columns)

    if pk_columns:
        conflict_sql = ", ".join(_quote_identifier(col) for col in pk_columns)
        update_columns = [col for col in columns if col not in pk_columns]
        if update_columns:
            update_sql = ", ".join(
                f"{_quote_identifier(col)} = excluded.{_quote_identifier(col)}"
                for col in update_columns
            )
            return (
                f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
            )
        return (
            f"INSERT INTO {quoted_table} ({col_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_sql}) DO NOTHING"
        )

    return f"INSERT OR IGNORE INTO {quoted_table} ({col_sql}) VALUES ({placeholders})"


def ingest_csv_to_sqlite(db_path, table, csv_path, encoding="utf-8-sig"):
    """Ingest one CSV file into an existing SQLite table.

    The bridge is defensive: it never creates target tables. If the database or
    table is missing, it logs and returns 0 so CSV collection remains the source
    of truth.
    """
    db_path = Path(db_path)
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(str(csv_path))

    if not db_path.exists():
        logger.warning("csv bridge skipped: database does not exist: %s", db_path)
        return 0

    rows_written = 0
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")

        target_columns = _table_columns(conn, table)
        if not target_columns:
            logger.warning("csv bridge skipped: table does not exist: %s", table)
            return 0

        with csv_path.open("r", encoding=encoding, newline="") as fh:
            reader = csv.DictReader(fh)
            csv_columns = reader.fieldnames or []
            api_name = _api_name_from_path(csv_path)
            columns = _columns_for_insert(table, csv_columns, target_columns, api_name)
            skipped = [col for col in csv_columns if col not in target_columns]
            if skipped:
                logger.debug(
                    "csv bridge skipped unknown columns for %s: %s",
                    table,
                    ", ".join(skipped),
                )
            if not columns:
                logger.warning("csv bridge skipped: no matching columns for %s in %s", table, csv_path)
                return 0

            pk_columns = [
                col
                for col in table_primary_keys().get(table, [])
                if col in target_columns
            ]
            sql = _insert_sql(table, columns, pk_columns)

            conn.execute("BEGIN IMMEDIATE")
            try:
                for row in reader:
                    row = _canonical_row(table, row, api_name, csv_path)
                    values = [row.get(col) for col in columns]
                    cur = conn.execute(sql, values)
                    rows_written += cur.rowcount if cur.rowcount > 0 else 0
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()

    return rows_written


def ingest_date_partition(db_path, api_name, trade_date, data_dir):
    """Ingest CSV files for one Tushare API/date partition."""
    table = CSV_TO_TABLE_MAP.get(api_name)
    summary = {
        "api_name": api_name,
        "trade_date": trade_date,
        "files_processed": 0,
        "total_rows": 0,
    }
    if not table:
        logger.warning("csv bridge skipped: no table mapping for api_name=%s", api_name)
        return summary

    partition_dir = Path(data_dir) / "tushare" / api_name / str(trade_date)
    if not partition_dir.exists():
        logger.warning("csv bridge skipped: partition does not exist: %s", partition_dir)
        return summary

    for csv_file in sorted(partition_dir.glob("*.csv")):
        rows = ingest_csv_to_sqlite(db_path, table, csv_file)
        summary["files_processed"] += 1
        summary["total_rows"] += rows

    return summary
