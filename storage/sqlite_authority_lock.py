"""Small cooperative lock for the TradingDatas SQLite authority.

The lock coordinates the generic provider writer with catalog/query readers.
It deliberately has no dependency on the retired business-table read model.
"""

from __future__ import annotations

import fcntl
import os
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class SqliteAuthorityLockError(RuntimeError):
    """The SQLite authority coordination lock is missing or unsafe."""


def sqlite_authority_lock_path(db_path: Path) -> Path:
    """Return the one lock path shared by all clean-slate readers and writers."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    canonical = Path(os.path.abspath(os.fspath(db_path)))
    return canonical.parent / f".{canonical.name}.tradingdatas.lock"


def _require_trusted_regular_file(
    metadata: os.stat_result,
    *,
    lock_path: Path,
) -> None:
    trusted_owners = {0, os.geteuid()}
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or bool(metadata.st_mode & stat.S_IWOTH)
        or metadata.st_uid not in trusted_owners
    ):
        raise SqliteAuthorityLockError(f"SQLite authority lock is unsafe: {lock_path}")


def _require_bound_directory(
    metadata: os.stat_result,
    *,
    directory_path: Path,
) -> None:
    if not stat.S_ISDIR(metadata.st_mode):
        raise SqliteAuthorityLockError(
            f"SQLite authority lock directory is unsafe: {directory_path}"
        )


def _acquire_flock(
    descriptor: int,
    *,
    operation: int,
    wait_seconds: float,
    lock_path: Path,
) -> None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            if wait_seconds <= 0 or time.monotonic() >= deadline:
                raise TimeoutError(
                    f"timed out waiting for SQLite authority lock: {lock_path}"
                ) from exc
            time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))


def _require_current_binding(
    lock_path: Path,
    *,
    opened_identity: tuple[int, int],
) -> None:
    try:
        observed = os.lstat(lock_path)
        _require_trusted_regular_file(observed, lock_path=lock_path)
    except (OSError, SqliteAuthorityLockError) as exc:
        raise SqliteAuthorityLockError(
            f"SQLite authority lock binding changed: {lock_path}"
        ) from exc
    if opened_identity != (observed.st_dev, observed.st_ino):
        raise SqliteAuthorityLockError(
            f"SQLite authority lock binding changed: {lock_path}"
        )


def _require_current_directory_binding(
    directory_path: Path,
    *,
    opened_identity: tuple[int, int],
) -> None:
    try:
        observed = os.lstat(directory_path)
        _require_bound_directory(observed, directory_path=directory_path)
    except (OSError, SqliteAuthorityLockError) as exc:
        raise SqliteAuthorityLockError(
            f"SQLite authority lock directory binding changed: {directory_path}"
        ) from exc
    if opened_identity != (observed.st_dev, observed.st_ino):
        raise SqliteAuthorityLockError(
            f"SQLite authority lock directory binding changed: {directory_path}"
        )


@dataclass(frozen=True)
class SqliteAuthorityLease:
    """Bound lease whose integrity can be rechecked before SQLite commit."""

    lock_path: Path
    lock_identity: tuple[int, int]
    directory_path: Path
    directory_identity: tuple[int, int]
    lock_descriptor: int
    directory_descriptor: int

    def validate(self) -> None:
        """Fail closed if either stable lock domain changed while held."""

        lock_metadata = os.fstat(self.lock_descriptor)
        try:
            _require_trusted_regular_file(lock_metadata, lock_path=self.lock_path)
        except SqliteAuthorityLockError as exc:
            raise SqliteAuthorityLockError(
                f"SQLite authority lock binding changed: {self.lock_path}"
            ) from exc
        if self.lock_identity != (lock_metadata.st_dev, lock_metadata.st_ino):
            raise SqliteAuthorityLockError(
                f"SQLite authority lock binding changed: {self.lock_path}"
            )
        directory_metadata = os.fstat(self.directory_descriptor)
        _require_bound_directory(
            directory_metadata,
            directory_path=self.directory_path,
        )
        if self.directory_identity != (
            directory_metadata.st_dev,
            directory_metadata.st_ino,
        ):
            raise SqliteAuthorityLockError(
                "SQLite authority lock directory binding changed: "
                f"{self.directory_path}"
            )
        _require_current_directory_binding(
            self.directory_path,
            opened_identity=self.directory_identity,
        )
        _require_current_binding(
            self.lock_path,
            opened_identity=self.lock_identity,
        )


@contextmanager
def sqlite_authority_lock(
    db_path: Path,
    *,
    mode: Literal["shared", "exclusive"],
    create: bool = False,
    timeout: float = 0.0,
):
    """Hold the cooperative authority lock without following filesystem links.

    Readers never create the lock. The first writer may create it beside an
    already provisioned database. A missing reader lock therefore fails closed
    instead of silently creating a second coordination domain.
    """

    if mode not in {"shared", "exclusive"}:
        raise ValueError("mode must be 'shared' or 'exclusive'")
    if mode == "shared" and create:
        raise ValueError("shared readers must not create the authority lock")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be a number")
    wait_seconds = max(0.0, float(timeout))
    lock_path = sqlite_authority_lock_path(db_path)

    nofollow = getattr(os, "O_NOFOLLOW", None)
    cloexec = getattr(os, "O_CLOEXEC", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or cloexec is None or directory_flag is None:
        raise SqliteAuthorityLockError(
            "SQLite authority lock requires O_NOFOLLOW, O_CLOEXEC, and O_DIRECTORY"
        )
    directory_path = lock_path.parent
    directory_descriptor: int | None = None
    sentinel_descriptor: int | None = None
    try:
        directory_before = os.lstat(directory_path)
        _require_bound_directory(
            directory_before,
            directory_path=directory_path,
        )
        directory_descriptor = os.open(
            directory_path,
            os.O_RDONLY | directory_flag | nofollow | cloexec,
        )
        directory_opened = os.fstat(directory_descriptor)
        _require_bound_directory(
            directory_opened,
            directory_path=directory_path,
        )
        directory_identity = (
            directory_opened.st_dev,
            directory_opened.st_ino,
        )
        if directory_identity != (
            directory_before.st_dev,
            directory_before.st_ino,
        ):
            raise SqliteAuthorityLockError(
                f"SQLite authority lock directory binding changed: {directory_path}"
            )

        operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
        _acquire_flock(
            directory_descriptor,
            operation=operation,
            wait_seconds=wait_seconds,
            lock_path=lock_path,
        )
        directory_after = os.lstat(directory_path)
        _require_bound_directory(
            directory_after,
            directory_path=directory_path,
        )
        if directory_identity != (
            directory_after.st_dev,
            directory_after.st_ino,
        ):
            raise SqliteAuthorityLockError(
                f"SQLite authority lock directory binding changed: {directory_path}"
            )

        try:
            pre_open = os.lstat(lock_path)
        except FileNotFoundError:
            if not create:
                raise SqliteAuthorityLockError(
                    f"SQLite authority lock is unavailable: {lock_path}"
                ) from None
            pre_open = None
        if pre_open is not None:
            _require_trusted_regular_file(pre_open, lock_path=lock_path)

        sentinel_flags = nofollow | cloexec | os.O_NONBLOCK | os.O_RDONLY
        if create:
            sentinel_flags = nofollow | cloexec | os.O_NONBLOCK | os.O_RDWR | os.O_CREAT
        sentinel_descriptor = os.open(lock_path, sentinel_flags, 0o600)
        opened = os.fstat(sentinel_descriptor)
        _require_trusted_regular_file(opened, lock_path=lock_path)
        opened_identity = (opened.st_dev, opened.st_ino)
        lease = SqliteAuthorityLease(
            lock_path=lock_path,
            lock_identity=opened_identity,
            directory_path=directory_path,
            directory_identity=directory_identity,
            lock_descriptor=sentinel_descriptor,
            directory_descriptor=directory_descriptor,
        )
        lease.validate()
        if pre_open is not None and opened_identity != (
            pre_open.st_dev,
            pre_open.st_ino,
        ):
            raise SqliteAuthorityLockError(
                f"SQLite authority lock binding changed: {lock_path}"
            )
        _acquire_flock(
            sentinel_descriptor,
            operation=operation,
            wait_seconds=wait_seconds,
            lock_path=lock_path,
        )
        _require_current_binding(
            lock_path,
            opened_identity=opened_identity,
        )
    except (SqliteAuthorityLockError, TimeoutError):
        if sentinel_descriptor is not None:
            os.close(sentinel_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise
    except OSError as exc:
        if sentinel_descriptor is not None:
            os.close(sentinel_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise SqliteAuthorityLockError(
            f"SQLite authority lock is unavailable: {lock_path}"
        ) from exc
    except BaseException:
        for descriptor in (sentinel_descriptor, directory_descriptor):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise

    try:
        try:
            yield lease
        except BaseException as body_error:
            try:
                lease.validate()
            except SqliteAuthorityLockError as integrity_error:
                raise integrity_error from body_error
            raise
        else:
            lease.validate()
    finally:
        os.close(sentinel_descriptor)
        os.close(directory_descriptor)
