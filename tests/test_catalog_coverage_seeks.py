"""Coverage retains exact aggregates while avoiding per-row MIN/MAX work."""

import sqlite3
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
    conn.close()
