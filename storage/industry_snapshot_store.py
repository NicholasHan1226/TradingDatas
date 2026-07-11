"""Atomic industry snapshot lifecycle store.

``start_snapshot``, ``reject_snapshot``, and ``promote_snapshot`` each run
inside their own SQLite ``BEGIN IMMEDIATE`` transaction.  A process-level
file lock (derived from the SQLite path) serialises the full collector run
so that cron and manual pilots cannot race.

``promote_snapshot`` is the critical section:
* re-checks that ``validation.accepted`` is True
* inserts every taxonomy and membership row and verifies the inserted count
  matches the candidate size
* supersedes any prior promoted ``SW/SW2021`` row **only after** the new
  candidate rows are fully written
* asserts exactly one promoted row for ``(SW, SW2021)``
* commits atomically — any exception triggers a full rollback and the old
  promoted row and its children survive untouched
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from collectors.tushare.sw2021_reference import IndustryCandidate, SnapshotValidation
from storage.read_model_store import _read_model_lock as _industry_lock

_TAXONOMY_INSERT_COLS = (
    "taxonomy_node_key", "snapshot_id", "taxonomy_system", "taxonomy_version",
    "level", "index_code", "industry_code", "industry_name", "parent_industry_code",
    "is_published", "provider", "collected_at", "raw_json",
)

_MEMBERSHIP_INSERT_COLS = (
    "membership_key", "snapshot_id", "market", "symbol", "name",
    "l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name",
    "in_date", "out_date", "is_current", "provider", "collected_at", "raw_json",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _validate_lineage(
    candidate: IndustryCandidate, completed_at: str
) -> None:
    """Reject empty IDs and time inversions before any DB write."""
    if not _text(candidate.snapshot_id):
        raise ValueError("snapshot_id must be non-empty")
    if not _text(candidate.source_run_id):
        raise ValueError("source_run_id must be non-empty")
    if not _text(candidate.started_at):
        raise ValueError("started_at must be non-empty")
    if not _text(completed_at):
        raise ValueError("completed_at must be non-empty")
    if candidate.started_at > completed_at:
        raise ValueError(
            f"started_at ({candidate.started_at}) must not be after "
            f"completed_at ({completed_at})"
        )


def _verify_candidate_internal_consistency(candidate: IndustryCandidate) -> None:
    """All child rows must reference the same snapshot_id as the candidate."""
    sid = _text(candidate.snapshot_id)
    for row in candidate.taxonomy_rows:
        if _text(row.get("snapshot_id")) != sid:
            raise ValueError(
                f"snapshot_id mismatch in taxonomy row: "
                f"expected {sid}, got {_text(row.get('snapshot_id'))}"
            )
    for row in candidate.membership_rows:
        if _text(row.get("snapshot_id")) != sid:
            raise ValueError(
                f"snapshot_id mismatch in membership row: "
                f"expected {sid}, got {_text(row.get('snapshot_id'))}"
            )


def _insert_taxonomy_rows(conn: sqlite3.Connection, rows: tuple) -> int:
    col_sql = ", ".join(_TAXONOMY_INSERT_COLS)
    placeholders = ", ".join("?" for _ in _TAXONOMY_INSERT_COLS)
    sql = (
        f"INSERT OR IGNORE INTO market_industry_taxonomy ({col_sql}) "
        f"VALUES ({placeholders})"
    )
    values = [
        [row.get(col, "") for col in _TAXONOMY_INSERT_COLS]
        for row in rows
    ]
    before = conn.total_changes
    conn.executemany(sql, values)
    return conn.total_changes - before


def _insert_memberships(conn: sqlite3.Connection, rows: tuple) -> int:
    col_sql = ", ".join(_MEMBERSHIP_INSERT_COLS)
    placeholders = ", ".join("?" for _ in _MEMBERSHIP_INSERT_COLS)
    sql = (
        f"INSERT OR IGNORE INTO market_industry_memberships ({col_sql}) "
        f"VALUES ({placeholders})"
    )
    values = [
        [row.get(col, "") for col in _MEMBERSHIP_INSERT_COLS]
        for row in rows
    ]
    before = conn.total_changes
    conn.executemany(sql, values)
    return conn.total_changes - before


def _assert_exactly_one_promoted(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        """SELECT COUNT(*) FROM market_industry_snapshots
           WHERE taxonomy_system='SW' AND taxonomy_version='SW2021'
             AND status='promoted'"""
    ).fetchone()
    count = row[0] if row else 0
    if count != 1:
        raise RuntimeError(
            f"expected exactly 1 promoted SW/SW2021 snapshot, found {count}"
        )


def _reject_collecting_attempt(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    source_run_id: str,
    started_at: str,
    completed_at: str,
    errors: list[Any],
    expected_partition_count: int = 0,
    successful_partition_count: int = 0,
    taxonomy_row_count: int = 0,
    membership_row_count: int = 0,
    unique_symbol_count: int = 0,
    active_universe_count: int = 0,
    coverage_ratio: float = 0.0,
) -> None:
    """Transition exactly one matching ``collecting`` attempt to rejected."""

    sid = _text(snapshot_id)
    srid = _text(source_run_id)
    sat = _text(started_at)
    cat = _text(completed_at)
    if not sid:
        raise ValueError("snapshot_id must be non-empty")
    if not srid:
        raise ValueError("source_run_id must be non-empty")
    if not sat:
        raise ValueError("started_at must be non-empty")
    if not cat:
        raise ValueError("completed_at must be non-empty")
    if sat > cat:
        raise ValueError(
            f"started_at ({sat}) must not be after completed_at ({cat})"
        )

    errors_json = json.dumps(errors, ensure_ascii=False, sort_keys=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            """UPDATE market_industry_snapshots
               SET status='rejected',
                   completed_at=?,
                   expected_partition_count=?,
                   successful_partition_count=?,
                   taxonomy_row_count=?,
                   membership_row_count=?,
                   unique_symbol_count=?,
                   active_universe_count=?,
                   coverage_ratio=?,
                   validation_errors_json=?
               WHERE snapshot_id=? AND status='collecting'
                 AND source_run_id=? AND started_at=?""",
            (
                cat,
                expected_partition_count,
                successful_partition_count,
                taxonomy_row_count,
                membership_row_count,
                unique_symbol_count,
                active_universe_count,
                coverage_ratio,
                errors_json,
                sid,
                srid,
                sat,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                "snapshot is not a matching collecting attempt: "
                f"snapshot_id={sid}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    source_run_id: str,
    started_at: str,
) -> None:
    """Create a ``collecting`` snapshot row.

    Must be called before collection begins.  Rejects empty IDs and
    duplicate ``snapshot_id`` (PK violation → ``IntegrityError``).
    """
    sid = _text(snapshot_id)
    srid = _text(source_run_id)
    sat = _text(started_at)
    if not sid:
        raise ValueError("snapshot_id must be non-empty")
    if not srid:
        raise ValueError("source_run_id must be non-empty")
    if not sat:
        raise ValueError("started_at must be non-empty")

    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            """INSERT INTO market_industry_snapshots
               (snapshot_id, taxonomy_system, taxonomy_version, provider,
                started_at, status, expected_partition_count,
                successful_partition_count, taxonomy_row_count,
                membership_row_count, unique_symbol_count,
                active_universe_count, coverage_ratio,
                validation_errors_json, source_run_id)
               VALUES (?, 'SW', 'SW2021', 'tushare', ?, 'collecting',
                0, 0, 0, 0, 0, 0, 0.0, '[]', ?)""",
            (sid, sat, srid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def reject_snapshot(
    conn: sqlite3.Connection,
    candidate: IndustryCandidate,
    validation: SnapshotValidation,
    *,
    completed_at: str,
) -> None:
    """Record a rejected attempt with structured validation errors.

    The old promoted snapshot (if any) is left untouched.  No taxonomy
    or membership rows are written.
    """
    _validate_lineage(candidate, completed_at)

    _reject_collecting_attempt(
        conn,
        snapshot_id=candidate.snapshot_id,
        source_run_id=candidate.source_run_id,
        started_at=candidate.started_at,
        completed_at=completed_at,
        errors=list(validation.errors),
        expected_partition_count=validation.expected_partition_count,
        successful_partition_count=validation.successful_partition_count,
        taxonomy_row_count=validation.taxonomy_row_count,
        membership_row_count=validation.membership_row_count,
        unique_symbol_count=validation.unique_symbol_count,
        active_universe_count=validation.active_universe_count,
        coverage_ratio=validation.coverage_ratio,
    )


def record_failed_attempt(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    source_run_id: str,
    started_at: str,
    completed_at: str,
    code: str,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    """Persist a provider, validation-pipeline, or write failure as rejected."""

    failure_code = _text(code)
    if not failure_code:
        raise ValueError("code must be non-empty")
    _reject_collecting_attempt(
        conn,
        snapshot_id=snapshot_id,
        source_run_id=source_run_id,
        started_at=started_at,
        completed_at=completed_at,
        errors=[
            {
                "code": failure_code,
                "evidence": dict(evidence or {}),
            }
        ],
    )


def promote_snapshot(
    conn: sqlite3.Connection,
    candidate: IndustryCandidate,
    validation: SnapshotValidation,
    *,
    completed_at: str,
) -> None:
    """Atomically promote a candidate snapshot.

    One transaction:
    1. Re-check ``validation.accepted``.
    2. Insert every taxonomy and membership row; verify inserted counts
       equal the candidate sizes.
    3. Supersede the prior promoted ``SW/SW2021`` row (if any).
    4. Mark *this* candidate as ``promoted``, set ``promoted_at``.
    5. Assert exactly one promoted ``SW/SW2021`` row.
    6. Commit.

    On any exception the transaction is rolled back — the old promoted
    row and its children are unchanged, and the new candidate has zero
    partial children.
    """
    if not validation.accepted:
        raise ValueError("cannot promote snapshot: validation not accepted")

    _validate_lineage(candidate, completed_at)
    _verify_candidate_internal_consistency(candidate)

    sid = _text(candidate.snapshot_id)
    errors_json = json.dumps(
        list(validation.errors), ensure_ascii=False, sort_keys=True
    )

    conn.execute("BEGIN IMMEDIATE")
    try:
        # 1. Re-verify accepted (defense in depth)
        if not validation.accepted:
            raise ValueError("cannot promote snapshot: validation not accepted")

        attempt = conn.execute(
            """SELECT 1 FROM market_industry_snapshots
               WHERE snapshot_id=? AND status='collecting'
                 AND source_run_id=? AND started_at=?
                 AND taxonomy_system='SW' AND taxonomy_version='SW2021'""",
            (sid, candidate.source_run_id, candidate.started_at),
        ).fetchone()
        if attempt is None:
            raise RuntimeError(
                "snapshot is not a matching collecting attempt: "
                f"snapshot_id={sid}"
            )

        # 2. Insert taxonomy rows and verify count
        tax_inserted = _insert_taxonomy_rows(conn, candidate.taxonomy_rows)
        if tax_inserted != len(candidate.taxonomy_rows):
            raise ValueError(
                f"taxonomy insert count mismatch: "
                f"expected {len(candidate.taxonomy_rows)}, "
                f"inserted {tax_inserted}"
            )
        if tax_inserted != validation.taxonomy_row_count:
            raise ValueError(
                f"taxonomy row count mismatch vs validation: "
                f"inserted {tax_inserted}, "
                f"validation says {validation.taxonomy_row_count}"
            )

        # 3. Insert membership rows and verify count
        mem_inserted = _insert_memberships(conn, candidate.membership_rows)
        if mem_inserted != len(candidate.membership_rows):
            raise ValueError(
                f"membership insert count mismatch: "
                f"expected {len(candidate.membership_rows)}, "
                f"inserted {mem_inserted}"
            )
        if mem_inserted != validation.membership_row_count:
            raise ValueError(
                f"membership row count mismatch vs validation: "
                f"inserted {mem_inserted}, "
                f"validation says {validation.membership_row_count}"
            )

        # Both taxonomy and membership must be non-zero
        if tax_inserted == 0:
            raise ValueError("taxonomy insert produced 0 rows")
        if mem_inserted == 0:
            raise ValueError("membership insert produced 0 rows")

        # 4. Supersede prior promoted SW/SW2021 row
        conn.execute(
            """UPDATE market_industry_snapshots
               SET status='superseded'
               WHERE taxonomy_system='SW' AND taxonomy_version='SW2021'
                 AND status='promoted'"""
        )

        # 5. Promote this candidate
        cursor = conn.execute(
            """UPDATE market_industry_snapshots
               SET status='promoted',
                   completed_at=?,
                   expected_partition_count=?,
                   successful_partition_count=?,
                   taxonomy_row_count=?,
                   membership_row_count=?,
                   unique_symbol_count=?,
                   active_universe_count=?,
                   coverage_ratio=?,
                   validation_errors_json=?,
                   promoted_at=?
               WHERE snapshot_id=? AND status='collecting'
                 AND source_run_id=? AND started_at=?""",
            (
                completed_at,
                validation.expected_partition_count,
                validation.successful_partition_count,
                validation.taxonomy_row_count,
                validation.membership_row_count,
                validation.unique_symbol_count,
                validation.active_universe_count,
                validation.coverage_ratio,
                errors_json,
                completed_at,
                sid,
                candidate.source_run_id,
                candidate.started_at,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                "snapshot is not a matching collecting attempt: "
                f"snapshot_id={sid}"
            )

        # 6. Assert exactly one promoted row
        _assert_exactly_one_promoted(conn)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
