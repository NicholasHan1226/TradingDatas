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
AUTHORITATIVE_SNAPSHOT_TABLES = {
    "market_assets",
    "market_backfill_status",
    "market_bars_daily",
    "market_bars_intraday",
    "market_coverage_status",
    "market_fund_portfolio",
    "market_industry_memberships",
    "market_industry_snapshots",
    "market_industry_taxonomy",
    "market_pm_markets",
    "market_relationships",
    "provider_interface_matrix",
}


class StorageAdapter:
    """Unified read/write adapter for SQLite (authoritative) + DuckDB (analytics)."""

    def __init__(
        self,
        sqlite_path: str = DEFAULT_SQLITE_PATH,
        duckdb_path: str = DEFAULT_DUCKDB_PATH,
    ):
        self._sqlite_path = Path(sqlite_path)
        self._duckdb_path = Path(duckdb_path)
        self._last_sync_errors: dict[str, dict[str, str]] = {}

    @property
    def sqlite_path(self) -> Path:
        return self._sqlite_path

    @property
    def duckdb_path(self) -> Path:
        return self._duckdb_path

    @property
    def last_sync_errors(self) -> dict[str, dict[str, str]]:
        return dict(self._last_sync_errors)

    # -- Connections ---------------------------------------------------------

    def sqlite_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._sqlite_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def duckdb_connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        path = str(self._duckdb_path)
        conn = duckdb.connect(path, read_only=read_only)
        try:
            if not read_only:
                temp_dir = self._duckdb_path.parent / ".duckdb_tmp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                memory_limit = os.environ.get("SHAREDSIGNALS_DUCKDB_MEMORY_LIMIT", "3GB")
                threads = max(
                    1, int(os.environ.get("SHAREDSIGNALS_DUCKDB_THREADS", "2"))
                )
                conn.execute(f"SET memory_limit = {_quote_literal(memory_limit)}")
                conn.execute(f"SET threads = {threads}")
                conn.execute("SET preserve_insertion_order = false")
                conn.execute(f"SET temp_directory = {_quote_literal(str(temp_dir))}")
                create_schema(conn)
                # Direct sqlite_scan avoids a Python memory round-trip.
                conn.execute("INSTALL sqlite; LOAD sqlite;")
                conn.execute("SET sqlite_all_varchar=true")
        except Exception:
            conn.close()
            raise
        return conn

    # -- Sync ----------------------------------------------------------------

    def sync_sqlite_to_duckdb(self, table: str, where: str = "") -> int:
        """Sync rows from SQLite to DuckDB for a single table. Returns row count.

        Uses DuckDB's native sqlite_scan to ATTACH SQLite directly — no Python
        memory round-trip, no temp NDJSON staging.  Scales to millions of rows
        without OOM risk (Bug #1 fix).

        Empty SQLite tables sync as 0 rows (success, not an error).  The full
        DuckDB contract is migrated by ``duckdb_connect`` before this method
        starts its data transaction.
        """
        # Fail closed before opening the mirror for an unknown relation.
        get_table(table)
        conn_dk = self.duckdb_connect()
        sqlite_path = str(self._sqlite_path.resolve())
        sqlite_literal = _quote_literal(sqlite_path)
        table_literal = _quote_literal(table)
        in_transaction = False

        try:
            pk = _pk_for_table(table)
            cols = _duckdb_table_columns(conn_dk, table)
            col_str = ", ".join(_quote_identifier(col) for col in cols)
            select_col_str = ", ".join(_sqlite_scan_select_expr(table, col) for col in cols)
            where_clause = f" WHERE {where}" if where else ""

            conn_dk.execute("BEGIN TRANSACTION")
            in_transaction = True

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
                    f"INSERT INTO {_quote_identifier(table)} ({col_str}) "
                    f"SELECT {source_cols} FROM ("
                    f"SELECT {select_col_str} FROM sqlite_scan({sqlite_literal}, {table_literal})"
                    f"{incremental_clause}) AS src "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {_quote_identifier(table)} AS dst "
                    f"WHERE {pk_match})"
                )
            elif pk:
                pk_str = ", ".join(_quote_identifier(col) for col in pk)
                non_pk_cols = [c for c in cols if c not in pk]
                update_set = ", ".join(
                    f"{_quote_identifier(col)} = EXCLUDED.{_quote_identifier(col)}"
                    for col in non_pk_cols
                )
                sql = (
                    f"INSERT INTO {_quote_identifier(table)} ({col_str}) "
                    f"SELECT {select_col_str} FROM sqlite_scan({sqlite_literal}, {table_literal})"
                    f"{where_clause} "
                    f"ON CONFLICT ({pk_str}) DO UPDATE SET {update_set}"
                )
            else:
                sql = (
                    f"INSERT OR IGNORE INTO {_quote_identifier(table)} ({col_str}) "
                    f"SELECT {select_col_str} FROM sqlite_scan({sqlite_literal}, {table_literal})"
                    f"{where_clause}"
                )

            result = conn_dk.execute(sql)
            count = result.fetchall()[0][0] if result.description else 0

            # Append-only semantics keep historical content immutable.  The
            # three identity fields are lineage metadata and are repaired from
            # SQLite authority for pre-identity rows with the same event_hash.
            if table == "market_events":
                _backfill_event_identity(conn_dk, sqlite_literal)

            if pk and table in AUTHORITATIVE_SNAPSHOT_TABLES and not where:
                pk_match = " AND ".join(
                    f"src.{_quote_identifier(col)} = dst.{_quote_identifier(col)}" for col in pk
                )
                conn_dk.execute(
                    f"DELETE FROM {_quote_identifier(table)} AS dst "
                    f"WHERE NOT EXISTS ("
                    f"SELECT 1 FROM sqlite_scan({sqlite_literal}, {table_literal}) AS src "
                    f"WHERE {pk_match})"
                )
            conn_dk.execute("COMMIT")
            in_transaction = False
            logger.info("duckdb merge: %s <- %d rows (direct sqlite_scan)", table, count)
        except Exception:
            if in_transaction:
                try:
                    conn_dk.execute("ROLLBACK")
                except Exception:
                    pass
            raise
        finally:
            conn_dk.close()

        return count

    def sync_all_to_duckdb(self) -> dict[str, int]:
        """Sync all tables from SQLite to DuckDB. Returns {table: count} dict."""
        from .duckdb_schema import TABLE_NAMES

        results = {}
        self._last_sync_errors = {}
        for table in TABLE_NAMES:
            try:
                count = self.sync_sqlite_to_duckdb(table)
                results[table] = count
                logger.info("sync %s: %d rows", table, count)
            except Exception as exc:
                logger.exception("sync failed: %s", table)
                results[table] = -1
                self._last_sync_errors[table] = {
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                }
        return results

    def reconcile_counts(self, tables: list[str] | None = None) -> dict[str, dict[str, int | str]]:
        """Reconcile authoritative SQLite and DuckDB structure and content.

        Row counts are necessary but insufficient for append-only events.  The
        event identity fields are also compared exactly so a legacy mirror with
        NULL identity metadata cannot be reported healthy.
        """
        from .duckdb_schema import TABLE_NAMES

        selected = tables or list(TABLE_NAMES)
        sqlite_conn = sqlite3.connect(
            f"file:{self._sqlite_path}?mode=ro",
            uri=True,
            timeout=30.0,
        )
        duckdb_conn = self.duckdb_connect(read_only=True)
        result: dict[str, dict[str, int | str]] = {}
        try:
            for table in selected:
                get_table(table)
                source_exists = _sqlite_table_exists(sqlite_conn, table)
                mirror_exists = _duckdb_table_exists(duckdb_conn, table)
                if not source_exists:
                    result[table] = {
                        "sqlite_rows": -1,
                        "duckdb_rows": (
                            _duckdb_row_count(duckdb_conn, table) if mirror_exists else -1
                        ),
                        "delta": 0,
                        "status": "source_missing",
                    }
                    continue
                sqlite_rows = int(
                    sqlite_conn.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
                    ).fetchone()[0]
                )
                if not mirror_exists:
                    result[table] = {
                        "sqlite_rows": sqlite_rows,
                        "duckdb_rows": -1,
                        "delta": sqlite_rows,
                        "status": "mirror_missing",
                    }
                    continue

                duckdb_rows = _duckdb_row_count(duckdb_conn, table)
                delta = sqlite_rows - duckdb_rows
                details: dict[str, int | str] = {
                    "sqlite_rows": sqlite_rows,
                    "duckdb_rows": duckdb_rows,
                    "delta": delta,
                    "status": "ok" if delta == 0 else "mismatch",
                }
                if table == "market_events":
                    identity = _reconcile_event_identity(
                        duckdb_conn, str(self._sqlite_path.resolve())
                    )
                    details.update(identity)
                    if any(
                        int(identity[key]) > 0
                        for key in (
                            "extra_in_duckdb",
                            "missing_in_duckdb",
                            "sqlite_identity_invalid",
                            "duckdb_identity_invalid",
                            "identity_mismatches",
                        )
                    ):
                        details["status"] = "mismatch"
                        details["mismatch_kind"] = "identity"
                result[table] = details
        finally:
            sqlite_conn.close()
            duckdb_conn.close()
        return result

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
    result = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name = ?
        ORDER BY ordinal_position
        """,
        [table],
    ).fetchall()
    if not result:
        raise RuntimeError(f"DuckDB mirror table is missing: {table}")
    return [str(row[0]) for row in result]


def _backfill_event_identity(conn: Any, sqlite_literal: str) -> None:
    conn.execute(
        f"""
        WITH src AS (
            SELECT
                CAST(event_hash AS VARCHAR) AS event_hash,
                CAST(event_id AS VARCHAR) AS event_id,
                TRY_CAST(NULLIF(CAST(revision AS VARCHAR), '') AS BIGINT) AS revision,
                CAST(source_family AS VARCHAR) AS source_family
            FROM sqlite_scan({sqlite_literal}, 'market_events')
        )
        UPDATE market_events AS dst
        SET
            event_id = src.event_id,
            revision = src.revision,
            source_family = src.source_family
        FROM src
        WHERE dst.event_hash = src.event_hash
          AND (
              dst.event_id IS DISTINCT FROM src.event_id
              OR dst.revision IS DISTINCT FROM src.revision
              OR dst.source_family IS DISTINCT FROM src.source_family
          )
        """
    )


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        [table],
    ).fetchone() is not None


def _duckdb_table_exists(conn: Any, table: str) -> bool:
    return conn.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table],
    ).fetchone() is not None


def _duckdb_row_count(conn: Any, table: str) -> int:
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
        ).fetchone()[0]
    )


def _reconcile_event_identity(conn: Any, sqlite_path: str) -> dict[str, int]:
    conn.execute("LOAD sqlite")
    conn.execute("SET sqlite_all_varchar=true")
    row = conn.execute(
        f"""
        WITH src AS (
            SELECT
                CAST(event_hash AS VARCHAR) AS event_hash,
                CAST(event_id AS VARCHAR) AS event_id,
                TRY_CAST(NULLIF(CAST(revision AS VARCHAR), '') AS BIGINT) AS revision,
                CAST(source_family AS VARCHAR) AS source_family
            FROM sqlite_scan({_quote_literal(sqlite_path)}, 'market_events')
        ),
        joined AS (
            SELECT
                src.event_hash AS src_hash,
                dst.event_hash AS dst_hash,
                src.event_id AS src_event_id,
                dst.event_id AS dst_event_id,
                src.revision AS src_revision,
                dst.revision AS dst_revision,
                src.source_family AS src_family,
                dst.source_family AS dst_family
            FROM src
            FULL OUTER JOIN market_events AS dst
              ON src.event_hash = dst.event_hash
        )
        SELECT
            COALESCE(SUM(CASE WHEN src_hash IS NULL THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN dst_hash IS NULL THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN src_hash IS NOT NULL AND (
                src_event_id IS NULL OR trim(src_event_id) = ''
                OR src_revision IS NULL OR src_revision < 1
                OR src_family IS NULL OR trim(src_family) = ''
            ) THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN dst_hash IS NOT NULL AND (
                dst_event_id IS NULL OR trim(dst_event_id) = ''
                OR dst_revision IS NULL OR dst_revision < 1
                OR dst_family IS NULL OR trim(dst_family) = ''
            ) THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN src_hash IS NOT NULL AND dst_hash IS NOT NULL AND (
                src_event_id IS DISTINCT FROM dst_event_id
                OR src_revision IS DISTINCT FROM dst_revision
                OR src_family IS DISTINCT FROM dst_family
            ) THEN 1 ELSE 0 END), 0)
        FROM joined
        """
    ).fetchone()
    keys = (
        "extra_in_duckdb",
        "missing_in_duckdb",
        "sqlite_identity_invalid",
        "duckdb_identity_invalid",
        "identity_mismatches",
    )
    return {key: int(value) for key, value in zip(keys, row)}
