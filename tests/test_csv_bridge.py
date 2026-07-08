from __future__ import annotations

import fcntl
import logging
import sqlite3
from pathlib import Path

import pytest

from storage.csv_bridge import CSV_TO_TABLE_MAP, ingest_csv_to_sqlite
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


def test_rt_min_ingests_intraday_with_metadata(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "rt_min" / "20260706" / "000001.SZ.csv",
        "\n".join(
            [
                "ts_code,freq,time,open,close,high,low,vol,amount",
                "000001.SZ,5MIN,2026-07-06 09:55:00,10.27,10.28,10.32,10.27,2245200,23112441",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_intraday", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT market, symbol, trade_date, bar_time, interval, provider, close, volume, amount "
            "FROM market_bars_intraday"
        ).fetchone()
    finally:
        conn.close()
    assert row == (
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


def test_rt_fut_min_ingests_futures_intraday_with_code_time_fields(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "rt_fut_min" / "20260703" / "rt_fut_min_20260703_5min.csv",
        "\n".join(
            [
                "code,time,open,close,high,low,vol,amount",
                "RB2609.SHF,2026-07-03 14:55:00,3500,3520,3530,3490,1000,3520000",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_intraday", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT market, symbol, trade_date, bar_time, interval, provider, close, volume, amount "
            "FROM market_bars_intraday"
        ).fetchone()
    finally:
        conn.close()
    assert row == (
        "Futures",
        "RB2609.SHF",
        "20260703",
        "2026-07-03 14:55:00",
        "5min",
        "tushare_rt_fut_min",
        3520.0,
        1000.0,
        3520000.0,
    )


def test_rt_fut_min_ingests_quote_and_expiry_fields(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "rt_fut_min" / "20260703" / "rt_fut_min_20260703_5min.csv",
        "\n".join(
            [
                "code,time,open,close,high,low,vol,amount,bid1,ask1,bid1_volume,ask1_volume,last_trade_date,expiry_date",
                "RB2609.SHF,2026-07-03 14:55:00,3500,3520,3530,3490,1000,3520000,3519,3521,12,9,20260915,20260930",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_intraday", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT bid_price, ask_price, bid_size, ask_size, last_trade_date, expiry_date "
            "FROM market_bars_intraday"
        ).fetchone()
    finally:
        conn.close()
    assert row == (3519.0, 3521.0, 12.0, 9.0, "20260915", "20260930")


def test_rt_fut_min_backfills_expiry_from_market_assets(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    asset_csv = _write_csv(
        tmp_path / "data" / "tushare" / "fut_basic" / "20260703" / "fut_basic_20260703.csv",
        "\n".join(
            [
                "ts_code,name,exchange,list_date,last_trade_date,delist_date",
                "RB2609.SHF,螺纹钢2609,SHFE,20260101,20260915,20260930",
            ]
        ),
    )
    bar_csv = _write_csv(
        tmp_path / "data" / "tushare" / "rt_fut_min" / "20260703" / "rt_fut_min_20260703_5min.csv",
        "\n".join(
            [
                "code,time,open,close,high,low,vol,amount",
                "RB2609.SHF,2026-07-03 14:55:00,3500,3520,3530,3490,1000,3520000",
            ]
        ),
    )

    ingest_csv_to_sqlite(db_path, "market_assets", asset_csv)
    rows = ingest_csv_to_sqlite(db_path, "market_bars_intraday", bar_csv)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT last_trade_date, expiry_date FROM market_bars_intraday WHERE symbol='RB2609.SHF'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("20260915", "20260930")


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


def test_stk_factor_ingests_daily_bars_and_factor_metrics(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "stk_factor" / "20260704" / "600519.SH.csv",
        "\n".join(
            [
                "ts_code,trade_date,open,high,low,close,vol,amount,pe,pb,turnover_rate",
                "600519.SH,20260704,1200,1210,1190,1205,1000,1205000,22.5,8.2,0.31",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["stk_factor"], csv_path)

    assert rows == 4
    conn = sqlite3.connect(str(db_path))
    try:
        daily = conn.execute(
            "SELECT market, symbol, trade_date, close, provider FROM market_bars_daily"
        ).fetchone()
        factors = conn.execute(
            "SELECT factor_name, value FROM market_factors ORDER BY factor_name"
        ).fetchall()
    finally:
        conn.close()
    assert daily == ("Ashare", "600519.SH", "20260704", 1205.0, "tushare_stk_factor")
    assert factors == [
        ("stk_factor:pb", 8.2),
        ("stk_factor:pe", 22.5),
        ("stk_factor:turnover_rate", 0.31),
    ]


def test_daily_basic_and_stk_factor_pro_map_to_factor_table() -> None:
    assert CSV_TO_TABLE_MAP["daily_basic"] == "market_factors"
    assert CSV_TO_TABLE_MAP["stk_factor_pro"] == "market_factors"


def test_index_global_derives_global_market_for_daily_bars(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "index_global" / "20260704" / "index_global_20260704.csv",
        "\n".join(
            [
                "ts_code,trade_date,open,close,high,low,pct_chg",
                "CKLSE,20260703,1665.73,1679.05,1682.62,1662.91,1.04",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        record = conn.execute(
            "SELECT market, symbol, trade_date, close, provider FROM market_bars_daily"
        ).fetchone()
    finally:
        conn.close()
    assert record == ("Global", "CKLSE", "20260703", 1679.05, "tushare_index_global")


def test_fut_daily_derives_futures_market_for_daily_bars(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "fut_daily" / "20260703" / "fut_daily_20260703.csv",
        "\n".join(
            [
                "ts_code,trade_date,open,high,low,close,vol,amount",
                "RB2601.SHF,20260703,3500,3550,3480,3520,1000,3520000",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        record = conn.execute(
            "SELECT market, symbol, trade_date, close, volume, amount, provider FROM market_bars_daily"
        ).fetchone()
    finally:
        conn.close()
    assert record == ("Futures", "RB2601.SHF", "20260703", 3520.0, 1000.0, 3520000.0, "tushare_fut_daily")


def test_etf_basic_maps_to_market_assets_with_name(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "etf_basic" / "20260704" / "etf_basic_20260704.csv",
        "\n".join(
            [
                "ts_code,csname,cname,list_status,exchange,list_date,etf_type",
                "158000.SZ,鹏华中证港股通内地金融ETF,鹏华中证港股通内地金融交易型开放式指数证券投资基金,P,SZ,,纯境内",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["etf_basic"], csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        record = conn.execute(
            "SELECT market, symbol, name, asset_type, exchange, status, provider FROM market_assets"
        ).fetchone()
    finally:
        conn.close()
    assert record == (
        "ETF",
        "158000.SZ",
        "鹏华中证港股通内地金融ETF",
        "etf",
        "SZ",
        "P",
        "tushare_etf_basic",
    )


def test_stock_company_does_not_blank_stock_basic_asset_fields(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    stock_basic = _write_csv(
        tmp_path / "data" / "tushare" / "stock_basic" / "20260705" / "stock_basic_20260705.csv",
        "\n".join(
            [
                "ts_code,name,industry,list_date",
                "000001.SZ,平安银行,银行,19910403",
            ]
        ),
    )
    stock_company = _write_csv(
        tmp_path / "data" / "tushare" / "stock_company" / "20260705" / "stock_company_20260705.csv",
        "\n".join(
            [
                "ts_code,chairman,manager,list_date",
                "000001.SZ,,,19910403",
            ]
        ),
    )

    assert ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["stock_basic"], stock_basic) == 1
    assert ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["stock_company"], stock_company) == 1

    conn = sqlite3.connect(str(db_path))
    try:
        record = conn.execute(
            "SELECT symbol, name, sector, list_date, provider FROM market_assets WHERE symbol = ?",
            ("000001.SZ",),
        ).fetchone()
    finally:
        conn.close()
    assert record == ("000001.SZ", "平安银行", "银行", "19910403", "tushare_stock_company")


def test_low_frequency_macro_bridge_map_covers_p4_macro_apis() -> None:
    assert CSV_TO_TABLE_MAP["cn_gdp"] == "market_factors"
    assert CSV_TO_TABLE_MAP["sf_month"] == "market_factors"
    assert CSV_TO_TABLE_MAP["us_tycr"] == "market_factors"
    assert CSV_TO_TABLE_MAP["us_tbr"] == "market_factors"
    assert CSV_TO_TABLE_MAP["us_tltr"] == "market_factors"
    assert CSV_TO_TABLE_MAP["repo_daily"] == "market_factors"


def test_repo_daily_keeps_factor_rows_and_projects_daily_bars(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "repo_daily" / "20260706" / "repo_daily_20260706.csv",
        "\n".join(
            [
                "ts_code,trade_date,repo_maturity,pre_close,open,high,low,close,weight,amount,num",
                "204001.SH,20260706,GC001,1.60,1.55,2.10,1.40,1.88,1.70,1000000,1200",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["repo_daily"], csv_path)

    assert rows == 9
    conn = sqlite3.connect(str(db_path))
    try:
        factor_names = [
            row[0]
            for row in conn.execute(
                "SELECT factor_name FROM market_factors ORDER BY factor_name"
            ).fetchall()
        ]
        bar = conn.execute(
            "SELECT market, symbol, trade_date, open, high, low, close, amount, provider "
            "FROM market_bars_daily"
        ).fetchone()
    finally:
        conn.close()
    assert "repo_daily:close" in factor_names
    assert bar == (
        "Ashare",
        "204001.SH",
        "20260706",
        1.55,
        2.1,
        1.4,
        1.88,
        1000000.0,
        "tushare_repo_daily",
    )


def test_cctv_news_derives_market_event_hash_and_metadata(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "cctv_news" / "20260704" / "cctv_news_20260704.csv",
        "\n".join(
            [
                "date,title,content",
                "20260702,headline one,content one",
                "20260703,headline two,content two",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_events", csv_path)

    assert rows == 2
    conn = sqlite3.connect(str(db_path))
    try:
        records = conn.execute(
            "SELECT event_hash, provider, event_type, event_time, trade_date, title, content, source_file "
            "FROM market_events ORDER BY trade_date"
        ).fetchall()
    finally:
        conn.close()
    assert len(records) == 2
    assert records[0][0]
    assert records[0][1:] == (
        "tushare_cctv_news",
        "cctv_news",
        "20260702",
        "20260702",
        "headline one",
        "content one",
        "cctv_news_20260704.csv",
    )


def test_anns_d_derives_announcement_market_event(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "anns_d" / "20260708" / "anns_d_20260708.csv",
        "\n".join(
            [
                "ts_code,name,ann_date,title,url,rec_time",
                "600276.SH,恒瑞医药,20260708,董事会公告,https://example.com/ann,2026-07-08 20:00:00",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, CSV_TO_TABLE_MAP["anns_d"], csv_path)

    assert rows == 1
    conn = sqlite3.connect(str(db_path))
    try:
        record = conn.execute(
            "SELECT provider, event_type, event_time, trade_date, market, symbol, title, url "
            "FROM market_events"
        ).fetchone()
    finally:
        conn.close()
    assert record == (
        "tushare_anns_d",
        "anns_d",
        "20260708",
        "20260708",
        "Ashare",
        "600276.SH",
        "董事会公告",
        "https://example.com/ann",
    )


def test_monthly_macro_factor_uses_month_as_event_time(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "data" / "tushare" / "cn_cpi" / "20260704" / "cn_cpi_20260704.csv",
        "\n".join(
            [
                "month,nt_val,town_val",
                "202606,100.4,100.5",
            ]
        ),
    )

    rows = ingest_csv_to_sqlite(db_path, "market_factors", csv_path)

    assert rows == 2
    conn = sqlite3.connect(str(db_path))
    try:
        records = conn.execute(
            "SELECT factor_name, event_time, value FROM market_factors ORDER BY factor_name"
        ).fetchall()
    finally:
        conn.close()
    assert records == [
        ("cn_cpi:nt_val", "202606", 100.4),
        ("cn_cpi:town_val", "202606", 100.5),
    ]


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


def test_ingest_csv_to_sqlite_honors_global_bridge_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from storage import csv_bridge

    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    csv_path = _write_csv(
        tmp_path / "daily.csv",
        "\n".join(
            [
                "market,symbol,trade_date,open,high,low,close,volume,amount,provider",
                "Ashare,000001.SZ,20260701,10,11,9,10.5,1000,10500,tushare",
            ]
        ),
    )
    lock_path = csv_bridge._bridge_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SHAREDSIGNALS_CSV_BRIDGE_LOCK_TIMEOUT", "0")

    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError):
            ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    rows = ingest_csv_to_sqlite(db_path, "market_bars_daily", csv_path)

    assert rows == 1
    assert _count_rows(db_path, "market_bars_daily") == 1


def test_csv_bridge_retries_sqlite_busy(monkeypatch: pytest.MonkeyPatch):
    from storage import csv_bridge

    calls = {"count": 0}

    def fake_ingest_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return 7

    monkeypatch.setattr(csv_bridge, "_ingest_csv_to_sqlite_once", fake_ingest_once)
    monkeypatch.setattr(csv_bridge.time, "sleep", lambda _seconds: None)

    rows = csv_bridge._ingest_csv_to_sqlite_unlocked("/tmp/marketdata.sqlite", "market_assets", "/tmp/fund_basic.csv")

    assert rows == 7
    assert calls["count"] == 2
