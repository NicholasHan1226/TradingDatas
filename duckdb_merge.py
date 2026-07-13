#!/usr/bin/env python3
"""DuckDB merge worker — periodically syncs SQLite (authoritative) to DuckDB (analytics).

Usage:
    python3 duckdb_merge.py                  # sync all tables once
    python3 duckdb_merge.py --table market_bars_daily  # sync single table
    python3 duckdb_merge.py --loop 300       # sync every 300s
    python3 duckdb_merge.py --dry-run        # preview without writing

Designed to run as a cron job or long-lived sidecar process.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure SharedSignals is on path for imports
_THIS = Path(__file__).resolve().parent
if str(_THIS) not in sys.path:
    sys.path.insert(0, str(_THIS))

from storage.storage_adapter import StorageAdapter
from storage.sqlite_snapshot import SQLiteSnapshotError, create_sqlite_snapshot

logger = logging.getLogger("duckdb_merge")
LOG_DIR = _THIS / "logs"
MERGE_LOG = LOG_DIR / "duckdb_merge.jsonl"
STATUS_PATH = Path(os.environ.get("WATCHDOG_INPUT_DIR", LOG_DIR / "watchdog_inputs")) / "duckdb_sync.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _with_diagnostic_continuity(result: dict) -> dict:
    enriched = dict(result)
    previous: dict = {}
    try:
        previous = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        previous = {}

    merge_at = str(enriched.get("merge_at") or utc_now())
    recent_failures = list(previous.get("recent_failures") or [])[-9:]
    status = enriched.get("status")
    if status == "ok":
        enriched["consecutive_failure_count"] = 0
        enriched["last_success_at"] = merge_at
        enriched["last_failure_at"] = previous.get("last_failure_at")
    elif status in {"error", "failed"}:
        enriched["consecutive_failure_count"] = int(
            previous.get("consecutive_failure_count") or 0
        ) + 1
        enriched["last_success_at"] = previous.get("last_success_at")
        enriched["last_failure_at"] = merge_at
        recent_failures.append({
            "at": merge_at,
            "error_class": enriched.get("error_class", "merge_failed"),
            "error": enriched.get("error", ""),
        })
    else:
        enriched["consecutive_failure_count"] = int(
            previous.get("consecutive_failure_count") or 0
        )
        enriched["last_success_at"] = previous.get("last_success_at")
        enriched["last_failure_at"] = previous.get("last_failure_at")
    enriched["recent_failures"] = recent_failures
    return enriched


def record_result(result: dict) -> None:
    result = _with_diagnostic_continuity(result)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(MERGE_LOG, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATUS_PATH.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATUS_PATH)


def run_merge(
    adapter: StorageAdapter | None = None,
    table: str = "",
    dry_run: bool = False,
) -> dict:
    """Run one merge cycle. Returns result dict."""
    started = time.monotonic()
    result = {
        "merge_at": utc_now(),
        "table": table or "all",
        "dry_run": dry_run,
        "results": {},
        "elapsed_s": 0,
        "status": "ok",
        "error": "",
    }

    if dry_run:
        result["status"] = "dry_run"
        result["message"] = "dry run — no data written"
        return result

    issues: list[dict[str, str]] = []
    source_snapshot = None

    if adapter is None:
        live_adapter = StorageAdapter()
        try:
            from storage.duckdb_schema import TABLE_NAMES

            source_snapshot = create_sqlite_snapshot(
                live_adapter.sqlite_path,
                required_tables=TABLE_NAMES,
                working_paths=[Path(live_adapter.duckdb_path).parent],
            )
            result["source_snapshot"] = source_snapshot.metadata
            adapter = StorageAdapter(
                sqlite_path=str(source_snapshot.path),
                duckdb_path=str(live_adapter.duckdb_path),
            )
        except SQLiteSnapshotError as exc:
            logger.exception("source snapshot failed")
            result["status"] = "error"
            result["error_class"] = exc.error_class
            result["source_snapshot"] = exc.metadata
            result["errors"] = [{
                "stage": "snapshot",
                "error_class": exc.error_class,
                "message": str(exc),
            }]
            result["error_classes"] = [exc.error_class]
            result["error"] = str(exc)
            result["elapsed_s"] = round(time.monotonic() - started, 2)
            return result
        except Exception as exc:
            logger.exception("unclassified source snapshot preflight failure")
            error_class = "snapshot_preflight_failed"
            result["status"] = "error"
            result["error_class"] = error_class
            result["errors"] = [{
                "stage": "snapshot",
                "error_class": error_class,
                "message": str(exc),
            }]
            result["error_classes"] = [error_class]
            result["error"] = str(exc)
            result["elapsed_s"] = round(time.monotonic() - started, 2)
            return result

    try:
        try:
            if table:
                count = adapter.sync_sqlite_to_duckdb(table)
                result["results"][table] = count
                result["total_rows"] = count
            else:
                counts = adapter.sync_all_to_duckdb()
                result["results"] = counts
                result["total_rows"] = sum(v for v in counts.values() if v > 0)
                failed_tables = sorted(table_name for table_name, count in counts.items() if count < 0)
                if failed_tables:
                    result["status"] = "error"
                    result["failed_tables"] = failed_tables
                    result["sync_errors"] = getattr(adapter, "last_sync_errors", {})
                    issues.append({
                        "stage": "sync",
                        "error_class": "sync_failed",
                        "message": "DuckDB sync failed for: " + ", ".join(failed_tables),
                    })
        except Exception as exc:
            logger.exception("merge sync failed")
            result["status"] = "error"
            issues.append({
                "stage": "sync",
                "error_class": "sync_failed",
                "message": str(exc),
            })

        try:
            reconciliation = adapter.reconcile_counts([table] if table else None)
            result["reconciliation"] = reconciliation
            mismatched_tables = sorted(
                table_name
                for table_name, details in reconciliation.items()
                if details.get("status") != "ok"
            )
            if mismatched_tables:
                result["status"] = "error"
                result["mismatched_tables"] = mismatched_tables
                issues.append({
                    "stage": "reconcile",
                    "error_class": "reconciliation_failed",
                    "message": "DuckDB reconciliation failed for: "
                    + ", ".join(mismatched_tables),
                })
        except Exception as exc:
            logger.exception("merge reconciliation failed")
            result["status"] = "error"
            result["reconciliation_error"] = str(exc)
            issues.append({
                "stage": "reconcile",
                "error_class": "reconciliation_failed",
                "message": str(exc),
            })
    finally:
        if source_snapshot is not None:
            try:
                result["snapshot_cleanup"] = source_snapshot.cleanup()
            except SQLiteSnapshotError as exc:
                logger.exception("source snapshot cleanup failed")
                result["status"] = "error"
                result["error_class"] = exc.error_class
                result["snapshot_cleanup"] = exc.metadata.get("cleanup") or exc.metadata
                issues.append({
                    "stage": "cleanup",
                    "error_class": "cleanup_failed",
                    "message": str(exc),
                })

    if issues:
        result["status"] = "error"
        result["errors"] = issues
        result["error"] = "; ".join(issue["message"] for issue in issues)
        result["error_classes"] = list(dict.fromkeys(
            issue.get("error_class", "merge_failed") for issue in issues
        ))
        result.setdefault("error_class", result["error_classes"][0])

    result["elapsed_s"] = round(time.monotonic() - started, 2)
    return result


def run_loop(interval_sec: int, table: str = "", dry_run: bool = False) -> None:
    """Run merge continuously every interval_sec."""
    logger.info("duckdb merge loop started, interval=%ds", interval_sec)

    while True:
        try:
            # A source snapshot is per-cycle.  Never reuse a live-source
            # adapter across loop iterations or the loop would bypass the
            # consistent-source contract used by the one-shot cron path.
            result = run_merge(table=table, dry_run=dry_run)
            if not dry_run:
                record_result(result)
            status_icon = "OK" if result["status"] == "ok" else "ERR"
            logger.info(
                "%s merged=%d rows in %.1fs",
                status_icon,
                result.get("total_rows", 0),
                result["elapsed_s"],
            )
        except Exception:
            logger.exception("merge loop iteration failed")
            record_result({
                "merge_at": utc_now(),
                "status": "error",
                "error": "unhandled loop exception",
            })
        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="DuckDB merge worker")
    parser.add_argument("--table", help="Sync a single table instead of all")
    parser.add_argument("--loop", type=int, metavar="SEC", help="Run continuously every SEC seconds")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--no-record", action="store_true", help="Don't write merge log")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Initialize result to avoid UnboundLocalError if --loop exits or is refactored (Bug #2 fix)
    result: dict = {"status": "ok"}

    if args.loop:
        run_loop(args.loop, table=args.table or "", dry_run=args.dry_run)
    else:
        result = run_merge(table=args.table or "", dry_run=args.dry_run)
        if not args.no_record and not args.dry_run:
            record_result(result)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            status = "OK" if result["status"] == "ok" else "ERROR"
            print(f"[{status}] merged {result.get('total_rows', 0)} rows in {result['elapsed_s']:.1f}s")
            for t, c in result.get("results", {}).items():
                print(f"  {t}: {c} rows")

    if result.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
