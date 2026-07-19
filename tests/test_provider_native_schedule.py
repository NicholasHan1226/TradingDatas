from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
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
from storage.sqlite_authority_lock import sqlite_authority_lock_path
import tools.run_provider_native_schedule as scheduler


ROOT = Path(__file__).resolve().parents[1]
TARGET_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"
SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64


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
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
    sqlite_authority_lock_path(path).touch(mode=0o600)


def _canonical_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    status: str,
    started_at: str,
    finished_at: str,
    request_window: dict[str, str] | None = None,
    row_count: int = 1,
) -> str:
    dataset = _active_registry().resolve(dataset_id)
    binding = dataset.provider_bindings[0]
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    if status == "success":
        counts = IngestCounts(
            returned=row_count,
            validated=row_count,
            inserted=row_count,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=row_count,
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
    window = request_window or {}
    receipt_id = insert_ingest_receipt(
        conn,
        context=IngestContext(
            attempt_id=f"attempt-{dataset_id}-{status}-{hashlib.sha256(json.dumps(window, sort_keys=True).encode()).hexdigest()[:12]}-{finished_at}",
            dataset_id=dataset_id,
            provider=binding.provider,
            provider_api=binding.api_name,
            request_window=window,
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
    return receipt_id


def _fact(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset_id: str,
    receipt_id: str,
    partition: str,
    payload: dict[str, object],
) -> None:
    dataset = registry.resolve(dataset_id)
    binding = dataset.provider_bindings[0]
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    conn.execute(
        """INSERT INTO provider_dataset_rows
           (dataset_id, provider, schema_major, ingested_schema_version, row_key,
            observed_at, partition_value, payload_json, payload_hash, quality_state,
            quality_issues_json, collected_at, receipt_id, revision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid', '[]', ?, ?, 1)""",
        (
            dataset_id,
            binding.provider,
            dataset.schema_major,
            dataset.schema_version,
            f"{dataset_id}:{partition}",
            partition,
            partition,
            raw,
            hashlib.sha256(raw.encode()).hexdigest(),
            "2026-07-20T09:00:00Z",
            receipt_id,
        ),
    )


def _seed_calendar(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    sessions: dict[date, bool],
) -> None:
    ordered = sorted(sessions)
    window = {
        "start_date": ordered[0].strftime("%Y%m%d"),
        "end_date": ordered[-1].strftime("%Y%m%d"),
    }
    receipt = _canonical_receipt(
        monkeypatch,
        conn,
        dataset_id="cn.market.trade_calendar",
        status="success",
        started_at="2026-07-20T00:00:00Z",
        finished_at="2026-07-20T01:00:00Z",
        request_window=window,
        row_count=len(ordered),
    )
    for day in ordered:
        value = day.strftime("%Y%m%d")
        _fact(
            conn,
            registry,
            "cn.market.trade_calendar",
            receipt,
            value,
            {"cal_date": value, "exchange": "SSE", "is_open": int(sessions[day])},
        )
    conn.commit()


def _seed_daily(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    day: date,
    *,
    finished_at: str = "2026-07-19T09:00:00Z",
) -> str:
    value = day.strftime("%Y%m%d")
    finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    started = (finished - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    receipt = _canonical_receipt(
        monkeypatch,
        conn,
        dataset_id="cn.equity.daily",
        status="success",
        started_at=started,
        finished_at=finished_at,
        request_window={"trade_date": value},
    )
    _fact(
        conn,
        registry,
        "cn.equity.daily",
        receipt,
        value,
        {"trade_date": value, "ts_code": "000001.SZ"},
    )
    conn.commit()
    return receipt


def test_generic_windows_cover_snapshot_partition_and_bounded_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    now = datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})

    result = scheduler.run_schedule(
        registry=registry, schedule=schedule, db_path=db_path, now=now, execute=False
    )
    current = {
        plan.dataset_id: plan for plan in result.plans if plan.priority == "current"
    }
    assert dict(current["cn.equity.daily"].request_window) == {"trade_date": "20260720"}
    assert dict(current["cn.equity.security_master"].request_window) == {}
    assert {
        tuple(plan.request_variant.items())
        for plan in result.plans
        if plan.dataset_id == "cn.equity.security_master"
    } == {
        (("list_status", "L"),),
        (("list_status", "D"),),
        (("list_status", "P"),),
    }
    calendar = current["cn.market.trade_calendar"].request_window
    assert calendar["start_date"] == "20260720"
    assert calendar["end_date"] == "20270720"
    assert all(plan.provider for plan in result.plans)


def test_runtime_rate_budget_counts_actual_calls_across_datasets_and_apis() -> None:
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    ledger = scheduler.RuntimeRateBudgetLedger(schedule)
    limit = schedule.rate_budgets["standard"].account_requests_per_run

    for index in range(limit):
        plan = scheduler.ScheduledRun(
            dataset_id=f"cn.synthetic.{index}",
            provider="tushare" if index % 2 == 0 else "another-provider",
            provider_api=f"api_{index}",
            cadence_class="postclose_daily",
            request_window={},
            rate_budget_class="standard",
        )
        ledger.consume(plan, plan.provider_api)

    overflow = scheduler.ScheduledRun(
        dataset_id="cn.synthetic.overflow",
        provider="tushare",
        provider_api="overflow_api",
        cadence_class="postclose_daily",
        request_window={},
        rate_budget_class="standard",
    )
    with pytest.raises(scheduler.RequestBudgetExceeded):
        ledger.consume(overflow, overflow.provider_api)


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
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
        receipt = _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="success",
            started_at="2026-07-20T07:00:00Z",
            finished_at="2026-07-20T08:30:00Z",
            request_window={"trade_date": "20260720"},
        )
        _fact(
            conn,
            registry,
            "cn.equity.daily",
            receipt,
            "20260720",
            {"trade_date": "20260720"},
        )
        conn.commit()

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


def test_tampered_success_receipt_fails_planner_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
        receipt_id = _seed_daily(
            monkeypatch,
            conn,
            registry,
            date(2026, 7, 20),
            finished_at="2026-07-20T08:30:00Z",
        )
        notes = conn.execute(
            "SELECT notes FROM market_ingest_runs WHERE run_id=?",
            (receipt_id,),
        ).fetchone()[0]
        payload = json.loads(notes)
        payload["counts"]["validated"] = 0
        conn.execute(
            "UPDATE market_ingest_runs SET notes=? WHERE run_id=?",
            (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                receipt_id,
            ),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="planner authority"):
        scheduler.run_schedule(
            registry=registry,
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=db_path,
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
        )


def test_failed_receipt_uses_short_retry_not_success_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
        _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="failed",
            started_at="2026-07-20T07:00:00Z",
            finished_at="2026-07-20T07:30:00Z",
            request_window={"trade_date": "20260720"},
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
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
        _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.daily",
            status="failed",
            started_at="2026-07-20T08:45:00Z",
            finished_at="2026-07-20T08:55:00Z",
            request_window={"trade_date": "20260720"},
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


def test_weak_receipt_envelope_fails_planner_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
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

    with pytest.raises(RuntimeError, match="planner authority"):
        scheduler.run_schedule(
            registry=registry,
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=db_path,
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
        )


def test_missing_calendar_skips_postclose_without_guessing_market_holidays(
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
    assert skipped["cn.equity.daily"] == "calendar_unavailable"
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
    assert len(result.executed) == len(result.plans)
    assert [item.state for item in result.executed] == ["failed"] + ["success"] * (
        len(result.executed) - 1
    )
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
        plan.dataset_id for plan in result.plans
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


def test_collector_credentials_use_validated_url_and_private_token_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/nonexistent-protected-home")
    for name in scheduler._FORBIDDEN_COLLECTOR_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)
    observed: list[bool] = []
    monkeypatch.setattr(
        scheduler,
        "read_tushare_config",
        lambda: (
            observed.append(True)
            or {"api_url": "https://api.tushare.pro", "token": "redacted"}
        ),
    )

    scheduler._validated_collector_credentials()
    assert observed == [True]


@pytest.mark.parametrize(
    "name",
    [
        "QUICKSYNC_API_URL",
        "QUICKSYNC_TOKEN",
        "TUSHARE_TOKEN",
        "TUSHARE_API_TOKEN",
    ],
)
def test_collector_credentials_reject_legacy_secret_sources(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for credential_name in scheduler._FORBIDDEN_COLLECTOR_CREDENTIALS:
        monkeypatch.delenv(credential_name, raising=False)
    monkeypatch.setenv(name, "must-not-be-read")
    monkeypatch.setattr(
        scheduler,
        "read_tushare_config",
        lambda: pytest.fail("legacy source must fail before credential read"),
    )

    with pytest.raises(ValueError, match="credential source is not allowed"):
        scheduler._validated_collector_credentials()


def test_scheduler_has_only_tradingdatas_runtime_paths_and_in_process_execution() -> (
    None
):
    source = Path(scheduler.__file__).read_text(encoding="utf-8")

    assert scheduler.DEFAULT_LOCK_PATH == Path("/run/lock/tradingdatas-collect.lock")
    assert "TRADINGDATAS_SCHEDULE_PATH" in source
    assert "TRADINGDATAS_COLLECT_LOCK" in source
    assert not hasattr(scheduler, "_pin_runtime_registry_to_release")
    assert not hasattr(scheduler, "_subprocess_executor")


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
    assert "api_name" not in raw
    assert "route" not in raw
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    assert set(schedule.cadences) == {
        "session_minute",
        "postclose_daily",
        "daily_reference",
        "weekly",
        "monthly",
        "quarterly_reporting",
        "event",
        "on_demand",
    }
    assert set(schedule.rate_budgets) == {
        "standard",
        "intraday",
        "low_frequency",
        "event",
    }
    assert "request_variants:" not in raw
    assert all(
        not hasattr(policy, "request_variants") for policy in schedule.cadences.values()
    )
    assert schedule.cadences["postclose_daily"].calendar is not None
    assert schedule.cadences["postclose_daily"].backfill_chunk_span_days == 1
    assert schedule.cadences["daily_reference"].future_horizon_days == 365
    assert schedule.cadences["on_demand"].automatic is False


def test_schedule_config_rejects_duplicate_keys(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("version: 2\nversion: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        scheduler.load_schedule(invalid)


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
    assert output["summary"]["planned"] >= 1
    assert "202607" not in json.dumps(output)


@pytest.mark.parametrize(
    ("current_open", "expected"),
    [
        (True, ["20260720", "20260714"]),
        (False, ["20260714"]),
    ],
)
def test_daily_uses_calendar_and_repairs_earliest_gap_after_current_session(
    current_open: bool,
    expected: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    sessions = {
        date(2026, 7, 13) + timedelta(days=offset): (
            date(2026, 7, 13) + timedelta(days=offset)
        ).weekday()
        < 5
        for offset in range(8)
    }
    sessions[date(2026, 7, 20)] = current_open
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, sessions)
        for day in (
            date(2026, 7, 13),
            date(2026, 7, 15),
            date(2026, 7, 16),
            date(2026, 7, 17),
        ):
            _seed_daily(
                monkeypatch, conn, registry, day, finished_at="2026-07-20T08:45:00Z"
            )
    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )
    daily = [plan for plan in result.plans if plan.dataset_id == "cn.equity.daily"]
    assert [plan.request_window["trade_date"] for plan in daily] == expected
    assert [plan.priority for plan in daily] == (
        ["current", "backfill"] if current_open else ["backfill"]
    )


def test_trade_calendar_uses_bounded_chunks_and_future_horizon(tmp_path: Path) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    today = date(2026, 7, 20)
    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )
    plans = [
        plan for plan in result.plans if plan.dataset_id == "cn.market.trade_calendar"
    ]
    assert plans[0].priority == "current"
    assert max(
        _date(plan.request_window["end_date"]) for plan in plans
    ) >= today + timedelta(days=365)
    assert all(
        1
        <= (
            _date(plan.request_window["end_date"])
            - _date(plan.request_window["start_date"])
        ).days
        + 1
        <= 366
        for plan in plans
    )


def _date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def test_correction_overlap_and_api_budget_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    sessions = {
        date(2026, 7, 13) + timedelta(days=offset): (
            date(2026, 7, 13) + timedelta(days=offset)
        ).weekday()
        < 5
        for offset in range(8)
    }
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, sessions)
        for day, opened in sessions.items():
            if opened:
                _seed_daily(
                    monkeypatch, conn, registry, day, finished_at="2026-07-18T09:00:00Z"
                )
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    result = scheduler.run_schedule(
        registry=registry,
        schedule=schedule,
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )
    daily = [plan for plan in result.plans if plan.dataset_id == "cn.equity.daily"]
    assert [(plan.request_window["trade_date"], plan.priority) for plan in daily] == [
        ("20260720", "current"),
        ("20260717", "correction"),
    ]

    budget = schedule.rate_budgets["standard"]
    constrained = replace(
        schedule,
        rate_budgets={
            **schedule.rate_budgets,
            "standard": replace(budget, api_requests_per_run=1),
        },
    )
    limited = scheduler.run_schedule(
        registry=registry,
        schedule=constrained,
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )
    assert (
        len([plan for plan in limited.plans if plan.dataset_id == "cn.equity.daily"])
        == 1
    )
    assert any(
        item.dataset_id == "cn.equity.daily" and item.state == "rate_budget"
        for item in limited.skipped
    )


def test_synthetic_dataset_and_plan_mode_remain_generic_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _active_registry()
    template = base.resolve("cn.equity.daily")
    synthetic = replace(
        template,
        dataset_id="cn.synthetic.partitioned",
        aliases=(),
        provider_bindings=(
            replace(template.provider_bindings[0], api_name="synthetic_api"),
        ),
    )
    registry = DatasetRegistry(
        (synthetic, base.resolve("cn.market.trade_calendar")),
        query_defaults=base.query_defaults,
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
    before = db_path.stat()
    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )
    plan = next(
        item for item in result.plans if item.dataset_id == synthetic.dataset_id
    )
    assert plan.provider_api == "synthetic_api"
    assert plan.request_window["trade_date"] == "20260720"
    assert 0 <= plan.retry_jitter_seconds <= plan.retry.jitter_seconds
    after = db_path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    source = (ROOT / "tools" / "provider_native_cadence_planner.py").read_text(
        encoding="utf-8"
    )
    assert all(
        literal not in source
        for literal in (
            "cn.equity.daily",
            "cn.market.trade_calendar",
            "stock_basic",
            "trade_cal",
        )
    )


def test_binding_variants_do_not_leak_between_same_key_datasets(
    tmp_path: Path,
) -> None:
    base = _active_registry()
    template = base.resolve("cn.equity.security_master")
    binding = template.provider_bindings[0]
    synthetic = replace(
        template,
        dataset_id="cn.synthetic.same-key",
        aliases=(),
        provider_bindings=(
            replace(
                binding,
                api_name="synthetic_same_key",
                request_template=MappingProxyType({"list_status": "X"}),
                request_variants=(MappingProxyType({"list_status": "X"}),),
            ),
        ),
    )
    registry = DatasetRegistry(
        (synthetic, base.resolve("cn.market.trade_calendar")),
        query_defaults=base.query_defaults,
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    synthetic_plans = [
        plan for plan in result.plans if plan.dataset_id == synthetic.dataset_id
    ]
    assert [dict(plan.request_variant) for plan in synthetic_plans] == [
        {"list_status": "X"}
    ]
