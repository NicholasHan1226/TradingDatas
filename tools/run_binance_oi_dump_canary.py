#!/usr/bin/env python3
"""Collect Binance USDⓈ-M open interest from the public daily metrics dump.

This candidate runner has no account, order, key, Testnet, or fallback path.
It is the owner-approved degradation source while ``fapi.binance.com`` is
blocked at the SNI layer: it downloads one published daily ``metrics`` zip per
frozen symbol from ``https://data.binance.vision`` and feeds the same
``crypto.perp.binance.<symbol>.open_interest`` datasets.  It accepts no
provider, symbol, field, or registry path input; the window is always the
latest fully closed UTC day so a run never asks for an unpublished file.  It
shares the isolated Crypto store lock with the Spot and USDM collectors so
writers on the same SQLite stay serial.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sys


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
from tools.run_binance_spot_canary import (  # noqa: E402
    _collect_with_one_provider_retry,
    _private_lock,
)
from tools.run_binance_usdm_canary import _perp_datasets  # noqa: E402


def metrics_dump_window(now: datetime) -> dict[str, str]:
    """Return the latest fully closed UTC day as the dump window."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"date": (today - timedelta(days=1)).strftime("%Y-%m-%d")}


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    datasets = _perp_datasets(registry, ".open_interest")
    window = metrics_dump_window(now)
    if not execute:
        return {
            "datasets": list(datasets),
            "mode": "plan",
            "state": "planned",
            "windows": {"open_interest": window},
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
        collector = BinanceUsdmMetricsDumpCollector()
        results = []
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
                    "collection_kind": "open_interest",
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
