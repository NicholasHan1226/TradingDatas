#!/usr/bin/env python3
"""Collect Binance USDⓈ-M open interest from the public daily metrics dump.

This candidate runner has no account, order, key, Testnet, or fallback path.
It is the owner-approved degradation source while ``fapi.binance.com`` is
blocked at the SNI layer: it downloads one published daily ``metrics`` zip per
frozen symbol from ``https://data.binance.vision`` and feeds the same
``crypto.perp.binance.<symbol>.open_interest`` datasets.  It accepts no
provider, symbol, field, or registry path input.

Daily publication of the dump lags the UTC day close by hours, so a run never
assumes the latest closed day is published: within a bounded seven-day
lookback it collects, per symbol, the newest day that is published and not yet
in the store (derived from SQLite facts with validated success receipts, not
from run history).  A missing file is an honest failed run retried by the next
timer tick; because the gap stays visible in the store, a late publication can
no longer cause a permanent day skip.  ``--backfill-days`` runs the frozen
one-shot historical horizon in per-day batches, releasing the shared store
lock between days so the five-minute collectors are not starved.  The runner
shares the isolated Crypto store lock with the Spot and USDM collectors so
writers on the same SQLite stay serial.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sqlite3
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.binance.oi_dump_collector import (  # noqa: E402
    BinanceUsdmMetricsDumpCollector,
)
from dataset_registry import (  # noqa: E402
    BINANCE_CANARY_REGISTRY_PATH,
    BINANCE_SPOT_CANARY_MODE,
    load_dataset_registry,
)
from storage.receipt_projection import validated_success_receipt_ids  # noqa: E402
from storage.sqlite_authority_lock import sqlite_authority_lock  # noqa: E402
from tools.run_binance_spot_canary import (  # noqa: E402
    _collect_with_one_provider_retry,
    _private_lock,
)
from tools.run_binance_usdm_canary import _perp_datasets  # noqa: E402

_PROVIDER = BinanceUsdmMetricsDumpCollector.provider
_LOOKBACK_DAYS = 7
# Frozen one-shot horizon: with the latest closed UTC day 2026-08-15 the 198
# day windows start at 2026-01-30, aligning open interest with the bar history.
_BACKFILL_DAYS = 198


def _latest_closed_day(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1)


def metrics_dump_window(now: datetime) -> dict[str, str]:
    """Return the latest fully closed UTC day as the newest dump window."""

    return {"date": _latest_closed_day(now).strftime("%Y-%m-%d")}


def lookback_days(now: datetime) -> tuple[str, ...]:
    """Return the bounded lookback candidate days, newest first."""

    latest = _latest_closed_day(now)
    return tuple(
        (latest - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(_LOOKBACK_DAYS)
    )


def backfill_windows(now: datetime, *, days: int) -> tuple[str, ...]:
    """Return the frozen one-shot historical horizon, oldest first."""

    if days != _BACKFILL_DAYS:
        raise ValueError("the frozen historical backfill horizon is 198 days")
    latest = _latest_closed_day(now)
    return tuple(
        (latest - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(days - 1, -1, -1)
    )


def _ingested_days(
    db_path: Path,
    registry,
    dataset_id: str,
) -> frozenset[str]:
    """Return the dump days backed by validated success receipts in the store.

    The receipt-validity horizon is the real current time, not the run's
    frozen clock, so receipts written moments earlier in the same run are
    never rejected as future evidence.
    """

    now = datetime.now(timezone.utc)

    dataset = registry.resolve(dataset_id)
    binding = registry.provider_binding(dataset_id, _PROVIDER)
    try:
        with sqlite_authority_lock(db_path, mode="shared"):
            uri = f"{db_path.resolve(strict=True).as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.execute("PRAGMA query_only = ON")
                valid = validated_success_receipt_ids(
                    conn, registry, dataset, binding, now=now
                )
                rows = conn.execute(
                    "SELECT p.observed_at, p.receipt_id "
                    "FROM provider_dataset_rows AS p "
                    "WHERE p.dataset_id=? AND p.provider=? AND p.schema_major=?",
                    (dataset.dataset_id, binding.provider, dataset.schema_major),
                ).fetchall()
    except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("open-interest dump fact authority is unavailable") from exc
    days: set[str] = set()
    for observed_at, receipt_id in rows:
        if (
            type(observed_at) is str
            and type(receipt_id) is str
            and receipt_id in valid
        ):
            days.add(observed_at[:10])
    return frozenset(days)


def _blocking_lock(path: Path):
    """Wait for the shared store lock instead of failing a one-shot batch."""

    if not path.is_absolute() or path.parent.is_symlink():
        raise ValueError("lock path must be an absolute non-symlink child")
    descriptor = path.open("a+", encoding="utf-8")
    fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX)
    return descriptor


def _release(lock) -> None:
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        lock.close()


def _yield_past_next_collection_boundary() -> None:
    """Sleep until the five-minute collectors had their scheduled window.

    The 5m timers fire at minute :00 (bars, ~25s worst) and :00:40
    (book-ticker); a backfill batch must not hold-or-regrab the shared lock
    across those windows, or the timers starve and leave permanent bar gaps.
    """

    now = time.time()
    boundary = now - (now % 300) + 300
    target = boundary + 45.0
    if target > now:
        time.sleep(target - now)


def _require_canary_mode() -> None:
    if (
        __import__("os").environ.get("TRADINGDATAS_CANARY_MODE")
        != BINANCE_SPOT_CANARY_MODE
    ):
        raise RuntimeError("Binance canary mode is required")


def _dataset_symbol(dataset_id: str) -> str:
    parts = dataset_id.split(".")
    if len(parts) != 5 or parts[3] != parts[3].lower() or not parts[3].endswith("usdt"):
        raise ValueError("open-interest dataset id does not match the frozen shape")
    return parts[3].upper()


def _run_lookback(
    *,
    db_path: Path,
    lock_path: Path,
    registry,
    datasets: tuple[str, ...],
    now: datetime,
) -> dict[str, object]:
    candidates = lookback_days(now)
    lock = _private_lock(lock_path)
    try:
        collector = BinanceUsdmMetricsDumpCollector()
        results = []
        for dataset_id in datasets:
            ingested = _ingested_days(db_path, registry, dataset_id)
            missing = [day for day in candidates if day not in ingested]
            if not missing:
                results.append(
                    {
                        "collection_kind": "open_interest",
                        "dataset_id": dataset_id,
                        "receipt_ids": [],
                        "retry_count": 0,
                        "state": "unchanged",
                        "window": None,
                    }
                )
                continue
            collected = False
            hard_failure = False
            probed_unpublished = False
            for day in missing:
                if not collector.probe_published(
                    symbol=_dataset_symbol(dataset_id), day=day
                ):
                    # The daily zip lags the UTC day close by hours; skip it
                    # without an ingest attempt so no failed receipt pollutes
                    # the dataset runtime state.
                    probed_unpublished = True
                    continue
                attempts = _collect_with_one_provider_retry(
                    db_path=db_path,
                    registry=registry,
                    collector=collector,
                    dataset_id=dataset_id,
                    request_window={"date": day},
                    now=now,
                )
                last = attempts[-1]
                results.append(
                    {
                        "collection_kind": "open_interest",
                        "dataset_id": dataset_id,
                        "receipt_ids": [
                            receipt_id
                            for attempt in attempts
                            for receipt_id in attempt.receipt_ids
                        ],
                        "retry_count": len(attempts) - 1,
                        "state": last.status,
                        "window": {"date": day},
                    }
                )
                if last.status == "success":
                    collected = True
                    break
                if last.errors != ("provider_error",):
                    # Contract/validation drift is never publication lag;
                    # stop the whole run fail closed.
                    hard_failure = True
                    break
                # provider_error includes an unpublished daily zip; fall
                # through to the next older missing day.
            if hard_failure:
                raise RuntimeError("one or more Crypto dataset collections failed")
            if not collected:
                attempted = any(
                    item["dataset_id"] == dataset_id
                    and item["window"] is not None
                    and item["receipt_ids"]
                    for item in results
                )
                if len(missing) > 1:
                    # Older missing days unpublished/failing too is an
                    # outage, not publication lag.
                    raise RuntimeError("one or more Crypto dataset collections failed")
                if attempted:
                    results[-1]["state"] = "pending_publication"
                else:
                    results.append(
                        {
                            "collection_kind": "open_interest",
                            "dataset_id": dataset_id,
                            "receipt_ids": [],
                            "retry_count": 0,
                            "state": "pending_publication",
                            "window": {"date": missing[0]},
                        }
                    )
        return {
            "datasets": results,
            "lookback_days": _LOOKBACK_DAYS,
            "mode": "execute",
            "state": "success",
        }
    finally:
        _release(lock)


def _run_backfill(
    *,
    db_path: Path,
    lock_path: Path,
    registry,
    datasets: tuple[str, ...],
    now: datetime,
) -> dict[str, object]:
    days = backfill_windows(now, days=_BACKFILL_DAYS)
    collector = BinanceUsdmMetricsDumpCollector()
    collected = 0
    receipt_count = 0
    unpublished_count = 0
    failed_count = 0
    # Compute the ingested-day sets once: re-deriving them per (day, dataset)
    # is O(days x datasets x receipt-table) and made the first production
    # backfill crawl at 100% CPU without writing.  The sets are updated in
    # memory as days complete; a crashed rerun simply re-derives them.
    ingested_by_dataset = {
        dataset_id: set(_ingested_days(db_path, registry, dataset_id))
        for dataset_id in datasets
    }
    for day in days:
        pending = tuple(
            dataset_id
            for dataset_id in datasets
            if day not in ingested_by_dataset[dataset_id]
        )
        if not pending:
            continue
        # One bounded batch per day: the shared store lock is released between
        # days so the five-minute collectors interleave instead of starving.
        # Unpublished zips (pre-listing days, publication gaps) are skipped
        # without an ingest attempt; a provider error after a positive probe
        # is recorded and the day continues, so one bad day never aborts the
        # remaining horizon.  Non-provider (contract/validation) failures
        # still raise fail closed.
        day_results: list[dict[str, object]] = []
        lock = _blocking_lock(lock_path)
        try:
            for dataset_id in pending:
                symbol = _dataset_symbol(dataset_id)
                if not collector.probe_published(symbol=symbol, day=day):
                    day_results.append(
                        {
                            "collection_kind": "open_interest",
                            "dataset_id": dataset_id,
                            "receipt_ids": [],
                            "retry_count": 0,
                            "state": "unpublished",
                            "window": {"date": day},
                        }
                    )
                    continue
                attempts = _collect_with_one_provider_retry(
                    db_path=db_path,
                    registry=registry,
                    collector=collector,
                    dataset_id=dataset_id,
                    request_window={"date": day},
                    now=now,
                )
                last = attempts[-1]
                day_results.append(
                    {
                        "collection_kind": "open_interest",
                        "dataset_id": dataset_id,
                        "receipt_ids": [
                            receipt_id
                            for attempt in attempts
                            for receipt_id in attempt.receipt_ids
                        ],
                        "retry_count": len(attempts) - 1,
                        "state": last.status,
                        "window": {"date": day},
                    }
                )
                if last.status == "success":
                    ingested_by_dataset[dataset_id].add(day)
                elif last.errors != ("provider_error",):
                    raise RuntimeError("OI dump backfill hit a non-provider failure")
        finally:
            _release(lock)
        _yield_past_next_collection_boundary()
        if any(item["state"] == "success" for item in day_results):
            collected += 1
        receipt_count += sum(len(item["receipt_ids"]) for item in day_results)
        unpublished_count += sum(
            1 for item in day_results if item["state"] == "unpublished"
        )
        failed_count += sum(1 for item in day_results if item["state"] == "failed")
    return {
        "backfill_days": _BACKFILL_DAYS,
        "collected_day_count": collected,
        "failed_attempt_count": failed_count,
        "mode": "execute",
        "receipt_count": receipt_count,
        "state": "success",
        "unpublished_skip_count": unpublished_count,
        "window_count": len(days),
    }


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
    backfill_days: int | None = None,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    datasets = _perp_datasets(registry, ".open_interest")
    window = metrics_dump_window(now)
    days = (
        backfill_windows(now, days=backfill_days)
        if backfill_days is not None
        else None
    )
    if not execute:
        return {
            "backfill_days": backfill_days,
            "datasets": list(datasets),
            "lookback_days": None if backfill_days is not None else _LOOKBACK_DAYS,
            "lookback_start": (
                None if backfill_days is not None else lookback_days(now)[-1]
            ),
            "mode": "plan",
            "state": "planned",
            "window_count": len(days) if days is not None else 1,
            "windows": (
                {"first_day": days[0], "last_day": days[-1]}
                if days is not None
                else {"open_interest": window}
            ),
            "will_call_provider": False,
            "will_write_database": False,
        }
    _require_canary_mode()
    if days is not None:
        return _run_backfill(
            db_path=db_path,
            lock_path=lock_path,
            registry=registry,
            datasets=datasets,
            now=now,
        )
    return _run_lookback(
        db_path=db_path,
        lock_path=lock_path,
        registry=registry,
        datasets=datasets,
        now=now,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--lock-path", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backfill-days", type=int)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        result = run(
            db_path=args.db_path,
            lock_path=args.lock_path,
            execute=args.execute,
            now=now,
            backfill_days=args.backfill_days,
        )
    except Exception:
        print(
            json.dumps(
                {"mode": "execute" if args.execute else "plan", "state": "failed"},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
