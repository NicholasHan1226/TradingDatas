from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import sqlite3
from zipfile import ZipFile

import pytest

from collectors.binance.collector import _RejectRedirects
from collectors.binance.oi_dump_collector import BinanceUsdmMetricsDumpCollector
import collectors.binance.oi_dump_collector as oi_dump_collector
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
from tools.run_binance_oi_dump_canary import metrics_dump_window, run
from tests.test_crypto_loopback_runtime import _ingest_result


_DUMP_DATE = "2026-08-13"
_DUMP_DAY = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _csv_lines(*, symbol: str = "BTCUSDT", day: datetime = _DUMP_DAY) -> list[str]:
    lines = [
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio"
    ]
    for index in range(288):
        stamp = (day + timedelta(minutes=5 * index)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(
            f"{stamp},{symbol},{1000 + index}.0,{100000000 + index}.0,"
            "1.9,1.5,1.8,2.1"
        )
    return lines


def _zip_payload(lines: list[str], *, member: str | None = None) -> bytes:
    buffer = io.BytesIO()
    name = member or f"BTCUSDT-metrics-{_DUMP_DATE}.csv"
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, "\n".join(lines) + "\n")
    return buffer.getvalue()


def _collector(payload: bytes) -> BinanceUsdmMetricsDumpCollector:
    collector = BinanceUsdmMetricsDumpCollector()
    collector._get = lambda path: payload
    return collector


def _collect(payload: bytes, **params: object) -> ProviderCallOutcome:
    request = {"symbol": "BTCUSDT", "date": _DUMP_DATE, **params}
    return _collector(payload).collect_outcome("metricsDump_btcusdt", request)


def test_oi_dump_collector_normalizes_a_complete_daily_metrics_zip() -> None:
    lines = _csv_lines()
    shuffled = [lines[0], *reversed(lines[1:])]
    outcome = _collect(_zip_payload(shuffled))
    assert outcome.state == "success"
    assert len(outcome.rows) == 288
    assert outcome.rows[0] == {
        "symbol": "BTCUSDT",
        "timestamp_ms": 1786579200000,
        "timestamp": "2026-08-13T00:00:00.000Z",
        "sum_open_interest": "1000.0",
        "sum_open_interest_value": "100000000.0",
    }
    assert outcome.rows[-1]["timestamp"] == "2026-08-13T23:55:00.000Z"
    timestamps = [row["timestamp_ms"] for row in outcome.rows]
    assert timestamps == sorted(timestamps)


def test_oi_dump_collector_rejects_a_corrupt_or_foreign_zip() -> None:
    assert _collect(b"not a zip").state == "failed"
    assert _collect(_zip_payload(_csv_lines(), member="evil.csv")).state == "failed"
    assert _collect(_zip_payload(_csv_lines(symbol="ETHUSDT"))).state == "failed"
    outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
        "metricsDump_btcusdt",
        {"symbol": "ETHUSDT", "date": _DUMP_DATE},
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_oi_dump_collector_rejects_header_and_grid_drift() -> None:
    lines = _csv_lines()
    assert _collect(_zip_payload(["wrong,header", *lines[1:]])).state == "failed"
    assert _collect(_zip_payload(lines[:-1])).state == "failed"
    duplicated = [*lines[:-1], lines[1]]
    assert _collect(_zip_payload(duplicated)).state == "failed"
    outside = [*lines[:-1], lines[-1].replace("23:55:00", "23:59:00")]
    assert _collect(_zip_payload(outside)).state == "failed"
    bad_cell = [*lines[:-1], lines[-1].replace("1.9,1.5,1.8,2.1", "nan,1.5,1.8,2.1")]
    assert _collect(_zip_payload(bad_cell)).state == "failed"


def test_oi_dump_collector_bounds_the_window_to_a_closed_utc_day() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for date in (today, "2999-01-01", "2026-8-13", "2026-08-13T00:00:00Z", ""):
        outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
            "metricsDump_btcusdt",
            {"symbol": "BTCUSDT", "date": date},
        )
        assert outcome.state == "failed"
        assert outcome.error_code == "transport_error"


def test_oi_dump_collector_rejects_api_outside_the_public_allowlist() -> None:
    outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
        "openInterestHist_btcusdt",
        {"symbol": "BTCUSDT", "date": _DUMP_DATE},
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_oi_dump_transport_is_credential_free_and_market_data_only() -> None:
    profile = provider_transport_profile("binance_usdm_dump")
    assert profile["credential_mode"] == "none"
    assert profile["market_data_only"] is True
    assert profile["endpoint"] == "https://data.binance.vision"
    assert profile["canonical_host"] == "data.binance.vision"
    assert profile["redirects_allowed"] is False
    assert profile["transport_service"] == "binance_usdm_public_metrics_dump"


def test_oi_dump_transport_rejects_redirects() -> None:
    assert any(
        isinstance(handler, _RejectRedirects)
        for handler in oi_dump_collector._PUBLIC_OPENER.handlers
    )
    with pytest.raises(OSError, match="redirect rejected"):
        _RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid/"
        )


def test_oi_dump_binding_feeds_the_frozen_open_interest_datasets() -> None:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    open_interest = registry.resolve("crypto.perp.binance.ethusdt.open_interest")
    fapi, dump = open_interest.provider_bindings
    assert fapi.provider == "binance_usdm"
    assert fapi.api_name == "openInterestHist_ethusdt"
    assert fapi.activation_state == "paused"
    assert dump.provider == "binance_usdm_dump"
    assert dump.api_name == "metricsDump_ethusdt"
    assert dump.entitlement_state == "active"
    assert dump.activation_state == "active"
    assert dump.adapter_version == "binance-usdm-metrics-dump.v1"
    assert dump.read_discriminator_value == "binance_usdm_dump_ethusdt_open_interest"
    assert dump.request_template == {
        "symbol": "ETHUSDT",
        "date": "${window.date}",
    }
    assert open_interest.primary_key == ("symbol", "timestamp")
    assert open_interest.point_in_time == "append_only"
    assert open_interest.read_model_adapter.row_key_strategy == "payload_hash"


def test_oi_dump_collection_is_idempotent_by_payload_identity(tmp_path) -> None:
    db_path = tmp_path / "facts.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)
        conn.commit()
    finally:
        conn.close()
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    payload = _zip_payload(_csv_lines())
    rows = BinanceUsdmMetricsDumpCollector._parse(
        payload, symbol="BTCUSDT", day=_DUMP_DAY
    )

    class _StubCollector:
        provider = "binance_usdm_dump"

        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            del api_name, params, fields
            return ProviderCallOutcome(
                state="success",
                rows=tuple(rows),
                provider_code=0,
                error_code=None,
                error_message=None,
                scan_budget=scan_budget,
            )

    window = {"date": _DUMP_DATE}
    first = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(),
        dataset_id="crypto.perp.binance.btcusdt.open_interest",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000001",
        started_at="2026-08-14T00:37:00Z",
    )
    second = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(),
        dataset_id="crypto.perp.binance.btcusdt.open_interest",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000002",
        started_at="2026-08-15T00:37:00Z",
    )
    assert first.status == "success"
    assert (first.counts.inserted, first.counts.unchanged) == (288, 0)
    assert second.status == "success"
    assert (second.counts.inserted, second.counts.unchanged) == (0, 288)
    assert first.receipt_ids != second.receipt_ids


def test_oi_dump_window_is_the_latest_closed_utc_day() -> None:
    window = metrics_dump_window(datetime(2026, 8, 16, 0, 37, tzinfo=timezone.utc))
    assert window == {"date": "2026-08-15"}
    with pytest.raises(ValueError, match="timezone-aware"):
        metrics_dump_window(datetime(2026, 8, 16, 0, 37))


def test_oi_dump_runner_plan_never_calls_provider_or_writes(tmp_path) -> None:
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "unused.lock",
        execute=False,
        now=datetime(2026, 8, 16, 0, 37, tzinfo=timezone.utc),
    )
    assert result["state"] == "planned"
    assert len(result["datasets"]) == 10
    assert set(result["windows"]) == {"open_interest"}
    assert result["windows"]["open_interest"] == {"date": "2026-08-15"}
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_oi_dump_runner_retries_one_provider_error_and_preserves_both_receipts(
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
                receipt_id="receipt:eth-oi-dump-first-failure",
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
        now=datetime(2026, 8, 16, 0, 37, tzinfo=timezone.utc),
    )

    assert result["state"] == "success"
    assert len(result["datasets"]) == 10
    eth_oi = next(
        item
        for item in result["datasets"]
        if item["dataset_id"].endswith("ethusdt.open_interest")
    )
    assert eth_oi["collection_kind"] == "open_interest"
    assert eth_oi["state"] == "success"
    assert eth_oi["retry_count"] == 1
    assert eth_oi["receipt_ids"][0] == "receipt:eth-oi-dump-first-failure"
    assert len(eth_oi["receipt_ids"]) == 2
    assert calls.count("crypto.perp.binance.ethusdt.open_interest") == 2
    assert all(item["window"] == {"date": "2026-08-15"} for item in result["datasets"])


def test_oi_dump_runner_surfaces_a_missing_dump_file_as_a_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")

    def collect(*args, **kwargs):
        del args, kwargs
        return _ingest_result(
            status="failed",
            receipt_id="receipt:missing-dump-file",
            errors=("provider_error",),
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    with pytest.raises(RuntimeError, match="collections failed"):
        run(
            db_path=tmp_path / "unused.sqlite",
            lock_path=tmp_path / "collect.lock",
            execute=True,
            now=datetime(2026, 8, 16, 0, 37, tzinfo=timezone.utc),
        )
