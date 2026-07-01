"""Polymarket Parquet loader — loads historical PM data from Parquet files.

Handles batch import of Polymarket market data from Parquet archives
into the market_pm_markets and market_pm_prices tables.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PMParquetLoader:
    """Load Polymarket data from Parquet files into staging / SQLite.

    Usage::

        loader = PMParquetLoader(input_dir="data/polymarket/exports")
        result = loader.load_all()
    """

    def __init__(self, input_dir: str = "", glob_pattern: str = "*.parquet"):
        self._input_dir = Path(input_dir) if input_dir else None
        self._glob_pattern = glob_pattern

    def load_all(self) -> dict[str, Any]:
        """Scan input directory and load all matching Parquet files."""
        if not self._input_dir or not self._input_dir.is_dir():
            return {"files_loaded": 0, "rows_loaded": 0, "error": "input_dir not found"}

        results = {"files_loaded": 0, "rows_loaded": 0, "errors": []}
        for parquet_path in sorted(self._input_dir.glob(self._glob_pattern)):
            try:
                count = self._load_file(parquet_path)
                results["files_loaded"] += 1
                results["rows_loaded"] += count
                logger.info("loaded %s: %d rows", parquet_path.name, count)
            except Exception as exc:
                results["errors"].append({"file": str(parquet_path), "error": str(exc)})
                logger.exception("failed to load %s", parquet_path)
        return results

    def _load_file(self, path: Path) -> int:
        """Load a single Parquet file. Returns row count."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas required for Parquet loading")

        df = pd.read_parquet(path)
        rows = df.to_dict(orient="records")
        collected_at = datetime.now(timezone.utc).isoformat()

        # Write as NDJSON staging
        output_dir = self._input_dir.parent / "staging" if self._input_dir else Path("data/polymarket/staging")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{path.stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.ndjson"

        count = 0
        with output_path.open("w", encoding="utf-8") as f:
            for row in rows:
                row["collected_at"] = collected_at
                row["source_file"] = str(path)
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                count += 1

        return count
