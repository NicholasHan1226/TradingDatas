"""Pure, registry-driven cadence/backfill planning from read-only SQLite authority."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import yaml

from dataset_registry import (
    DatasetDefinition,
    DatasetRegistry,
    ProviderBinding,
    ResumableFanoutPolicy,
    RequestScalar,
    encode_request_window_value,
    normalize_request_window,
    request_window_covered_dates,
)
from provider_ingest_contract import provider_ingest_config_hash
from storage.receipt_projection import (
    RuntimeProjectionError,
    ValidatedReceiptHistoryEntry,
    open_verified_read_model_snapshot,
    validated_receipt_histories_by_dataset,
)


CADENCE_CLASSES = frozenset(
    {
        "session_minute",
        "postclose_daily",
        "daily_reference",
        "weekly",
        "monthly",
        "quarterly_reporting",
        "event",
        "on_demand",
    }
)
_ROOT_KEYS = frozenset(
    {"version", "dataset_timeout_seconds", "rate_budgets", "cadences"}
)
_CADENCE_KEYS = frozenset(
    {
        "automatic",
        "availability_after_local",
        "session_windows_local",
        "weekdays",
        "incremental_mode",
        "partition_frequency",
        "calendar",
        "minimum_interval_seconds",
        "failure_retry_seconds",
        "correction_overlap_days",
        "correction_overlap_bars",
        "backfill_start_policy",
        "backfill_lookback_days",
        "backfill_start_date",
        "backfill_chunk_span_days",
        "future_horizon_days",
        "max_backfill_chunks_per_run",
        "rate_budget_class",
        "retry",
    }
)
_REQUIRED_CADENCE_KEYS = _CADENCE_KEYS - {"session_windows_local"}
_PRIORITY = {"current": 0, "backfill": 1, "correction": 2}
_ACTIVATION_WAVE_ROOT_KEYS = frozenset({"version", "input_hashes", "waves"})
_ACTIVATION_WAVE_HASH_KEYS = frozenset(
    {"runtime_registry_sha256", "schedule_sha256"}
)
_ACTIVATION_WAVE_KEYS = frozenset({"dataset_ids"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _execution_order(plan: "ScheduledRun") -> tuple[int, int, str]:
    """Order current intraday observations before other equal-priority work.

    This remains cadence-driven: any dataset declared as ``session_minute`` gets
    the first provider slot in its current/backfill/correction tier.  It avoids
    an alphabetically earlier reference request delaying a completed bar while
    preserving the existing priority and deterministic dataset ordering.
    """

    return (
        _PRIORITY[plan.priority],
        0 if plan.cadence_class == "session_minute" else 1,
        plan.dataset_id,
    )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: int
    max_delay_seconds: int
    jitter_seconds: int


@dataclass(frozen=True)
class RateBudget:
    account_requests_per_run: int
    provider_requests_per_run: int
    api_requests_per_run: int
    api_overrides: Mapping[str, int] = MappingProxyType({})


@dataclass(frozen=True)
class CalendarPolicy:
    dataset_id: str
    date_field: str
    open_field: str
    open_values: tuple[object, ...]
    previous_open_date_field: str | None = None


@dataclass(frozen=True)
class CadencePolicy:
    automatic: bool
    availability_after_local: time | None
    session_windows_local: tuple[tuple[time, time], ...]
    weekdays: tuple[int, ...]
    incremental_mode: str
    partition_frequency: str
    calendar: CalendarPolicy | None
    minimum_interval_seconds: int
    failure_retry_seconds: int
    correction_overlap_days: int
    correction_overlap_bars: int
    backfill_start_policy: str
    backfill_lookback_days: int
    backfill_start_date: date | None
    backfill_chunk_span_days: int
    future_horizon_days: int
    max_backfill_chunks_per_run: int
    rate_budget_class: str
    retry: RetryPolicy


@dataclass(frozen=True)
class Schedule:
    dataset_timeout_seconds: int
    rate_budgets: Mapping[str, RateBudget]
    cadences: Mapping[str, CadencePolicy]


@dataclass(frozen=True)
class ScheduledRun:
    dataset_id: str
    provider: str
    provider_api: str
    cadence_class: str
    request_window: Mapping[str, str]
    priority: str = "current"
    request_variants: tuple[Mapping[str, RequestScalar], ...] = field(
        default_factory=lambda: (MappingProxyType({}),)
    )
    rate_budget_class: str = "standard"
    retry: RetryPolicy = RetryPolicy(1, 0, 0, 0)
    retry_jitter_seconds: int = 0
    resumable_fanout: ResumableFanoutPolicy | None = None


@dataclass(frozen=True)
class PlannerSkip:
    dataset_id: str
    provider: str
    state: str


@dataclass(frozen=True)
class ActivationWave:
    dataset_ids: frozenset[str]


@dataclass(frozen=True)
class _Fact:
    partition_value: str | None
    payload: Mapping[str, object]
    receipt_id: str


@dataclass(frozen=True)
class _DatasetState:
    receipts: tuple[ValidatedReceiptHistoryEntry, ...] = ()
    facts: tuple[_Fact, ...] = ()


@dataclass(frozen=True)
class _ReceiptCohort:
    execution_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    request_window: Mapping[str, str]
    receipt_ids: frozenset[str]
    success_receipt_ids: frozenset[str]


@dataclass(frozen=True)
class PlannerState:
    datasets: Mapping[tuple[str, str], _DatasetState]
    invalid_datasets: Mapping[tuple[str, str], tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def get(
        self, dataset: DatasetDefinition, binding: ProviderBinding
    ) -> _DatasetState:
        return self.datasets.get(
            (dataset.dataset_id, binding.provider), _DatasetState()
        )

    def invalid_reasons(
        self, dataset: DatasetDefinition, binding: ProviderBinding
    ) -> tuple[str, ...]:
        return self.invalid_datasets.get((dataset.dataset_id, binding.provider), ())


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(
    loader: _UniqueLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("schedule YAML contains a duplicate key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def _mapping(value: object, label: str) -> dict[object, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a mapping")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical text")
    return value


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be SHA-256")
    return text


def load_activation_wave(
    path: Path,
    wave_id: str,
    *,
    registry: DatasetRegistry,
    registry_payload: bytes,
    schedule_payload: bytes,
) -> ActivationWave:
    """Load one fail-closed, hash-bound canonical dataset selection."""

    root = _mapping(
        yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueLoader),
        "activation wave manifest",
    )
    if (
        set(root) != _ACTIVATION_WAVE_ROOT_KEYS
        or type(root["version"]) is not int
        or root["version"] != 1
    ):
        raise ValueError("activation wave manifest contract is invalid")
    hashes = _mapping(root["input_hashes"], "activation wave input hashes")
    if set(hashes) != _ACTIVATION_WAVE_HASH_KEYS:
        raise ValueError("activation wave input hashes are invalid")
    expected_registry_hash = _sha256(
        hashes["runtime_registry_sha256"], "runtime registry SHA-256"
    )
    expected_schedule_hash = _sha256(hashes["schedule_sha256"], "schedule SHA-256")
    if hashlib.sha256(registry_payload).hexdigest() != expected_registry_hash:
        raise ValueError("runtime registry SHA-256 does not match activation wave")
    if hashlib.sha256(schedule_payload).hexdigest() != expected_schedule_hash:
        raise ValueError("schedule SHA-256 does not match activation wave")
    waves = _mapping(root["waves"], "activation waves")
    if not waves:
        raise ValueError("activation waves must be non-empty")
    wave_names = tuple(_text(item, "activation wave id") for item in waves)
    if wave_names != tuple(sorted(wave_names)):
        raise ValueError("activation wave ids must be sorted")
    validated: dict[str, frozenset[str]] = {}
    seen_dataset_ids: set[str] = set()
    for name, value in waves.items():
        raw_wave = _mapping(value, f"activation wave {name}")
        if set(raw_wave) != _ACTIVATION_WAVE_KEYS:
            raise ValueError("activation wave keys are invalid")
        raw_ids = raw_wave["dataset_ids"]
        if type(raw_ids) is not list or not raw_ids:
            raise ValueError("activation wave dataset_ids must be non-empty")
        dataset_ids = tuple(
            _text(item, "activation wave dataset_id") for item in raw_ids
        )
        if tuple(sorted(dataset_ids)) != dataset_ids:
            raise ValueError("activation wave dataset_ids must be sorted")
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ValueError("activation wave contains duplicate dataset_id")
        for dataset_id in dataset_ids:
            if dataset_id in seen_dataset_ids:
                raise ValueError("activation wave contains duplicate dataset_id")
            seen_dataset_ids.add(dataset_id)
            try:
                dataset = registry.resolve(dataset_id)
            except KeyError as exc:
                raise ValueError("activation wave dataset_id is unknown") from exc
            if dataset.dataset_id != dataset_id:
                raise ValueError("activation wave must use canonical dataset_id")
            try:
                _active_binding(dataset)
            except ValueError as exc:
                raise ValueError(
                    "activation wave dataset must be active and entitled"
                ) from exc
        validated[name] = frozenset(dataset_ids)
    name = _text(wave_id, "activation wave id")
    if name not in validated:
        raise ValueError("unknown activation wave")
    return ActivationWave(validated[name])


def _integer(value: object, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(
            f"{label} must be {'positive' if positive else 'non-negative'}"
        )
    return value


def _clock(value: object, label: str) -> time | None:
    if value is None:
        return None
    text = _text(value, label)
    if len(text) != 5 or text[2] != ":":
        raise ValueError(f"{label} must use HH:MM")
    return time.fromisoformat(text)


def _day(value: object, label: str) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(_text(value, label), "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYYMMDD") from exc


def _session_windows(value: object, label: str) -> tuple[tuple[time, time], ...]:
    if value is None:
        return ()
    if type(value) is not list:
        raise ValueError(f"{label} must be a list")
    windows: list[tuple[time, time]] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"{label}[{index}]")
        if set(item) != {"start", "end"}:
            raise ValueError(f"{label}[{index}] keys are invalid")
        start = _clock(item["start"], f"{label}[{index}].start")
        end = _clock(item["end"], f"{label}[{index}].end")
        if start is None or end is None or start >= end:
            raise ValueError(f"{label}[{index}] range is invalid")
        windows.append((start, end))
    if any(previous[1] >= current[0] for previous, current in zip(windows, windows[1:])):
        raise ValueError(f"{label} windows must be sorted and disjoint")
    return tuple(windows)


def load_schedule_bytes(payload: bytes) -> Schedule:
    root = _mapping(
        yaml.load(payload.decode("utf-8"), Loader=_UniqueLoader),
        "schedule",
    )
    if (
        set(root) != _ROOT_KEYS
        or root["version"] != 2
        or type(root["version"]) is not int
    ):
        raise ValueError("schedule root contract is invalid")
    raw_budgets = _mapping(root["rate_budgets"], "schedule.rate_budgets")
    budgets: dict[str, RateBudget] = {}
    for raw_name, raw in raw_budgets.items():
        name = _text(raw_name, "rate budget name")
        value = _mapping(raw, f"rate budget {name}")
        allowed = {
            "account_requests_per_run",
            "provider_requests_per_run",
            "api_requests_per_run",
            "api_overrides",
        }
        if not {
            "account_requests_per_run",
            "provider_requests_per_run",
            "api_requests_per_run",
        } <= set(value) or not set(value) <= allowed:
            raise ValueError("rate budget keys are invalid")
        overrides_raw = value.get("api_overrides") or {}
        overrides = _mapping(
            overrides_raw, f"rate budget {name}.api_overrides"
        )
        normalized_overrides: dict[str, int] = {}
        for raw_api, raw_limit in overrides.items():
            api_name = _text(
                raw_api, f"rate budget {name}.api_overrides key"
            )
            normalized_overrides[api_name] = _integer(
                raw_limit,
                f"rate budget {name}.api_overrides.{api_name}",
                positive=True,
            )
        budgets[name] = RateBudget(
            _integer(
                value["account_requests_per_run"],
                "account_requests_per_run",
                positive=True,
            ),
            _integer(
                value["provider_requests_per_run"],
                "provider_requests_per_run",
                positive=True,
            ),
            _integer(
                value["api_requests_per_run"],
                "api_requests_per_run",
                positive=True,
            ),
            MappingProxyType(normalized_overrides),
        )
    raw_cadences = _mapping(root["cadences"], "schedule.cadences")
    if set(raw_cadences) != CADENCE_CLASSES:
        raise ValueError("schedule must declare the eight cadence classes")
    cadences: dict[str, CadencePolicy] = {}
    for name, raw in raw_cadences.items():
        value = _mapping(raw, f"cadence {name}")
        if not _REQUIRED_CADENCE_KEYS <= set(value) <= _CADENCE_KEYS:
            raise ValueError(f"cadence {name} keys are invalid")
        raw_calendar = value["calendar"]
        calendar = None
        if raw_calendar is not None:
            item = _mapping(raw_calendar, f"cadence {name}.calendar")
            required_calendar_keys = {
                "dataset_id",
                "date_field",
                "open_field",
                "open_values",
            }
            allowed_calendar_keys = required_calendar_keys | {
                "previous_open_date_field"
            }
            if not required_calendar_keys <= set(item) <= allowed_calendar_keys:
                raise ValueError("calendar keys are invalid")
            open_values = item["open_values"]
            if type(open_values) is not list or not open_values:
                raise ValueError("calendar.open_values must be non-empty")
            calendar = CalendarPolicy(
                _text(item["dataset_id"], "calendar.dataset_id"),
                _text(item["date_field"], "calendar.date_field"),
                _text(item["open_field"], "calendar.open_field"),
                tuple(open_values),
                (
                    _text(
                        item["previous_open_date_field"],
                        "calendar.previous_open_date_field",
                    )
                    if item.get("previous_open_date_field") is not None
                    else None
                ),
            )
        retry_value = _mapping(value["retry"], f"cadence {name}.retry")
        if set(retry_value) != {
            "max_attempts",
            "base_delay_seconds",
            "max_delay_seconds",
            "jitter_seconds",
        }:
            raise ValueError("retry keys are invalid")
        retry = RetryPolicy(
            _integer(retry_value["max_attempts"], "retry.max_attempts", positive=True),
            _integer(retry_value["base_delay_seconds"], "retry.base_delay_seconds"),
            _integer(retry_value["max_delay_seconds"], "retry.max_delay_seconds"),
            _integer(retry_value["jitter_seconds"], "retry.jitter_seconds"),
        )
        if retry.max_delay_seconds < retry.base_delay_seconds:
            raise ValueError("retry delay is invalid")
        weekdays = value["weekdays"]
        if (
            type(weekdays) is not list
            or not weekdays
            or any(type(day) is not int or not 1 <= day <= 7 for day in weekdays)
        ):
            raise ValueError("weekdays are invalid")
        start_policy = _text(value["backfill_start_policy"], "backfill_start_policy")
        start_date = _day(value["backfill_start_date"], "backfill_start_date")
        lookback = _integer(value["backfill_lookback_days"], "backfill_lookback_days")
        if start_policy not in {"rolling_days", "fixed_date", "none"}:
            raise ValueError("backfill_start_policy is invalid")
        if start_policy == "rolling_days" and lookback == 0:
            raise ValueError("rolling backfill requires lookback")
        if (start_policy == "fixed_date") != (start_date is not None):
            raise ValueError("fixed backfill start is inconsistent")
        automatic = value["automatic"]
        if type(automatic) is not bool:
            raise ValueError("automatic must be boolean")
        incremental = _text(value["incremental_mode"], "incremental_mode")
        frequency = _text(value["partition_frequency"], "partition_frequency")
        if incremental not in {
            "request_shape",
            "append",
            "on_demand",
        } or frequency not in {
            "session",
            "open_day",
            "day",
            "week",
            "month",
            "quarter",
            "event",
            "none",
        }:
            raise ValueError("incremental partition policy is invalid")
        if automatic == (incremental == "on_demand") or (
            incremental == "on_demand"
        ) != (frequency == "none"):
            raise ValueError("automatic/on-demand policy is inconsistent")
        rate_class = _text(value["rate_budget_class"], "rate_budget_class")
        if rate_class not in budgets:
            raise ValueError("rate budget class is unknown")
        session_windows = _session_windows(
            value.get("session_windows_local"), "session_windows_local"
        )
        if session_windows and (name != "session_minute" or calendar is None):
            raise ValueError("session windows require session_minute calendar cadence")
        cadences[name] = CadencePolicy(
            automatic,
            _clock(value["availability_after_local"], "availability_after_local"),
            session_windows,
            tuple(sorted(set(weekdays))),
            incremental,
            frequency,
            calendar,
            _integer(
                value["minimum_interval_seconds"],
                "minimum_interval_seconds",
                positive=True,
            ),
            _integer(
                value["failure_retry_seconds"], "failure_retry_seconds", positive=True
            ),
            _integer(value["correction_overlap_days"], "correction_overlap_days"),
            _integer(value["correction_overlap_bars"], "correction_overlap_bars"),
            start_policy,
            lookback,
            start_date,
            _integer(
                value["backfill_chunk_span_days"],
                "backfill_chunk_span_days",
                positive=True,
            ),
            _integer(value["future_horizon_days"], "future_horizon_days"),
            _integer(
                value["max_backfill_chunks_per_run"],
                "max_backfill_chunks_per_run",
                positive=True,
            ),
            rate_class,
            retry,
        )
    return Schedule(
        _integer(
            root["dataset_timeout_seconds"], "dataset_timeout_seconds", positive=True
        ),
        MappingProxyType(dict(sorted(budgets.items()))),
        MappingProxyType(dict(sorted(cadences.items()))),
    )


def load_schedule(path: Path) -> Schedule:
    return load_schedule_bytes(Path(path).read_bytes())


class _DuplicateKey(ValueError):
    pass


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _partition(value: object) -> date:
    if type(value) is not str:
        raise ValueError
    parsed = datetime.strptime(value, "%Y%m%d").date()
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError
    return parsed


def _fact_partition_format(binding: ProviderBinding) -> str | None:
    policy = binding.request_window_policy
    completeness = binding.response_completeness
    if policy is None or completeness is None:
        return None
    key = completeness.request_partition_key
    return policy.formats.get(key)


def _month_anchor(value: object) -> date:
    if type(value) is not str:
        raise ValueError
    parsed = datetime.strptime(value, "%Y%m").date()
    if parsed.strftime("%Y%m") != value:
        raise ValueError
    return date(parsed.year, parsed.month, 1)


def _fact_partition(value: object, binding: ProviderBinding) -> date:
    """Parse a retained fact partition using its declared request format."""
    if _fact_partition_format(binding) == "yyyymm":
        return _month_anchor(value)
    return _partition(value)


def _planning_anchor(day: date, binding: ProviderBinding) -> date:
    if _fact_partition_format(binding) == "yyyymm":
        return date(day.year, day.month, 1)
    return day


def _active_binding(dataset: DatasetDefinition) -> ProviderBinding:
    bindings = tuple(
        item
        for item in dataset.provider_bindings
        if item.entitlement_state == "active" and item.activation_state == "active"
    )
    if len(bindings) != 1:
        raise ValueError("scheduled dataset requires one active binding")
    return bindings[0]


def load_planner_state(
    db_path: Path,
    registry: DatasetRegistry,
    *,
    now: datetime,
    calendar_dataset_ids: frozenset[str] | None = None,
) -> PlannerState:
    """Load only the fact material needed to plan one schedule run.

    All datasets need their validated receipt history and partition values.
    Provider payloads are only needed to derive an exchange calendar; avoiding
    payload JSON hydration for every other historical fact keeps the common
    automatic run bounded without changing scheduling semantics.
    ``None`` preserves the complete-fact behaviour for direct callers.
    """

    if calendar_dataset_ids is not None and any(
        type(dataset_id) is not str or not dataset_id
        for dataset_id in calendar_dataset_ids
    ):
        raise ValueError("calendar_dataset_ids must contain non-empty strings")
    datasets = {
        item.dataset_id: item
        for item in registry.datasets
        if item.read_model_adapter.storage_kind == "provider_native_rows"
    }
    receipts: dict[tuple[str, str], list[ValidatedReceiptHistoryEntry]] = defaultdict(
        list
    )
    facts: dict[tuple[str, str], list[_Fact]] = defaultdict(list)
    try:
        invalid_datasets: dict[tuple[str, str], tuple[str, ...]] = {}
        with open_verified_read_model_snapshot(db_path) as conn:
            histories = validated_receipt_histories_by_dataset(
                conn, registry, now=now
            )
            for dataset_id, reasons in histories.failures_by_dataset.items():
                dataset = datasets.get(dataset_id)
                if dataset is None:
                    continue
                try:
                    binding = _active_binding(dataset)
                except ValueError:
                    continue
                invalid_datasets[(dataset_id, binding.provider)] = reasons
            for entries in histories.entries_by_dataset.values():
                for receipt in entries:
                    dataset = datasets.get(receipt.dataset_id)
                    if dataset is None:
                        continue
                    try:
                        binding = _active_binding(dataset)
                    except ValueError:
                        continue
                    if (
                        receipt.provider != binding.provider
                        or receipt.config_hash != provider_ingest_config_hash(dataset, binding)
                    ):
                        continue
                    receipts[(receipt.dataset_id, receipt.provider)].append(receipt)
            for dataset in datasets.values():
                try:
                    binding = _active_binding(dataset)
                except ValueError:
                    continue
                key = (dataset.dataset_id, binding.provider)
                success_ids = {
                    item.receipt_id
                    for item in receipts[key]
                    if item.status == "success" and item.cohort_status == "success"
                }
                hydrate_payload = (
                    calendar_dataset_ids is None
                    or dataset.dataset_id in calendar_dataset_ids
                )
                columns = (
                    "partition_value, payload_json, receipt_id"
                    if hydrate_payload
                    else "DISTINCT partition_value, receipt_id"
                )
                for row in conn.execute(
                    f"SELECT {columns} FROM provider_dataset_rows "
                    "WHERE dataset_id=? AND provider=? AND schema_major=?",
                    (dataset.dataset_id, binding.provider, dataset.schema_major),
                ):
                    if hydrate_payload:
                        partition_value, payload_json, receipt_id = row
                    else:
                        partition_value, receipt_id = row
                    if receipt_id not in success_ids:
                        continue
                    if partition_value is not None and type(partition_value) is not str:
                        raise RuntimeError("provider-native fact authority is invalid")
                    if not hydrate_payload:
                        facts[key].append(
                            _Fact(partition_value, MappingProxyType({}), receipt_id)
                        )
                        continue
                    try:
                        payload = json.loads(
                            payload_json, object_pairs_hook=_json_pairs
                        )
                    except (
                        json.JSONDecodeError,
                        TypeError,
                        ValueError,
                        _DuplicateKey,
                    ) as exc:
                        raise RuntimeError(
                            "provider-native fact authority is invalid"
                        ) from exc
                    if type(payload) is not dict:
                        raise RuntimeError("provider-native fact authority is invalid")
                    facts[key].append(
                        _Fact(partition_value, MappingProxyType(payload), receipt_id)
                    )
    except RuntimeProjectionError as exc:
        raise RuntimeError("provider-native planner authority is unavailable") from exc
    keys = set(receipts) | set(facts)
    return PlannerState(
        MappingProxyType(
            {
                key: _DatasetState(tuple(receipts[key]), tuple(facts[key]))
                for key in keys
            }
        ),
        MappingProxyType(dict(sorted(invalid_datasets.items()))),
    )


def _latest_available(now: datetime, policy: CadencePolicy) -> date:
    if policy.availability_after_local is None:
        raise ValueError("automatic cadence requires availability")
    day = now.date() - timedelta(
        days=now.timetz().replace(tzinfo=None) < policy.availability_after_local
    )
    while day.isoweekday() not in policy.weekdays:
        day -= timedelta(days=1)
    return day


def _session_window_state(
    registry: DatasetRegistry,
    state: PlannerState,
    now: datetime,
    policy: CadencePolicy,
    local_now: datetime,
) -> str | None:
    """Return a fail-closed skip state outside a declared intraday session."""

    if not policy.session_windows_local:
        return None
    clock = local_now.timetz().replace(tzinfo=None, second=0, microsecond=0)
    if not any(start <= clock <= end for start, end in policy.session_windows_local):
        return "not_due"
    calendar = _calendar(registry, state, policy)
    if calendar is None or local_now.date() not in calendar:
        return "calendar_unavailable"
    if calendar[local_now.date()] is not True:
        return "not_due"
    return None


def _calendar(
    registry: DatasetRegistry, state: PlannerState, policy: CadencePolicy
) -> Mapping[date, bool] | None:
    if policy.calendar is None:
        return None
    dataset = registry.resolve(policy.calendar.dataset_id)
    binding = _active_binding(dataset)
    result: dict[date, bool] = {}
    previous_open_by_closed_day: dict[date, set[date | None]] = defaultdict(set)
    for fact in state.get(dataset, binding).facts:
        day = _partition(
            fact.payload.get(policy.calendar.date_field, fact.partition_value)
        )
        if fact.partition_value is not None and _partition(fact.partition_value) != day:
            raise RuntimeError("calendar partition is inconsistent")
        opened = (
            fact.payload.get(policy.calendar.open_field) in policy.calendar.open_values
        )
        if day in result and result[day] != opened:
            raise RuntimeError("calendar session is conflicting")
        result[day] = opened
        if policy.calendar.previous_open_date_field is not None and not opened:
            raw_prior = fact.payload.get(policy.calendar.previous_open_date_field)
            if raw_prior is None:
                previous_open_by_closed_day[day].add(None)
                continue
            try:
                prior = _partition(raw_prior)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("calendar previous session is invalid") from exc
            if prior >= day:
                raise RuntimeError("calendar previous session is invalid")
            previous_open_by_closed_day[day].add(prior)
    prior_open_days: set[date] = set()
    missing_previous_days: set[date] = set()
    for day, values in previous_open_by_closed_day.items():
        if len(values) != 1:
            raise RuntimeError("calendar previous session is conflicting")
        prior = next(iter(values))
        if prior is None:
            missing_previous_days.add(day)
        else:
            prior_open_days.add(prior)
    closed_days = tuple(day for day, opened in result.items() if not opened)
    if closed_days and max(closed_days) in missing_previous_days:
        raise RuntimeError("calendar previous session is missing")
    for prior in prior_open_days:
        existing = result.get(prior)
        if existing is False:
            raise RuntimeError("calendar previous session is conflicting")
        result.setdefault(prior, True)
    return MappingProxyType(result)


def _desired(
    start: date, end: date, policy: CadencePolicy, calendar: Mapping[date, bool] | None
) -> tuple[date, ...]:
    days = tuple(
        start + timedelta(days=i) for i in range(max(0, (end - start).days + 1))
    )
    if policy.partition_frequency in {"session", "open_day"}:
        if calendar is None:
            raise ValueError("open-session cadence requires calendar")
        return tuple(day for day in days if calendar.get(day) is True)
    if policy.partition_frequency in {"day", "event"}:
        return days
    eligible = (
        tuple(day for day in days if calendar.get(day) is True)
        if calendar is not None
        else days
    )
    grouped: dict[tuple[int, ...], date] = {}
    for day in eligible:
        if policy.partition_frequency == "week":
            iso = day.isocalendar()
            key = (iso.year, iso.week)
        elif policy.partition_frequency == "month":
            key = (day.year, day.month)
        elif policy.partition_frequency == "quarter":
            key = (day.year, (day.month - 1) // 3)
        else:
            raise ValueError("partition frequency is invalid")
        grouped[key] = max(day, grouped.get(key, day))
    return tuple(sorted(grouped.values()))


def _window_dates(
    binding: ProviderBinding, window: Mapping[str, str]
) -> tuple[date, ...]:
    policy = binding.request_window_policy
    if policy is None or set(window) != set(policy.required_keys):
        return ()
    try:
        return request_window_covered_dates(policy, window)
    except (KeyError, TypeError, ValueError):
        return ()


def _latest(
    receipts: Sequence[ValidatedReceiptHistoryEntry],
    window: Mapping[str, str] | None = None,
) -> _ReceiptCohort | None:
    grouped: dict[str, list[ValidatedReceiptHistoryEntry]] = defaultdict(list)
    for receipt in receipts:
        if window is None or dict(receipt.request_window) == dict(window):
            grouped[receipt.execution_id].append(receipt)
    items: list[_ReceiptCohort] = []
    for execution_id, members in grouped.items():
        statuses = {member.cohort_status for member in members}
        windows = {
            _canonical_json(dict(member.request_window)) for member in members
        }
        started = {member.started_at for member in members}
        if len(statuses) != 1 or len(windows) != 1 or len(started) != 1:
            raise RuntimeError("provider-native receipt cohort is inconsistent")
        items.append(
            _ReceiptCohort(
                execution_id=execution_id,
                status=next(iter(statuses)),
                started_at=next(iter(started)),
                finished_at=max(member.finished_at for member in members),
                request_window=members[0].request_window,
                receipt_ids=frozenset(member.receipt_id for member in members),
                success_receipt_ids=frozenset(
                    member.receipt_id
                    for member in members
                    if member.status == "success"
                ),
            )
        )
    return max(
        items,
        key=lambda item: (item.started_at, item.execution_id, item.finished_at),
        default=None,
    )


def _resumable_window_completed_at(
    receipts: Sequence[ValidatedReceiptHistoryEntry],
    *,
    registry: DatasetRegistry,
    state: PlannerState,
    now: datetime,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    request_window: Mapping[str, str],
) -> datetime | None:
    """Return completion time only for one exact, variant-complete v2 window."""

    if binding.resumable_fanout is None:
        return None
    config_hash = provider_ingest_config_hash(dataset, binding)
    candidates = tuple(
        item
        for item in receipts
        if (
            item.dataset_id == dataset.dataset_id
            and item.provider == binding.provider
            and item.config_hash == config_hash
            and dict(item.request_window) == dict(request_window)
            and item.cursor_contract_version == 2
            and item.frozen_universe_sha256 is not None
            and item.batch_index is not None
            and item.batch_count is not None
            and item.batch_values_sha256 is not None
        )
    )
    if not candidates:
        return None
    universes = {item.frozen_universe_sha256 for item in candidates}
    counts = {item.batch_count for item in candidates}
    if len(universes) != 1 or len(counts) != 1:
        return None
    universe_sha = next(iter(universes))
    batch_count = next(iter(counts))
    if (
        type(universe_sha) is not str
        or not _SHA256.fullmatch(universe_sha)
        or type(batch_count) is not int
        or batch_count <= 0
    ):
        return None
    fanout = binding.fanout
    if (
        fanout is None
        or fanout.strategy not in {"literal_values", "dataset_field"}
        or fanout.parameter is None
        or fanout.batch_size is None
    ):
        return None
    try:
        from collectors.tushare.provider_native_ingest import _stable_fanout_batches

        if fanout.strategy == "literal_values":
            values = fanout.values
        else:
            if fanout.source_dataset_id is None or fanout.source_field is None:
                return None
            source = registry.resolve(fanout.source_dataset_id)
            source_binding = next(
                (
                    item
                    for item in source.provider_bindings
                    if item.provider == binding.provider
                    and item.entitlement_state == "active"
                    and item.activation_state == "active"
                ),
                None,
            )
            if source_binding is None:
                return None
            source_facts = state.get(source, source_binding).facts
            source_field = next(
                (field for field in source.fields if field.name == fanout.source_field),
                None,
            )
            if source_field is None:
                return None
            cutoff = None
            if fanout.source_date_lte_days is not None:
                cutoff = now.astimezone(ZoneInfo(source.timezone)).date() - timedelta(
                    days=fanout.source_date_lte_days
                )
            values_list: list[RequestScalar] = []
            for fact in source_facts:
                if any(fact.payload.get(key) != value for key, value in fanout.source_equals):
                    continue
                if cutoff is not None:
                    if fanout.source_date_field is None:
                        return None
                    raw_date = fact.payload.get(fanout.source_date_field)
                    if type(raw_date) is not str or len(raw_date) != 8 or not raw_date.isdigit():
                        return None
                    try:
                        listed = datetime.strptime(raw_date, "%Y%m%d").date()
                    except ValueError:
                        return None
                    if listed > cutoff:
                        continue
                value = fact.payload.get(fanout.source_field)
                if source_field.logical_type == "text":
                    valid = type(value) is str and bool(value)
                elif source_field.logical_type == "integer":
                    valid = type(value) is int
                else:
                    valid = type(value) in {int, float} and (
                        type(value) is not float or math.isfinite(value)
                    )
                if not valid:
                    return None
                values_list.append(value)
            if fanout.max_values is not None:
                values_list = values_list[: fanout.max_values]
            values = tuple(values_list)
        expected_batches = _stable_fanout_batches(
            values,
            parameter=fanout.parameter,
            batch_size=fanout.batch_size,
            max_values=fanout.max_values,
            source_order=fanout.source_order,
            resumable=True,
        )
    except (TypeError, ValueError):
        return None
    if not expected_batches or len(expected_batches) != batch_count:
        return None
    if expected_batches[0].frozen_universe_sha256 != universe_sha:
        return None
    expected_variants = {
        _canonical_json(dict(variant)) for variant in binding.request_variants
    }
    if not expected_variants:
        expected_variants = {_canonical_json({})}
    latest: dict[tuple[int, str, str], ValidatedReceiptHistoryEntry] = {}
    for item in candidates:
        assert item.batch_index is not None
        assert item.batch_values_sha256 is not None
        if not 0 <= item.batch_index < batch_count or not _SHA256.fullmatch(
            item.batch_values_sha256
        ):
            return None
        variant_key = _canonical_json(dict(item.request_variant))
        if variant_key not in expected_variants:
            return None
        identity = (item.batch_index, item.batch_values_sha256, variant_key)
        previous = latest.get(identity)
        key = (
            item.finished_at,
            item.retry_index if item.retry_index is not None else -1,
            item.physical_call_index if item.physical_call_index is not None else -1,
            item.receipt_id,
        )
        if previous is None or key > (
            previous.finished_at,
            previous.retry_index if previous.retry_index is not None else -1,
            previous.physical_call_index if previous.physical_call_index is not None else -1,
            previous.receipt_id,
        ):
            latest[identity] = item
    completed_at: list[datetime] = []
    for batch_index in range(batch_count):
        expected_values_sha = expected_batches[batch_index].batch_values_sha256
        if expected_values_sha is None:
            return None
        values = {
            values_sha
            for (index, values_sha, _variant), item in latest.items()
            if index == batch_index
        }
        if values != {expected_values_sha}:
            return None
        values_sha = next(iter(values))
        for variant_key in expected_variants:
            item = latest.get((batch_index, values_sha, variant_key))
            if item is None or item.status not in {"success", "empty"}:
                return None
            completed_at.append(item.finished_at)
    return max(completed_at)


def _chunks(days: Sequence[date], span: int) -> tuple[tuple[date, date], ...]:
    if not days:
        return ()
    result: list[tuple[date, date]] = []
    start = previous = min(days)
    for day in sorted(set(days))[1:]:
        if day != previous + timedelta(days=1) or (day - start).days + 1 > span:
            result.append((start, previous))
            start = day
        previous = day
    result.append((start, previous))
    return tuple(result)


def _window(binding: ProviderBinding, start: date, end: date) -> Mapping[str, str]:
    policy = binding.request_window_policy
    if policy is None:
        return MappingProxyType({})
    if end < start:
        raise ValueError("request range start must not exceed range end")
    if policy.range_start_key == policy.range_end_key:
        if start != end:
            raise ValueError("single-partition request cannot span dates")
        key = policy.range_start_key
        window = {
            key: encode_request_window_value(start, policy.formats[key]),
        }
        return MappingProxyType(normalize_request_window(policy, window))
    if (end - start).days + 1 > policy.max_span_days:
        raise ValueError("request exceeds registry span")
    start_format = policy.formats[policy.range_start_key]
    if start_format == "local_datetime_seconds":
        # Date-based planning covers whole calendar days; a datetime-ranged
        # contract expresses the same planned span as local day boundaries
        # (e.g. the news flash window "YYYY-MM-DD 00:00:00" .. "23:59:59").
        end_format = policy.formats[policy.range_end_key]
        if end_format != "local_datetime_seconds":
            raise ValueError(
                "automatic local_datetime_seconds ranges require an explicit window"
            )
        window = {
            policy.range_start_key: encode_request_window_value(
                start, start_format
            ),
            policy.range_end_key: encode_request_window_value(
                datetime.combine(end, time(23, 59, 59), tzinfo=timezone.utc),
                end_format,
            ),
        }
        return MappingProxyType(normalize_request_window(policy, window))
    window = {
        policy.range_start_key: encode_request_window_value(start, start_format),
        policy.range_end_key: encode_request_window_value(
            end, policy.formats[policy.range_end_key]
        ),
    }
    return MappingProxyType(normalize_request_window(policy, window))


def _runs(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    policy: CadencePolicy,
    window: Mapping[str, str],
    priority: str,
) -> tuple[ScheduledRun, ...]:
    identity = _canonical_json(
        {
            "dataset_id": dataset.dataset_id,
            "provider": binding.provider,
            "provider_api": binding.api_name,
            "variants": [dict(variant) for variant in binding.request_variants],
            "window": dict(window),
        }
    )
    jitter = (
        0
        if policy.retry.jitter_seconds == 0
        else int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
        % (policy.retry.jitter_seconds + 1)
    )
    return (
        ScheduledRun(
            dataset_id=dataset.dataset_id,
            provider=binding.provider,
            provider_api=binding.api_name,
            cadence_class=dataset.cadence_class,
            request_window=window,
            priority=priority,
            request_variants=tuple(binding.request_variants),
            rate_budget_class=policy.rate_budget_class,
            retry=policy.retry,
            retry_jitter_seconds=jitter,
            resumable_fanout=binding.resumable_fanout,
        ),
    )


def _dataset_plans(
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    policy: CadencePolicy,
    state: PlannerState,
    now: datetime,
    current_only: bool,
) -> tuple[tuple[ScheduledRun, ...], str]:
    current = state.get(dataset, binding)
    now_utc = now.astimezone(timezone.utc)
    local_now = now.astimezone(ZoneInfo(dataset.timezone))
    session_state = _session_window_state(registry, state, now, policy, local_now)
    if session_state is not None:
        return (), session_state
    if binding.request_window_policy is None:
        latest = _latest(current.receipts, {})
        if latest is not None:
            age = (now_utc - latest.finished_at).total_seconds()
            healthy = latest.status == "empty" or any(
                fact.receipt_id in latest.success_receipt_ids
                for fact in current.facts
            )
            if (latest.status == "failed" and age < policy.failure_retry_seconds) or (
                latest.status != "failed"
                and healthy
                and age < policy.minimum_interval_seconds
            ):
                return (), "not_due"
        return _runs(
            dataset, binding, policy, MappingProxyType({}), "current"
        ), "planned"
    available = _latest_available(local_now, policy)
    # The registry, not a dataset name or provider API branch, declares the
    # bounded known-future window.  Its value is capped by the cadence policy;
    # ordinary datasets therefore remain at the current available date.
    future_horizon_days = min(
        dataset.known_future_horizon_days, policy.future_horizon_days
    )
    start = (
        available - timedelta(days=policy.backfill_lookback_days - 1)
        if policy.backfill_start_policy == "rolling_days"
        else policy.backfill_start_date or available
    )
    end = available + timedelta(days=future_horizon_days)
    calendar = _calendar(registry, state, policy)
    desired = tuple(
        _planning_anchor(day, binding)
        for day in _desired(start, end, policy, calendar)
    )
    if policy.calendar is not None and not calendar:
        return (), "calendar_unavailable"
    covered = {
        _fact_partition(fact.partition_value, binding)
        for fact in current.facts
        if fact.partition_value is not None
    }
    execution_ids = {receipt.execution_id for receipt in current.receipts}
    for execution_id in execution_ids:
        members = tuple(
            receipt
            for receipt in current.receipts
            if receipt.execution_id == execution_id
        )
        cohort = _latest(members)
        # A resumable fanout window is covered only by the exact v2
        # batch/variant completion check below.  One valid-empty physical
        # batch must not make the entire request window appear covered.
        if (
            cohort is not None
            and cohort.status == "empty"
            and binding.resumable_fanout is None
        ):
            covered.update(_window_dates(binding, cohort.request_window))
    missing = set(desired) - covered
    overlap: set[date] = (
        set(desired[-policy.correction_overlap_bars :])
        if policy.correction_overlap_bars
        else set()
    )
    if policy.correction_overlap_days:
        overlap.update(
            day
            for day in desired
            if day >= available - timedelta(days=policy.correction_overlap_days - 1)
        )
    needed = missing | overlap
    current_days = {
        day
        for day in needed
        if day >= _planning_anchor(available, binding)
        and (future_horizon_days or day == _planning_anchor(available, binding))
    }
    backfill_days = missing - current_days
    correction_days = overlap - missing - current_days
    window_policy = binding.request_window_policy
    span = min(policy.backfill_chunk_span_days, window_policy.max_span_days, 366)
    current_chunks = _chunks(tuple(current_days), span)
    deferred = []
    if not current_only:
        deferred = (
            [("backfill", *chunk) for chunk in _chunks(tuple(backfill_days), span)]
            + [("correction", *chunk) for chunk in _chunks(tuple(correction_days), span)]
        )[: policy.max_backfill_chunks_per_run]
    demands = [("current", *chunk) for chunk in current_chunks] + deferred
    plans: list[ScheduledRun] = []
    suppressed = False
    for priority, chunk_start, chunk_end in demands:
        request_window = _window(binding, chunk_start, chunk_end)
        prior = _latest(current.receipts, request_window)
        resumable_finished = _resumable_window_completed_at(
            current.receipts,
            registry=registry,
            state=state,
            now=now,
            dataset=dataset,
            binding=binding,
            request_window=request_window,
        )
        if resumable_finished is not None:
            continue
        correction_only = not any(
            day in missing for day in _window_dates(binding, request_window)
        )
        if prior is not None:
            age = (now_utc - prior.finished_at).total_seconds()
            if (prior.status == "failed" and age < policy.failure_retry_seconds) or (
                correction_only and age < policy.minimum_interval_seconds
            ):
                suppressed = True
                continue
        plans.extend(_runs(dataset, binding, policy, request_window, priority))
    return (
        (tuple(plans), "planned")
        if plans
        else ((), "not_due" if suppressed else "up_to_date")
    )


def plan_runs(
    *,
    registry: DatasetRegistry,
    schedule: Schedule,
    state: PlannerState,
    now: datetime,
    selected_dataset_ids: frozenset[str] | None = None,
    current_only: bool = False,
) -> tuple[tuple[ScheduledRun, ...], tuple[PlannerSkip, ...]]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    candidates: list[ScheduledRun] = []
    skips: list[PlannerSkip] = []
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        if dataset.read_model_adapter.storage_kind != "provider_native_rows":
            continue
        try:
            binding = _active_binding(dataset)
        except ValueError:
            for item in dataset.provider_bindings:
                skips.append(
                    PlannerSkip(
                        dataset.dataset_id,
                        item.provider,
                        "paused"
                        if item.activation_state != "active"
                        else "not_entitled",
                    )
                )
            continue
        if (
            selected_dataset_ids is not None
            and dataset.dataset_id not in selected_dataset_ids
        ):
            skips.append(
                PlannerSkip(dataset.dataset_id, binding.provider, "not_selected")
            )
            continue
        if state.invalid_reasons(dataset, binding):
            skips.append(
                PlannerSkip(dataset.dataset_id, binding.provider, "invalid_receipt_authority")
            )
            continue
        try:
            policy = schedule.cadences[dataset.cadence_class]
        except KeyError as exc:
            raise ValueError("active dataset cadence is not scheduled") from exc
        if not policy.automatic:
            skips.append(PlannerSkip(dataset.dataset_id, binding.provider, "on_demand"))
            continue
        plans, status = _dataset_plans(
            registry,
            dataset,
            binding,
            policy,
            state,
            now,
            current_only,
        )
        if plans:
            candidates.extend(plans)
        else:
            skips.append(PlannerSkip(dataset.dataset_id, binding.provider, status))
    account: dict[str, int] = defaultdict(int)
    provider: dict[tuple[str, str], int] = defaultdict(int)
    api: dict[tuple[str, str, str], int] = defaultdict(int)
    accepted: list[ScheduledRun] = []
    for _, plan in sorted(
        enumerate(candidates),
        key=lambda item: (*_execution_order(item[1]), item[0]),
    ):
        budget = schedule.rate_budgets[plan.rate_budget_class]
        provider_key = (plan.rate_budget_class, plan.provider)
        api_key = (plan.rate_budget_class, plan.provider, plan.provider_api)
        api_limit = budget.api_overrides.get(
            plan.provider_api, budget.api_requests_per_run
        )
        if (
            account[plan.rate_budget_class] >= budget.account_requests_per_run
            or provider[provider_key] >= budget.provider_requests_per_run
            or api[api_key] >= api_limit
        ):
            skips.append(PlannerSkip(plan.dataset_id, plan.provider, "rate_budget"))
            continue
        account[plan.rate_budget_class] += 1
        provider[provider_key] += 1
        api[api_key] += 1
        accepted.append(plan)
    return tuple(accepted), tuple(skips)
