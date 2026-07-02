#!/usr/bin/env python3
"""Check SQLite/DuckDB schema drift against the canonical schema contract."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage import duckdb_schema, schema  # noqa: E402
from storage.schema_contract import (  # noqa: E402
    TABLES,
    TYPE_MAP,
    render_schema,
    table_primary_keys,
)


EXPECTED_DAILY_PK = ["market", "symbol", "trade_date"]


def validate_contract() -> list[str]:
    errors: list[str] = []
    table_names = [table.name for table in TABLES]
    if len(table_names) != len(set(table_names)):
        errors.append("duplicate table names in schema contract")

    for table in TABLES:
        column_names = [column.name for column in table.columns]
        if len(column_names) != len(set(column_names)):
            errors.append(f"{table.name}: duplicate column names")
        for column in table.columns:
            if column.logical_type not in TYPE_MAP["sqlite"]:
                errors.append(f"{table.name}.{column.name}: unknown logical type {column.logical_type}")
        missing_pk = [column for column in table.primary_key if column not in column_names]
        if missing_pk:
            errors.append(f"{table.name}: primary key references missing columns {missing_pk}")
        for index_name, index_columns in table.indexes:
            if not index_name:
                errors.append(f"{table.name}: index has empty name")
            missing_index = [column for column in index_columns if column not in column_names]
            if missing_index:
                errors.append(f"{table.name}.{index_name}: index references missing columns {missing_index}")

    daily_pk = table_primary_keys().get("market_bars_daily")
    if daily_pk != EXPECTED_DAILY_PK:
        errors.append(f"market_bars_daily primary key drift: expected {EXPECTED_DAILY_PK}, got {daily_pk}")

    return errors


def validate_legacy_exports() -> list[str]:
    errors: list[str] = []
    expected_sqlite = render_schema("sqlite")
    expected_duckdb = render_schema("duckdb")

    if schema.SCHEMA_SQL != expected_sqlite:
        errors.append("storage/schema.py SCHEMA_SQL does not match render_schema('sqlite')")
    if schema.schema_sql() != expected_sqlite:
        errors.append("storage/schema.py schema_sql() does not match render_schema('sqlite')")
    if duckdb_schema.DUCKDB_SCHEMA_SQL != expected_duckdb:
        errors.append("storage/duckdb_schema.py DUCKDB_SCHEMA_SQL does not match render_schema('duckdb')")
    if duckdb_schema.TABLE_PRIMARY_KEYS != table_primary_keys():
        errors.append("storage/duckdb_schema.py TABLE_PRIMARY_KEYS does not match schema_contract")
    return errors


def validate_rendered_ddl() -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_sqlite_render())
    errors.extend(_validate_duckdb_render())
    return errors


def _validate_sqlite_render() -> list[str]:
    errors: list[str] = []
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(render_schema("sqlite"))
        for table in TABLES:
            rows = conn.execute(f"PRAGMA table_info({table.name})").fetchall()
            actual = [(row[1], _normalize_type(row[2])) for row in rows]
            expected = [(column.name, column.logical_type) for column in table.columns]
            if actual != expected:
                errors.append(f"sqlite {table.name}: column drift expected {expected}, got {actual}")
            index_rows = conn.execute(f"PRAGMA index_list({table.name})").fetchall()
            actual_indexes = {
                row[1]: tuple(
                    info_row[2]
                    for info_row in conn.execute(f"PRAGMA index_info({row[1]})").fetchall()
                )
                for row in index_rows
                if row[1].startswith("idx_")
            }
            expected_indexes = dict(table.indexes)
            if actual_indexes != expected_indexes:
                errors.append(
                    f"sqlite {table.name}: index drift expected {expected_indexes}, got {actual_indexes}"
                )
    finally:
        conn.close()
    return errors


def _validate_duckdb_render() -> list[str]:
    try:
        import duckdb
    except ImportError:
        return _validate_duckdb_render_static()

    errors: list[str] = []
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(render_schema("duckdb"))
        for table in TABLES:
            rows = conn.execute(f"PRAGMA table_info('{table.name}')").fetchall()
            actual = [(row[1], _normalize_type(row[2])) for row in rows]
            expected = [(column.name, column.logical_type) for column in table.columns]
            if actual != expected:
                errors.append(f"duckdb {table.name}: column drift expected {expected}, got {actual}")
    finally:
        conn.close()
    return errors


def _validate_duckdb_render_static() -> list[str]:
    """Validate DuckDB DDL without importing the optional duckdb runtime."""
    errors: list[str] = []
    ddl = render_schema("duckdb")
    for table in TABLES:
        if f"CREATE TABLE IF NOT EXISTS {table.name}" not in ddl:
            errors.append(f"duckdb {table.name}: CREATE TABLE statement missing")
        for column in table.columns:
            expected = f"{column.name} {TYPE_MAP['duckdb'][column.logical_type]}"
            if expected not in ddl:
                errors.append(f"duckdb {table.name}.{column.name}: column DDL missing {expected}")
        if table.primary_key:
            expected_pk = f"PRIMARY KEY ({', '.join(table.primary_key)})"
            if expected_pk not in ddl:
                errors.append(f"duckdb {table.name}: primary key DDL missing {expected_pk}")
    return errors


def _normalize_type(sql_type: str) -> str:
    normalized = sql_type.upper()
    if normalized in {"TEXT", "VARCHAR"}:
        return "text"
    if normalized in {"REAL", "DOUBLE", "FLOAT"}:
        return "float"
    if normalized in {"INTEGER", "BIGINT", "INT8"}:
        return "integer"
    return normalized.lower()


def main() -> int:
    errors = []
    errors.extend(validate_contract())
    errors.extend(validate_legacy_exports())
    errors.extend(validate_rendered_ddl())

    if errors:
        print("schema drift detected:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("schema contract OK: SQLite and DuckDB DDL are structurally equivalent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
