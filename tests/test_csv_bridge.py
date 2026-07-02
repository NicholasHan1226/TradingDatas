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
