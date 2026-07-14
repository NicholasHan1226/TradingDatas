from __future__ import annotations

from storage.schema_contract import get_table, render_schema, table_names
from storage.storage_adapter import AUTHORITATIVE_SNAPSHOT_TABLES


EXPECTED_TABLES = {
    "market_sector_flow_snapshots_v2",
    "market_sector_flow_industries_v2",
    "market_sector_flow_constituents_v2",
}


def test_sector_flow_v2_tables_are_in_canonical_contract() -> None:
    assert EXPECTED_TABLES.issubset(set(table_names()))


def test_snapshot_contract_exposes_pit_source_coverage_and_runtime_semantics() -> None:
    table = get_table("market_sector_flow_snapshots_v2")
    columns = {column.name for column in table.columns}
    assert {
        "snapshot_id",
        "schema_version",
        "fact_kind",
        "trade_date",
        "effective_at",
        "available_at",
        "collected_at",
        "provider",
        "source_run_id",
        "source_hash",
        "industry_snapshot_id",
        "status",
        "expected_industry_count",
        "observed_industry_count",
        "expected_constituent_count",
        "observed_constituent_count",
        "industry_coverage_ratio",
        "constituent_coverage_ratio",
        "runtime_status",
        "runtime_reason",
    }.issubset(columns)
    assert table.primary_key == ("snapshot_id",)


def test_fact_tables_are_snapshot_scoped_and_do_not_contain_scores() -> None:
    industry = get_table("market_sector_flow_industries_v2")
    constituent = get_table("market_sector_flow_constituents_v2")
    assert industry.primary_key == ("snapshot_id", "industry_code")
    assert constituent.primary_key == ("snapshot_id", "industry_code", "symbol")
    names = {column.name for table in (industry, constituent) for column in table.columns}
    assert {"effective_at", "available_at", "provider", "source_hash", "net_inflow"}.issubset(names)
    assert not {"score", "rank_score", "signal", "direction"}.intersection(names)


def test_sector_flow_v2_schema_renders_for_sqlite_and_duckdb() -> None:
    for dialect in ("sqlite", "duckdb"):
        ddl = render_schema(dialect)
        for table_name in EXPECTED_TABLES:
            assert f"CREATE TABLE IF NOT EXISTS {table_name}" in ddl


def test_sector_flow_v2_tables_are_authoritative_mirror_snapshots() -> None:
    assert EXPECTED_TABLES.issubset(AUTHORITATIVE_SNAPSHOT_TABLES)
