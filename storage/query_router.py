"""Route queries: hot(<30d)→SQLite,  cold(>30d)→DuckDB/Parquet."""
import sqlite3
from datetime import datetime, timedelta
import os

SQLITE_PATH = os.environ.get(
    "MARKETDATA_SQLITE",
    "/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite")
HOT_DAYS = 30


def is_hot(date_str):
    cutoff = (datetime.now() - timedelta(days=HOT_DAYS)).strftime("%Y%m%d")
    return date_str >= cutoff


def query(table, start_date, end_date):
    results = []
    # Hot path: SQLite
    if is_hot(start_date) or is_hot(end_date):
        con = sqlite3.connect(SQLITE_PATH)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM {table} WHERE trade_date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchall()
        results.extend([dict(r) for r in rows])
        con.close()
    # Cold path: DuckDB/Parquet
    if not is_hot(start_date):
        try:
            from storage.archive_manager import query_cold
            results.extend(query_cold(table, start_date, end_date))
        except ImportError:
            pass
    return results


if __name__ == "__main__":
    import json
    r = query("market_bars_daily", "20200101", "20260601")
    print(f"cold query returned {len(r)} rows")
