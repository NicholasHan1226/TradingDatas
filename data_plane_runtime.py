"""Lazy construction for the provider-neutral V1 data plane."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_service import CatalogService
    from dataset_registry import DatasetRegistry
    from legacy_query_compat import LegacyQueryCompat
    from query_cursor import SignedCursorCodec
    from query_service import QueryService


@dataclass(frozen=True)
class DataPlaneRuntime:
    registry: DatasetRegistry
    cursor_codec: SignedCursorCodec
    catalog: CatalogService
    query: QueryService
    legacy_registry: DatasetRegistry
    legacy: LegacyQueryCompat
    legacy_query: QueryService
    services: tuple[CatalogService, QueryService]


_RUNTIME_LOCK = threading.Lock()
_RUNTIME: DataPlaneRuntime | None = None
# Backward-compatible reset/view used by earlier Phase 2 tests and consumers.
_SERVICES: tuple[CatalogService, QueryService] | None = None


def build_data_plane_runtime() -> DataPlaneRuntime:
    """Build and atomically publish one immutable data-plane dependency graph."""

    global _RUNTIME, _SERVICES
    with _RUNTIME_LOCK:
        if _RUNTIME is not None and _SERVICES is _RUNTIME.services:
            return _RUNTIME
        # A legacy test/consumer may still clear only ``_SERVICES``. Treat any
        # mismatched publication as a complete reset while holding one lock.
        _RUNTIME = None
        _SERVICES = None

        from catalog_service import CatalogService
        from dataset_registry import (
            DATASET_REGISTRY_PATH,
            load_dataset_registry,
            runtime_dataset_registry_path,
        )
        from legacy_query_compat import LegacyQueryCompat
        from query_cursor import SignedCursorCodec
        from query_service import QueryService
        from runtime_paths import marketdata_sqlite_path

        registry_path = runtime_dataset_registry_path()
        if registry_path == DATASET_REGISTRY_PATH:
            registry = load_dataset_registry()
            legacy_registry = registry
        else:
            registry = load_dataset_registry(registry_path)
            legacy_registry = load_dataset_registry()
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
        legacy_query = QueryService(
            db_path=db_path,
            registry=legacy_registry,
            cursor_codec=cursor_codec,
        )
        services = (catalog, query)
        runtime = DataPlaneRuntime(
            registry=registry,
            cursor_codec=cursor_codec,
            catalog=catalog,
            query=query,
            legacy_registry=legacy_registry,
            legacy=LegacyQueryCompat(legacy_registry),
            legacy_query=legacy_query,
            services=services,
        )
        _RUNTIME = runtime
        _SERVICES = services
        return runtime


def build_data_plane_services() -> tuple[CatalogService, QueryService]:
    """Return the stable backward-compatible view of the shared runtime."""

    return build_data_plane_runtime().services


def _reset_data_plane_runtime_for_tests() -> None:
    """Invalidate the complete dependency graph under the publication lock."""

    global _RUNTIME, _SERVICES
    with _RUNTIME_LOCK:
        _RUNTIME = None
        _SERVICES = None
