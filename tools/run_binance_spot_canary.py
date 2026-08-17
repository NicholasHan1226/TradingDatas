#!/usr/bin/env python3
"""Collect only the latest closed Binance Spot 5m bars into an isolated store.

This candidate runner has no account, order, key, Testnet, or fallback path.
It is intentionally separate from the Tushare cadence runner and accepts no
provider, symbol, field, or registry path input.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.binance.collector import BinanceSpotPublicCollector  # noqa: E402
from collectors.tushare.provider_native_ingest import (  # noqa: E402
    collect_provider_native_dataset,
)
from dataset_registry import (  # noqa: E402
    BINANCE_CANARY_REGISTRY_PATH,
    BINANCE_SPOT_CANARY_MODE,
    load_dataset_registry,
)
from tools.compile_crypto_binance_canary_registry import (  # noqa: E402
    FROZEN_CRYPTO_SYMBOL_COUNT,
)

FIVE_MINUTES = timedelta(minutes=5)
_MAX_DATASET_ATTEMPTS = 2


def _bar_datasets(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".5m")
    )
    if len(datasets) != FROZEN_CRYPTO_SYMBOL_COUNT or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen forty-symbol bar cohort"
        )
    return datasets


def _rule_datasets(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".rules")
    )
    if len(datasets) != FROZEN_CRYPTO_SYMBOL_COUNT or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen forty-symbol rule cohort"
        )
    return datasets


def _book_ticker_datasets(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".book_ticker")
    )
    if len(datasets) != FROZEN_CRYPTO_SYMBOL_COUNT or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen forty-symbol book-ticker cohort"
        )
    return datasets


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def latest_closed_window(now: datetime) -> dict[str, str]:
    """Return two adjacent 5m opens ending with the last fully closed bar."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    minute = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    boundary = minute - timedelta(minutes=minute.minute % 5)
    latest_open = boundary - timedelta(minutes=5)
    return {
        "start_open_time": _utc(latest_open - timedelta(minutes=5)),
        "end_open_time": _utc(latest_open),
    }


def backfill_windows(now: datetime, *, days: int) -> tuple[dict[str, str], ...]:
    """Return contiguous non-overlapping windows within the provider cap."""

    if days != 180:
        raise ValueError("the frozen historical backfill horizon is 180 days")
    latest = latest_closed_window(now)["end_open_time"]
    latest_open = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    first_open = latest_open - timedelta(days=days) + FIVE_MINUTES
    windows: list[dict[str, str]] = []
    cursor = first_open
    maximum_span = timedelta(days=3)
    while cursor <= latest_open:
        end = min(cursor + maximum_span, latest_open)
        windows.append(
            {
                "start_open_time": _utc(cursor),
                "end_open_time": _utc(end),
            }
        )
        cursor = end + FIVE_MINUTES
    return tuple(windows)


def _private_lock(path: Path):
    if not path.is_absolute() or path.parent.is_symlink():
        raise ValueError("lock path must be an absolute non-symlink child")
    descriptor = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        descriptor.close()
        raise RuntimeError("collection lock is already held") from None
    return descriptor


def _collect_with_one_provider_retry(
    *,
    db_path: Path,
    registry,
    collector: BinanceSpotPublicCollector,
    dataset_id: str,
    request_window: dict[str, str],
    now: datetime,
):
    """Persist a failed provider attempt, then retry it once if it is transient.

    The generic ingest path persists every terminal attempt.  A single immediate
    retry therefore preserves the failed receipt while allowing a brief public
    transport interruption to recover before the consumer's 5-minute cutoff.
    Config, validation, and legal-empty outcomes are never retried here.
    """

    attempts = []
    for index in range(_MAX_DATASET_ATTEMPTS):
        result = collect_provider_native_dataset(
            db_path,
            registry=registry,
            collector=collector,
            dataset_id=dataset_id,
            request_window=request_window,
            attempt_id=str(uuid.uuid4()),
            started_at=_utc(now if index == 0 else datetime.now(timezone.utc)),
        )
        attempts.append(result)
        if not (
            result.status == "failed"
            and result.errors == ("provider_error",)
            and index + 1 < _MAX_DATASET_ATTEMPTS
        ):
            break
    return tuple(attempts)


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
    collect_rules: bool = False,
    collect_book_ticker: bool = False,
    backfill_days: int | None = None,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    if collect_rules and collect_book_ticker:
        raise ValueError("Crypto collector mode is ambiguous")
    if (collect_rules or collect_book_ticker) and backfill_days is not None:
        raise ValueError("current snapshots do not support historical backfill")
    datasets = (
        _rule_datasets(registry)
        if collect_rules
        else _book_ticker_datasets(registry)
        if collect_book_ticker
        else _bar_datasets(registry)
    )
    windows = (
        ({},)
        if collect_rules or collect_book_ticker
        else (
            backfill_windows(now, days=backfill_days)
            if backfill_days is not None
            else (latest_closed_window(now),)
        )
    )
    if not execute:
        return {
            "backfill_days": backfill_days,
            "collection_kind": (
                "rules"
                if collect_rules
                else "book_ticker"
                if collect_book_ticker
                else "bars"
            ),
            "datasets": list(datasets),
            "mode": "plan",
            "state": "planned",
            "window_count": len(windows),
            "windows": list(windows),
            "will_call_provider": False,
            "will_write_database": False,
        }
    if (
        __import__("os").environ.get("TRADINGDATAS_CANARY_MODE")
        != BINANCE_SPOT_CANARY_MODE
    ):
        raise RuntimeError("Binance canary mode is required")
    lock = _private_lock(lock_path)
    try:
        collector = BinanceSpotPublicCollector()
        results = []
        for window in windows:
            for dataset_id in datasets:
                attempts = _collect_with_one_provider_retry(
                    db_path=db_path,
                    registry=registry,
                    collector=collector,
                    dataset_id=dataset_id,
                    request_window=window,
                    now=now,
                )
                results.append(
                    {
                        "dataset_id": dataset_id,
                        "receipt_ids": [
                            receipt_id
                            for attempt in attempts
                            for receipt_id in attempt.receipt_ids
                        ],
                        "retry_count": len(attempts) - 1,
                        "state": attempts[-1].status,
                        "window": window,
                    }
                )
        if any(item["state"] != "success" for item in results):
            raise RuntimeError("one or more Crypto dataset collections failed")
        return {
            "backfill_days": backfill_days,
            "collection_kind": (
                "rules"
                if collect_rules
                else "book_ticker"
                if collect_book_ticker
                else "bars"
            ),
            "datasets": results,
            "mode": "execute",
            "state": "success",
            "window_count": len(windows),
        }
    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            lock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--lock-path", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--rules", action="store_true")
    parser.add_argument("--book-ticker", action="store_true")
    parser.add_argument("--backfill-days", type=int)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        result = run(
            db_path=args.db_path,
            lock_path=args.lock_path,
            execute=args.execute,
            now=now,
            collect_rules=args.rules,
            collect_book_ticker=args.book_ticker,
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
