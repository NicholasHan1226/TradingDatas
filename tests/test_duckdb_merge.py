from __future__ import annotations

import json

import duckdb_merge
import pytest


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
    assert result["error_class"] == "sync_failed"


def test_run_merge_reports_count_mismatch_as_error() -> None:
    result = duckdb_merge.run_merge(adapter=_CountMismatchAdapter())

    assert result["status"] == "error"
    assert result["mismatched_tables"] == ["market_assets"]
    assert result["reconciliation"]["market_assets"]["delta"] == -1
    assert result["error_class"] == "reconciliation_failed"


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

    written = json.loads(status_path.read_text(encoding="utf-8"))
    assert written == json.loads(merge_log.read_text(encoding="utf-8"))
    assert written | result == written
    assert written["consecutive_failure_count"] == 0
    assert written["last_success_at"] == result["merge_at"]
    assert written["recent_failures"] == []


def test_record_result_retains_failure_diagnostics_after_success(tmp_path, monkeypatch) -> None:
    merge_log = tmp_path / "duckdb_merge.jsonl"
    status_path = tmp_path / "watchdog_inputs" / "duckdb_sync.json"
    monkeypatch.setattr(duckdb_merge, "LOG_DIR", tmp_path)
    monkeypatch.setattr(duckdb_merge, "MERGE_LOG", merge_log)
    monkeypatch.setattr(duckdb_merge, "STATUS_PATH", status_path)

    duckdb_merge.record_result({
        "status": "error",
        "merge_at": "2026-07-13T01:00:00+00:00",
        "error_class": "snapshot_timeout",
        "error": "first",
    })
    duckdb_merge.record_result({
        "status": "error",
        "merge_at": "2026-07-13T02:00:00+00:00",
        "error_class": "backup_failed",
        "error": "second",
    })
    duckdb_merge.record_result({
        "status": "ok",
        "merge_at": "2026-07-13T03:00:00+00:00",
        "results": {},
    })

    written = json.loads(status_path.read_text(encoding="utf-8"))
    history = [json.loads(line) for line in merge_log.read_text().splitlines()]
    assert [row["consecutive_failure_count"] for row in history] == [1, 2, 0]
    assert written["last_failure_at"] == "2026-07-13T02:00:00+00:00"
    assert written["last_success_at"] == "2026-07-13T03:00:00+00:00"
    assert [row["error_class"] for row in written["recent_failures"]] == [
        "snapshot_timeout",
        "backup_failed",
    ]


def test_dry_run_does_not_change_failure_continuity(tmp_path, monkeypatch) -> None:
    merge_log = tmp_path / "duckdb_merge.jsonl"
    status_path = tmp_path / "watchdog_inputs" / "duckdb_sync.json"
    monkeypatch.setattr(duckdb_merge, "LOG_DIR", tmp_path)
    monkeypatch.setattr(duckdb_merge, "MERGE_LOG", merge_log)
    monkeypatch.setattr(duckdb_merge, "STATUS_PATH", status_path)
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({
        "status": "error",
        "consecutive_failure_count": 2,
        "last_success_at": "2026-07-12T01:00:00+00:00",
        "last_failure_at": "2026-07-13T01:00:00+00:00",
        "recent_failures": [{"at": "2026-07-13T01:00:00+00:00"}],
    }))

    duckdb_merge.record_result({
        "status": "dry_run",
        "merge_at": "2026-07-13T02:00:00+00:00",
    })

    written = json.loads(status_path.read_text())
    assert written["consecutive_failure_count"] == 2
    assert written["last_success_at"] == "2026-07-12T01:00:00+00:00"
    assert written["last_failure_at"] == "2026-07-13T01:00:00+00:00"
    assert written["recent_failures"] == [{"at": "2026-07-13T01:00:00+00:00"}]


def test_snapshot_failure_returns_before_sync_or_reconcile(monkeypatch) -> None:
    calls: list[str] = []

    class _LiveAdapter:
        sqlite_path = "/authority.sqlite"
        duckdb_path = "/mirror.duckdb"

        def sync_all_to_duckdb(self):
            calls.append("sync")

        def reconcile_counts(self, tables=None):
            calls.append("reconcile")

    monkeypatch.setattr(duckdb_merge, "StorageAdapter", _LiveAdapter)

    def fail_snapshot(*_args, **_kwargs):
        raise duckdb_merge.SQLiteSnapshotError(
            "insufficient_space",
            "space gate",
            {"space_preflight": {"available_bytes": 1, "required_bytes": 2}},
        )

    monkeypatch.setattr(duckdb_merge, "create_sqlite_snapshot", fail_snapshot)

    result = duckdb_merge.run_merge()

    assert result["status"] == "error"
    assert result["error_class"] == "insufficient_space"
    assert calls == []


def test_unclassified_preflight_failure_still_returns_red_artifact(monkeypatch) -> None:
    class _LiveAdapter:
        sqlite_path = "/authority.sqlite"
        duckdb_path = "/mirror.duckdb"

    monkeypatch.setattr(duckdb_merge, "StorageAdapter", _LiveAdapter)
    monkeypatch.setattr(
        duckdb_merge,
        "create_sqlite_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad preflight")),
    )

    result = duckdb_merge.run_merge()

    assert result["status"] == "error"
    assert result["error_class"] == "snapshot_preflight_failed"
    assert result["error_classes"] == ["snapshot_preflight_failed"]
    assert "bad preflight" in result["error"]


def test_default_merge_uses_one_snapshot_for_sync_and_reconcile(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshot.sqlite"
    snapshot_path.write_bytes(b"snapshot")
    calls: list[tuple[str, str]] = []

    class _Handle:
        path = snapshot_path
        metadata = {"snapshot_id": "snap-1"}

        def cleanup(self):
            calls.append(("cleanup", str(self.path)))
            return {"status": "ok"}

    class _Adapter:
        def __init__(self, sqlite_path="/authority.sqlite", duckdb_path="/mirror.duckdb"):
            self.sqlite_path = sqlite_path
            self.duckdb_path = duckdb_path

        def sync_all_to_duckdb(self):
            calls.append(("sync", str(self.sqlite_path)))
            return {"market_assets": 1}

        def reconcile_counts(self, tables=None):
            calls.append(("reconcile", str(self.sqlite_path)))
            return {"market_assets": {"status": "ok"}}

    monkeypatch.setattr(duckdb_merge, "StorageAdapter", _Adapter)
    monkeypatch.setattr(duckdb_merge, "create_sqlite_snapshot", lambda *_a, **_k: _Handle())

    result = duckdb_merge.run_merge()

    assert result["status"] == "ok"
    assert calls == [
        ("sync", str(snapshot_path)),
        ("reconcile", str(snapshot_path)),
        ("cleanup", str(snapshot_path)),
    ]


def test_loop_creates_a_fresh_snapshot_cycle_instead_of_reusing_adapter(monkeypatch) -> None:
    adapters: list[object] = []

    def fake_run_merge(adapter=None, table="", dry_run=False):
        adapters.append(adapter)
        return {"status": "ok", "total_rows": 0, "elapsed_s": 0}

    monkeypatch.setattr(duckdb_merge, "run_merge", fake_run_merge)
    monkeypatch.setattr(duckdb_merge, "record_result", lambda _result: None)
    class _StopLoop(Exception):
        pass

    def stop_loop(_seconds):
        raise _StopLoop

    monkeypatch.setattr(duckdb_merge.time, "sleep", stop_loop)

    with pytest.raises(_StopLoop):
        duckdb_merge.run_loop(1)

    assert adapters == [None]


def test_loop_dry_run_does_not_write_runtime_artifacts(monkeypatch) -> None:
    recorded: list[dict] = []

    class _StopLoop(Exception):
        pass

    monkeypatch.setattr(
        duckdb_merge,
        "run_merge",
        lambda adapter=None, table="", dry_run=False: {
            "status": "dry_run",
            "total_rows": 0,
            "elapsed_s": 0,
        },
    )
    monkeypatch.setattr(duckdb_merge, "record_result", recorded.append)

    def stop_loop(_seconds):
        raise _StopLoop

    monkeypatch.setattr(duckdb_merge.time, "sleep", stop_loop)

    with pytest.raises(_StopLoop):
        duckdb_merge.run_loop(1, dry_run=True)

    assert recorded == []
