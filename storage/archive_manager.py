"""Cold/hot storage: SQLite(hot <30d) + DuckDB/Parquet(cold 30d+)."""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta

SQLITE_PATH = os.environ.get(
    "MARKETDATA_SQLITE",
    "/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite")
COLD_DIR = Path("/opt/investment/SharedSignals/storage/cold")
ARCHIVE_DAYS = int(os.environ.get("ARCHIVE_DAYS", "30"))


def archive_old_data(days=ARCHIVE_DAYS):
    try:
        import duckdb
    except ImportError:
        return {"error": "duckdb not installed", "archived": 0}

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    con = duckdb.connect()
    con.execute(f"ATTACH '{SQLITE_PATH}' AS sqlite_db (TYPE SQLITE)")

    tables = ["market_bars_daily", "market_events"]
    total = 0
    for table in tables:
        try:
            cnt = con.execute(
                f"SELECT COUNT(*) FROM sqlite_db.{table} "
                f"WHERE trade_date < '{cutoff}'"
            ).fetchone()[0]
            if cnt == 0:
                continue
            dest = COLD_DIR / table
            dest.mkdir(parents=True, exist_ok=True)
            pq = str(dest / f"before_{cutoff}.parquet")
            con.execute(
                f"COPY (SELECT * FROM sqlite_db.{table} "
                f"WHERE trade_date < '{cutoff}') "
                f"TO '{pq}' (FORMAT PARQUET)")
            con.execute(
                f"DELETE FROM sqlite_db.{table} "
                f"WHERE trade_date < '{cutoff}'")
            total += cnt
            print(f"  {table}: {cnt} rows → {pq}")
        except Exception as exc:
            print(f"  {table}: skip ({exc})")
    con.close()
    return {"archived": total, "cutoff": cutoff}


def query_cold(table, start_date, end_date):
    try:
        import duckdb
        con = duckdb.connect()
        glob = str(COLD_DIR / table / "*.parquet")
        df = con.execute(
            f"SELECT * FROM read_parquet('{glob}') "
            f"WHERE trade_date BETWEEN '{start_date}' AND '{end_date}'"
        ).fetchdf()
        con.close()
        return df.to_dict("records")
    except Exception:
        return []


if __name__ == "__main__":
    import json
    r = archive_old_data()
    print(json.dumps(r, indent=2))
