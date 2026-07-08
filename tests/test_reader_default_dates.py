from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path


def _reset_reader_paths(reader, *, db_path: Path, intake_root: Path) -> None:
    reader.SQLITE_PATH = reader._LazyPath(lambda: db_path)
    reader.SHAREDSIGNALS_ROOT = reader._LazyPath(lambda: intake_root.parent)
    reader.clear_caches()


def test_get_sentiment_without_dates_returns_recent_rows(tmp_path: Path) -> None:
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
            INSERT INTO market_events (
                event_hash, provider, event_type, event_time, trade_date,
                market, symbol, title, content, url, source, source_file,
                collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sentiment-1",
                "tushare_news",
                "sentiment",
                "20260703",
                "20260703",
                "Ashare",
                "000001.SZ",
                "positive signal",
                "sentiment=positive",
                "",
                "tushare_news",
                "news_direct",
                "2026-07-03T10:00:00+00:00",
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    rows = reader.get_sentiment()

    assert rows
    assert rows[0]["degraded"] is False
    assert rows[0]["data"]["event_hash"] == "sentiment-1"


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


def test_get_realtime_5min_does_not_fall_back_to_rt_min_csv(tmp_path: Path) -> None:
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
    old_csv = tmp_path / "data" / "tushare" / "rt_min" / "20260706" / "000001.SZ.csv"
    old_csv.parent.mkdir(parents=True)
    old_csv.write_text("ts_code,time,close\n000001.SZ,2026-07-06 09:55:00,10.28\n", encoding="utf-8")

    rows = reader.get_realtime_5min("000001.SZ", "20260706")

    assert rows
    assert rows[0]["degraded"] is True
    assert rows[0]["data"] == {}
    assert rows[0]["provenance"]["source_id"] == "sqlite:market_bars_intraday"


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


def test_get_realtime_5min_can_return_latest_market_batch_without_symbol(tmp_path: Path) -> None:
    import reader
    from storage.schema import SCHEMA_SQL

    db_path = tmp_path / "marketdata.sqlite"
    intake_root = tmp_path / "intake"
    _reset_reader_paths(reader, db_path=db_path, intake_root=intake_root)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        rows = [
            ("Futures", "RB2609.SHF", "20260703", "2026-07-03T14:50:00+08:00", 3510.0),
            ("Futures", "RB2609.SHF", "20260703", "2026-07-03T14:55:00+08:00", 3520.0),
            ("Futures", "CU2609.SHF", "20260703", "2026-07-03T14:55:00+08:00", 80120.0),
            ("Futures", "RB2609.SHF", "20260702", "2026-07-02T14:55:00+08:00", 3500.0),
        ]
        for market, symbol, trade_date, bar_time, close in rows:
            conn.execute(
                """
                INSERT INTO market_bars_intraday
                (market, symbol, trade_date, bar_time, interval, open, high, low, close, volume, amount, provider, source_file, collected_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market,
                    symbol,
                    trade_date,
                    bar_time,
                    "5min",
                    close,
                    close,
                    close,
                    close,
                    1000.0,
                    close * 1000,
                    "sina_futures_minute",
                    "direct_db",
                    "2026-07-03T06:55:00+00:00",
                    "{}",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    result = reader.get_realtime_5min("", "20260703", market="Futures")

    symbols = [row["data"]["symbol"] for row in result]
    assert symbols == ["CU2609.SHF", "RB2609.SHF"]
    assert {row["data"]["bar_time"] for row in result} == {"2026-07-03T14:55:00+08:00"}
    assert result[0]["lineage"]["filters"]["ts_code"] == ""


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
