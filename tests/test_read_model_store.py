from __future__ import annotations

import fcntl
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dataset_registry import load_dataset_registry
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


@pytest.mark.parametrize(
    ("table", "api_name", "trusted_provider", "row", "expected_provider"),
    [
        (
            "market_bars_daily",
            "daily",
            "tushare_daily",
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260716",
                "close": 10.0,
                "provider": "row-spoof-daily",
            },
            "tushare_daily",
        ),
        (
            "market_bars_intraday",
            "rt_fut_min",
            "tushare_rt_fut_min",
            {
                "ts_code": "RB2609.SHF",
                "time": "2026-07-16 09:05:00",
                "close": 3500.0,
                "provider": "sina_futures_minute",
            },
            "tushare_rt_fut_min",
        ),
    ],
)
def test_bar_provider_claim_is_persisted_before_trusted_identity_overwrite(
    tmp_path: Path,
    table: str,
    api_name: str,
    trusted_provider: str,
    row: dict,
    expected_provider: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    assert ingest_rows_to_sqlite(
        db_path,
        table,
        api_name,
        [row],
        source_name=f"{api_name}_provider_claim_test",
        provider_discriminator=trusted_provider,
    ) == 1

    stored_provider, stored_raw_json = _fetchone(
        db_path,
        f"SELECT provider, raw_json FROM {table}",
    )
    provenance = json.loads(stored_raw_json)
    assert stored_provider == expected_provider
    assert provenance["_sharedsignals_provenance"] == {
        "provider_claim": row["provider"],
        "raw_payload_source": "row",
        "schema": "provider-claim.v1",
    }
    assert provenance["raw_payload"] == row


def test_existing_raw_json_keeps_payload_and_provider_claim_in_envelope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    original_raw_json = '{"payload":"kept","nested":{"x":1}}'

    assert ingest_rows_to_sqlite(
        db_path,
        "market_bars_daily",
        "daily",
        [
            {
                "ts_code": "000002.SZ",
                "trade_date": "20260716",
                "close": 20.0,
                "provider": "row-spoof-existing-raw",
                "raw_json": original_raw_json,
            }
        ],
        source_name="daily_existing_raw_provider_claim_test",
        provider_discriminator="tushare_daily",
    ) == 1

    stored_provider, stored_raw_json = _fetchone(
        db_path,
        "SELECT provider, raw_json FROM market_bars_daily",
    )
    provenance = json.loads(stored_raw_json)
    assert stored_provider == "tushare_daily"
    assert provenance["_sharedsignals_provenance"] == {
        "provider_claim": "row-spoof-existing-raw",
        "raw_payload_source": "raw_json",
        "schema": "provider-claim.v1",
    }
    assert provenance["raw_payload"] == original_raw_json


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
        provider_discriminator="tushare_rt_fut_min",
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


def test_rt_fut_min_missing_or_unknown_provider_context_fails_closed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    rows = [
        {
            "code": "RB2609.SHF",
            "time": "2026-07-03 14:55:00",
            "provider": "sina_futures_minute",
            "close": 3520,
        }
    ]

    with pytest.raises(ValueError, match="provider_discriminator.*required"):
        ingest_rows_to_sqlite(
            db_path,
            "market_bars_intraday",
            "rt_fut_min",
            rows,
            source_name="ambiguous_rt_fut_min_rows_test",
        )
    with pytest.raises(ValueError, match="unknown provider_discriminator"):
        ingest_rows_to_sqlite(
            db_path,
            "market_bars_intraday",
            "rt_fut_min",
            rows,
            source_name="unknown_rt_fut_min_rows_test",
            provider_discriminator="row-spoof",
        )

    assert _count_rows(db_path, "market_bars_intraday") == 0


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


@pytest.mark.parametrize(
    ("api_name", "row"),
    [
        (
            "repo_daily",
            {
                "ts_code": "204001.SH",
                "trade_date": "20260716",
                "open": 1.2,
                "high": 1.5,
                "low": 1.0,
                "close": 1.4,
                "vol": 1000,
                "amount": 1400,
            },
        ),
        (
            "stk_factor",
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260716",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "vol": 1000,
                "amount": 10200,
                "adj_factor": 1.23,
            },
        ),
    ],
)
def test_multitable_ingest_matches_registry_target_tables(
    tmp_path: Path,
    api_name: str,
    row: dict,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    registry = load_dataset_registry()
    dataset = registry.resolve(f"tushare.{api_name}")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")

    rows_written = ingest_rows_to_sqlite(
        db_path,
        dataset.read_model_adapter.primary_table,
        api_name,
        [row],
        source_name=f"{api_name}_registry_target_test",
    )

    candidate_tables = {"market_bars_daily", "market_factors"}
    table_counts = {
        table: _count_rows(db_path, table) for table in candidate_tables
    }
    assert {table for table, count in table_counts.items() if count} == set(
        binding.target_tables
    )
    assert rows_written == sum(table_counts.values())


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


REGISTERED_EVENT_IDENTITY_CASES = (
    (
        "block_trade",
        {
            "ts_code": "600000.SH",
            "trade_date": "20260713",
            "price": 10.0,
            "vol": 1000,
            "buyer": "buyer-a",
            "seller": "seller-b",
        },
        "trade_date",
    ),
    (
        "limit_list",
        {"ts_code": "600000.SH", "trade_date": "20260713"},
        "trade_date",
    ),
    (
        "limit_list_d",
        {"ts_code": "600000.SH", "trade_date": "20260713"},
        "trade_date",
    ),
    (
        "broker_recommend",
        {"month": "202607", "broker": "broker-a", "ts_code": "600000.SH"},
        "ts_code",
    ),
    (
        "suspend_d",
        {"ts_code": "600000.SH", "suspend_date": "20260713"},
        "suspend_date",
    ),
    (
        "namechange",
        {"ts_code": "600000.SH", "start_date": "20260713", "name": "new-name"},
        "start_date",
    ),
    ("cb_issue", {"ts_code": "123456.SZ"}, "ts_code"),
    (
        "news",
        {"datetime": "2026-07-13 09:00:00", "title": "headline"},
        "datetime",
    ),
    (
        "major_news",
        {"pub_time": "2026-07-13 09:00:00", "title": "major headline"},
        "pub_time",
    ),
    (
        "cctv_news",
        {"date": "20260713", "broadcast_time": "19:00", "title": "broadcast"},
        "date",
    ),
    (
        "anns_d",
        {"ts_code": "600000.SH", "ann_date": "20260713", "title": "announcement"},
        "ann_date",
    ),
    (
        "report_rc",
        {
            "ts_code": "600000.SH",
            "report_date": "20260713",
            "report_title": "research report",
        },
        "report_date",
    ),
)


@pytest.mark.parametrize("identity_state", ["missing", "blank", "null", "whitespace"])
@pytest.mark.parametrize(
    ("api_name", "complete", "identity_field"),
    REGISTERED_EVENT_IDENTITY_CASES,
)
def test_registered_event_identity_uses_original_fields_before_normalization(
    tmp_path: Path,
    api_name: str,
    complete: dict[str, object],
    identity_field: str,
    identity_state: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    canonical_aliases = {
        "event_time": "2026-07-13 09:00:00",
        "symbol": str(complete.get("ts_code") or "ALIAS.SYMBOL"),
        "volume": complete.get("vol", 1000),
    }
    incomplete = {**complete, **canonical_aliases}
    if identity_state == "missing":
        incomplete.pop(identity_field)
    elif identity_state == "blank":
        incomplete[identity_field] = ""
    elif identity_state == "null":
        incomplete[identity_field] = None
    else:
        incomplete[identity_field] = "   "
    original_incomplete = dict(incomplete)

    with pytest.raises(ValueError, match="missing required business key"):
        ingest_rows_to_sqlite(
            db_path,
            "market_events",
            api_name,
            [incomplete],
        )

    assert incomplete == original_incomplete
    assert _count_rows(db_path, "market_events") == 0
    complete_with_aliases = {**complete, **canonical_aliases}
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        api_name,
        [complete_with_aliases],
    ) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        api_name,
        [complete_with_aliases],
    ) == 0


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


def test_provider_business_key_events_ingest_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    namechange = {
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "start_date": "20260713",
        "ann_date": "20260713",
        "change_reason": "简称变更",
    }
    report = {
        "ts_code": "600000.SH",
        "report_date": "20260713",
        "report_title": "盈利预测更新",
        "org_name": "示例机构",
    }

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "namechange",
        [namechange],
    ) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "namechange",
        [namechange],
    ) == 0
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "report_rc",
        [report],
    ) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "report_rc",
        [report],
    ) == 0

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_type, event_time, trade_date, symbol "
            "FROM market_events ORDER BY event_type"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("namechange", "20260713", "20260713", "000001.SZ"),
        ("report_rc", "20260713", "20260713", "600000.SH"),
    ]


def test_cb_issue_replay_is_idempotent_and_content_change_is_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    first = {
        "ts_code": "123456.SZ",
        "ann_date": "20260713",
        "issue_size": 10.0,
        "issue_price": 100.0,
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "cb_issue", [first]) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [dict(reversed(list(first.items())))],
    ) == 0
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [{**first, "issue_size": 11.0}],
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision FROM market_events ORDER BY revision"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [(rows[0][0], 1), (rows[0][0], 2)]


def test_cb_issue_provider_claim_replay_keeps_one_canonical_revision(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "123456.SZ",
        "ann_date": "20260713",
        "issue_size": 10.0,
        "issue_price": 100.0,
        "provider": "spoof-source",
    }

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [row],
        source_name="cb_issue_provider_claim_replay_test",
    ) == 1
    first_stored = _fetchone(
        db_path,
        "SELECT revision, event_id, provider, event_type, raw_json "
        "FROM market_events",
    )
    assert first_stored[:4] == (
        1,
        first_stored[1],
        "tushare_cb_issue",
        "cb_issue",
    )
    assert json.loads(first_stored[4])["_sharedsignals_provenance"][
        "provider_claim"
    ] == "spoof-source"

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [row],
        source_name="cb_issue_provider_claim_replay_test",
    ) == 0
    assert _count_rows(db_path, "market_events") == 1
    assert _fetchone(
        db_path,
        "SELECT revision, event_id, provider, event_type, raw_json "
        "FROM market_events",
    ) == first_stored

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [{**row, "issue_price": 101.0}],
        source_name="cb_issue_provider_claim_replay_test",
    ) == 1
    conn = sqlite3.connect(db_path)
    try:
        revisions = conn.execute(
            "SELECT revision, event_id, provider, raw_json "
            "FROM market_events ORDER BY revision"
        ).fetchall()
    finally:
        conn.close()
    assert [item[:3] for item in revisions] == [
        (1, first_stored[1], "tushare_cb_issue"),
        (2, first_stored[1], "tushare_cb_issue"),
    ]
    provenance = [json.loads(item[3]) for item in revisions]
    assert [
        item["_sharedsignals_provenance"]["provider_claim"]
        for item in provenance
    ] == ["spoof-source", "spoof-source"]
    assert [item["raw_payload"]["issue_price"] for item in provenance] == [
        100.0,
        101.0,
    ]


def test_registered_event_route_cannot_be_spoofed_by_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "123456.SZ",
        "ann_date": "20260713",
        "issue_price": 100.0,
        "provider": "spoof-source",
        "event_type": "forged-type",
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "cb_issue", [row]) == 1
    stored = _fetchone(
        db_path,
        "SELECT provider, event_type, raw_json FROM market_events",
    )

    assert stored[:2] == ("tushare_cb_issue", "cb_issue")
    raw = json.loads(stored[2])
    assert raw["_sharedsignals_provenance"]["provider_claim"] == "spoof-source"


def test_prewrapped_raw_cannot_replace_current_provider_claim(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    prewrapped = json.dumps(
        {
            "_sharedsignals_provenance": {
                "provider_claim": "nested-forged",
                "raw_payload_source": "row",
                "schema": "provider-claim.v1",
            },
            "raw_payload": {"ts_code": "123456.SZ", "issue_price": 100.0},
        },
        sort_keys=True,
    )

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [
            {
                "ts_code": "123456.SZ",
                "ann_date": "20260713",
                "issue_price": 100.0,
                "provider": "current-spoof",
                "raw_json": prewrapped,
            }
        ],
    ) == 1
    raw = json.loads(
        _fetchone(db_path, "SELECT raw_json FROM market_events")[0]
    )

    assert raw["_sharedsignals_provenance"]["provider_claim"] == "current-spoof"


@pytest.mark.parametrize(
    "raw_json",
    [
        "",
        "opaque",
        json.dumps({"ts_code": "123456.SZ", "issue_price": 99.0}),
    ],
)
def test_cb_issue_raw_provenance_cannot_hide_business_revision(
    tmp_path: Path,
    raw_json: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "123456.SZ",
        "ann_date": "20260713",
        "issue_price": 100.0,
        "provider": "spoof-source",
        "raw_json": raw_json,
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "cb_issue", [row]) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "cb_issue",
        [{**row, "issue_price": 101.0}],
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision FROM market_events ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(rows[0][0], 1), (rows[0][0], 2)]


def test_block_trade_without_native_id_keeps_distinct_complete_facts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
        "price": 10.0,
        "vol": 1000,
        "buyer": "buyer-a",
        "seller": "seller-b",
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "block_trade", [row]) == 1
    assert ingest_rows_to_sqlite(db_path, "market_events", "block_trade", [row]) == 0
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "block_trade",
        [{**row, "price": 10.1}],
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision FROM market_events ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    assert [revision for _, revision in rows] == [1, 1]
    assert len({event_id for event_id, _ in rows}) == 2


def test_block_trade_nested_fake_id_cannot_join_distinct_facts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
        "price": 10.0,
        "vol": 1000,
        "buyer": "buyer-a",
        "seller": "seller-b",
        "raw_json": json.dumps({"id": "forged-block-id"}),
    }

    assert ingest_rows_to_sqlite(db_path, "market_events", "block_trade", [row]) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "block_trade",
        [{**row, "price": 10.1}],
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, revision FROM market_events ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    assert [revision for _, revision in rows] == [1, 1]
    assert len({event_id for event_id, _ in rows}) == 2


def test_block_trade_prewrapped_nested_fake_ids_do_not_duplicate_replay(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
        "price": 10.0,
        "vol": 1000,
        "buyer": "buyer-a",
        "seller": "seller-b",
    }

    def prewrapped(fake_id: str) -> str:
        return json.dumps(
            {
                "_sharedsignals_provenance": {
                    "provider_claim": "nested-forged",
                    "raw_payload_source": "row",
                    "schema": "provider-claim.v1",
                },
                "raw_payload": {"id": fake_id},
            },
            sort_keys=True,
        )

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "block_trade",
        [{**row, "raw_json": prewrapped("forged-a")}],
    ) == 1
    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "block_trade",
        [{**row, "raw_json": prewrapped("forged-b")}],
    ) == 0

    assert _fetchone(
        db_path,
        "SELECT COUNT(*), MIN(revision), MAX(revision) FROM market_events",
    ) == (1, 1, 1)


def test_block_trade_nested_seller_cannot_complete_missing_top_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    base = {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
        "price": 10.0,
        "vol": 1000,
        "buyer": "A",
    }

    rows = []
    for fake_id, nested_seller in (("forged-a", "B"), ("forged-c", "C")):
        nested_identity = {**base, "id": fake_id, "seller": nested_seller}
        rows.append(
            {
                **base,
                "raw_json": json.dumps(
                    {"metadata": nested_identity},
                    sort_keys=True,
                ),
            }
        )

    with pytest.raises(ValueError, match="missing required business key.*seller"):
        ingest_rows_to_sqlite(
            db_path,
            "market_events",
            "block_trade",
            rows,
        )

    assert _count_rows(db_path, "market_events") == 0


def test_block_trade_missing_business_key_rolls_back_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    with pytest.raises(ValueError, match="missing required business key"):
        ingest_rows_to_sqlite(
            db_path,
            "market_events",
            "block_trade",
            [
                {
                    "ts_code": "600000.SH",
                    "trade_date": "20260713",
                    "price": 10.0,
                    "vol": 1000,
                    "buyer": "buyer-a",
                    "seller": "seller-b",
                },
                {
                    "ts_code": "600001.SH",
                    "trade_date": "20260713",
                    "price": 10.0,
                    "vol": 1000,
                    "buyer": "buyer-a",
                },
            ],
        )

    assert _count_rows(db_path, "market_events") == 0


@pytest.mark.parametrize("api_name", ["news", "anns_d"])
def test_nested_raw_replay_and_content_change_are_symmetric(
    tmp_path: Path,
    api_name: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    if api_name == "news":
        base = {
            "id": "news-42",
            "datetime": "2026-07-13 09:00:00",
            "title": "headline",
        }
    else:
        base = {
            "id": "ann-42",
            "ts_code": "600000.SH",
            "ann_date": "20260713",
            "title": "announcement",
        }
    raw_v1 = json.dumps(
        {
            "content": "v1",
            "provider": "nested-forged",
            "event_type": "nested-forged",
        },
        sort_keys=True,
    )
    raw_v2 = json.dumps(
        {
            "content": "v2",
            "provider": "nested-forged-2",
            "event_type": "nested-forged-2",
        },
        sort_keys=True,
    )

    assert ingest_rows_to_sqlite(
        db_path, "market_events", api_name, [{**base, "raw_json": raw_v1}]
    ) == 1
    assert ingest_rows_to_sqlite(
        db_path, "market_events", api_name, [{**base, "raw_json": raw_v1}]
    ) == 0
    assert ingest_rows_to_sqlite(
        db_path, "market_events", api_name, [{**base, "raw_json": raw_v2}]
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT provider, event_type, event_id, revision "
            "FROM market_events ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    assert [row[:2] for row in rows] == [
        (f"tushare_{api_name}", api_name),
        (f"tushare_{api_name}", api_name),
    ]
    assert rows[0][2:] == (rows[1][2], 1)
    assert rows[1][3] == 2


def test_cb_issue_missing_business_key_rolls_back_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    with pytest.raises(ValueError, match="missing required business key ts_code"):
        ingest_rows_to_sqlite(
            db_path,
            "market_events",
            "cb_issue",
            [
                {"ts_code": "123456.SZ", "ann_date": "20260713"},
                {"ann_date": "20260713", "title": "invalid fallback"},
            ],
        )

    assert _count_rows(db_path, "market_events") == 0


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
