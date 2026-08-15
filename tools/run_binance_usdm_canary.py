#!/usr/bin/env python3
"""Collect Binance USDⓈ-M funding-rate and open-interest history slices.

This candidate runner has no account, order, key, Testnet, or fallback path.
It is intentionally separate from the Spot canary runner and accepts no
provider, symbol, field, or registry path input.  Funding-rate polling uses a
trailing 48-hour window so re-observed rows deduplicate by their append-only
payload identity; open-interest polling uses the two latest closed 5-minute
boundaries.  It shares the isolated Crypto store lock with the Spot collector
so writers on the same SQLite stay serial.
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

from collectors.binance.usdm_collector import BinanceUsdmPublicCollector  # noqa: E402
from dataset_registry import (  # noqa: E402
    BINANCE_CANARY_REGISTRY_PATH,
    BINANCE_SPOT_CANARY_MODE,
    load_dataset_registry,
)
from tools.run_binance_spot_canary import (  # noqa: E402
    _collect_with_one_provider_retry,
    _private_lock,
    _utc,
)

_FUNDING_LOOKBACK = timedelta(hours=48)


def _perp_datasets(registry, suffix: str) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.perp.binance.")
        and item.dataset_id.endswith(suffix)
    )
    if len(datasets) != 10 or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen ten-symbol perp cohort"
        )
    return datasets


def funding_rate_window(now: datetime) -> dict[str, str]:
    """Return a trailing 48h window ending at the latest realized funding time."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    minute = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    boundary = minute.replace(minute=0) - timedelta(hours=minute.hour % 8)
    return {
        "start_time": _utc(boundary - _FUNDING_LOOKBACK),
        "end_time": _utc(boundary),
    }


def open_interest_window(now: datetime) -> dict[str, str]:
    """Return the two latest closed 5-minute boundaries, mirroring the bars."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    minute = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    boundary = minute - timedelta(minutes=minute.minute % 5)
    latest_open = boundary - timedelta(minutes=5)
    return {
        "start_time": _utc(latest_open - timedelta(minutes=5)),
        "end_time": _utc(latest_open),
    }


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    funding_datasets = _perp_datasets(registry, ".funding_rate")
    open_interest_datasets = _perp_datasets(registry, ".open_interest")
    groups = (
        ("funding_rate", funding_datasets, funding_rate_window(now)),
        ("open_interest", open_interest_datasets, open_interest_window(now)),
    )
    if not execute:
        return {
            "datasets": [dataset for _, datasets, _ in groups for dataset in datasets],
            "mode": "plan",
            "state": "planned",
            "windows": {kind: window for kind, _, window in groups},
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
        collector = BinanceUsdmPublicCollector()
        results = []
        for kind, datasets, window in groups:
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
                        "collection_kind": kind,
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
            "datasets": results,
            "mode": "execute",
            "state": "success",
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
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        result = run(
            db_path=args.db_path,
            lock_path=args.lock_path,
            execute=args.execute,
            now=now,
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
