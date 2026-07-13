"""Regression tests for fail-closed DuckDB additive migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

import duckdb

from storage.schema import SCHEMA_SQL
from storage.schema_contract import TABLES, Table, get_table, render_indexes, render_table


IDENTITY_COLUMNS = {"event_id", "revision", "source_family"}
INDUSTRY_TABLES = {
    "market_industry_snapshots",
    "market_industry_taxonomy",
    "market_industry_memberships",
}


def _create_sqlite(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _insert_sqlite_event(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            INSERT INTO market_events (
                event_hash, event_id, revision, source_family, provider,
                event_type, event_time, trade_date, market, symbol, title,
                content, url, source, source_file, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "same-hash",
                "authoritative-event-id",
                2,
                "tushare",
                "tushare_news",
                "news",
                "2026-07-12T01:00:00Z",
                "20260712",
                "Ashare",
                "000001.SZ",
                "sqlite-title",
                "sqlite-content",
                "https://example.invalid/current",
                "sqlite-source",
                "sqlite.json",
                "2026-07-12T01:01:00Z",
                '{"version":"sqlite"}',
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _legacy_event_table() -> Table:
    current = get_table("market_events")
    return Table(
        name=current.name,
        columns=tuple(
            column for column in current.columns if column.name not in IDENTITY_COLUMNS
        ),
        primary_key=current.primary_key,
        indexes=tuple(
            index
            for index in current.indexes
            if index[0]
            not in {"idx_market_events_identity", "idx_market_events_time_identity"}
        ),
    )


def _create_legacy_duckdb(path: Path) -> None:
    legacy = _legacy_event_table()
    conn = duckdb.connect(str(path))
    try:
        conn.execute(render_table(legacy, "duckdb"))
        for statement in render_indexes(legacy, "duckdb").splitlines():
            conn.execute(statement)
        conn.execute(
            """
            INSERT INTO market_events (
                event_hash, provider, event_type, event_time, trade_date,
                market, symbol, title, content, url, source, source_file,
                collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "same-hash",
                "tushare_news",
                "news",
                "2026-07-12T01:00:00Z",
                "20260712",
                "Ashare",
                "000001.SZ",
                "legacy-title-must-stay",
                "legacy-content-must-stay",
                "https://example.invalid/legacy",
                "legacy-source",
                "legacy.json",
                "2026-07-12T01:01:00Z",
                '{"version":"legacy-must-stay"}',
            ],
        )
    finally:
        conn.close()


def _duckdb_table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
    }


def test_create_schema_is_idempotent_and_creates_complete_contract(tmp_path: Path) -> None:
    from storage.duckdb_schema import create_schema

    conn = duckdb.connect(str(tmp_path / "fresh.duckdb"))
    try:
        create_schema(conn)
        create_schema(conn)
        assert _duckdb_table_names(conn) == {table.name for table in TABLES}

        for table in TABLES:
            expected = {name for name, _columns in table.indexes}
            actual = {
                str(row[0])
                for row in conn.execute(
                    "SELECT index_name FROM duckdb_indexes() WHERE table_name = ?",
                    [table.name],
                ).fetchall()
            }
            assert expected <= actual
    finally:
        conn.close()


def test_true_legacy_event_migration_backfills_only_identity(tmp_path: Path) -> None:
    import duckdb_merge
    from storage.storage_adapter import StorageAdapter

    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)
    _insert_sqlite_event(sqlite_path)
    _create_legacy_duckdb(duckdb_path)

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    result = duckdb_merge.run_merge(adapter=adapter, table="market_events")

    assert result["status"] == "ok", result
    assert result["reconciliation"]["market_events"]["status"] == "ok"
    assert result["reconciliation"]["market_events"]["identity_mismatches"] == 0

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        assert _duckdb_table_names(conn) == {table.name for table in TABLES}
        assert INDUSTRY_TABLES <= _duckdb_table_names(conn)
        row = conn.execute(
            """
            SELECT event_id, revision, source_family, title, content, raw_json
            FROM market_events WHERE event_hash = 'same-hash'
            """
        ).fetchone()
        assert row == (
            "authoritative-event-id",
            2,
            "tushare",
            "legacy-title-must-stay",
            "legacy-content-must-stay",
            '{"version":"legacy-must-stay"}',
        )
    finally:
        conn.close()


def test_same_count_with_invalid_identity_is_semantic_mismatch(tmp_path: Path) -> None:
    from storage.storage_adapter import StorageAdapter

    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)
    _insert_sqlite_event(sqlite_path)
    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    assert adapter.sync_sqlite_to_duckdb("market_events") == 1

    conn = duckdb.connect(str(duckdb_path))
    try:
        conn.execute(
            """
            UPDATE market_events
            SET event_id = NULL, revision = NULL, source_family = NULL
            WHERE event_hash = 'same-hash'
            """
        )
    finally:
        conn.close()

    details = adapter.reconcile_counts(["market_events"])["market_events"]
    assert details["sqlite_rows"] == details["duckdb_rows"] == 1
    assert details["status"] == "mismatch"
    assert details["mismatch_kind"] == "identity"
    assert details["duckdb_identity_invalid"] == 1
    assert details["identity_mismatches"] == 1


def test_nonempty_table_missing_not_null_column_rolls_back(tmp_path: Path) -> None:
    from storage.duckdb_schema import DuckDBSchemaError, create_schema

    conn = duckdb.connect(str(tmp_path / "not-null-drift.duckdb"))
    try:
        conn.execute(
            """
            CREATE TABLE market_bars_daily (
                market VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                close DOUBLE,
                PRIMARY KEY (market, symbol)
            )
            """
        )
        conn.execute(
            "INSERT INTO market_bars_daily VALUES ('Ashare', '000001.SZ', 10.0)"
        )

        with pytest.raises(DuckDBSchemaError, match="NOT NULL column"):
            create_schema(conn)

        columns = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'market_bars_daily'
                """
            ).fetchall()
        }
        assert columns == {"market", "symbol", "close"}
        assert not (INDUSTRY_TABLES & _duckdb_table_names(conn))
    finally:
        conn.close()


def test_index_ddl_failure_rolls_back_whole_schema(tmp_path: Path, monkeypatch) -> None:
    import storage.duckdb_schema as schema

    real_render_indexes = schema.render_indexes

    def broken_indexes(table: Table, dialect: str = "sqlite") -> str:
        rendered = real_render_indexes(table, dialect)
        if dialect == "duckdb" and table.name == "market_events":
            return rendered + "\nCREATE INDEX broken_idx ON market_events (missing_column);"
        return rendered

    monkeypatch.setattr(schema, "render_indexes", broken_indexes)
    conn = duckdb.connect(str(tmp_path / "bad-index.duckdb"))
    try:
        with pytest.raises(Exception, match="missing_column"):
            schema.create_schema(conn)
        assert _duckdb_table_names(conn) == set()
    finally:
        conn.close()


def test_empty_industry_tables_sync_and_reconcile_as_zero(tmp_path: Path) -> None:
    from storage.storage_adapter import StorageAdapter

    sqlite_path = tmp_path / "marketdata.sqlite"
    duckdb_path = tmp_path / "marketdata.duckdb"
    _create_sqlite(sqlite_path)
    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))

    for table in INDUSTRY_TABLES:
        assert adapter.sync_sqlite_to_duckdb(table) == 0

    reconciliation = adapter.reconcile_counts(sorted(INDUSTRY_TABLES))
    for table in INDUSTRY_TABLES:
        assert reconciliation[table] == {
            "sqlite_rows": 0,
            "duckdb_rows": 0,
            "delta": 0,
            "status": "ok",
        }


def test_reconcile_distinguishes_missing_source_and_mirror(tmp_path: Path) -> None:
    from storage.storage_adapter import StorageAdapter

    sqlite_path = tmp_path / "partial.sqlite"
    duckdb_path = tmp_path / "partial.duckdb"
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.execute("CREATE TABLE market_assets (market TEXT)")
    sqlite_conn.commit()
    sqlite_conn.close()

    duckdb_conn = duckdb.connect(str(duckdb_path))
    duckdb_conn.execute(render_table(get_table("market_events"), "duckdb"))
    duckdb_conn.close()

    adapter = StorageAdapter(str(sqlite_path), str(duckdb_path))
    reconciliation = adapter.reconcile_counts(
        ["market_events", "market_industry_snapshots"]
    )
    assert reconciliation["market_events"]["status"] == "source_missing"
    assert reconciliation["market_industry_snapshots"]["status"] == "source_missing"

    full_sqlite = tmp_path / "full.sqlite"
    empty_duckdb = tmp_path / "empty.duckdb"
    _create_sqlite(full_sqlite)
    duckdb.connect(str(empty_duckdb)).close()
    missing_mirror = StorageAdapter(str(full_sqlite), str(empty_duckdb)).reconcile_counts(
        ["market_industry_snapshots"]
    )
    assert missing_mirror["market_industry_snapshots"]["status"] == "mirror_missing"
