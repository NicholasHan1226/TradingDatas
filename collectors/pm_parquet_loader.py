"""Backward-compatible entry point for pm_parquet_loader.

Replaces the broken symlink to /opt/investment/MarketGraph/...
Delegates to collectors.polymarket.parquet_loader.PMParquetLoader.
"""

from collectors.polymarket.parquet_loader import PMParquetLoader

CollectorClass = PMParquetLoader
MAIN_COLLECTOR = "pm_parquet_loader"

__all__ = ["PMParquetLoader", "CollectorClass", "MAIN_COLLECTOR"]
