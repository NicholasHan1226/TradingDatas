from __future__ import annotations

import pytest

from storage.schema_contract import (
    Column,
    Table,
    get_table,
    render_schema,
    render_table,
    table_names,
    table_primary_keys,
)


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


def test_schema_contract_is_sqlite_only() -> None:
    with pytest.raises(ValueError, match="unsupported dialect"):
        render_schema("duckdb")
    with pytest.raises(ValueError, match="unsupported dialect"):
        render_table(get_table("market_ingest_runs"), "duckdb")


def test_clean_slate_schema_contains_only_fact_and_receipt_authorities() -> None:
    assert table_names() == ["provider_dataset_rows", "market_ingest_runs"]
    assert table_primary_keys() == {
        "provider_dataset_rows": ["dataset_id", "provider", "schema_major", "row_key"],
        "market_ingest_runs": ["run_id"],
    }

    ddl = render_schema("sqlite")
    assert ddl.count("CREATE TABLE IF NOT EXISTS") == 2
    assert "CREATE TABLE IF NOT EXISTS provider_dataset_rows" in ddl
    assert "CREATE TABLE IF NOT EXISTS market_ingest_runs" in ddl
    assert "market_events" not in ddl
    assert "market_bars_daily" not in ddl
