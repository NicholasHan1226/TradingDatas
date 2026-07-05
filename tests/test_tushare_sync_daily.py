from __future__ import annotations

from pathlib import Path

from collectors.mixins.dedup import DeduplicatorMixin
from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import (
    date_range,
    filter_apis,
    load_config,
    parse_positive_int,
    resolve_api_window,
    select_rotating_stock_batch,
)


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
