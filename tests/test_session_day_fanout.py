"""Generic current-day cumulative fanout, independent of provider API names."""

from dataclasses import replace
from datetime import date, datetime
import sqlite3
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest

from dataset_registry import DatasetRegistry, ResumableFanoutPolicy, load_dataset_registry
from provider_ingest_contract import provider_ingest_config_hash
from tests.test_provider_native_registry import generic_dataset, write_registry
from tests import test_provider_native_schedule as fixtures
from collectors.tushare.provider_native_ingest import _select_resumable_fanout_batches, _stable_fanout_batches


def _registry():
    base = fixtures._resumable_window_registry(values=("A", "B", "C"))
    dataset = base.datasets[0]
    binding = replace(dataset.provider_bindings[0], request_template=MappingProxyType({"variant": "a"}),
                      request_window_policy=None,
                      resumable_fanout=ResumableFanoutPolicy(max_batches_per_run=1, window_scope="session_day"))
    dataset = replace(dataset, cadence_class="session_minute", provider_bindings=(binding,))
    calendar = fixtures._active_registry().resolve("cn.market.trade_calendar")
    return DatasetRegistry((dataset, calendar), query_defaults=base.query_defaults)


def test_session_day_scope_hash_isolated_and_bar_hash_compatible():
    registry = _registry()
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]
    bar = replace(binding, resumable_fanout=ResumableFanoutPolicy(max_batches_per_run=1))
    explicit_bar = replace(bar, resumable_fanout=replace(bar.resumable_fanout, window_scope="bar"))
    assert provider_ingest_config_hash(dataset, bar) == provider_ingest_config_hash(dataset, explicit_bar)
    assert provider_ingest_config_hash(dataset, binding) != provider_ingest_config_hash(dataset, bar)


@pytest.mark.parametrize("scope", ["week", "", None, 1, True])
def test_scope_rejects_unknown_values(tmp_path, scope):
    payload = generic_dataset(cadence_class="session_minute")
    binding = payload["provider_bindings"][0]
    binding["resumable_fanout"] = {"cursor_contract_version": 2, "max_batches_per_run": 1, "window_scope": scope}
    with pytest.raises(ValueError, match="window_scope"):
        load_dataset_registry(write_registry(tmp_path, payload))


@pytest.mark.parametrize("contamination", ["none", "old_day", "old_bar", "old_config", "old_universe"])
def test_session_day_cursor_continues_and_never_borrows_identity(contamination):
    registry = _registry()
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]
    window = {"session_date": "20260728"}
    histories = tuple(h for h in fixtures._v2_histories(registry, window=window) if h.batch_index == 0)
    if contamination == "old_day":
        histories = tuple(replace(h, request_window={"session_date": "20260727"}) for h in histories)
    elif contamination == "old_bar":
        histories = tuple(replace(h, request_window={"bar_time": "2026-07-28 09:30:00"}) for h in histories)
    elif contamination == "old_config":
        histories = tuple(replace(h, config_hash="0" * 64) for h in histories)
    elif contamination == "old_universe":
        histories = tuple(replace(h, frozen_universe_sha256="0" * 64) for h in histories)
    batches = _stable_fanout_batches(binding.fanout.values, parameter="ts_code", batch_size=1, resumable=True)
    selected = _select_resumable_fanout_batches(batches, dataset=dataset, binding=binding, request_window=window, histories=histories)
    assert selected[0].batch_index == (1 if contamination == "none" else 0)
    assert _select_resumable_fanout_batches(batches, dataset=dataset, binding=binding, request_window={"session_date": "20260729"}, histories=histories)[0].batch_index == 0


def test_session_day_transient_failure_still_retries_first():
    registry = _registry()
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]
    window = {"session_date": "20260728"}
    histories = tuple(h for h in fixtures._v2_histories(registry, window=window, statuses={(1, "a"): "failed", (1, "b"): "failed"}) if h.batch_index < 2)
    batches = _stable_fanout_batches(binding.fanout.values, parameter="ts_code", batch_size=1, resumable=True)
    assert _select_resumable_fanout_batches(batches, dataset=dataset, binding=binding, request_window=window, histories=histories) == (batches[1],)


@pytest.mark.parametrize("day,hour,minute,expected", [(28, 9, 35, True), (28, 9, 40, True), (28, 12, 0, False), (29, 9, 35, True), (26, 9, 35, False), (30, 9, 35, False), (28, 16, 0, False)])
def test_session_day_planner_preserves_session_gate_and_day(tmp_path, monkeypatch, day, hour, minute, expected):
    registry = _registry()
    db_path = tmp_path / "facts.sqlite"
    fixtures._database(db_path)
    schedule = fixtures.scheduler.load_schedule(fixtures.SCHEDULE_CONFIG)
    with sqlite3.connect(db_path) as conn:
        fixtures._seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 26): False, date(2026, 7, 28): True, date(2026, 7, 29): True})
        conn.commit()
    now = datetime(2026, 7, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    state = fixtures.scheduler.load_planner_state(db_path, registry, now=now)
    plans, _ = fixtures.cadence_planner.plan_runs(registry=registry, schedule=schedule, state=state, now=now, current_only=True, selected_dataset_ids=frozenset({registry.datasets[0].dataset_id}))
    assert bool(plans) is expected
    if expected:
        assert plans[0].request_window == {"session_date": f"202607{day}"}


@pytest.mark.parametrize("window", [{}, {"session_date": "20260727"}, {"session_date": "20260729"}, {"session_date": "20260728", "bar_time": "09:30"}])
def test_session_day_rejects_wrong_day_before_provider_or_store_access(tmp_path, window):
    from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
    registry = _registry()
    with pytest.raises(ValueError, match="session_date"):
        collect_provider_native_dataset(tmp_path / "missing.sqlite", registry=registry, collector=object(), dataset_id=registry.datasets[0].dataset_id, request_window=window, attempt_id="018f47de-0000-7000-8000-000000000001", started_at="2026-07-28T01:35:00Z")


@pytest.mark.parametrize("mutation", ["cadence", "template", "completeness"])
def test_session_day_registry_rejects_incompatible_contract(tmp_path, mutation):
    payload = generic_dataset(cadence_class="session_minute")
    binding = payload["provider_bindings"][0]
    binding.update(request_shape="dimension_fanout", request_template={}, request_variants=[{}], request_window_policy=None, response_completeness=None,
                   fanout={"strategy": "literal_values", "parameter": "ts_code", "values": ["A"], "batch_size": 1},
                   resumable_fanout={"cursor_contract_version": 2, "max_batches_per_run": 1, "window_scope": "session_day"})
    if mutation == "cadence":
        payload["cadence_class"] = "daily_reference"
    elif mutation == "template":
        binding["request_template"] = {"day": "${window.day}"}
    else:
        binding["response_completeness"] = {"strategy": "unique_primary_key_snapshot", "fixed_field_matches": {}, "reject_at_row_limit": False}
    with pytest.raises(ValueError, match="session_day|request_window_policy"):
        load_dataset_registry(write_registry(tmp_path, payload))


@pytest.mark.parametrize("parser_path", ["runtime", "observation", "registry"])
def test_scope_compilers_reject_unknown_and_preserve_legacy_shape(parser_path):
    from tools.compile_provider_native_registry import _resumable_fanout
    from tools.compile_tushare_runtime_contracts import _request_resumable_fanout
    from dataset_registry import _resumable_fanout_policy
    parsers = {
        "runtime": lambda value: _resumable_fanout(value, "synthetic.resumable_fanout"),
        "observation": lambda value: _request_resumable_fanout(value, label="synthetic.resumable_fanout"),
        "registry": lambda value: _resumable_fanout_policy(value, path="synthetic.resumable_fanout"),
    }
    parser = parsers[parser_path]
    legacy = {"cursor_contract_version": 2, "max_batches_per_run": 20}
    base = parser(legacy)
    assert parser({**legacy, "window_scope": "bar"}) == base
    for scope in ("week", "", None, 1, True):
        with pytest.raises((ValueError, RuntimeError), match="window_scope"):
            parser({**legacy, "window_scope": scope})
    daily = parser({**legacy, "window_scope": "session_day"})
    assert (daily.window_scope if parser_path == "registry" else daily["window_scope"]) == "session_day"


def test_scope_window_identity_does_not_become_a_provider_parameter():
    from collectors.tushare.provider_native_ingest import _resolved_request
    registry = _registry()
    binding = registry.datasets[0].provider_bindings[0]
    # This synthetic request has no parameters and one empty variant.
    binding = replace(binding, request_template=MappingProxyType({}), request_variants=(MappingProxyType({}),))
    window, params = _resolved_request(binding, {"session_date": "20260728"}, request_variant={})
    assert window == {"session_date": "20260728"}
    assert params == {}


def test_session_day_collect_receipt_authority_round_trip_continues_and_resets(tmp_path, monkeypatch):
    import json
    from tests import test_collect_provider_dataset as collect_fixtures
    from collectors.tushare import provider_native_ingest as ingest
    from collectors.tushare.tushare_common import ProviderCallOutcome
    from dataset_registry import FanoutPolicy
    from storage import ingest_receipts
    from storage.receipt_projection import load_dataset_runtime_projection

    base = collect_fixtures._registry()
    original = base.datasets[0]
    binding = replace(
        original.provider_bindings[0], request_shape="dimension_fanout",
        request_template=MappingProxyType({}), request_variants=(MappingProxyType({}),),
        request_window_policy=None, response_completeness=None,
        fanout=FanoutPolicy(strategy="literal_values", parameter="ts_code", values=("A", "B", "C"), batch_size=1),
        resumable_fanout=ResumableFanoutPolicy(max_batches_per_run=1, window_scope="session_day"),
    )
    dataset = replace(original, cadence_class="session_minute", provider_bindings=(binding,))
    registry = DatasetRegistry((dataset,), query_defaults=base.query_defaults)
    db_path = tmp_path / "facts.sqlite"
    collect_fixtures._database(db_path)
    fixtures.sqlite_authority_lock_path(db_path).touch(mode=0o600)
    assert ingest._resumable_histories(db_path, registry, dataset) == ()
    calls = []

    class Collector:
        current_date = "20260728"

        def collect_outcome(self, api_name, params, fields=None, *, scan_budget=None):
            assert "session_date" not in params
            calls.append(params["ts_code"])
            return ProviderCallOutcome(state="success", rows=({"ts_code": params["ts_code"], "trade_date": self.current_date, "close": 1.0},), provider_code=0, error_code=None, error_message=None)

    collector = Collector()
    for attempt, day, minute in ((1, "20260728", "35"), (2, "20260728", "40"), (3, "20260729", "35")):
        collector.current_date = day
        iso_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        start = f"{iso_day}T01:{minute}:00Z"
        end = f"{iso_day}T01:{minute}:01Z"
        monkeypatch.setattr(ingest_receipts, "_utc_now", lambda: end)
        result = ingest.collect_provider_native_dataset(db_path, registry=registry, collector=collector, dataset_id=dataset.dataset_id, request_window={"session_date": day}, attempt_id=f"018f47de-0000-7000-8000-{attempt:012d}", started_at=start)
        assert result.status == "success", result
        histories = ingest._resumable_histories(db_path, registry, dataset)
        assert len(histories) == attempt
        projection = load_dataset_runtime_projection(db_path, dataset, registry=registry, now=datetime.fromisoformat(end.replace("Z", "+00:00")))
        assert projection.state == "success"
    assert calls == ["A", "B", "A"]
    with sqlite3.connect(db_path) as conn:
        receipts = [json.loads(row[0]) for row in conn.execute("SELECT notes FROM market_ingest_runs ORDER BY started_at")]
    assert [receipt["request_identity"]["batch_index"] for receipt in receipts] == [0, 1, 0]
    assert [receipt["request_window"] for receipt in receipts] == [{"session_date": "20260728"}, {"session_date": "20260728"}, {"session_date": "20260729"}]


@pytest.mark.parametrize("evidence", ["complete", "partial", "old_config"])
def test_completed_session_day_does_not_create_zero_call_freshness(tmp_path, monkeypatch, evidence):
    registry = _registry()
    dataset = registry.datasets[0]
    binding = dataset.provider_bindings[0]
    db_path = tmp_path / "facts.sqlite"
    fixtures._database(db_path)
    with sqlite3.connect(db_path) as conn:
        fixtures._seed_calendar(monkeypatch, conn, registry, {date(2026, 7, 28): True})
        conn.commit()
    now = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    state = fixtures.scheduler.load_planner_state(db_path, registry, now=now)
    histories = fixtures._v2_histories(registry, window={"session_date": "20260728"})
    if evidence == "partial":
        histories = tuple(item for item in histories if item.batch_index < 2)
    elif evidence == "old_config":
        histories = tuple(replace(item, config_hash="0" * 64) for item in histories)
    state = replace(state, datasets=MappingProxyType({**state.datasets, (dataset.dataset_id, binding.provider): fixtures.cadence_planner._DatasetState(histories, ())}))
    plans, skips = fixtures.cadence_planner.plan_runs(registry=registry, schedule=fixtures.scheduler.load_schedule(fixtures.SCHEDULE_CONFIG), state=state, now=now, current_only=True, selected_dataset_ids=frozenset({dataset.dataset_id}))
    assert bool(plans) is (evidence != "complete")
    if evidence == "complete":
        assert next(item.state for item in skips if item.dataset_id == dataset.dataset_id) == "not_due"
