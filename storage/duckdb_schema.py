"""DuckDB schema — shadow read-model mirroring the SQLite marketdata schema.

Strategy (from Codex architecture review):
  - SQLite continues as authoritative write model
  - DuckDB provides a fast read-only analytics copy
  - Per-thread duckdb.connect() — never global duckdb.sql()

All 11 tables defined here match the SQLite schema in storage/schema.py.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# DuckDB DDL (rendered from storage.schema_contract)
# ---------------------------------------------------------------------------

from .schema_contract import render_schema, table_names

DUCKDB_SCHEMA_SQL = render_schema("duckdb")
TABLE_NAMES = table_names()


def create_schema(conn: Any) -> None:
    """Create all DuckDB tables if they don't exist."""
    conn.execute(DUCKDB_SCHEMA_SQL)
