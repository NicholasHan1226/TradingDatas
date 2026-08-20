from __future__ import annotations

from datetime import datetime, timezone
import io
import sqlite3
from zipfile import ZipFile

import pytest


pytestmark = pytest.mark.slow

from collectors.binance.oi_dump_collector import BinanceUsdmMetricsDumpCollector
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from collectors.tushare.tushare_common import ProviderCallOutcome
from dataset_registry import (
    BINANCE_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)
from storage.schema import SCHEMA_SQL
from storage.schema_contract import PROVIDER_DATASET_ROWS_DDL
import tools.run_binance_spot_canary as spot_canary
import tools.run_binance_oi_dump_canary as oi_dump_canary
from tools.run_binance_oi_dump_canary import backfill_windows, lookback_days
from tools.run_binance_premium_dump_canary import run
from tests.test_crypto_loopback_runtime import _ingest_result


_DUMP_DATE = "2026-08-13"
_DUMP_DAY = datetime(2026, 8, 13, tzinfo=timezone.utc)
_OPEN_BASE_MS = 1786579200000
_REAL_PREMIUM_PROBE = BinanceUsdmMetricsDumpCollector.probe_premium_index_published


@pytest.fixture(autouse=True)
def _published_probe(monkeypatch: pytest.MonkeyPatch):
    """Default the publication probe to published; specific tests override."""

    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "probe_premium_index_published",
        staticmethod(lambda *, symbol, day: True),
    )
    # Stub the shared backfill boundary yield; production-timing behavior is
    # covered by the OI runner tests.
    import tools.run_binance_oi_dump_canary as oi_dump_canary

    monkeypatch.setattr(
        oi_dump_canary, "_yield_past_next_collection_boundary", lambda: None
    )


def _csv_lines(*, day: datetime = _DUMP_DAY) -> list[str]:
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore"
    ]
    day_start_ms = int(day.timestamp() * 1000)
    for index in range(288):
        open_ms = day_start_ms + 300_000 * index
        lines.append(
            f"{open_ms},-0.0001{index % 10},-0.0000{index % 10},"
            f"-0.0002{index % 10},-0.0001{index % 10},0,"
            f"{open_ms + 299_999},0,60,0,0,0"
        )
    return lines


def _zip_payload(lines: list[str], *, member: str | None = None) -> bytes:
    buffer = io.BytesIO()
    name = member or f"BTCUSDT-5m-{_DUMP_DATE}.csv"
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, "\n".join(lines) + "\n")
    return buffer.getvalue()


def _collector(payload: bytes) -> BinanceUsdmMetricsDumpCollector:
    collector = BinanceUsdmMetricsDumpCollector()
    collector._get = lambda path: payload
    return collector


def _collect(payload: bytes, **params: object) -> ProviderCallOutcome:
    request = {"symbol": "BTCUSDT", "date": _DUMP_DATE, **params}
    return _collector(payload).collect_outcome("premiumIndexKlinesDump_btcusdt", request)


def test_premium_dump_collector_normalizes_a_complete_daily_klines_zip() -> None:
    lines = _csv_lines()
    shuffled = [lines[0], *reversed(lines[1:])]
    outcome = _collect(_zip_payload(shuffled))
    assert outcome.state == "success"
    assert len(outcome.rows) == 288
    assert outcome.rows[0] == {
        "symbol": "BTCUSDT",
        "open_time_ms": 1786579200000,
        "open_time": "2026-08-13T00:00:00.000Z",
        "close_time_ms": 1786579499999,
        "close_time": "2026-08-13T00:04:59.999Z",
        "open": "-0.00010",
        "high": "-0.00000",
        "low": "-0.00020",
        "close": "-0.00010",
    }
    assert outcome.rows[-1]["open_time"] == "2026-08-13T23:55:00.000Z"
    timestamps = [row["open_time_ms"] for row in outcome.rows]
    assert timestamps == sorted(timestamps)


def test_premium_dump_collector_rejects_a_corrupt_or_foreign_zip() -> None:
    assert _collect(b"not a zip").state == "failed"
    assert _collect(_zip_payload(_csv_lines(), member="evil.csv")).state == "failed"
    outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
        "premiumIndexKlinesDump_btcusdt",
        {"symbol": "ETHUSDT", "date": _DUMP_DATE},
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_premium_dump_collector_rejects_header_and_grid_drift() -> None:
    lines = _csv_lines()
    assert _collect(_zip_payload(["wrong,header", *lines[1:]])).state == "failed"
    assert _collect(_zip_payload(lines[:-1])).state == "failed"
    duplicated = [*lines[:-1], lines[1]]
    assert _collect(_zip_payload(duplicated)).state == "failed"
    outside = lines[-1].split(",")
    outside[0] = str(_OPEN_BASE_MS + 300_000 * 288)
    outside[6] = str(int(outside[0]) + 299_999)
    assert _collect(_zip_payload([*lines[:-1], ",".join(outside)])).state == "failed"
    bad_close = lines[-1].split(",")
    bad_close[6] = str(int(bad_close[0]) + 300_000)
    assert _collect(_zip_payload([*lines[:-1], ",".join(bad_close)])).state == "failed"
    bad_cell = [*lines[:-1], lines[-1].replace("-0.00027", "nan")]
    assert _collect(_zip_payload(bad_cell)).state == "failed"


def test_premium_dump_collector_bounds_the_window_to_a_closed_utc_day() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for date in (today, "2999-01-01", "2026-8-13", "2026-08-13T00:00:00Z", ""):
        outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
            "premiumIndexKlinesDump_btcusdt",
            {"symbol": "BTCUSDT", "date": date},
        )
        assert outcome.state == "failed"
        assert outcome.error_code == "transport_error"


def test_premium_dump_collector_rejects_api_outside_the_public_allowlist() -> None:
    outcome = BinanceUsdmMetricsDumpCollector().collect_outcome(
        "premiumIndex_btcusdt",
        {"symbol": "BTCUSDT", "date": _DUMP_DATE},
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_premium_dump_probe_targets_the_interval_scoped_dump_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []
    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "_probe",
        staticmethod(lambda path: paths.append(path) or True),
    )
    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "probe_premium_index_published",
        staticmethod(_REAL_PREMIUM_PROBE),
    )
    assert BinanceUsdmMetricsDumpCollector.probe_premium_index_published(
        symbol="BTCUSDT", day=_DUMP_DATE
    )
    assert paths == [
        "/data/futures/um/daily/premiumIndexKlines/BTCUSDT/5m/"
        "BTCUSDT-5m-2026-08-13.zip"
    ]


def test_premium_dump_binding_feeds_the_frozen_premium_index_datasets() -> None:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    premium = registry.resolve("crypto.perp.binance.ethusdt.premium_index")
    assert premium.market == "CRYPTO_PERP"
    assert premium.cadence_class == "postclose_daily"
    assert premium.freshness_sla_seconds == 129600
    (dump,) = premium.provider_bindings
    assert dump.provider == "binance_usdm_dump"
    assert dump.api_name == "premiumIndexKlinesDump_ethusdt"
    assert dump.entitlement_state == "active"
    assert dump.activation_state == "active"
    assert dump.adapter_version == "binance-usdm-premium-index-dump.v1"
    assert dump.read_discriminator_value == "binance_usdm_dump_ethusdt_premium_index"
    assert dump.request_template == {
        "symbol": "ETHUSDT",
        "date": "${window.date}",
    }
    assert premium.primary_key == ("symbol", "open_time")
    assert premium.as_of_field == "close_time"
    assert premium.range_field == "open_time"
    assert premium.point_in_time == "append_only"
    assert premium.read_model_adapter.row_key_strategy == "payload_hash"


def test_premium_dump_collection_is_idempotent_by_payload_identity(tmp_path) -> None:
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
    rows = BinanceUsdmMetricsDumpCollector._parse_premium(
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
        dataset_id="crypto.perp.binance.btcusdt.premium_index",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000101",
        started_at="2026-08-14T00:53:00Z",
    )
    second = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(),
        dataset_id="crypto.perp.binance.btcusdt.premium_index",
        request_window=window,
        attempt_id="018f47de-0000-7000-8000-000000000102",
        started_at="2026-08-15T00:53:00Z",
    )
    assert first.status == "success"
    assert (first.counts.inserted, first.counts.unchanged) == (288, 0)
    assert second.status == "success"
    assert (second.counts.inserted, second.counts.unchanged) == (0, 288)
    assert first.receipt_ids != second.receipt_ids


def test_premium_dump_runner_plan_never_calls_provider_or_writes(tmp_path) -> None:
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "unused.lock",
        execute=False,
        now=datetime(2026, 8, 16, 0, 53, tzinfo=timezone.utc),
    )
    assert result["state"] == "planned"
    assert len(result["datasets"]) == 40
    assert set(result["windows"]) == {"premium_index"}
    assert result["windows"]["premium_index"] == {"date": "2026-08-15"}
    assert result["lookback_days"] == 7
    assert result["lookback_start"] == "2026-08-09"
    assert result["backfill_days"] is None
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_premium_dump_runner_backfill_plan_never_calls_provider_or_writes(
    tmp_path,
) -> None:
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "unused.lock",
        execute=False,
        now=datetime(2026, 8, 16, 0, 53, tzinfo=timezone.utc),
        backfill_days=198,
    )
    assert result["state"] == "planned"
    assert len(result["datasets"]) == 40
    assert result["backfill_days"] == 198
    assert result["window_count"] == 198
    assert result["windows"] == {
        "first_day": "2026-01-30",
        "last_day": "2026-08-15",
    }
    assert result["lookback_days"] is None
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_premium_dump_runner_retries_one_provider_error_and_preserves_both_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    monkeypatch.setattr(
        oi_dump_canary, "_ingested_days", lambda *args, **kwargs: frozenset()
    )
    calls: list[str] = []

    def collect(*args, **kwargs):
        del args
        dataset_id = kwargs["dataset_id"]
        calls.append(dataset_id)
        if (
            dataset_id.endswith("ethusdt.premium_index")
            and calls.count(dataset_id) == 1
        ):
            return _ingest_result(
                status="failed",
                receipt_id="receipt:eth-premium-dump-first-failure",
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
        now=datetime(2026, 8, 16, 0, 53, tzinfo=timezone.utc),
    )

    assert result["state"] == "success"
    assert len(result["datasets"]) == 40
    eth = next(
        item
        for item in result["datasets"]
        if item["dataset_id"].endswith("ethusdt.premium_index")
    )
    assert eth["collection_kind"] == "premium_index"
    assert eth["state"] == "success"
    assert eth["retry_count"] == 1
    assert eth["receipt_ids"][0] == "receipt:eth-premium-dump-first-failure"
    assert len(eth["receipt_ids"]) == 2
    assert calls.count("crypto.perp.binance.ethusdt.premium_index") == 2
    assert all(item["window"] == {"date": "2026-08-15"} for item in result["datasets"])


def test_premium_dump_runner_treats_missing_dump_as_soft_gap_across_multiple_days(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    monkeypatch.setattr(
        oi_dump_canary, "_ingested_days", lambda *args, **kwargs: frozenset()
    )

    def collect(*args, **kwargs):
        del args, kwargs
        return _ingest_result(
            status="failed",
            receipt_id="receipt:missing-dump-file",
            errors=("provider_error",),
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=datetime(2026, 8, 16, 0, 53, tzinfo=timezone.utc),
    )

    assert result["state"] == "success"
    assert any(
        item["state"] == "pending_publication" for item in result["datasets"]
    )


def test_premium_dump_runner_falls_through_unpublished_newest_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    candidates = lookback_days(now)
    # Only the two newest days are missing for every symbol; the newest zip
    # is still unpublished while the older one is available.
    monkeypatch.setattr(
        oi_dump_canary,
        "_ingested_days",
        lambda db_path, registry, dataset_id: frozenset(candidates[2:]),
    )
    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "probe_premium_index_published",
        staticmethod(lambda *, symbol, day: day != candidates[0]),
    )
    calls: list[tuple[str, str]] = []

    def collect(*args, **kwargs):
        del args
        day = kwargs["request_window"]["date"]
        calls.append((kwargs["dataset_id"], day))
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:published:{day}",
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
    )

    assert result["state"] == "success"
    assert all(
        call[1] == candidates[1] for call in calls
    ), "unpublished days must be skipped without an ingest attempt"
    by_id: dict[str, list[dict[str, object]]] = {}
    for item in result["datasets"]:
        by_id.setdefault(item["dataset_id"], []).append(item)
    for entries in by_id.values():
        assert [item["state"] for item in entries] == ["success"]
        assert entries[0]["window"] == {"date": candidates[1]}


def test_premium_dump_runner_marks_single_newest_gap_pending_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    candidates = lookback_days(now)
    # Steady state: every lookback day except the newest is already ingested,
    # and the newest zip is not published yet.
    monkeypatch.setattr(
        oi_dump_canary,
        "_ingested_days",
        lambda db_path, registry, dataset_id: frozenset(candidates[1:]),
    )
    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "probe_premium_index_published",
        staticmethod(lambda *, symbol, day: False),
    )

    def collect(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("unpublished days must not be collected")

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
    )

    assert result["state"] == "success"
    assert {item["state"] for item in result["datasets"]} == {"pending_publication"}
    assert all(
        item["window"] == {"date": candidates[0]} and item["receipt_ids"] == []
        for item in result["datasets"]
    )


def test_premium_dump_runner_collects_only_the_newest_missing_day_per_symbol(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    candidates = lookback_days(now)
    ingested = {
        "crypto.perp.binance.btcusdt.premium_index": frozenset(candidates),
        "crypto.perp.binance.ethusdt.premium_index": frozenset(candidates[1:]),
    }
    monkeypatch.setattr(
        oi_dump_canary,
        "_ingested_days",
        lambda db_path, registry, dataset_id: ingested.get(
            dataset_id,
            frozenset(day for day in candidates if day != "2026-08-13"),
        ),
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def collect(*args, **kwargs):
        del args
        calls.append((kwargs["dataset_id"], kwargs["request_window"]))
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{kwargs['dataset_id']}:{len(calls)}",
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
    )

    assert result["state"] == "success"
    assert result["lookback_days"] == 7
    by_id = {item["dataset_id"]: item for item in result["datasets"]}
    btc = by_id["crypto.perp.binance.btcusdt.premium_index"]
    assert btc["state"] == "unchanged"
    assert btc["window"] is None
    assert btc["receipt_ids"] == []
    eth = by_id["crypto.perp.binance.ethusdt.premium_index"]
    assert eth["state"] == "success"
    assert eth["window"] == {"date": "2026-08-15"}
    others = [
        item
        for item in result["datasets"]
        if item["dataset_id"].endswith("solusdt.premium_index")
    ]
    assert others[0]["state"] == "success"
    assert others[0]["window"] == {"date": "2026-08-13"}
    assert not any(call[0].endswith("btcusdt.premium_index") for call in calls)
    assert all(
        call[1] == {"date": "2026-08-15"}
        for call in calls
        if call[0].endswith("ethusdt.premium_index")
    )


def test_premium_dump_ingested_days_come_from_validated_receipts(tmp_path) -> None:
    db_path = tmp_path / "facts.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(PROVIDER_DATASET_ROWS_DDL)
        conn.commit()
    finally:
        conn.close()
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    rows = BinanceUsdmMetricsDumpCollector._parse_premium(
        _zip_payload(_csv_lines()), symbol="BTCUSDT", day=_DUMP_DAY
    )

    class _StubCollector:
        provider = "binance_usdm_dump"

        def __init__(self, outcome_rows):
            self._rows = outcome_rows

        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            del api_name, params, fields
            if self._rows is None:
                return ProviderCallOutcome(
                    state="failed",
                    rows=(),
                    provider_code=None,
                    error_code="transport_error",
                    error_message="OSError",
                    scan_budget=scan_budget,
                )
            return ProviderCallOutcome(
                state="success",
                rows=tuple(self._rows),
                provider_code=0,
                error_code=None,
                error_message=None,
                scan_budget=scan_budget,
            )

    failed = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(None),
        dataset_id="crypto.perp.binance.btcusdt.premium_index",
        request_window={"date": "2026-08-12"},
        attempt_id="018f47de-0000-7000-8000-0000000001f0",
        started_at="2026-08-13T00:53:00Z",
    )
    assert failed.status == "failed"
    assert oi_dump_canary._ingested_days(
        db_path, registry, "crypto.perp.binance.btcusdt.premium_index"
    ) == frozenset()
    success = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=_StubCollector(rows),
        dataset_id="crypto.perp.binance.btcusdt.premium_index",
        request_window={"date": _DUMP_DATE},
        attempt_id="018f47de-0000-7000-8000-0000000001f1",
        started_at="2026-08-14T00:53:00Z",
    )
    assert success.status == "success"
    assert oi_dump_canary._ingested_days(
        db_path, registry, "crypto.perp.binance.btcusdt.premium_index"
    ) == frozenset({_DUMP_DATE})
    assert oi_dump_canary._ingested_days(
        db_path, registry, "crypto.perp.binance.ethusdt.premium_index"
    ) == frozenset()


def test_premium_dump_backfill_batches_per_day_and_releases_the_lock_between_days(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    days = backfill_windows(now, days=198)
    monkeypatch.setattr(
        oi_dump_canary, "_ingested_days", lambda *args, **kwargs: frozenset()
    )
    lock_events: list[str] = []
    real_blocking_lock = oi_dump_canary._blocking_lock
    real_release = oi_dump_canary._release

    def blocking_lock(path):
        lock_events.append("acquire")
        return real_blocking_lock(path)

    def release(lock) -> None:
        lock_events.append("release")
        real_release(lock)

    monkeypatch.setattr(oi_dump_canary, "_blocking_lock", blocking_lock)
    monkeypatch.setattr(oi_dump_canary, "_release", release)
    calls: list[tuple[str, dict[str, str]]] = []

    def collect(*args, **kwargs):
        del args
        calls.append((kwargs["dataset_id"], kwargs["request_window"]))
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{len(calls)}",
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
        backfill_days=198,
    )

    assert result["state"] == "success"
    assert result["window_count"] == 198
    assert result["collected_day_count"] == 198
    assert result["receipt_count"] == 7920
    assert len(calls) == 7920
    assert lock_events == ["acquire", "release"] * 198
    collected_days = {call[1]["date"] for call in calls}
    assert collected_days == set(days)
    per_day = {}
    for _, window in calls:
        per_day[window["date"]] = per_day.get(window["date"], 0) + 1
    assert set(per_day.values()) == {40}


def test_premium_dump_backfill_skips_already_ingested_days_without_locking(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    days = set(backfill_windows(now, days=198))
    monkeypatch.setattr(
        oi_dump_canary, "_ingested_days", lambda *args, **kwargs: frozenset(days)
    )
    monkeypatch.setattr(
        oi_dump_canary,
        "_blocking_lock",
        lambda path: pytest.fail("caught-up backfill must not take the lock"),
    )

    def collect(*args, **kwargs):
        del args, kwargs
        return pytest.fail("caught-up backfill must not call the provider")

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
        backfill_days=198,
    )

    assert result["state"] == "success"
    assert result["collected_day_count"] == 0
    assert result["receipt_count"] == 0


def test_premium_dump_backfill_skips_unpublished_days_without_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 8, 16, 3, 5, tzinfo=timezone.utc)
    days = backfill_windows(now, days=198)
    monkeypatch.setattr(
        oi_dump_canary, "_ingested_days", lambda *args, **kwargs: frozenset()
    )
    # Only the two newest days are published for every symbol (pre-listing
    # days and publication gaps simply have no zip).
    published = set(days[-2:])
    monkeypatch.setattr(
        BinanceUsdmMetricsDumpCollector,
        "probe_premium_index_published",
        staticmethod(lambda *, symbol, day: day in published),
    )
    calls: list[str] = []

    def collect(*args, **kwargs):
        del args
        day = kwargs["request_window"]["date"]
        assert day in published
        calls.append(day)
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{kwargs['dataset_id']}:{day}",
        )

    monkeypatch.setattr(spot_canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
        backfill_days=198,
    )

    assert result["state"] == "success"
    assert result["collected_day_count"] == 2
    assert result["unpublished_skip_count"] == (len(days) - 2) * 40
    assert result["failed_attempt_count"] == 0
    assert len(calls) == 80
