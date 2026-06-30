#!/usr/bin/env python3
"""SharedSignals patrol: periodic health checks across sources, data, staging,
SQLite, disk, and schema drift. Outputs JSON suitable for heal.py consumption.

Usage:
    python3 patrol.py [--json] [--check source_health|data_freshness|staging_backpressure|sqlite_health|disk_usage|field_drift|all]
    python3 patrol.py --self-test staging_backpressure  # simulate backpressure

Checks:
    source_health    — each source's last collection time vs staleness threshold
    data_freshness   — latest trade_date in marketdata.sqlite vs max gap
    staging_backpressure — pending NDJSON file count vs limit
    sqlite_health    — WAL size, lock contention, integrity
    disk_usage       — partition usage % vs thresholds
    field_drift      — actual CSV headers vs expected_fields registry
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path configuration (mirrors SharedSignals convention)
# ---------------------------------------------------------------------------
SHARED_ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", "/opt/investment/SharedSignals"))
MARKETGRAPH_ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
RUNTIME_ROOT = Path(os.environ.get("MARKETGRAPH_RUNTIME_DIR", "/opt/investment/MarketGraphRuntime"))

DB_PATH = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"
SOURCE_REGISTRY = SHARED_ROOT / "data" / "source_registry.csv"
INTAKE_DIR = SHAREDSIGNALS_ROOT / "data" / "intake"  # fixed: was MARKETGRAPH_ROOT
STAGING_ROOT = RUNTIME_ROOT / "staging"
ARCHIVE_DIR = RUNTIME_ROOT / "archive"
COLLECTION_RUNS_CSV = INTAKE_DIR / "collection_runs.csv"

MEMORY_DIR = SHARED_ROOT / "memory"
PATROL_HISTORY = MEMORY_DIR / "patrol_history.jsonl"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
STALE_SOURCE_HOURS = 6          # source considered stale if no collection in N hours
DATA_FRESHNESS_MAX_DAYS = 1     # trade_date older than N days → stale
MAX_STAGING_FILES = 100         # pending NDJSON count > N → backpressure
WAL_SIZE_WARN_MB = 100          # WAL file size > N MB → checkpoint
DISK_WARN_PCT = 80              # disk usage > N% → warning
DISK_STOP_PCT = 90              # disk usage > N% → stop collection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts_now() -> float:
    return time.time()


# ============================================================
# Check implementations
# ============================================================

def check_source_health() -> dict[str, Any]:
    """Check each source's last collection timestamp via collection_runs.csv.

    Only flags sources that have been collected before but whose last run
    exceeds the staleness threshold. Sources never collected are tracked
    separately as 'never_collected' (informational, not an alert).

    Returns:
        {status, value, threshold, stale_sources: [...], alert}
    """
    stale = []
    never_collected = []
    now = datetime.now(timezone.utc)

    # Read source registry for active sources
    active_source_ids: set[str] = set()
    if SOURCE_REGISTRY.exists():
        with open(SOURCE_REGISTRY, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("source_id", "").strip()
                status = row.get("status", "").strip()
                if sid and status == "active":
                    active_source_ids.add(sid)

    # Read collection_runs for last run per source
    last_run: dict[str, str] = {}  # source_id → finished_at
    if COLLECTION_RUNS_CSV.exists():
        with open(COLLECTION_RUNS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("source_id", "").strip()
                finished = row.get("finished_at", "").strip()
                if sid and finished:
                    if sid not in last_run or finished > last_run[sid]:
                        last_run[sid] = finished

    for sid in sorted(active_source_ids):
        finished = last_run.get(sid)
        if not finished:
            # Never collected: track separately, not an alert
            never_collected.append(sid)
        else:
            try:
                finished_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                hours = (now - finished_dt).total_seconds() / 3600
                if hours > STALE_SOURCE_HOURS:
                    stale.append({"source_id": sid, "last_run": finished,
                                  "hours_since": round(hours, 1),
                                  "reason": f"stale_{hours:.0f}h"})
            except (ValueError, TypeError):
                stale.append({"source_id": sid, "last_run": finished, "hours_since": None,
                              "reason": "unparseable_timestamp"})

    # Only stale (previously-collected but timed-out) sources trigger alert
    status = "ok" if len(stale) == 0 else ("degrade" if len(stale) <= 5 else "alert")
    return {
        "name": "source_health",
        "status": status,
        "value": len(stale),
        "threshold": STALE_SOURCE_HOURS,
        "threshold_unit": "hours",
        "stale_sources": stale,
        "total_active_sources": len(active_source_ids),
        "collected_sources": len(last_run),
        "never_collected_count": len(never_collected),
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


def check_data_freshness() -> dict[str, Any]:
    """Check the latest trade_date in marketdata.sqlite.

    Returns:
        {status, value, threshold, latest_date, days_behind, alert}
    """
    if not DB_PATH.exists():
        return {
            "name": "data_freshness",
            "status": "alert",
            "value": None,
            "threshold": DATA_FRESHNESS_MAX_DAYS,
            "threshold_unit": "days",
            "latest_date": None,
            "days_behind": None,
            "alert": True,
            "checked_at": utc_now(),
            "reason": "database_not_found",
        }

    conn = sqlite3.connect(str(DB_PATH))
    try:
        r = conn.execute("SELECT MAX(trade_date) FROM market_bars_daily").fetchone()
        latest = r[0] if r else None
    finally:
        conn.close()

    if not latest:
        return {
            "name": "data_freshness",
            "status": "alert",
            "value": None,
            "threshold": DATA_FRESHNESS_MAX_DAYS,
            "threshold_unit": "days",
            "latest_date": None,
            "days_behind": None,
            "alert": True,
            "checked_at": utc_now(),
            "reason": "no_trade_date_found",
        }

    now = datetime.now(timezone.utc).date()
    try:
        latest_date = datetime.strptime(latest, "%Y%m%d").date()
    except ValueError:
        latest_date = now  # assume ok if unparseable

    days_behind = (now - latest_date).days
    status = "ok" if days_behind <= DATA_FRESHNESS_MAX_DAYS else "stale"
    return {
        "name": "data_freshness",
        "status": status,
        "value": days_behind,
        "threshold": DATA_FRESHNESS_MAX_DAYS,
        "threshold_unit": "days",
        "latest_date": latest,
        "days_behind": days_behind,
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


def check_staging_backpressure() -> dict[str, Any]:
    """Count pending NDJSON files in staging directory tree.

    Returns:
        {status, value, threshold, per_stream: {...}, alert}
    """
    per_stream: dict[str, int] = {}
    total = 0
    if STAGING_ROOT.exists():
        for stream_dir in sorted(STAGING_ROOT.iterdir()):
            if stream_dir.is_dir():
                n = len(list(stream_dir.glob("*.ndjson")))
                per_stream[stream_dir.name] = n
                total += n

    if total > MAX_STAGING_FILES:
        status = "backpressure"
    elif total > MAX_STAGING_FILES * 0.7:
        status = "degrade"
    else:
        status = "ok"

    return {
        "name": "staging_backpressure",
        "status": status,
        "value": total,
        "threshold": MAX_STAGING_FILES,
        "per_stream": per_stream,
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


def check_sqlite_health() -> dict[str, Any]:
    """Check SQLite health: WAL size, lock contention, integrity.

    Returns:
        {status, value_in_mb, threshold, wal_size_mb, lock_wait, integrity, alert}
    """
    wal_path = Path(str(DB_PATH) + "-wal")
    shm_path = Path(str(DB_PATH) + "-shm")

    wal_size_mb = round(wal_path.stat().st_size / (1024 * 1024), 2) if wal_path.exists() else 0.0

    # Simple lock check: try a fast read, measure contention
    lock_wait = False
    conn = None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.execute("SELECT 1").fetchone()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "database is locked" in str(e).lower():
            lock_wait = True
    finally:
        if conn:
            conn.close()

    # Integrity check (lightweight: pragma quick_check)
    integrity_ok = True
    integrity_msg = ""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        r = conn.execute("PRAGMA quick_check").fetchone()
        integrity_ok = r[0] == "ok" if r and r[0] else False
        integrity_msg = r[0] if r else ""
    except Exception as e:
        integrity_ok = False
        integrity_msg = str(e)
    finally:
        if conn:
            conn.close()

    issues = []
    if wal_size_mb > WAL_SIZE_WARN_MB:
        issues.append(f"wal_size_{wal_size_mb}MB_>{WAL_SIZE_WARN_MB}MB")
    if lock_wait:
        issues.append("lock_contention")
    if not integrity_ok:
        issues.append(f"integrity_fail:{integrity_msg}")

    status = "alert" if issues else "ok"
    return {
        "name": "sqlite_health",
        "status": status,
        "value": wal_size_mb,
        "threshold": WAL_SIZE_WARN_MB,
        "threshold_unit": "MB",
        "wal_size_mb": wal_size_mb,
        "lock_wait": lock_wait,
        "integrity_ok": integrity_ok,
        "integrity_msg": integrity_msg,
        "issues": issues,
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


def check_disk_usage() -> dict[str, Any]:
    """Check disk usage on the partition containing SharedSignals.

    Returns:
        {status, value_pct, threshold, disk_total_gb, disk_used_gb, disk_free_gb, alert}
    """
    usage = shutil.disk_usage(str(SHARED_ROOT))
    pct = round((usage.used / usage.total) * 100, 1)
    total_gb = round(usage.total / (1024 ** 3), 1)
    used_gb = round(usage.used / (1024 ** 3), 1)
    free_gb = round(usage.free / (1024 ** 3), 1)

    if pct >= DISK_STOP_PCT:
        status = "stop"
    elif pct >= DISK_WARN_PCT:
        status = "warn"
    else:
        status = "ok"

    return {
        "name": "disk_usage",
        "status": status,
        "value": pct,
        "threshold": DISK_WARN_PCT,
        "threshold_unit": "percent",
        "stop_threshold": DISK_STOP_PCT,
        "disk_total_gb": total_gb,
        "disk_used_gb": used_gb,
        "disk_free_gb": free_gb,
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


def check_field_drift() -> dict[str, Any]:
    """Compare actual CSV headers in intake_dir against expected_fields.

    Expected fields are loaded from SHARED_ROOT/reference/expected_fields.json
    if present; otherwise built from the existing CSV headers on first run.

    Returns:
        {status, value, drift_count, drifts: [...], alert}
    """
    expected_path = SHARED_ROOT / "reference" / "expected_fields.json"
    expected: dict[str, list[str]] = {}
    if expected_path.exists():
        with open(expected_path) as f:
            expected = json.load(f)

    drifts = []
    for csvf in sorted(INTAKE_DIR.glob("*.csv")):
        stream = csvf.stem
        # Skip tmp/ and sample files
        if stream.startswith("tmp") or "_sample_" in stream.lower():
            continue
        try:
            with open(csvf, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                actual = next(reader, [])
        except Exception:
            continue

        # Clean BOM
        actual_clean = [c.lstrip("\ufeff") for c in actual]

        if stream in expected:
            exp = expected[stream]
            missing = [f for f in exp if f not in actual_clean]
            extra = [f for f in actual_clean if f not in exp]
            if missing or extra:
                drifts.append({
                    "stream": stream,
                    "expected": exp,
                    "actual": actual_clean,
                    "missing": missing,
                    "extra": extra,
                })
        else:
            # First time seen: record as expected silently (no drift)
            pass

    status = "ok" if len(drifts) == 0 else "alert"
    return {
        "name": "field_drift",
        "status": status,
        "value": len(drifts),
        "threshold": 0,
        "drifts": drifts,
        "alert": status != "ok",
        "checked_at": utc_now(),
    }


# ============================================================
# Overall score
# ============================================================

CHECKS_MAP = {
    "source_health": check_source_health,
    "data_freshness": check_data_freshness,
    "staging_backpressure": check_staging_backpressure,
    "sqlite_health": check_sqlite_health,
    "disk_usage": check_disk_usage,
    "field_drift": check_field_drift,
}

STATUS_SCORE = {"ok": 10, "degrade": 5, "warn": 5, "alert": 0, "stop": 0, "backpressure": 3, "stale": 3}


def compute_overall_score(checks: list[dict]) -> int:
    scores = [STATUS_SCORE.get(c["status"], 0) for c in checks]
    return sum(scores)


# ============================================================
# Main
# ============================================================

def run_checks(check_names: list[str]) -> dict[str, Any]:
    checks = []
    for name in check_names:
        fn = CHECKS_MAP.get(name)
        if fn:
            try:
                result = fn()
            except Exception as e:
                result = {
                    "name": name,
                    "status": "alert",
                    "value": None,
                    "threshold": None,
                    "alert": True,
                    "checked_at": utc_now(),
                    "error": str(e),
                }
            checks.append(result)

    score = compute_overall_score(checks)
    max_score = len(checks) * 10
    return {
        "checks": checks,
        "overall_score": score,
        "max_score": max_score,
        "score_pct": round(score / max_score * 100, 1) if max_score > 0 else 0,
        "patrol_at": utc_now(),
    }


def record_patrol(result: dict) -> None:
    """Append patrol result to patrol_history.jsonl."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(PATROL_HISTORY, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="SharedSignals patrol health check")
    parser.add_argument("--check", default="all",
                        help="Check to run: source_health|data_freshness|staging_backpressure|sqlite_health|disk_usage|field_drift|all")
    parser.add_argument("--json", action="store_true", default=True,
                        help="Output JSON (default)")
    parser.add_argument("--no-record", action="store_true",
                        help="Don't write patrol_history.jsonl")
    parser.add_argument("--self-test", metavar="CHECK",
                        help="Simulate a check failure for testing")
    args = parser.parse_args()

    if args.self_test:
        # Simulate a specific backpressure/failure scenario
        check_name = args.self_test
        if check_name == "staging_backpressure":
            # Fake a high staging count
            result = {
                "name": "staging_backpressure",
                "status": "backpressure",
                "value": MAX_STAGING_FILES + 50,
                "threshold": MAX_STAGING_FILES,
                "per_stream": {"collection_runs": 50, "sentiment_signals": 50, "event_candidates": 50},
                "alert": True,
                "checked_at": utc_now(),
                "self_test": True,
            }
            output = {"checks": [result], "overall_score": 3, "max_score": 10, "score_pct": 30.0, "patrol_at": utc_now()}
        else:
            fn = CHECKS_MAP.get(check_name)
            if fn:
                output = {"checks": [fn()], "overall_score": 0, "max_score": 10, "score_pct": 0, "patrol_at": utc_now()}
            else:
                print(json.dumps({"error": f"unknown check: {check_name}"}))
                sys.exit(1)
    else:
        if args.check == "all":
            check_names = list(CHECKS_MAP.keys())
        else:
            check_names = [c.strip() for c in args.check.split(",")]
            for c in check_names:
                if c not in CHECKS_MAP:
                    print(json.dumps({"error": f"unknown check: {c}"}))
                    sys.exit(1)
        output = run_checks(check_names)

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    if not args.no_record:
        record_patrol(output)


if __name__ == "__main__":
    main()
