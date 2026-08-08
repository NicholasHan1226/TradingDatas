#!/usr/bin/env python3
"""Backfill canonical ``partition_value`` for the Crypto 5m read model.

The 5m bar datasets declare ``partition_field: open_time``; the query service
renders range filters against ``partition_value`` with canonical
RFC3339-millisecond operands (``...T04:40:00.000Z``).  Rows written before the
partition field was declared carry ``NULL`` (or a non-canonical spelling) in
that column, which silently excludes them from single-window ``BETWEEN``
queries.  This tool idempotently re-derives ``partition_value`` from each
row's ``payload_json`` using the exact canonical encoding, and refuses to
touch any other dataset.

Run with ``--dry-run`` first; the write mode wraps all updates in one
transaction.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)


def canonical_rfc3339_milliseconds(value: object) -> str | None:
    """Return the provider-row canonical spelling or None when unparseable."""

    if type(value) is not str or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _bar_dataset_ids(registry) -> tuple[str, ...]:
    datasets = tuple(
        item.dataset_id
        for item in registry.datasets
        if item.dataset_id.startswith("crypto.spot.binance.")
        and item.dataset_id.endswith(".5m")
        and item.partition_field == "open_time"
    )
    if len(datasets) != 10 or len(set(datasets)) != len(datasets):
        raise RuntimeError("runtime registry must contain the frozen ten 5m bar datasets")
    return datasets


def backfill_partition_values(
    conn: sqlite3.Connection,
    registry,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    """Backfill partition_value for crypto 5m rows; return per-dataset counts."""

    datasets = _bar_dataset_ids(registry)
    placeholders = ", ".join("?" for _ in datasets)
    rows = conn.execute(
        "SELECT dataset_id, row_key, "
        "json_extract(payload_json, '$.open_time'), partition_value "
        "FROM provider_dataset_rows "
        f"WHERE dataset_id IN ({placeholders})",
        datasets,
    ).fetchall()

    summary: dict[str, object] = {"dry_run": dry_run, "datasets": {}}
    by_dataset: dict[str, dict[str, int]] = {
        dataset: {
            "total": 0,
            "backfill": 0,
            "already_canonical": 0,
            "unparseable": 0,
        }
        for dataset in datasets
    }
    updates: list[tuple[str, str, str]] = []
    for dataset_id, row_key, raw_open_time, current_value in rows:
        by_dataset[dataset_id]["total"] += 1
        canonical = canonical_rfc3339_milliseconds(raw_open_time)
        if canonical is None:
            by_dataset[dataset_id]["unparseable"] += 1
            continue
        if current_value == canonical:
            by_dataset[dataset_id]["already_canonical"] += 1
            continue
        by_dataset[dataset_id]["backfill"] += 1
        updates.append((canonical, dataset_id, row_key))

    if not dry_run and updates:
        conn.executemany(
            "UPDATE provider_dataset_rows SET partition_value = ? "
            "WHERE dataset_id = ? AND row_key = ?",
            updates,
        )
        conn.commit()

    summary["rows_updated"] = len(updates)
    summary["datasets"] = by_dataset
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument(
        "--registry-path",
        type=Path,
        default=BINANCE_SPOT_CANARY_REGISTRY_PATH,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="open the database read-only (safe for production dry-run)",
    )
    args = parser.parse_args(argv)

    registry = load_dataset_registry(args.registry_path)
    if args.read_only:
        conn = sqlite3.connect(
            f"file:{args.db_path}?mode=ro",
            uri=True,
        )
    else:
        conn = sqlite3.connect(args.db_path)
    try:
        summary = backfill_partition_values(conn, registry, dry_run=args.dry_run)
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if summary["datasets"] and any(
        item["unparseable"] for item in summary["datasets"].values()
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
