from __future__ import annotations

from pathlib import Path

from collectors.mixins.dedup import DeduplicatorMixin
from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import date_range, filter_apis, load_config, resolve_api_window


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
