from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_v1_server_source_contains_only_the_fixed_public_routes() -> None:
    source = (ROOT / "api_server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    route_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/")
    }

    allowed = {
        "/v1/catalog",
        "/v1/query",
        "/",
        "/admin",
        "/admin/",
        "/admin/api/tokens",
        "/admin/api/tokens/",
        "/admin/api/usage",
        "/admin/api/usage/history",
        "/admin/api/collection/status",
        "/admin/api/data/overview",
        "/admin/api/health/alerts",
    }
    assert route_literals == allowed


def test_v1_startup_and_runtime_do_not_import_legacy_modules() -> None:
    forbidden = {
        "api_control_plane",
        "api_response",
        "legacy_query_compat",
        "reader",
        "sector_flow_v2",
    }
    assert _imported_module_names(ROOT / "api_server.py").isdisjoint(forbidden)
    assert _imported_module_names(ROOT / "data_plane_runtime.py").isdisjoint(forbidden)

    before = set(sys.modules)
    module = importlib.import_module("api_server")
    assert module is not None
    newly_imported = set(sys.modules) - before
    assert newly_imported.isdisjoint(forbidden)


def test_data_plane_runtime_has_no_legacy_compatibility_graph() -> None:
    import data_plane_runtime

    fields = set(data_plane_runtime.DataPlaneRuntime.__dataclass_fields__)
    assert fields == {"registry", "cursor_codec", "catalog", "query", "services"}
    source = (ROOT / "data_plane_runtime.py").read_text(encoding="utf-8")
    assert "legacy" not in source.casefold()


def test_v1_defaults_and_runtime_use_only_the_runtime_registry() -> None:
    server_source = (ROOT / "api_server.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "data_plane_runtime.py").read_text(encoding="utf-8")

    assert "load_runtime_dataset_registry" in server_source
    assert "load_runtime_dataset_registry" in runtime_source
    assert "load_dataset_registry" not in server_source
    assert "load_dataset_registry" not in runtime_source


def test_runtime_registry_loader_never_uses_an_implicit_legacy_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataset_registry

    real_loader = dataset_registry.load_dataset_registry
    selected_paths: list[Path] = []

    def explicit_only(path: Path | None = None) -> object:
        assert path is not None, "runtime registry must always pass an explicit path"
        selected_paths.append(Path(path))
        return real_loader(Path(path))

    monkeypatch.delenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, raising=False)
    monkeypatch.setattr(dataset_registry, "load_dataset_registry", explicit_only)

    registry = dataset_registry.load_runtime_dataset_registry()

    assert registry.datasets
    assert selected_paths == [dataset_registry.PROVIDER_NATIVE_DATASET_REGISTRY_PATH]


def test_v1_launcher_has_no_trading_or_legacy_profile_dependency() -> None:
    source = (ROOT / "tools" / "serve_provider_native_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "REAL_TRADING_ENABLED",
        "SHAREDSIGNALS_",
        "env_bootstrap",
        "ProviderNativeV1Handler",
    ):
        assert forbidden not in source
