"""Lazy construction for the provider-neutral V1 data plane."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_service import CatalogService
    from query_service import QueryService


_SERVICES_LOCK = threading.Lock()
_SERVICES: tuple[CatalogService, QueryService] | None = None


def build_data_plane_services() -> tuple[CatalogService, QueryService]:
    """Build and cache V1 services only when a data-plane request needs them."""

    global _SERVICES
    if _SERVICES is not None:
        return _SERVICES
    with _SERVICES_LOCK:
        if _SERVICES is not None:
            return _SERVICES

        from catalog_service import CatalogService
        from dataset_registry import load_dataset_registry
        from query_cursor import SignedCursorCodec
        from query_service import QueryService
        from runtime_paths import marketdata_sqlite_path

        registry = load_dataset_registry()
        db_path = Path(os.path.abspath(os.fspath(marketdata_sqlite_path())))
        cursor_codec = SignedCursorCodec.from_env()
        services = (
            CatalogService(
                registry=registry,
                db_path=db_path,
                cursor_codec=cursor_codec,
            ),
            QueryService(
                db_path=db_path,
                registry=registry,
                cursor_codec=cursor_codec,
            ),
        )
        _SERVICES = services
        return services
