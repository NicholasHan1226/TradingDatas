#!/usr/bin/env python3
"""SharedSignals source failover: switch stale/down sources to backup sources.

Usage:
    python3 source_failover.py --sources cn_cls_telegraph,cn_21jingji_news --action failover
    python3 source_failover.py --list-backups              # show all backup mappings
    python3 source_failover.py --source cn_cls_news --action status  # check status

The failover registry maps each primary source_id to one or more backup
source_ids. When a primary source goes stale, the backup is activated and
the change is recorded in memory/failover_history.jsonl.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SHARED_ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", "/opt/investment/SharedSignals"))
MARKETGRAPH_ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
SOURCE_REGISTRY = SHARED_ROOT / "data" / "source_registry.csv"
MEMORY_DIR = SHARED_ROOT / "memory"
FAILOVER_HISTORY = MEMORY_DIR / "failover_history.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Failover registry: primary → [backup_source_ids]
#
# These are curated mappings based on source_registry.csv analysis.
# Backup sources should:
#   - Cover similar market scope (cn / global / us / crypto / pm)
#   - Have equal or lower trust_tier (S > A > B > C)
#   - Be active (status=active)
# ---------------------------------------------------------------------------

FAILOVER_MAP: dict[str, list[str]] = {
    # Tushare data - fallback to other Tushare endpoints or slower alternatives
    "cn_quicksync_tushare": ["cn_cninfo_announcements"],  # A股行情→公告

    # RSS Chinese news feeds - cross-fallback within same tier
    "cn_cls_telegraph": ["cn_cls_news"],          # 财联社电报→财联社新闻
    "cn_cls_news": ["cn_cls_telegraph", "cn_yicai_news"],
    "cn_yicai_news": ["cn_21jingji_news", "cn_stcn_news"],
    "cn_21jingji_news": ["cn_yicai_news", "cn_cnstock_news"],
    "cn_stcn_news": ["cn_cnstock_news", "cn_cs_news"],
    "cn_cnstock_news": ["cn_stcn_news", "cn_cs_news"],
    "cn_cs_news": ["cn_cnstock_news", "cn_stcn_news"],
    "cn_sina_finance": ["cn_cls_news", "cn_yicai_news"],

    # Global news
    "cn_bjnews_news": ["cn_yicai_news", "cn_21jingji_news"],
    "cn_cena_news": ["cn_21jingji_news", "cn_yicai_news"],

    # Exchange disclosures - fallback to umbrella
    "cn_sse_disclosure": ["cn_exchange_disclosure"],
    "cn_szse_disclosure": ["cn_exchange_disclosure"],
    "cn_bse_disclosure": ["cn_exchange_disclosure"],
    "cn_csrc_disclosure": ["cn_exchange_disclosure"],

    # Cross-market
    "hk_exchange_disclosure": ["cn_exchange_disclosure"],  # 港股公告→A股公告(间接)
    "us_sec_edgar": ["us_federal_reserve"],
    "us_federal_reserve": ["us_white_house"],
    "us_white_house": ["us_federal_reserve"],
    "us_ustr": ["us_white_house"],
    "us_fda": ["us_federal_reserve"],
    "us_defense": ["us_white_house"],

    # EU/UK
    "eu_commission": ["eu_council"],
    "eu_council": ["eu_commission"],
    "uk_gov": ["eu_commission"],
}


def load_source_registry() -> dict[str, dict]:
    """Load source_registry.csv into a dict keyed by source_id."""
    registry: dict[str, dict] = {}
    if not SOURCE_REGISTRY.exists():
        return registry
    with open(SOURCE_REGISTRY, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("source_id", "").strip()
            if sid:
                registry[sid] = row
    return registry


def get_backup(sid: str) -> list[str]:
    """Get backup source IDs for a primary source."""
    # Check exact match first
    if sid in FAILOVER_MAP:
        return FAILOVER_MAP[sid]

    # Check for partial matches (e.g., RSS feed IDs may vary)
    for pattern, backups in FAILOVER_MAP.items():
        if pattern in sid or sid in pattern:
            return backups

    return []


def failover(sources: list[str]) -> list[dict]:
    """Execute failover for a list of stale source IDs.

    For each source, finds backup(s), checks they're active, and records the switch.
    Returns a list of actions taken.
    """
    registry = load_source_registry()
    actions = []

    for sid in sources:
        current = registry.get(sid, {})
        current_status = current.get("status", "unknown")
        backups = get_backup(sid)

        action: dict = {
            "source_id": sid,
            "source_name": current.get("source_name", ""),
            "action": "failover",
            "executed_at": utc_now(),
            "previous_status": current_status,
        }

        if not backups:
            action["status"] = "no_backup"
            action["reason"] = "no_failover_mapping"
            actions.append(action)
            continue

        # Filter to active backups
        active_backups = [
            b for b in backups
            if registry.get(b, {}).get("status", "") == "active"
        ]

        if not active_backups:
            action["status"] = "no_active_backup"
            action["reason"] = f"all_backups_inactive: {backups}"
            action["attempted_backups"] = backups
            actions.append(action)
            continue

        action["status"] = "failed_over"
        action["backup_source_id"] = active_backups[0]
        action["backup_source_name"] = registry.get(active_backups[0], {}).get("source_name", "")
        action["all_backups"] = active_backups

        actions.append(action)

    # Record history + update source registry
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    for action in actions:
        with open(FAILOVER_HISTORY, "a") as f:
            f.write(json.dumps(action, ensure_ascii=False) + "\n")

    # Update source_registry.csv: deactivate stale sources, activate backups
    _update_registry(actions)

    return actions


def _update_registry(actions: list[dict]) -> None:
    """Deactivate stale sources and activate backup sources in source_registry.csv."""
    if not SOURCE_REGISTRY.exists():
        return

    rows: list[dict] = []
    with open(SOURCE_REGISTRY, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    stale_ids = {a["source_id"] for a in actions if a["status"] == "failed_over"}
    backup_ids = {a["backup_source_id"] for a in actions if a["status"] == "failed_over"}

    for row in rows:
        sid = row.get("source_id", "").strip()
        if sid in stale_ids:
            row["status"] = "failover"
        elif sid in backup_ids:
            row["status"] = "active"

    with open(SOURCE_REGISTRY, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def list_backups() -> dict:
    """Return the full failover registry."""
    registry = load_source_registry()
    result = {}
    for primary, backups in FAILOVER_MAP.items():
        primary_info = registry.get(primary, {})
        result[primary] = {
            "name": primary_info.get("source_name", ""),
            "status": primary_info.get("status", ""),
            "backups": [
                {"id": b, "name": registry.get(b, {}).get("source_name", ""),
                 "status": registry.get(b, {}).get("status", "")}
                for b in backups
            ],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description="SharedSignals source failover")
    parser.add_argument("--sources", help="Comma-separated source IDs to failover")
    parser.add_argument("--action", default="failover",
                        choices=["failover", "status", "list"])
    parser.add_argument("--list-backups", action="store_true",
                        help="Show all backup mappings")
    parser.add_argument("--source", help="Single source to check status")
    args = parser.parse_args()

    if args.list_backups:
        backups = list_backups()
        print(json.dumps(backups, ensure_ascii=False, indent=2))
        return

    if args.action == "status" and args.source:
        registry = load_source_registry()
        info = registry.get(args.source, {})
        backups = get_backup(args.source)
        backup_info = [
            {"id": b, "name": registry.get(b, {}).get("source_name", ""),
             "status": registry.get(b, {}).get("status", "")}
            for b in backups
        ]
        output = {"source_id": args.source, "info": info, "backups": backup_info}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if args.sources:
        sources = [s.strip() for s in args.sources.split(",")]
        actions = failover(sources)
        print(json.dumps({"failover_actions": actions}, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
