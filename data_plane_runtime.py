"""Lazy construction for the provider-neutral TradingDatas V1 data plane."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_service import CatalogService
    from dataset_registry import DatasetRegistry
    from query_cursor import SignedCursorCodec
    from query_service import QueryService


@dataclass(frozen=True)
class DataPlaneRuntime:
    registry: DatasetRegistry
    cursor_codec: SignedCursorCodec
    catalog: CatalogService
    query: QueryService
    services: tuple[CatalogService, QueryService]


_RUNTIME_LOCK = threading.Lock()
_RUNTIME: DataPlaneRuntime | None = None


def build_data_plane_runtime() -> DataPlaneRuntime:
    """Build and atomically publish one immutable V1 dependency graph."""

    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is not None:
            return _RUNTIME

        from catalog_service import CatalogService
        from dataset_registry import load_runtime_dataset_registry
        from query_cursor import SignedCursorCodec
        from query_service import QueryService
        from runtime_paths import marketdata_sqlite_path

        registry = load_runtime_dataset_registry()
        db_path = Path(os.path.abspath(os.fspath(marketdata_sqlite_path())))
        cursor_codec = SignedCursorCodec.from_env()
        catalog = CatalogService(
            registry=registry,
            db_path=db_path,
            cursor_codec=cursor_codec,
        )
        query = QueryService(
            db_path=db_path,
            registry=registry,
            cursor_codec=cursor_codec,
        )
        services = (catalog, query)
        runtime = DataPlaneRuntime(
            registry=registry,
            cursor_codec=cursor_codec,
            catalog=catalog,
            query=query,
            services=services,
        )
        _RUNTIME = runtime
        return runtime


def build_data_plane_services() -> tuple[CatalogService, QueryService]:
    """Return the shared catalog/query service pair."""

    return build_data_plane_runtime().services


def _reset_data_plane_runtime_for_tests() -> None:
    """Invalidate the dependency graph under the publication lock."""

    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = None
