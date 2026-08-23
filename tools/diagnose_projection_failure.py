#!/usr/bin/env python3
"""Triage helper for site-wide projection failures.

When every dataset projects to ``failed`` the usual suspect is one or more
``market_ingest_runs`` rows whose ``source`` is outside the registry: the
fail-closed contract treats those as tamper evidence and fails all
projections on purpose.  This tool lists the offending rows so the owner can
decide whether to remove them or investigate, without touching SQLite.

Read-only: opens the store with ``mode=ro`` and never writes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from dataset_registry import load_dataset_registry


def diagnose(db_path: Path) -> dict[str, object]:
    registry = load_dataset_registry()
    known = frozenset(item.dataset_id for item in registry.datasets)
    uri = f"{db_path.resolve(strict=True).as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        rows = conn.execute(
            "SELECT source, count(*), max(finished_at), min(run_id) "
            "FROM market_ingest_runs GROUP BY source"
        ).fetchall()
    finally:
        conn.close()
    unmapped = [
        {
            "source": source,
            "rows": count,
            "last_finished_at": last_finished_at,
            "example_run_id": example_run_id,
        }
        for source, count, last_finished_at, example_run_id in rows
        if type(source) is str and source not in known
    ]
    return {"unmapped_sources": unmapped, "unmapped_source_count": len(unmapped)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    args = parser.parse_args(argv)
    result = diagnose(args.db_path)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
