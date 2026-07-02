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
from typing import Any

import yaml

# Bootstrap: add SharedSignals root to sys.path so package imports work
_BASE_DIR = Path(__file__).resolve().parents[2]  # SharedSignals root
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from collectors.tushare.collector import TushareCollector  # noqa: E402
from storage.csv_bridge import (  # noqa: E402
    CSV_TO_TABLE_MAP,
    DEFAULT_SQLITE_PATH,
    ingest_csv_to_sqlite,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = _BASE_DIR / "collectors" / "tushare" / "config.yaml"
STOCK_MASTER_PATH = _BASE_DIR / "reference" / "stock_master.csv"
HK_STOCK_MASTER_PATH = _BASE_DIR / "reference" / "hk_stock_master.csv"
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
    """Substitute placeholders in a params template dict.

    Uses data-level key-value substitution to avoid YAML injection via
    unescaped placeholder values (no string → YAML re-parse round-trip).
    """
    import copy
    result = copy.deepcopy(template)

    def _replace(val: Any) -> Any:
        if isinstance(val, str):
            if ts_code:
                val = val.replace("{ts_code}", ts_code)
            val = val.replace("{trade_date}", trade_date)
            val = val.replace("{start_date}", start_date)
            val = val.replace("{end_date}", end_date)
            return val
        if isinstance(val, dict):
            return {k: _replace(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_replace(item) for item in val]
        return val

    return _replace(result)


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
    hk_stock_codes: list[str] | None = None,
    sqlite_bridge_enabled: bool = True,
    sqlite_db_path: Path = DEFAULT_SQLITE_PATH,
) -> dict[str, dict]:
    """Run all APIs in a tier. Returns {api_name: {"rows": N, "duration_s": t}}."""
    stats: dict[str, dict] = {}
    tier_start = time.time()

    # Split APIs: global, A-share per-stock, HK per-stock
    per_stock_ashare = [a for a in apis if a.get("per_stock", True) and a.get("stock_list") != "hk"]
    per_stock_hk = [a for a in apis if a.get("per_stock", True) and a.get("stock_list") == "hk"]
    global_apis = [a for a in apis if not a.get("per_stock", True)]

    # Resolve HK stock codes
    hk_codes = hk_stock_codes or []

    total_calls = (
        len(per_stock_ashare) * len(stock_codes)
        + len(per_stock_hk) * len(hk_codes)
        + len(global_apis)
    )
    call_idx = 0

    logger.info("[%s] %d APIs (%d A-share per-stock, %d HK per-stock, %d global) x (%d A / %d HK stocks) = %d calls",
                tier_name, len(apis), len(per_stock_ashare), len(per_stock_hk), len(global_apis),
                len(stock_codes), len(hk_codes), total_calls)

    def _bridge_csv(api_name: str, path: Path | None) -> int:
        if not sqlite_bridge_enabled or path is None:
            return 0
        table = CSV_TO_TABLE_MAP.get(api_name)
        if not table:
            return 0
        try:
            rows = ingest_csv_to_sqlite(sqlite_db_path, table, path)
            logger.info("sqlite bridge %s -> %s: %d rows from %s", api_name, table, rows, path)
            return rows
        except Exception:
            logger.exception("sqlite bridge failed for %s from %s", api_name, path)
            return 0

    def _run_per_stock(api_defs: list[dict], codes: list[str], label: str) -> None:
        nonlocal call_idx
        for api_def in api_defs:
            api_name = api_def["api_name"]
            template = api_def.get("params", {})
            fields = api_def.get("fields")
            api_start = time.time()
            api_total = 0
            bridge_total = 0

            for ts_code in codes:
                call_idx += 1
                params = fill_params(template, ts_code, trade_date, start_date, end_date)
                rows = collector.collect(api_name, params, fields)
                api_total += len(rows)
                save_path = collector.save(api_name, rows, trade_date, filename=ts_code)
                bridge_total += _bridge_csv(api_name, save_path)
                logger.info("[%s] [%d/%d] %s %s → %d rows",
                            tier_name, call_idx, total_calls,
                            api_name, ts_code, len(rows))

            duration = time.time() - api_start
            stats[api_name] = {
                "rows": api_total,
                "duration_s": round(duration, 1),
                "sqlite_bridge_rows": bridge_total,
            }
            logger.info("[%s] %s (%s): %d rows, bridge=%d rows in %.1fs",
                        tier_name, api_name, label, api_total, bridge_total, duration)

    # ── Per-stock: A-share ──
    _run_per_stock(per_stock_ashare, stock_codes, "A-share")

    # ── Per-stock: HK ──
    _run_per_stock(per_stock_hk, hk_codes, "HK")

    # ── Global (non-per-stock) APIs ──
    for api_def in global_apis:
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        api_start = time.time()

        call_idx += 1
        params = fill_params(template, None, trade_date, start_date, end_date)
        rows = collector.collect(api_name, params, fields)
        save_path = collector.save(api_name, rows, trade_date)
        bridge_total = _bridge_csv(api_name, save_path)

        duration = time.time() - api_start
        stats[api_name] = {
            "rows": len(rows),
            "duration_s": round(duration, 1),
            "sqlite_bridge_rows": bridge_total,
        }
        logger.info("[%s] [%d/%d] %s (global) → %d rows, bridge=%d rows in %.1fs",
                    tier_name, call_idx, total_calls,
                    api_name, len(rows), bridge_total, duration)

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
    parser.add_argument(
        "--no-sqlite-bridge",
        action="store_true",
        help="Disable additive CSV-to-SQLite bridge and keep CSV-only mode",
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

    # Detect if any API in this tier needs HK stock codes
    needs_hk = any(a.get("stock_list") == "hk" for a in apis)
    hk_stock_codes: list[str] = []
    if needs_hk:
        if HK_STOCK_MASTER_PATH.exists():
            hk_stock_codes = load_stock_codes(HK_STOCK_MASTER_PATH)
            if not hk_stock_codes:
                logger.warning("HK stock master file exists but is empty: %s", HK_STOCK_MASTER_PATH)
        else:
            logger.warning("HK stock master file not found: %s — HK per-stock APIs will be skipped", HK_STOCK_MASTER_PATH)

    if args.test:
        stock_codes = stock_codes[:3]
        hk_stock_codes = hk_stock_codes[:3] if hk_stock_codes else []
        logger.info("TEST MODE: using %d A-share / %d HK stocks", len(stock_codes), len(hk_stock_codes))

    trade_date, start_date, end_date = date_range(args.lookback)
    logger.info("=" * 60)
    logger.info("TIER: %s  |  A-Stocks: %d  |  HK-Stocks: %d  |  APIs: %d",
                tier_name, len(stock_codes), len(hk_stock_codes), len(apis))
    logger.info("Window: %s → %s (trade_date=%s, lookback=%d days)",
                start_date, end_date, trade_date, args.lookback)
    logger.info("=" * 60)

    collector = TushareCollector()
    start_time = time.time()

    stats = sync_tier(
        collector, tier_name, apis, stock_codes,
        trade_date, start_date, end_date,
        hk_stock_codes=hk_stock_codes,
        sqlite_bridge_enabled=not args.no_sqlite_bridge,
    )

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("SYNC SUMMARY [%s] — %.1fs total", tier_name, elapsed)
    total_rows = 0
    total_bridge_rows = 0
    for api_name, s in stats.items():
        total_rows += s["rows"]
        total_bridge_rows += s.get("sqlite_bridge_rows", 0)
        logger.info("  %-25s %6d rows  bridge=%6d  %6.1fs",
                    api_name, s["rows"], s.get("sqlite_bridge_rows", 0), s["duration_s"])
    logger.info("  %-25s %6d rows", "TOTAL", total_rows)
    logger.info("  %-25s %6d rows", "SQLITE_BRIDGE_TOTAL", total_bridge_rows)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
