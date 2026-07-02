"""SharedSignals SQLite storage schema.

The canonical table contract lives in :mod:`storage.schema_contract`; this
module keeps the historical SQLite-facing exports stable.
"""

from __future__ import annotations

from .schema_contract import render_schema, table_names

SCHEMA_SQL = render_schema("sqlite")
TABLE_NAMES = table_names()


def schema_sql() -> str:
    """Return the full SQLite schema DDL string."""
    return SCHEMA_SQL


def table_names() -> list[str]:
    """Return the list of table names in dependency-safe order."""
    from .schema_contract import table_names as _table_names

    return _table_names()
