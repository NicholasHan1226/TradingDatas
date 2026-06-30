#!/usr/bin/env python3
"""Data retention manager for SharedSignals collected Tushare data.

Scans data/tushare/ directory tree, classifies API directories by retention
policy, deletes expired files, and archives hot data to Parquet cold storage.

Retention policies:
  trading   — daily, moneyflow, stk_factor, adj_factor, stk_mins, etc.
              keep 2 years hot, archive older to Parquet
  financial — fina_indicator, income, balancesheet, cashflow, etc.
              keep 10 years
  reference — stock_basic, stock_company, concept, etc.
              keep forever
  macro     — cn_cpi, cn_pmi, shibor, etc.
              keep 10 years
  hk_us     — hk_daily, us_daily
              keep 2 years hot, archive older to Parquet
  other     — fut_daily, fund_basic, news, etc.
              keep 2 years hot, archive older to Parquet

Usage:
  python3 storage/retention.py --dry-run          # report what would be done
  python3 storage/retention.py --execute          # actually delete/archive
  python3 storage/retention.py --dry-run --json   # machine-readable report
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INVESTMENT_ROOT = Path(os.environ.get("INVESTMENT_ROOT", "/opt/investment"))
SHAREDSIGNALS_ROOT = Path(
    os.environ.get("SHAREDSIGNALS_ROOT", INVESTMENT_ROOT / "SharedSignals")
)
TUSHARE_DATA_ROOT = SHAREDSIGNALS_ROOT / "data" / "tushare"
COLD_DIR = SHAREDSIGNALS_ROOT / "storage" / "cold"

# Retention classification by API name.
# Each entry: (category, keep_hot_years)
# Categories: trading, financial, reference, macro, hk_us, other

RETENTION_POLICY: dict[str, tuple[str, int]] = {
    # --- trading (2 years hot) ---
    "daily": ("trading", 2),
    "daily_basic": ("trading", 2),
    "stk_factor": ("trading", 2),
    "adj_factor": ("trading", 2),
    "stk_mins": ("trading", 2),
    "moneyflow": ("trading", 2),
    "moneyflow_hsgt": ("trading", 2),
    "margin_detail": ("trading", 2),
    "limit_list": ("trading", 2),
    "top_list": ("trading", 2),
    "block_trade": ("trading", 2),
    "stk_auction": ("trading", 2),
    "stk_limit": ("trading", 2),
    "index_daily": ("trading", 2),
    "fund_daily": ("trading", 2),
    # --- financial (10 years) ---
    "fina_indicator": ("financial", 10),
    "income": ("financial", 10),
    "balancesheet": ("financial", 10),
    "cashflow": ("financial", 10),
    "forecast": ("financial", 10),
    "express": ("financial", 10),
    "dividend": ("financial", 10),
    # --- reference (forever) ---
    "stock_basic": ("reference", 0),
    "stock_company": ("reference", 0),
    "concept": ("reference", 0),
    "concept_detail": ("reference", 0),
    "hs_const": ("reference", 0),
    "index_basic": ("reference", 0),
    "index_weight": ("reference", 0),
    "margin_secs": ("reference", 0),
    "stk_holdernumber": ("reference", 0),
    # --- macro (10 years) ---
    "cn_cpi": ("macro", 10),
    "cn_pmi": ("macro", 10),
    "cn_m": ("macro", 10),
    "cn_ppi": ("macro", 10),
    "shibor": ("macro", 10),
    "shibor_lpr": ("macro", 10),
    "cn_gdp": ("macro", 10),
    "sf_month": ("macro", 10),
    # --- hk_us (2 years hot) ---
    "hk_daily": ("hk_us", 2),
    "us_daily": ("hk_us", 2),
    "hk_basic": ("hk_us", 2),
    "us_basic": ("hk_us", 2),
    # --- other (2 years hot) ---
    "fut_daily": ("other", 2),
    "fund_basic": ("other", 2),
    "etf_basic": ("other", 2),
    "cb_daily": ("other", 2),
    "news": ("other", 2),
    "major_news": ("other", 2),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date_dir(dirname: str) -> datetime | None:
    """Parse a YYYYMMDD directory name to datetime."""
    if len(dirname) == 8 and dirname.isdigit():
        try:
            return datetime.strptime(dirname, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _archive_to_parquet(api_name: str, date_dir: Path, dry_run: bool = True) -> bool:
    """Archive a date-partitioned CSV directory to Parquet in cold storage."""
    dest_dir = COLD_DIR / api_name
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(date_dir.glob("*.csv"))
    if not csv_files:
        return False

    if dry_run:
        return True

    try:
        import duckdb
        con = duckdb.connect()
        for csv_file in csv_files:
            parquet_name = csv_file.stem + ".parquet"
            parquet_path = dest_dir / parquet_name
            con.execute(
                f"COPY (SELECT * FROM read_csv_auto({csv_file})) "
                f"TO {parquet_path} (FORMAT PARQUET)"
            )
            logger.info("archived %s -> %s", csv_file.name, parquet_path)
        con.close()
        return True
    except ImportError:
        logger.warning("duckdb not installed, skipping Parquet archive for %s", api_name)
        return False
    except Exception as exc:
        logger.error("archive failed for %s/%s: %s", api_name, date_dir.name, exc)
        return False


def _delete_date_dir(date_dir: Path, dry_run: bool = True) -> bool:
    """Delete a date-partitioned directory."""
    if dry_run:
        return True
    try:
        shutil.rmtree(date_dir)
        logger.info("deleted %s", date_dir)
        return True
    except Exception as exc:
        logger.error("delete failed for %s: %s", date_dir, exc)
        return False


def scan_and_retain(dry_run: bool = True) -> dict[str, Any]:
    """Scan data/tushare/ and apply retention policies.

    Returns a report dict with counts by category.
    """
    if not TUSHARE_DATA_ROOT.exists():
        return {"error": f"TUSHARE_DATA_ROOT not found: {TUSHARE_DATA_ROOT}", "dry_run": dry_run}

    now = _now()
    report = {
        "scan_time": now.isoformat(),
        "dry_run": dry_run,
        "categories": {},
        "total_expired_dirs": 0,
        "total_deleted": 0,
        "total_archived": 0,
        "errors": [],
    }

    for api_dir in sorted(TUSHARE_DATA_ROOT.iterdir()):
        if not api_dir.is_dir():
            continue

        api_name = api_dir.name
        policy = RETENTION_POLICY.get(api_name)

        if policy is None:
            # Unknown API: skip
            continue

        category, keep_hot_years = policy

        if category not in report["categories"]:
            report["categories"][category] = {
                "keep_years": keep_hot_years if category != "reference" else None,
                "api_count": 0,
                "expired_dirs": 0,
                "deleted": 0,
                "archived": 0,
                "kept": 0,
            }
        report["categories"][category]["api_count"] += 1

        # Reference data: keep forever, skip deletion
        if category == "reference" or keep_hot_years == 0:
            for date_dir in sorted(api_dir.iterdir()):
                if date_dir.is_dir() and _parse_date_dir(date_dir.name):
                    report["categories"][category]["kept"] += 1
            continue

        cutoff = now - timedelta(days=keep_hot_years * 365)

        for date_dir in sorted(api_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            date_dt = _parse_date_dir(date_dir.name)
            if date_dt is None:
                continue

            if date_dt < cutoff:
                report["categories"][category]["expired_dirs"] += 1
                report["total_expired_dirs"] += 1

                # Archive to Parquet before deleting (trading/hk_us/other)
                if category in ("trading", "hk_us", "other"):
                    archived = _archive_to_parquet(api_name, date_dir, dry_run)
                    if archived:
                        report["categories"][category]["archived"] += 1
                        report["total_archived"] += 1
                    else:
                        report["errors"].append(
                            f"archive failed: {api_name}/{date_dir.name}"
                        )

                deleted = _delete_date_dir(date_dir, dry_run)
                if deleted:
                    report["categories"][category]["deleted"] += 1
                    report["total_deleted"] += 1
                else:
                    report["errors"].append(
                        f"delete failed: {api_name}/{date_dir.name}"
                    )
            else:
                report["categories"][category]["kept"] += 1

    return report


def main():
    parser = argparse.ArgumentParser(
        description="SharedSignals data retention manager"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report what would be done (default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete/archive files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON",
    )
    args = parser.parse_args()

    dry_run = not args.execute
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    report = scan_and_retain(dry_run=dry_run)

    if args.json:
        print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    else:
        mode = "DRY RUN" if dry_run else "EXECUTE"
        print(f"SharedSignals Retention Report ({mode})")
        print(f"  Scan time: {report[scan_time]}")
        print(f"  Expired dirs: {report[total_expired_dirs]}")
        print(f"  To delete: {report[total_deleted]}")
        print(f"  To archive: {report[total_archived]}")
        if report.get("errors"):
            print(f"  Errors: {len(report[errors])}")
            for err in report["errors"][:10]:
                print(f"    - {err}")
        print()
        for cat, info in sorted(report.get("categories", {}).items()):
            keep = f"{info[keep_years]}y" if info["keep_years"] else "forever"
            print(
                f"  {cat:12s} keep={keep:8s} apis={info[api_count]:2d} "
                f"expired={info[expired_dirs]:3d} "
                f"deleted={info[deleted]:3d} "
                f"archived={info[archived]:3d} "
                f"kept={info[kept]:3d}"
            )


if __name__ == "__main__":
    main()
