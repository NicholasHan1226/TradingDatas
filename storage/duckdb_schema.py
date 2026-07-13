"""DuckDB schema for the SQLite-backed analytics mirror.

SQLite remains authoritative.  DuckDB schema upgrades are additive and run as
one fail-closed transaction: create every table, migrate every contract column,
then create and validate indexes.  A partial schema must never be reported as a
healthy mirror.
"""

from __future__ import annotations

from typing import Any

from .schema_contract import (
    TABLES,
    TYPE_MAP,
    Table,
    get_table,
    render_indexes,
    render_schema,
    render_table,
    table_names,
    table_primary_keys,
)

DUCKDB_SCHEMA_SQL = render_schema("duckdb")
TABLE_NAMES = table_names()
TABLE_PRIMARY_KEYS = table_primary_keys()


class DuckDBSchemaError(RuntimeError):
    """Raised when the analytics mirror cannot satisfy the schema contract."""


def create_schema(conn: Any) -> None:
    """Create or migrate the complete DuckDB contract atomically.

    The ordering is deliberate.  Older mirrors can lack columns referenced by
    newer indexes, so all tables and columns must exist before any index DDL is
    attempted.  Any failure rolls the whole migration back and propagates to
    the merge worker.
    """

    conn.execute("BEGIN TRANSACTION")
    try:
        for table in TABLES:
            conn.execute(render_table(table, "duckdb"))

        for table in TABLES:
            _ensure_contract_columns(conn, table)

        for table in TABLES:
            _create_indexes(conn, table)

        for table in TABLES:
            _validate_table_contract(conn, table)
            _validate_indexes(conn, table)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    conn.execute("COMMIT")


def ensure_table_columns(conn: Any, table_name: str) -> list[str]:
    """Migrate one known table's columns without swallowing contract errors.

    This helper exists for focused migration tests.  Normal runtime setup must
    use :func:`create_schema` so the complete contract is transactional.
    """

    try:
        table = get_table(table_name)
    except KeyError as exc:
        raise DuckDBSchemaError(f"unknown DuckDB contract table: {table_name}") from exc
    _ensure_contract_columns(conn, table)
    return list(_column_info(conn, table_name))


def _ensure_contract_columns(conn: Any, table: Table) -> None:
    info = _column_info(conn, table.name)
    if not info:
        raise DuckDBSchemaError(f"DuckDB table missing after CREATE: {table.name}")

    for column in table.columns:
        expected_type = TYPE_MAP["duckdb"][column.logical_type]
        current = info.get(column.name)
        if current is None:
            if not column.nullable and _table_row_count(conn, table.name) > 0:
                raise DuckDBSchemaError(
                    f"cannot add NOT NULL column {table.name}.{column.name} "
                    "to a non-empty DuckDB table without an authoritative default"
                )
            conn.execute(
                f"ALTER TABLE {_quote_identifier(table.name)} "
                f"ADD COLUMN {_quote_identifier(column.name)} {expected_type}"
            )
            if not column.nullable:
                conn.execute(
                    f"ALTER TABLE {_quote_identifier(table.name)} "
                    f"ALTER COLUMN {_quote_identifier(column.name)} SET NOT NULL"
                )
            info = _column_info(conn, table.name)
            current = info.get(column.name)
            if current is None:
                raise DuckDBSchemaError(
                    f"DuckDB column migration did not create {table.name}.{column.name}"
                )

        actual_type, actual_nullable = current
        if _normalise_type(actual_type) != _normalise_type(expected_type):
            raise DuckDBSchemaError(
                f"DuckDB type drift for {table.name}.{column.name}: "
                f"expected {expected_type}, found {actual_type}"
            )

        if not column.nullable and actual_nullable:
            null_count = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(table.name)} "
                    f"WHERE {_quote_identifier(column.name)} IS NULL"
                ).fetchone()[0]
            )
            if null_count:
                raise DuckDBSchemaError(
                    f"DuckDB nullability drift for {table.name}.{column.name}: "
                    f"{null_count} existing NULL rows"
                )
            conn.execute(
                f"ALTER TABLE {_quote_identifier(table.name)} "
                f"ALTER COLUMN {_quote_identifier(column.name)} SET NOT NULL"
            )


def _create_indexes(conn: Any, table: Table) -> None:
    index_sql = render_indexes(table, "duckdb")
    for statement in index_sql.splitlines():
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def _validate_table_contract(conn: Any, table: Table) -> None:
    info = _column_info(conn, table.name)
    expected_names = {column.name for column in table.columns}
    actual_names = set(info)
    if actual_names != expected_names:
        raise DuckDBSchemaError(
            f"DuckDB column drift for {table.name}: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )

    for column in table.columns:
        actual_type, actual_nullable = info[column.name]
        expected_type = TYPE_MAP["duckdb"][column.logical_type]
        if _normalise_type(actual_type) != _normalise_type(expected_type):
            raise DuckDBSchemaError(
                f"DuckDB type drift for {table.name}.{column.name}: "
                f"expected {expected_type}, found {actual_type}"
            )
        if not column.nullable and actual_nullable:
            raise DuckDBSchemaError(
                f"DuckDB nullability drift for {table.name}.{column.name}"
            )


def _validate_indexes(conn: Any, table: Table) -> None:
    for index_name, columns in table.indexes:
        row = conn.execute(
            "SELECT table_name, expressions FROM duckdb_indexes() WHERE index_name = ?",
            [index_name],
        ).fetchone()
        if row is None:
            raise DuckDBSchemaError(f"DuckDB index missing: {index_name}")
        actual_columns = _index_columns(row[1])
        if row[0] != table.name or actual_columns != tuple(columns):
            raise DuckDBSchemaError(
                f"DuckDB index drift for {index_name}: "
                f"expected {table.name}{tuple(columns)}, "
                f"found {row[0]}{actual_columns}"
            )


def _column_info(conn: Any, table_name: str) -> dict[str, tuple[str, bool]]:
    rows = conn.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name = ?
        ORDER BY ordinal_position
        """,
        [table_name],
    ).fetchall()
    return {str(name): (str(data_type), str(nullable).upper() == "YES") for name, data_type, nullable in rows}


def _table_row_count(conn: Any, table_name: str) -> int:
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}"
        ).fetchone()[0]
    )


def _normalise_type(value: str) -> str:
    return " ".join(str(value).upper().split())


def _index_columns(value: Any) -> tuple[str, ...]:
    """Normalise DuckDB's display quoting for simple contract indexes."""

    rendered = str(value).strip()
    if rendered.startswith("[") and rendered.endswith("]"):
        rendered = rendered[1:-1]
    if not rendered:
        return ()
    columns = []
    for item in rendered.split(","):
        normalised = item.strip().strip("'").strip('"')
        columns.append(normalised)
    return tuple(columns)


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'
