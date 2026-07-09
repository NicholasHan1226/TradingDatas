"""Canonical storage schema contract for SQLite and DuckDB.

This module is the single source of truth for the SharedSignals table
storage contract.  SQLite remains the authoritative write model; DuckDB mirrors
the same logical structure with dialect-specific column types.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Column:
    name: str
    logical_type: str
    nullable: bool = True


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    indexes: tuple[tuple[str, tuple[str, ...]], ...] = ()


TYPE_MAP: dict[str, dict[str, str]] = {
    "sqlite": {
        "text": "TEXT",
        "float": "REAL",
        "integer": "INTEGER",
    },
    "duckdb": {
        "text": "VARCHAR",
        "float": "DOUBLE",
        "integer": "BIGINT",
    },
}


TABLES: tuple[Table, ...] = (
    Table(
        name="market_assets",
        columns=(
            Column("market", "text", False),
            Column("symbol", "text", False),
            Column("name", "text"),
            Column("asset_type", "text"),
            Column("exchange", "text"),
            Column("sector", "text"),
            Column("list_date", "text"),
            Column("last_trade_date", "text"),
            Column("expiry_date", "text"),
            Column("status", "text"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("updated_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("market", "symbol"),
        indexes=(
            ("idx_market_assets_provider_market_symbol", ("provider", "market", "symbol")),
            ("idx_market_assets_updated_at", ("updated_at",)),
        ),
    ),
    Table(
        name="market_relationships",
        columns=(
            Column("relationship_hash", "text"),
            Column("provider", "text"),
            Column("relationship_type", "text"),
            Column("market", "text"),
            Column("parent_symbol", "text"),
            Column("parent_name", "text"),
            Column("child_symbol", "text"),
            Column("child_name", "text"),
            Column("start_date", "text"),
            Column("end_date", "text"),
            Column("trade_date", "text"),
            Column("weight", "float"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("relationship_hash",),
        indexes=(
            ("idx_market_relationships_parent", ("provider", "relationship_type", "parent_symbol")),
            ("idx_market_relationships_child", ("child_symbol", "relationship_type")),
            ("idx_market_relationships_trade_date", ("trade_date",)),
            ("idx_market_relationships_collected_at", ("collected_at",)),
        ),
    ),
    Table(
        name="market_bars_daily",
        columns=(
            Column("market", "text", False),
            Column("symbol", "text", False),
            Column("trade_date", "text", False),
            Column("open", "float"),
            Column("high", "float"),
            Column("low", "float"),
            Column("close", "float"),
            Column("volume", "float"),
            Column("amount", "float"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("market", "symbol", "trade_date"),
        indexes=(
            ("idx_market_bars_daily_lookup", ("market", "symbol", "trade_date")),
        ),
    ),
    Table(
        name="market_bars_intraday",
        columns=(
            Column("market", "text", False),
            Column("symbol", "text", False),
            Column("bar_time", "text", False),
            Column("trade_date", "text"),
            Column("interval", "text"),
            Column("open", "float"),
            Column("high", "float"),
            Column("low", "float"),
            Column("close", "float"),
            Column("volume", "float"),
            Column("amount", "float"),
            Column("bid_price", "float"),
            Column("ask_price", "float"),
            Column("bid_size", "float"),
            Column("ask_size", "float"),
            Column("last_trade_date", "text"),
            Column("expiry_date", "text"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("market", "symbol", "bar_time", "interval", "provider"),
        indexes=(
            ("idx_market_bars_intraday_lookup", ("market", "symbol", "trade_date", "interval")),
            ("idx_market_bars_intraday_market_date_time", ("market", "trade_date", "interval", "bar_time")),
            ("idx_market_bars_intraday_collected_at", ("market", "collected_at")),
        ),
    ),
    Table(
        name="market_events",
        columns=(
            Column("event_hash", "text"),
            Column("provider", "text"),
            Column("event_type", "text"),
            Column("event_time", "text"),
            Column("trade_date", "text"),
            Column("market", "text"),
            Column("symbol", "text"),
            Column("title", "text"),
            Column("content", "text"),
            Column("url", "text"),
            Column("source", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("event_hash",),
        indexes=(
            ("idx_market_events_lookup", ("provider", "event_type", "event_time")),
            ("idx_market_events_trade_date", ("trade_date",)),
            ("idx_market_events_market_symbol_trade_date", ("market", "symbol", "trade_date")),
            ("idx_market_events_collected_at", ("collected_at",)),
        ),
    ),
    Table(
        name="market_pm_markets",
        columns=(
            Column("market_id", "text"),
            Column("question", "text"),
            Column("slug", "text"),
            Column("end_date", "text"),
            Column("volume", "float"),
            Column("liquidity", "float"),
            Column("active", "text"),
            Column("closed", "text"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("market_id",),
    ),
    Table(
        name="market_pm_prices",
        columns=(
            Column("price_hash", "text"),
            Column("market_id", "text"),
            Column("token_id", "text"),
            Column("price_time", "text"),
            Column("price", "float"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("price_hash",),
        indexes=(
            ("idx_market_pm_prices_lookup", ("market_id", "price_time")),
        ),
    ),
    Table(
        name="market_factors",
        columns=(
            Column("factor_hash", "text"),
            Column("market", "text"),
            Column("symbol", "text"),
            Column("factor_name", "text"),
            Column("event_time", "text"),
            Column("value", "float"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("factor_hash",),
        indexes=(
            ("idx_market_factors_symbol", ("symbol", "event_time")),
            ("idx_market_factors_provider_event_time", ("provider", "event_time")),
            ("idx_market_factors_market_event_time", ("market", "event_time")),
            ("idx_market_factors_collected_at", ("collected_at",)),
        ),
    ),
    Table(
        name="market_fund_portfolio",
        columns=(
            Column("portfolio_hash", "text"),
            Column("market", "text"),
            Column("symbol", "text"),
            Column("holding_symbol", "text"),
            Column("ann_date", "text"),
            Column("end_date", "text"),
            Column("market_value", "float"),
            Column("amount", "float"),
            Column("stk_mkv_ratio", "float"),
            Column("stk_float_ratio", "float"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("collected_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("portfolio_hash",),
        indexes=(
            ("idx_market_fund_portfolio_symbol_ann", ("symbol", "ann_date")),
            ("idx_market_fund_portfolio_holding_ann", ("holding_symbol", "ann_date")),
            ("idx_market_fund_portfolio_provider_ann", ("provider", "ann_date")),
            ("idx_market_fund_portfolio_collected_at", ("collected_at",)),
        ),
    ),
    Table(
        name="market_ingest_runs",
        columns=(
            Column("run_id", "text"),
            Column("started_at", "text"),
            Column("finished_at", "text"),
            Column("status", "text"),
            Column("source", "text"),
            Column("rows_read", "integer"),
            Column("rows_written", "integer"),
            Column("notes", "text"),
        ),
        primary_key=("run_id",),
    ),
    Table(
        name="market_coverage_status",
        columns=(
            Column("market", "text", False),
            Column("trade_date", "text", False),
            Column("symbol", "text", False),
            Column("coverage_status", "text", False),
            Column("reason", "text"),
            Column("provider", "text"),
            Column("source_file", "text"),
            Column("updated_at", "text"),
            Column("raw_json", "text"),
        ),
        primary_key=("market", "trade_date", "symbol"),
        indexes=(
            ("idx_market_coverage_status_lookup", ("market", "trade_date", "coverage_status")),
        ),
    ),
    Table(
        name="market_backfill_status",
        columns=(
            Column("market", "text", False),
            Column("dataset", "text", False),
            Column("trade_date", "text", False),
            Column("status", "text", False),
            Column("rows_read", "integer"),
            Column("rows_written", "integer"),
            Column("error", "text"),
            Column("updated_at", "text", False),
        ),
        primary_key=("market", "dataset", "trade_date"),
        indexes=(
            ("idx_market_backfill_status_lookup", ("market", "dataset", "status")),
        ),
    ),
    Table(
        name="provider_interface_matrix",
        columns=(
            Column("matrix_id", "text"),
            Column("layer", "text", False),
            Column("interface_name", "text", False),
            Column("provider", "text"),
            Column("source_family", "text"),
            Column("mcp_tool", "text"),
            Column("collector_scripts", "text"),
            Column("collection_schedule", "text"),
            Column("storage_kind", "text"),
            Column("storage_path", "text"),
            Column("read_model_table", "text"),
            Column("actual_state", "text"),
            Column("updated_at", "text", False),
        ),
        primary_key=("matrix_id",),
        indexes=(
            ("idx_provider_interface_matrix_lookup", ("provider", "layer", "interface_name")),
        ),
    ),
)


def get_table(name: str) -> Table:
    """Return a table contract by name."""
    for table in TABLES:
        if table.name == name:
            return table
    raise KeyError(f"unknown table: {name}")


def render_table(table: Table, dialect: str) -> str:
    """Render a single CREATE TABLE statement for sqlite or duckdb."""
    type_map = TYPE_MAP[dialect]
    lines = []
    for column in table.columns:
        column_type = type_map[column.logical_type]
        nullable = "" if column.nullable else " NOT NULL"
        lines.append(f"    {column.name} {column_type}{nullable}")
    if table.primary_key:
        lines.append(f"    PRIMARY KEY ({', '.join(table.primary_key)})")
    body = ",\n".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n{body}\n);"


def render_indexes(table: Table) -> str:
    """Render CREATE INDEX statements for a table."""
    statements = []
    for index_name, columns in table.indexes:
        statements.append(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table.name} ({', '.join(columns)});"
        )
    return "\n".join(statements)


def render_schema(dialect: str) -> str:
    """Return full schema DDL for sqlite or duckdb."""
    if dialect not in TYPE_MAP:
        raise ValueError(f"unsupported dialect: {dialect}")

    statements: list[str] = []
    for table in TABLES:
        statements.append(render_table(table, dialect))
        index_sql = render_indexes(table)
        if index_sql:
            statements.append(index_sql)
    return "\n\n".join(statements) + "\n"


def table_primary_keys() -> dict[str, list[str]]:
    """Return the primary-key columns for every table."""
    return {table.name: list(table.primary_key) for table in TABLES}


def table_names() -> list[str]:
    """Return table names in dependency-safe order."""
    return [table.name for table in TABLES]


def table_with_name(table: Table, name: str) -> Table:
    """Return a copy of a table contract with a different table name."""
    return replace(table, name=name)
