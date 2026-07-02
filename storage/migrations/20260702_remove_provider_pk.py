#!/usr/bin/env python3
"""Remove provider from market_bars_daily primary key.

The migration keeps one row per (market, symbol, trade_date), preserving the
highest-priority provider row and keeping the old table as a backup.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.schema_contract import get_table, render_indexes, render_table, table_with_name  # noqa: E402


DEFAULT_SQLITE_PATH = "/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite"
OLD_TABLE = "market_bars_daily"
NEW_TABLE = "market_bars_daily_new"
BACKUP_TABLE = "market_bars_daily_old_provider_pk"
OLD_PK = ["market", "symbol", "trade_date", "provider"]
NEW_PK = ["market", "symbol", "trade_date"]


def migrate(database_path: str = DEFAULT_SQLITE_PATH, dry_run: bool = False) -> dict[str, Any]:
    """Run the migration or print a read-only dry-run plan."""
    db_path = Path(database_path)
    if dry_run:
        return _dry_run(db_path)
    return _migrate(db_path)


def _dry_run(db_path: Path) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "database": str(db_path),
        "dry_run": True,
        "would_change": False,
        "steps": [
            f"create {NEW_TABLE} with primary key ({', '.join(NEW_PK)})",
            "copy one preferred row per (market, symbol, trade_date)",
            f"rename {OLD_TABLE} to {BACKUP_TABLE}",
            f"rename {NEW_TABLE} to {OLD_TABLE}",
            "recreate market_bars_daily indexes",
        ],
    }

    if not db_path.exists():
        plan["status"] = "database_not_found"
        _print_plan(plan)
        return plan

    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        if not _table_exists(conn, OLD_TABLE):
            plan["status"] = "source_table_missing"
            _print_plan(plan)
            return plan

        current_pk = _current_pk(conn, OLD_TABLE)
        total_rows = conn.execute(f"SELECT COUNT(*) FROM {OLD_TABLE}").fetchone()[0]
        distinct_rows = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT 1
                FROM {OLD_TABLE}
                GROUP BY market, symbol, trade_date
            )
            """
        ).fetchone()[0]
        plan.update(
            {
                "status": "ready" if current_pk == OLD_PK else "already_migrated_or_unexpected_pk",
                "would_change": current_pk == OLD_PK,
                "current_pk": current_pk,
                "target_pk": NEW_PK,
                "total_rows": total_rows,
                "rows_after_dedup": distinct_rows,
                "duplicate_rows_to_collapse": total_rows - distinct_rows,
                "backup_table_exists": _table_exists(conn, BACKUP_TABLE),
                "temp_table_exists": _table_exists(conn, NEW_TABLE),
            }
        )
    finally:
        conn.close()

    _print_plan(plan)
    return plan


def _migrate(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None
    began = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        began = True
        if not _table_exists(conn, OLD_TABLE):
            raise RuntimeError(f"{OLD_TABLE} does not exist")
        if _table_exists(conn, BACKUP_TABLE):
            raise RuntimeError(f"{BACKUP_TABLE} already exists; refusing to overwrite backup")
        if _table_exists(conn, NEW_TABLE):
            raise RuntimeError(f"{NEW_TABLE} already exists; refusing to reuse temp table")

        current_pk = _current_pk(conn, OLD_TABLE)
        if current_pk == NEW_PK:
            conn.execute("ROLLBACK")
            began = False
            return {"status": "already_migrated", "current_pk": current_pk}
        if current_pk != OLD_PK:
            raise RuntimeError(f"unexpected {OLD_TABLE} primary key: {current_pk}")

        create_new_sql = render_table(table_with_name(get_table(OLD_TABLE), NEW_TABLE), "sqlite")
        create_new_sql = create_new_sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1)
        conn.execute(create_new_sql)

        columns = [column.name for column in get_table(OLD_TABLE).columns]
        column_sql = ", ".join(columns)
        conn.execute(
            f"""
            INSERT INTO {NEW_TABLE} ({column_sql})
            SELECT {column_sql}
            FROM (
                SELECT
                    {column_sql},
                    ROW_NUMBER() OVER (
                        PARTITION BY market, symbol, trade_date
                        ORDER BY
                            CASE provider
                                WHEN 'tushare_daily' THEN 5
                                WHEN 'tushare_hk_daily' THEN 4
                                WHEN 'tushare_us_daily' THEN 3
                                WHEN 'binance' THEN 2
                                ELSE 1
                            END DESC,
                            COALESCE(collected_at, '') DESC,
                            COALESCE(source_file, '') DESC,
                            rowid DESC
                    ) AS rn
                FROM {OLD_TABLE}
            )
            WHERE rn = 1
            """
        )
        rows_after_dedup = conn.execute(f"SELECT COUNT(*) FROM {NEW_TABLE}").fetchone()[0]

        conn.execute("DROP INDEX IF EXISTS idx_market_bars_daily_lookup")
        conn.execute(f"ALTER TABLE {OLD_TABLE} RENAME TO {BACKUP_TABLE}")
        conn.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO {OLD_TABLE}")
        for statement in _split_sql(render_indexes(get_table(OLD_TABLE))):
            conn.execute(statement)

        conn.execute("COMMIT")
        began = False
        return {
            "status": "migrated",
            "database": str(db_path),
            "backup_table": BACKUP_TABLE,
            "new_pk": NEW_PK,
            "rows_after_dedup": rows_after_dedup,
        }
    except Exception:
        if began:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _current_pk(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk_columns = [(row[5], row[1]) for row in rows if row[5]]
    return [name for _, name in sorted(pk_columns)]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def _print_plan(plan: dict[str, Any]) -> None:
    print("market_bars_daily provider-PK removal dry-run")
    for key, value in plan.items():
        if key == "steps":
            print("steps:")
            for step in value:
                print(f"- {step}")
        else:
            print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DEFAULT_SQLITE_PATH, help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="print the migration plan without changes")
    args = parser.parse_args()

    result = migrate(args.database, dry_run=args.dry_run)
    if not args.dry_run:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
