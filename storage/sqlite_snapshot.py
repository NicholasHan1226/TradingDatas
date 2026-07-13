"""Create one permission-controlled SQLite source point for DuckDB sync.

The authoritative SQLite database remains live while collectors append to it.
SQLite's backup API gives the DuckDB mirror one consistent source database for
the whole sync and reconciliation cycle without blocking collectors for the
duration of DuckDB work.
"""

from __future__ import annotations

import os
import math
import sqlite3
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_RESERVE_BYTES = 5 * 1024**3
DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_MAX_FS_USAGE_PERCENT = 90.0
# The production wrapper is bounded at 600 seconds and holds its single-instance
# lock for the whole run.  A residual older than two outer timeouts is orphaned
# and can be removed by the next lock holder.
DEFAULT_STALE_SECONDS = 2 * 600
SNAPSHOT_PREFIX = "duckdb-sync-"


class SQLiteSnapshotError(RuntimeError):
    """A classified, fail-before-sync snapshot failure."""

    def __init__(self, error_class: str, message: str, metadata: dict | None = None):
        super().__init__(message)
        self.error_class = error_class
        self.metadata = metadata or {}


@dataclass
class SQLiteSnapshot:
    path: Path
    snapshot_id: str
    metadata: dict
    _inode: int

    def cleanup(self) -> dict:
        """Delete exactly this run's snapshot without following replacements."""
        cleanup = {"status": "ok", "path": str(self.path)}
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            cleanup["status"] = "already_absent"
            cleanup["sidecars"] = _remove_snapshot_sidecars(self.path)
            return cleanup
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise SQLiteSnapshotError(
                "cleanup_failed",
                f"refusing to remove non-regular snapshot: {self.path}",
                {"cleanup": {"status": "refused", "path": str(self.path)}},
            )
        if info.st_ino != self._inode:
            raise SQLiteSnapshotError(
                "cleanup_failed",
                f"snapshot inode changed before cleanup: {self.path}",
                {"cleanup": {"status": "inode_changed", "path": str(self.path)}},
            )
        try:
            self.path.unlink()
        except OSError as exc:
            raise SQLiteSnapshotError(
                "cleanup_failed",
                f"failed to remove snapshot {self.path}: {exc}",
                {"cleanup": {"status": "error", "path": str(self.path)}},
            ) from exc
        cleanup["sidecars"] = _remove_snapshot_sidecars(self.path)
        return cleanup


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_metadata(path: Path) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "is_symlink": stat.S_ISLNK(info.st_mode),
        "is_regular": stat.S_ISREG(info.st_mode),
    }


def source_metadata(source_path: Path) -> dict:
    source = Path(source_path)
    return {
        "database": {
            **_path_metadata(source),
            "resolved_path": str(source.resolve(strict=False)),
        },
        "wal": _path_metadata(Path(f"{source}-wal")),
        "shm": _path_metadata(Path(f"{source}-shm")),
    }


def _snapshot_root(source_path: Path) -> Path:
    configured = os.environ.get("SHAREDSIGNALS_DUCKDB_SNAPSHOT_DIR")
    return Path(configured) if configured else source_path.parent / ".duckdb_sync_snapshots"


def _prepare_snapshot_root(root: Path) -> None:
    if root.exists() and root.is_symlink():
        raise SQLiteSnapshotError(
            "permission_denied", f"snapshot directory must not be a symlink: {root}"
        )
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
    except OSError as exc:
        raise SQLiteSnapshotError(
            "permission_denied", f"cannot prepare snapshot directory {root}: {exc}"
        ) from exc
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SQLiteSnapshotError(
            "permission_denied", f"invalid snapshot directory: {root}"
        )


def cleanup_stale_snapshots(
    root: Path,
    *,
    stale_after_seconds: float = DEFAULT_STALE_SECONDS,
    now: float | None = None,
) -> dict:
    """Remove only old regular files owned by this helper's fixed prefix."""
    current = time.time() if now is None else now
    removed: list[str] = []
    skipped: list[dict[str, str]] = []
    for candidate in root.glob(f"{SNAPSHOT_PREFIX}*"):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            skipped.append({"path": str(candidate), "reason": "not_regular"})
            continue
        if current - info.st_mtime < stale_after_seconds:
            skipped.append({"path": str(candidate), "reason": "not_stale"})
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            raise SQLiteSnapshotError(
                "cleanup_failed", f"cannot remove stale snapshot {candidate}: {exc}"
            ) from exc
        removed.append(str(candidate))
    return {"removed": removed, "skipped": skipped}


def _filesystem_space(path: Path) -> dict:
    info = os.statvfs(path)
    total = int(info.f_blocks * info.f_frsize)
    available = int(info.f_bavail * info.f_frsize)
    used = max(0, total - available)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "usage_percent": round(100.0 * used / total, 3) if total else 100.0,
        "device": int(path.stat().st_dev),
        "path": str(path),
    }


def _logical_database_bytes(path: Path) -> dict:
    """Read the current logical size, including committed WAL-backed pages."""
    try:
        conn = sqlite3.connect(_source_readonly_uri(path), uri=True, timeout=30)
        try:
            conn.execute("PRAGMA query_only=ON")
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SQLiteSnapshotError(
            "source_unavailable", f"cannot inspect SQLite logical size: {exc}"
        ) from exc
    return {
        "page_count": page_count,
        "page_size": page_size,
        "logical_bytes": page_count * page_size,
    }


def _nonnegative_int(value: object, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SQLiteSnapshotError(
            "invalid_configuration", f"{name} must be a nonnegative integer"
        ) from exc
    if parsed < 0:
        raise SQLiteSnapshotError(
            "invalid_configuration", f"{name} must be a nonnegative integer"
        )
    return parsed


def _positive_finite_float(value: object, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SQLiteSnapshotError(
            "invalid_configuration", f"{name} must be a positive finite number"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise SQLiteSnapshotError(
            "invalid_configuration", f"{name} must be a positive finite number"
        )
    return parsed


def _usage_ceiling(value: object) -> float:
    parsed = _positive_finite_float(value, "snapshot max filesystem usage percent")
    if parsed > 100:
        raise SQLiteSnapshotError(
            "invalid_configuration",
            "snapshot max filesystem usage percent must be <= 100",
        )
    return parsed


def _remove_exact_regular(path: Path, expected_inode: int) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"status": "absent", "path": str(path)}
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_ino != expected_inode
    ):
        raise SQLiteSnapshotError(
            "cleanup_failed",
            f"refusing to remove replaced snapshot temp: {path}",
            {
                "temp_cleanup": {
                    "status": "replacement_refused",
                    "path": str(path),
                    "expected_inode": expected_inode,
                    "actual_inode": info.st_ino,
                }
            },
        )
    try:
        path.unlink()
    except OSError as exc:
        raise SQLiteSnapshotError(
            "cleanup_failed",
            f"failed to remove snapshot temp {path}: {exc}",
            {"temp_cleanup": {"status": "error", "path": str(path)}},
        ) from exc
    return {"status": "removed", "path": str(path)}


def _remove_snapshot_sidecars(base_path: Path) -> list[dict]:
    removed: list[dict] = []
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{base_path}{suffix}")
        try:
            info = sidecar.lstat()
        except FileNotFoundError:
            removed.append({"path": str(sidecar), "status": "absent"})
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise SQLiteSnapshotError(
                "cleanup_failed",
                f"refusing to remove non-regular snapshot sidecar: {sidecar}",
                {
                    "sidecar_cleanup": {
                        "status": "refused",
                        "path": str(sidecar),
                    }
                },
            )
        try:
            sidecar.unlink()
        except OSError as exc:
            raise SQLiteSnapshotError(
                "cleanup_failed",
                f"failed to remove snapshot sidecar {sidecar}: {exc}",
                {"sidecar_cleanup": {"status": "error", "path": str(sidecar)}},
            ) from exc
        removed.append({"path": str(sidecar), "status": "removed"})
    return removed


def _readonly_uri(path: Path, *, immutable: bool = False) -> str:
    suffix = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    return path.resolve().as_uri() + suffix


def _source_readonly_uri(path: Path) -> str:
    # A WAL database with no sidecars cannot always be opened mode=ro because
    # SQLite may need to create SHM.  With no WAL content, immutable mode is a
    # safe read of the main file; when WAL exists, mode=ro includes committed
    # WAL pages without mutating authority.
    has_wal = Path(f"{path}-wal").exists()
    return _readonly_uri(path, immutable=not has_wal)


def _validate_snapshot(path: Path, required_tables: Iterable[str]) -> dict:
    conn = sqlite3.connect(_readonly_uri(path, immutable=True), uri=True, timeout=10)
    try:
        schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        present = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = sorted(set(required_tables) - present)
        if missing:
            raise SQLiteSnapshotError(
                "snapshot_validation_failed",
                "snapshot is missing required tables: " + ", ".join(missing),
            )
        return {
            "schema_version": schema_version,
            "page_count": page_count,
            "page_size": page_size,
            "required_table_count": len(set(required_tables)),
        }
    except sqlite3.Error as exc:
        raise SQLiteSnapshotError(
            "snapshot_validation_failed", f"snapshot validation failed: {exc}"
        ) from exc
    finally:
        conn.close()


def create_sqlite_snapshot(
    source_path: str | Path,
    *,
    snapshot_root: str | Path | None = None,
    reserve_bytes: int | None = None,
    timeout_seconds: float | None = None,
    stale_after_seconds: float = DEFAULT_STALE_SECONDS,
    required_tables: Iterable[str] = (),
    working_paths: Iterable[str | Path] = (),
) -> SQLiteSnapshot:
    """Create and lightly validate one native SQLite backup snapshot."""
    started = time.monotonic()
    source = Path(source_path)
    snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex}"
    before = source_metadata(source)
    attempt_metadata = {
        "snapshot_id": snapshot_id,
        "source_before": before,
    }
    source_info = before["database"]
    if not source_info.get("exists") or not source_info.get("is_regular"):
        raise SQLiteSnapshotError(
            "source_unavailable",
            f"SQLite source is not a regular file: {source}",
            attempt_metadata,
        )
    if source_info.get("is_symlink"):
        raise SQLiteSnapshotError(
            "source_unavailable",
            f"SQLite source must not be a symlink: {source}",
            attempt_metadata,
        )

    root = Path(snapshot_root) if snapshot_root is not None else _snapshot_root(source)
    attempt_metadata["snapshot_root"] = str(root)
    try:
        _prepare_snapshot_root(root)
        stale_seconds = _positive_finite_float(
            os.environ.get(
                "SHAREDSIGNALS_DUCKDB_SNAPSHOT_STALE_SECONDS",
                stale_after_seconds,
            ),
            "snapshot stale threshold",
        )
        stale_cleanup = cleanup_stale_snapshots(
            root, stale_after_seconds=stale_seconds
        )
        attempt_metadata["stale_cleanup"] = stale_cleanup

        reserve = _nonnegative_int(
            os.environ.get(
                "SHAREDSIGNALS_DUCKDB_SNAPSHOT_RESERVE_BYTES",
                DEFAULT_RESERVE_BYTES,
            )
            if reserve_bytes is None
            else reserve_bytes,
            "snapshot reserve bytes",
        )
        logical_size = _logical_database_bytes(source)
        attempt_metadata["logical_source"] = logical_size
        filesystem = _filesystem_space(root)
        usage_ceiling = _usage_ceiling(
            os.environ.get(
                "SHAREDSIGNALS_DUCKDB_SNAPSHOT_MAX_FS_USAGE_PCT",
                DEFAULT_MAX_FS_USAGE_PERCENT,
            )
        )
    except SQLiteSnapshotError as exc:
        attempt_metadata.update(exc.metadata)
        exc.metadata = attempt_metadata
        raise
    except OSError as exc:
        raise SQLiteSnapshotError(
            "snapshot_preflight_failed",
            f"snapshot preflight filesystem failure: {exc}",
            attempt_metadata,
        ) from exc

    estimated_backup_bytes = max(
        int(source_info["size"]), int(logical_size["logical_bytes"])
    )
    required = estimated_backup_bytes + reserve
    projected_used = int(filesystem["used_bytes"]) + estimated_backup_bytes
    projected_usage = (
        100.0 * projected_used / int(filesystem["total_bytes"])
        if int(filesystem["total_bytes"])
        else 100.0
    )
    work_filesystems: list[dict] = []
    seen_devices = {int(filesystem["device"])}
    try:
        for raw_path in working_paths:
            work_path = Path(raw_path)
            probe_path = work_path if work_path.exists() else work_path.parent
            work_space = _filesystem_space(probe_path)
            device = int(work_space["device"])
            if device in seen_devices:
                continue
            seen_devices.add(device)
            work_filesystems.append(work_space)
    except OSError as exc:
        raise SQLiteSnapshotError(
            "snapshot_preflight_failed",
            f"cannot inspect DuckDB work filesystem: {exc}",
            attempt_metadata,
        ) from exc
    preflight = {
        **filesystem,
        "required_bytes": required,
        "source_file_bytes": int(source_info["size"]),
        "source_logical_bytes": int(logical_size["logical_bytes"]),
        "estimated_backup_bytes": estimated_backup_bytes,
        "wal_bytes": int(before["wal"].get("size") or 0),
        "reserve_bytes": reserve,
        "projected_usage_percent": round(projected_usage, 3),
        "max_usage_percent": usage_ceiling,
        "work_filesystems": work_filesystems,
    }
    attempt_metadata["space_preflight"] = preflight
    if int(filesystem["available_bytes"]) < required:
        raise SQLiteSnapshotError(
            "insufficient_space",
            "insufficient snapshot space: "
            f"need {required} bytes, available {filesystem['available_bytes']}",
            attempt_metadata,
        )
    if projected_usage > usage_ceiling:
        raise SQLiteSnapshotError(
            "insufficient_space",
            "snapshot would exceed filesystem usage ceiling: "
            f"projected {projected_usage:.2f}%, ceiling {usage_ceiling:.2f}%",
            attempt_metadata,
        )
    for work_space in work_filesystems:
        if (
            int(work_space["available_bytes"]) < reserve
            or float(work_space["usage_percent"]) > usage_ceiling
        ):
            raise SQLiteSnapshotError(
                "insufficient_space",
                "DuckDB work filesystem lacks reserve or exceeds usage ceiling",
                attempt_metadata,
            )

    try:
        timeout = _positive_finite_float(
            os.environ.get(
                "SHAREDSIGNALS_DUCKDB_SNAPSHOT_TIMEOUT",
                DEFAULT_TIMEOUT_SECONDS,
            )
            if timeout_seconds is None
            else timeout_seconds,
            "snapshot timeout",
        )
    except SQLiteSnapshotError as exc:
        attempt_metadata.update(exc.metadata)
        exc.metadata = attempt_metadata
        raise
    deadline = time.monotonic() + timeout
    temp_path = root / f"{SNAPSHOT_PREFIX}{snapshot_id}.sqlite.tmp"
    final_path = root / f"{SNAPSHOT_PREFIX}{snapshot_id}.sqlite"
    source_conn: sqlite3.Connection | None = None
    target_conn: sqlite3.Connection | None = None
    temp_inode: int | None = None
    primary_error: SQLiteSnapshotError | None = None
    validation: dict = {}
    try:
        fd = os.open(temp_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            temp_inode = os.fstat(fd).st_ino
        finally:
            os.close(fd)
        source_conn = sqlite3.connect(_source_readonly_uri(source), uri=True, timeout=30)
        target_conn = sqlite3.connect(str(temp_path), timeout=30)

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise SQLiteSnapshotError(
                    "snapshot_timeout", f"SQLite backup exceeded {timeout:.1f}s"
                )

        source_conn.backup(target_conn, pages=4096, progress=progress, sleep=0.05)
        target_conn.close()
        target_conn = None
        source_conn.close()
        source_conn = None
        temp_path.chmod(0o600)
        validation = _validate_snapshot(temp_path, required_tables)
        current = temp_path.lstat()
        if (
            temp_inode is None
            or current.st_ino != temp_inode
            or not stat.S_ISREG(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
        ):
            raise SQLiteSnapshotError(
                "snapshot_validation_failed",
                "snapshot temp changed before publish",
            )
        temp_path.replace(final_path)
    except SQLiteSnapshotError as exc:
        attempt_metadata.update(exc.metadata)
        exc.metadata = attempt_metadata
        primary_error = exc
    except PermissionError as exc:
        primary_error = SQLiteSnapshotError(
            "permission_denied",
            f"SQLite snapshot permission failure: {exc}",
            attempt_metadata,
        )
    except sqlite3.Error as exc:
        primary_error = SQLiteSnapshotError(
            "backup_failed", f"SQLite backup failed: {exc}", attempt_metadata
        )
    except OSError as exc:
        primary_error = SQLiteSnapshotError(
            "backup_failed",
            f"SQLite snapshot filesystem failure: {exc}",
            attempt_metadata,
        )
    finally:
        close_errors: list[str] = []
        for name, conn in (("target", target_conn), ("source", source_conn)):
            if conn is None:
                continue
            try:
                conn.close()
            except sqlite3.Error as exc:
                close_errors.append(f"{name}: {exc}")
        if close_errors and primary_error is None:
            primary_error = SQLiteSnapshotError(
                "cleanup_failed",
                "SQLite snapshot connection cleanup failed: " + "; ".join(close_errors),
                attempt_metadata,
            )
        if temp_inode is not None:
            try:
                attempt_metadata["temp_cleanup"] = _remove_exact_regular(
                    temp_path, temp_inode
                )
            except SQLiteSnapshotError as cleanup_error:
                if primary_error is not None:
                    cleanup_error.metadata["prior_error"] = {
                        "error_class": primary_error.error_class,
                        "message": str(primary_error),
                    }
                attempt_metadata.update(cleanup_error.metadata)
                cleanup_error.metadata = attempt_metadata
                primary_error = cleanup_error
        else:
            attempt_metadata["temp_cleanup"] = {"status": "not_created"}
        try:
            attempt_metadata["temp_sidecar_cleanup"] = _remove_snapshot_sidecars(
                temp_path
            )
        except SQLiteSnapshotError as cleanup_error:
            if primary_error is not None:
                cleanup_error.metadata["prior_error"] = {
                    "error_class": primary_error.error_class,
                    "message": str(primary_error),
                }
            attempt_metadata.update(cleanup_error.metadata)
            cleanup_error.metadata = attempt_metadata
            primary_error = cleanup_error

    if primary_error is not None:
        raise primary_error

    try:
        info = final_path.lstat()
        metadata = {
            "snapshot_id": snapshot_id,
            "created_at": _utc_now(),
            "elapsed_s": round(time.monotonic() - started, 3),
            "path": str(final_path),
            "bytes": info.st_size,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "source_before": before,
            "source_after": source_metadata(source),
            "space_preflight": preflight,
            "stale_cleanup": stale_cleanup,
            "validation": validation,
        }
    except Exception as exc:
        metadata_error = SQLiteSnapshotError(
            "snapshot_metadata_failed",
            f"snapshot metadata capture failed after publish: {exc}",
            attempt_metadata,
        )
        if temp_inode is not None:
            try:
                attempt_metadata["published_cleanup"] = _remove_exact_regular(
                    final_path, temp_inode
                )
                attempt_metadata["published_sidecar_cleanup"] = (
                    _remove_snapshot_sidecars(final_path)
                )
            except SQLiteSnapshotError as cleanup_error:
                cleanup_error.metadata["prior_error"] = {
                    "error_class": metadata_error.error_class,
                    "message": str(metadata_error),
                }
                attempt_metadata.update(cleanup_error.metadata)
                cleanup_error.metadata = attempt_metadata
                raise cleanup_error from metadata_error
        raise metadata_error from exc
    return SQLiteSnapshot(final_path, snapshot_id, metadata, info.st_ino)
