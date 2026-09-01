"""Synthetic contracts: observation progress must never imply data completeness."""

from dataclasses import replace
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from collectors.tushare import provider_native_ingest as ingest
from dataset_registry import DatasetRegistry, ResumableFanoutPolicy
from tests import test_provider_native_schedule as helpers

import sqlite3
from uuid import uuid4

from collectors.tushare.tushare_common import ProviderCallOutcome
from dataset_registry import load_dataset_registry, load_runtime_dataset_registry
from storage import ingest_receipts
from tests.test_provider_native_registry import generic_dataset, _field, write_registry


def test_session_rotation_revisits_empty_and_success_without_prefix_starvation():
    registry = helpers._resumable_window_registry(values=("A", "B", "C"))
    dataset = registry.datasets[0]
    binding = replace(
        dataset.provider_bindings[0],
        resumable_fanout=ResumableFanoutPolicy(
            progress_mode="session_day_rotation", max_batches_per_run=1
        ),
    )
    dataset = replace(dataset, provider_bindings=(binding,))
    registry = DatasetRegistry((dataset,))
    window = {"start": "2026-07-20 00:00:00", "end": "2026-07-20 23:59:59"}
    histories = helpers._v2_histories(registry, window=window)[:2]
    batches = ingest._stable_fanout_batches(
        ("A", "B", "C"), parameter="ts_code", batch_size=1, resumable=True
    )
    selected = ingest._select_resumable_fanout_batches(
        batches,
        dataset=dataset,
        binding=binding,
        request_window=window,
        histories=histories,
    )
    assert selected[0].values == ("B",)
    complete = helpers._v2_histories(registry, window=window)
    selected = ingest._select_resumable_fanout_batches(
        batches,
        dataset=dataset,
        binding=binding,
        request_window=window,
        histories=complete,
    )
    assert selected[0].values == ("A",)  # refresh, not permanently complete


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz or timezone.utc)

    monkeypatch.setattr(ingest, "datetime", Clock)
    monkeypatch.setattr(ingest_receipts, "_utc_now", lambda: state["now"].isoformat())
    return state


def _registry(
    tmp_path, mode="session_day_rotation", *, values=("A", "B", "C"), batch_size=1
):
    session = mode == "session_day_rotation"
    payload = generic_dataset(
        schema_version="3.0.0" if session else "1.0.0",
        fields=[
            _field("ts_code"),
            _field("event_time", nullable=not session),
            _field("close", "float", nullable=True),
        ],
        primary_key=["ts_code", "event_time"] if session else [],
        default_projection=["ts_code", "event_time", "close"],
        as_of_field=None,
        as_of_format=None,
        partition_field=None,
        range_field=None,
        cadence_class="session_minute" if session else "event",
        point_in_time="append_only",
    )
    payload["read_model_adapter"]["row_key_strategy"] = "payload_hash"
    b = payload["provider_bindings"][0]
    b.update(
        request_shape="dimension_fanout",
        request_template={"freq": "1MIN"} if session else {"ann_date": "${window.day}"},
        requested_fields=[],
        fanout={
            "strategy": "literal_values",
            "parameter": "ts_code",
            "values": list(values),
            "batch_size": batch_size,
        },
        resumable_fanout={
            "cursor_contract_version": 2,
            "max_batches_per_run": 1,
            "progress_mode": mode,
        },
    )
    if session:
        b["request_window_policy"] = {
            "required_keys": ["start", "end"],
            "formats": {
                "start": "local_datetime_seconds",
                "end": "local_datetime_seconds",
            },
            "range_start_key": "start",
            "range_end_key": "end",
            "max_span_days": 1,
        }
        b["response_completeness"] = {
            "strategy": "windowed_unique_primary_key",
            "date_field": "event_time",
            "fanout_field": "ts_code",
            "request_start_key": "start",
            "request_end_key": "end",
            "fixed_field_matches": {},
            "reject_at_row_limit": False,
        }
    else:
        b["request_window_policy"] = {
            "required_keys": ["day"],
            "formats": {"day": "yyyymmdd"},
            "range_start_key": "day",
            "range_end_key": "day",
            "max_span_days": 1,
        }
        b["response_completeness"] = None
        b["resumable_fanout"].update(
            continuation_max_age_days=31, partition_date_field="event_time"
        )
    target = load_dataset_registry(write_registry(tmp_path, payload)).datasets[0]
    calendar = load_runtime_dataset_registry().resolve("cn.market.trade_calendar")
    return DatasetRegistry((target, calendar))


def _db(tmp_path, registry, monkeypatch, clock):
    path = tmp_path / "facts.sqlite"
    helpers._database(path)
    with sqlite3.connect(path) as conn:
        helpers._seed_calendar(
            monkeypatch,
            conn,
            registry,
            {
                date(2026, 7, 20): True,
                date(2026, 7, 21): True,
                date(2026, 7, 25): False,
            },
        )
    monkeypatch.setattr(ingest_receipts, "_utc_now", lambda: clock["now"].isoformat())
    return path


def _window(day="2026-07-20"):
    return {"start": day + " 00:00:00", "end": day + " 23:59:59"}


class Collector:
    def __init__(self, make_rows=None, *, state="success"):
        self.make_rows = make_rows or (
            lambda params: [
                {
                    "ts_code": params["ts_code"],
                    "event_time": "2026-07-20 09:55:00",
                    "close": 1.0,
                }
            ]
        )
        self.state = state
        self.calls = []

    def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
        self.calls.append(dict(params))
        return ProviderCallOutcome(
            state=self.state,
            rows=tuple(self.make_rows(params)) if self.state == "success" else (),
            provider_code=0 if self.state != "failed" else -1,
            error_code="provider_error" if self.state == "failed" else None,
            error_message=None,
        )


def _collect(path, registry, collector, clock, window=None, *, started=None):
    return ingest.collect_provider_native_dataset(
        path,
        registry=registry,
        collector=collector,
        dataset_id=registry.datasets[0].dataset_id,
        request_window=window or _window(),
        attempt_id=str(uuid4()),
        started_at=(started or clock["now"] - timedelta(seconds=1)).isoformat(),
    )


def _plans(path, registry, now):
    state = helpers.scheduler.load_planner_state(path, registry, now=now)
    return helpers.cadence_planner.plan_runs(
        registry=registry,
        schedule=helpers.scheduler.load_schedule(helpers.SCHEDULE_CONFIG),
        state=state,
        now=now,
        selected_dataset_ids=frozenset({registry.datasets[0].dataset_id}),
        current_only=True,
    )[0]


def _rows(path, dataset):
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT payload_json,receipt_id,quality_state FROM provider_dataset_rows WHERE dataset_id=? ORDER BY rowid",
            (dataset.dataset_id,),
        ).fetchall()


def test_session_sqlite_progress_refresh_revision_and_next_day(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path, values=("A", "B"))
    path = _db(tmp_path, registry, monkeypatch, clock)
    collector = Collector()
    for expected in ("A", "B", "A"):
        plans = _plans(path, registry, clock["now"])
        assert len(plans) == 1 and dict(plans[0].request_window) == _window()
        assert _collect(path, registry, collector, clock).status == "success"
        assert collector.calls[-1] == {"freq": "1MIN", "ts_code": expected}
        clock["now"] += timedelta(minutes=5)
    before = _rows(path, registry.datasets[0])
    assert len(before) == 2  # repeated identical observation retains old row lineage
    collector.make_rows = lambda p: [
        {"ts_code": p["ts_code"], "event_time": "2026-07-20 09:55:00", "close": 2.0}
    ]
    assert _collect(path, registry, collector, clock).status == "success"
    assert len(_rows(path, registry.datasets[0])) == 3  # revision is append-only
    clock["now"] = clock["now"].replace(day=21)
    collector.make_rows = lambda p: [
        {"ts_code": p["ts_code"], "event_time": "2026-07-21 09:55:00", "close": 3.0}
    ]
    plans = _plans(path, registry, clock["now"])
    assert dict(plans[0].request_window) == _window("2026-07-21")
    assert (
        _collect(path, registry, collector, clock, _window("2026-07-21")).status
        == "success"
    )
    assert collector.calls[-1]["ts_code"] == "A"
    history = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert len(history) == 5
    assert history[-1].data_through == "2026-07-21 09:55:00"


@pytest.mark.parametrize(
    "timestamps",
    [
        ("2026-07-19 15:00:00",),
        ("2026-07-19 15:00:00", "2026-07-20 09:55:00"),
        ("2026-07-20 10:01:00",),
        (None,),
        ("2026-07-20",),
    ],
)
def test_invalid_current_day_response_never_writes_valid_rows(
    tmp_path, monkeypatch, clock, timestamps
):
    registry = _registry(tmp_path)
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(
        lambda p: [
            {"ts_code": p["ts_code"], "event_time": t, "close": 1.0} for t in timestamps
        ]
    )
    assert _collect(path, registry, c, clock).status == "failed"
    assert _rows(path, registry.datasets[0]) == []
    histories = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert histories[0].status == "failed" and histories[0].data_through is None
    clock["now"] += timedelta(minutes=5)
    c.make_rows = lambda p: [
        {"ts_code": p["ts_code"], "event_time": "2026-07-20 09:55:00", "close": 1.0}
    ]
    assert _collect(path, registry, c, clock).status == "success"
    assert c.calls[-1]["ts_code"] == "B"  # bad A cannot pin pending B


@pytest.mark.parametrize("state", ["empty", "success"])
def test_midnight_late_response_fails_even_if_empty(
    tmp_path, monkeypatch, clock, state
):
    registry = _registry(tmp_path)
    path = _db(tmp_path, registry, monkeypatch, clock)
    clock["now"] = datetime(2026, 7, 21, 0, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        _collect(
            path,
            registry,
            Collector(state=state),
            clock,
            started=clock["now"] - timedelta(seconds=2),
        ).status
        == "failed"
    )
    assert _rows(path, registry.datasets[0]) == []


@pytest.mark.parametrize("state", ["empty", "failed"])
def test_empty_and_failure_rotate_fairly_and_are_not_day_completion(
    tmp_path, monkeypatch, clock, state
):
    registry = _registry(tmp_path, values=("A", "B"))
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(state=state)
    for code in ("A", "B", "A"):
        assert _collect(path, registry, c, clock).status == state
        assert c.calls[-1]["ts_code"] == code
        clock["now"] += timedelta(minutes=5)
        assert len(_plans(path, registry, clock["now"])) == 1
    assert all(
        h.data_through is None
        for h in ingest._resumable_histories(path, registry, registry.datasets[0])
    )


def test_session_closed_calendar_and_lunch_have_no_plan(tmp_path, monkeypatch, clock):
    registry = _registry(tmp_path)
    path = _db(tmp_path, registry, monkeypatch, clock)
    for day, hour, minute in [(20, 12, 0), (20, 15, 10), (25, 10, 0)]:
        assert (
            _plans(
                path, registry, clock["now"].replace(day=day, hour=hour, minute=minute)
            )
            == ()
        )


def test_partition_sqlite_rollover_alternates_current_and_old_exact_date(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path, "partition_continuation")
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": p["ts_code"], "event_time": p["ann_date"], "close": 1.0}]
    )
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "success"
    clock["now"] += timedelta(days=1)
    for day, code in [
        ("20260721", "A"),
        ("20260720", "B"),
        ("20260721", "B"),
        ("20260720", "C"),
        ("20260721", "C"),
        ("20260721", "A"),
    ]:
        plans = _plans(path, registry, clock["now"])
        assert len(plans) == 1 and dict(plans[0].request_window) == {"day": day}
        assert (
            _collect(path, registry, c, clock, plans[0].request_window).status
            == "success"
        )
        assert c.calls[-1] == {"ann_date": day, "ts_code": code}
        clock["now"] += timedelta(minutes=5)
    history = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert {h.data_through for h in history} == {"20260720", "20260721"}
    assert (
        registry.datasets[0].as_of_field is None
        and registry.datasets[0].primary_key == ()
    )


def test_partial_provider_failure_does_not_preserve_invalid_success_prefix(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path)
    target = registry.datasets[0]
    binding = replace(
        target.provider_bindings[0],
        resumable_fanout=ResumableFanoutPolicy(
            progress_mode="session_day_rotation", max_batches_per_run=2
        ),
    )
    registry = DatasetRegistry(
        (replace(target, provider_bindings=(binding,)), registry.datasets[1])
    )
    path = _db(tmp_path, registry, monkeypatch, clock)

    class Partial(Collector):
        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            if params["ts_code"] == "B":
                return ProviderCallOutcome(
                    state="failed",
                    rows=(),
                    provider_code=-1,
                    error_code="provider_error",
                    error_message=None,
                )
            return ProviderCallOutcome(
                state="success",
                rows=(
                    {"ts_code": "A", "event_time": "2026-07-19 15:00:00", "close": 1.0},
                ),
                provider_code=0,
                error_code=None,
                error_message=None,
            )

    assert _collect(path, registry, Partial(), clock).status == "failed"
    assert _rows(path, registry.datasets[0]) == []
    h = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert len(h) == 2 and all(r.status == "failed" for r in h)


@pytest.mark.parametrize("response_time", [None, "20260719", "2026-07-20", "20260721"])
def test_partition_wrong_null_or_future_row_date_is_rejected(
    tmp_path, monkeypatch, clock, response_time
):
    registry = _registry(tmp_path, "partition_continuation")
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": p["ts_code"], "event_time": response_time, "close": 1.0}]
    )
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "failed"
    assert _rows(path, registry.datasets[0]) == []


def test_partition_empty_current_refreshes_and_failed_debt_does_not_starve_current(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path, "partition_continuation", values=("A", "B"))
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(state="empty")
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "empty"
    clock["now"] += timedelta(days=1)
    for day, state in [
        ("20260721", "empty"),
        ("20260720", "failed"),
        ("20260721", "empty"),
        ("20260720", "failed"),
        ("20260721", "empty"),
    ]:
        plan = _plans(path, registry, clock["now"])[0]
        assert dict(plan.request_window) == {"day": day}
        c.state = state
        assert _collect(path, registry, c, clock, plan.request_window).status == state
        clock["now"] += timedelta(minutes=5)
    assert [call["ts_code"] for call in c.calls if call["ann_date"] == "20260721"] == [
        "A",
        "B",
        "A",
    ]
    clock["now"] += timedelta(days=32)
    assert dict(_plans(path, registry, clock["now"])[0].request_window) == {
        "day": clock["now"].strftime("%Y%m%d")
    }
    assert (
        len(ingest._resumable_histories(path, registry, registry.datasets[0])) == 6
    )  # expired debt retained


def test_new_universe_cannot_borrow_previous_rotation(tmp_path, monkeypatch, clock):
    registry = _registry(tmp_path, values=("A", "B"))
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector()
    assert _collect(path, registry, c, clock).status == "success"
    clock["now"] += timedelta(minutes=5)
    target = registry.datasets[0]
    b = target.provider_bindings[0]
    changed = replace(b, fanout=replace(b.fanout, values=("A", "B", "C")))
    updated = DatasetRegistry(
        (replace(target, provider_bindings=(changed,)), registry.datasets[1])
    )
    assert _collect(path, updated, c, clock).status == "success"
    assert [x["ts_code"] for x in c.calls] == ["A", "A"]
    assert len(ingest._resumable_histories(path, updated, updated.datasets[0])) == 2


def test_registered_variant_only_controls_rotation():
    registry = helpers._resumable_window_registry(values=("A", "B"))
    target = registry.datasets[0]
    b = replace(
        target.provider_bindings[0],
        resumable_fanout=ResumableFanoutPolicy(progress_mode="session_day_rotation"),
    )
    target = replace(target, provider_bindings=(b,))
    registry = DatasetRegistry((target,))
    window = _window()
    histories = helpers._v2_histories(registry, window=window)
    forged = tuple(
        replace(h, request_variant={"variant": "unknown"}) for h in histories[:2]
    )
    batches = ingest._stable_fanout_batches(
        ("A", "B"), parameter="ts_code", batch_size=1, resumable=True
    )
    assert ingest._select_resumable_fanout_batches(
        batches, dataset=target, binding=b, request_window=window, histories=forged
    )[0].values == ("A",)
    # A's successful sibling is only an attempt: A will be revisited after B,
    # and the executor requests all registered variants again.
    assert (
        ingest._resumable_batch_state(
            batches[0],
            dataset=target,
            binding=b,
            request_window=window,
            histories=histories[:1],
        )
        != "complete"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"progress_mode": "unknown"},
        {"progress_mode": []},
        {"progress_mode": "session_day_rotation", "continuation_max_age_days": 1},
        {
            "progress_mode": "partition_continuation",
            "continuation_max_age_days": 32,
            "partition_date_field": "day",
        },
        {
            "progress_mode": "partition_continuation",
            "continuation_max_age_days": True,
            "partition_date_field": "day",
        },
        {"progress_mode": "partition_continuation", "continuation_max_age_days": 1},
    ],
)
def test_progress_policy_parser_and_compiler_fail_closed(patch):
    from tools.compile_provider_native_registry import _resumable_fanout
    from tools.compile_tushare_runtime_contracts import _request_resumable_fanout

    raw = {"cursor_contract_version": 2, "max_batches_per_run": 1, **patch}
    with pytest.raises(ValueError):
        ResumableFanoutPolicy(**raw)
    with pytest.raises(ValueError):
        _resumable_fanout(raw, "test")
    with pytest.raises(ValueError):
        _request_resumable_fanout(raw, label="test")


def test_new_binding_reobservation_preserves_old_fact_proof(
    tmp_path, monkeypatch, clock
):
    from query_contract import QueryAccessContext, QueryRequest
    from query_cursor import SignedCursorCodec
    from query_service import QueryService

    registry = _registry(tmp_path, "partition_continuation", values=("A",))
    target = registry.datasets[0]
    b = target.provider_bindings[0]
    old_target = replace(
        target,
        provider_bindings=(replace(b, resumable_fanout=ResumableFanoutPolicy()),),
    )
    old_registry = DatasetRegistry((old_target, registry.datasets[1]))
    path = _db(tmp_path, old_registry, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": p["ts_code"], "event_time": p["ann_date"], "close": 1.0}]
    )
    first = _collect(path, old_registry, c, clock, {"day": "20260720"})
    before = _rows(path, target)
    clock["now"] += timedelta(minutes=5)
    second = _collect(path, registry, c, clock, {"day": "20260720"})
    assert second.status == "success" and second.counts.unchanged == 1
    assert _rows(path, target) == before
    assert before[0][1] in first.receipt_ids and before[0][1] not in second.receipt_ids
    service = QueryService(
        db_path=path,
        registry=registry,
        cursor_codec=SignedCursorCodec(b"synthetic-signing-key-collection-progress"),
    )
    request = QueryRequest(
        dataset_id=target.dataset_id,
        schema_major=1,
        fields=("ts_code", "event_time"),
        filters={},
        as_of=None,
        order=("ts_code:asc",),
        limit=10,
        cursor=None,
        include_receipt_proofs=True,
    )
    result = service.execute(
        request,
        access=QueryAccessContext.from_grants(
            tenant_id="synthetic", scopes=("market_data",), allowed_dataset_ids=()
        ),
        now=clock["now"],
        request_id="synthetic-query",
    )
    assert (
        result["metadata"]["row_receipt_proofs"][0]["receipt_id"] in first.receipt_ids
    )
    assert (
        result["metadata"]["row_receipt_proofs"][0]["receipt_id"]
        not in second.receipt_ids
    )


def test_prechange_partition_debt_cannot_enter_new_binding_queue(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path, "partition_continuation")
    target = registry.datasets[0]
    old_binding = replace(
        target.provider_bindings[0], resumable_fanout=ResumableFanoutPolicy()
    )
    old = DatasetRegistry(
        (replace(target, provider_bindings=(old_binding,)), registry.datasets[1])
    )
    path = _db(tmp_path, old, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": p["ts_code"], "event_time": p["ann_date"], "close": 1.0}]
    )
    assert _collect(path, old, c, clock, {"day": "20260720"}).status == "success"
    clock["now"] += timedelta(days=1)
    for expected in ("A", "B"):
        plan = _plans(path, registry, clock["now"])[0]
        assert dict(plan.request_window) == {"day": "20260721"}
        assert (
            _collect(path, registry, c, clock, plan.request_window).status == "success"
        )
        assert c.calls[-1]["ts_code"] == expected
        clock["now"] += timedelta(minutes=5)


def test_failed_sibling_variant_is_retried_on_next_fair_visit(
    tmp_path, monkeypatch, clock
):
    registry = _registry(tmp_path, values=("A", "B"))
    target = registry.datasets[0]
    binding = replace(
        target.provider_bindings[0],
        request_variants=({"kind": "first"}, {"kind": "second"}),
        request_template={"freq": "1MIN", "kind": "first"},
    )
    registry = DatasetRegistry(
        (replace(target, provider_bindings=(binding,)), registry.datasets[1])
    )
    path = _db(tmp_path, registry, monkeypatch, clock)

    class Sibling(Collector):
        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            self.state = "failed" if params["kind"] == "second" else "success"
            return super().collect_outcome(
                api_name, params, fields, scan_budget=scan_budget
            )

    c = Sibling()
    for code in ("A", "B", "A"):
        assert _collect(path, registry, c, clock).status == "failed"
        assert [(p["ts_code"], p["kind"]) for p in c.calls[-2:]] == [
            (code, "first"),
            (code, "second"),
        ]
        clock["now"] += timedelta(minutes=5)
    history = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert len(history) == 6 and sum(h.status == "failed" for h in history) == 3


def test_partition_universe_change_cannot_borrow_started_or_current_seen(
    tmp_path, monkeypatch, clock
):
    from provider_ingest_contract import provider_ingest_config_hash

    registry = _registry(tmp_path, "partition_continuation", values=("A", "B"))
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": p["ts_code"], "event_time": p["ann_date"], "close": 1.0}]
    )
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "success"
    clock["now"] += timedelta(days=1)
    assert _collect(path, registry, c, clock, {"day": "20260721"}).status == "success"
    clock["now"] += timedelta(minutes=5)
    target = registry.datasets[0]
    binding = target.provider_bindings[0]
    updated_binding = replace(
        binding, fanout=replace(binding.fanout, values=("A", "B", "C"))
    )
    updated_target = replace(target, provider_bindings=(updated_binding,))
    updated = DatasetRegistry((updated_target, registry.datasets[1]))
    assert provider_ingest_config_hash(target, binding) == provider_ingest_config_hash(
        updated_target, updated_binding
    )
    for code in ("A", "B"):
        plan = _plans(path, updated, clock["now"])[0]
        assert dict(plan.request_window) == {"day": "20260721"}
        assert (
            _collect(path, updated, c, clock, plan.request_window).status == "success"
        )
        assert c.calls[-1]["ts_code"] == code
        clock["now"] += timedelta(minutes=5)


@pytest.mark.parametrize("code", [[], {}, None, ""])
def test_invalid_partition_code_records_failure_and_does_not_pin_batch(
    tmp_path, monkeypatch, clock, code
):
    registry = _registry(tmp_path, "partition_continuation")
    path = _db(tmp_path, registry, monkeypatch, clock)
    c = Collector(
        lambda p: [{"ts_code": code, "event_time": p["ann_date"], "close": 1.0}]
    )
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "failed"
    assert _rows(path, registry.datasets[0]) == []
    histories = ingest._resumable_histories(path, registry, registry.datasets[0])
    assert len(histories) == 1 and histories[0].status == "failed"
    clock["now"] += timedelta(minutes=5)
    c.make_rows = lambda p: [
        {"ts_code": p["ts_code"], "event_time": p["ann_date"], "close": 1.0}
    ]
    assert _collect(path, registry, c, clock, {"day": "20260720"}).status == "success"
    assert c.calls[-1]["ts_code"] == "B"


def _real_source_progress_registry(tmp_path, monkeypatch, clock, name):
    full = load_runtime_dataset_registry()
    target = full.resolve("cn.dataset." + name)
    binding = target.provider_bindings[0]
    source = full.resolve(binding.fanout.source_dataset_id)
    calendar = full.resolve("cn.market.trade_calendar")
    registry = DatasetRegistry((target, source, calendar))
    path = _db(tmp_path, registry, monkeypatch, clock)
    codes = ("000001.SZ", "000002.SZ") if name == "income" else ("110001.SH", "110002.SH")

    class SourceCollector(Collector):
        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            rows = tuple({**{field.name: None for field in source.fields},
                          "ts_code": code, "list_date": "20100101"} for code in codes)
            if "list_status" in params:
                rows = tuple({**row, "list_status": params["list_status"]} for row in rows)
            return ProviderCallOutcome(state="success" if rows else "empty", rows=rows,
                provider_code=0, error_code=None, error_message=None,
                response_fields=tuple(field.name for field in source.fields))

    result = ingest.collect_provider_native_dataset(path, registry=registry,
        collector=SourceCollector(), dataset_id=source.dataset_id, request_window={},
        attempt_id=str(uuid4()), started_at=(clock["now"] - timedelta(seconds=1)).isoformat())
    assert result.status == "success", result
    clock["now"] += timedelta(minutes=5)
    return path, registry, target, source, codes


@pytest.mark.parametrize("name", ["income", "cb_share"])
def test_calendar_only_planner_hydrates_verified_fanout_dependencies(
    tmp_path, monkeypatch, clock, name
):
    path, registry, target, source, codes = _real_source_progress_registry(
        tmp_path, monkeypatch, clock, name)
    state = helpers.scheduler.load_planner_state(path, registry, now=clock["now"],
        calendar_dataset_ids=frozenset({"cn.market.trade_calendar"}))
    source_facts = state.get(source, source.provider_bindings[0]).facts
    assert {fact.payload.get("ts_code") for fact in source_facts} == set(codes)
    plans, skips = helpers.cadence_planner.plan_runs(registry=registry,
        schedule=helpers.scheduler.load_schedule(helpers.SCHEDULE_CONFIG), state=state,
        now=clock["now"], selected_dataset_ids=frozenset({target.dataset_id}),
        current_only=True)
    assert len(plans) == 1 and dict(plans[0].request_window) == {"ann_date": "20260720"}


@pytest.mark.parametrize("name", ["income", "cb_share"])
def test_real_dataset_field_continuation_collect_receipt_planner_roundtrip(
    tmp_path, monkeypatch, clock, name
):
    path, registry, target, source, codes = _real_source_progress_registry(
        tmp_path, monkeypatch, clock, name)
    date_field = target.provider_bindings[0].resumable_fanout.partition_date_field
    collector = Collector(lambda params: [{
        **{field.name: None for field in target.fields}, "ts_code": params["ts_code"],
        date_field: params["ann_date"],
    }])
    for day, expected_codes in (("20260720", codes), ("20260721", codes)):
        if day == "20260721":
            clock["now"] += timedelta(days=1)
        for code in expected_codes:
            result = _collect(path, registry, collector, clock, {"ann_date": day})
            assert result.status == "success"
            assert collector.calls[-1]["ts_code"] == code
            clock["now"] += timedelta(minutes=5)
    histories = ingest._resumable_histories(path, registry, target)
    assert len(histories) == 4 and all(item.status == "success" for item in histories)
    assert [item.batch_index for item in sorted(histories, key=lambda item: item.started_at)] == [0, 1, 0, 1]
    assert {item.data_through for item in histories} == {"20260720", "20260721"}
    state = helpers.scheduler.load_planner_state(path, registry, now=clock["now"],
        calendar_dataset_ids=frozenset({"cn.market.trade_calendar"}))
    assert all(not fact.payload for fact in state.get(target, target.provider_bindings[0]).facts)
    plans, _ = helpers.cadence_planner.plan_runs(registry=registry,
        schedule=helpers.scheduler.load_schedule(helpers.SCHEDULE_CONFIG), state=state,
        now=clock["now"], selected_dataset_ids=frozenset({target.dataset_id}), current_only=True)
    assert len(plans) == 1 and dict(plans[0].request_window) == {"ann_date": "20260721"}
