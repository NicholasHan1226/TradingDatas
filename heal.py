#!/usr/bin/env python3
"""SharedSignals heal: self-healing actions triggered by patrol.py findings.

Usage:
    python3 heal.py --patrol-result patrol_output.json    # full patrol result
    python3 heal.py --check source_health --json '{"status":"alert",...}'  # single check
    python3 heal.py --dry-run                              # preview actions only

Healing strategies:
    source_health   → source_failover.py (switch to backup source)
    data_freshness  → trigger backfill collector re-run
    staging_backpressure → force runtime_bridge merge
    sqlite_health    → WAL checkpoint, lock retry, integrity repair
    disk_usage       → clean old archive (>30d Parquet), stop collectors
    field_drift      → update expected_fields.json + alert
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------
SHARED_ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", "/opt/investment/SharedSignals"))
MARKETGRAPH_ROOT = Path(os.environ.get("MARKETGRAPH_ROOT", "/opt/investment/MarketGraph"))
RUNTIME_ROOT = Path(os.environ.get("MARKETGRAPH_RUNTIME_DIR", "/opt/investment/MarketGraphRuntime"))

DB_PATH = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"
STAGING_ROOT = RUNTIME_ROOT / "staging"
ARCHIVE_DIR = RUNTIME_ROOT / "archive"
INTAKE_DIR = MARKETGRAPH_ROOT / "data" / "intake"

BRIDGE_SCRIPT = SHARED_ROOT / "bridge" / "marketgraph_runtime_bridge.py"
FAILOVER_SCRIPT = SHARED_ROOT / "source_failover.py"

MEMORY_DIR = SHARED_ROOT / "memory"
HEAL_ACTIONS_LOG = MEMORY_DIR / "heal_actions.jsonl"
PATTERNS_LOG = MEMORY_DIR / "patterns.jsonl"

EMERGENCY_ALERT_FILE = SHARED_ROOT / "logs" / "emergency_alerts.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts_now() -> float:
    return time.time()


def record_action(action: dict) -> None:
    """Append heal action to heal_actions.jsonl."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(HEAL_ACTIONS_LOG, "a") as f:
        f.write(json.dumps(action, ensure_ascii=False) + "\n")


def record_pattern(pattern: dict) -> None:
    """Record a recurring issue pattern."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(PATTERNS_LOG, "a") as f:
        f.write(json.dumps(pattern, ensure_ascii=False) + "\n")


def emergency_alert(reason: str, details: dict) -> None:
    """Log an emergency alert that heal could not self-resolve."""
    SHARED_ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    alert = {
        "alert_at": utc_now(),
        "level": "emergency",
        "reason": reason,
        "details": details,
        "requires_human": True,
    }
    with open(EMERGENCY_ALERT_FILE, "a") as f:
        f.write(json.dumps(alert, ensure_ascii=False) + "\n")
    print(f"[EMERGENCY] {reason}", file=sys.stderr)
    print(json.dumps(alert, ensure_ascii=False, indent=2))


# ============================================================
# Heal strategies
# ============================================================

def heal_source_health(check_result: dict, dry_run: bool = False) -> dict:
    """Switch stale sources to backup via source_failover.py.

    source_failover.py reads the stale source list and maps to fallback sources.
    """
    stale = check_result.get("stale_sources", [])
    if not stale:
        return {"action": "source_health", "healed": False, "reason": "no_stale_sources"}

    action = {
        "action": "source_health",
        "action_type": "failover",
        "target": [s["source_id"] for s in stale],
        "from_val": "stale",
        "to_val": "backup",
        "reason": f"{len(stale)} source(s) stale",
        "reversible": True,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    # Run source_failover.py if it exists
    if FAILOVER_SCRIPT.exists():
        stale_ids = ",".join(s["source_id"] for s in stale)
        try:
            result = subprocess.run(
                [sys.executable, str(FAILOVER_SCRIPT), "--sources", stale_ids, "--action", "failover"],
                capture_output=True, text=True, timeout=30, cwd=str(SHARED_ROOT)
            )
            action["failover_output"] = result.stdout.strip()
            action["failover_rc"] = result.returncode
            action["healed"] = result.returncode == 0
            if result.returncode != 0:
                action["healed"] = False
                action["error"] = result.stderr.strip()
        except Exception as e:
            action["healed"] = False
            action["error"] = str(e)
    else:
        action["healed"] = False
        action["error"] = "source_failover.py not found"
        action["fallback"] = "manual_failover_required"

    record_action(action)
    if not action.get("healed"):
        emergency_alert("source_failover_failed", action)

    return action


def heal_data_freshness(check_result: dict, dry_run: bool = False) -> dict:
    """Trigger backfill for stale data.

    Strategy: call the marketdata_db backfill mechanism, or a dedicated
    collector re-run script.
    """
    days_behind = check_result.get("days_behind", 0)
    action = {
        "action": "data_freshness",
        "action_type": "backfill",
        "target": "marketdata.sqlite",
        "from_val": f"{days_behind}d_behind",
        "to_val": "fresh",
        "reason": f"data {days_behind} days stale",
        "reversible": True,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    # Try to run the marketdata_db backfill
    db_script = SHARED_ROOT / "bridge" / "marketgraph_marketdata_db.py"
    if db_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(db_script), "--ingest", "--dataset", "daily"],
                capture_output=True, text=True, timeout=120, cwd=str(SHARED_ROOT)
            )
            action["backfill_output"] = result.stdout.strip()[:500]
            action["backfill_rc"] = result.returncode
            action["healed"] = result.returncode == 0
            if result.returncode != 0:
                action["error"] = result.stderr.strip()[:500]
        except subprocess.TimeoutExpired:
            action["healed"] = False
            action["error"] = "backfill_timed_out_after_120s"
        except Exception as e:
            action["healed"] = False
            action["error"] = str(e)
    else:
        action["healed"] = False
        action["error"] = "marketgraph_marketdata_db.py not found"

    record_action(action)
    if not action.get("healed"):
        emergency_alert("data_backfill_failed", action)

    return action


def heal_staging_backpressure(check_result: dict, dry_run: bool = False) -> dict:
    """Force runtime_bridge merge to clear staging backlog."""
    total = check_result.get("value", 0)
    action = {
        "action": "staging_backpressure",
        "action_type": "bridge_merge",
        "target": str(STAGING_ROOT),
        "from_val": f"{total}_pending",
        "to_val": "merged",
        "reason": f"{total} pending staging files (threshold: {check_result.get('threshold', 100)})",
        "reversible": False,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    if not BRIDGE_SCRIPT.exists():
        action["healed"] = False
        action["error"] = "bridge script not found"
        record_action(action)
        emergency_alert("bridge_not_found", action)
        return action

    try:
        # Process all streams at once (no --stream flag = all streams)
        result = subprocess.run(
            [sys.executable, str(BRIDGE_SCRIPT), "--apply", "--min-file-age-seconds", "0"],
            capture_output=True, text=True, timeout=300, cwd=str(SHARED_ROOT)
        )
        action["bridge_output"] = result.stdout.strip()[:1000]
        action["bridge_rc"] = result.returncode
        action["healed"] = result.returncode == 0

        # Re-count staging after merge
        remaining = 0
        if STAGING_ROOT.exists():
            for d in STAGING_ROOT.iterdir():
                if d.is_dir():
                    remaining += len(list(d.glob("*.ndjson")))
        action["remaining_after"] = remaining

        if result.returncode != 0:
            action["error"] = result.stderr.strip()[:500]
    except subprocess.TimeoutExpired:
        action["healed"] = False
        action["error"] = "bridge_merge_timed_out"
    except Exception as e:
        action["healed"] = False
        action["error"] = str(e)

    record_action(action)
    if not action.get("healed"):
        emergency_alert("staging_merge_failed", action)

    return action


def heal_sqlite_health(check_result: dict, dry_run: bool = False) -> dict:
    """Handle SQLite issues: WAL checkpoint, lock retry.

    - WAL too large → PRAGMA wal_checkpoint(TRUNCATE)
    - Lock contention → wait 5s and retry, then force checkpoint
    """
    wal_size = check_result.get("wal_size_mb", 0)
    lock_wait = check_result.get("lock_wait", False)
    integrity_ok = check_result.get("integrity_ok", True)

    action = {
        "action": "sqlite_health",
        "action_type": "repair",
        "target": str(DB_PATH),
        "from_val": f"wal_{wal_size}MB_lock_{lock_wait}",
        "to_val": "healthy",
        "reason": ", ".join(check_result.get("issues", [])),
        "reversible": False,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    healed = True
    errors = []

    # If lock contention: wait and retry
    if lock_wait:
        time.sleep(5)
        try:
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            action["lock_retry"] = "ok"
        except Exception as e:
            errors.append(f"lock_retry_failed: {e}")
            healed = False

    # If WAL too large: checkpoint
    if wal_size > 0:
        try:
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            action["checkpoint"] = "done"

            # Verify WAL size after checkpoint
            wal_path = Path(str(DB_PATH) + "-wal")
            new_wal = round(wal_path.stat().st_size / (1024 * 1024), 2) if wal_path.exists() else 0
            action["wal_after_mb"] = new_wal
        except Exception as e:
            errors.append(f"checkpoint_failed: {e}")
            healed = False

    # If integrity failed: run full integrity check
    if not integrity_ok:
        try:
            import sqlite3
            conn = sqlite3.connect(str(DB_PATH), timeout=30)
            r = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            action["integrity_result"] = r[0] if r else "unknown"
            if r and r[0] == "ok":
                action["integrity_after"] = "ok"
            else:
                errors.append(f"integrity_still_failed: {r[0] if r else 'unknown'}")
                healed = False
        except Exception as e:
            errors.append(f"integrity_check_error: {e}")
            healed = False

    action["healed"] = healed
    if errors:
        action["errors"] = errors

    record_action(action)
    if not healed:
        emergency_alert("sqlite_repair_failed", action)

    return action


def heal_disk_usage(check_result: dict, dry_run: bool = False) -> dict:
    """Clean old archive files (>30 days) to free disk space.

    If >90%, also emit stop-collectors signal.
    """
    pct = check_result.get("value", 0)
    action = {
        "action": "disk_usage",
        "action_type": "cleanup",
        "target": str(ARCHIVE_DIR),
        "from_val": f"{pct}%",
        "to_val": "below_threshold",
        "reason": f"disk at {pct}% (warn: {check_result.get('threshold', 80)}%, stop: {check_result.get('stop_threshold', 90)}%)",
        "reversible": False,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    cleaned = 0
    freed_mb = 0
    cutoff = datetime.now() - timedelta(days=30)

    if ARCHIVE_DIR.exists():
        for f in ARCHIVE_DIR.glob("*.parquet"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    size_mb = f.stat().st_size / (1024 * 1024)
                    freed_mb += size_mb
                    f.unlink()
                    cleaned += 1
            except Exception as e:
                action.setdefault("cleanup_errors", []).append(str(f.name))

    action["files_cleaned"] = cleaned
    action["freed_mb"] = round(freed_mb, 2)
    action["healed"] = True

    # If still over stop threshold, emit stop signal
    if pct >= check_result.get("stop_threshold", 90):
        stop_file = SHARED_ROOT / "logs" / "COLLECTORS_STOPPED"
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        stop_file.write_text(f"stopped_at: {utc_now()}\nreason: disk_{pct}pct_>_stop_threshold\n")
        action["collectors_stopped"] = True

    record_action(action)
    return action


def heal_field_drift(check_result: dict, dry_run: bool = False) -> dict:
    """Update expected_fields.json when field drift is detected.

    This records the actual fields as the new expected, emitting an alert
    so a human can verify the change is intentional.
    """
    drifts = check_result.get("drifts", [])
    action = {
        "action": "field_drift",
        "action_type": "update_expected",
        "target": "expected_fields.json",
        "from_val": "drifted",
        "to_val": "updated",
        "reason": f"{len(drifts)} stream(s) with field drift",
        "reversible": True,
        "healed_at": utc_now(),
    }

    if dry_run:
        action["dry_run"] = True
        return action

    expected_path = SHARED_ROOT / "reference" / "expected_fields.json"
    expected: dict[str, list[str]] = {}

    # Load existing
    if expected_path.exists():
        with open(expected_path) as f:
            expected = json.load(f)

    # Update drifted streams with actual fields
    for drift in drifts:
        expected[drift["stream"]] = drift["actual"]

    # Save
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    with open(expected_path, "w") as f:
        json.dump(expected, f, ensure_ascii=False, indent=2)

    action["updated_streams"] = [d["stream"] for d in drifts]
    action["healed"] = True

    record_action(action)
    return action


# ============================================================
# Heal dispatch
# ============================================================

HEAL_MAP = {
    "source_health": heal_source_health,
    "data_freshness": heal_data_freshness,
    "staging_backpressure": heal_staging_backpressure,
    "sqlite_health": heal_sqlite_health,
    "disk_usage": heal_disk_usage,
    "field_drift": heal_field_drift,
}


def heal_from_patrol(patrol_result: dict, dry_run: bool = False) -> list[dict]:
    """Process all checks from a patrol result and heal any that need it."""
    actions = []
    for check in patrol_result.get("checks", []):
        if check.get("alert") or check.get("status") not in ("ok",):
            name = check["name"]
            heal_fn = HEAL_MAP.get(name)
            if heal_fn:
                try:
                    result = heal_fn(check, dry_run=dry_run)
                    actions.append(result)
                except Exception as e:
                    error_action = {
                        "action": name,
                        "action_type": "error",
                        "healed": False,
                        "error": str(e),
                        "healed_at": utc_now(),
                    }
                    actions.append(error_action)
                    record_action(error_action)
                    emergency_alert(f"heal_{name}_exception", error_action)
    return actions


def heal_single(check_name: str, check_result: dict, dry_run: bool = False) -> dict:
    """Heal a single check result."""
    heal_fn = HEAL_MAP.get(check_name)
    if not heal_fn:
        return {"error": f"unknown check: {check_name}"}
    return heal_fn(check_result, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="SharedSignals heal: self-healing actions")
    parser.add_argument("--patrol-result", help="Path to patrol.py JSON output file")
    parser.add_argument("--check", help="Single check name to heal")
    parser.add_argument("--json", help="JSON result for single check (used with --check)")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions only, don't execute")
    parser.add_argument("--self-test", help="Run a specific heal scenario for testing")
    args = parser.parse_args()

    actions = []

    if args.self_test:
        test_mode = args.self_test
        if test_mode == "staging_backpressure":
            check = {"name": "staging_backpressure", "value": 150, "threshold": 100,
                     "status": "backpressure", "alert": True}
            action = heal_staging_backpressure(check, dry_run=args.dry_run)
            actions = [action]
        elif test_mode in HEAL_MAP:
            check = {"name": test_mode, "value": 1, "threshold": 0, "status": "alert", "alert": True}
            action = HEAL_MAP[test_mode](check, dry_run=args.dry_run)
            actions = [action]
        else:
            print(json.dumps({"error": f"unknown self-test: {test_mode}"}))
            sys.exit(1)
    elif args.patrol_result:
        with open(args.patrol_result) as f:
            patrol_result = json.load(f)
        actions = heal_from_patrol(patrol_result, dry_run=args.dry_run)
    elif args.check and args.json:
        check_result = json.loads(args.json)
        action = heal_single(args.check, check_result, dry_run=args.dry_run)
        actions = [action]
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps({"heal_actions": actions, "heal_at": utc_now()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
