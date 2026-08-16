from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from collectors.binance.collector import _RejectRedirects
from collectors.binance.usdm_collector import BinanceUsdmPublicCollector
import collectors.binance.usdm_collector as usdm_collector
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from collectors.tushare.tushare_common import ProviderCallOutcome
from dataset_registry import (
    BINANCE_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)
from provider_transport import provider_transport_profile
from storage.schema import SCHEMA_SQL
from storage.schema_contract import PROVIDER_DATASET_ROWS_DDL
import tools.run_binance_spot_canary as spot_canary
from tools.run_binance_usdm_canary import (
    funding_rate_window,
    open_interest_window,
    run,
)
from tests.test_crypto_loopback_runtime import _ingest_result


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

_FUNDING_PAYLOAD = [
    {"symbol": "BTCUSDT", "fundingTime": 1785052800000, "fundingRate": "0.0001"},
    {"symbol": "BTCUSDT", "fundingTime": 1785081600000, "fundingRate": "-0.0002"},
]

_OPEN_INTEREST_PAYLOAD = [
    {
        "symbol": "BTCUSDT",
        "sumOpenInterest": "1000.0",
        "sumOpenInterestValue": "100000000.0",
        "timestamp": 1785225600000,
    },
]


def test_usdm_collector_normalizes_funding_rate_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = BinanceUsdmPublicCollector()
    monkeypatch.setattr(
        collector,
        "_get",
        lambda path, query: [
            *_FUNDING_PAYLOAD,
            {"symbol": "BTCUSDT", "fundingTime": 1785225600000, "fundingRate": "0.0"},
        ],
    )
    outcome = collector.collect_outcome(
        "fundingRate_btcusdt",
        {
            "symbol": "BTCUSDT",
            "start_time": "2026-07-26T08:00:00Z",
            "end_time": "2026-07-27T08:00:00Z",
        },
    )
    assert outcome.state == "success"
    assert outcome.rows == (
        {
            "symbol": "BTCUSDT",
            "funding_time_ms": 1785052800000,
            "funding_time": "2026-07-26T08:00:00.000Z",
            "funding_rate": "0.0001",
        },
        {
            "symbol": "BTCUSDT",
            "funding_time_ms": 1785081600000,
            "funding_time": "2026-07-26T16:00:00.000Z",
            "funding_rate": "-0.0002",
        },
    )


def test_usdm_collector_rejects_funding_rate_shape_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = BinanceUsdmPublicCollector()
    monkeypatch.setattr(
        collector,
        "_get",
        lambda path, query: [
            {
                "symbol": "BTCUSDT",
                "fundingTime": 1785052800000,
                "fundingRate": "0.0001",
                "markPrice": "1.0",
            }
        ],
    )
    outcome = collector.collect_outcome(
        "fundingRate_btcusdt",
        {
            "symbol": "BTCUSDT",
            "start_time": "2026-07-26T08:00:00Z",
            "end_time": "2026-07-27T08:00:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_collector_rejects_funding_rate_symbol_mismatch() -> None:
    outcome = BinanceUsdmPublicCollector().collect_outcome(
        "fundingRate_btcusdt",
        {
            "symbol": "ETHUSDT",
            "start_time": "2026-07-26T08:00:00Z",
            "end_time": "2026-07-27T08:00:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_collector_bounds_one_funding_rate_request_to_thirty_days() -> None:
    outcome = BinanceUsdmPublicCollector().collect_outcome(
        "fundingRate_btcusdt",
        {
            "symbol": "BTCUSDT",
            "start_time": "2026-06-01T00:00:00Z",
            "end_time": "2026-07-28T00:00:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_collector_normalizes_open_interest_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = BinanceUsdmPublicCollector()
    monkeypatch.setattr(collector, "_get", lambda path, query: _OPEN_INTEREST_PAYLOAD)
    outcome = collector.collect_outcome(
        "openInterestHist_btcusdt",
        {
            "symbol": "BTCUSDT",
            "period": "5m",
            "start_time": "2026-07-28T08:00:00Z",
            "end_time": "2026-07-28T08:05:00Z",
        },
    )
    assert outcome.state == "success"
    assert outcome.rows == (
        {
            "symbol": "BTCUSDT",
            "timestamp_ms": 1785225600000,
            "timestamp": "2026-07-28T08:00:00.000Z",
            "sum_open_interest": "1000.0",
            "sum_open_interest_value": "100000000.0",
        },
    )


def test_usdm_collector_rejects_open_interest_period_mismatch() -> None:
    outcome = BinanceUsdmPublicCollector().collect_outcome(
        "openInterestHist_btcusdt",
        {
            "symbol": "BTCUSDT",
            "period": "15m",
            "start_time": "2026-07-28T08:00:00Z",
            "end_time": "2026-07-28T08:05:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_collector_bounds_one_open_interest_request_to_one_day() -> None:
    outcome = BinanceUsdmPublicCollector().collect_outcome(
        "openInterestHist_btcusdt",
        {
            "symbol": "BTCUSDT",
            "period": "5m",
            "start_time": "2026-07-26T08:00:00Z",
            "end_time": "2026-07-28T08:00:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_collector_rejects_api_outside_the_public_allowlist() -> None:
    outcome = BinanceUsdmPublicCollector().collect_outcome(
        "account_btcusdt",
        {"symbol": "BTCUSDT"},
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_usdm_transport_is_credential_free_and_market_data_only() -> None:
    profile = provider_transport_profile("binance_usdm")
    assert profile["credential_mode"] == "none"
    assert profile["market_data_only"] is True
    assert profile["endpoint"] == "https://fapi.binance.com"
    assert profile["canonical_host"] == "fapi.binance.com"
    assert profile["redirects_allowed"] is False
    assert profile["transport_service"] == "binance_usdm_public_market_data"


def test_usdm_transport_rejects_redirects() -> None:
    assert any(
        isinstance(handler, _RejectRedirects)
        for handler in usdm_collector._PUBLIC_OPENER.handlers
    )
    with pytest.raises(OSError, match="redirect rejected"):
        _RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid/"
        )


def test_usdm_registry_freezes_ten_symbol_funding_and_open_interest_cohorts() -> None:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    assert [item.dataset_id for item in registry.datasets[30:]] == [
        *(f"crypto.perp.binance.{symbol.lower()}.funding_rate" for symbol in SYMBOLS),
        *(f"crypto.perp.binance.{symbol.lower()}.open_interest" for symbol in SYMBOLS),
    ]
    funding = registry.resolve("crypto.perp.binance.btcusdt.funding_rate")
    assert funding.primary_key == ("symbol", "funding_time")
    assert funding.point_in_time == "append_only"
    assert funding.read_model_adapter.row_key_strategy == "payload_hash"
    assert funding.as_of_field == "funding_time"
    assert funding.range_field == "funding_time"
    assert funding.schema_major == 1
    binding = funding.provider_bindings[0]
    assert binding.provider == "binance_usdm"
    assert binding.api_name == "fundingRate_btcusdt"
    assert binding.request_template == {
        "symbol": "BTCUSDT",
        "start_time": "${window.start_time}",
        "end_time": "${window.end_time}",
    }
    open_interest = registry.resolve("crypto.perp.binance.ethusdt.open_interest")
    assert open_interest.primary_key == ("symbol", "timestamp")
    assert open_interest.point_in_time == "append_only"
    fapi_binding, dump_binding = open_interest.provider_bindings
    assert fapi_binding.provider == "binance_usdm"
    assert fapi_binding.api_name == "openInterestHist_ethusdt"
    assert fapi_binding.activation_state == "paused"
    assert fapi_binding.request_template["period"] == "5m"
    assert dump_binding.provider == "binance_usdm_dump"
    assert dump_binding.api_name == "metricsDump_ethusdt"
    assert dump_binding.activation_state == "active"
    assert dump_binding.request_template == {
        "symbol": "ETHUSDT",
        "date": "${window.date}",
    }


def test_usdm_funding_rate_collection_is_idempotent_by_payload_identity(
    tmp_path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)
        conn.commit()
    finally:
        conn.close()
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    rows = tuple(
        {
            "symbol": "BTCUSDT",
            "funding_time_ms": funding_time_ms,
            "funding_time": funding_time,
            "funding_rate": "0.0001",
        }
        for funding_time_ms, funding_time in (
            (1785052800000, "2026-07-26T08:00:00.000Z"),
            (1785081600000, "2026-07-26T16:00:00.000Z"),
        )
    )

    class _StubCollector:
        provider = "binance_usdm"

        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            del api_name, params, fields
            return ProviderCallOutcome(
                state="success",
                rows=rows,
                provider_code=0,
                error_code=None,
                error_message=None,
                scan_budget=scan_budget,
            )

    window = {
        "start_time": "2026-07-26T08:00:00Z",
        "end_time": "2026-07-28T08:00:00Z",
    }
    first = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(),
        dataset_id="crypto.perp.binance.btcusdt.funding_rate",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-07-28T08:05:00Z",
    )
    second = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(),
        dataset_id="crypto.perp.binance.btcusdt.funding_rate",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000002",
        started_at="2026-07-28T08:10:00Z",
    )
    assert first.status == "success"
    assert (first.counts.inserted, first.counts.unchanged) == (2, 0)
    assert second.status == "success"
    assert (second.counts.inserted, second.counts.unchanged) == (0, 2)
    assert first.receipt_ids != second.receipt_ids


def test_usdm_funding_rate_window_tracks_realized_eight_hour_boundaries() -> None:
    window = funding_rate_window(datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc))
    assert window == {
        "start_time": "2026-07-26T08:00:00Z",
        "end_time": "2026-07-28T08:00:00Z",
    }


def test_usdm_open_interest_window_uses_two_closed_adjacent_boundaries() -> None:
    window = open_interest_window(datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc))
    assert window == {
        "start_time": "2026-07-28T09:35:00Z",
        "end_time": "2026-07-28T09:40:00Z",
    }


def test_usdm_runner_plan_never_calls_provider_or_writes(tmp_path) -> None:
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "unused.lock",
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
    )
    assert result["state"] == "planned"
    assert len(result["datasets"]) == 20
    assert set(result["windows"]) == {"funding_rate", "open_interest"}
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_usdm_runner_retries_one_provider_error_and_preserves_both_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    calls: list[str] = []

    def collect(*args, **kwargs):
        del args
        dataset_id = kwargs["dataset_id"]
        calls.append(dataset_id)
        if (
            dataset_id.endswith("ethusdt.open_interest")
            and calls.count(dataset_id) == 1
        ):
            return _ingest_result(
                status="failed",
                receipt_id="receipt:eth-oi-first-failure",
                errors=("provider_error",),
            )
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{dataset_id}:{len(calls)}",
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=datetime(2026, 8, 2, 12, 10, tzinfo=timezone.utc),
    )

    assert result["state"] == "success"
    assert len(result["datasets"]) == 20
    eth_oi = next(
        item
        for item in result["datasets"]
        if item["dataset_id"].endswith("ethusdt.open_interest")
    )
    assert eth_oi["collection_kind"] == "open_interest"
    assert eth_oi["state"] == "success"
    assert eth_oi["retry_count"] == 1
    assert eth_oi["receipt_ids"][0] == "receipt:eth-oi-first-failure"
    assert len(eth_oi["receipt_ids"]) == 2
    assert calls.count("crypto.perp.binance.ethusdt.open_interest") == 2
