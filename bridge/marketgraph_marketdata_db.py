"""Compatibility bridge for the SharedSignals marketdata read model.

Historically this filename was a symlink into MarketGraph. SharedSignals now
owns the read-model schema locally, so the compatibility surface lives in this
repository and must not depend on a MarketGraph checkout being present.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from storage.schema import SCHEMA_SQL


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite read-model database and ensure the canonical schema."""
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn
