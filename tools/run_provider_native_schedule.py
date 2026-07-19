#!/usr/bin/env python3
"""Run every due provider-native binding from the trusted runtime registry.

This scheduler owns no dataset or provider API list.  Cadence timing lives in
``config/provider_native_schedule.yaml``; request parameter names and bounds
remain owned by the process-selected dataset registry.  Plan mode is the safe
default.  ``--execute`` is intended for the reviewed systemd oneshot unit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType
from typing import Callable, Iterator, Mapping
from urllib.parse import urlsplit
import uuid
from zoneinfo import ZoneInfo

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    DatasetRegistry,
    ProviderBinding,
    load_runtime_dataset_registry,
)
from runtime_paths import marketdata_sqlite_path  # noqa: E402
from storage.receipt_projection import (  # noqa: E402
    RuntimeProjectionError,
    load_interface_runtime_report,
)


DEFAULT_SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
DEFAULT_LOCK_PATH = Path("/run/sharedsignals/provider-native-collect.lock")
_ROOT_KEYS = frozenset({"version", "dataset_timeout_seconds", "cadences"})
_CADENCE_KEYS = frozenset(
    {
        "minimum_interval_seconds",
        "failure_retry_seconds",
        "not_before_local",
        "partition_offset_days",
        "range_days",
        "weekdays",
    }
)
_TERMINAL_STATES = frozenset({"success", "empty", "validation", "failed"})
_SUCCESS_STATES = frozenset({"success", "empty"})
_STATE_EXIT_CODES = {"success": 0, "empty": 3, "validation": 2, "failed": 4}
_RUNNER_RESULT_KEYS = frozenset(
    {
        "counts",
        "dataset_id",
        "error_codes",
        "mode",
        "provider",
        "provider_api",
        "receipt_count",
        "state",
    }
)
_RUNNER_COUNT_KEYS = frozenset(
    {
        "committed",
        "inserted",
        "rejected",
        "returned",
        "unchanged",
        "updated",
        "validated",
    }
)
_FORBIDDEN_COLLECTOR_CREDENTIALS = frozenset(
    {
        "QUICKSYNC_API_TOKEN",
        "QUICKSYNC_URL",
        "SHAREDSIGNALS_INTERNAL_V1_TOKEN",
        "TUSHARE_API_TOKEN",
        "TUSHARE_API_URL",
        "TUSHARE_MCP_URL",
        "TUSHARE_TOKEN",
    }
)


class ScheduleBusyError(RuntimeError):
    """Another reviewed scheduler instance owns the global collection lock."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("schedule YAML contains a duplicate key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class CadencePolicy:
    minimum_interval_seconds: int
    failure_retry_seconds: int
    not_before_local: time
    partition_offset_days: int
    range_days: int
    weekdays: tuple[int, ...]


@dataclass(frozen=True)
class Schedule:
    dataset_timeout_seconds: int
    cadences: Mapping[str, CadencePolicy]


@dataclass(frozen=True)
class ScheduledRun:
    dataset_id: str
    provider: str
    provider_api: str
    cadence_class: str
    request_window: Mapping[str, str]


@dataclass(frozen=True)
class LastTerminal:
    status: str
    finished_at: datetime


@dataclass(frozen=True)
class DatasetResult:
    dataset_id: str
    provider: str
    state: str
    exit_code: int


@dataclass(frozen=True)
class SkippedResult:
    dataset_id: str
    provider: str
    state: str


@dataclass(frozen=True)
class ScheduleResult:
    exit_code: int
    mode: str
    executed: tuple[DatasetResult, ...]
    skipped: tuple[SkippedResult, ...]

    def public_payload(self) -> dict[str, object]:
        planned = sum(item.state == "planned" for item in self.executed)
        terminal = len(self.executed) - planned
        return {
            "datasets": [
                {
                    "dataset_id": item.dataset_id,
                    "provider": item.provider,
                    "state": item.state,
                }
                for item in self.executed
            ],
            "mode": self.mode,
            "skipped": [
                {
                    "dataset_id": item.dataset_id,
                    "provider": item.provider,
                    "state": item.state,
                }
                for item in self.skipped
            ],
            "summary": {
                "failed": sum(
                    item.state not in _SUCCESS_STATES | {"planned"}
                    for item in self.executed
                ),
                "planned": planned,
                "skipped": len(self.skipped),
                "terminal": terminal,
            },
        }


def _mapping(value: object, label: str) -> dict[object, object]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a mapping")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _validated_collector_credentials() -> None:
    if any(os.environ.get(name) for name in _FORBIDDEN_COLLECTOR_CREDENTIALS):
        raise ValueError("collector credential source is not allowed")
    api_url = os.environ.get("QUICKSYNC_API_URL")
    token = os.environ.get("QUICKSYNC_TOKEN")
    if (
        type(api_url) is not str
        or not api_url
        or api_url != api_url.strip()
        or type(token) is not str
        or not token
        or token != token.strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in token)
    ):
        raise ValueError("collector credentials are unavailable")
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("collector API URL is invalid")


def _clock(value: object, label: str) -> time:
    if type(value) is not str or len(value) != 5 or value[2] != ":":
        raise ValueError(f"{label} must use HH:MM")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must use HH:MM") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError(f"{label} must use HH:MM")
    return parsed


def _weekdays(value: object, label: str) -> tuple[int, ...]:
    if type(value) is not list or not value:
        raise ValueError(f"{label} must be one non-empty list")
    result = tuple(value)
    if any(type(item) is not int or item < 1 or item > 7 for item in result):
        raise ValueError(f"{label} values must be ISO weekdays 1 through 7")
    if len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise ValueError(f"{label} must be sorted without duplicates")
    return result


def load_schedule(path: Path = DEFAULT_SCHEDULE_CONFIG) -> Schedule:
    raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    root = _mapping(raw, "schedule")
    if set(root) != _ROOT_KEYS:
        raise ValueError("schedule root keys must exactly match the contract")
    if root["version"] != 1 or type(root["version"]) is not int:
        raise ValueError("schedule.version must be integer 1")
    timeout = _positive_int(
        root["dataset_timeout_seconds"], "schedule.dataset_timeout_seconds"
    )
    raw_cadences = _mapping(root["cadences"], "schedule.cadences")
    if not raw_cadences:
        raise ValueError("schedule.cadences must not be empty")
    cadences: dict[str, CadencePolicy] = {}
    for raw_name, raw_policy in raw_cadences.items():
        if type(raw_name) is not str or not raw_name or raw_name != raw_name.strip():
            raise ValueError("cadence name must be non-empty canonical text")
        policy = _mapping(raw_policy, f"schedule.cadences.{raw_name}")
        if set(policy) != _CADENCE_KEYS:
            raise ValueError(f"schedule cadence {raw_name} keys are invalid")
        cadences[raw_name] = CadencePolicy(
            minimum_interval_seconds=_positive_int(
                policy["minimum_interval_seconds"],
                f"schedule.cadences.{raw_name}.minimum_interval_seconds",
            ),
            failure_retry_seconds=_positive_int(
                policy["failure_retry_seconds"],
                f"schedule.cadences.{raw_name}.failure_retry_seconds",
            ),
            not_before_local=_clock(
                policy["not_before_local"],
                f"schedule.cadences.{raw_name}.not_before_local",
            ),
            partition_offset_days=_nonnegative_int(
                policy["partition_offset_days"],
                f"schedule.cadences.{raw_name}.partition_offset_days",
            ),
            range_days=_positive_int(
                policy["range_days"],
                f"schedule.cadences.{raw_name}.range_days",
            ),
            weekdays=_weekdays(
                policy["weekdays"],
                f"schedule.cadences.{raw_name}.weekdays",
            ),
        )
    return Schedule(
        dataset_timeout_seconds=timeout,
        cadences=MappingProxyType(dict(sorted(cadences.items()))),
    )


def _parse_timestamp(value: object) -> datetime:
    if type(value) is not str or not value:
        raise ValueError("receipt timestamp is invalid")
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("receipt timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _read_last_finished_at(
    db_path: Path,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> Mapping[str, LastTerminal]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduler clock must include timezone")
    try:
        report = load_interface_runtime_report(db_path, registry, now=now)
    except RuntimeProjectionError as exc:
        raise RuntimeError("provider-native receipt authority is unavailable") from exc
    datasets = report.get("datasets")
    if type(datasets) is not dict:
        raise RuntimeError("provider-native receipt projection is invalid")
    latest: dict[str, LastTerminal] = {}
    now_utc = now.astimezone(timezone.utc)
    for dataset in registry.datasets:
        if dataset.read_model_adapter.storage_kind != "provider_native_rows":
            continue
        if not any(
            binding.entitlement_state == "active"
            and binding.activation_state == "active"
            for binding in dataset.provider_bindings
        ):
            continue
        row = datasets.get(dataset.dataset_id)
        if type(row) is not dict or row.get("dataset_id") != dataset.dataset_id:
            raise RuntimeError("provider-native receipt projection identity is invalid")
        state = row.get("state")
        if state in {"unobserved", "paused"}:
            if any(
                row.get(key) is not None
                for key in ("receipt_id", "observed_at", "data_through")
            ):
                raise RuntimeError("provider-native startup projection is invalid")
            continue
        if state not in {"success", "empty", "failed", "stale"}:
            raise RuntimeError("provider-native receipt projection state is invalid")
        if type(row.get("receipt_id")) is not str or not row["receipt_id"]:
            raise RuntimeError("provider-native receipt projection is incomplete")
        observed = _parse_timestamp(row.get("observed_at"))
        if observed > now_utc:
            raise RuntimeError("provider-native receipt projection is in the future")
        status = (
            "failed"
            if state == "failed"
            else "empty"
            if state == "empty"
            else "success"
        )
        latest[dataset.dataset_id] = LastTerminal(
            status=status,
            finished_at=observed,
        )
    return MappingProxyType(latest)


def _request_window(
    binding: ProviderBinding,
    *,
    policy: CadencePolicy,
    local_date: date,
) -> Mapping[str, str]:
    window_policy = binding.request_window_policy
    if window_policy is None:
        return MappingProxyType({})
    end_date = local_date - timedelta(days=policy.partition_offset_days)
    if window_policy.range_start_key == window_policy.range_end_key:
        keys = (window_policy.range_start_key,)
        if window_policy.required_keys != keys:
            raise ValueError("single-partition window contract is inconsistent")
        return MappingProxyType({keys[0]: end_date.strftime("%Y%m%d")})
    expected_keys = {
        window_policy.range_start_key,
        window_policy.range_end_key,
    }
    if set(window_policy.required_keys) != expected_keys:
        raise ValueError("range window requires only its start and end keys")
    span_days = min(policy.range_days, window_policy.max_span_days)
    start_date = end_date - timedelta(days=span_days - 1)
    return MappingProxyType(
        {
            window_policy.range_end_key: end_date.strftime("%Y%m%d"),
            window_policy.range_start_key: start_date.strftime("%Y%m%d"),
        }
    )


def plan_runs(
    *,
    registry: DatasetRegistry,
    schedule: Schedule,
    last_finished_at: Mapping[str, LastTerminal],
    now: datetime,
) -> tuple[tuple[ScheduledRun, ...], tuple[SkippedResult, ...]]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduler clock must include timezone")
    utc_now = now.astimezone(timezone.utc)
    plans: list[ScheduledRun] = []
    skipped: list[SkippedResult] = []
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        if dataset.read_model_adapter.storage_kind != "provider_native_rows":
            continue
        active = tuple(
            binding
            for binding in dataset.provider_bindings
            if binding.entitlement_state == "active"
            and binding.activation_state == "active"
        )
        if not active:
            for binding in dataset.provider_bindings:
                state = (
                    "paused" if binding.activation_state != "active" else "not_entitled"
                )
                skipped.append(
                    SkippedResult(dataset.dataset_id, binding.provider, state)
                )
            continue
        if len(active) != 1:
            raise ValueError("each scheduled dataset requires one active binding")
        binding = active[0]
        try:
            cadence = schedule.cadences[dataset.cadence_class]
        except KeyError as exc:
            raise ValueError("active dataset cadence is not scheduled") from exc
        local_now = now.astimezone(ZoneInfo(dataset.timezone))
        if local_now.isoweekday() not in cadence.weekdays:
            skipped.append(
                SkippedResult(dataset.dataset_id, binding.provider, "outside_weekdays")
            )
            continue
        if local_now.timetz().replace(tzinfo=None) < cadence.not_before_local:
            skipped.append(
                SkippedResult(dataset.dataset_id, binding.provider, "before_window")
            )
            continue
        previous = last_finished_at.get(dataset.dataset_id)
        interval = (
            cadence.failure_retry_seconds
            if previous is not None and previous.status == "failed"
            else cadence.minimum_interval_seconds
        )
        if (
            previous is not None
            and (utc_now - previous.finished_at).total_seconds() < interval
        ):
            skipped.append(
                SkippedResult(dataset.dataset_id, binding.provider, "not_due")
            )
            continue
        plans.append(
            ScheduledRun(
                dataset_id=dataset.dataset_id,
                provider=binding.provider,
                provider_api=binding.api_name,
                cadence_class=dataset.cadence_class,
                request_window=_request_window(
                    binding,
                    policy=cadence,
                    local_date=local_now.date(),
                ),
            )
        )
    return tuple(plans), tuple(skipped)


def _subprocess_executor(
    plan: ScheduledRun,
    *,
    db_path: Path,
    timeout_seconds: int,
    started_at: str,
) -> DatasetResult:
    command = [
        sys.executable,
        str(ROOT / "tools" / "collect_provider_dataset.py"),
        "--db-path",
        str(db_path),
        "--dataset-id",
        plan.dataset_id,
        "--request-window-json",
        json.dumps(dict(plan.request_window), separators=(",", ":"), sort_keys=True),
        "--attempt-id",
        str(uuid.uuid4()),
        "--started-at",
        started_at,
        "--execute",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
    if type(payload) is not dict or set(payload) != _RUNNER_RESULT_KEYS:
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
    counts = payload.get("counts")
    error_codes = payload.get("error_codes")
    receipt_count = payload.get("receipt_count")
    state = payload.get("state")
    count_values_valid = type(counts) is dict and set(counts) == _RUNNER_COUNT_KEYS
    if count_values_valid:
        count_values_valid = all(
            value is None or (type(value) is int and value >= 0)
            for value in counts.values()
        )
    if (
        not count_values_valid
        or type(error_codes) is not list
        or any(type(code) is not str or not code for code in error_codes)
        or type(receipt_count) is not int
        or receipt_count < 0
        or payload.get("mode") != "execute"
        or payload.get("dataset_id") != plan.dataset_id
        or payload.get("provider") != plan.provider
        or payload.get("provider_api") != plan.provider_api
        or type(state) is not str
        or state not in _TERMINAL_STATES
        or _STATE_EXIT_CODES[state] != completed.returncode
    ):
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
    return DatasetResult(plan.dataset_id, plan.provider, state, completed.returncode)


def run_schedule(
    *,
    registry: DatasetRegistry,
    schedule: Schedule,
    db_path: Path,
    now: datetime,
    execute: bool,
    executor: Callable[[ScheduledRun], DatasetResult] | None = None,
) -> ScheduleResult:
    last_finished = _read_last_finished_at(
        db_path,
        registry,
        now=now,
    )
    plans, skipped = plan_runs(
        registry=registry,
        schedule=schedule,
        last_finished_at=last_finished,
        now=now,
    )
    if not execute:
        planned = tuple(
            DatasetResult(plan.dataset_id, plan.provider, "planned", 0)
            for plan in plans
        )
        return ScheduleResult(0, "plan", planned, skipped)
    started_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    execute_one = executor or (
        lambda plan: _subprocess_executor(
            plan,
            db_path=db_path,
            timeout_seconds=schedule.dataset_timeout_seconds,
            started_at=started_at,
        )
    )
    results: list[DatasetResult] = []
    for plan in plans:
        try:
            result = execute_one(plan)
        except Exception:
            result = DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
        if (
            not isinstance(result, DatasetResult)
            or result.dataset_id != plan.dataset_id
            or result.provider != plan.provider
            or _STATE_EXIT_CODES.get(result.state) != result.exit_code
        ):
            result = DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
        results.append(result)
    failed = any(item.state not in _SUCCESS_STATES for item in results)
    return ScheduleResult(1 if failed else 0, "execute", tuple(results), skipped)


@contextmanager
def exclusive_schedule_lock(lock_path: Path) -> Iterator[None]:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ScheduleBusyError(
                "provider-native schedule is already running"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include timezone")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=marketdata_sqlite_path())
    parser.add_argument("--schedule-config", type=Path, default=DEFAULT_SCHEDULE_CONFIG)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--now", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.execute and args.now is not None:
        print('{"mode":"execute","state":"validation"}')
        return 2
    try:
        if args.execute:
            _validated_collector_credentials()
        with exclusive_schedule_lock(args.lock_path):
            result = run_schedule(
                registry=load_runtime_dataset_registry(),
                schedule=load_schedule(args.schedule_config),
                db_path=args.db_path,
                now=_now(args.now),
                execute=args.execute,
            )
    except ScheduleBusyError:
        print('{"mode":"execute","state":"busy"}')
        return 75
    except Exception:
        print(
            json.dumps(
                {
                    "mode": "execute" if args.execute else "plan",
                    "state": "validation",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            result.public_payload(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
