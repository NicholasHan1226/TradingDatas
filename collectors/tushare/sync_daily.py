#!/usr/bin/env python3
"""SharedSignals Tushare daily sync — multi-tier collector.

Usage:
    sync_daily.py --tier P0_trading_5min         # 5-min trading data
    sync_daily.py --tier P1_eod_daily            # EOD after close
    sync_daily.py --tier P2_financial_daily      # financial statements
    sync_daily.py --tier P3_reference_daily      # reference/master
    sync_daily.py --tier P4_macro_daily          # macro indicators
    sync_daily.py --tier P5_hk_us_daily          # HK/US markets
    sync_daily.py --tier P6_other_daily          # futures/funds/news
    sync_daily.py --test --tier P0_trading_5min  # quick test on 3 stocks

Reads config.yaml for tier definitions, iterates over stocks in
reference/stock_master.csv (for per_stock APIs), calls each API,
and writes date-partitioned CSV output to data/tushare/.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# Bootstrap: ensure collector is importable
_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root
_COLLECTOR_DIR = _BASE_DIR / "collectors" / "tushare"
if str(_COLLECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_COLLECTOR_DIR))

from collector import TushareCollector  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = _COLLECTOR_DIR / "config.yaml"
STOCK_MASTER_PATH = _BASE_DIR / "reference" / "stock_master.csv"
DEFAULT_LOOKBACK_DAYS = 7

VALID_TIERS = [
    "P0_trading_5min",
    "P1_eod_daily",
    "P2_financial_daily",
    "P3_reference_daily",
    "P4_macro_daily",
    "P5_hk_us_daily",
    "P6_other_daily",
]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_stock_codes(path: Path) -> list[str]:
    """Read ts_code column from stock_master.csv."""
    codes: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("ts_code") or "").strip()
            if code:
                codes.append(code)
    logger.info("Loaded %d stock codes from %s", len(codes), path)
    return codes


def date_range(lookback_days: int) -> tuple[str, str, str]:
    """Return (trade_date, start_date, end_date) for a lookback window."""
    today = datetime.now()
    trade_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end_date = trade_date
    return trade_date, start_date, end_date


def fill_params(
    template: dict,
    ts_code: str | None,
    trade_date: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Substitute placeholders in a params template dict."""
    raw = str(template)
    if ts_code:
        raw = raw.replace("{ts_code}", ts_code)
    raw = raw.replace("{trade_date}", trade_date)
    raw = raw.replace("{start_date}", start_date)
    raw = raw.replace("{end_date}", end_date)
    return yaml.safe_load(raw)


# ---------------------------------------------------------------------------
# sync_tier — core sync logic for a single tier
# ---------------------------------------------------------------------------

def sync_tier(
    collector: TushareCollector,
    tier_name: str,
    apis: list[dict],
    stock_codes: list[str],
    trade_date: str,
    start_date: str,
    end_date: str,
) -> dict[str, dict]:
    """Run all APIs in a tier. Returns {api_name: {"rows": N, "duration_s": t}}."""
    stats: dict[str, dict] = {}
    tier_start = time.time()

    # Split APIs by per_stock flag
    per_stock_apis = [a for a in apis if a.get("per_stock", True)]
    global_apis = [a for a in apis if not a.get("per_stock", True)]

    total_calls = len(per_stock_apis) * len(stock_codes) + len(global_apis)
    call_idx = 0

    logger.info("[%s] %d APIs (%d per-stock, %d global) × %d stocks = %d calls",
                tier_name, len(apis), len(per_stock_apis), len(global_apis),
                len(stock_codes), total_calls)

    # ── Per-stock APIs ──
    for api_def in per_stock_apis:
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        api_start = time.time()
        api_total = 0

        for ts_code in stock_codes:
            call_idx += 1
            params = fill_params(template, ts_code, trade_date, start_date, end_date)
            rows = collector.collect(api_name, params, fields)
            api_total += len(rows)
            collector.save(api_name, rows, trade_date, filename=ts_code)
            logger.info("[%s] [%d/%d] %s %s → %d rows",
                        tier_name, call_idx, total_calls,
                        api_name, ts_code, len(rows))

        duration = time.time() - api_start
        stats[api_name] = {"rows": api_total, "duration_s": round(duration, 1)}
        logger.info("[%s] %s: %d rows in %.1fs", tier_name, api_name, api_total, duration)

    # ── Global (non-per-stock) APIs ──
    for api_def in global_apis:
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        api_start = time.time()

        call_idx += 1
        params = fill_params(template, None, trade_date, start_date, end_date)
        rows = collector.collect(api_name, params, fields)
        collector.save(api_name, rows, trade_date)

        duration = time.time() - api_start
        stats[api_name] = {"rows": len(rows), "duration_s": round(duration, 1)}
        logger.info("[%s] [%d/%d] %s (global) → %d rows in %.1fs",
                    tier_name, call_idx, total_calls,
                    api_name, len(rows), duration)

    tier_duration = time.time() - tier_start
    logger.info("[%s] COMPLETE: %d APIs, %.1fs total", tier_name, len(apis), tier_duration)
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SharedSignals Tushare multi-tier sync")
    parser.add_argument(
        "--tier",
        required=True,
        choices=VALID_TIERS,
        help="Which tier to sync",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window in days (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Limit to 3 stocks for speed testing",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Load config + stocks
    config = load_config(CONFIG_PATH)
    stock_codes = load_stock_codes(STOCK_MASTER_PATH)

    if not stock_codes:
        logger.error("No stock codes in %s — aborting", STOCK_MASTER_PATH)
        sys.exit(1)

    tier_name = args.tier
    if tier_name not in config.get("priorities", {}):
        logger.error("Tier %s not found in config.yaml priorities", tier_name)
        sys.exit(1)

    apis = config["priorities"][tier_name]
    if args.test:
        stock_codes = stock_codes[:3]
        logger.info("TEST MODE: using %d stocks", len(stock_codes))

    trade_date, start_date, end_date = date_range(args.lookback)
    logger.info("=" * 60)
    logger.info("TIER: %s  |  Stocks: %d  |  APIs: %d", tier_name, len(stock_codes), len(apis))
    logger.info("Window: %s → %s (trade_date=%s, lookback=%d days)",
                start_date, end_date, trade_date, args.lookback)
    logger.info("=" * 60)

    collector = TushareCollector()
    start_time = time.time()

    stats = sync_tier(collector, tier_name, apis, stock_codes, trade_date, start_date, end_date)

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("SYNC SUMMARY [%s] — %.1fs total", tier_name, elapsed)
    total_rows = 0
    for api_name, s in stats.items():
        total_rows += s["rows"]
        logger.info("  %-25s %6d rows  %6.1fs", api_name, s["rows"], s["duration_s"])
    logger.info("  %-25s %6d rows", "TOTAL", total_rows)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
