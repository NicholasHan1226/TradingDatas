from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import tools.run_binance_spot_canary as canary
from dataset_registry import BINANCE_CANARY_REGISTRY_PATH, load_dataset_registry
from storage.ingest_receipts import IngestCounts, IngestResult
from tools.run_binance_spot_canary import latest_closed_window, run


def _ingest_result(*, status: str, receipt_id: str) -> IngestResult:
    succeeded = status == "success"
    return IngestResult(
        status=status,
        counts=IngestCounts(
            returned=1 if succeeded else 0,
            validated=1 if succeeded else 0,
            inserted=1 if succeeded else 0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1 if succeeded else 0,
            count_semantics="exact_row_outcomes"
            if succeeded
            else "terminal_no_data_transaction",
        ),
        receipt_ids=(receipt_id,),
        errors=(),
    )


def test_closed_bar_workers_and_finish_budget_stay_bounded() -> None:
    assert canary._DATASET_WORKER_COUNT == 4
    assert canary._CLOSED_BAR_FINISH_BUDGET_SECONDS == 270.0
    assert (
        canary._bar_dataset_workers(
            collect_rules=False,
            collect_book_ticker=False,
            backfill_days=None,
        )
        == 4
    )
    assert (
        canary._bar_dataset_workers(
            collect_rules=True,
            collect_book_ticker=False,
            backfill_days=None,
        )
        == 1
    )
    assert (
        canary._bar_dataset_workers(
            collect_rules=False,
            collect_book_ticker=True,
            backfill_days=None,
        )
        == 1
    )
    assert (
        canary._bar_dataset_workers(
            collect_rules=False,
            collect_book_ticker=False,
            backfill_days=180,
        )
        == 1
    )
    source = Path(canary.__file__).read_text(encoding="utf-8")
    assert "_DATASET_WORKER_COUNT = 4" in source
    assert "_CLOSED_BAR_FINISH_BUDGET_SECONDS = 270.0" in source


def test_closed_bar_plan_advertises_four_workers() -> None:
    planned = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
    )
    assert planned["dataset_workers"] == 4
    assert planned["windows"] == [latest_closed_window(datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc))]


def test_closed_bar_workers_overlap_provider_calls_under_one_lock(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    in_flight = 0
    max_in_flight = 0
    persist_in_flight = 0
    max_persist = 0
    guard = threading.Lock()
    now = datetime(2026, 9, 5, 9, 5, 10, tzinfo=timezone.utc)
    expected = latest_closed_window(now)
    finish_times: list[float] = []

    def collect(*args, **kwargs):
        del args
        nonlocal in_flight, max_in_flight, persist_in_flight, max_persist
        assert kwargs["request_window"] == expected
        assert kwargs["persist_lock"] is not None
        with guard:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with guard:
            in_flight -= 1
        with kwargs["persist_lock"]:
            with guard:
                persist_in_flight += 1
                max_persist = max(max_persist, persist_in_flight)
            time.sleep(0.005)
            with guard:
                persist_in_flight -= 1
        finish_times.append(time.monotonic())
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{kwargs['dataset_id']}",
        )

    monkeypatch.setattr(canary, "collect_provider_native_dataset", collect)
    started = time.monotonic()
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
    )
    elapsed = time.monotonic() - started
    registry_ids = list(
        canary._bar_datasets(load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH))
    )

    assert result["state"] == "success"
    assert result["dataset_workers"] == 4
    assert [item["dataset_id"] for item in result["datasets"]] == registry_ids
    assert all(item["window"] == expected for item in result["datasets"])
    assert 2 <= max_in_flight <= 4
    assert max_persist == 1
    assert elapsed < canary._CLOSED_BAR_FINISH_BUDGET_SECONDS
    assert elapsed < 40 * 0.05 * 0.7
    assert max(finish_times) - min(finish_times) < canary._CLOSED_BAR_FINISH_BUDGET_SECONDS
