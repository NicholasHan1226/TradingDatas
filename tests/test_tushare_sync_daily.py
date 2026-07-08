from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import collectors.tushare.sync_daily as sync_daily_module
from collectors.mixins.dedup import DeduplicatorMixin
from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import (
    DEFAULT_P0_STOCK_BATCH_SIZE,
    date_range,
    filter_apis,
    load_stock_codes,
    load_priority_stock_codes,
    load_config,
    is_ashare_intraday_session,
    normalize_ashare_code,
    parse_positive_int,
    resolve_api_window,
    select_priority_rotating_stock_batch,
    select_rotating_stock_batch,
    sync_tier,
)
from storage.csv_bridge import CSV_TO_TABLE_MAP


def test_resolve_api_window_uses_api_lookback_days() -> None:
    trade_date, start_date, end_date = resolve_api_window(
        {"api_name": "shibor_lpr", "lookback_days": 120},
        "20260704",
        "20260627",
        "20260704",
    )

    assert trade_date == "20260704"
    assert start_date == "20260306"
    assert end_date == "20260704"


def test_date_range_accepts_trade_date_override() -> None:
    trade_date, start_date, end_date = date_range(7, "20260703")

    assert trade_date == "20260703"
    assert start_date == "20260626"
    assert end_date == "20260703"


def test_only_api_filter_selects_named_api() -> None:
    apis = [{"api_name": "fut_daily"}, {"api_name": "fut_basic"}]

    assert filter_apis(apis, "fut_daily") == [{"api_name": "fut_daily"}]
    assert filter_apis(apis, "") == apis


def test_p6_fut_daily_is_global_trade_date_collection() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    fut_daily = [
        api for api in config["priorities"]["P6_other_daily"]
        if api.get("api_name") == "fut_daily"
    ][0]

    assert fut_daily["per_stock"] is False
    assert fut_daily["params"] == {"trade_date": "{trade_date}"}


def test_p6_fut_basic_collects_expiry_fields() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    fut_basic = [
        api for api in config["priorities"]["P6_other_daily"]
        if api.get("api_name") == "fut_basic"
    ][0]

    fields = {field.strip() for field in fut_basic["fields"].split(",")}
    assert {"ts_code", "name", "exchange", "list_date", "last_ddate", "delist_date"}.issubset(fields)


def test_configured_tushare_apis_have_sqlite_table_mapping() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    missing = []
    for tier, apis in config["priorities"].items():
        for api in apis:
            api_name = api["api_name"]
            if api_name not in CSV_TO_TABLE_MAP:
                missing.append(f"{tier}:{api_name}")

    assert missing == []


def test_configured_tushare_apis_are_allowed_by_api_gateway() -> None:
    from api_server import ALLOWED_TUSHARE_APIS

    config = load_config(Path("collectors/tushare/config.yaml"))
    missing = []
    for tier, apis in config["priorities"].items():
        for api in apis:
            api_name = api["api_name"]
            if api_name not in ALLOWED_TUSHARE_APIS:
                missing.append(f"{tier}:{api_name}")

    assert missing == []


def test_p6_news_announcement_event_apis_are_single_config_entries() -> None:
    from collections import Counter

    config = load_config(Path("collectors/tushare/config.yaml"))
    all_names = [
        api["api_name"]
        for apis in config["priorities"].values()
        for api in apis
    ]
    duplicate_names = {
        name: count
        for name, count in Counter(all_names).items()
        if count > 1
    }
    assert duplicate_names == {}

    p6_names = [api["api_name"] for api in config["priorities"]["P6_other_daily"]]
    counts = Counter(p6_names)

    for api_name in ("news", "major_news", "cctv_news", "anns_d", "report_rc"):
        assert counts[api_name] == 1

    p6_by_name = {
        api["api_name"]: api for api in config["priorities"]["P6_other_daily"]
    }
    assert p6_by_name["news"]["params"] == {
        "start_date": "{start_date}",
        "end_date": "{end_date}",
    }
    assert "url" in p6_by_name["news"]["fields"]
    assert p6_by_name["anns_d"]["params"] == {
        "start_date": "{start_date}",
        "end_date": "{end_date}",
    }
    assert p6_by_name["anns_d"]["per_stock"] is False


def test_p6_index_and_fund_daily_are_trade_date_snapshots() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p6_by_name = {
        api["api_name"]: api for api in config["priorities"]["P6_other_daily"]
    }

    for api_name in ("index_daily", "fund_daily"):
        api = p6_by_name[api_name]
        assert api["frequency"] == "daily"
        assert api["per_stock"] is False
        assert api["params"] == {"trade_date": "{trade_date}"}


def test_p6_cb_daily_is_global_trade_date_snapshot() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    cb_daily_apis = [
        api for api in config["priorities"]["P6_other_daily"]
        if api.get("api_name") == "cb_daily"
    ]

    assert len(cb_daily_apis) == 1
    assert cb_daily_apis[0]["per_stock"] is False
    assert cb_daily_apis[0]["params"] == {"trade_date": "{trade_date}"}


def test_sync_tier_marks_non_empty_rows_zero_sqlite_writes_failed(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            return [{"ts_code": "000001.SZ", "trade_date": "20260708"}]

    monkeypatch.setattr(sync_daily_module, "ingest_rows_to_sqlite", lambda *args, **kwargs: 0)

    stats = sync_tier(
        FakeCollector(),
        "P1_eod_daily",
        [{"api_name": "daily", "per_stock": False, "params": {"trade_date": "{trade_date}"}}],
        stock_codes=[],
        trade_date="20260708",
        start_date="20260708",
        end_date="20260708",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert stats["daily"]["sqlite_status"] == "failed"
    assert stats["daily"]["sqlite_errors"]
    assert stats["_tier_summary"]["sqlite_failure_count"] == 1


def test_exit_on_failure_considers_sqlite_failures() -> None:
    assert sync_daily_module._failure_exit_code(
        {"calls": 10, "failure_count": 6, "sqlite_failure_count": 0},
        threshold=0.5,
        exit_on_failure=True,
    ) == 2
    assert sync_daily_module._failure_exit_code(
        {"calls": 10, "failure_count": 0, "sqlite_failure_count": 1},
        threshold=0.5,
        exit_on_failure=True,
    ) == 2
    assert sync_daily_module._failure_exit_code(
        {"calls": 10, "failure_count": 4, "sqlite_failure_count": 0},
        threshold=0.5,
        exit_on_failure=True,
    ) == 0
    assert sync_daily_module._failure_exit_code(
        {"calls": 10, "failure_count": 10, "sqlite_failure_count": 10},
        threshold=0.5,
        exit_on_failure=False,
    ) == 0


def test_p6_cron_runs_after_market_close_only() -> None:
    crontabs = [
        Path("crontab.txt").read_text(encoding="utf-8"),
        Path("cron/crontab.txt").read_text(encoding="utf-8"),
    ]

    for crontab in crontabs:
        assert (
            "*/30 * * * * /opt/investment/SharedSignals/cron/collectors.sh --tier P6_other_daily"
            not in crontab
        )
        assert (
            "20 20 * * 1-6 /opt/investment/SharedSignals/cron/collectors.sh --tier P6_other_daily"
            in crontab
        )


def test_p0_trading_lane_only_contains_intraday_apis() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p0_names = [api["api_name"] for api in config["priorities"]["P0_trading_5min"]]

    assert p0_names == ["stk_mins", "rt_min"]
    assert DEFAULT_P0_STOCK_BATCH_SIZE == 30



def test_p0_priority_sources_do_not_read_cross_system_files() -> None:
    assert not hasattr(sync_daily_module, "DEFAULT_P0_PRIORITY_STOCK_FILES")
    assert not hasattr(sync_daily_module, "_priority_stock_paths")

def test_p1_ashare_scoring_apis_collect_90_day_per_symbol_windows() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p1_by_name = {
        api["api_name"]: api for api in config["priorities"]["P1_eod_daily"]
    }

    for api_name in ("daily", "stk_factor", "stk_factor_pro"):
        api = p1_by_name[api_name]
        assert api["lookback_days"] == 90
        assert api["per_stock"] is True
        assert api["params"] == {
            "ts_code": "{ts_code}",
            "start_date": "{start_date}",
            "end_date": "{end_date}",
        }


def test_p1_moneyflow_collects_daily_market_wide_snapshot() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p1_by_name = {
        api["api_name"]: api for api in config["priorities"]["P1_eod_daily"]
    }

    api = p1_by_name["moneyflow"]
    assert api["frequency"] == "daily"
    assert api["lookback_days"] == 7
    assert api["per_stock"] is False
    assert api["params"] == {"trade_date": "{trade_date}"}


def test_load_stock_codes_prefers_sqlite_market_assets(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE market_assets (
                market TEXT,
                symbol TEXT,
                name TEXT,
                asset_type TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_assets VALUES (?, ?, ?, ?)",
            [
                ("Ashare", "000001.SZ", "平安银行", "stock"),
                ("Ashare", "300750.SZ", "宁德时代", "stock"),
                ("Ashare", "600519.SH", "贵州茅台", "stock"),
                ("Ashare", "159001.SZ", "易方达货币ETF", "fund"),
                ("Ashare", "830000.BJ", "北交样本", "stock"),
                ("Ashare", "000003.SZ", "", "stock"),
                ("Ashare", "000004.SZ", "国华退", "stock"),
                ("US", "AAPL.US", "苹果", "stock"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    codes = load_stock_codes(sqlite_path=db_path)

    assert codes == ["000001.SZ", "300750.SZ", "600519.SH"]


def test_load_stock_codes_returns_empty_when_sqlite_missing(tmp_path: Path) -> None:
    codes = load_stock_codes(sqlite_path=tmp_path / "missing.sqlite")

    assert codes == []


def test_shibor_lpr_dedup_key_keeps_distinct_dates() -> None:
    collector = TushareCollector()

    rows = collector.deduplicate(
        "shibor_lpr",
        [
            {"date": "20260320", "1y": "3.0", "5y": "3.5"},
            {"date": "20260224", "1y": "3.0", "5y": "3.5"},
        ],
    )

    assert len(rows) == 2


def test_macro_dedup_keys_keep_distinct_periods_in_mixin_and_collector() -> None:
    rows = [
        {"month": "202606", "m2": "325000"},
        {"month": "202605", "m2": "323000"},
    ]

    assert len(TushareCollector().deduplicate("cn_m", rows)) == 2
    assert len(DeduplicatorMixin().deduplicate("cn_m", rows)) == 2

    gdp_rows = [
        {"quarter": "2025Q4", "gdp": "1349000"},
        {"quarter": "2025Q3", "gdp": "1015000"},
    ]
    assert len(TushareCollector().deduplicate("cn_gdp", gdp_rows)) == 2
    assert len(DeduplicatorMixin().deduplicate("cn_gdp", gdp_rows)) == 2


def test_parse_positive_int_uses_default_for_invalid_values() -> None:
    assert parse_positive_int("25", 10) == 25
    assert parse_positive_int("0", 10) == 10
    assert parse_positive_int("bad", 10) == 10


def test_select_rotating_stock_batch_persists_cursor(tmp_path: Path) -> None:
    state_path = tmp_path / "cursor.json"
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]

    first, first_meta = select_rotating_stock_batch(codes, batch_size=2, state_path=state_path)
    second, second_meta = select_rotating_stock_batch(codes, batch_size=2, state_path=state_path)

    assert first == ["000001.SZ", "000002.SZ"]
    assert first_meta["next_index"] == 2
    assert second == ["000003.SZ", "000004.SZ"]
    assert second_meta["next_index"] == 0


def test_select_rotating_stock_batch_wraps_at_end(tmp_path: Path) -> None:
    state_path = tmp_path / "cursor.json"
    state_path.write_text('{"next_index": 3}', encoding="utf-8")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]

    selected, meta = select_rotating_stock_batch(codes, batch_size=3, state_path=state_path)

    assert selected == ["000004.SZ", "000001.SZ", "000002.SZ"]
    assert meta["start_index"] == 3
    assert meta["next_index"] == 2


def test_select_rotating_stock_batch_resets_on_new_trade_date(tmp_path: Path) -> None:
    state_path = tmp_path / "cursor.json"
    state_path.write_text(
        '{"next_index": 3, "trade_date": "20260707"}',
        encoding="utf-8",
    )
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]

    selected, meta = select_rotating_stock_batch(
        codes,
        batch_size=2,
        state_path=state_path,
        trade_date="20260708",
    )

    assert selected == ["000001.SZ", "000002.SZ"]
    assert meta["start_index"] == 0
    assert meta["next_index"] == 2
    assert '"trade_date": "20260708"' in state_path.read_text(encoding="utf-8")


def test_is_ashare_intraday_session_windows() -> None:
    tz = ZoneInfo("Asia/Shanghai")

    assert is_ashare_intraday_session(datetime(2026, 7, 8, 9, 30, tzinfo=tz)) is True
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 13, 0, tzinfo=tz)) is True
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 9, 25, tzinfo=tz)) is False
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 12, 0, tzinfo=tz)) is False
    assert is_ashare_intraday_session(datetime(2026, 7, 11, 10, 0, tzinfo=tz)) is False


def test_normalize_ashare_code_filters_unsupported_symbols() -> None:
    assert normalize_ashare_code("600000") == "600000.SH"
    assert normalize_ashare_code("000001") == "000001.SZ"
    assert normalize_ashare_code("300750.SZ") == "300750.SZ"
    assert normalize_ashare_code("200011.SZ") == ""
    assert normalize_ashare_code("830000.BJ") == ""


def test_load_priority_stock_codes_reads_explicit_env_only() -> None:
    codes, meta = load_priority_stock_codes(
        explicit_codes="600000.SH,000001.SZ,300750,200011.SZ",
        allowed_codes={"600000.SH", "000001.SZ", "300750.SZ"},
    )

    assert codes == ["600000.SH", "000001.SZ", "300750.SZ"]
    assert meta["enabled"] is True
    assert meta["selected"] == 3


def test_select_priority_rotating_stock_batch_keeps_hot_pool_first(tmp_path: Path) -> None:
    state_path = tmp_path / "cursor.json"
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "600000.SH", "600001.SH"]

    selected, meta = select_priority_rotating_stock_batch(
        codes,
        batch_size=4,
        state_path=state_path,
        priority_codes=["600000.SH", "000003.SZ", "200011.SZ"],
    )

    assert selected[:2] == ["600000.SH", "000003.SZ"]
    assert len(selected) == 4
    assert meta["priority_count"] == 2
