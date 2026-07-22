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

from dataset_registry import (
    DatasetRegistry,
    RequestWindowPolicy,
    load_dataset_registry,
)
import storage.ingest_receipts as receipt_module
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    ProviderRequestIdentity,
    insert_ingest_receipt,
    make_provider_call_attempt_id,
    parse_schedule_plan_attempt_id,
)
from storage.schema import SCHEMA_SQL
from storage.sqlite_authority_lock import sqlite_authority_lock_path
import tools.run_provider_native_schedule as scheduler
import tools.provider_native_cadence_planner as cadence_planner


ROOT = Path(__file__).resolve().parents[1]
TARGET_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"
SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
ACTIVATION_WAVES = ROOT / "config" / "provider_native_activation_waves.v1.yaml"
CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64


def _active_registry() -> DatasetRegistry:
    return load_dataset_registry(TARGET_REGISTRY)


def _window_registry(
    format_name: str,
    cadence_class: str,
    *,
    ranged: bool = False,
) -> DatasetRegistry:
    base = _active_registry()
    template = base.resolve("cn.equity.daily")
    keys = ("start", "end") if ranged else ("period",)
    binding = replace(
        template.provider_bindings[0],
        api_name=f"synthetic_{format_name}",
        read_discriminator_value=f"synthetic_{format_name}",
        request_template=MappingProxyType(
            {f"provider_{key}": f"${{window.{key}}}" for key in keys}
        ),
        request_window_policy=RequestWindowPolicy(
            required_keys=keys,
            formats=MappingProxyType({key: format_name for key in keys}),
            range_start_key=keys[0],
            range_end_key=keys[-1],
            max_span_days=2 if ranged else 1,
        ),
        response_completeness=None,
    )
    dataset = replace(
        template,
        dataset_id=f"cn.synthetic.window_{format_name}",
        aliases=(),
        cadence_class=cadence_class,
        provider_bindings=(binding,),
    )
    return DatasetRegistry((dataset,), query_defaults=base.query_defaults)


def _single_partition_schedule(
    cadence_class: str,
    partition_frequency: str,
) -> cadence_planner.Schedule:
    schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    policy = replace(
        schedule.cadences[cadence_class],
        calendar=None,
        partition_frequency=partition_frequency,
        backfill_start_policy="fixed_date",
        backfill_start_date=date(2026, 7, 20),
        backfill_lookback_days=0,
        backfill_chunk_span_days=1,
        future_horizon_days=0,
        correction_overlap_days=0,
        correction_overlap_bars=0,
        max_backfill_chunks_per_run=1,
    )
    return replace(
        schedule,
        cadences=MappingProxyType(
            {**schedule.cadences, cadence_class: policy}
        ),
    )


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
    attempt_id: str | None = None,
    request_variant: dict[str, str] | None = None,
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
    elif status == "empty":
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
        errors = ()
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
            attempt_id=attempt_id
            or f"attempt-{dataset_id}-{status}-{hashlib.sha256(json.dumps(window, sort_keys=True).encode()).hexdigest()[:12]}-{finished_at}",
            dataset_id=dataset_id,
            provider=binding.provider,
            provider_api=binding.api_name,
            request_window=window,
            config_hash=CONFIG_HASH,
            adapter_version=binding.adapter_version,
            started_at=started_at,
            data_through="20260720",
            request_identity=ProviderRequestIdentity(
                request_variant=request_variant or {},
                fanout_parameter=None,
                fanout_values=(),
                page_offset=None,
                page_index=0,
            ),
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
    assert [
        dict(variant)
        for variant in current["cn.equity.security_master"].request_variants
    ] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert "cn.market.trade_calendar" not in current
    assert any(
        item.dataset_id == "cn.market.trade_calendar" and item.priority == "backfill"
        for item in result.plans
    )
    assert all(plan.provider for plan in result.plans)


@pytest.mark.parametrize(
    ("format_name", "cadence_class", "partition_frequency", "expected"),
    [
        ("yyyymmdd", "daily_reference", "day", "20260720"),
        ("yyyymm", "monthly", "month", "202607"),
        ("yyyy_qn", "quarterly_reporting", "quarter", "2026Q3"),
        ("yyyyww", "weekly", "week", "202630"),
        (
            "local_datetime_seconds",
            "postclose_daily",
            "day",
            "2026-07-20 00:00:00",
        ),
    ],
)
def test_planner_renders_each_runtime_window_from_partition_frequency(
    format_name: str,
    cadence_class: str,
    partition_frequency: str,
    expected: str,
) -> None:
    registry = _window_registry(format_name, cadence_class)
    plans, skips = cadence_planner.plan_runs(
        registry=registry,
        schedule=_single_partition_schedule(cadence_class, partition_frequency),
        state=cadence_planner.PlannerState(MappingProxyType({})),
        now=datetime(2026, 7, 20, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert skips == ()
    assert len(plans) == 1
    assert dict(plans[0].request_window) == {"period": expected}


@pytest.mark.parametrize(
    ("format_name", "window", "first", "last", "count"),
    [
        ("yyyymmdd", {"period": "20260228"}, date(2026, 2, 28), date(2026, 2, 28), 1),
        ("yyyymm", {"period": "202602"}, date(2026, 2, 1), date(2026, 2, 28), 28),
        ("yyyy_qn", {"period": "2026Q1"}, date(2026, 1, 1), date(2026, 3, 31), 90),
        ("yyyyww", {"period": "202653"}, date(2026, 12, 28), date(2027, 1, 3), 7),
        (
            "local_datetime_seconds",
            {"start": "2026-07-20 23:59:59", "end": "2026-07-21 00:00:00"},
            date(2026, 7, 20),
            date(2026, 7, 21),
            2,
        ),
    ],
)
def test_planner_parses_windows_back_to_covered_calendar_dates(
    format_name: str,
    window: dict[str, str],
    first: date,
    last: date,
    count: int,
) -> None:
    registry = _window_registry(
        format_name,
        "daily_reference",
        ranged=len(window) == 2,
    )
    binding = registry.datasets[0].provider_bindings[0]

    dates = cadence_planner._window_dates(binding, window)

    assert dates[0] == first
    assert dates[-1] == last
    assert len(dates) == count


def test_active_on_demand_window_is_never_automatically_planned() -> None:
    registry = _window_registry("yyyymm", "on_demand")

    plans, skips = cadence_planner.plan_runs(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        state=cadence_planner.PlannerState(MappingProxyType({})),
        now=datetime(2026, 7, 20, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plans == ()
    assert [(item.dataset_id, item.state) for item in skips] == [
        (registry.datasets[0].dataset_id, "on_demand")
    ]


def test_planner_rejects_naive_run_clock_before_window_generation() -> None:
    registry = _window_registry("yyyymmdd", "daily_reference")

    with pytest.raises(ValueError, match="now must be timezone-aware"):
        cadence_planner.plan_runs(
            registry=registry,
            schedule=_single_partition_schedule("daily_reference", "day"),
            state=cadence_planner.PlannerState(MappingProxyType({})),
            now=datetime(2026, 7, 20, 21, 0),
        )


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


def test_execute_derives_canonical_plan_roots_from_one_scheduler_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    fixed_run = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(scheduler.uuid, "uuid4", lambda: fixed_run)
    captured: list[str] = []

    def execute(
        plan: scheduler.ScheduledRun,
        **kwargs: object,
    ) -> scheduler.DatasetResult:
        attempt_id = kwargs["attempt_id"]
        assert isinstance(attempt_id, str)
        captured.append(attempt_id)
        return scheduler.DatasetResult(plan.dataset_id, plan.provider, "success", 0)

    monkeypatch.setattr(scheduler, "_in_process_executor", execute)
    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
    )

    assert result.exit_code == 0
    identities = [parse_schedule_plan_attempt_id(value) for value in captured]
    assert all(identity is not None for identity in identities)
    assert {identity.run_attempt_id for identity in identities if identity} == {
        fixed_run
    }
    assert [identity.plan_index for identity in identities if identity] == list(
        range(len(captured))
    )


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
        "cn.dataset.adj_factor",
        "cn.dataset.hsgt_top10",
        "cn.dataset.index_classify",
        "cn.dataset.limit_list_ths",
        "cn.dataset.moneyflow_ind_ths",
        "cn.dataset.stk_auction",
        "cn.dataset.stk_limit",
        "cn.dataset.sw_daily",
        "cn.dataset.suspend_d",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }


def test_single_recent_variant_receipt_cannot_suppress_complete_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        receipt = _canonical_receipt(
            monkeypatch,
            conn,
            dataset_id="cn.equity.security_master",
            status="success",
            started_at="2026-07-20T08:00:00Z",
            finished_at="2026-07-20T08:30:00Z",
            attempt_id=make_provider_call_attempt_id(
                "incomplete-security-master-cohort",
                call_index=0,
                retry_index=0,
            ),
            request_variant={"list_status": "L"},
        )
        _fact(
            conn,
            registry,
            "cn.equity.security_master",
            receipt,
            "20260720",
            {"list_status": "L", "ts_code": "000001.SZ"},
        )
        conn.commit()

    state = scheduler.load_planner_state(
        db_path,
        registry,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    dataset = registry.resolve("cn.equity.security_master")
    assert state.get(dataset, dataset.provider_bindings[0]).facts == ()
    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
    )

    plans = [
        plan
        for plan in result.plans
        if plan.dataset_id == "cn.equity.security_master"
    ]
    assert len(plans) == 1
    assert [dict(variant) for variant in plans[0].request_variants] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]


def test_complete_recent_variant_cohort_is_not_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    root = "11111111-1111-4111-8111-111111111111"
    with sqlite3.connect(db_path) as conn:
        receipt_ids: dict[str, str] = {}
        for call_index, (status, terminal_status) in enumerate(
            (("L", "success"), ("D", "success"), ("P", "empty"))
        ):
            receipt_ids[status] = _canonical_receipt(
                monkeypatch,
                conn,
                dataset_id="cn.equity.security_master",
                status=terminal_status,
                started_at="2026-07-20T08:00:00Z",
                finished_at="2026-07-20T08:30:00Z",
                attempt_id=make_provider_call_attempt_id(
                    root,
                    call_index=call_index,
                    retry_index=0,
                ),
                request_variant={"list_status": status},
            )
        _fact(
            conn,
            registry,
            "cn.equity.security_master",
            receipt_ids["L"],
            "20260720",
            {"list_status": "L", "ts_code": "000001.SZ"},
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
    assert skipped["cn.equity.security_master"] == "not_due"


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
    assert skipped["cn.dataset.sw_daily"] == "calendar_unavailable"
    assert {item.dataset_id for item in result.executed} == {
        "cn.dataset.adj_factor",
        "cn.dataset.index_classify",
        "cn.dataset.stk_auction",
        "cn.dataset.stk_limit",
        "cn.dataset.suspend_d",
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

    priority_rank = {"current": 0, "backfill": 1, "correction": 2}
    planner_order = [
        (priority_rank[plan.priority], plan.dataset_id, index)
        for index, plan in enumerate(result.plans)
    ]
    assert planner_order == sorted(planner_order)
    assert calls == [plan.dataset_id for plan in result.plans]
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
    assert "TRADINGDATAS_SCHEDULE_PATH" not in source
    assert "TRADINGDATAS_COLLECT_LOCK" in source
    assert not hasattr(scheduler, "_pin_runtime_registry_to_release")
    assert not hasattr(scheduler, "_subprocess_executor")


def test_execute_rejects_schedule_override_before_credentials_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    override = tmp_path / "provider_native_schedule.yaml"
    override.write_text(SCHEDULE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(
        scheduler,
        "_validated_collector_credentials",
        lambda: pytest.fail("schedule override must fail before credential access"),
    )
    monkeypatch.setattr(
        scheduler,
        "load_runtime_dataset_registry",
        lambda: pytest.fail("schedule override must fail before registry access"),
    )

    code = scheduler.main(
        [
            "--execute",
            "--schedule-config",
            str(override),
            "--lock-path",
            str(tmp_path / "schedule.lock"),
        ]
    )

    assert code == 2
    assert json.loads(capsys.readouterr().out) == {
        "mode": "execute",
        "state": "validation",
    }


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
    assert schedule.cadences["daily_reference"].future_horizon_days == 0
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


def test_trade_calendar_uses_bounded_chunks_through_current_day(tmp_path: Path) -> None:
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
    assert plans[0].request_window == {
        "start_date": "20260720",
        "end_date": "20260720",
    }
    assert max(_date(plan.request_window["end_date"]) for plan in plans) == today
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
    assert [
        [dict(variant) for variant in plan.request_variants]
        for plan in synthetic_plans
    ] == [[{"list_status": "X"}]]


def _activation_wave_manifest(
    tmp_path: Path,
    *,
    dataset_ids: list[str],
    wave_id: str = "pilot",
    registry_hash: str | None = None,
    schedule_hash: str | None = None,
) -> Path:
    manifest = tmp_path / "activation-waves.yaml"
    manifest.write_text(
        "\n".join(
            [
                "version: 1",
                "input_hashes:",
                '  runtime_registry_sha256: "'
                + (registry_hash or hashlib.sha256(TARGET_REGISTRY.read_bytes()).hexdigest())
                + '"',
                '  schedule_sha256: "'
                + (schedule_hash or hashlib.sha256(SCHEDULE_CONFIG.read_bytes()).hexdigest())
                + '"',
                "waves:",
                f"  {wave_id}:",
                "    dataset_ids:",
                *[f"    - {dataset_id}" for dataset_id in dataset_ids],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def test_activation_wave_rejects_an_unknown_wave_before_planner_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    manifest = _activation_wave_manifest(
        tmp_path, dataset_ids=["cn.equity.daily"]
    )
    monkeypatch.setattr(
        scheduler,
        "load_planner_state",
        lambda *args, **kwargs: pytest.fail("unknown wave must fail before database access"),
    )

    with pytest.raises(ValueError, match="unknown activation wave"):
        scheduler.run_schedule(
            registry=registry,
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=True,
            activation_wave="missing",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_wave_rejects_duplicate_dataset_ids(tmp_path: Path) -> None:
    manifest = _activation_wave_manifest(
        tmp_path, dataset_ids=["cn.equity.daily", "cn.equity.daily"]
    )

    with pytest.raises(ValueError, match="duplicate dataset_id"):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_wave_rejects_alias_instead_of_canonical_dataset_id(
    tmp_path: Path,
) -> None:
    manifest = _activation_wave_manifest(tmp_path, dataset_ids=["tushare.daily"])

    with pytest.raises(ValueError, match="canonical dataset_id"):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_wave_rejects_non_active_or_non_entitled_dataset(
    tmp_path: Path,
) -> None:
    registry_bytes = TARGET_REGISTRY.read_bytes()
    active_fragment = (
        b"    api_name: daily\n"
        b"    adapter_version: tushare-provider-native.v1\n"
        b"    read_discriminator_value: tushare_daily\n"
        b"    entitlement_state: active\n"
        b"    activation_state: active\n"
    )
    inactive_fragment = (
        active_fragment.replace(
            b"entitlement_state: active", b"entitlement_state: locked"
        ).replace(b"activation_state: active", b"activation_state: paused")
    )
    assert registry_bytes.count(active_fragment) == 1
    inactive_registry_bytes = registry_bytes.replace(
        active_fragment, inactive_fragment, 1
    )
    inactive_registry = tmp_path / "inactive-registry.yaml"
    inactive_registry.write_bytes(inactive_registry_bytes)
    manifest = _activation_wave_manifest(
        tmp_path,
        dataset_ids=["cn.equity.daily"],
        registry_hash=hashlib.sha256(inactive_registry_bytes).hexdigest(),
    )

    with pytest.raises(ValueError, match="active and entitled"):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=inactive_registry,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_wave_rejects_authority_hash_drift_before_planner_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _activation_wave_manifest(
        tmp_path,
        dataset_ids=["cn.equity.daily"],
        registry_hash="0" * 64,
    )
    monkeypatch.setattr(
        scheduler,
        "load_planner_state",
        lambda *args, **kwargs: pytest.fail("hash drift must fail before database access"),
    )

    with pytest.raises(ValueError, match="registry SHA-256 does not match"):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=True,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_wave_selects_mixed_rate_classes_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _active_registry()
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
    manifest = _activation_wave_manifest(
        tmp_path,
        dataset_ids=["cn.dataset.index_classify", "cn.equity.daily"],
    )
    executed: list[str] = []

    result = scheduler.run_schedule(
        registry=registry,
        schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=True,
        executor=lambda plan: (
            executed.append(plan.dataset_id)
            or scheduler.DatasetResult(plan.dataset_id, plan.provider, "success", 0)
        ),
        activation_wave="pilot",
        activation_wave_manifest=manifest,
        registry_source_path=TARGET_REGISTRY,
        schedule_source_path=SCHEDULE_CONFIG,
    )

    assert {plan.rate_budget_class for plan in result.plans} == {
        "standard",
        "low_frequency",
    }
    assert executed == [item.dataset_id for item in result.plans]
    assert {
        "cn.dataset.sw_daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    } <= {item.dataset_id for item in result.skipped if item.state == "not_selected"}


def test_activation_wave_option_is_exposed_by_the_cli() -> None:
    args = scheduler.parse_args(["--activation-wave", "pilot_existing"])

    assert args.activation_wave == "pilot_existing"


def test_formal_direct_wave_1_is_hash_bound_and_disjoint_from_existing_pilot() -> None:
    registry_payload = TARGET_REGISTRY.read_bytes()
    schedule_payload = SCHEDULE_CONFIG.read_bytes()
    registry = _active_registry()

    direct = scheduler.load_activation_wave(
        ACTIVATION_WAVES,
        "direct_wave_1",
        registry=registry,
        registry_payload=registry_payload,
        schedule_payload=schedule_payload,
    )
    pilot = scheduler.load_activation_wave(
        ACTIVATION_WAVES,
        "pilot_existing",
        registry=registry,
        registry_payload=registry_payload,
        schedule_payload=schedule_payload,
    )

    assert direct.dataset_ids == frozenset(
        {
            "cn.dataset.adj_factor",
            "cn.dataset.stk_auction",
            "cn.dataset.stk_limit",
            "cn.dataset.suspend_d",
        }
    )
    assert pilot.dataset_ids == frozenset(
        {
            "cn.dataset.index_classify",
            "cn.dataset.sw_daily",
            "cn.equity.daily",
            "cn.equity.security_master",
            "cn.market.trade_calendar",
        }
    )
    assert direct.dataset_ids.isdisjoint(pilot.dataset_ids)


def test_formal_direct_wave_1_dry_run_plans_every_selected_dataset(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    expected = {
        "cn.dataset.adj_factor",
        "cn.dataset.stk_auction",
        "cn.dataset.stk_limit",
        "cn.dataset.suspend_d",
    }

    result = scheduler.run_schedule(
        registry=None,
        schedule=None,
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
        activation_wave="direct_wave_1",
        activation_wave_manifest=ACTIVATION_WAVES,
        registry_source_path=TARGET_REGISTRY,
        schedule_source_path=SCHEDULE_CONFIG,
    )

    assert {plan.dataset_id for plan in result.plans} == expected
    assert not {
        item.dataset_id
        for item in result.skipped
        if item.dataset_id in expected and item.state == "on_demand"
    }


def test_formal_direct_wave_2_is_hash_bound_and_disjoint_from_existing_waves() -> None:
    registry_payload = TARGET_REGISTRY.read_bytes()
    schedule_payload = SCHEDULE_CONFIG.read_bytes()
    registry = _active_registry()

    direct = scheduler.load_activation_wave(
        ACTIVATION_WAVES,
        "direct_wave_2",
        registry=registry,
        registry_payload=registry_payload,
        schedule_payload=schedule_payload,
    )
    direct_wave_1 = scheduler.load_activation_wave(
        ACTIVATION_WAVES,
        "direct_wave_1",
        registry=registry,
        registry_payload=registry_payload,
        schedule_payload=schedule_payload,
    )
    pilot = scheduler.load_activation_wave(
        ACTIVATION_WAVES,
        "pilot_existing",
        registry=registry,
        registry_payload=registry_payload,
        schedule_payload=schedule_payload,
    )

    assert direct.dataset_ids == frozenset(
        {
            "cn.dataset.hsgt_top10",
            "cn.dataset.limit_list_ths",
            "cn.dataset.moneyflow_ind_ths",
        }
    )
    assert direct.dataset_ids.isdisjoint(direct_wave_1.dataset_ids)
    assert direct.dataset_ids.isdisjoint(pilot.dataset_ids)


def test_formal_direct_wave_2_dry_run_plans_every_selected_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    registry = _active_registry()
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 20): True})
        conn.commit()
    expected = {
        "cn.dataset.hsgt_top10",
        "cn.dataset.limit_list_ths",
        "cn.dataset.moneyflow_ind_ths",
    }

    result = scheduler.run_schedule(
        registry=None,
        schedule=None,
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
        activation_wave="direct_wave_2",
        activation_wave_manifest=ACTIVATION_WAVES,
        registry_source_path=TARGET_REGISTRY,
        schedule_source_path=SCHEDULE_CONFIG,
    )

    assert {plan.dataset_id for plan in result.plans} == expected
    assert not {
        item.dataset_id
        for item in result.skipped
        if item.dataset_id in expected
    }


def test_activation_wave_uses_hashed_input_bytes_not_detached_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_registry = _active_registry()
    daily = source_registry.resolve("cn.equity.daily")
    detached_daily = replace(
        daily,
        provider_bindings=(replace(daily.provider_bindings[0], api_name="detached_api"),),
    )
    detached_registry = DatasetRegistry(
        (
            detached_daily,
            *[
                item
                for item in source_registry.datasets
                if item.dataset_id != daily.dataset_id
            ],
        ),
        query_defaults=source_registry.query_defaults,
    )
    source_schedule = scheduler.load_schedule(SCHEDULE_CONFIG)
    detached_schedule = replace(
        source_schedule,
        cadences={
            **source_schedule.cadences,
            "postclose_daily": replace(
                source_schedule.cadences["postclose_daily"], automatic=False
            ),
        },
    )
    bound_registry_path = tmp_path / "bound-registry.yaml"
    bound_registry_bytes = TARGET_REGISTRY.read_bytes().replace(
        b"    api_name: daily\n",
        b"    api_name: byte_bound_api\n",
        1,
    )
    assert bound_registry_bytes != TARGET_REGISTRY.read_bytes()
    bound_registry_path.write_bytes(bound_registry_bytes)
    manifest = _activation_wave_manifest(
        tmp_path,
        dataset_ids=["cn.equity.daily"],
        registry_hash=hashlib.sha256(bound_registry_bytes).hexdigest(),
    )
    db_path = tmp_path / "facts.sqlite"
    _database(db_path)
    with sqlite3.connect(db_path) as conn:
        _seed_calendar(
            monkeypatch,
            conn,
            source_registry,
            {date(2026, 7, 20): True},
        )

    result = scheduler.run_schedule(
        registry=detached_registry,
        schedule=detached_schedule,
        db_path=db_path,
        now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        execute=False,
        activation_wave="pilot",
        activation_wave_manifest=manifest,
        registry_source_path=bound_registry_path,
        schedule_source_path=SCHEDULE_CONFIG,
    )

    daily_plans = [
        plan for plan in result.plans if plan.dataset_id == "cn.equity.daily"
    ]
    assert daily_plans
    assert {plan.provider_api for plan in daily_plans} == {"byte_bound_api"}


@pytest.mark.parametrize(
    ("hidden_wave", "message"),
    [
        (
            "  zzz_hidden_alias:\n"
            "    dataset_ids:\n"
            "    - tushare.daily\n",
            "canonical dataset_id",
        ),
        (
            "  zzz_hidden_token:\n"
            "    dataset_ids:\n"
            "    - cn.equity.security_master\n"
            "    token: must-not-be-accepted\n",
            "activation wave keys are invalid",
        ),
    ],
)
def test_activation_manifest_validates_every_wave_before_selection(
    hidden_wave: str,
    message: str,
    tmp_path: Path,
) -> None:
    manifest = _activation_wave_manifest(
        tmp_path, dataset_ids=["cn.equity.daily"]
    )
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + hidden_wave,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_activation_manifest_rejects_boolean_version(tmp_path: Path) -> None:
    manifest = _activation_wave_manifest(
        tmp_path, dataset_ids=["cn.equity.daily"]
    )
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "version: 1", "version: true", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest contract is invalid"):
        scheduler.run_schedule(
            registry=_active_registry(),
            schedule=scheduler.load_schedule(SCHEDULE_CONFIG),
            db_path=tmp_path / "must-not-open.sqlite",
            now=datetime(2026, 7, 20, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            execute=False,
            activation_wave="pilot",
            activation_wave_manifest=manifest,
            registry_source_path=TARGET_REGISTRY,
            schedule_source_path=SCHEDULE_CONFIG,
        )


def test_main_wave_defers_registry_and_schedule_parsing_to_bound_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        scheduler,
        "load_runtime_dataset_registry",
        lambda: pytest.fail("wave main must not preparse a detached registry"),
    )
    monkeypatch.setattr(
        scheduler,
        "load_schedule",
        lambda *args, **kwargs: pytest.fail(
            "wave main must not preparse a detached schedule"
        ),
    )

    def run(**kwargs: object) -> scheduler.ScheduleResult:
        assert kwargs["registry"] is None
        assert kwargs["schedule"] is None
        return scheduler.ScheduleResult(0, "plan", (), ())

    monkeypatch.setattr(scheduler, "run_schedule", run)

    code = scheduler.main(
        [
            "--activation-wave",
            "pilot_existing",
            "--lock-path",
            str(tmp_path / "schedule.lock"),
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "plan"
