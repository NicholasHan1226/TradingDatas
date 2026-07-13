from __future__ import annotations

import json

import duckdb_merge


class _PartialFailureAdapter:
    def sync_all_to_duckdb(self) -> dict[str, int]:
        return {"market_events": -1, "market_factors": 3}

    def reconcile_counts(self, tables=None) -> dict[str, dict[str, int | str]]:
        return {}


class _CountMismatchAdapter:
    def sync_all_to_duckdb(self) -> dict[str, int]:
        return {"market_assets": 2}

    def reconcile_counts(self, tables=None) -> dict[str, dict[str, int | str]]:
        return {
            "market_assets": {
                "sqlite_rows": 1,
                "duckdb_rows": 2,
                "delta": -1,
                "status": "mismatch",
            }
        }


class _SyncAndReconcileFailureAdapter:
    def sync_all_to_duckdb(self) -> dict[str, int]:
        return {"market_events": -1}

    def reconcile_counts(self, tables=None) -> dict[str, dict[str, int | str]]:
        raise RuntimeError("reconcile exploded")


def test_run_merge_reports_partial_table_failures_as_error() -> None:
    result = duckdb_merge.run_merge(adapter=_PartialFailureAdapter())

    assert result["status"] == "error"
    assert result["failed_tables"] == ["market_events"]
    assert result["total_rows"] == 3


def test_run_merge_reports_count_mismatch_as_error() -> None:
    result = duckdb_merge.run_merge(adapter=_CountMismatchAdapter())

    assert result["status"] == "error"
    assert result["mismatched_tables"] == ["market_assets"]
    assert result["reconciliation"]["market_assets"]["delta"] == -1


def test_run_merge_preserves_sync_failure_when_reconcile_also_fails() -> None:
    result = duckdb_merge.run_merge(adapter=_SyncAndReconcileFailureAdapter())

    assert result["status"] == "error"
    assert result["failed_tables"] == ["market_events"]
    assert result["reconciliation_error"] == "reconcile exploded"
    assert [issue["stage"] for issue in result["errors"]] == ["sync", "reconcile"]
    assert "DuckDB sync failed for: market_events" in result["error"]
    assert "reconcile exploded" in result["error"]


def test_record_result_atomically_updates_watchdog_artifact(tmp_path, monkeypatch) -> None:
    merge_log = tmp_path / "duckdb_merge.jsonl"
    status_path = tmp_path / "watchdog_inputs" / "duckdb_sync.json"
    monkeypatch.setattr(duckdb_merge, "LOG_DIR", tmp_path)
    monkeypatch.setattr(duckdb_merge, "MERGE_LOG", merge_log)
    monkeypatch.setattr(duckdb_merge, "STATUS_PATH", status_path)
    result = {"status": "ok", "merge_at": "2026-07-10T01:00:00+00:00", "results": {}}

    duckdb_merge.record_result(result)

    assert json.loads(status_path.read_text(encoding="utf-8")) == result
    assert json.loads(merge_log.read_text(encoding="utf-8")) == result
