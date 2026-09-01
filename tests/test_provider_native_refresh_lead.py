from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

from dataset_registry import DatasetRegistry, load_dataset_registry
from provider_ingest_contract import provider_ingest_config_hash
from storage.receipt_projection import ValidatedReceiptHistoryEntry
import tools.provider_native_cadence_planner as planner

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "config/provider_native_schedule.yaml"
FIELD = "freshness_refresh_lead_seconds"


def _schedule(value=None, *, cadence="event", explicit=False):
    document = yaml.safe_load(SCHEDULE.read_bytes())
    if explicit:
        document["cadences"][cadence][FIELD] = value
    return planner.load_schedule_bytes(yaml.safe_dump(document).encode())


@pytest.fixture(scope="module")
def registry():
    return load_dataset_registry()


def _case(
    registry, *, status="empty", with_older_empty=False, sla=900, no_window=False
):
    dataset = registry.resolve("cn.dataset.stk_holdernumber")
    binding = dataset.provider_bindings[0]
    if no_window:
        binding = replace(
            binding, request_window_policy=None, request_template=MappingProxyType({})
        )
    dataset = replace(dataset, freshness_sla_seconds=sla, provider_bindings=(binding,))
    local_registry = DatasetRegistry((dataset,), query_defaults=registry.query_defaults)
    window = {} if no_window else {"ann_date": "20260830"}
    receipt = ValidatedReceiptHistoryEntry(
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        receipt_id="synthetic-current",
        status=status,
        cohort_status=status,
        started_at=datetime.fromisoformat("2026-08-30T21:15:00+08:00"),
        finished_at=datetime.fromisoformat("2026-08-30T21:17:37+08:00"),
        request_window=MappingProxyType(window),
        request_variant=MappingProxyType({}),
        execution_id="synthetic-current",
        config_hash=provider_ingest_config_hash(dataset, binding),
    )
    older = replace(
        receipt,
        receipt_id="synthetic-old-empty",
        status="empty",
        cohort_status="empty",
        started_at=datetime.fromisoformat("2026-08-30T20:00:00+08:00"),
        finished_at=datetime.fromisoformat("2026-08-30T20:01:00+08:00"),
        execution_id="synthetic-old-empty",
    )
    receipts = (older, receipt) if with_older_empty else (receipt,)
    facts = (
        (planner._Fact(None, MappingProxyType({}), receipt.receipt_id),)
        if status == "success"
        else ()
    )
    state = planner.PlannerState(
        MappingProxyType(
            {
                (dataset.dataset_id, binding.provider): planner._DatasetState(
                    receipts=receipts, facts=facts
                )
            }
        )
    )
    return local_registry, dataset, state


def _plan(case, schedule, clock="21:25:00"):
    registry, dataset, state = case
    return planner.plan_runs(
        registry=registry,
        schedule=schedule,
        state=state,
        now=datetime.fromisoformat("2026-08-30T" + clock + "+08:00"),
    )


def test_lead_defaults_to_zero_without_checked_in_enablement():
    schedule = _schedule()
    assert all(getattr(policy, FIELD) == 0 for policy in schedule.cadences.values())
    assert FIELD not in yaml.safe_load(SCHEDULE.read_bytes())["cadences"]["event"]


@pytest.mark.parametrize("value", [True, False, 1.0, "600", None, -1, 900, 901])
def test_invalid_event_lead_is_rejected(value):
    with pytest.raises(ValueError):
        _schedule(value, explicit=True)


@pytest.mark.parametrize("cadence", sorted(planner.CADENCE_CLASSES - {"event"}))
def test_nonzero_lead_is_only_valid_for_event(cadence):
    with pytest.raises(ValueError):
        _schedule(1, cadence=cadence, explicit=True)


@pytest.mark.parametrize("cadence", sorted(planner.CADENCE_CLASSES))
def test_explicit_zero_is_compatible_for_every_cadence(cadence):
    assert _schedule(0, cadence=cadence, explicit=True) == _schedule()


@pytest.mark.parametrize("status,older", [("empty", False), ("success", True)])
@pytest.mark.parametrize("no_window", [False, True])
def test_short_sla_repeat_is_due_before_next_timer_deadline(
    registry, status, older, no_window
):
    case = _case(registry, status=status, with_older_empty=older, no_window=no_window)
    before, skips = _plan(case, _schedule())
    assert before == () and skips[0].state == "not_due"
    after, skips = _plan(case, _schedule(600, explicit=True))
    assert len(after) == 1 and skips == ()
    assert dict(after[0].request_window) == (
        {} if no_window else {"ann_date": "20260830"}
    )
    assert after[0].priority == "current"
    assert after[0].retry == _schedule().cadences["event"].retry


@pytest.mark.parametrize(
    "clock", ["21:20:00", "21:25:00", "21:30:00", "21:32:37", "21:35:00"]
)
def test_lead_zero_preserves_exact_original_results(registry, clock):
    case = _case(registry)
    assert _plan(case, _schedule(), clock) == _plan(
        case, _schedule(0, explicit=True), clock
    )


@pytest.mark.parametrize("no_window", [False, True])
def test_long_sla_repeat_does_not_speed_up(registry, no_window):
    case = _case(registry, sla=86400, no_window=no_window)
    for clock in ["21:20:00", "21:25:00", "21:30:00", "21:35:00"]:
        assert _plan(case, _schedule(), clock) == _plan(
            case, _schedule(600, explicit=True), clock
        )


@pytest.mark.parametrize("older", [False, True])
@pytest.mark.parametrize("no_window", [False, True])
def test_failure_keeps_all_existing_retry_and_correction_throttles(
    registry, older, no_window
):
    case = _case(registry, status="failed", with_older_empty=older, no_window=no_window)
    for clock in ["21:20:00", "21:25:00", "21:30:00", "21:35:00"]:
        assert _plan(case, _schedule(), clock) == _plan(
            case, _schedule(600, explicit=True), clock
        )


def test_invalid_receipt_authority_is_never_advanced(registry):
    local, dataset, state = _case(registry)
    state = replace(
        state,
        invalid_datasets=MappingProxyType(
            {(dataset.dataset_id, "tushare"): ("receipt_identity_mismatch",)}
        ),
    )
    plans, skips = _plan((local, dataset, state), _schedule(600, explicit=True))
    assert plans == () and skips[0].state == "invalid_receipt_authority"


def test_candidate_keeps_budgets_unchanged_and_does_not_repeat_early(registry):
    candidate = _schedule(600, explicit=True)
    assert candidate.rate_budgets == _schedule().rate_budgets
    case = _case(registry)
    plans, skips = _plan(case, candidate, "21:20:00")
    assert plans == () and skips[0].state == "not_due"


def test_refresh_interval_boundary_is_exact(registry):
    case = _case(registry)
    schedule = _schedule(600, explicit=True)
    plans, skips = _plan(case, schedule, "21:22:36")
    assert plans == () and skips[0].state == "not_due"
    plans, skips = _plan(case, schedule, "21:22:37")
    assert len(plans) == 1 and skips == ()


def test_paused_binding_remains_paused(registry):
    local, dataset, state = _case(registry)
    binding = replace(dataset.provider_bindings[0], activation_state="paused")
    dataset = replace(dataset, provider_bindings=(binding,))
    local = DatasetRegistry((dataset,), query_defaults=local.query_defaults)
    plans, skips = _plan((local, dataset, state), _schedule(600, explicit=True))
    assert plans == () and skips[0].state == "paused"


def test_previous_day_empty_cannot_cover_new_day(registry):
    local, dataset, state = _case(registry)
    plans, _ = planner.plan_runs(
        registry=local,
        schedule=_schedule(600, explicit=True),
        state=state,
        now=datetime.fromisoformat("2026-08-31T00:00:00+08:00"),
    )
    assert len(plans) == 1
    assert dict(plans[0].request_window) == {"ann_date": "20260831"}


@pytest.mark.parametrize(
    "sla,lead,expected",
    [(900, 600, 300), (86400, 600, 900), (300, 600, 1), (900, 899, 1)],
)
def test_frozen_effective_interval_formula(registry, sla, lead, expected):
    dataset = replace(
        registry.resolve("cn.dataset.stk_holdernumber"), freshness_sla_seconds=sla
    )
    policy = _schedule(lead, explicit=True).cadences["event"]
    assert planner._repeat_interval_seconds(dataset, policy, "empty") == expected
    assert planner._repeat_interval_seconds(dataset, policy, "success") == expected
    assert planner._repeat_interval_seconds(dataset, policy, "failed") == 900
