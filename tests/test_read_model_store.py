from __future__ import annotations

import fcntl
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from storage.read_model_store import API_TO_TABLE_MAP, ingest_rows_to_sqlite
from storage.schema import SCHEMA_SQL


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _count_rows(path: Path, table: str) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _fetchone(path: Path, sql: str):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


def test_ingest_rows_to_sqlite_creates_daily_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_bars_daily",
        "daily",
        [
            {"ts_code": "000001.SZ", "trade_date": "20260701", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 1000, "amount": 10500},
            {"ts_code": "000002.SZ", "trade_date": "20260701", "open": 20, "high": 21, "low": 19, "close": 20.5, "vol": 2000, "amount": 41000},
        ],
        source_name="daily_rows_test",
    )

    assert rows == 2
    assert _count_rows(db_path, "market_bars_daily") == 2


def test_us_daily_adds_tushare_lineage_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_bars_daily",
        "us_daily",
        [{"ts_code": "AAPL", "trade_date": "20260702", "open": 200, "high": 205, "low": 199, "close": 204, "vol": 1000, "amount": 204000}],
        source_name="us_daily_rows_test",
    )

    assert rows == 1
    assert _fetchone(db_path, "SELECT market, symbol, provider, source_file FROM market_bars_daily") == (
        "US",
        "AAPL",
        "tushare_us_daily",
        "us_daily_rows_test",
    )


def test_rt_min_ingests_intraday_with_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_bars_intraday",
        "rt_min",
        [{"ts_code": "000001.SZ", "time": "2026-07-06 09:55:00", "open": 10.27, "close": 10.28, "high": 10.32, "low": 10.27, "vol": 2245200, "amount": 23112441}],
        source_name="rt_min_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT market, symbol, trade_date, bar_time, interval, provider, close, volume, amount FROM market_bars_intraday",
    ) == (
        "Ashare",
        "000001.SZ",
        "20260706",
        "2026-07-06 09:55:00",
        "5min",
        "tushare_rt_min",
        10.28,
        2245200.0,
        23112441.0,
    )


def test_weekly_rows_use_canonical_bar_time(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_bars_intraday",
        "weekly",
        [{"ts_code": "000001.SZ", "trade_date": "20260703", "close": 10.5}],
        source_name="weekly_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT trade_date, bar_time, interval FROM market_bars_intraday",
    ) == ("20260703", "2026-07-03 00:00:00", "weekly")

def test_rt_fut_min_ingests_quote_and_expiry_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_bars_intraday",
        "rt_fut_min",
        [
            {
                "code": "RB2609.SHF",
                "time": "2026-07-03 14:55:00",
                "open": 3500,
                "close": 3520,
                "high": 3530,
                "low": 3490,
                "vol": 1000,
                "amount": 3520000,
                "bid1": 3519,
                "ask1": 3521,
                "bid1_volume": 12,
                "ask1_volume": 9,
                "last_trade_date": "20260915",
                "expiry_date": "20260930",
            }
        ],
        source_name="rt_fut_min_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT market, symbol, trade_date, bar_time, interval, bid_price, ask_price, bid_size, ask_size, last_trade_date, expiry_date FROM market_bars_intraday",
    ) == (
        "Futures",
        "RB2609.SHF",
        "20260703",
        "2026-07-03 14:55:00",
        "5min",
        3519.0,
        3521.0,
        12.0,
        9.0,
        "20260915",
        "20260930",
    )


def test_factor_rows_expand_numeric_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_factors",
        "fina_indicator",
        [{"ts_code": "600519.SH", "end_date": "20260331", "roa": 18.2, "roe": 28.5, "update_flag": "1"}],
        source_name="fina_indicator_rows_test",
    )

    assert rows == 2
    conn = sqlite3.connect(str(db_path))
    try:
        records = conn.execute(
            "SELECT market, symbol, factor_name, event_time, value, provider, source_file FROM market_factors ORDER BY factor_name"
        ).fetchall()
    finally:
        conn.close()
    assert records == [
        ("Ashare", "600519.SH", "fina_indicator:roa", "20260331", 18.2, "tushare_fina_indicator", "fina_indicator_rows_test"),
        ("Ashare", "600519.SH", "fina_indicator:roe", "20260331", 28.5, "tushare_fina_indicator", "fina_indicator_rows_test"),
    ]


def test_manager_rows_are_factors_not_asset_names(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    ingest_rows_to_sqlite(
        db_path,
        "market_assets",
        "stock_basic",
        [{"ts_code": "000001.SZ", "name": "平安银行", "asset_type": "stock"}],
        source_name="stock_basic_rows_test",
    )

    rows = ingest_rows_to_sqlite(
        db_path,
        API_TO_TABLE_MAP["stk_managers"],
        "stk_managers",
        [{"ts_code": "000001.SZ", "name": "某高管", "position": "董事长", "gender": "M"}],
        source_name="stk_managers_rows_test",
    )

    assert rows == 1
    assert _fetchone(db_path, "SELECT name, provider FROM market_assets WHERE symbol='000001.SZ'") == (
        "平安银行",
        "tushare_stock_basic",
    )
    assert _fetchone(db_path, "SELECT symbol, factor_name, provider FROM market_factors") == (
        "000001.SZ",
        "stk_managers:stk_managers",
        "tushare_stk_managers",
    )


def test_repo_daily_projects_to_factors_and_daily_bars(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        API_TO_TABLE_MAP["repo_daily"],
        "repo_daily",
        [{"ts_code": "204001.SH", "trade_date": "20260706", "open": 1.2, "high": 1.5, "low": 1.0, "close": 1.4, "vol": 1000, "amount": 1400}],
        source_name="repo_daily_rows_test",
    )

    assert rows > 1
    assert _count_rows(db_path, "market_factors") > 0
    assert _fetchone(db_path, "SELECT market, symbol, trade_date, close, provider FROM market_bars_daily") == (
        "Ashare",
        "204001.SH",
        "20260706",
        1.4,
        "tushare_repo_daily",
    )


def test_event_rows_are_normalized(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "anns_d",
        [{"ts_code": "600276.SH", "ann_date": "20260708", "title": "董事会公告", "url": "https://example.com/ann"}],
        source_name="anns_d_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT provider, event_type, event_time, trade_date, market, symbol, title, url FROM market_events",
    ) == (
        "tushare_anns_d",
        "anns_d",
        "20260708",
        "20260708",
        "Ashare",
        "600276.SH",
        "董事会公告",
        "https://example.com/ann",
    )


def test_event_ingest_keeps_logical_id_and_appends_changed_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    base = {
        "id": "provider-42",
        "datetime": "2026-07-11 09:00:00",
        "title": "A",
        "content": "v1",
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 1
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [base]) == 0
    changed = {**base, "content": "v2"}
    assert ingest_rows_to_sqlite(db_path, "market_events", "news", [changed]) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision, source_family FROM market_events ORDER BY revision"
        ).fetchall()
    finally:
        conn.close()

    assert len({row[0] for row in rows}) == 1
    assert rows == [(rows[0][0], 1, "tushare"), (rows[0][0], 2, "tushare")]


def test_concurrent_event_ingest_serializes_one_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    event = {
        "id": "provider-42",
        "datetime": "2026-07-11 09:00:00",
        "title": "A",
        "content": "v1",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: ingest_rows_to_sqlite(db_path, "market_events", "news", [event]),
                range(2),
            )
        )

    assert sorted(results) == [0, 1]
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision FROM market_events"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][1] == 1


def test_relationship_member_apis_ingest_to_market_relationships(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_relationships",
        "index_member",
        [{"index_code": "000300.SH", "con_code": "600519.SH", "con_name": "贵州茅台", "trade_date": "20260709", "weight": 6.5}],
        source_name="index_member_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT provider, relationship_type, market, parent_symbol, child_symbol, child_name, weight FROM market_relationships",
    ) == (
        "tushare_index_member",
        "index_member",
        "Ashare",
        "000300.SH",
        "600519.SH",
        "贵州茅台",
        6.5,
    )


def test_fund_portfolio_ingests_to_dedicated_table(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    rows = ingest_rows_to_sqlite(
        db_path,
        "market_fund_portfolio",
        "fund_portfolio",
        [{"ts_code": "000001.OF", "stock_code": "600519.SH", "ann_date": "20260422", "end_date": "20260331", "mkv": 1200, "amount": 100, "stk_mkv_ratio": 3.5, "stk_float_ratio": 0.02}],
        source_name="fund_portfolio_rows_test",
    )

    assert rows == 1
    assert _fetchone(
        db_path,
        "SELECT market, symbol, holding_symbol, ann_date, end_date, market_value, amount, stk_mkv_ratio, stk_float_ratio, provider FROM market_fund_portfolio",
    ) == (
        "Fund",
        "000001.OF",
        "600519.SH",
        "20260422",
        "20260331",
        1200.0,
        100.0,
        3.5,
        0.02,
        "tushare_fund_portfolio",
    )


def test_ingest_rows_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    payload = [{"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260701", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10500}]

    first_rows = ingest_rows_to_sqlite(db_path, "market_bars_daily", "daily", payload, source_name="daily_rows_test")
    first_count = _count_rows(db_path, "market_bars_daily")
    second_rows = ingest_rows_to_sqlite(db_path, "market_bars_daily", "daily", payload, source_name="daily_rows_test")
    second_count = _count_rows(db_path, "market_bars_daily")

    assert first_rows == 1
    assert second_rows == 1
    assert first_count == 1
    assert second_count == 1


def test_ingest_rows_honors_global_read_model_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from storage import read_model_store

    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    lock_path = read_model_store._read_model_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SHAREDSIGNALS_READ_MODEL_LOCK_TIMEOUT", "0")

    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError):
            ingest_rows_to_sqlite(
                db_path,
                "market_bars_daily",
                "daily",
                [{"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260701", "close": 10.5}],
                source_name="daily_rows_test",
            )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert ingest_rows_to_sqlite(
        db_path,
        "market_bars_daily",
        "daily",
        [{"market": "Ashare", "symbol": "000001.SZ", "trade_date": "20260701", "close": 10.5}],
        source_name="daily_rows_test",
    ) == 1


def test_read_model_store_retries_sqlite_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    from storage import read_model_store

    calls = {"count": 0}

    def fake_ingest_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return 7

    monkeypatch.setattr(read_model_store, "_ingest_rows_to_sqlite_once", fake_ingest_once)
    monkeypatch.setattr(read_model_store.time, "sleep", lambda _seconds: None)

    rows = read_model_store._ingest_rows_to_sqlite_unlocked(
        "/tmp/marketdata.sqlite",
        "market_assets",
        "fund_basic",
        [{"ts_code": "000001.OF"}],
        source_name="fund_basic_rows_test",
    )

    assert rows == 7
    assert calls["count"] == 2
