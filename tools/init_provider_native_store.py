#!/usr/bin/env python3
"""Create the isolated provider-native SQLite authority exactly once.

This bootstrap intentionally has no database-path CLI selector.  Production
paths are fixed below; tests call :func:`initialize_provider_native_store`
directly with isolated paths.  Existing databases are never migrated or
modified.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import pwd
import secrets
import sqlite3
import stat

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


@dataclass(frozen=True)
class _DirectoryBinding:
    path: Path
    label: str
    descriptor: int
    device: int
    inode: int


@dataclass(frozen=True)
class _OwnedArtifact:
    binding: _DirectoryBinding
    name: str
    canonical_path: Path
    device: int
    inode: int


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


def _require_canonical_absolute(path: Path, label: str) -> Path:
    raw = os.fspath(path)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise StoreInitializationError(f"{label} path must be canonical and absolute")
    return path


def _require_safe_existing_directory(path: Path, label: str) -> Path:
    path = _require_canonical_absolute(path, label)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise StoreInitializationError(f"{label} directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid not in _trusted_owner_ids()
        or bool(metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    ):
        raise StoreInitializationError(f"{label} directory is unsafe")
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise StoreInitializationError(f"{label} directory is unavailable") from exc
    if canonical != path:
        raise StoreInitializationError(f"{label} directory is not canonical")
    return canonical


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _open_directory_binding(path: Path, label: str) -> _DirectoryBinding:
    canonical = _require_safe_existing_directory(path, label)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(canonical, flags)
    except OSError as exc:
        raise StoreInitializationError(
            f"{label} directory binding is unavailable"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        path_metadata = canonical.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or _identity(metadata) != _identity(path_metadata)
            or metadata.st_uid not in _trusted_owner_ids()
            or bool(metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
        ):
            raise StoreInitializationError(f"{label} directory binding is unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _DirectoryBinding(
            path=canonical,
            label=label,
            descriptor=descriptor,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
    except BaseException:
        os.close(descriptor)
        raise


def _close_directory_binding(binding: _DirectoryBinding) -> None:
    try:
        fcntl.flock(binding.descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(binding.descriptor)
    except OSError:
        # The initializer is a bounded process; process exit releases a file
        # description whose close status is indeterminate after an OS error.
        pass


def _require_directory_binding(binding: _DirectoryBinding) -> None:
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
        or path_metadata.st_uid not in _trusted_owner_ids()
        or bool(path_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    ):
        raise StoreInitializationError(f"{binding.label} directory binding changed")


def _initialization_boundary(_boundary: str) -> None:
    """Deterministic test seam before every parent-identity revalidation."""


def _checkpoint(boundary: str, *bindings: _DirectoryBinding) -> None:
    _initialization_boundary(boundary)
    for binding in bindings:
        _require_directory_binding(binding)


def _stat_at(binding: _DirectoryBinding, name: str) -> os.stat_result:
    return os.stat(
        name,
        dir_fd=binding.descriptor,
        follow_symlinks=False,
    )


def _require_absent_at(
    binding: _DirectoryBinding,
    name: str,
    label: str,
) -> None:
    try:
        _stat_at(binding, name)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise StoreInitializationError(f"{label} is unavailable") from exc
    raise StoreInitializationError(f"{label} already exists")


def _artifact_from_descriptor(
    binding: _DirectoryBinding,
    name: str,
    canonical_path: Path,
    descriptor: int,
) -> _OwnedArtifact:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise StoreInitializationError("created runtime artifact is not a regular file")
    return _OwnedArtifact(
        binding=binding,
        name=name,
        canonical_path=canonical_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _artifact_at(
    binding: _DirectoryBinding,
    name: str,
    canonical_path: Path,
) -> _OwnedArtifact:
    metadata = _stat_at(binding, name)
    if not stat.S_ISREG(metadata.st_mode):
        raise StoreInitializationError(
            "published runtime artifact is not a regular file"
        )
    return _OwnedArtifact(
        binding=binding,
        name=name,
        canonical_path=canonical_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _same_artifact(metadata: os.stat_result, artifact: _OwnedArtifact) -> bool:
    return _identity(metadata) == (artifact.device, artifact.inode)


def _unlink_owned_at(artifact: _OwnedArtifact) -> None:
    try:
        metadata = _stat_at(artifact.binding, artifact.name)
    except FileNotFoundError:
        return
    if not _same_artifact(metadata, artifact):
        return
    os.unlink(artifact.name, dir_fd=artifact.binding.descriptor)


def _unlink_owned_canonical(artifact: _OwnedArtifact) -> None:
    try:
        metadata = artifact.canonical_path.lstat()
    except FileNotFoundError:
        return
    if not _same_artifact(metadata, artifact):
        return
    artifact.canonical_path.unlink()


def _cleanup_owned_artifact(artifact: _OwnedArtifact) -> None:
    errors: list[OSError] = []
    try:
        _unlink_owned_at(artifact)
    except OSError as exc:
        errors.append(exc)
    try:
        _unlink_owned_canonical(artifact)
    except OSError as exc:
        errors.append(exc)
    try:
        remaining = _stat_at(artifact.binding, artifact.name)
    except FileNotFoundError:
        remaining = None
    except OSError as exc:
        errors.append(exc)
        remaining = None
    if remaining is not None and _same_artifact(remaining, artifact):
        errors.append(OSError("owned artifact remains in bound directory"))
    try:
        remaining = artifact.canonical_path.lstat()
    except FileNotFoundError:
        remaining = None
    except OSError as exc:
        errors.append(exc)
        remaining = None
    if remaining is not None and _same_artifact(remaining, artifact):
        errors.append(OSError("owned artifact remains at canonical path"))
    if errors:
        raise errors[0]


def _create_coordination_file_at(
    binding: _DirectoryBinding,
    name: str,
    canonical_path: Path,
    *,
    owner_uid: int,
    owner_gid: int,
) -> _OwnedArtifact:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=binding.descriptor)
    artifact = _artifact_from_descriptor(binding, name, canonical_path, descriptor)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fsync(descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        _cleanup_owned_artifact(artifact)
        raise
    try:
        os.close(descriptor)
    except BaseException:
        _cleanup_owned_artifact(artifact)
        raise
    return artifact


def _require_canonical_schema(conn: sqlite3.Connection) -> None:
    quick_check = conn.execute("PRAGMA quick_check").fetchone()
    if quick_check != ("ok",):
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
    _validate_database_payload(payload)
    return payload


def _validate_database_payload(payload: bytes) -> None:
    if not hasattr(sqlite3.Connection, "deserialize"):
        raise StoreInitializationError("SQLite deserialization is unavailable")
    if not payload or len(payload) > 64 * 1024 * 1024:
        raise StoreInitializationError("serialized SQLite payload size is invalid")
    with sqlite3.connect(":memory:", isolation_level=None) as conn:
        conn.deserialize(payload)
        _require_canonical_schema(conn)


def _create_empty_artifact_at(
    binding: _DirectoryBinding,
    name: str,
    canonical_path: Path,
    *,
    owner_uid: int,
    owner_gid: int,
) -> tuple[_OwnedArtifact, int]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=binding.descriptor)
    artifact = _artifact_from_descriptor(binding, name, canonical_path, descriptor)
    try:
        os.fchmod(descriptor, 0o600)
        os.fchown(descriptor, owner_uid, owner_gid)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        _cleanup_owned_artifact(artifact)
        raise
    return artifact, descriptor


def _write_payload(descriptor: int, payload: bytes) -> None:
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise StoreInitializationError("serialized SQLite payload write failed")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _read_artifact_payload(artifact: _OwnedArtifact) -> bytes:
    descriptor = os.open(
        artifact.name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=artifact.binding.descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if not _same_artifact(metadata, artifact):
            raise StoreInitializationError("published database identity changed")
        if metadata.st_size <= 0 or metadata.st_size > 64 * 1024 * 1024:
            raise StoreInitializationError("published database size is invalid")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise StoreInitializationError("published database read was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory_fd(binding: _DirectoryBinding) -> None:
    os.fsync(binding.descriptor)


def _require_artifact_contract(
    artifact: _OwnedArtifact,
    *,
    owner_uid: int,
    expected_nlink: int = 1,
) -> None:
    metadata = _stat_at(artifact.binding, artifact.name)
    if (
        not _same_artifact(metadata, artifact)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != expected_nlink
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != owner_uid
    ):
        raise StoreInitializationError("published runtime artifact is unsafe")


def initialize_provider_native_store(
    database_path: Path,
    *,
    legacy_db_path: Path,
    maintenance_lock_path: Path,
) -> StoreInitializationResult:
    """Atomically create one fresh SQLite authority and its two lock files."""

    database_path = _require_canonical_absolute(Path(database_path), "database")
    legacy_db_path = _require_canonical_absolute(
        Path(legacy_db_path), "legacy database"
    )
    maintenance_lock_path = _require_canonical_absolute(
        Path(maintenance_lock_path), "maintenance lock"
    )
    if database_path.resolve(strict=False) == legacy_db_path.resolve(strict=False):
        raise StoreInitializationError(
            "refusing to initialize the legacy database path"
        )
    database_parent = _require_safe_existing_directory(
        database_path.parent, "database parent"
    )
    maintenance_parent = _require_safe_existing_directory(
        maintenance_lock_path.parent, "maintenance lock parent"
    )
    if database_parent.parent != maintenance_parent.parent:
        raise StoreInitializationError(
            "coordination artifacts must share one runtime root"
        )
    runtime_uid, runtime_gid = _runtime_owner_ids()
    database_lock_path = (
        database_parent / f".{database_path.name}.read_model_store.lock"
    )
    database_binding: _DirectoryBinding | None = None
    maintenance_binding: _DirectoryBinding | None = None
    database_lock: _OwnedArtifact | None = None
    maintenance_lock: _OwnedArtifact | None = None
    temporary: _OwnedArtifact | None = None
    published_database: _OwnedArtifact | None = None
    temporary_descriptor: int | None = None
    result: StoreInitializationResult | None = None
    try:
        database_binding = _open_directory_binding(
            database_parent,
            "database parent",
        )
        maintenance_binding = _open_directory_binding(
            maintenance_parent,
            "maintenance lock parent",
        )
        bindings = database_binding, maintenance_binding
        _checkpoint("parents_locked", *bindings)

        _require_absent_at(database_binding, database_path.name, "database")
        _require_absent_at(
            database_binding,
            database_lock_path.name,
            "coordination artifact",
        )
        _require_absent_at(
            maintenance_binding,
            maintenance_lock_path.name,
            "coordination artifact",
        )

        database_lock = _create_coordination_file_at(
            database_binding,
            database_lock_path.name,
            database_lock_path,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        _checkpoint("after_database_lock", *bindings)

        maintenance_lock = _create_coordination_file_at(
            maintenance_binding,
            maintenance_lock_path.name,
            maintenance_lock_path,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        _checkpoint("after_maintenance_lock", *bindings)

        temporary_name = (
            f".{database_path.name}.init-{os.getpid()}-{secrets.token_hex(12)}"
        )
        temporary_path = database_parent / temporary_name
        temporary, temporary_descriptor = _create_empty_artifact_at(
            database_binding,
            temporary_name,
            temporary_path,
            owner_uid=runtime_uid,
            owner_gid=runtime_gid,
        )
        _checkpoint("after_temp_create", *bindings)

        payload = _build_database_payload()
        _write_payload(temporary_descriptor, payload)
        descriptor_to_close = temporary_descriptor
        temporary_descriptor = None
        os.close(descriptor_to_close)
        _checkpoint("after_sqlite_build", *bindings)

        _require_absent_at(database_binding, database_path.name, "database")
        os.link(
            temporary.name,
            database_path.name,
            src_dir_fd=database_binding.descriptor,
            dst_dir_fd=database_binding.descriptor,
            follow_symlinks=False,
        )
        published_database = _artifact_at(
            database_binding,
            database_path.name,
            database_path,
        )
        if (published_database.device, published_database.inode) != (
            temporary.device,
            temporary.inode,
        ):
            raise StoreInitializationError("published database identity is invalid")
        _checkpoint("after_database_link", *bindings)

        _unlink_owned_at(temporary)
        temporary = None
        _fsync_directory_fd(database_binding)
        _fsync_directory_fd(maintenance_binding)
        _checkpoint("after_directory_fsync", *bindings)

        _require_artifact_contract(
            published_database,
            owner_uid=runtime_uid,
        )
        _require_artifact_contract(database_lock, owner_uid=runtime_uid)
        _require_artifact_contract(maintenance_lock, owner_uid=runtime_uid)
        observed_payload = _read_artifact_payload(published_database)
        if observed_payload != payload:
            raise StoreInitializationError("published database bytes changed")
        _validate_database_payload(observed_payload)
        _checkpoint("before_return", *bindings)
        result = StoreInitializationResult(
            database_path=database_path,
            database_lock_path=database_lock_path,
            maintenance_lock_path=maintenance_lock_path,
        )
    except BaseException as exc:
        cleanup_errors: list[BaseException] = []
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError as close_exc:
                cleanup_errors.append(close_exc)
            temporary_descriptor = None
        for artifact in (
            published_database,
            temporary,
            maintenance_lock,
            database_lock,
        ):
            if artifact is None:
                continue
            try:
                _cleanup_owned_artifact(artifact)
            except OSError as cleanup_exc:
                cleanup_errors.append(cleanup_exc)
        for binding in (database_binding, maintenance_binding):
            if binding is None:
                continue
            try:
                _fsync_directory_fd(binding)
            except OSError as fsync_exc:
                cleanup_errors.append(fsync_exc)
        if cleanup_errors:
            raise StoreInitializationError(
                "provider-native store initialization compensation failed"
            ) from exc
        if isinstance(exc, StoreInitializationError):
            raise
        raise StoreInitializationError(
            f"provider-native store initialization failed: {type(exc).__name__}"
        ) from exc
    finally:
        for binding in (maintenance_binding, database_binding):
            if binding is None:
                continue
            _close_directory_binding(binding)

    if result is None:
        raise StoreInitializationError("provider-native store initialization failed")
    return result


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
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
