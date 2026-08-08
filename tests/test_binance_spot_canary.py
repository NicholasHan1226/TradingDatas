from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from types import MappingProxyType

import pytest

from collectors.binance.collector import BinanceSpotPublicCollector, _RejectRedirects
from dataset_registry import (
    BINANCE_SPOT_CANARY_MODE,
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
    runtime_dataset_registry_path,
)
from provider_transport import provider_transport_profile
from query_contract import QueryExecutionOptions, QueryRequest
from query_service import (
    _base_predicates,
    _prepare_query,
    _validate_filter_clause,
    _where_clause,
)
from tools.compile_crypto_binance_spot_registry import (
    DEFAULT_REGISTRY,
    DEFAULT_UNIVERSE,
    compile_registry,
)


SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "TRXUSDT",
    "LINKUSDT",
    "AVAXUSDT",
)


def test_canary_registry_freezes_ten_symbols_and_current_snapshot_sets() -> None:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    assert len(registry.datasets) == 30
    assert [item.dataset_id for item in registry.datasets] == [
        *(f"crypto.spot.binance.{symbol.lower()}.5m" for symbol in SYMBOLS),
        *(f"crypto.spot.binance.{symbol.lower()}.rules" for symbol in SYMBOLS),
        *(f"crypto.spot.binance.{symbol.lower()}.book_ticker" for symbol in SYMBOLS),
    ]
    bar = registry.resolve("crypto.spot.binance.btcusdt.5m")
    assert bar.primary_key == ("symbol", "open_time")
    assert bar.as_of_field == "close_time"
    assert bar.timezone == "UTC"
    assert bar.freshness_sla_seconds == 600
    book_ticker = registry.resolve("crypto.spot.binance.btcusdt.book_ticker")
    assert book_ticker.primary_key == ("symbol",)
    assert book_ticker.point_in_time == "current_snapshot"
    assert book_ticker.as_of_field is None
    assert book_ticker.backfill_policy == "disabled"


def test_crypto_registry_compiler_is_deterministic_and_matches_checked_in_bytes() -> (
    None
):
    first = compile_registry(
        universe_path=DEFAULT_UNIVERSE,
        registry_path=DEFAULT_REGISTRY,
    )
    second = compile_registry(
        universe_path=DEFAULT_UNIVERSE,
        registry_path=DEFAULT_REGISTRY,
    )
    assert first == second == DEFAULT_REGISTRY.read_bytes()


def test_canary_mode_selects_only_the_pinned_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", BINANCE_SPOT_CANARY_MODE)
    monkeypatch.delenv("TRADINGDATAS_REGISTRY_PATH", raising=False)
    assert runtime_dataset_registry_path() == BINANCE_SPOT_CANARY_REGISTRY_PATH
    monkeypatch.setenv(
        "TRADINGDATAS_REGISTRY_PATH", str(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    )
    with pytest.raises(ValueError, match="does not accept a path override"):
        runtime_dataset_registry_path()


def test_binance_collector_rejects_registry_symbol_mismatch() -> None:
    outcome = BinanceSpotPublicCollector().collect_outcome(
        "klines_btcusdt",
        {
            "symbol": "DOGEUSDT",
            "interval": "5m",
            "start_open_time": "2026-07-28T00:00:00Z",
            "end_open_time": "2026-07-28T00:05:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_binance_collector_accepts_a_frozen_non_canary_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = BinanceSpotPublicCollector()
    monkeypatch.setattr(
        collector,
        "_get",
        lambda path, query: [
            [
                1785225600000,
                "1.0",
                "1.1",
                "0.9",
                "1.05",
                "100",
                1785225899999,
                "105",
                10,
                "50",
                "52.5",
                "0",
            ]
        ],
    )
    outcome = collector.collect_outcome(
        "klines_solusdt",
        {
            "symbol": "SOLUSDT",
            "interval": "5m",
            "start_open_time": "2026-07-28T08:00:00Z",
            "end_open_time": "2026-07-28T08:00:00Z",
        },
    )
    assert outcome.state == "success"
    assert outcome.rows[0]["symbol"] == "SOLUSDT"


def test_binance_collector_normalizes_book_ticker_without_a_provider_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = BinanceSpotPublicCollector()
    monkeypatch.setattr(
        collector,
        "_get",
        lambda path, query: {
            "symbol": "SOLUSDT",
            "bidPrice": "1.0",
            "bidQty": "2.0",
            "askPrice": "1.1",
            "askQty": "3.0",
        },
    )
    outcome = collector.collect_outcome("bookTicker_solusdt", {"symbol": "SOLUSDT"})
    assert outcome.state == "success"
    assert outcome.rows == (
        {
            "symbol": "SOLUSDT",
            "bid_price": "1.0",
            "bid_qty": "2.0",
            "ask_price": "1.1",
            "ask_qty": "3.0",
        },
    )


def test_binance_collector_rejects_book_ticker_symbol_mismatch() -> None:
    outcome = BinanceSpotPublicCollector().collect_outcome(
        "bookTicker_btcusdt", {"symbol": "ETHUSDT"}
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_binance_transport_is_credential_free_and_market_data_only() -> None:
    profile = provider_transport_profile("binance_spot")
    assert profile["credential_mode"] == "none"
    assert profile["market_data_only"] is True
    assert profile["transport_service"] == "binance_public_market_data"


def test_binance_transport_rejects_redirects() -> None:
    with pytest.raises(OSError, match="redirect rejected"):
        _RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid/"
        )


def test_rfc3339_open_time_between_normalizes_to_provider_row_order() -> None:
    bar = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH).resolve(
        "crypto.spot.binance.btcusdt.5m"
    )
    open_time = next(field for field in bar.fields if field.name == "open_time")
    operator, values = _validate_filter_clause(
        open_time,
        MappingProxyType(
            {
                "between": (
                    "2026-07-28T08:40:00+00:00",
                    "2026-07-28T09:40:00+00:00",
                )
            }
        ),
        dataset=bar,
    )
    assert operator == "between"
    assert values == ("2026-07-28T08:40:00.000Z", "2026-07-28T09:40:00.000Z")


def test_partition_field_open_time_between_binds_provider_row_order() -> None:
    """Lock the partition-index range path and its boundary format contract.

    The 5m bar datasets declare ``partition_field: open_time``; a between
    filter must therefore render against the persisted ``partition_value``
    column with canonical RFC3339-millisecond operands.  A row whose
    partition_value uses any other spelling (for example a backfill written as
    ``+00:00``) compares outside the exact window boundary and is silently
    excluded, which is the failure mode that stalled the crypto lane in the
    2026-08-08 partition-field experiment.
    """

    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    bar = registry.resolve("crypto.spot.binance.btcusdt.5m")
    assert bar.partition_field == "open_time"

    request = QueryRequest(
        dataset_id=bar.dataset_id,
        schema_major=bar.schema_major,
        fields=("symbol", "open_time"),
        filters=MappingProxyType(
            {
                "symbol": MappingProxyType({"eq": "BTCUSDT"}),
                "open_time": MappingProxyType(
                    {
                        "between": (
                            "2026-07-28T08:40:00+00:00",
                            "2026-07-28T08:45:00+00:00",
                        )
                    }
                ),
            }
        ),
        as_of="2026-07-28T08:49:59.999+00:00",
        order=("symbol:asc", "open_time:asc"),
        limit=10,
        cursor=None,
    )
    prepared = _prepare_query(
        request,
        QueryExecutionOptions(),
        bar,
        registry,
        now=datetime(2026, 7, 28, 8, 50, tzinfo=timezone.utc),
    )
    predicates, params = _base_predicates(request, QueryExecutionOptions(), bar, prepared)
    rendered = _where_clause(predicates)
    assert '"partition_value" BETWEEN ? AND ?' in rendered
    assert params[:3] == [bar.dataset_id, "binance_spot", 1]
    assert params[3:5] == ["2026-07-28T08:40:00.000Z", "2026-07-28T08:45:00.000Z"]

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE provider_dataset_rows ("
        "dataset_id TEXT NOT NULL, provider TEXT NOT NULL, "
        "schema_major INTEGER NOT NULL, ingested_schema_version TEXT NOT NULL, "
        "row_key TEXT NOT NULL, observed_at TEXT, partition_value TEXT, "
        "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "quality_state TEXT NOT NULL, quality_issues_json TEXT NOT NULL, "
        "collected_at TEXT NOT NULL, receipt_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, "
        "PRIMARY KEY(dataset_id, provider, schema_major, row_key)"
        ") WITHOUT ROWID"
    )
    for row_key, open_time, partition_value in (
        ("canonical", "2026-07-28T08:40:00.000Z", "2026-07-28T08:40:00.000Z"),
        ("noncanonical", "2026-07-28T08:40:00.000Z", "2026-07-28T08:40:00+00:00"),
    ):
        payload = json.dumps(
            {
                "symbol": "BTCUSDT",
                "open_time": open_time,
                "close_time": "2026-07-28T08:44:59.999Z",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            "INSERT INTO provider_dataset_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (
                bar.dataset_id,
                "binance_spot",
                1,
                "1.0.0",
                row_key,
                open_time,
                partition_value,
                payload,
                "a" * 64,
                "valid",
                "[]",
                "2026-07-28T08:50:00Z",
                f"receipt:{row_key}",
            ),
        )
    conn.commit()
    matched = conn.execute(
        f"SELECT row_key FROM main.provider_dataset_rows{rendered}",
        params,
    ).fetchall()
    assert [row[0] for row in matched] == ["canonical"]


def _bar_request(
    *,
    filters: MappingProxyType[str, MappingProxyType[str, object]],
    as_of: str | None,
) -> tuple[QueryRequest, object, object]:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    bar = registry.resolve("crypto.spot.binance.btcusdt.5m")
    request = QueryRequest(
        dataset_id=bar.dataset_id,
        schema_major=bar.schema_major,
        fields=(),
        filters=filters,
        as_of=as_of,
        order=None,
        limit=13,
        cursor=None,
    )
    return request, bar, registry


def test_rfc3339_open_time_gte_matches_catalog_contract() -> None:
    request, bar, registry = _bar_request(
        filters=MappingProxyType(
            {"open_time": MappingProxyType({"gte": "2026-07-28T08:40:00+00:00"})}
        ),
        as_of="2026-07-28T09:44:59.999+00:00",
    )

    prepared = _prepare_query(
        request,
        QueryExecutionOptions(),
        bar,
        registry,
        now=datetime(2026, 7, 28, 9, 45, tzinfo=timezone.utc),
    )

    assert prepared.empty_interval is False


def test_rfc3339_as_of_cutoff_uses_provider_row_timestamp_encoding() -> None:
    request, bar, registry = _bar_request(
        filters=MappingProxyType(
            {
                "open_time": MappingProxyType(
                    {
                        "between": (
                            "2026-07-28T08:40:00+00:00",
                            "2026-07-28T09:40:00+00:00",
                        )
                    }
                )
            }
        ),
        as_of="2026-07-28T09:44:59.999+00:00",
    )
    prepared = _prepare_query(
        request,
        QueryExecutionOptions(),
        bar,
        registry,
        now=datetime(2026, 7, 28, 9, 45, tzinfo=timezone.utc),
    )

    _, params = _base_predicates(
        request,
        QueryExecutionOptions(),
        bar,
        prepared,
    )

    assert params[-1] == "2026-07-28T09:44:59.999Z"
