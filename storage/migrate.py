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
            conn.commit()
            if added_columns:
                conn.execute(
                    "INSERT INTO _migrations (schema_hash, applied_at, table_count, notes) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        current_hash,
                        datetime.now(timezone.utc).isoformat(),
                        conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
                        f"repair missing nullable columns: {added_columns}",
                    ),
                )
                conn.commit()
            conn.close()
            return {
                "status": "ok",
                "message": f"schema up to date, added {added_columns} columns",
                "applied": 0,
                "added_columns": added_columns,
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
