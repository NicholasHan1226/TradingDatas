#!/usr/bin/env python3
"""Run bounded routine maintenance on the SharedSignals SQLite read model."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_paths import marketdata_sqlite_path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _rw_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=rw"


def run_maintenance(
    db_path: Path,
    *,
    deep_check: bool = False,
) -> dict[str, Any]:
    """Checkpoint and optimize the authoritative database without rewriting it."""

    path = Path(db_path)
    result: dict[str, Any] = {
        "owner": "SharedSignals",
        "status": "red",
        "database": str(path),
        "wal_checkpoint": None,
        "optimized": False,
        "integrity": "not_run",
        "deep_check": bool(deep_check),
        "started_at": _utc_now(),
        "completed_at": None,
    }
    if not path.is_file():
        result["error"] = "database_not_found"
        result["completed_at"] = _utc_now()
        return result

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(_rw_uri(path), uri=True, timeout=30)
        checkpoint_row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        if checkpoint_row is None or len(checkpoint_row) < 3:
            raise RuntimeError("wal_checkpoint returned no evidence")
        busy, log_frames, checkpointed_frames = (
            int(checkpoint_row[0]),
            int(checkpoint_row[1]),
            int(checkpoint_row[2]),
        )
        result["wal_checkpoint"] = {
            "busy": busy,
            "log_frames": log_frames,
            "checkpointed_frames": checkpointed_frames,
        }

        conn.execute("PRAGMA optimize(0x10002)")
        result["optimized"] = True

        if deep_check:
            quick_check_row = conn.execute("PRAGMA quick_check").fetchone()
            result["integrity"] = (
                str(quick_check_row[0]) if quick_check_row else "missing_result"
            )

        integrity_ok = result["integrity"] in {"not_run", "ok"}
        result["status"] = "green" if busy == 0 and integrity_ok else "red"
    except Exception as exc:  # noqa: BLE001 - the evidence must survive any DB failure
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "red"
    finally:
        if conn is not None:
            conn.close()
        result["completed_at"] = _utc_now()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded SharedSignals SQLite checkpoint/optimize maintenance"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (default: SHAREDSIGNALS_MARKETDATA_DB/runtime path)",
    )
    parser.add_argument(
        "--deep-check",
        action="store_true",
        help="Run PRAGMA quick_check in addition to routine maintenance",
    )
    args = parser.parse_args()

    report = run_maintenance(
        args.db or Path(marketdata_sqlite_path()),
        deep_check=args.deep_check,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
