#!/usr/bin/env python3
"""SharedSignals daily Tushare sync — P0 + P1 APIs for all stocks in stock_master.csv.

Reads config.yaml for P0/P1 API definitions, iterates over every stock in
reference/stock_master.csv, calls each API for a configurable lookback window,
and writes date-partitioned CSV output.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
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
    """Return (trade_date, start_date, end_date) for a lookback window.

    trade_date = today
    start_date = today - lookback_days
    end_date   = today
    """
    today = datetime.now()
    trade_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end_date = trade_date
    return trade_date, start_date, end_date


def fill_params(template: dict, ts_code: str, trade_date: str, start_date: str, end_date: str) -> dict:
    """Substitute placeholders in a params template dict."""
    raw = str(template)
    raw = raw.replace("{ts_code}", ts_code)
    raw = raw.replace("{trade_date}", trade_date)
    raw = raw.replace("{start_date}", start_date)
    raw = raw.replace("{end_date}", end_date)
    # Round-trip through YAML-safe eval to get typed dict back
    return yaml.safe_load(raw)


def sync_priority(
    collector: TushareCollector,
    apis: list[dict],
    stock_codes: list[str],
    trade_date: str,
    start_date: str,
    end_date: str,
) -> dict[str, int]:
    """Run all APIs in a priority tier for every stock.  Returns {api_name: total_rows}."""
    stats: dict[str, int] = {}
    total = len(stock_codes) * len(apis)
    idx = 0

    for api_def in apis:
        api_name = api_def["api_name"]
        template = api_def.get("params", {})
        fields = api_def.get("fields")
        api_total = 0

        for ts_code in stock_codes:
            idx += 1
            params = fill_params(template, ts_code, trade_date, start_date, end_date)
            rows = collector.collect(api_name, params, fields)
            api_total += len(rows)
            collector.save(api_name, rows, trade_date, filename=ts_code)
            logger.info("[%d/%d] %s %s → %d rows", idx, total, api_name, ts_code, len(rows))

        stats[api_name] = api_total
        logger.info("%s: %d total rows across %d stocks", api_name, api_total, len(stock_codes))

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config = load_config(CONFIG_PATH)
    stock_codes = load_stock_codes(STOCK_MASTER_PATH)

    if not stock_codes:
        logger.error("No stock codes found in %s — aborting", STOCK_MASTER_PATH)
        sys.exit(1)

    trade_date, start_date, end_date = date_range(DEFAULT_LOOKBACK_DAYS)
    logger.info("Sync window: %s → %s (trade_date=%s)", start_date, end_date, trade_date)
    logger.info("Stocks: %d  APIs P0: %d  P1: %d", len(stock_codes),
                len(config["priorities"]["P0"]), len(config["priorities"]["P1"]))

    collector = TushareCollector()

    # P0 — daily OHLCV / moneyflow
    logger.info("=== P0: daily price/volume/moneyflow ===")
    p0_stats = sync_priority(
        collector,
        config["priorities"]["P0"],
        stock_codes,
        trade_date,
        start_date,
        end_date,
    )

    # P1 — financial statements
    logger.info("=== P1: financial indicators / income / balance sheet ===")
    p1_stats = sync_priority(
        collector,
        config["priorities"]["P1"],
        stock_codes,
        trade_date,
        start_date,
        end_date,
    )

    # Summary
    logger.info("=== SYNC SUMMARY ===")
    for label, stats in [("P0", p0_stats), ("P1", p1_stats)]:
        for api_name, total in stats.items():
            logger.info("%s %s: %d rows", label, api_name, total)


# ---------------------------------------------------------------------------
# Self-test (limit to 3 stocks for speed)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick self-test mode: override stock list to 3 stocks
    if "--test" in sys.argv:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        config = load_config(CONFIG_PATH)
        all_stocks = load_stock_codes(STOCK_MASTER_PATH)
        stock_codes = all_stocks[:3]
        trade_date, start_date, end_date = date_range(DEFAULT_LOOKBACK_DAYS)

        logger.info("SELF-TEST MODE: %d/%d stocks, window %s→%s",
                    len(stock_codes), len(all_stocks), start_date, end_date)

        collector = TushareCollector()

        logger.info("=== P0 ===")
        p0_stats = sync_priority(
            collector, config["priorities"]["P0"], stock_codes,
            trade_date, start_date, end_date,
        )

        logger.info("=== P1 ===")
        p1_stats = sync_priority(
            collector, config["priorities"]["P1"], stock_codes,
            trade_date, start_date, end_date,
        )

        logger.info("=== SELF-TEST SUMMARY ===")
        for label, stats in [("P0", p0_stats), ("P1", p1_stats)]:
            for api_name, total in stats.items():
                logger.info("%s %s: %d rows", label, api_name, total)
    else:
        main()
