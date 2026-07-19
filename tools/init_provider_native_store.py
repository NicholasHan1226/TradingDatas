#!/usr/bin/env python3
"""Create the isolated provider-native SQLite runtime root exactly once.

The complete runtime tree is built in a random sibling directory and published
with an operating-system no-replace rename.  A crash therefore leaves the
fixed runtime root either absent or complete; abandoned sibling staging trees
are reported but are never guessed at or automatically deleted.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import pwd
import secrets
import sqlite3
import stat
import sys

from storage.schema import SCHEMA_SQL
from storage.schema_contract import (
    PROVIDER_DATASET_ROWS_COLUMNS,
    PROVIDER_DATASET_ROWS_INDEX_COLUMNS,
)


DEFAULT_DATABASE_PATH = Path(
    "/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite"
)
DEFAULT_MAINTENANCE_LOCK_PATH = Path(
    "/opt/investment-data/sharedsignals-v1/locks/read_model_maintenance.lock"
)
LEGACY_DATABASE_PATH = Path(
    "/opt/investment-data/SharedSignals/runtime/read_model/marketdata.sqlite"
)


class StoreInitializationError(RuntimeError):
    """Raised before an unsafe or partial provider-native store can publish."""


@dataclass(frozen=True)
class StoreInitializationResult:
    database_path: Path
    database_lock_path: Path
    maintenance_lock_path: Path
    stale_staging_count: int = 0


@dataclass(frozen=True)
class _DirectoryBinding:
    path: Path
    label: str
    descriptor: int
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int


def _runtime_owner_ids() -> tuple[int, int]:
    if os.geteuid() != 0:
        return os.geteuid(), os.getegid()
    try:
        account = pwd.getpwnam("marketgraph")
    except KeyError:
        raise StoreInitializationError(
            "marketgraph runtime account is unavailable"
        ) from None
    return account.pw_uid, account.pw_gid


def _trusted_owner_ids() -> set[int]:
    runtime_uid, _ = _runtime_owner_ids()
    return {0, os.geteuid(), runtime_uid}


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _require_canonical_absolute(path: Path, label: str) -> Path:
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise StoreInitializationError(f"{label} path must be canonical and absolute")
    return path


def _open_runtime_parent(path: Path) -> _DirectoryBinding:
    path = _require_canonical_absolute(path, "runtime parent")
    try:
        metadata = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise StoreInitializationError("runtime parent is unavailable") from exc
    if (
        canonical != path
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid not in _trusted_owner_ids()
        or bool(metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    ):
        raise StoreInitializationError("runtime parent is unsafe")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise StoreInitializationError("runtime parent binding is unavailable") from exc
    try:
        observed = os.fstat(descriptor)
        if _identity(observed) != _identity(metadata):
            raise StoreInitializationError("runtime parent binding changed")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return _DirectoryBinding(
            path=path,
            label="runtime parent",
            descriptor=descriptor,
            device=observed.st_dev,
            inode=observed.st_ino,
            owner_uid=observed.st_uid,
            owner_gid=observed.st_gid,
            mode=stat.S_IMODE(observed.st_mode),
        )
    except BaseException:
        os.close(descriptor)
        raise


def _close_binding(binding: _DirectoryBinding) -> None:
    try:
        fcntl.flock(binding.descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(binding.descriptor)
    except OSError:
        pass


def _require_binding(binding: _DirectoryBinding) -> None:
    try:
        descriptor_metadata = os.fstat(binding.descriptor)
        path_metadata = binding.path.lstat()
        canonical = binding.path.resolve(strict=True)
    except OSError as exc:
        raise StoreInitializationError(
            f"{binding.label} directory binding changed"
        ) from exc
    expected = binding.device, binding.inode
    if (
        canonical != binding.path
        or _identity(descriptor_metadata) != expected
        or _identity(path_metadata) != expected
        or not stat.S_ISDIR(path_metadata.st_mode)
        or stat.S_ISLNK(path_metadata.st_mode)
        or descriptor_metadata.st_uid != binding.owner_uid
        or descriptor_metadata.st_gid != binding.owner_gid
        or stat.S_IMODE(descriptor_metadata.st_mode) != binding.mode
        or path_metadata.st_uid != binding.owner_uid
        or path_metadata.st_gid != binding.owner_gid
        or stat.S_IMODE(path_metadata.st_mode) != binding.mode
    ):
        raise StoreInitializationError(f"{binding.label} directory binding changed")


def _initialization_boundary(_boundary: str) -> None:
    """Deterministic crash/race seam used by the isolated test suite."""


def _checkpoint(boundary: str, *bindings: _DirectoryBinding) -> None:
    _initialization_boundary(boundary)
    for binding in bindings:
        _require_binding(binding)


def _open_directory_at(
    parent: _DirectoryBinding,
    name: str,
    path: Path,
    label: str,
    *,
    owner_uid: int,
    owner_gid: int,
    mode: int = 0o700,
) -> _DirectoryBinding:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent.descriptor,
        )
    except OSError as exc:
        raise StoreInitializationError(f"{label} directory is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        if (
            _identity(metadata) != _identity(path_metadata)
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or metadata.st_uid != owner_uid
            or metadata.st_gid != owner_gid
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise StoreInitializationError(f"{label} directory is unsafe")
        return _DirectoryBinding(
            path=path,
            label=label,
            descriptor=descriptor,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            owner_uid=metadata.st_uid,
            owner_gid=metadata.st_gid,
            mode=stat.S_IMODE(metadata.st_mode),
        )
    except BaseException:
        os.close(descriptor)
        raise


def _create_directory_at(
    parent: _DirectoryBinding,
    name: str,
    path: Path,
    label: str,
    *,
    owner_uid: int,
    owner_gid: int,
) -> _DirectoryBinding:
    os.mkdir(name, 0o700, dir_fd=parent.descriptor)
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent.descriptor,
    )
    try:
        os.fchmod(descriptor, 0o700)
        os.fchown(descriptor, owner_uid, owner_gid)
    finally:
        os.close(descriptor)
    return _open_directory_at(
        parent,
        name,
        path,
        label,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise StoreInitializationError("runtime artifact write failed")
        remaining = remaining[written:]


def _create_file_at(
    parent: _DirectoryBinding,
    name: str,
    *,
    owner_uid: int,
    owner_gid: int,
    payload: bytes,
) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent.descriptor,
    )
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, owner_uid, owner_gid)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stat_regular_at(
    parent: _DirectoryBinding,
    name: str,
    *,
    owner_uid: int,
    owner_gid: int,
) -> os.stat_result:
    metadata = os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != owner_uid
        or metadata.st_gid != owner_gid
    ):
        raise StoreInitializationError("provider-native runtime artifact is unsafe")
    return metadata


def _require_empty_regular_at(
    parent: _DirectoryBinding,
    name: str,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    metadata = _stat_regular_at(
        parent,
        name,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    if metadata.st_size != 0:
        raise StoreInitializationError("coordination artifact is invalid")


def _require_canonical_schema(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise StoreInitializationError("SQLite quick_check failed")
    provider_columns = conn.execute(
        "PRAGMA table_xinfo(provider_dataset_rows)"
    ).fetchall()
    if tuple(str(row[1]) for row in provider_columns) != tuple(
        column[0] for column in PROVIDER_DATASET_ROWS_COLUMNS
    ):
        raise StoreInitializationError("provider_dataset_rows contract is unavailable")
    receipt_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_xinfo(market_ingest_runs)").fetchall()
    }
    if not {
        "run_id",
        "started_at",
        "finished_at",
        "status",
        "source",
        "rows_read",
        "rows_written",
        "notes",
    }.issubset(receipt_columns):
        raise StoreInitializationError("market_ingest_runs contract is unavailable")
    indexes = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    if not set(PROVIDER_DATASET_ROWS_INDEX_COLUMNS).issubset(indexes):
        raise StoreInitializationError("provider_dataset_rows indexes are unavailable")


def _build_database_payload() -> bytes:
    if not hasattr(sqlite3.Connection, "serialize"):
        raise StoreInitializationError("SQLite serialization is unavailable")
    with sqlite3.connect(":memory:", isolation_level=None) as conn:
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_SQL)
        _require_canonical_schema(conn)
        payload = conn.serialize()
    if not payload:
        raise StoreInitializationError("serialized SQLite payload is empty")
    return payload


def _validate_database_file(path: Path, expected: tuple[int, int]) -> None:
    before = path.lstat()
    if _identity(before) != expected:
        raise StoreInitializationError("provider-native database identity changed")
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
        _require_canonical_schema(conn)
    after = path.lstat()
    if _identity(after) != expected:
        raise StoreInitializationError("provider-native database identity changed")


def _legacy_snapshot(path: Path) -> tuple[int, int, int, int] | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StoreInitializationError("legacy database is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise StoreInitializationError("legacy database is unsafe")
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def _stale_staging_names(parent: _DirectoryBinding, root_name: str) -> tuple[str, ...]:
    prefix = f".{root_name}.init-"
    return tuple(
        sorted(
            name for name in os.listdir(parent.descriptor) if name.startswith(prefix)
        )
    )


def _publish_directory_noreplace(
    parent_descriptor: int,
    staging_name: str,
    final_name: str,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(staging_name)
    target = os.fsencode(final_name)
    if sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise StoreInitializationError("renameat2 no-replace is unavailable")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = function(parent_descriptor, source, parent_descriptor, target, 1)
    elif sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        if function is None:
            raise StoreInitializationError("renameatx_np exclusive is unavailable")
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        result = function(parent_descriptor, source, parent_descriptor, target, 4)
    else:
        raise StoreInitializationError("exclusive directory publish is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), final_name)
        raise OSError(error, os.strerror(error), final_name)


def _validate_complete_store(
    parent: _DirectoryBinding,
    root_path: Path,
    database_path: Path,
    database_lock_path: Path,
    maintenance_lock_path: Path,
    legacy_snapshot: tuple[int, int, int, int] | None,
    *,
    runtime_uid: int,
    runtime_gid: int,
) -> StoreInitializationResult:
    root = _open_directory_at(
        parent,
        root_path.name,
        root_path,
        "runtime root",
        owner_uid=runtime_uid,
        owner_gid=runtime_gid,
    )
    read_model: _DirectoryBinding | None = None
    locks: _DirectoryBinding | None = None
    try:
        if set(os.listdir(root.descriptor)) != {"read_model", "locks"}:
            raise StoreInitializationError("runtime root contents are invalid")
        read_model = _open_directory_at(
            root,
            "read_model",
            root_path / "read_model",
            "read model",
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        locks = _open_directory_at(
            root,
            "locks",
            root_path / "locks",
            "maintenance locks",
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        if set(os.listdir(read_model.descriptor)) != {
            database_path.name,
            database_lock_path.name,
        } or set(os.listdir(locks.descriptor)) != {maintenance_lock_path.name}:
            raise StoreInitializationError("runtime root artifacts are invalid")
        database_metadata = _stat_regular_at(
            read_model,
            database_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        _require_empty_regular_at(
            read_model,
            database_lock_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        _require_empty_regular_at(
            locks,
            maintenance_lock_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        if (
            legacy_snapshot is not None
            and _identity(database_metadata) == legacy_snapshot[:2]
        ):
            raise StoreInitializationError(
                "provider-native database aliases legacy data"
            )
        _validate_database_file(database_path, _identity(database_metadata))
        _checkpoint("complete_store_validated", parent, root, read_model, locks)
        return StoreInitializationResult(
            database_path=database_path,
            database_lock_path=database_lock_path,
            maintenance_lock_path=maintenance_lock_path,
            stale_staging_count=len(_stale_staging_names(parent, root_path.name)),
        )
    finally:
        if locks is not None:
            _close_binding(locks)
        if read_model is not None:
            _close_binding(read_model)
        _close_binding(root)


def initialize_provider_native_store(
    database_path: Path,
    *,
    legacy_db_path: Path,
    maintenance_lock_path: Path,
) -> StoreInitializationResult:
    """Publish a fresh runtime root or validate an existing complete one."""

    database_path = _require_canonical_absolute(Path(database_path), "database")
    legacy_db_path = _require_canonical_absolute(
        Path(legacy_db_path), "legacy database"
    )
    maintenance_lock_path = _require_canonical_absolute(
        Path(maintenance_lock_path), "maintenance lock"
    )
    root_path = database_path.parent.parent
    if (
        database_path.parent != root_path / "read_model"
        or database_path.name != "provider_native.sqlite"
        or maintenance_lock_path.parent != root_path / "locks"
        or maintenance_lock_path.name != "read_model_maintenance.lock"
    ):
        raise StoreInitializationError("provider-native runtime layout is invalid")
    if database_path == legacy_db_path:
        raise StoreInitializationError(
            "refusing to initialize the legacy database path"
        )
    database_lock_path = (
        database_path.parent / f".{database_path.name}.read_model_store.lock"
    )
    runtime_uid, runtime_gid = _runtime_owner_ids()
    legacy_before = _legacy_snapshot(legacy_db_path)
    parent = _open_runtime_parent(root_path.parent)
    staging: _DirectoryBinding | None = None
    read_model: _DirectoryBinding | None = None
    locks: _DirectoryBinding | None = None
    try:
        _checkpoint("parent_locked", parent)
        try:
            os.stat(root_path.name, dir_fd=parent.descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise StoreInitializationError("runtime root is unavailable") from exc
        else:
            try:
                return _validate_complete_store(
                    parent,
                    root_path,
                    database_path,
                    database_lock_path,
                    maintenance_lock_path,
                    legacy_before,
                    runtime_uid=runtime_uid,
                    runtime_gid=runtime_gid,
                )
            except StoreInitializationError as exc:
                raise StoreInitializationError(
                    "provider-native runtime root is partial or unsafe"
                ) from exc

        staging_name = f".{root_path.name}.init-{secrets.token_hex(16)}"
        staging_path = root_path.parent / staging_name
        staging = _create_directory_at(
            parent,
            staging_name,
            staging_path,
            "staging runtime root",
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        os.fsync(parent.descriptor)
        _checkpoint("after_staging_root", parent, staging)
        read_model = _create_directory_at(
            staging,
            "read_model",
            staging_path / "read_model",
            "staging read model",
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        locks = _create_directory_at(
            staging,
            "locks",
            staging_path / "locks",
            "staging maintenance locks",
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        os.fsync(staging.descriptor)
        _checkpoint("after_staging_directories", parent, staging, read_model, locks)
        _create_file_at(
            read_model,
            database_lock_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
            payload=b"",
        )
        _create_file_at(
            locks,
            maintenance_lock_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
            payload=b"",
        )
        os.fsync(read_model.descriptor)
        os.fsync(locks.descriptor)
        _checkpoint("after_coordination_files", parent, staging, read_model, locks)
        payload = _build_database_payload()
        _create_file_at(
            read_model,
            database_path.name,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
            payload=payload,
        )
        _checkpoint("after_sqlite_build", parent, staging, read_model, locks)
        os.fsync(read_model.descriptor)
        os.fsync(locks.descriptor)
        os.fsync(staging.descriptor)
        _checkpoint("before_publish", parent, staging, read_model, locks)
        try:
            _publish_directory_noreplace(
                parent.descriptor,
                staging_name,
                root_path.name,
            )
        except FileExistsError:
            return _validate_complete_store(
                parent,
                root_path,
                database_path,
                database_lock_path,
                maintenance_lock_path,
                legacy_before,
                runtime_uid=runtime_uid,
                runtime_gid=runtime_gid,
            )
        _initialization_boundary("after_publish")
        _require_binding(parent)
        os.fsync(parent.descriptor)
        _checkpoint("after_parent_fsync", parent)
        result = _validate_complete_store(
            parent,
            root_path,
            database_path,
            database_lock_path,
            maintenance_lock_path,
            legacy_before,
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
        )
        if _legacy_snapshot(legacy_db_path) != legacy_before:
            raise StoreInitializationError(
                "legacy database changed during initialization"
            )
        return result
    except StoreInitializationError:
        raise
    except BaseException as exc:
        raise StoreInitializationError(
            f"provider-native store initialization failed: {type(exc).__name__}"
        ) from exc
    finally:
        if locks is not None:
            _close_binding(locks)
        if read_model is not None:
            _close_binding(read_model)
        if staging is not None:
            _close_binding(staging)
        _close_binding(parent)


def main() -> int:
    result = initialize_provider_native_store(
        DEFAULT_DATABASE_PATH,
        legacy_db_path=LEGACY_DATABASE_PATH,
        maintenance_lock_path=DEFAULT_MAINTENANCE_LOCK_PATH,
    )
    print(
        json.dumps(
            {
                "database": str(result.database_path),
                "database_lock": str(result.database_lock_path),
                "maintenance_lock": str(result.maintenance_lock_path),
                "quick_check": "ok",
                "stale_staging_count": result.stale_staging_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
