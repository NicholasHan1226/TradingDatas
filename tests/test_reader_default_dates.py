from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def _reset_reader_paths(reader, *, db_path: Path, intake_root: Path) -> None:
    reader.SQLITE_PATH = reader._LazyPath(lambda: db_path)
    reader.INTAKE_ROOT = reader._LazyPath(lambda: intake_root)
    reader.SENTIMENT_SIGNALS_PATH = reader._LazyPath(lambda: intake_root / "sentiment_signals_archive.csv")
    reader.REALTIME_5M_ROOT = reader._LazyPath(lambda: intake_root / "rt_min_5m")
    reader.clear_caches()


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_get_sentiment_without_dates_returns_recent_rows(tmp_path: Path) -> None:
    import reader

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)
    _write_csv(
        intake_root / "sentiment_signals.csv",
        ["signal_id", "title", "sentiment", "source_date", "collected_at"],
        [
            {
                "signal_id": "s001",
                "title": "positive signal",
                "sentiment": "positive",
                "source_date": "20260703",
                "collected_at": "2026-07-03T10:00:00+00:00",
            }
        ],
    )

    rows = reader.get_sentiment()

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["signal_id"] == "s001"


def test_get_realtime_5min_without_date_uses_latest_intraday_date(tmp_path: Path) -> None:
    import reader
    from storage.schema import SCHEMA_SQL

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO market_bars_intraday
            (market, symbol, trade_date, bar_time, interval, open, high, low, close, volume, amount, provider, source_file, collected_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Ashare",
                "000001.SZ",
                "20260703",
                "2026-07-03T09:35:00+08:00",
                "5min",
                10.0,
                10.2,
                9.9,
                10.1,
                1000.0,
                10100.0,
                "tushare",
                "rt.csv",
                "2026-07-03T01:35:00+00:00",
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = reader.get_realtime_5min("000001.SZ", None)

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["trade_date"] == "20260703"
    assert rows[0]["lineage"]["filters"]["date"] == "20260703"


def test_get_realtime_5min_supports_non_ashare_market_and_l1_fields(tmp_path: Path) -> None:
    import reader
    from storage.schema import SCHEMA_SQL

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO market_bars_intraday
            (market, symbol, trade_date, bar_time, interval, open, high, low, close, volume, amount,
             bid_price, ask_price, bid_size, ask_size, provider, source_file, collected_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Futures",
                "RB2609.SHF",
                "20260703",
                "2026-07-03T14:55:00+08:00",
                "5min",
                3500.0,
                3530.0,
                3490.0,
                3520.0,
                1000.0,
                3520000.0,
                3519.0,
                3521.0,
                12.0,
                9.0,
                "tushare_rt_fut_min",
                "rt_fut_min.csv",
                "2026-07-03T06:55:00+00:00",
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = reader.get_realtime_5min("RB2609.SHF", "20260703", market="Futures")

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["bid_price"] == 3519.0
    assert rows[0]["data"]["ask_price"] == 3521.0
    assert rows[0]["lineage"]["filters"]["market"] == "Futures"
