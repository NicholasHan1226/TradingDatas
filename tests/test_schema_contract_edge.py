from __future__ import annotations

import pytest

from storage import duckdb_schema
from storage.schema_contract import Column, Table, get_table, render_schema, render_table, table_primary_keys


def test_schema_contract_unknown_dialect_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported dialect"):
        render_schema("postgres")


def test_schema_contract_unknown_table_raises_key_error() -> None:
    with pytest.raises(KeyError, match="unknown table"):
        get_table("missing_table")


def test_schema_contract_table_without_pk_renders_without_primary_key() -> None:
    table = Table(
        name="no_pk_table",
        columns=(
            Column("symbol", "text", nullable=False),
            Column("value", "float"),
        ),
    )

    ddl = render_table(table, "sqlite")

    assert "CREATE TABLE IF NOT EXISTS no_pk_table" in ddl
    assert "symbol TEXT NOT NULL" in ddl
    assert "value REAL" in ddl
    assert "PRIMARY KEY" not in ddl


def test_duckdb_schema_exports_primary_keys() -> None:
    assert duckdb_schema.TABLE_PRIMARY_KEYS == table_primary_keys()
    assert duckdb_schema.TABLE_PRIMARY_KEYS["market_relationships"] == ["relationship_hash"]
    assert duckdb_schema.TABLE_PRIMARY_KEYS["market_fund_portfolio"] == ["portfolio_hash"]
