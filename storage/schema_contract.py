"""Clean-slate provider-native SQLite schema contract.

Fresh TradingDatas databases contain only the generic provider fact authority
and its transaction-scoped receipt authority. Historical market business
tables and DuckDB rendering are intentionally outside this contract.
"""

from __future__ import annotations

import sqlite3
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
    unique_indexes: tuple[tuple[str, tuple[str, ...], str], ...] = ()


TYPE_MAP: dict[str, dict[str, str]] = {
    "sqlite": {
        "text": "TEXT",
        "float": "REAL",
        "integer": "INTEGER",
    },
}

PROVIDER_DATASET_ROWS_TABLE = "provider_dataset_rows"
PROVIDER_DATASET_ROWS_COLUMNS: tuple[tuple[str, str, bool, str | None, int], ...] = (
    ("dataset_id", "TEXT", False, None, 1),
    ("provider", "TEXT", False, None, 2),
    ("schema_major", "INTEGER", False, None, 3),
    ("ingested_schema_version", "TEXT", False, None, 0),
    ("row_key", "TEXT", False, None, 4),
    ("observed_at", "TEXT", True, None, 0),
    ("partition_value", "TEXT", True, None, 0),
    ("payload_json", "TEXT", False, None, 0),
    ("payload_hash", "TEXT", False, None, 0),
    ("quality_state", "TEXT", False, None, 0),
    ("quality_issues_json", "TEXT", False, "'[]'", 0),
    ("collected_at", "TEXT", False, None, 0),
    ("receipt_id", "TEXT", False, None, 0),
    ("revision", "INTEGER", False, None, 0),
)
PROVIDER_DATASET_ROWS_INDEX_COLUMNS: dict[str, tuple[str, ...]] = {
    "provider_dataset_rows_partition_idx": (
        "dataset_id",
        "provider",
        "schema_major",
        "partition_value",
        "row_key",
    ),
    "provider_dataset_rows_observed_idx": (
        "dataset_id",
        "provider",
        "schema_major",
        "observed_at",
        "row_key",
    ),
    "provider_dataset_rows_quality_idx": (
        "dataset_id",
        "provider",
        "schema_major",
        "quality_state",
    ),
    "provider_dataset_rows_coverage_idx": (
        "dataset_id",
        "schema_major",
        "observed_at",
    ),
    "provider_dataset_rows_receipt_idx": ("receipt_id",),
}
PROVIDER_DATASET_ROWS_CREATE_SQL = """CREATE TABLE IF NOT EXISTS provider_dataset_rows (
    dataset_id          TEXT NOT NULL,
    provider            TEXT NOT NULL,
    schema_major        INTEGER NOT NULL CHECK (schema_major >= 1),
    ingested_schema_version TEXT NOT NULL,
    row_key             TEXT NOT NULL,
    observed_at         TEXT,
    partition_value     TEXT,
    payload_json        TEXT NOT NULL
                        CHECK (json_valid(payload_json)
                               AND json_type(payload_json) = 'object'),
    payload_hash        TEXT NOT NULL,
    quality_state       TEXT NOT NULL CHECK (quality_state IN ('valid', 'degraded')),
    quality_issues_json TEXT NOT NULL DEFAULT '[]'
                        CHECK (json_valid(quality_issues_json)
                               AND json_type(quality_issues_json) = 'array'),
    collected_at        TEXT NOT NULL,
    receipt_id          TEXT NOT NULL,
    revision            INTEGER NOT NULL CHECK (revision >= 1),
    PRIMARY KEY (dataset_id, provider, schema_major, row_key)
)"""
PROVIDER_DATASET_ROWS_INDEX_SQL: tuple[str, ...] = tuple(
    f"CREATE INDEX IF NOT EXISTS {name} ON {PROVIDER_DATASET_ROWS_TABLE} "
    f"({', '.join(columns)})"
    for name, columns in PROVIDER_DATASET_ROWS_INDEX_COLUMNS.items()
)
PROVIDER_DATASET_ROWS_DDL = (
    ";\n".join((PROVIDER_DATASET_ROWS_CREATE_SQL, *PROVIDER_DATASET_ROWS_INDEX_SQL))
    + ";\n"
)

PROVIDER_DATASET_ROWS_CONTRACT = Table(
    name=PROVIDER_DATASET_ROWS_TABLE,
    columns=tuple(
        Column(
            name=name,
            logical_type={"TEXT": "text", "INTEGER": "integer"}[sqlite_type],
            nullable=nullable,
        )
        for name, sqlite_type, nullable, _default, _pk_position in PROVIDER_DATASET_ROWS_COLUMNS
    ),
    primary_key=("dataset_id", "provider", "schema_major", "row_key"),
    indexes=tuple(PROVIDER_DATASET_ROWS_INDEX_COLUMNS.items()),
)

MARKET_INGEST_RUNS_INDEX_COLUMNS: dict[str, tuple[str, ...]] = {
    "market_ingest_runs_source_idx": ("source",),
    "market_ingest_runs_source_finished_idx": ("source", "finished_at DESC"),
}

MARKET_INGEST_RUNS_CONTRACT = Table(
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
    indexes=tuple(MARKET_INGEST_RUNS_INDEX_COLUMNS.items()),
)

TABLES: tuple[Table, ...] = (
    PROVIDER_DATASET_ROWS_CONTRACT,
    MARKET_INGEST_RUNS_CONTRACT,
)


def _expected_table_xinfo(table: Table) -> tuple[tuple[object, ...], ...]:
    primary_key_positions = {
        name: index for index, name in enumerate(table.primary_key, start=1)
    }
    if table.name == PROVIDER_DATASET_ROWS_TABLE:
        return tuple(
            (
                index,
                name,
                sqlite_type,
                int(not nullable),
                default,
                primary_key_position,
                0,
            )
            for index, (
                name,
                sqlite_type,
                nullable,
                default,
                primary_key_position,
            ) in enumerate(PROVIDER_DATASET_ROWS_COLUMNS)
        )
    return tuple(
        (
            index,
            column.name,
            {"text": "TEXT", "integer": "INTEGER"}[column.logical_type],
            int(not column.nullable),
            None,
            primary_key_positions.get(column.name, 0),
            0,
        )
        for index, column in enumerate(table.columns)
    )


def _sqlite_schema_sql(ddl: str) -> str:
    """Return SQLite's stored SQL text for one canonical DDL statement."""

    normalized = ddl.strip().removesuffix(";")
    for object_type in ("TABLE", "INDEX"):
        prefix = f"CREATE {object_type} IF NOT EXISTS "
        if normalized.startswith(prefix):
            return f"CREATE {object_type} {normalized.removeprefix(prefix)}"
    raise ValueError("canonical SQLite DDL must use CREATE ... IF NOT EXISTS")


def _expected_sqlite_objects(
    include_provider_coverage_index: bool = True,
    market_ingest_run_indexes: frozenset[str] = frozenset(),
) -> dict[tuple[str, str, str], str]:
    expected = {
        ("table", table.name, table.name): _sqlite_schema_sql(
            render_table(table, "sqlite")
        )
        for table in TABLES
    }
    provider_index_names = PROVIDER_DATASET_ROWS_INDEX_COLUMNS
    if not include_provider_coverage_index:
        provider_index_names = {
            name: columns
            for name, columns in provider_index_names.items()
            if name != "provider_dataset_rows_coverage_idx"
        }
    expected.update(
        {
            ("index", name, PROVIDER_DATASET_ROWS_TABLE): _sqlite_schema_sql(
                "CREATE INDEX IF NOT EXISTS "
                f"{name} ON {PROVIDER_DATASET_ROWS_TABLE} "
                f"({', '.join(columns)});"
            )
            for name, columns in provider_index_names.items()
        }
    )
    present = set(market_ingest_run_indexes) & set(MARKET_INGEST_RUNS_INDEX_COLUMNS)
    expected.update(
        {
            ("index", name, "market_ingest_runs"): _sqlite_schema_sql(
                "CREATE INDEX IF NOT EXISTS "
                f"{name} ON market_ingest_runs "
                f"({', '.join(columns)});"
            )
            for name, columns in MARKET_INGEST_RUNS_INDEX_COLUMNS.items()
            if name in present
        }
    )
    return expected


def require_clean_sqlite_authority_schema(conn: sqlite3.Connection) -> None:
    """Require the exact two-table clean-slate authority on a live connection.

    Runtime writers call this after ``BEGIN IMMEDIATE``.  Rejecting all views,
    triggers, and undeclared tables/indexes prevents a pre-provisioned SQLite
    object from silently rewriting or ignoring either facts or receipts.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")

    expected_tables = {table.name: _expected_table_xinfo(table) for table in TABLES}
    for table_name, expected in expected_tables.items():
        observed = tuple(
            tuple(row)
            for row in conn.execute(
                f"PRAGMA main.table_xinfo('{table_name}')"
            ).fetchall()
        )
        if observed != expected:
            raise RuntimeError(f"{table_name} table is missing or incompatible")

    objects = {
        (str(row[0]), str(row[1]), str(row[2])): row[3]
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM main.sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    observed_names = {name for (_type, name, _table) in objects}
    expected_objects = _expected_sqlite_objects(
        include_provider_coverage_index=(
            "provider_dataset_rows_coverage_idx" in observed_names
        ),
        market_ingest_run_indexes=frozenset(
            observed_names & set(MARKET_INGEST_RUNS_INDEX_COLUMNS)
        ),
    )
    if objects != expected_objects:
        raise RuntimeError(
            "SQLite authority contains unsupported tables, views, triggers, or indexes"
        )

    provider_indexes = {
        str(row[1]): (int(row[2]), str(row[3]), int(row[4]))
        for row in conn.execute(
            "PRAGMA main.index_list('provider_dataset_rows')"
        ).fetchall()
        if str(row[3]) == "c"
    }
    expected_provider_indexes = {
        name: (0, "c", 0) for name in PROVIDER_DATASET_ROWS_INDEX_COLUMNS
    }
    # The coverage index is optional on pre-existing stores: the first writer
    # transaction upgrades them in place via
    # ensure_provider_dataset_rows_coverage_index.  Absence is tolerated here,
    # but a present index must match the declared column order exactly.
    if "provider_dataset_rows_coverage_idx" not in provider_indexes:
        expected_provider_indexes.pop("provider_dataset_rows_coverage_idx", None)
    if provider_indexes != expected_provider_indexes:
        raise RuntimeError("provider_dataset_rows indexes are incompatible")
    for name, expected_columns in PROVIDER_DATASET_ROWS_INDEX_COLUMNS.items():
        if (
            name == "provider_dataset_rows_coverage_idx"
            and name not in provider_indexes
        ):
            continue
        columns = tuple(
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                (name,),
            ).fetchall()
        )
        if columns != expected_columns:
            raise RuntimeError("provider_dataset_rows indexes are incompatible")

    receipt_custom_indexes = tuple(
        row
        for row in conn.execute(
            "PRAGMA main.index_list('market_ingest_runs')"
        ).fetchall()
        if str(row[3]) == "c"
    )
    for name, expected_columns in MARKET_INGEST_RUNS_INDEX_COLUMNS.items():
        if name not in {str(row[1]) for row in receipt_custom_indexes}:
            continue
        columns = tuple(
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                (name,),
            ).fetchall()
        )
        if columns != tuple(
            item.split()[0] for item in expected_columns
        ):
            raise RuntimeError("market_ingest_runs indexes are incompatible")
        receipt_custom_indexes = tuple(
            row for row in receipt_custom_indexes if str(row[1]) != name
        )
    if receipt_custom_indexes:
        raise RuntimeError("market_ingest_runs indexes are incompatible")


def _type_map(dialect: str) -> dict[str, str]:
    try:
        return TYPE_MAP[dialect]
    except KeyError:
        raise ValueError(f"unsupported dialect: {dialect}") from None


def get_table(name: str) -> Table:
    """Return one clean-slate table contract by name."""

    for table in TABLES:
        if table.name == name:
            return table
    raise KeyError(f"unknown table: {name}")


def render_table(table: Table, dialect: str) -> str:
    """Render one SQLite CREATE TABLE statement."""

    type_map = _type_map(dialect)
    if table.name == PROVIDER_DATASET_ROWS_TABLE:
        return f"{PROVIDER_DATASET_ROWS_CREATE_SQL};"
    lines = []
    for column in table.columns:
        column_type = type_map[column.logical_type]
        nullable = "" if column.nullable else " NOT NULL"
        lines.append(f"    {column.name} {column_type}{nullable}")
    if table.primary_key:
        lines.append(f"    PRIMARY KEY ({', '.join(table.primary_key)})")
    body = ",\n".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n{body}\n);"


def render_indexes(table: Table, dialect: str = "sqlite") -> str:
    """Render SQLite indexes for one clean-slate table."""

    _type_map(dialect)
    statements = [
        f"CREATE INDEX IF NOT EXISTS {name} ON {table.name} ({', '.join(columns)});"
        for name, columns in table.indexes
    ]
    for name, columns, where_clause in table.unique_indexes:
        statements.append(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table.name} "
            f"({', '.join(columns)}) WHERE {where_clause};"
        )
    return "\n".join(statements)


def render_schema(
    dialect: str,
    *,
    include_provider_dataset_rows: bool = True,
) -> str:
    """Return the fresh SQLite schema; DuckDB is intentionally unsupported."""

    _type_map(dialect)
    statements: list[str] = []
    for table in TABLES:
        if (
            table.name == PROVIDER_DATASET_ROWS_TABLE
            and not include_provider_dataset_rows
        ):
            continue
        statements.append(render_table(table, dialect))
        index_sql = render_indexes(table, dialect)
        if index_sql:
            statements.append(index_sql)
    return "\n\n".join(statements) + "\n"


def table_primary_keys() -> dict[str, list[str]]:
    """Return primary-key columns for the two clean-slate authorities."""

    return {table.name: list(table.primary_key) for table in TABLES}


def table_names() -> list[str]:
    """Return clean-slate table names in creation order."""

    return [table.name for table in TABLES]


def table_with_name(table: Table, name: str) -> Table:
    """Return a copy of a table contract with a different name."""

    return replace(table, name=name)


def ensure_market_ingest_runs_source_index(conn: sqlite3.Connection) -> None:
    """Create the market_ingest_runs source index if missing (idempotent).

    Called inside the writer's IMMEDIATE transaction after schema validation,
    so existing read-only releases without the index keep validating clean
    while the first write on this release upgrades the store in place.
    """

    existing = {
        row[0]
        for row in conn.execute("PRAGMA index_list(market_ingest_runs)").fetchall()
    }
    if "market_ingest_runs_source_idx" not in existing:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS market_ingest_runs_source_idx"
            " ON market_ingest_runs (source)"
        )
    if "market_ingest_runs_source_finished_idx" not in existing:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS market_ingest_runs_source_finished_idx"
            " ON market_ingest_runs (source, finished_at DESC)"
        )


def ensure_provider_dataset_rows_coverage_index(
    conn: sqlite3.Connection,
) -> None:
    """Create the provider_dataset_rows coverage index if missing (idempotent).

    Serves the catalog coverage aggregation (COUNT / MIN / MAX(observed_at)
    per ``dataset_id`` + ``schema_major``).  Same upgrade-on-first-write
    contract as the market_ingest_runs ensures: read-only releases created
    before this index keep validating clean, and the first writer
    transaction creates it in place.
    """

    existing = {
        row[1]
        for row in conn.execute(
            "PRAGMA index_list(provider_dataset_rows)"
        ).fetchall()
    }
    if "provider_dataset_rows_coverage_idx" not in existing:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS provider_dataset_rows_coverage_idx"
            f" ON {PROVIDER_DATASET_ROWS_TABLE}"
            " (dataset_id, schema_major, observed_at)"
        )
