#!/usr/bin/env python3
"""SharedSignals CNFutures historical daily backfill.

Lightweight wrapper around the existing ``sync_daily.py`` P6 ``fut_daily``
entry. Instead of duplicating Tushare collection logic, this script loops over
a date range and spawns one ``sync_daily.py`` invocation per trade date.

Examples
--------
    # 6-month historical backfill, skip weekends (default)
    python3 collectors/tushare/backfill_fut_daily.py \
        --start-date 20260101 --end-date 20260630

    # 12-month backfill with fail-fast
    python3 collectors/tushare/backfill_fut_daily.py \
        --start-date 20250101 --end-date 20251231 --fail-fast

    # Dry-run to preview commands
    python3 collectors/tushare/backfill_fut_daily.py \
        --start-date 20260101 --end-date 20260131 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SYNC_SCRIPT = _ROOT / "collectors" / "tushare" / "sync_daily.py"
_TIER = "P6_other_daily"
_API = "fut_daily"

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}, expected YYYYMMDD"
        ) from exc


def generate_dates(start: datetime, end: datetime, skip_weekends: bool) -> list[str]:
    """Return YYYYMMDD strings between ``start`` and ``end`` (inclusive)."""
    if end < start:
        raise ValueError(
            f"end_date {end:%Y%m%d} is before start_date {start:%Y%m%d}"
        )
    dates: list[str] = []
    current = start
    while current <= end:
        if not skip_weekends or current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def build_command(
    python_bin: str,
    trade_date: str,
) -> list[str]:
    """Construct the sync_daily.py command for a single trade date."""
    return [
        python_bin,
        str(_SYNC_SCRIPT),
        "--tier", _TIER,
        "--only-api", _API,
        "--trade-date", trade_date,
        "--exit-on-failure",
        "--failure-threshold", "0.0",
    ]


def run_backfill(
    start_date: str,
    end_date: str,
    *,
    skip_weekends: bool = True,
    dry_run: bool = False,
    fail_fast: bool = False,
    python_bin: str | None = None,
) -> dict[str, Any]:
    """Loop over dates and run the per-day sync command.

    Returns a summary dict including ``successful``, ``failed``,
    ``success_count``, ``failure_count`` and ``total_dates``.
    """
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    dates = generate_dates(start_dt, end_dt, skip_weekends)
    python_bin = python_bin or sys.executable

    summary: dict[str, Any] = {
        "tier": _TIER,
        "api": _API,
        "start_date": start_date,
        "end_date": end_date,
        "skip_weekends": skip_weekends,
        "dry_run": dry_run,
        "fail_fast": fail_fast,
        "total_dates": len(dates),
        "successful": [],
        "failed": [],
        "commands": [],
    }

    for trade_date in dates:
        cmd = build_command(python_bin, trade_date)
        summary["commands"].append({"date": trade_date, "cmd": cmd})

        if dry_run:
            logger.info("DRY-RUN: %s", " ".join(cmd))
            summary["successful"].append(trade_date)
            continue

        logger.info("backfill %s/%s: %s", trade_date, _API, " ".join(cmd))
        result = subprocess.run(
            cmd,
            cwd=_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        if result.stdout:
            for line in result.stdout.splitlines():
                logger.info("[sync_daily %s] %s", trade_date, line)

        if result.returncode != 0:
            summary["failed"].append({
                "date": trade_date,
                "returncode": result.returncode,
                "stderr": result.stderr,
            })
            logger.error(
                "backfill failed for %s: exit %d\n%s",
                trade_date,
                result.returncode,
                result.stderr,
            )
            if fail_fast:
                break
        else:
            summary["successful"].append(trade_date)

    summary["success_count"] = len(summary["successful"])
    summary["failure_count"] = len(summary["failed"])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill CNFutures daily bars via sync_daily.py"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=_parse_date,
        help="Start date (YYYYMMDD)",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=_parse_date,
        help="End date (YYYYMMDD)",
    )
    parser.add_argument(
        "--skip-weekends",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Skip Saturday/Sunday (default: True)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first failed day",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python interpreter used to run sync_daily.py",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    start = args.start_date.strftime("%Y%m%d")
    end = args.end_date.strftime("%Y%m%d")
    try:
        summary = run_backfill(
            start,
            end,
            skip_weekends=args.skip_weekends,
            dry_run=args.dry_run,
            fail_fast=args.fail_fast,
            python_bin=args.python_bin,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(2)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    sys.exit(2 if summary["failure_count"] else 0)


if __name__ == "__main__":
    main()
