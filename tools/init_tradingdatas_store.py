#!/usr/bin/env python3
"""Create or validate one fresh TradingDatas SQLite authority.

This tool never migrates or imports a legacy database.  It publishes the two
clean-slate tables beside the shared authority lock, or validates an existing
store without rewriting it.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.schema import SCHEMA_SQL, TABLE_NAMES  # noqa: E402
from storage.sqlite_authority_lock import (  # noqa: E402
    SqliteAuthorityLockError,
    sqlite_authority_lock,
)
from runtime_paths import (  # noqa: E402
    RuntimePathError,
    provider_native_sqlite_path,
)


class StoreInitializationError(RuntimeError):
    """The requested clean-slate store cannot be created or trusted."""


def _canonical_absolute(path: Path) -> Path:
    if not isinstance(path, Path):
        raise TypeError("database path must be pathlib.Path")
    if not path.is_absolute() or Path(os.path.abspath(os.fspath(path))) != path:
        raise StoreInitializationError("database path must be absolute canonical")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise StoreInitializationError("database parent is unavailable") from exc
    if parent != path.parent or not parent.is_dir() or parent.is_symlink():
        raise StoreInitializationError("database parent is unsafe")
    return path


def _require_regular_private_file(path: Path) -> os.stat_result:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise StoreInitializationError("database is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise StoreInitializationError("database must be one regular file")
    if metadata.st_uid not in {0, os.geteuid()}:
        raise StoreInitializationError("database owner is unsafe")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise StoreInitializationError("database mode must be 0600")
    return metadata


def _read_only_validation_uri(path: Path) -> str:
    """Return a WAL-safe read URI for store validation.

    ``immutable=1`` skips WAL frames.  When ``-wal``/``-shm`` sidecars exist,
    validation must use ``mode=ro`` only, matching catalog/query.
    """

    wal_path = path.with_name(f"{path.name}-wal")
    shm_path = path.with_name(f"{path.name}-shm")
    if (
        wal_path.exists()
        or wal_path.is_symlink()
        or shm_path.exists()
        or shm_path.is_symlink()
    ):
        return f"{path.as_uri()}?mode=ro"
    return f"{path.as_uri()}?mode=ro&immutable=1"


def _validate_store(path: Path) -> None:
    before = _require_regular_private_file(path)
    try:
        uri = _read_only_validation_uri(path)
        with sqlite3.connect(uri, uri=True) as conn:
            conn.execute("PRAGMA query_only = ON")
            integrity = conn.execute("PRAGMA quick_check").fetchone()
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
    except sqlite3.Error as exc:
        raise StoreInitializationError("database validation failed") from exc
    after = _require_regular_private_file(path)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise StoreInitializationError("database binding changed during validation")
    if integrity != ("ok",):
        raise StoreInitializationError("database integrity check failed")
    if tables != sorted(TABLE_NAMES):
        raise StoreInitializationError("database table set is not clean-slate")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _build_staging_database(parent: Path, name: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{name}.init-", dir=parent)
    staging = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    try:
        with sqlite3.connect(staging) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        _validate_store(staging)
        descriptor = os.open(staging, os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return staging
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def initialize_store(database_path: Path) -> str:
    """Create the fresh authority once, or validate it without mutation."""

    path = _canonical_absolute(database_path)
    try:
        if os.path.lexists(path):
            _require_regular_private_file(path)
            with sqlite_authority_lock(path, mode="shared", create=False):
                _validate_store(path)
            return "existing"

        staging = _build_staging_database(path.parent, path.name)
        try:
            with sqlite_authority_lock(path, mode="exclusive", create=True):
                try:
                    os.link(staging, path, follow_symlinks=False)
                except FileExistsError:
                    _validate_store(path)
                    return "existing"
                staging.unlink()
                _fsync_directory(path.parent)
                _validate_store(path)
            return "created"
        finally:
            staging.unlink(missing_ok=True)
    except StoreInitializationError:
        raise
    except (OSError, SqliteAuthorityLockError, sqlite3.Error) as exc:
        raise StoreInitializationError("store initialization failed closed") from exc


def _database_path_from_cli(raw_path: str) -> Path:
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or "\x00" in raw_path
        or not raw_path.startswith("/")
        or raw_path.startswith("//")
        or os.path.normpath(raw_path) != raw_path
    ):
        raise StoreInitializationError(
            "database path must be absolute lexical canonical"
        )
    path = Path(raw_path)
    try:
        configured = provider_native_sqlite_path()
    except RuntimePathError as exc:
        raise StoreInitializationError(str(exc)) from exc
    if path != configured:
        raise StoreInitializationError(
            "database path must match the configured TradingDatas authority"
        )
    return _canonical_absolute(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        database = _database_path_from_cli(args.database)
        result = initialize_store(database)
    except StoreInitializationError as exc:
        parser.error(str(exc))
    print(result)


if __name__ == "__main__":
    main()
