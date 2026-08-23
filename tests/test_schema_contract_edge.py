from __future__ import annotations

import sqlite3

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


def _authority_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(render_schema("sqlite"))
    conn.commit()
    return conn


def test_market_ingest_runs_source_index_is_optional_and_validated() -> None:
    from storage.schema_contract import (
        MARKET_INGEST_RUNS_INDEX_COLUMNS,
        ensure_market_ingest_runs_source_index,
        require_clean_sqlite_authority_schema,
    )

    conn = _authority_conn()
    try:
        conn.execute("DROP INDEX market_ingest_runs_source_idx")
        conn.commit()
        require_clean_sqlite_authority_schema(conn)

        ensure_market_ingest_runs_source_index(conn)
        conn.commit()
        require_clean_sqlite_authority_schema(conn)

        stored_ddl = conn.execute(
            "SELECT sql FROM main.sqlite_schema "
            "WHERE type='index' AND name='market_ingest_runs_source_idx'"
        ).fetchone()[0]
        assert stored_ddl == (
            "CREATE INDEX market_ingest_runs_source_idx "
            "ON market_ingest_runs (source)"
        )
        assert MARKET_INGEST_RUNS_INDEX_COLUMNS == {
            "market_ingest_runs_source_idx": ("source",),
            "market_ingest_runs_source_finished_idx": (
                "source",
                "finished_at DESC",
            ),
        }

        conn.execute("DROP INDEX market_ingest_runs_source_idx")
        conn.execute(
            "CREATE INDEX rogue_runs_idx ON market_ingest_runs (run_id)"
        )
        conn.commit()
        with pytest.raises(RuntimeError):
            require_clean_sqlite_authority_schema(conn)
    finally:
        conn.close()


def test_ensure_market_ingest_runs_source_index_is_idempotent() -> None:
    from storage.schema_contract import (
        ensure_market_ingest_runs_source_index,
        require_clean_sqlite_authority_schema,
    )

    conn = _authority_conn()
    try:
        ensure_market_ingest_runs_source_index(conn)
        ensure_market_ingest_runs_source_index(conn)
        conn.commit()
        require_clean_sqlite_authority_schema(conn)

        count = conn.execute(
            "SELECT COUNT(*) FROM main.sqlite_schema "
            "WHERE type='index' AND name='market_ingest_runs_source_idx'"
        ).fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_ensure_market_ingest_runs_projection_index_is_idempotent() -> None:
    """The (source, finished_at DESC) catalog index follows the same
    create-if-missing, validate-when-present contract as the source index."""
    from storage.schema_contract import (
        ensure_market_ingest_runs_source_index,
        require_clean_sqlite_authority_schema,
    )

    conn = _authority_conn()
    try:
        require_clean_sqlite_authority_schema(conn)
        ensure_market_ingest_runs_source_index(conn)
        conn.commit()
        require_clean_sqlite_authority_schema(conn)

        columns = tuple(
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                ("market_ingest_runs_source_finished_idx",),
            ).fetchall()
        )
        assert columns == ("source", "finished_at")

        ensure_market_ingest_runs_source_index(conn)
        conn.commit()
        require_clean_sqlite_authority_schema(conn)

        conn.execute("DROP INDEX market_ingest_runs_source_finished_idx")
        conn.execute(
            "CREATE INDEX market_ingest_runs_source_finished_idx "
            "ON market_ingest_runs (source)"
        )
        conn.commit()
        with pytest.raises(RuntimeError):
            require_clean_sqlite_authority_schema(conn)
    finally:
        conn.close()
