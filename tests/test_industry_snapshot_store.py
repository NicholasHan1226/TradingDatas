"""RED tests for storage/industry_snapshot_store.py — Task 5 atomic promotion."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from collectors.tushare.sw2021_reference import (
    IndustryCandidate,
    SnapshotValidation,
)
from storage.industry_snapshot_store import (
    _industry_lock,
    promote_snapshot,
    record_failed_attempt,
    reject_snapshot,
    start_snapshot,
)
from storage.read_model_store import _read_model_lock
from storage.schema import SCHEMA_SQL


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _fresh_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with the full contract schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    for stmt in SCHEMA_SQL.split(";"):
        clean = stmt.strip()
        if clean and not clean.startswith("--"):
            conn.execute(clean)
    conn.commit()
    return conn


def _valid_candidate(
    snapshot_id: str = "snap-new",
    source_run_id: str | None = None,
) -> IndustryCandidate:
    """Return a minimal but valid IndustryCandidate."""
    taxonomy = (
        MappingProxyType(
            {
                "taxonomy_node_key": f"{snapshot_id}-tax-01",
                "snapshot_id": snapshot_id,
                "taxonomy_system": "SW",
                "taxonomy_version": "SW2021",
                "level": "L1",
                "index_code": "L1-01",
                "industry_code": "010000",
                "industry_name": "Level 1 Industry",
                "parent_industry_code": "",
                "is_published": "1",
                "provider": "tushare_index_classify",
                "collected_at": "2026-07-11T00:00:00+00:00",
                "raw_json": '{"index_code":"L1-01","industry_name":"Level 1 Industry","level":"L1"}',
            },
        ),
        MappingProxyType(
            {
                "taxonomy_node_key": f"{snapshot_id}-tax-02",
                "snapshot_id": snapshot_id,
                "taxonomy_system": "SW",
                "taxonomy_version": "SW2021",
                "level": "L2",
                "index_code": "L2-01",
                "industry_code": "010100",
                "industry_name": "Level 2 Industry",
                "parent_industry_code": "010000",
                "is_published": "1",
                "provider": "tushare_index_classify",
                "collected_at": "2026-07-11T00:00:00+00:00",
                "raw_json": '{"index_code":"L2-01","industry_name":"Level 2 Industry","level":"L2"}',
            },
        ),
        MappingProxyType(
            {
                "taxonomy_node_key": f"{snapshot_id}-tax-03",
                "snapshot_id": snapshot_id,
                "taxonomy_system": "SW",
                "taxonomy_version": "SW2021",
                "level": "L3",
                "index_code": "L3-01",
                "industry_code": "010101",
                "industry_name": "Level 3 Industry",
                "parent_industry_code": "010100",
                "is_published": "1",
                "provider": "tushare_index_classify",
                "collected_at": "2026-07-11T00:00:00+00:00",
                "raw_json": '{"index_code":"L3-01","industry_name":"Level 3 Industry","level":"L3"}',
            },
        ),
    )
    membership = (
        MappingProxyType(
            {
                "membership_key": f"{snapshot_id}-mem-01",
                "snapshot_id": snapshot_id,
                "market": "Ashare",
                "symbol": "000001.SZ",
                "name": "Stock 1",
                "l1_code": "L1-01",
                "l1_name": "Level 1 Industry",
                "l2_code": "L2-01",
                "l2_name": "Level 2 Industry",
                "l3_code": "L3-01",
                "l3_name": "Level 3 Industry",
                "in_date": "20210101",
                "out_date": "",
                "is_current": "Y",
                "provider": "tushare_index_member_all",
                "collected_at": "2026-07-11T00:00:00+00:00",
                "raw_json": json.dumps(
                    {
                        "provider_row": {"ts_code": "000001.SZ", "name": "Stock 1"},
                        "requested_l1": "L1-01",
                        "source_partitions": ["L1-01"],
                        "evidence_hash": "mock-hash",
                    },
                    separators=(",", ":"),
                ),
            },
        ),
    )
    return IndustryCandidate(
        snapshot_id=snapshot_id,
        started_at="2026-07-11T00:00:00+00:00",
        source_run_id=source_run_id or snapshot_id.replace("snap", "run", 1),
        taxonomy_rows=taxonomy,
        membership_rows=membership,
        partition_counts=MappingProxyType({"L1-01": 1}),
        deduplicated_partition_counts=MappingProxyType({"L1-01": 1}),
        declared_partition_counts=MappingProxyType({"L1-01": 1}),
        partition_scope_mismatches=(),
        partition_failures=MappingProxyType({}),
    )


def _accepted_validation() -> SnapshotValidation:
    return SnapshotValidation(
        accepted=True,
        errors=(),
        expected_partition_count=1,
        successful_partition_count=1,
        taxonomy_row_count=3,
        membership_row_count=1,
        unique_symbol_count=1,
        active_universe_count=1,
        coverage_ratio=1.0,
    )


def _rejected_validation(reason: str = "test_rejection") -> SnapshotValidation:
    return SnapshotValidation(
        accepted=False,
        errors=(reason,),
        expected_partition_count=1,
        successful_partition_count=0,
        taxonomy_row_count=3,
        membership_row_count=1,
        unique_symbol_count=1,
        active_universe_count=1,
        coverage_ratio=1.0,
    )


def _seed_promoted(conn: sqlite3.Connection, snapshot_id: str) -> None:
    """Insert a fully promoted snapshot with taxonomy/membership children."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO market_industry_snapshots
               (snapshot_id, taxonomy_system, taxonomy_version, provider,
                started_at, completed_at, status, expected_partition_count,
                successful_partition_count, taxonomy_row_count, membership_row_count,
                unique_symbol_count, active_universe_count, coverage_ratio,
                validation_errors_json, source_run_id, promoted_at)
               VALUES (?, 'SW', 'SW2021', 'tushare',
                '2026-07-10T00:00:00+00:00', '2026-07-10T01:00:00+00:00', 'promoted',
                1, 1, 3, 1, 1, 1, 1.0,
                '[]', 'run-old', '2026-07-10T01:00:00+00:00')""",
            (snapshot_id,),
        )
        conn.execute(
            """INSERT INTO market_industry_taxonomy
               (taxonomy_node_key, snapshot_id, taxonomy_system, taxonomy_version,
                level, index_code, industry_code, industry_name, parent_industry_code,
                is_published, provider, collected_at, raw_json)
               VALUES (?, ?, 'SW', 'SW2021', 'L1', 'L1-01', '010000', 'Old Industry',
                '', '1', 'tushare_index_classify', '2026-07-10T00:00:00+00:00',
                '{"old":true}')""",
            (f"{snapshot_id}-tax-old", snapshot_id),
        )
        conn.execute(
            """INSERT INTO market_industry_memberships
               (membership_key, snapshot_id, market, symbol, name, l1_code, l1_name,
                l2_code, l2_name, l3_code, l3_name, in_date, out_date, is_current,
                provider, collected_at, raw_json)
               VALUES (?, ?, 'Ashare', '000001.SZ', 'Old Stock',
                'L1-01', 'Old Industry', 'L2-01', 'Old L2', 'L3-01', 'Old L3',
                '20210101', '', 'Y', 'tushare_index_member_all',
                '2026-07-10T00:00:00+00:00', '{"old":true}')""",
            (f"{snapshot_id}-mem-old", snapshot_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _current_snapshot_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT snapshot_id FROM market_industry_snapshots WHERE status='promoted'"
    ).fetchone()
    return row[0] if row else None


def _snapshot_child_count(conn: sqlite3.Connection, snapshot_id: str) -> int:
    taxonomy = conn.execute(
        "SELECT COUNT(*) FROM market_industry_taxonomy WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()[0]
    memberships = conn.execute(
        "SELECT COUNT(*) FROM market_industry_memberships WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()[0]
    return taxonomy + memberships


def _snapshot_status(conn: sqlite3.Connection, snapshot_id: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM market_industry_snapshots WHERE snapshot_id=?",
        (snapshot_id,),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# start_snapshot tests
# ---------------------------------------------------------------------------


def test_industry_collection_uses_the_same_process_lock_as_read_model_writes() -> None:
    assert _industry_lock is _read_model_lock


def test_start_snapshot_creates_collecting_row() -> None:
    conn = _fresh_db()
    start_snapshot(
        conn,
        snapshot_id="snap-1",
        source_run_id="run-1",
        started_at="2026-07-11T00:00:00+00:00",
    )
    row = conn.execute(
        "SELECT status, taxonomy_system, taxonomy_version, provider, source_run_id "
        "FROM market_industry_snapshots WHERE snapshot_id='snap-1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "collecting"
    assert row[1] == "SW"
    assert row[2] == "SW2021"
    assert row[3] == "tushare"
    assert row[4] == "run-1"


def test_start_snapshot_rejects_duplicate_snapshot_id() -> None:
    conn = _fresh_db()
    start_snapshot(
        conn, snapshot_id="snap-dup", source_run_id="run-1",
        started_at="2026-07-11T00:00:00+00:00",
    )
    with pytest.raises(sqlite3.IntegrityError):
        start_snapshot(
            conn, snapshot_id="snap-dup", source_run_id="run-2",
            started_at="2026-07-11T01:00:00+00:00",
        )


def test_start_snapshot_rejects_empty_snapshot_id() -> None:
    conn = _fresh_db()
    with pytest.raises(ValueError, match="snapshot_id"):
        start_snapshot(
            conn, snapshot_id="  ", source_run_id="run-1",
            started_at="2026-07-11T00:00:00+00:00",
        )


def test_start_snapshot_rejects_empty_source_run_id() -> None:
    conn = _fresh_db()
    with pytest.raises(ValueError, match="source_run_id"):
        start_snapshot(
            conn, snapshot_id="snap-1", source_run_id="",
            started_at="2026-07-11T00:00:00+00:00",
        )


def test_start_snapshot_commits_independently() -> None:
    """Each start_snapshot call commits its own transaction."""
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-a", source_run_id="run-a",
                   started_at="2026-07-11T00:00:00+00:00")
    # Second call should see first row and not deadlock
    start_snapshot(conn, snapshot_id="snap-b", source_run_id="run-b",
                   started_at="2026-07-11T01:00:00+00:00")
    rows = conn.execute(
        "SELECT snapshot_id FROM market_industry_snapshots ORDER BY snapshot_id"
    ).fetchall()
    assert [r[0] for r in rows] == ["snap-a", "snap-b"]


# ---------------------------------------------------------------------------
# reject_snapshot tests
# ---------------------------------------------------------------------------


def test_reject_snapshot_records_structured_errors() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-rej", source_run_id="run-rej",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-rej")
    validation = _rejected_validation("coverage_below_0.90")
    reject_snapshot(
        conn, candidate, validation,
        completed_at="2026-07-11T01:00:00+00:00",
    )
    row = conn.execute(
        "SELECT status, validation_errors_json, completed_at "
        "FROM market_industry_snapshots WHERE snapshot_id='snap-rej'"
    ).fetchone()
    assert row[0] == "rejected"
    errors = json.loads(row[1])
    assert "coverage_below_0.90" in errors
    assert row[2] == "2026-07-11T01:00:00+00:00"


def test_reject_snapshot_preserves_old_promoted() -> None:
    conn = _fresh_db()
    _seed_promoted(conn, "snap-old")
    start_snapshot(conn, snapshot_id="snap-rej", source_run_id="run-rej",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-rej")
    validation = _rejected_validation("partition_fetch_failed")
    reject_snapshot(
        conn, candidate, validation,
        completed_at="2026-07-11T01:00:00+00:00",
    )
    assert _current_snapshot_id(conn) == "snap-old"
    assert _snapshot_status(conn, "snap-old") == "promoted"
    assert _snapshot_status(conn, "snap-rej") == "rejected"


def test_reject_snapshot_rejects_empty_snapshot_id() -> None:
    conn = _fresh_db()
    # Candidate with empty snapshot_id after strip
    candidate = replace(_valid_candidate("snap-x"), snapshot_id="   ")
    with pytest.raises(ValueError, match="snapshot_id"):
        reject_snapshot(
            conn, candidate, _rejected_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_reject_snapshot_rejects_time_inversion() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-rej", source_run_id="run-rej",
                   started_at="2026-07-11T02:00:00+00:00")
    candidate = replace(_valid_candidate("snap-rej"),
                        started_at="2026-07-11T03:00:00+00:00")
    with pytest.raises(ValueError, match="started_at.*completed_at"):
        reject_snapshot(
            conn, candidate, _rejected_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_reject_snapshot_requires_matching_collecting_attempt() -> None:
    conn = _fresh_db()
    candidate = _valid_candidate("snap-missing")
    with pytest.raises(RuntimeError, match="matching collecting attempt"):
        reject_snapshot(
            conn,
            candidate,
            _rejected_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_record_failed_attempt_persists_structured_provider_evidence() -> None:
    conn = _fresh_db()
    start_snapshot(
        conn,
        snapshot_id="snap-provider-fail",
        source_run_id="run-provider-fail",
        started_at="2026-07-11T00:00:00+00:00",
    )
    record_failed_attempt(
        conn,
        snapshot_id="snap-provider-fail",
        source_run_id="run-provider-fail",
        started_at="2026-07-11T00:00:00+00:00",
        completed_at="2026-07-11T00:01:00+00:00",
        code="taxonomy_fetch_failed",
        evidence={"page": 2},
    )
    row = conn.execute(
        "SELECT status, validation_errors_json FROM market_industry_snapshots "
        "WHERE snapshot_id='snap-provider-fail'"
    ).fetchone()
    assert row[0] == "rejected"
    assert json.loads(row[1]) == [
        {"code": "taxonomy_fetch_failed", "evidence": {"page": 2}}
    ]


# ---------------------------------------------------------------------------
# promote_snapshot tests
# ---------------------------------------------------------------------------


def test_promotion_supersedes_previous_snapshot_in_one_transaction() -> None:
    conn = _fresh_db()
    _seed_promoted(conn, "snap-old")
    start_snapshot(conn, snapshot_id="snap-new", source_run_id="run-new",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-new")
    validation = _accepted_validation()
    promote_snapshot(
        conn, candidate, validation,
        completed_at="2026-07-11T02:00:00+00:00",
    )
    assert _snapshot_status(conn, "snap-old") == "superseded"
    assert _snapshot_status(conn, "snap-new") == "promoted"
    assert _current_snapshot_id(conn) == "snap-new"


def test_write_failure_rolls_back_new_rows_and_keeps_old_promoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage.industry_snapshot_store as store

    conn = _fresh_db()
    _seed_promoted(conn, "snap-old")
    start_snapshot(conn, snapshot_id="snap-new", source_run_id="run-new",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-new")
    validation = _accepted_validation()

    original_insert = store._insert_memberships

    def _failing_insert(*args: Any, **kwargs: Any) -> int:
        raise sqlite3.OperationalError("simulated write failure")

    monkeypatch.setattr(store, "_insert_memberships", _failing_insert)
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated write failure"):
            promote_snapshot(
                conn, candidate, validation,
                completed_at="2026-07-11T02:00:00+00:00",
            )
    finally:
        monkeypatch.setattr(store, "_insert_memberships", original_insert)

    assert _snapshot_status(conn, "snap-old") == "promoted"
    assert _snapshot_status(conn, "snap-new") == "collecting"
    assert _snapshot_child_count(conn, "snap-new") == 0
    assert _current_snapshot_id(conn) == "snap-old"


def test_promote_rejects_not_accepted_validation() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-x")
    validation = _rejected_validation("test")
    with pytest.raises(ValueError, match="not accepted"):
        promote_snapshot(
            conn, candidate, validation,
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_requires_matching_collecting_attempt() -> None:
    conn = _fresh_db()
    _seed_promoted(conn, "snap-old")
    candidate = _valid_candidate("snap-missing")
    with pytest.raises(RuntimeError, match="matching collecting attempt"):
        promote_snapshot(
            conn,
            candidate,
            _accepted_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )
    assert _current_snapshot_id(conn) == "snap-old"


def test_promote_rejects_mismatched_collecting_lineage() -> None:
    conn = _fresh_db()
    start_snapshot(
        conn,
        snapshot_id="snap-x",
        source_run_id="different-run",
        started_at="2026-07-11T00:00:00+00:00",
    )
    with pytest.raises(RuntimeError, match="matching collecting attempt"):
        promote_snapshot(
            conn,
            _valid_candidate("snap-x"),
            _accepted_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_rejects_empty_snapshot_id() -> None:
    conn = _fresh_db()
    candidate = replace(_valid_candidate("snap-x"), snapshot_id="")
    with pytest.raises(ValueError, match="snapshot_id"):
        promote_snapshot(
            conn, candidate, _accepted_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_rejects_time_inversion() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T02:00:00+00:00")
    candidate = replace(_valid_candidate("snap-x"),
                        started_at="2026-07-11T03:00:00+00:00")
    with pytest.raises(ValueError, match="started_at.*completed_at"):
        promote_snapshot(
            conn, candidate, _accepted_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_verifies_taxonomy_count_matches() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-x")
    # Mismatch: validation says 3 taxonomy rows, but we tamper with the count
    validation = replace(_accepted_validation(), taxonomy_row_count=99)
    with pytest.raises(ValueError, match="taxonomy.*count"):
        promote_snapshot(
            conn, candidate, validation,
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_verifies_membership_count_matches() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-x")
    validation = replace(_accepted_validation(), membership_row_count=99)
    with pytest.raises(ValueError, match="membership.*count"):
        promote_snapshot(
            conn, candidate, validation,
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_promote_inserts_exact_taxonomy_and_membership_counts() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-x")
    validation = _accepted_validation()
    promote_snapshot(
        conn, candidate, validation,
        completed_at="2026-07-11T01:00:00+00:00",
    )
    tax_count = conn.execute(
        "SELECT COUNT(*) FROM market_industry_taxonomy WHERE snapshot_id='snap-x'"
    ).fetchone()[0]
    mem_count = conn.execute(
        "SELECT COUNT(*) FROM market_industry_memberships WHERE snapshot_id='snap-x'"
    ).fetchone()[0]
    assert tax_count == len(candidate.taxonomy_rows)
    assert mem_count == len(candidate.membership_rows)
    assert tax_count == validation.taxonomy_row_count
    assert mem_count == validation.membership_row_count


def test_promote_sets_promoted_at_to_completed_at() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-x"), _accepted_validation(),
        completed_at="2026-07-11T03:30:00+00:00",
    )
    row = conn.execute(
        "SELECT promoted_at, completed_at FROM market_industry_snapshots WHERE snapshot_id='snap-x'"
    ).fetchone()
    assert row[0] == "2026-07-11T03:30:00+00:00"
    assert row[1] == "2026-07-11T03:30:00+00:00"


def test_promote_asserts_exactly_one_promoted_after_commit() -> None:
    """No prior promoted → exactly one promoted after commit."""
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-x"), _accepted_validation(),
        completed_at="2026-07-11T01:00:00+00:00",
    )
    count = conn.execute(
        "SELECT COUNT(*) FROM market_industry_snapshots "
        "WHERE taxonomy_system='SW' AND taxonomy_version='SW2021' AND status='promoted'"
    ).fetchone()[0]
    assert count == 1


def test_promote_detects_zero_promoted_anomaly(monkeypatch: pytest.MonkeyPatch) -> None:
    """If something deletes the promoted row mid-transaction, fail."""
    import storage.industry_snapshot_store as store

    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")

    original_check = store._assert_exactly_one_promoted

    def _fail_check(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("zero promoted rows detected")

    monkeypatch.setattr(store, "_assert_exactly_one_promoted", _fail_check)
    try:
        with pytest.raises(RuntimeError, match="zero promoted"):
            promote_snapshot(
                conn, _valid_candidate("snap-x"), _accepted_validation(),
                completed_at="2026-07-11T01:00:00+00:00",
            )
    finally:
        monkeypatch.setattr(store, "_assert_exactly_one_promoted", original_check)

    # Rollback must leave no new taxonomy/membership rows
    assert _snapshot_child_count(conn, "snap-x") == 0


def test_first_promotion_with_no_prior_promoted_succeeds() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-first", source_run_id="run-first",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-first"), _accepted_validation(),
        completed_at="2026-07-11T01:00:00+00:00",
    )
    assert _current_snapshot_id(conn) == "snap-first"
    assert _snapshot_status(conn, "snap-first") == "promoted"


def test_promote_rejects_invalid_snapshot_id_in_candidate() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = replace(_valid_candidate("snap-x"), snapshot_id="other-snap")
    with pytest.raises(ValueError, match="snapshot_id mismatch"):
        promote_snapshot(
            conn, candidate, _accepted_validation(),
            completed_at="2026-07-11T01:00:00+00:00",
        )


def test_membership_rows_contain_correct_snapshot_id() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-x"), _accepted_validation(),
        completed_at="2026-07-11T01:00:00+00:00",
    )
    row = conn.execute(
        "SELECT snapshot_id, symbol FROM market_industry_memberships WHERE snapshot_id='snap-x'"
    ).fetchone()
    assert row[0] == "snap-x"
    assert row[1] == "000001.SZ"


def test_taxonomy_rows_contain_correct_snapshot_id() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-x"), _accepted_validation(),
        completed_at="2026-07-11T01:00:00+00:00",
    )
    rows = conn.execute(
        "SELECT snapshot_id, level FROM market_industry_taxonomy WHERE snapshot_id='snap-x' ORDER BY level"
    ).fetchall()
    assert [r[0] for r in rows] == ["snap-x", "snap-x", "snap-x"]
    assert [r[1] for r in rows] == ["L1", "L2", "L3"]


# ---------------------------------------------------------------------------
# Snapshot snapshot row completeness
# ---------------------------------------------------------------------------


def test_promote_updates_all_snapshot_counts() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    promote_snapshot(
        conn, _valid_candidate("snap-x"), _accepted_validation(),
        completed_at="2026-07-11T01:00:00+00:00",
    )
    row = conn.execute(
        """SELECT expected_partition_count, successful_partition_count,
                  taxonomy_row_count, membership_row_count,
                  unique_symbol_count, active_universe_count, coverage_ratio
           FROM market_industry_snapshots WHERE snapshot_id='snap-x'"""
    ).fetchone()
    assert row[0] == 1
    assert row[1] == 1
    assert row[2] == 3
    assert row[3] == 1
    assert row[4] == 1
    assert row[5] == 1
    assert row[6] == 1.0


def test_reject_updates_all_snapshot_counts() -> None:
    conn = _fresh_db()
    start_snapshot(conn, snapshot_id="snap-x", source_run_id="run-x",
                   started_at="2026-07-11T00:00:00+00:00")
    candidate = _valid_candidate("snap-x")
    validation = _rejected_validation("coverage_below_0.90")
    reject_snapshot(
        conn, candidate, validation,
        completed_at="2026-07-11T01:00:00+00:00",
    )
    row = conn.execute(
        """SELECT status, expected_partition_count, successful_partition_count,
                  validation_errors_json
           FROM market_industry_snapshots WHERE snapshot_id='snap-x'"""
    ).fetchone()
    assert row[0] == "rejected"
    assert row[1] == 1
    assert row[2] == 0
    assert "coverage_below_0.90" in row[3]
