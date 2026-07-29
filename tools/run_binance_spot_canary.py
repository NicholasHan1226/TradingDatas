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
    BINANCE_SPOT_CANARY_MODE,
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)


def _bar_datasets(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".5m")
    )
    if len(datasets) != 10 or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen ten-symbol bar cohort"
        )
    return datasets


def _rule_datasets(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".rules")
    )
    if len(datasets) != 10 or len(set(datasets)) != len(datasets):
        raise RuntimeError(
            "runtime registry must contain the frozen ten-symbol rule cohort"
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


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
    collect_rules: bool = False,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    datasets = _rule_datasets(registry) if collect_rules else _bar_datasets(registry)
    window = {} if collect_rules else latest_closed_window(now)
    if not execute:
        return {
            "collection_kind": "rules" if collect_rules else "bars",
            "datasets": list(datasets),
            "mode": "plan",
            "state": "planned",
            "window": window,
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
        for dataset_id in datasets:
            result = collect_provider_native_dataset(
                db_path,
                registry=registry,
                collector=collector,
                dataset_id=dataset_id,
                request_window=window,
                attempt_id=str(uuid.uuid4()),
                started_at=_utc(now),
            )
            results.append(
                {
                    "dataset_id": dataset_id,
                    "receipt_ids": list(result.receipt_ids),
                    "state": result.status,
                }
            )
        if any(item["state"] != "success" for item in results):
            raise RuntimeError("one or more Crypto dataset collections failed")
        return {
            "collection_kind": "rules" if collect_rules else "bars",
            "datasets": results,
            "mode": "execute",
            "state": "success",
            "window": window,
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
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        result = run(
            db_path=args.db_path,
            lock_path=args.lock_path,
            execute=args.execute,
            now=now,
            collect_rules=args.rules,
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
