#!/usr/bin/env python3
"""SharedSignals SQLite recovery: detect corruption and recover/backup-switch.

This tool is intentionally fail-safe:
  - All public recovery functions default to ``dry_run=True``.
  - Real writes only happen when ``dry_run=False`` (or ``--apply`` on CLI).
  - A corrupt/missing DB is never replaced without first quarantining the old
    file and choosing a verified recovery source.

Recovery source precedence (``auto``):
  1. Most recent valid SQLite backup under the configured backup dirs.
  2. DuckDB mirror (rebuild authoritative SQLite from analytics mirror).
  3. None → blocked, requires human intervention.

Usage:
    python3 tools/sqlite_recovery.py --dry-run              # preview default DB
    python3 tools/sqlite_recovery.py --apply                # execute recovery
    python3 tools/sqlite_recovery.py --source duckdb --apply
    python3 tools/sqlite_recovery.py --db /tmp/bad.sqlite --backup-dir /tmp/bak
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from runtime_paths import marketdata_duckdb_path, marketdata_sqlite_path, sharedsignals_root
from storage.schema import SCHEMA_SQL
from storage.schema_contract import table_names

# ---------------------------------------------------------------------------
# Defaults (mirroring patrol.py / heal.py)
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = marketdata_sqlite_path()
DEFAULT_DUCKDB_PATH = marketdata_duckdb_path()
DEFAULT_SHARED_ROOT = sharedsignals_root()

# Tables that must exist and have at least some rows for a backup to be
# considered "not empty".  Empty backups are still valid if explicitly chosen.
REQUIRED_TABLES = (
    "market_assets",
    "market_bars_daily",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Corruption / health detection
# ---------------------------------------------------------------------------

def check_sqlite_corruption(db_path: Path | str, *, deep_check: bool = True) -> dict[str, Any]:
    """Read-only corruption probe for a SQLite file.

    Routine patrols should set ``deep_check=False`` so large production files
    are not fully scanned. Recovery and backup validation keep the default
    deep check.

    Returns a dict with keys:
      - status: "ok" | "corrupt" | "missing" | "unknown"
      - corrupt: bool
      - missing: bool
      - can_open: bool
      - integrity_ok: bool | None
      - integrity_msg: str
      - size: int
      - reason: str
      - checked_at: str
    """
    db_path = Path(db_path)
    result: dict[str, Any] = {
        "name": "sqlite_corruption",
        "status": "ok",
        "corrupt": False,
        "missing": False,
        "can_open": True,
        "integrity_ok": True,
        "integrity_msg": "ok",
        "size": 0,
        "reason": "",
        "checked_at": utc_now(),
        "deep_check": deep_check,
    }

    if not db_path.exists():
        result.update(
            status="missing",
            corrupt=False,
            missing=True,
            can_open=False,
            integrity_ok=None,
            integrity_msg="database_not_found",
            reason="database_not_found",
        )
        return result

    try:
        st = db_path.stat()
        result["size"] = st.st_size
    except OSError as exc:
        result.update(
            status="unknown",
            can_open=False,
            integrity_ok=None,
            integrity_msg=f"stat_error: {exc}",
            reason=f"stat_error: {exc}",
        )
        return result

    if st.st_size == 0:
        result.update(
            status="corrupt",
            corrupt=True,
            can_open=False,
            integrity_ok=False,
            integrity_msg="empty_file",
            reason="empty_database_file",
        )
        return result

    # Opening the schema catches malformed headers/pages without a full scan.
    # A full quick_check remains available for recovery and release gates.
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("SELECT 1").fetchone()
        conn.execute("PRAGMA schema_version").fetchone()
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        if deep_check:
            quick = conn.execute("PRAGMA quick_check").fetchone()
            if quick is None or quick[0] != "ok":
                msg = quick[0] if quick else "no_quick_check_result"
                result.update(
                    status="corrupt",
                    corrupt=True,
                    integrity_ok=False,
                    integrity_msg=msg,
                    reason=f"integrity_check_failed: {msg}",
                )
                return result
            result["integrity_ok"] = True
            result["integrity_msg"] = "ok"
        else:
            result["integrity_ok"] = True
            result["integrity_msg"] = "shallow_open_ok"
    except sqlite3.DatabaseError as exc:
        result.update(
            status="corrupt",
            corrupt=True,
            can_open=False,
            integrity_ok=False,
            integrity_msg=str(exc),
            reason=f"database_error: {exc}",
        )
        return result
    except sqlite3.OperationalError as exc:
        # Could be locked or malformed; treat as corrupt from a recovery POV.
        result.update(
            status="corrupt",
            corrupt=True,
            can_open=False,
            integrity_ok=False,
            integrity_msg=str(exc),
            reason=f"operational_error: {exc}",
        )
        return result
    except OSError as exc:
        result.update(
            status="unknown",
            can_open=False,
            integrity_ok=None,
            integrity_msg=f"open_error: {exc}",
            reason=f"open_error: {exc}",
        )
        return result
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return result


# ---------------------------------------------------------------------------
# Backup discovery / validation
# ---------------------------------------------------------------------------

def default_backup_dirs(db_path: Path | str) -> list[Path]:
    """Return default backup directories in search order."""
    db_path = Path(db_path)
    return [
        db_path.parent / "backups",
        DEFAULT_SHARED_ROOT / "backups",
    ]


def _sidecar_paths(db_path: Path) -> list[Path]:
    return [
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ]


def list_candidate_backups(
    backup_dirs: Optional[list[Path]] = None,
) -> list[dict[str, Any]]:
    """List SQLite backup candidates newest first.

    Looks for ``*.sqlite`` files in the configured backup directories.
    Does not validate content here; use :func:`validate_backup` for that.
    """
    if backup_dirs is None:
        backup_dirs = default_backup_dirs(DEFAULT_DB_PATH)

    candidates: list[dict[str, Any]] = []
    for directory in backup_dirs:
        if not directory.exists():
            continue
        for path in directory.glob("*.sqlite"):
            try:
                st = path.stat()
                candidates.append(
                    {
                        "path": str(path.resolve()),
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }
                )
            except OSError:
                continue

    candidates.sort(key=lambda x: x["mtime"], reverse=True)
    return candidates


def validate_backup(
    backup_path: Path | str,
    required_tables: Optional[tuple[str, ...]] = None,
) -> dict[str, Any]:
    """Validate that a SQLite backup can be opened and looks usable.

    Checks:
      - file exists and non-empty
      - can be opened
      - PRAGMA quick_check == "ok"
      - required tables exist and are non-empty (if required_tables given)
    """
    backup_path = Path(backup_path)
    result: dict[str, Any] = {
        "valid": False,
        "path": str(backup_path),
        "reason": "",
        "integrity_ok": False,
        "integrity_msg": "",
        "table_counts": {},
    }

    if not backup_path.exists():
        result["reason"] = "file_not_found"
        return result

    if backup_path.stat().st_size == 0:
        result["reason"] = "empty_file"
        return result

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(str(backup_path), timeout=5)
        quick = conn.execute("PRAGMA quick_check").fetchone()
        if quick is None or quick[0] != "ok":
            msg = quick[0] if quick else "no_result"
            result.update(
                integrity_ok=False,
                integrity_msg=msg,
                reason=f"integrity_check_failed: {msg}",
            )
            return result
        result["integrity_ok"] = True
        result["integrity_msg"] = "ok"

        tables = required_tables or REQUIRED_TABLES
        counts: dict[str, int] = {}
        for table in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                count = -1
            counts[table] = count
        result["table_counts"] = counts

        if any(c == -1 for c in counts.values()):
            missing = [t for t, c in counts.items() if c == -1]
            result["reason"] = f"missing_tables: {missing}"
            return result

        # Empty backup is technically valid but not useful for auto-recovery.
        if all(c == 0 for c in counts.values()):
            result["reason"] = "all_required_tables_empty"
            return result

        result["valid"] = True
        result["reason"] = "ok"
    except sqlite3.DatabaseError as exc:
        result.update(
            integrity_ok=False,
            integrity_msg=str(exc),
            reason=f"database_error: {exc}",
        )
    except OSError as exc:
        result["reason"] = f"open_error: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return result


def choose_recovery_source(
    db_path: Path | str,
    duckdb_path: Path | str = DEFAULT_DUCKDB_PATH,
    backup_dirs: Optional[list[Path]] = None,
    source_type: str = "auto",
) -> Optional[dict[str, Any]]:
    """Choose the best recovery source for *db_path*.

    ``source_type`` can be ``auto``, ``backup``, or ``duckdb``.
    Returns a dict with ``source_type`` and ``path``, or ``None`` if blocked.
    """
    db_path = Path(db_path)
    candidate_dirs = default_backup_dirs(db_path) if backup_dirs is None else backup_dirs
    if source_type in ("auto", "backup"):
        for candidate in list_candidate_backups(candidate_dirs):
            validation = validate_backup(candidate["path"])
            if validation["valid"]:
                return {
                    "source_type": "backup",
                    "path": Path(candidate["path"]),
                    "validation": validation,
                }

    if source_type in ("auto", "duckdb"):
        duckdb_path = Path(duckdb_path)
        if duckdb_path.exists() and _duckdb_has_data(duckdb_path):
            return {
                "source_type": "duckdb",
                "path": duckdb_path,
                "validation": {"valid": True, "reason": "duckdb_mirror_available"},
            }

    return None


def _duckdb_has_data(duckdb_path: Path) -> bool:
    """Return True if DuckDB mirror exists and has at least one required table."""
    try:
        import duckdb
    except Exception:
        return False

    conn: Optional[duckdb.DuckDBPyConnection] = None
    try:
        conn = duckdb.connect(str(duckdb_path), read_only=True)
        for table in REQUIRED_TABLES:
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count > 0:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Recovery actions
# ---------------------------------------------------------------------------

def _quarantine_bad_db(
    db_path: Path,
    quarantine_dir: Path,
    dry_run: bool = True,
) -> Optional[Path]:
    """Move the bad DB and its WAL/SHM sidecars into quarantine.

    Returns the quarantine path for the main DB, or None if there was nothing
    to quarantine.  In dry-run mode no files are moved.
    """
    if not db_path.exists():
        return None

    quarantine_dir = quarantine_dir or (db_path.parent / "backups")
    if not dry_run:
        quarantine_dir.mkdir(parents=True, exist_ok=True)

    tag = _timestamp_tag()
    main_target = quarantine_dir / f"marketdata_corrupt_{tag}.sqlite"

    if dry_run:
        return main_target

    # Move sidecars first so they don't get reused by a replacement file with
    # the same base name.
    for sidecar in _sidecar_paths(db_path):
        if sidecar.exists():
            try:
                sidecar_target = quarantine_dir / f"{main_target.stem}{sidecar.suffix}"
                shutil.move(str(sidecar), str(sidecar_target))
            except OSError as exc:
                # Best-effort: an orphan sidecar will be removed later.
                pass

    shutil.move(str(db_path), str(main_target))
    return main_target


def _install_file(source: Path, target: Path) -> None:
    """Atomically copy *source* to *target* via a temp file + os.replace."""
    tmp = target.with_name(f".{target.name}.{_timestamp_tag()}.tmp")
    try:
        shutil.copy2(str(source), str(tmp))
        os.replace(str(tmp), str(target))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _clean_sidecars(db_path: Path) -> None:
    for sidecar in _sidecar_paths(db_path):
        sidecar.unlink(missing_ok=True)


def _finalize_sqlite(db_path: Path) -> dict[str, Any]:
    """Run integrity check and WAL checkpoint on a freshly installed DB."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        quick = conn.execute("PRAGMA quick_check").fetchone()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _clean_sidecars(db_path)
        return {
            "integrity_ok": quick is not None and quick[0] == "ok",
            "integrity_msg": quick[0] if quick else "unknown",
        }
    finally:
        conn.close()


def _recover_from_backup(
    db_path: Path,
    source: dict[str, Any],
    quarantine_dir: Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Replace db_path with the chosen backup file."""
    backup_path = source["path"]
    action: dict[str, Any] = {
        "source_type": "backup",
        "source_path": str(backup_path),
        "dry_run": dry_run,
        "quarantine_path": None,
    }

    quarantine_path = _quarantine_bad_db(db_path, quarantine_dir, dry_run=dry_run)
    action["quarantine_path"] = str(quarantine_path) if quarantine_path else None

    if dry_run:
        action["recovered"] = True
        action["reason"] = "dry_run_would_restore_backup"
        action["next_step"] = "pass dry_run=False or --apply to execute"
        return action

    _install_file(backup_path, db_path)
    finalize = _finalize_sqlite(db_path)
    action.update(finalize)
    action["recovered"] = finalize["integrity_ok"]
    action["reason"] = "restored_from_backup" if finalize["integrity_ok"] else "backup_restore_failed_integrity"
    return action


def _recover_from_duckdb(
    db_path: Path,
    source: dict[str, Any],
    quarantine_dir: Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Rebuild db_path from a DuckDB mirror."""
    duckdb_path = source["path"]
    action: dict[str, Any] = {
        "source_type": "duckdb",
        "source_path": str(duckdb_path),
        "dry_run": dry_run,
        "quarantine_path": None,
        "table_counts": {},
    }

    quarantine_path = _quarantine_bad_db(db_path, quarantine_dir, dry_run=dry_run)
    action["quarantine_path"] = str(quarantine_path) if quarantine_path else None

    if dry_run:
        action["recovered"] = True
        action["reason"] = "dry_run_would_rebuild_from_duckdb"
        action["next_step"] = "pass dry_run=False or --apply to execute"
        return action

    import duckdb

    tmp_db = db_path.with_name(f".{db_path.name}.{_timestamp_tag()}.rebuild.sqlite")
    conn_dk: Optional[duckdb.DuckDBPyConnection] = None
    conn_sqlite: Optional[sqlite3.Connection] = None

    try:
        conn_dk = duckdb.connect(str(duckdb_path), read_only=True)
        conn_sqlite = sqlite3.connect(str(tmp_db), timeout=10)
        conn_sqlite.executescript(SCHEMA_SQL)
        conn_sqlite.execute("PRAGMA journal_mode=WAL")

        tables = table_names()
        total_rows = 0
        for table in tables:
            try:
                cols = _sqlite_table_columns(conn_sqlite, table)
                if not cols:
                    continue
                col_str = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join("?" for _ in cols)
                insert_sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})'

                # Stream rows from DuckDB in chunks to avoid memory spikes.
                cur = conn_dk.execute(f"SELECT {col_str} FROM {table}")
                chunk_size = 1000
                rows_inserted = 0
                while True:
                    rows = cur.fetchmany(chunk_size)
                    if not rows:
                        break
                    conn_sqlite.executemany(insert_sql, rows)
                    rows_inserted += len(rows)

                action["table_counts"][table] = rows_inserted
                total_rows += rows_inserted
            except Exception as exc:
                action["table_counts"][table] = f"error: {exc}"

        conn_sqlite.commit()
        action["total_rows"] = total_rows

        finalize = _finalize_sqlite(tmp_db)
        action.update(finalize)

        if finalize["integrity_ok"]:
            os.replace(str(tmp_db), str(db_path))
            action["recovered"] = True
            action["reason"] = "rebuilt_from_duckdb"
        else:
            action["recovered"] = False
            action["reason"] = "duckdb_rebuild_failed_integrity"
            tmp_db.unlink(missing_ok=True)
    except Exception as exc:
        action["recovered"] = False
        action["reason"] = f"duckdb_rebuild_error: {exc}"
        if tmp_db.exists():
            tmp_db.unlink(missing_ok=True)
    finally:
        if conn_dk is not None:
            try:
                conn_dk.close()
            except Exception:
                pass
        if conn_sqlite is not None:
            try:
                conn_sqlite.close()
            except Exception:
                pass

    return action


def _sqlite_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def recover(
    db_path: Path | str = DEFAULT_DB_PATH,
    duckdb_path: Path | str = DEFAULT_DUCKDB_PATH,
    backup_dirs: Optional[list[Path]] = None,
    source_type: str = "auto",
    dry_run: bool = True,
    force: bool = False,
    quarantine_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Detect corruption and recover *db_path* from a verified source.

    Args:
        db_path: Path to the SQLite database to recover.
        duckdb_path: Path to the DuckDB mirror.
        backup_dirs: Directories to search for ``*.sqlite`` backups.
        source_type: ``auto`` | ``backup`` | ``duckdb``.
        dry_run: If True, only plan and report; no files are changed.
        force: If True, recover even when the current DB appears healthy.
        quarantine_dir: Directory to move the bad DB into.  Defaults to
            ``db_path.parent / "backups"``.

    Returns:
        A dict describing the detected state, chosen source, and outcome.
    """
    db_path = Path(db_path)
    duckdb_path = Path(duckdb_path)
    if backup_dirs is None:
        backup_dirs = default_backup_dirs(db_path)
    if quarantine_dir is None:
        quarantine_dir = db_path.parent / "backups"

    detection = check_sqlite_corruption(db_path)
    needs_recovery = force or detection["status"] in ("corrupt", "missing")

    result: dict[str, Any] = {
        "action": "sqlite_recovery",
        "action_type": "recover",
        "target": str(db_path),
        "checked_at": detection["checked_at"],
        "detected": {
            "status": detection["status"],
            "corrupt": detection["corrupt"],
            "missing": detection["missing"],
            "integrity_ok": detection["integrity_ok"],
            "integrity_msg": detection["integrity_msg"],
            "size": detection["size"],
            "reason": detection["reason"],
        },
        "dry_run": dry_run,
        "force": force,
        "source_type": source_type,
        "source": None,
        "recovered": False,
        "reason": "",
        "quarantine_path": None,
    }

    if not needs_recovery:
        result["recovered"] = False
        result["reason"] = "database_healthy_no_recovery_needed"
        return result

    source = choose_recovery_source(
        db_path,
        duckdb_path=duckdb_path,
        backup_dirs=backup_dirs,
        source_type=source_type,
    )

    if source is None:
        result["recovered"] = False
        result["reason"] = "blocked_no_valid_recovery_source"
        result["next_step"] = (
            "provide a valid *.sqlite backup or ensure the DuckDB mirror is available; "
            "manual recovery required"
        )
        return result

    result["source"] = {
        "source_type": source["source_type"],
        "path": str(source["path"]),
        "validation": source.get("validation", {}),
    }

    if source["source_type"] == "backup":
        action = _recover_from_backup(
            db_path, source, quarantine_dir, dry_run=dry_run
        )
    else:
        action = _recover_from_duckdb(
            db_path, source, quarantine_dir, dry_run=dry_run
        )

    result.update(action)
    result["recovered"] = action.get("recovered", False)
    if not result.get("reason"):
        result["reason"] = action.get("reason", "")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--duckdb", default=str(DEFAULT_DUCKDB_PATH), help="DuckDB mirror path")
    parser.add_argument(
        "--backup-dir",
        action="append",
        dest="backup_dirs",
        help="Backup directory (can be given multiple times)",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "backup", "duckdb"],
        default="auto",
        help="Recovery source preference",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually execute recovery (default is dry-run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recover even if the DB appears healthy",
    )
    parser.add_argument(
        "--quarantine-dir",
        help="Directory to move the bad DB into",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    backup_dirs: Optional[list[Path]] = None
    if args.backup_dirs:
        backup_dirs = [Path(d) for d in args.backup_dirs]

    quarantine_dir: Optional[Path] = None
    if args.quarantine_dir:
        quarantine_dir = Path(args.quarantine_dir)

    result = recover(
        db_path=Path(args.db),
        duckdb_path=Path(args.duckdb),
        backup_dirs=backup_dirs,
        source_type=args.source,
        dry_run=not args.apply,
        force=args.force,
        quarantine_dir=quarantine_dir,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = result.get("status") or result.get("detected", {}).get("status")
        print(f"[{status}] {result.get('reason', '')}")
        if result.get("source"):
            print(f"  source: {result['source']['source_type']} -> {result['source']['path']}")
        if result.get("quarantine_path"):
            print(f"  quarantine: {result['quarantine_path']}")
        if result.get("recovered") is False and result.get("reason", "").startswith("blocked"):
            print("  BLOCKED: no valid recovery source")

    # Exit codes:
    #   0 = healthy, dry-run planned, or recovery succeeded
    #   1 = blocked or recovery failed
    if not args.apply and not result.get("recovered", False):
        # Dry-run preview is always a success exit unless blocked.
        if result.get("reason", "").startswith("blocked"):
            return 1
        return 0

    return 0 if result.get("recovered", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
