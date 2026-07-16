"""Compatibility entry points for the SQLite-authoritative runtime projection."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dataset_registry import (
    TUSHARE_ALLOWED_API_NAMES,
    DatasetRegistry,
    load_dataset_registry,
)
from runtime_paths import marketdata_sqlite_path
from storage.receipt_projection import (
    load_interface_runtime_report,
    write_interface_runtime_cache,
)

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "watchdog_inputs" / "interface_runtime.json"


def expected_tushare_api_names(path: Path | None = None) -> set[str]:
    """Return the registry set; ``path`` remains an ignored legacy argument."""
    del path
    return set(TUSHARE_ALLOWED_API_NAMES)


def record_tushare_stats(
    stats: dict[str, Any],
    *,
    tier: str,
    started_at: str,
    finished_at: str,
    expected_api_names: Iterable[str] | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    db_path: Path | None = None,
    registry: DatasetRegistry | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Rebuild the diagnostic cache; supplied collector stats are non-authority."""

    del stats, tier, started_at, finished_at, expected_api_names
    effective_registry = registry or load_dataset_registry()
    effective_now = now or datetime.now(timezone.utc)
    report = load_interface_runtime_report(
        db_path or marketdata_sqlite_path(),
        effective_registry,
        now=effective_now,
    )
    write_interface_runtime_cache(report, output_path)
    return report
