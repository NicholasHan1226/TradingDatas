#!/usr/bin/env python3
"""SharedSignals schema migration runner.

Reads schema.py and applies CREATE TABLE IF NOT EXISTS statements to the
target SQLite database. Idempotent — safe to run on every deploy.

Tracks applied migrations in a ``_migrations`` meta-table so the runner
can detect when the schema definition has changed and report drift.

Usage:
    python3 storage/migrate.py              # apply migrations
    python3 storage/migrate.py --check      # dry-run: report drift only
    python3 storage/migrate.py --db /path/to/db.sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
REPO_DIR = Path(__file__).resolve().parents[1]  # SharedSignals root
sys.path.insert(0, str(REPO_DIR))

from runtime_paths import marketdata_sqlite_path  # noqa: E402
from storage.event_identity import source_family, stable_event_id  # noqa: E402

DEFAULT_DB = marketdata_sqlite_path()


def schema_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _add_missing_columns(conn: sqlite3.Connection) -> int:
    """Add nullable columns that were introduced after a table already existed."""
    from storage.schema_contract import TABLES, TYPE_MAP

    added = 0
    type_map = TYPE_MAP["sqlite"]
    for table in TABLES:
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table.name)})").fetchall()
        }
        if not existing:
            continue
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable:
                raise RuntimeError(f"cannot add missing NOT NULL column {table.name}.{column.name}")
            conn.execute(
                f"ALTER TABLE {_quote_identifier(table.name)} "
                f"ADD COLUMN {_quote_identifier(column.name)} {type_map[column.logical_type]}"
            )
            added += 1
    return added


def _create_missing_indexes(conn: sqlite3.Connection) -> int:
    """Create contract indexes after additive columns are available."""
    from storage.schema_contract import TABLES

    created = 0
    for table in TABLES:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table.name,),
        ).fetchone():
            continue
        existing = {
            row[1]
            for row in conn.execute(
                f"PRAGMA index_list({_quote_identifier(table.name)})"
            ).fetchall()
        }
        for index_name, columns in table.indexes:
            if index_name in existing:
                continue
            column_sql = ", ".join(_quote_identifier(column) for column in columns)
            conn.execute(
                f"CREATE INDEX {_quote_identifier(index_name)} "
                f"ON {_quote_identifier(table.name)} ({column_sql})"
            )
            created += 1
    return created


def _normalize_periodic_bar_times(conn: sqlite3.Connection) -> int:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_bars_intraday'"
    ).fetchone()
    if not table_exists:
        return 0
    cursor = conn.execute(
        """
        UPDATE market_bars_intraday
        SET bar_time =
            substr(bar_time, 1, 4) || '-' ||
            substr(bar_time, 5, 2) || '-' ||
            substr(bar_time, 7, 2) || ' 00:00:00'
        WHERE interval IN ('weekly', 'monthly', 'index_weekly', 'index_monthly')
          AND length(bar_time) = 8
          AND bar_time GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
        """
    )
    return max(0, int(cursor.rowcount or 0))


def _backfill_event_identity(conn: sqlite3.Connection) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_events'").fetchone():
        return 0
    rows = conn.execute(
        """
        SELECT rowid, event_hash, event_id, revision, source_family, provider,
               event_type, event_time, trade_date, symbol, title, content, url,
               source, collected_at, raw_json
        FROM market_events
        """
    ).fetchall()
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        identity_row = {
            "event_time": row[7],
            "trade_date": row[8],
            "symbol": row[9],
            "title": row[10],
            "content": row[11],
            "url": row[12],
            "source": row[13],
            "raw_json": row[15],
        }
        try:
            expected_id = stable_event_id(row[5], row[6], identity_row)
        except ValueError:
            expected_id = str(row[2] or row[1] or "").strip()
        grouped.setdefault(expected_id, []).append(row)

    updated = 0
    for expected_id, identity_rows in grouped.items():
        ordered = sorted(
            identity_rows,
            key=lambda row: (str(row[7] or ""), str(row[14] or ""), int(row[0])),
        )
        for revision, row in enumerate(ordered, start=1):
            expected_family = source_family(row[5])
            if row[2] == expected_id and row[3] == revision and row[4] == expected_family:
                continue
            conn.execute(
                "UPDATE market_events SET event_id=?, revision=?, source_family=? WHERE rowid=?",
                (expected_id, revision, expected_family, row[0]),
            )
            updated += 1
    return updated


def apply_migrations(db_path: Path, check_only: bool = False) -> dict:
    """Apply SCHEMA_SQL DDL to *db_path*. Returns a result dict."""
    import importlib

    if not db_path.exists():
        return {
            "status": "error",
            "message": f"database not found: {db_path}",
            "applied": 0,
            "drift": False,
        }

    schema_mod = importlib.import_module("storage.schema")
    sql = schema_mod.SCHEMA_SQL

    conn = sqlite3.connect(str(db_path), timeout=10)
    applied = 0
    drift = False

    try:
        # Ensure migration tracking table exists
        conn.execute(
            """CREATE TABLE IF NOT EXISTS _migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_hash TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                table_count INTEGER,
                notes TEXT
            )"""
        )

        # Check last applied hash
        cur = conn.execute(
            "SELECT schema_hash FROM _migrations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        current_hash = schema_hash(sql)
        last_hash = cur[0] if cur else None

        if last_hash == current_hash:
            if check_only:
                conn.close()
                return {
                    "status": "ok",
                    "message": "schema up to date",
                    "applied": 0,
                    "drift": False,
                    "schema_hash": current_hash,
                }
            added_columns = _add_missing_columns(conn)
            indexes_created = _create_missing_indexes(conn)
            periodic_bar_times_normalized = _normalize_periodic_bar_times(conn)
            event_identity_backfilled = _backfill_event_identity(conn)
            conn.commit()
            if added_columns or indexes_created or periodic_bar_times_normalized or event_identity_backfilled:
                conn.execute(
                    "INSERT INTO _migrations (schema_hash, applied_at, table_count, notes) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        current_hash,
                        datetime.now(timezone.utc).isoformat(),
                        conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
                        "repair missing nullable columns: "
                        f"{added_columns}; create missing indexes: {indexes_created}; "
                        "normalize periodic bar times: "
                        f"{periodic_bar_times_normalized}; backfill event identity: "
                        f"{event_identity_backfilled}",
                    ),
                )
                conn.commit()
            conn.close()
            return {
                "status": "ok",
                "message": f"schema up to date, added {added_columns} columns",
                "applied": 0,
                "added_columns": added_columns,
                "indexes_created": indexes_created,
                "periodic_bar_times_normalized": periodic_bar_times_normalized,
                "event_identity_backfilled": event_identity_backfilled,
                "drift": False,
                "schema_hash": current_hash,
            }

        if check_only:
            conn.close()
            return {
                "status": "drift",
                "message": "schema drift detected (--check mode)",
                "applied": 0,
                "drift": True,
                "schema_hash": current_hash,
                "last_hash": last_hash,
            }

        # Apply DDL statements
        statements = [
            s.strip()
            for s in sql.split(";")
            if s.strip() and not s.strip().startswith("--")
        ]
        for stmt in statements:
            try:
                conn.execute(stmt)
                applied += 1
            except sqlite3.OperationalError as exc:
                print(f"[migrate] WARNING: {exc}", file=sys.stderr)

        added_columns = _add_missing_columns(conn)
        indexes_created = _create_missing_indexes(conn)
        periodic_bar_times_normalized = _normalize_periodic_bar_times(conn)
        event_identity_backfilled = _backfill_event_identity(conn)

        conn.commit()

        # Count tables
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]

        # Record migration
        conn.execute(
            "INSERT INTO _migrations (schema_hash, applied_at, table_count, notes) "
            "VALUES (?, ?, ?, ?)",
            (
                current_hash,
                datetime.now(timezone.utc).isoformat(),
                table_count,
                "deploy migration",
            ),
        )
        conn.commit()

        result = {
            "status": "ok",
            "message": f"applied {applied} statements, added {added_columns} columns",
            "applied": applied,
            "added_columns": added_columns,
            "indexes_created": indexes_created,
            "periodic_bar_times_normalized": periodic_bar_times_normalized,
            "event_identity_backfilled": event_identity_backfilled,
            "table_count": table_count,
            "drift": False,
            "schema_hash": current_hash,
        }
    except Exception as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "applied": applied,
            "drift": False,
        }
    finally:
        conn.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="SharedSignals schema migration runner")
    parser.add_argument("--check", action="store_true", help="Dry-run: report drift only")
    parser.add_argument("--db", help="Override database path")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DEFAULT_DB
    result = apply_migrations(db_path, check_only=args.check)
    print(result["message"])

    if result["drift"]:
        print(
            f"  schema_hash={result.get('schema_hash')} "
            f"last_hash={result.get('last_hash')}"
        )
        sys.exit(2)

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
