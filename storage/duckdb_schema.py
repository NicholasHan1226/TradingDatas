"""DuckDB schema — shadow read-model mirroring the SQLite marketdata schema.

Strategy (from Codex architecture review):
  - SQLite continues as authoritative write model
  - DuckDB provides a fast read-only analytics copy
  - Single-writer batch-merges from NDJSON staging files
  - Per-thread duckdb.connect() — never global duckdb.sql()

All 11 tables defined here match the SQLite schema in storage/schema.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DuckDB DDL (rendered from storage.schema_contract)
# ---------------------------------------------------------------------------

from .schema_contract import render_schema, table_names, table_primary_keys

DUCKDB_SCHEMA_SQL = render_schema("duckdb")
TABLE_PRIMARY_KEYS: dict[str, list[str]] = table_primary_keys()
TABLE_NAMES = table_names()


def create_schema(conn: Any) -> None:
    """Create all DuckDB tables if they don't exist."""
    conn.execute(DUCKDB_SCHEMA_SQL)


def merge_from_ndjson(conn: Any, table: str, ndjson_path: str) -> int:
    """Merge rows from an NDJSON staging file into a DuckDB table.

    Uses INSERT OR REPLACE (via ON CONFLICT) pattern.
    Returns number of rows merged.
    """
    import json

    pk = TABLE_PRIMARY_KEYS.get(table, [])
    cols = _table_columns(conn, table)
    if not cols:
        logger.warning("merge_from_ndjson: unknown table %s", table)
        return 0

    # Read NDJSON
    rows = []
    with open(ndjson_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        return 0

    # Build ON CONFLICT clause
    conflict_clause = ""
    if pk:
        pk_str = ", ".join(pk)
        conflict_clause = f" ON CONFLICT ({pk_str}) DO UPDATE SET " + ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols if c not in pk
        )
    else:
        conflict_clause = " ON CONFLICT DO NOTHING"

    # Column list — only include columns that exist in the table
    col_names = [c for c in rows[0].keys() if c in cols]
    placeholders = ", ".join(["?" for _ in col_names])
    col_str = ", ".join(col_names)

    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}){conflict_clause}"
    data = [[row.get(c) for c in col_names] for row in rows]

    conn.executemany(sql, data)
    logger.info("duckdb merge: %s ← %d rows from %s", table, len(rows), Path(ndjson_path).name)
    return len(rows)


def _table_columns(conn: Any, table: str) -> list[str]:
    """Return column names for a DuckDB table."""
    try:
        result = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
        return [r[0] for r in result]
    except Exception:
        return []
