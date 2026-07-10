"""Storage adapter — bridges SQLite (authoritative) and DuckDB (analytics read-model).

Provides:
  - sqlite_connect() — connect to marketdata.sqlite
  - duckdb_connect() — connect to marketdata.duckdb (or :memory: for tests)
  - sync_to_duckdb() — batch-sync SQLite rows to DuckDB shadow
  - query() — unified read across both backends (DuckDB-first for analytics)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

import duckdb

from runtime_paths import marketdata_duckdb_path, marketdata_sqlite_path
from .duckdb_schema import create_schema
from .schema_contract import get_table

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = str(marketdata_sqlite_path())
DEFAULT_DUCKDB_PATH = str(marketdata_duckdb_path())
APPEND_ONLY_HASH_TABLES = {"market_events", "market_factors"}


class StorageAdapter:
    """Unified read/write adapter for SQLite (authoritative) + DuckDB (analytics)."""

    def __init__(
        self,
        sqlite_path: str = DEFAULT_SQLITE_PATH,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ):
        self._sqlite_path = Path(sqlite_path)
        self._duckdb_path = Path(duckdb_path)

    # -- Connections ---------------------------------------------------------

    def sqlite_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._sqlite_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def duckdb_connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        path = str(self._duckdb_path)
        conn = duckdb.connect(path, read_only=read_only)
        if not read_only:
            temp_dir = self._duckdb_path.parent / ".duckdb_tmp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            memory_limit = os.environ.get("SHAREDSIGNALS_DUCKDB_MEMORY_LIMIT", "3GB")
            threads = max(1, int(os.environ.get("SHAREDSIGNALS_DUCKDB_THREADS", "2")))
            conn.execute(f"SET memory_limit = {_quote_literal(memory_limit)}")
            conn.execute(f"SET threads = {threads}")
            conn.execute("SET preserve_insertion_order = false")
            conn.execute(f"SET temp_directory = {_quote_literal(str(temp_dir))}")
            create_schema(conn)
        # Install sqlite extension for direct ATTACH (Bug #1 fix — skip Python memory round-trip)
        if not read_only:
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            conn.execute("SET sqlite_all_varchar=true")
        return conn

    # -- Sync ----------------------------------------------------------------

    def sync_sqlite_to_duckdb(self, table: str, where: str = "") -> int:
        """Sync rows from SQLite to DuckDB for a single table. Returns row count.

        Uses DuckDB's native sqlite_scan to ATTACH SQLite directly — no Python
        memory round-trip, no temp NDJSON staging.  Scales to millions of rows
        without OOM risk (Bug #1 fix).
        """
        conn_dk = self.duckdb_connect()
        sqlite_path = str(self._sqlite_path.resolve())

        try:
            pk = _pk_for_table(table)
            cols = _duckdb_table_columns(conn_dk, table)
            if not cols:
                logger.warning("sync_sqlite_to_duckdb: unknown table %s", table)
                return 0

            col_str = ", ".join(_quote_identifier(col) for col in cols)
            select_col_str = ", ".join(_sqlite_scan_select_expr(table, col) for col in cols)
            where_clause = f" WHERE {where}" if where else ""

            if pk and table in APPEND_ONLY_HASH_TABLES:
                watermark_row = conn_dk.execute(
                    f"SELECT MAX(collected_at) FROM {_quote_identifier(table)}"
                ).fetchone()
                watermark = watermark_row[0] if watermark_row else None
                incremental_where = where
                if watermark:
                    watermark_filter = f"collected_at >= {_quote_literal(str(watermark))}"
                    incremental_where = f"({where}) AND {watermark_filter}" if where else watermark_filter
                incremental_clause = f" WHERE {incremental_where}" if incremental_where else ""
                source_cols = ", ".join(f"src.{_quote_identifier(col)}" for col in cols)
                pk_match = " AND ".join(
                    f"dst.{_quote_identifier(col)} = src.{_quote_identifier(col)}" for col in pk
                )
                sql = (
                    f"INSERT INTO {table} ({col_str}) "
                    f"SELECT {source_cols} FROM ("
                    f"SELECT {select_col_str} FROM sqlite_scan('{sqlite_path}', '{table}')"
                    f"{incremental_clause}) AS src "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {table} AS dst WHERE {pk_match})"
                )
            elif pk:
                pk_str = ", ".join(_quote_identifier(col) for col in pk)
                non_pk_cols = [c for c in cols if c not in pk]
                update_set = ", ".join(
                    f"{_quote_identifier(col)} = EXCLUDED.{_quote_identifier(col)}"
                    for col in non_pk_cols
                )
                sql = (
                    f"INSERT INTO {table} ({col_str}) "
                    f"SELECT {select_col_str} FROM sqlite_scan('{sqlite_path}', '{table}')"
                    f"{where_clause} "
                    f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_set}"
                )
            else:
                sql = (
                    f"INSERT OR IGNORE INTO {table} ({col_str}) "
                    f"SELECT {select_col_str} FROM sqlite_scan('{sqlite_path}', '{table}')"
                    f"{where_clause}"
                )

            result = conn_dk.execute(sql)
            count = result.fetchall()[0][0] if result.description else 0
            logger.info("duckdb merge: %s <- %d rows (direct sqlite_scan)", table, count)
        finally:
            conn_dk.close()

        return count

    def sync_all_to_duckdb(self) -> dict[str, int]:
        """Sync all tables from SQLite to DuckDB. Returns {table: count} dict."""
        from .duckdb_schema import TABLE_NAMES

        results = {}
        for table in TABLE_NAMES:
            try:
                count = self.sync_sqlite_to_duckdb(table)
                results[table] = count
                logger.info("sync %s: %d rows", table, count)
            except Exception:
                logger.exception("sync failed: %s", table)
                results[table] = -1
        return results

    # -- Query (DuckDB-first for speed) --------------------------------------

    def query(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """Execute a read query against DuckDB. Fall back to SQLite on error."""
        try:
            conn = self.duckdb_connect(read_only=True)
            result = conn.execute(sql, params or ()).fetchall()
            cols = [desc[0] for desc in conn.description] if conn.description else []
            conn.close()
            return [dict(zip(cols, row)) for row in result]
        except Exception:
            logger.debug("duckdb query failed, trying sqlite", exc_info=True)
            conn = self.sqlite_connect()
            result = conn.execute(sql, params or ()).fetchall()
            conn.close()
            return [dict(row) for row in result]

    def query_df(self, sql: str) -> Any:
        """Execute query and return as pandas DataFrame (duckdb-native)."""
        conn = self.duckdb_connect(read_only=True)
        df = conn.execute(sql).df()
        conn.close()
        return df


def _pk_for_table(table: str) -> list[str]:
    from .schema_contract import table_primary_keys

    return table_primary_keys().get(table, [])


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sqlite_scan_select_expr(table: str, column: str) -> str:
    column_types = {col.name: col.logical_type for col in get_table(table).columns}
    logical_type = column_types.get(column, "text")
    quoted = _quote_identifier(column)
    if logical_type == "float":
        return f"TRY_CAST(NULLIF(CAST({quoted} AS VARCHAR), '') AS DOUBLE) AS {quoted}"
    if logical_type == "integer":
        return f"TRY_CAST(NULLIF(CAST({quoted} AS VARCHAR), '') AS BIGINT) AS {quoted}"
    return quoted


def _duckdb_table_columns(conn: Any, table: str) -> list[str]:
    """Return column names for a DuckDB table."""
    try:
        result = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
        return [r[0] for r in result]
    except Exception:
        return []
