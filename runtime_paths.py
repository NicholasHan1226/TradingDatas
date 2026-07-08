"""SharedSignals-owned runtime path helpers."""

from __future__ import annotations

import os
from pathlib import Path


def sharedsignals_root() -> Path:
    return Path(os.environ.get("SHAREDSIGNALS_ROOT", "/opt/investment/SharedSignals"))


def runtime_root() -> Path:
    return Path(os.environ.get("SHAREDSIGNALS_RUNTIME_ROOT", sharedsignals_root() / "runtime"))


def marketdata_sqlite_path() -> Path:
    return Path(
        os.environ.get("SHAREDSIGNALS_MARKETDATA_DB")
        or os.environ.get("MARKETDATA_SQLITE")
        or os.environ.get("SHARED_SIGNALS_DB")
        or runtime_root() / "read_model" / "marketdata.sqlite"
    )


def marketdata_duckdb_path() -> Path:
    return Path(
        os.environ.get("SHAREDSIGNALS_DUCKDB")
        or sharedsignals_root() / "data" / "marketdata.duckdb"
    )
