from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import collectors.tushare.sync_daily as sync_daily_module
from collectors.mixins.dedup import DeduplicatorMixin
from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import (
    date_range,
    filter_apis,
    load_stock_codes,
    load_config,
    is_ashare_intraday_session,
    resolve_api_window,
    sync_tier,
)
from storage.read_model_store import API_TO_TABLE_MAP


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
            if api_name not in API_TO_TABLE_MAP:
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


def test_every_per_stock_api_binds_the_requested_symbol() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    invalid = []
    for tier, apis in config["priorities"].items():
        for api in apis:
            if not api.get("per_stock", True):
                continue
            if "{ts_code}" not in str(api.get("params") or {}):
                invalid.append(f"{tier}:{api['api_name']}")

    assert invalid == []


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
        "start_date": "{start_datetime}",
        "end_date": "{end_datetime}",
    }
    assert "url" in p6_by_name["news"]["fields"]
    assert p6_by_name["major_news"]["params"] == {
        "start_date": "{start_datetime}",
        "end_date": "{end_datetime}",
    }
    assert p6_by_name["anns_d"]["params"] == {
        "start_date": "{start_date}",
        "end_date": "{end_date}",
    }
    assert p6_by_name["anns_d"]["per_stock"] is False


def test_fill_params_supports_datetime_bounds() -> None:
    params = sync_daily_module.fill_params(
        {
            "start_date": "{start_datetime}",
            "end_date": "{end_datetime}",
            "trade_date": "{trade_date}",
        },
        None,
        "20260709",
        "20260707",
        "20260709",
    )

    assert params == {
        "start_date": "2026-07-07 00:00:00",
        "end_date": "2026-07-09 23:59:59",
        "trade_date": "20260709",
    }


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


def test_first_batch_planned_apis_are_assigned_to_frequency_lanes() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    by_tier = {
        tier: {api["api_name"]: api for api in apis}
        for tier, apis in config["priorities"].items()
    }

    for api_name in ("namechange", "ths_index", "dc_index", "index_classify", "cb_basic", "opt_basic"):
        assert by_tier["P3_reference_daily"][api_name]["per_stock"] is False

    for api_name in ("fund_share", "fund_div", "cb_issue", "ft_limit"):
        assert by_tier["P6_other_daily"][api_name]["per_stock"] is False

    for api_name in ("weekly", "monthly", "index_weekly", "index_monthly"):
        assert by_tier["P7_low_frequency"][api_name]["per_stock"] is False


def test_sync_daily_tier_choices_come_from_config() -> None:
    assert "P7_low_frequency" in sync_daily_module.valid_tiers()


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


def test_sync_tier_accepts_idempotent_market_event_no_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            return [
                {
                    "title": "same event",
                    "pub_time": "2026-07-13 10:00:00",
                }
            ]

    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda *args, **kwargs: 0,
    )

    stats = sync_tier(
        FakeCollector(),
        "P6_other_daily",
        [
            {
                "api_name": "major_news",
                "per_stock": False,
                "params": {},
            }
        ],
        stock_codes=[],
        trade_date="20260713",
        start_date="20260713",
        end_date="20260713",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert stats["major_news"]["sqlite_status"] == "ok"
    assert stats["major_news"]["sqlite_errors"] == []
    assert stats["_tier_summary"]["sqlite_failure_count"] == 0


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
    p0_apis = config["priorities"]["P0_trading_5min"]

    assert [api["api_name"] for api in p0_apis] == ["rt_min"]
    assert p0_apis[0]["stock_batch_size"] == 300
    assert p0_apis[0]["empty_is_failure"] is True
    assert p0_apis[0]["failed_batch_retry_rounds"] == 2
    assert p0_apis[0]["failed_batch_retry_delay_seconds"] == 2
    configured_names = {
        api["api_name"]
        for tier in config["priorities"].values()
        for api in tier
    }
    assert "stk_mins" not in configured_names



def test_p0_priority_sources_do_not_read_cross_system_files() -> None:
    assert not hasattr(sync_daily_module, "DEFAULT_P0_PRIORITY_STOCK_FILES")
    assert not hasattr(sync_daily_module, "_priority_stock_paths")
    assert not hasattr(sync_daily_module, "select_rotating_stock_batch")
    assert not hasattr(sync_daily_module, "select_priority_rotating_stock_batch")


def test_p0_rt_min_batches_the_complete_stock_universe(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            assert api_name == "rt_min"
            calls.append(params["ts_code"])
            return [
                {"ts_code": code, "time": "2026-07-10 13:30:00", "close": 10.0}
                for code in params["ts_code"].split(",")
            ]

    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda _path, _table, _api, rows, **_kwargs: len(rows),
    )
    codes = [f"{index:06d}.SZ" for index in range(650)]

    stats = sync_tier(
        FakeCollector(),
        "P0_trading_5min",
        [{
            "api_name": "rt_min",
            "per_stock": True,
            "stock_batch_size": 300,
            "empty_is_failure": True,
            "params": {"freq": "5MIN", "ts_code": "{ts_code}"},
        }],
        stock_codes=codes,
        trade_date="20260710",
        start_date="20260710",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert [len(value.split(",")) for value in calls] == [300, 300, 50]
    assert stats["rt_min"]["calls"] == 3
    assert stats["rt_min"]["rows"] == 650
    assert stats["rt_min"]["sqlite_rows"] == 650
    assert stats["_tier_summary"]["failure_count"] == 0


def test_p0_rt_min_empty_batch_is_counted_as_failure(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            del api_name, params, fields
            return []

    monkeypatch.setattr(sync_daily_module, "ingest_rows_to_sqlite", lambda *args, **kwargs: 0)

    stats = sync_tier(
        FakeCollector(),
        "P0_trading_5min",
        [{
            "api_name": "rt_min",
            "per_stock": True,
            "stock_batch_size": 300,
            "empty_is_failure": True,
            "params": {"freq": "5MIN", "ts_code": "{ts_code}"},
        }],
        stock_codes=["000001.SZ", "000002.SZ"],
        trade_date="20260710",
        start_date="20260710",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert stats["rt_min"]["calls"] == 1
    assert stats["rt_min"]["failure_count"] == 1
    assert stats["_tier_summary"]["failure_count"] == 1
    assert stats["_tier_summary"]["critical_failure_count"] == 1
    assert sync_daily_module._failure_exit_code(
        stats["_tier_summary"],
        threshold=0.5,
        exit_on_failure=True,
    ) == 2

def test_p0_rt_min_retries_only_failed_batches(tmp_path: Path, monkeypatch) -> None:
    attempts: dict[str, int] = {}
    sleeps: list[float] = []

    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            del api_name, fields
            ts_code = params["ts_code"]
            attempts[ts_code] = attempts.get(ts_code, 0) + 1
            if ts_code == "000001.SZ,000002.SZ" and attempts[ts_code] == 1:
                self.last_collect_failed = True
                return []
            self.last_collect_failed = False
            return [
                {"ts_code": code, "time": "2026-07-10 14:55:00", "close": 10.0}
                for code in ts_code.split(",")
            ]

    monkeypatch.setattr(sync_daily_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda _path, _table, _api, rows, **_kwargs: len(rows),
    )

    stats = sync_tier(
        FakeCollector(),
        "P0_trading_5min",
        [{
            "api_name": "rt_min",
            "per_stock": True,
            "stock_batch_size": 2,
            "empty_is_failure": True,
            "failed_batch_retry_rounds": 2,
            "failed_batch_retry_delay_seconds": 2,
            "params": {"freq": "5MIN", "ts_code": "{ts_code}"},
        }],
        stock_codes=["000001.SZ", "000002.SZ", "000003.SZ"],
        trade_date="20260710",
        start_date="20260710",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert attempts == {"000001.SZ,000002.SZ": 2, "000003.SZ": 1}
    assert sleeps == [2]
    assert stats["rt_min"]["calls"] == 3
    assert stats["rt_min"]["rows"] == 3
    assert stats["rt_min"]["failure_count"] == 0
    assert stats["_tier_summary"]["critical_failure_count"] == 0


def test_p1_daily_collects_one_market_wide_trade_date_snapshot() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p1_by_name = {
        api["api_name"]: api for api in config["priorities"]["P1_eod_daily"]
    }

    daily = p1_by_name["daily"]
    assert daily["per_stock"] is False
    assert daily["params"] == {"trade_date": "{trade_date}"}
    assert daily["coverage_key"] == "ts_code"
    assert daily["min_universe_coverage_ratio"] == 0.9
    assert daily["row_limit_guard"] == 6000


def test_p1_unverified_research_apis_use_bounded_single_symbol_rotation() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p1_by_name = {
        api["api_name"]: api for api in config["priorities"]["P1_eod_daily"]
    }

    for api_name in (
        "stk_factor",
        "stk_factor_pro",
        "daily_basic",
        "cyq_perf",
        "cyq_chips",
        "adj_factor",
        "stk_auction",
        "stk_limit",
        "pledge_stat",
        "pledge_detail",
    ):
        api = p1_by_name[api_name]
        assert api["per_stock"] is True
        assert api["params"]["ts_code"] == "{ts_code}"
        assert api["bounded_rotation_size"] == 300
        assert not api.get("stock_batch_size")


def test_p1_repurchase_uses_market_wide_announcement_window() -> None:
    config = load_config(Path("collectors/tushare/config.yaml"))
    p1_by_name = {
        api["api_name"]: api for api in config["priorities"]["P1_eod_daily"]
    }

    repurchase = p1_by_name["repurchase"]
    assert repurchase["per_stock"] is False
    assert repurchase["params"] == {
        "start_date": "{start_date}",
        "end_date": "{end_date}",
    }
    assert repurchase["row_limit_guard"] == 2000


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


def test_p1_daily_completeness_guard_marks_silent_truncation_critical(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            assert api_name == "daily"
            assert params == {"trade_date": "20260710"}
            return [
                {"ts_code": "000001.SZ", "trade_date": "20260710"},
                {"ts_code": "000002.SZ", "trade_date": "20260710"},
            ]

    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda _path, _table, _api, rows, **_kwargs: len(rows),
    )
    universe = [f"{index:06d}.SZ" for index in range(10)]

    stats = sync_tier(
        FakeCollector(),
        "P1_eod_daily",
        [{
            "api_name": "daily",
            "per_stock": False,
            "params": {"trade_date": "{trade_date}"},
            "coverage_key": "ts_code",
            "min_universe_coverage_ratio": 0.9,
            "row_limit_guard": 6000,
        }],
        stock_codes=universe,
        trade_date="20260710",
        start_date="20260710",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert stats["daily"]["coverage_status"] == "failed"
    assert stats["daily"]["unique_symbols"] == 2
    assert stats["daily"]["universe_coverage_ratio"] == 0.2
    assert stats["daily"]["critical_failure_count"] == 1
    assert stats["_tier_summary"]["critical_failure_count"] == 1


def test_p1_global_row_limit_guard_marks_possible_truncation_critical(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            del api_name, params, fields
            return [{"ts_code": "000001.SZ", "ann_date": "20260710"}] * 3

    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda _path, _table, _api, rows, **_kwargs: len(rows),
    )

    stats = sync_tier(
        FakeCollector(),
        "P1_eod_daily",
        [{
            "api_name": "repurchase",
            "per_stock": False,
            "params": {"start_date": "{start_date}", "end_date": "{end_date}"},
            "row_limit_guard": 3,
        }],
        stock_codes=[],
        trade_date="20260710",
        start_date="20260701",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert stats["repurchase"]["possible_truncation"] is True
    assert stats["repurchase"]["critical_failure_count"] == 1


def test_p1_bounded_rotation_limits_provider_calls_without_batching(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeCollector:
        last_collect_failed = False

        def collect(self, api_name, params, fields=None):
            del api_name, fields
            calls.append(params["ts_code"])
            return [{"ts_code": params["ts_code"], "trade_date": "20260710"}]

    monkeypatch.setattr(
        sync_daily_module,
        "ingest_rows_to_sqlite",
        lambda _path, _table, _api, rows, **_kwargs: len(rows),
    )
    universe = [f"{index:06d}.SZ" for index in range(1000)]

    stats = sync_tier(
        FakeCollector(),
        "P1_eod_daily",
        [{
            "api_name": "pledge_stat",
            "per_stock": True,
            "params": {"ts_code": "{ts_code}"},
            "bounded_rotation_size": 300,
        }],
        stock_codes=universe,
        trade_date="20260710",
        start_date="20260710",
        end_date="20260710",
        sqlite_db_path=tmp_path / "marketdata.sqlite",
    )

    assert len(calls) == 300
    assert all("," not in code for code in calls)
    assert stats["pledge_stat"]["universe_symbols"] == 1000
    assert stats["pledge_stat"]["scheduled_symbols"] == 300
    assert stats["pledge_stat"]["collection_mode"] == "bounded_rotation"


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


def test_ashare_symbol_validation_binds_prefix_to_exchange() -> None:
    assert sync_daily_module._looks_like_ashare_stock_code("000001.SZ") is True
    assert sync_daily_module._looks_like_ashare_stock_code("600000.SH") is True
    assert sync_daily_module._looks_like_ashare_stock_code("000001.SH") is False
    assert sync_daily_module._looks_like_ashare_stock_code("600000.SZ") is False


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


def test_is_ashare_intraday_session_windows() -> None:
    tz = ZoneInfo("Asia/Shanghai")

    assert is_ashare_intraday_session(datetime(2026, 7, 8, 9, 30, tzinfo=tz)) is True
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 13, 0, tzinfo=tz)) is True
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 9, 25, tzinfo=tz)) is False
    assert is_ashare_intraday_session(datetime(2026, 7, 8, 12, 0, tzinfo=tz)) is False
    assert is_ashare_intraday_session(datetime(2026, 7, 11, 10, 0, tzinfo=tz)) is False
