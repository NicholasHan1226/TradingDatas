from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from tools.refresh_stock_industry_map import refresh_stock_industry_map


def _create_market_assets_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE market_assets (
                market TEXT,
                symbol TEXT,
                name TEXT,
                asset_type TEXT,
                exchange TEXT,
                sector TEXT,
                list_date TEXT,
                status TEXT,
                provider TEXT,
                source_file TEXT,
                updated_at TEXT,
                raw_json TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("Ashare", "000001.SZ", "Ping An Bank", "stock", "SZSE", "Bank", "19910403", "active", "tushare", "stock_company_20260704.csv", "2026-07-03T03:55:01+00:00", "{}"),
                ("Ashare", "000002.SZ", "Vanke A", "stock", "SZSE", "Real Estate", "19910129", "active", "tushare", "stock_company_20260704.csv", "2026-07-03T03:55:01+00:00", "{}"),
                ("Ashare", "000004.SZ", "Missing Sector", "stock", "SZSE", "", "19901201", "active", "tushare", "stock_company_20260704.csv", "2026-07-03T03:55:01+00:00", "{}"),
                ("US", "AAPL", "Apple", "stock", "NASDAQ", "Technology", "", "active", "tushare", "us_basic_20260704.csv", "2026-07-04T00:00:00+00:00", "{}"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_refresh_stock_industry_map_writes_basic_sector_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    output = tmp_path / "stock_industry_map.csv"
    _create_market_assets_db(db_path)

    result = refresh_stock_industry_map(db_path=db_path, output_path=output, backup_dir=None, min_rows=1)

    assert result.rows_written == 2
    assert output.stat().st_mode & 0o777 == 0o664
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["ts_code"] for row in rows] == ["000001.SZ", "000002.SZ"]
    assert rows[0]["sw_l1_name"] == "Bank"
    assert rows[0]["taxonomy_id"] == "market_assets_sector"
    assert rows[0]["source"] == "market_assets"
    assert rows[0]["source_date"] == "20260703"
    assert "not verified" in rows[0]["notes"]
