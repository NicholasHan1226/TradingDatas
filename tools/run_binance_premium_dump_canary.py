#!/usr/bin/env python3
"""Collect Binance USDⓈ-M premium index from the public daily klines dump.

This candidate runner has no account, order, key, Testnet, or fallback path.
While ``fapi.binance.com`` is blocked at the SNI layer it downloads one
published daily ``premiumIndexKlines`` 5-minute zip per frozen symbol from
``https://data.binance.vision`` and feeds the
``crypto.perp.binance.<symbol>.premium_index`` datasets.  The premium index is
the main observable driver of funding-rate pressure — a proxy input, not the
funding rate itself, which still has no public dump.  It accepts no provider,
symbol, field, or registry path input.

The windowing, publication probe, bounded seven-day lookback, one-shot
historical backfill and shared store-lock discipline are exactly those of the
open-interest dump runner: ``tools/run_binance_oi_dump_canary.py`` provides
the shared implementation, and this runner only binds the premium-index
dataset family, probe path, and collection kind.  ``--backfill-days`` runs the
same frozen 198-day horizon aligned with the bar history, in per-day batches
that release the shared store lock between days.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
    load_dataset_registry,
)
from tools.run_binance_oi_dump_canary import (  # noqa: E402
    _LOOKBACK_DAYS,
    _require_canary_mode,
    _run_backfill,
    _run_lookback,
    backfill_windows,
    lookback_days,
    metrics_dump_window,
)
from tools.run_binance_usdm_canary import _perp_datasets  # noqa: E402


def run(
    *,
    db_path: Path,
    lock_path: Path,
    execute: bool,
    now: datetime,
    backfill_days: int | None = None,
) -> dict[str, object]:
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    datasets = _perp_datasets(registry, ".premium_index")
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
                else {"premium_index": window}
            ),
            "will_call_provider": False,
            "will_write_database": False,
        }
    _require_canary_mode()
    collector = BinanceUsdmMetricsDumpCollector()
    if days is not None:
        return _run_backfill(
            db_path=db_path,
            lock_path=lock_path,
            registry=registry,
            collector=collector,
            collection_kind="premium_index",
            datasets=datasets,
            now=now,
        )
    return _run_lookback(
        db_path=db_path,
        lock_path=lock_path,
        registry=registry,
        collector=collector,
        collection_kind="premium_index",
        probe=lambda symbol, day: collector.probe_premium_index_published(
            symbol=symbol, day=day
        ),
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
