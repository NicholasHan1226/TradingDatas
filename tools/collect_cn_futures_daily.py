#!/usr/bin/env python3
"""SharedSignals CNFutures daily collection entry point.

Thin wrapper around ``collectors/tushare/sync_daily.py`` that runs the
Tushare ``fut_daily`` global API for a single trade_date, writes the result
directly into ``market_bars_daily`` with ``market=Futures``, and exits
non-zero on any failure.

Intended callers:
- TradingAgent scheduler / server jobs
- cron via ``cron/cn_futures_daily.sh``
- Manual backfill: ``python3 tools/collect_cn_futures_daily.py --trade-date 20260703``

Usage:
    python3 tools/collect_cn_futures_daily.py
    python3 tools/collect_cn_futures_daily.py --trade-date 20260703
    python3 tools/collect_cn_futures_daily.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# SharedSignals root (two levels up from this file)
ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT / "collectors" / "tushare" / "sync_daily.py"
TIER = "P6_other_daily"
API_NAME = "fut_daily"

logger = logging.getLogger(__name__)
_DATE_RE = re.compile(r"^\d{8}$")


def default_trade_date() -> str:
    """Return today's date as YYYYMMDD."""
    return datetime.now().strftime("%Y%m%d")


def build_command(trade_date: str) -> list[str]:
    """Build the sync_daily.py subprocess command."""
    if not _DATE_RE.match(trade_date):
        raise ValueError(f"invalid trade_date {trade_date!r}, expected YYYYMMDD")
    cmd = [
        sys.executable,
        str(SYNC_SCRIPT),
        "--tier", TIER,
        "--only-api", API_NAME,
        "--trade-date", trade_date,
        "--exit-on-failure",
        "--failure-threshold", "0.0",
    ]
    return cmd


def run_collection(
    trade_date: str,
    *,
    dry_run: bool = False,
) -> int:
    """Run the fut_daily collection and return the subprocess exit code."""
    cmd = build_command(trade_date)
    logger.info("CNFutures daily collection: trade_date=%s direct_sqlite=true", trade_date)
    logger.info("Running: %s", " ".join(cmd))

    if dry_run:
        print(" ".join(cmd))
        return 0

    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        logger.error("CNFutures daily collection failed with exit code %d", result.returncode)
    else:
        logger.info("CNFutures daily collection completed")
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SharedSignals CNFutures daily collection wrapper",
    )
    parser.add_argument(
        "--trade-date",
        default=default_trade_date(),
        help=f"Trade date as YYYYMMDD (default: {default_trade_date()})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would be run without executing it",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        return run_collection(
            trade_date=args.trade_date,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
