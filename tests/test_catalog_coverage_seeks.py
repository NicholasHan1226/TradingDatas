"""Coverage retains exact aggregates while avoiding per-row MIN/MAX work."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from catalog_service import _dataset_coverage


@pytest.mark.parametrize("indexed", [False, True])
def test_coverage_matches_combined_aggregate_for_dataset_and_schema(indexed):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE provider_dataset_rows(dataset_id TEXT, schema_major INTEGER, observed_at TEXT)"
    )
    if indexed:
        conn.execute(
            "CREATE INDEX provider_dataset_rows_coverage_idx ON provider_dataset_rows(dataset_id,schema_major,observed_at)"
        )
    conn.executemany(
        "INSERT INTO provider_dataset_rows VALUES(?,?,?)",
        [
            ("chosen", 1, "2026-09-01T00:00:00Z"),
            ("chosen", 1, "2026-09-01T00:00:00Z"),
            ("chosen", 1, "2026-09-05T00:00:00+08:00"),
            ("chosen", 2, "2020-01-01T00:00:00Z"),
            ("other", 1, "2030-01-01T00:00:00Z"),
        ],
    )
    for identity in (("chosen", 1), ("chosen", 2), ("missing", 1), ("chosen", 3)):
        expected = conn.execute(
            "SELECT COUNT(*),MIN(observed_at),MAX(observed_at) FROM provider_dataset_rows WHERE dataset_id=? AND schema_major=?",
            identity,
        ).fetchone()
        actual = _dataset_coverage(
            conn, SimpleNamespace(dataset_id=identity[0], schema_major=identity[1])
        )
        assert tuple(actual.values()) == expected
    conn.close()


def test_coverage_uses_fewer_vm_steps_without_changing_values():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE provider_dataset_rows(dataset_id TEXT, schema_major INTEGER, observed_at TEXT)"
    )
    conn.execute(
        "CREATE INDEX provider_dataset_rows_coverage_idx ON provider_dataset_rows(dataset_id,schema_major,observed_at)"
    )
    conn.executemany(
        "INSERT INTO provider_dataset_rows VALUES('chosen',1,?)",
        [(f"2026-09-05T00:{i:05d}",) for i in range(10000)],
    )
    steps = 0

    def progress():
        nonlocal steps
        steps += 1
        return 0

    conn.set_progress_handler(progress, 1)
    before = conn.execute(
        "SELECT COUNT(*),MIN(observed_at),MAX(observed_at) FROM provider_dataset_rows WHERE dataset_id='chosen' AND schema_major=1"
    ).fetchone()
    baseline_steps = steps
    steps = 0
    after = _dataset_coverage(
        conn, SimpleNamespace(dataset_id="chosen", schema_major=1)
    )
    candidate_steps = steps
    conn.set_progress_handler(None, 0)
    assert tuple(after.values()) == before
    assert candidate_steps < baseline_steps * 0.5
    plan = "\n".join(
        row[-1]
        for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM provider_dataset_rows "
            "INDEXED BY provider_dataset_rows_coverage_idx "
            "WHERE dataset_id='chosen' AND schema_major=1"
        )
    )
    assert "COVERING INDEX provider_dataset_rows_coverage_idx" in plan
    conn.close()


def test_coverage_prefetch_discards_count_and_keeps_exact_aggregates(
    tmp_path: Path,
) -> None:
    from catalog_service import _dataset_coverage, fault_in_catalog_coverage_index
    from storage.receipt_projection import RuntimeProjectionError
    from storage.schema import SCHEMA_SQL
    from storage.sqlite_authority_lock import sqlite_authority_lock

    db_path = tmp_path / "provider_native.sqlite"
    writer = sqlite3.connect(db_path)
    try:
        writer.executescript(SCHEMA_SQL)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.executemany(
            """INSERT INTO provider_dataset_rows
               (dataset_id, provider, schema_major, ingested_schema_version,
                row_key, observed_at, partition_value, payload_json,
                payload_hash, quality_state, quality_issues_json,
                collected_at, receipt_id, revision)
               VALUES (?, 'tushare', 1, 'v1', ?, ?, NULL, '{}', ?, 'valid', '[]',
                       '2026-09-05T00:00:00Z', ?, 1)""",
            [
                ("chosen", "k1", "2026-09-01T00:00:00Z", "h1", "receipt:1"),
                ("chosen", "k2", "2026-09-05T00:00:00Z", "h2", "receipt:1"),
                ("other", "k9", "2030-01-01T00:00:00Z", "h9", "receipt:2"),
            ],
        )
        writer.commit()
        with sqlite_authority_lock(db_path, mode="exclusive", create=True):
            pass
        before = writer.execute(
            "SELECT COUNT(*), MIN(observed_at), MAX(observed_at) "
            "FROM provider_dataset_rows WHERE dataset_id='chosen' AND schema_major=1"
        ).fetchone()
        fault_in_catalog_coverage_index(db_path)
        after = _dataset_coverage(
            writer, SimpleNamespace(dataset_id="chosen", schema_major=1)
        )
        assert tuple(after.values()) == before
        missing = tmp_path / "missing.sqlite"
        with pytest.raises(RuntimeProjectionError):
            fault_in_catalog_coverage_index(missing)
    finally:
        writer.close()
