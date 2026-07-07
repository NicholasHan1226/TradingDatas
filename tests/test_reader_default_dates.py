from __future__ import annotations

import csv
import os
import sqlite3
import time
from pathlib import Path


def _reset_reader_paths(reader, *, db_path: Path, intake_root: Path) -> None:
    reader.SQLITE_PATH = reader._LazyPath(lambda: db_path)
    reader.INTAKE_ROOT = reader._LazyPath(lambda: intake_root)
    reader.SHAREDSIGNALS_ROOT = reader._LazyPath(lambda: intake_root.parent)
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


def test_get_realtime_5min_normalizes_lowercase_ashare_market(tmp_path: Path) -> None:
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
                "20260707",
                "2026-07-07T09:35:00+08:00",
                "5min",
                10.0,
                10.2,
                9.9,
                10.1,
                1000.0,
                10100.0,
                "tushare_rt_min",
                "rt.csv",
                "2026-07-07T01:35:00+00:00",
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = reader.get_realtime_5min("000001.SZ", "20260707", market="ashare")

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["market"] == "Ashare"
    assert rows[0]["data"]["close"] == 10.1
    assert rows[0]["lineage"]["filters"]["market"] == "Ashare"


def test_get_realtime_5min_falls_back_to_sharedsignals_rt_min_csv(tmp_path: Path) -> None:
    import reader
    from storage.schema import SCHEMA_SQL

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    _write_csv(
        tmp_path / "data" / "tushare" / "rt_min" / "20260706" / "000001.SZ.csv",
        ["ts_code", "freq", "time", "open", "close", "high", "low", "vol", "amount"],
        [
            {
                "ts_code": "000001.SZ",
                "freq": "5MIN",
                "time": "2026-07-06 09:55:00",
                "open": "10.27",
                "close": "10.28",
                "high": "10.32",
                "low": "10.27",
                "vol": "2245200",
                "amount": "23112441",
            }
        ],
    )

    rows = reader.get_realtime_5min("000001.SZ", "20260706")

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["close"] == "10.28"
    assert "rt_min" in rows[0]["lineage"]["source_paths"][2]


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


def test_cache_invalidation_watches_sqlite_wal_sidecar(tmp_path: Path) -> None:
    import reader

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)

    reset_time = time.time()
    wal_path = Path(str(db_path) + "-wal")
    wal_path.write_text("pending sqlite writes\n", encoding="utf-8")
    os.utime(wal_path, (reset_time + 10, reset_time + 10))

    assert wal_path in reader._watched_paths()
    assert reader._files_changed(reset_time) is True
