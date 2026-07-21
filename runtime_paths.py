"""TradingDatas-owned runtime path helpers."""

from __future__ import annotations

import os
from pathlib import Path
import stat


class RuntimePathError(ValueError):
    """A TradingDatas runtime path violates the fail-closed path contract."""


def _assert_no_symlink_components(path: Path, *, name: str) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimePathError(f"{name} parent chain is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimePathError(f"{name} parent chain may not contain a symlink")


def _canonical_env_path(name: str, default: str | Path) -> Path:
    raw = os.environ.get(name, os.fspath(default))
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise RuntimePathError(f"{name} must be a non-empty path")
    if not raw.startswith("/") or raw.startswith("//") or os.path.normpath(raw) != raw:
        raise RuntimePathError(f"{name} must be absolute lexical canonical")
    path = Path(raw)
    _assert_no_symlink_components(path, name=name)
    return path


def _physical_path(path: Path, *, name: str) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise RuntimePathError(f"{name} physical path is unavailable") from exc


def _require_within(child: Path, parent: Path, *, child_name: str) -> None:
    physical_child = _physical_path(child, name=child_name)
    physical_parent = _physical_path(parent, name="TRADINGDATAS_DATA_MOUNT")
    if physical_child == physical_parent or physical_parent in physical_child.parents:
        return
    raise RuntimePathError(
        f"{child_name} must remain physically below TRADINGDATAS_DATA_MOUNT"
    )


def data_mount() -> Path:
    """Return the physical mount that contains mutable TradingDatas data."""

    return _canonical_env_path(
        "TRADINGDATAS_DATA_MOUNT",
        "/opt/investment-data",
    )


def data_root() -> Path:
    """Return the TradingDatas-owned mutable data root."""

    root = _canonical_env_path(
        "TRADINGDATAS_DATA_ROOT",
        "/opt/investment-data/tradingdatas",
    )
    _require_within(root, data_mount(), child_name="TRADINGDATAS_DATA_ROOT")
    return root


def provider_native_sqlite_path() -> Path:
    """Return the single provider-native SQLite authority path."""

    root = data_root()
    database = _canonical_env_path(
        "TRADINGDATAS_DB_PATH",
        root / "read_model" / "provider_native.sqlite",
    )
    physical_database = _physical_path(database, name="TRADINGDATAS_DB_PATH")
    physical_root = _physical_path(root, name="TRADINGDATAS_DATA_ROOT")
    if (
        physical_database == physical_root
        or physical_root not in physical_database.parents
    ):
        raise RuntimePathError(
            "TRADINGDATAS_DB_PATH must remain physically below TRADINGDATAS_DATA_ROOT"
        )
    return database


def marketdata_sqlite_path() -> Path:
    """Return the provider-native SQLite path used by current call sites."""

    return provider_native_sqlite_path()
