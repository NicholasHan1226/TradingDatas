from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

import pytest

from dataset_registry import DatasetRegistry, load_dataset_registry
import storage.ingest_receipts as receipt_module
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    insert_ingest_receipt,
)
from storage.schema import SCHEMA_SQL
import tools.run_provider_native_schedule as scheduler


ROOT = Path(__file__).resolve().parents[1]
TARGET_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"
SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64


@pytest.fixture(autouse=True)
def _snapshot_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maintenance = tmp_path / "read_model_maintenance.lock"
    maintenance.touch()
    monkeypatch.setenv("SHAREDSIGNALS_MAINTENANCE_LOCK_FILE", str(maintenance))


def _active_registry() -> DatasetRegistry:
    registry = load_dataset_registry(TARGET_REGISTRY)
    datasets = []
    for dataset in registry.datasets:
        binding = replace(
            dataset.provider_bindings[0],
            entitlement_state="active",
            activation_state="active",
        )
        datasets.append(replace(dataset, provider_bindings=(binding,)))
    return DatasetRegistry(tuple(datasets), query_defaults=registry.query_defaults)


def _database(path: Path) -> None:
    (path.parent / f".{path.name}.read_model_store.lock").touch()
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)


def _canonical_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    status: str,
    started_at: str,
    finished_at: str,
) -> None:
    dataset = _active_registry().resolve(dataset_id)
    binding = dataset.provider_bindings[0]
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    if status == "success":
        counts = IngestCounts(
            returned=1,
            validated=1,
            inserted=1,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1,
            count_semantics="exact_row_outcomes",
        )
        target_table: str | None = "provider_dataset_rows"
        errors: tuple[str, ...] = ()
    else:
        counts = IngestCounts(
            returned=0,
            validated=0,
            inserted=0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=0,
            count_semantics="terminal_no_data_transaction",
        )
        target_table = None
        errors = ("provider_error",)
    insert_ingest_receipt(
        conn,
        context=IngestContext(
            attempt_id=f"attempt-{dataset_id}-{status}",
            dataset_id=dataset_id,
            provider=binding.provider,
            provider_api=binding.api_name,
            request_window={},
            config_hash=CONFIG_HASH,
            adapter_version=binding.adapter_version,
            started_at=started_at,
            data_through="20260720",
        ),
        target_table=target_table,
        transaction_index=0,
        status=status,
        counts=counts,
        errors=errors,
        payload_fingerprint=PAYLOAD_FINGERPRINT,
    )
    conn.commit()


def test_generic_windows_cover_snapshot_partition_and_bounded_range() -> None:
    registry = _active_registry()
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    now = datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    plans, skipped = scheduler.plan_runs(
        registry=registry,
        schedule=schedule,
        last_finished_at={},
        now=now,
    )

    assert skipped == ()
    windows = {plan.dataset_id: dict(plan.request_window) for plan in plans}
    assert windows == {
        "cn.equity.daily": {"trade_date": "20260720"},
        "cn.equity.security_master": {},
        "cn.market.trade_calendar": {
            "end_date": "20260720",
            "start_date": "20260714",
        },
    }
    assert all(plan.provider for plan in plans)


def test_paused_and_locked_bindings_never_reach_executor(tmp_path: Path) -> None:
    registry = load_dataset_registry(TARGET_REGISTRY)
    datasets = []
    for index, dataset in enumerate(registry.datasets):
        binding = replace(
            dataset.provider_bindings[0],
            entitlement_state="locked" if index == 0 else "active",
            activation_state="paused",
        )
        datasets.append(replace(dataset, provider_bindings=(binding,)))
    dormant = DatasetRegistry(tuple(datasets), query_defaults=registry.query_defaults)
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    calls: list[object] = []

    result = scheduler.run_schedule(
        registry=dormant,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 19, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
        executor=lambda plan: calls.append(plan),
    )

    assert calls == []
    assert result.exit_code == 0
    assert result.executed == ()
    assert {item.state for item in result.skipped} == {"paused"}


def test_recent_terminal_receipt_makes_active_dataset_not_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="success",
            started_at="2026-07-20T07:00:00Z",
            finished_at="2026-07-20T08:30:00Z",
        )

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    skipped = {item.dataset_id: item.state for item in result.skipped}
    assert skipped["cn.equity.daily"] == "not_due"
    assert {item.dataset_id for item in result.executed} == {
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }


def test_failed_receipt_uses_short_retry_not_success_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="failed",
            started_at="2026-07-20T07:00:00Z",
            finished_at="2026-07-20T07:30:00Z",
        )

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    assert "cn.equity.daily" in {item.dataset_id for item in result.executed}


def test_failed_receipt_still_obeys_retry_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="failed",
            started_at="2026-07-20T08:45:00Z",
            finished_at="2026-07-20T08:55:00Z",
        )

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    skipped = {item.dataset_id: item.state for item in result.skipped}
    assert skipped["cn.equity.daily"] == "not_due"


def test_weak_envelope_cannot_pose_as_recent_success_receipt(tmp_path: Path) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO market_ingest_runs
               (run_id, started_at, finished_at, status, source,
                rows_read, rows_written, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "receipt:weak",
                "2026-07-20T08:30:00Z",
                "2026-07-20T08:40:00Z",
                "success",
                "cn.equity.daily",
                1,
                1,
                "{}",
            ),
        )

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    assert "cn.equity.daily" in {item.dataset_id for item in result.executed}


def test_subprocess_summary_requires_exact_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = scheduler.ScheduledRun(
        dataset_id="cn.equity.daily",
        provider="tushare",
        provider_api="daily",
        cadence_class="postclose_daily",
        request_window={"trade_date": "20260720"},
    )
    payload = {
        "counts": {
            "committed": 1,
            "inserted": 1,
            "rejected": 0,
            "returned": 1,
            "unchanged": 0,
            "updated": 0,
            "validated": 1,
        },
        "error_codes": [],
        "mode": "execute",
        "provider": "tushare",
        "provider_api": "daily",
        "receipt_count": 1,
        "state": "success",
    }
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    result = scheduler._subprocess_executor(
        plan,
        db_path=tmp_path / "facts.sqlite",
        timeout_seconds=60,
        started_at="2026-07-20T09:00:00Z",
    )

    assert result.state == "failed"
    assert result.exit_code == 4


def test_weekday_gate_skips_postclose_without_guessing_market_holidays(
    tmp_path: Path,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 19, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    skipped = {item.dataset_id: item.state for item in result.skipped}
    assert skipped["cn.equity.daily"] == "outside_weekdays"
    assert {item.dataset_id for item in result.executed} == {
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }


def test_failed_dataset_does_not_hide_later_terminal_results(tmp_path: Path) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    calls: list[str] = []

    def execute(plan: scheduler.ScheduledRun) -> scheduler.DatasetResult:
        calls.append(plan.dataset_id)
        if len(calls) == 1:
            return scheduler.DatasetResult(
                dataset_id=plan.dataset_id,
                provider=plan.provider,
                state="failed",
                exit_code=4,
            )
        return scheduler.DatasetResult(
            dataset_id=plan.dataset_id,
            provider=plan.provider,
            state="success",
            exit_code=0,
        )

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
        executor=execute,
    )

    assert calls == sorted(calls)
    assert len(result.executed) == 3
    assert [item.state for item in result.executed] == [
        "failed",
        "success",
        "success",
    ]
    assert result.exit_code == 1


def test_executor_cannot_relabel_a_scheduled_dataset(tmp_path: Path) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
        executor=lambda plan: scheduler.DatasetResult(
            dataset_id="other.dataset.identity",
            provider=plan.provider,
            state="success",
            exit_code=0,
        ),
    )

    assert result.exit_code == 1
    assert all(item.state == "failed" for item in result.executed)
    assert {item.dataset_id for item in result.executed} == {
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }


def test_executor_terminal_state_and_exit_code_must_agree(tmp_path: Path) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
        executor=lambda plan: scheduler.DatasetResult(
            dataset_id=plan.dataset_id,
            provider=plan.provider,
            state="success",
            exit_code=4,
        ),
    )

    assert result.exit_code == 1
    assert all(item.state == "failed" for item in result.executed)


def test_global_lock_rejects_overlap_before_provider_call(tmp_path: Path) -> None:
    lock_path = tmp_path / "scheduler.lock"
    calls: list[object] = []
    with scheduler.exclusive_schedule_lock(lock_path):
        with pytest.raises(scheduler.ScheduleBusyError):
            with scheduler.exclusive_schedule_lock(lock_path):
                calls.append("unreachable")
    assert calls == []


def test_collector_credentials_are_environment_only_with_protected_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/nonexistent-protected-home")
    monkeypatch.setenv("QUICKSYNC_API_URL", "https://api.quicksync.cn")
    monkeypatch.setenv("QUICKSYNC_TOKEN", "collector-secret")
    for name in scheduler._FORBIDDEN_COLLECTOR_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    scheduler._validated_collector_credentials()


@pytest.mark.parametrize(
    "url",
    [
        "http://api.quicksync.cn",
        "https://example.invalid",
        "https://api.quicksync.cn:444",
        "https://api.quicksync.cn/provider",
    ],
)
def test_collector_credentials_reject_unapproved_provider_routes(
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUICKSYNC_API_URL", url)
    monkeypatch.setenv("QUICKSYNC_TOKEN", "collector-secret")
    for name in scheduler._FORBIDDEN_COLLECTOR_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="collector API URL is invalid"):
        scheduler._validated_collector_credentials()


def test_scheduler_pins_the_reviewed_current_pointer_to_its_immutable_release(
    tmp_path: Path,
) -> None:
    release = tmp_path / "releases" / ("a" * 40)
    registry = release / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
    registry.parent.mkdir(parents=True)
    registry.write_text("version: 1\n", encoding="utf-8")
    current = tmp_path / "current"
    current.symlink_to(release, target_is_directory=True)
    environment = {
        scheduler.DATASET_REGISTRY_PATH_ENV: str(
            current / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
        )
    }

    pinned = scheduler._pin_runtime_registry_to_release(
        environment=environment,
        current_root=current,
        release_root=release,
    )

    assert pinned == registry
    assert environment[scheduler.DATASET_REGISTRY_PATH_ENV] == str(registry)


def test_scheduler_rejects_a_current_pointer_to_another_release(
    tmp_path: Path,
) -> None:
    expected_release = tmp_path / "releases" / ("a" * 40)
    expected_registry = (
        expected_release / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
    )
    expected_registry.parent.mkdir(parents=True)
    expected_registry.write_text("version: 1\n", encoding="utf-8")
    other_release = tmp_path / "releases" / ("b" * 40)
    other_release.mkdir(parents=True)
    current = tmp_path / "current"
    current.symlink_to(other_release, target_is_directory=True)
    environment = {
        scheduler.DATASET_REGISTRY_PATH_ENV: str(
            current / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
        )
    }

    with pytest.raises(ValueError, match="another release"):
        scheduler._pin_runtime_registry_to_release(
            environment=environment,
            current_root=current,
            release_root=expected_release,
        )


def test_scheduler_rejects_an_old_immutable_registry_after_current_moves(
    tmp_path: Path,
) -> None:
    old_release = tmp_path / "releases" / ("a" * 40)
    old_registry = old_release / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
    old_registry.parent.mkdir(parents=True)
    old_registry.write_text("version: 1\n", encoding="utf-8")
    active_release = tmp_path / "releases" / ("b" * 40)
    active_registry = active_release / scheduler.PROVIDER_NATIVE_REGISTRY_RELATIVE
    active_registry.parent.mkdir(parents=True)
    active_registry.write_text("version: 1\n", encoding="utf-8")
    current = tmp_path / "current"
    current.symlink_to(active_release, target_is_directory=True)
    environment = {scheduler.DATASET_REGISTRY_PATH_ENV: str(old_registry)}

    with pytest.raises(ValueError, match="another release"):
        scheduler._pin_runtime_registry_to_release(
            environment=environment,
            current_root=current,
            release_root=old_release,
        )


@pytest.mark.parametrize(
    "environment",
    [
        {"QUICKSYNC_API_URL": "https://api.quicksync.cn"},
        {
            "QUICKSYNC_API_URL": "https://api.quicksync.cn",
            "QUICKSYNC_TOKEN": "collector-secret",
            "TUSHARE_TOKEN": "wrong-secret-source",
        },
    ],
)
def test_missing_or_wrong_collector_secret_fails_before_registry_or_provider_call(
    environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in {
        "QUICKSYNC_API_URL",
        "QUICKSYNC_TOKEN",
        *scheduler._FORBIDDEN_COLLECTOR_CREDENTIALS,
    }:
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        scheduler,
        "load_runtime_dataset_registry",
        lambda: pytest.fail("invalid credentials must fail before registry access"),
    )

    code = scheduler.main(["--execute", "--lock-path", str(tmp_path / "schedule.lock")])

    output = capsys.readouterr().out
    assert code == 2
    assert json.loads(output)["state"] == "validation"
    assert "secret" not in output.casefold()


def test_schedule_config_has_no_dataset_or_provider_api_lists() -> None:
    raw = SCHEDULE_CONFIG.read_text(encoding="utf-8")
    assert "dataset_id" not in raw
    assert "api_name" not in raw
    assert "route" not in raw
    assert scheduler.load_schedule(SCHEDULE_CONFIG).cadences
    assert "failure_retry_seconds" in raw
    assert "weekdays" in raw


def test_main_emits_public_terminal_summary_without_request_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    monkeypatch.setattr(scheduler, "load_runtime_dataset_registry", _active_registry)

    code = scheduler.main(
        [
            "--db-path",
            str(db_path),
            "--schedule-config",
            str(SCHEDULE_CONFIG),
            "--lock-path",
            str(tmp_path / "run.lock"),
            "--now",
            "2026-07-20T17:00:00+08:00",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["mode"] == "plan"
    assert output["summary"]["planned"] == 3
    assert "202607" not in json.dumps(output)
