from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from storage.csv_bridge import ingest_csv_to_sqlite
from storage.schema import SCHEMA_SQL


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _write_csv(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _count_rows(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_ingest_csv_to_sqlite_creates_rows(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "daily" / "20260701" / "000001.SZ.csv",
        "\n".join(
            [
                "ts_code,trade_date,open,high,low,close,vol,amount",
                "000001.SZ,20260701,10,11,9,10.5,1000,10500",
                "000002.SZ,20260701,20,21,19,20.5,2000,41000",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 2
    assert _count_rows(db_path, "market_bars_daily") == 2


def test_us_daily_adds_tushare_lineage_metadata(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "us_daily" / "20260704" / "us_daily_20260704.csv",
        "\n".join(
            [
                "ts_code,trade_date,open,high,low,close,vol,amount",
                "AAPL,20260702,200,205,199,204,1000,204000",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT market, symbol, provider, collected_at, source_file FROM market_bars_daily"
        ).fetchone()
    finally:
        conn.close()
    assert row[:3] == ("US", "AAPL", "tushare_us_daily")
    assert row[3]
    assert row[4] == "us_daily_20260704.csv"


def test_stk_mins_ingests_intraday_with_metadata(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "stk_mins" / "20260703" / "000001.SZ.csv",
        "\n".join(
            [
                "ts_code,trade_time,open,close,high,low,vol,amount",
                "000001.SZ,2026-07-03 14:55:00,10.1,10.2,10.3,10.0,1000,10200",
                "000001.SZ,2026-07-03 15:00:00,10.2,10.3,10.4,10.1,2000,20600",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_intraday", csv_path)

    assert rows == 2
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT market, symbol, trade_date, bar_time, interval, provider, source_file, collected_at "
            "FROM market_bars_intraday ORDER BY bar_time LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row[:7] == (
        "Ashare",
        "000001.SZ",
        "20260703",
        "2026-07-03 14:55:00",
        "5min",
        "tushare_stk_mins",
        "000001.SZ.csv",
    )
    assert row[7]


def test_factor_csv_expands_numeric_metrics(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "fina_indicator" / "20260704" / "600519.SH.csv",
        "\n".join(
            [
                "ts_code,end_date,roe,roa,update_flag,report_type",
                "600519.SH,20260331,28.5,18.2,1,Q1",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_factors", csv_path)

    assert rows == 2
    conn = sqlite3.connect(str(db_path))
    try:
        records = conn.execute(
            "SELECT market, symbol, factor_name, event_time, value, provider, source_file, raw_json "
            "FROM market_factors ORDER BY factor_name"
        ).fetchall()
    finally:
        conn.close()
    assert [(row[0], row[1], row[2], row[3], row[4], row[5], row[6]) for row in records] == [
        ("Ashare", "600519.SH", "fina_indicator:roa", "20260331", 18.2, "tushare_fina_indicator", "600519.SH.csv"),
        ("Ashare", "600519.SH", "fina_indicator:roe", "20260331", 28.5, "tushare_fina_indicator", "600519.SH.csv"),
    ]
    assert "report_type" in records[0][7]


def test_ingest_idempotent(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "daily.csv",
        "\n".join(
            [
                "market,symbol,trade_date,open,high,low,close,volume,amount,provider",
                "Ashare,000001.SZ,20260701,10,11,9,10.5,1000,10500,tushare",
                "Ashare,000002.SZ,20260701,20,21,19,20.5,2000,41000,tushare",
            ]
        ),
    )

    first_rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)
    first_count = _count_rows(db_path, "market_bars_daily")
    second_rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)
    second_count = _count_rows(db_path, "market_bars_daily")

    assert first_rows == 2
    assert second_rows == 2
    assert first_count == 2
    assert second_count == 2


def test_unknown_columns_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "daily.csv",
        "\n".join(
            [
                "market,symbol,trade_date,open,high,low,close,volume,unknown_col",
                "Ashare,000001.SZ,20260701,10,11,9,10.5,1000,ignore-me",
            ]
        ),
    )

    caplog.set_level(logging.DEBUG)
    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    assert _count_rows(db_path, "market_bars_daily") == 1
    assert "unknown_col" in caplog.text


def test_missing_csv_raises(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    with pytest.raises(FileNotFoundError):
        ingest_csv_to_sqlite(db_path, "market_bars_daily", tmp_path / "missing.csv")


def test_empty_csv_header_only_returns_zero(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "daily.csv",
        "market,symbol,trade_date,open,high,low,close,volume\n",
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 0
    assert _count_rows(db_path, "market_bars_daily") == 0


def test_bom_only_csv_returns_zero(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = tmp_path / "bom-only.csv"
    csv_path.write_bytes(b"\xef\xbb\xbf")

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 0
    assert _count_rows(db_path, "market_bars_daily") == 0


def test_all_unknown_columns_skips_all_rows(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "unknown-only.csv",
        "\n".join(
            [
                "unknown_a,unknown_b",
                "one,two",
                "three,four",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 0
    assert _count_rows(db_path, "market_bars_daily") == 0


def test_csv_with_null_bytes_does_not_crash(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = tmp_path / "null-byte.csv"
    csv_path.write_bytes(
        b"market,symbol,name,asset_type\n"
        b"Ashare,000001.SZ,Name\x00WithNull,stock\n"
    )

    rows = ingest_csv_to_sqlite(db_path, "market_assets", csv_path)

    assert rows == 1
    assert _count_rows(db_path, "market_assets") == 1


def test_large_csv_crosses_chunk_boundaries(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = tmp_path / "large-100k.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("market,symbol,trade_date,open,high,low,close,volume,amount,provider\n")
        for idx in range(100_000):
            fh.write(
                f"Ashare,{idx:06d}.SZ,20260701,10,11,9,10.5,{idx},10500,tushare\n"
            )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 100_000
    assert _count_rows(db_path, "market_bars_daily") == 100_000


def test_csv_path_with_special_characters(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data with spaces" / "daily @#%" / "20260701" / "000001.SZ sample.csv",
        "\n".join(
            [
                "market,symbol,trade_date,open,high,low,close,volume,amount",
                "Ashare,000001.SZ,20260701,10,11,9,10.5,1000,10500",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    assert _count_rows(db_path, "market_bars_daily") == 1
