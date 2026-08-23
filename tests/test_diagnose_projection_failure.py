from __future__ import annotations

import sqlite3
from pathlib import Path

from tools import diagnose_projection_failure


def test_diagnose_reports_unknown_and_null_sources_without_writing(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "runs.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE market_ingest_runs (source TEXT, finished_at TEXT, run_id TEXT)"
        )
        connection.executemany(
            "INSERT INTO market_ingest_runs VALUES (?, ?, ?)",
            [
                ("known.dataset", "2026-08-23T00:00:00Z", "known-run"),
                ("unknown.dataset", "2026-08-23T00:01:00Z", "unknown-run"),
                (None, "2026-08-23T00:02:00Z", "null-run"),
            ],
        )

    class Registry:
        datasets = [type("Dataset", (), {"dataset_id": "known.dataset"})()]

    monkeypatch.setattr(diagnose_projection_failure, "load_dataset_registry", lambda: Registry())
    before = db_path.stat().st_mtime_ns

    result = diagnose_projection_failure.diagnose(db_path)

    assert result == {
        "unmapped_sources": [
            {
                "source": None,
                "rows": 1,
                "last_finished_at": "2026-08-23T00:02:00Z",
                "example_run_id": "null-run",
            },
            {
                "source": "unknown.dataset",
                "rows": 1,
                "last_finished_at": "2026-08-23T00:01:00Z",
                "example_run_id": "unknown-run",
            },
        ],
        "unmapped_source_count": 2,
    }
    assert db_path.stat().st_mtime_ns == before
