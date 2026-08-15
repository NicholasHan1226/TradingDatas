#!/usr/bin/env python3
"""Run every due provider-native binding from the trusted runtime registry.

This scheduler owns no dataset or provider API list.  Cadence timing lives in
``config/provider_native_schedule.yaml``; request parameter names and bounds
remain owned by the process-selected dataset registry.  Plan mode is the safe
default.  ``--execute`` is intended for the reviewed systemd oneshot unit.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Callable, Iterator
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dataset_registry as _dataset_registry  # noqa: E402
from dataset_registry import DatasetRegistry, load_runtime_dataset_registry  # noqa: E402
from collectors.tushare.collector import (  # noqa: E402
    RequestBudgetExceeded,
    TushareCollector,
)
from collectors.tushare.provider_native_ingest import (  # noqa: E402
    RetrySettings,
    collect_provider_native_dataset,
)
from collectors.tushare.tushare_common import read_tushare_config  # noqa: E402
from runtime_paths import provider_native_sqlite_path  # noqa: E402
from storage.ingest_receipts import make_schedule_plan_attempt_id  # noqa: E402
from storage.receipt_projection import (  # noqa: E402
    ReceiptJournalEntry,
    validated_receipt_journal_entries_by_dataset,
)
from tools.provider_native_cadence_planner import (  # noqa: E402
    Schedule,
    ScheduledRun,
    load_activation_wave,
    load_planner_state,
    load_schedule as _load_schedule,
    load_schedule_bytes,
    plan_runs as _plan_runs,
)


DEFAULT_SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
DEFAULT_RUNTIME_REGISTRY_CONFIG = ROOT / "config" / "provider_native_dataset_registry.yaml"
DEFAULT_ACTIVATION_WAVE_CONFIG = (
    ROOT / "config" / "provider_native_activation_waves.v1.yaml"
)
DEFAULT_LOCK_PATH = Path(
    os.environ.get(
        "TRADINGDATAS_COLLECT_LOCK",
        "/run/lock/tradingdatas-collect.lock",
    )
)


def load_schedule(path: Path = DEFAULT_SCHEDULE_CONFIG) -> Schedule:
    return _load_schedule(path)


def _load_dataset_registry_bytes(payload: bytes) -> DatasetRegistry:
    root = _dataset_registry._mapping(  # noqa: SLF001
        yaml.safe_load(payload.decode("utf-8")), "registry"
    )
    _dataset_registry._reject_unknown_keys(  # noqa: SLF001
        root,
        _dataset_registry._ROOT_KEYS,  # noqa: SLF001
        "registry",
        required=_dataset_registry._ROOT_REQUIRED_KEYS,  # noqa: SLF001
    )
    version = root["version"]
    if type(version) is not int or version != 1:
        raise ValueError("registry.version must be integer 1")
    raw_datasets = root["datasets"]
    if type(raw_datasets) is not list or not raw_datasets:
        raise ValueError("registry.datasets must be a non-empty list")
    query_defaults = _dataset_registry._load_query_defaults(  # noqa: SLF001
        root["query_defaults"]
    )
    schema_profiles = _dataset_registry._load_schema_profiles(  # noqa: SLF001
        root.get("schema_profiles"), query_defaults=query_defaults
    )
    return DatasetRegistry(
        tuple(
            _dataset_registry._load_dataset(  # noqa: SLF001
                dataset, index, schema_profiles, query_defaults
            )
            for index, dataset in enumerate(raw_datasets)
        ),
        query_defaults=query_defaults,
    )


_SUCCESS_STATES = frozenset({"success", "empty"})
_STATE_EXIT_CODES = {"success": 0, "empty": 3, "validation": 2, "failed": 4}
_VALIDATION_ERROR_CODES = frozenset(
    {"config_error", "resource_budget", "validation_failed"}
)
_FORBIDDEN_COLLECTOR_CREDENTIALS = frozenset(
    {
        "QUICKSYNC_API_TOKEN",
        "QUICKSYNC_API_URL",
        "QUICKSYNC_TOKEN",
        "QUICKSYNC_URL",
        "TUSHARE_API_TOKEN",
        "TUSHARE_MCP_URL",
        "TUSHARE_TOKEN",
    }
)
_CURRENT_ONLY_ACTIVATION_WAVE = "pilot_existing"
_TOP_LEVEL_VALIDATION_PROVENANCE = frozenset(
    {
        ("dispatcher", "selector_validation"),
        ("preplan", "credential_validation"),
        ("preplan", "registry_load"),
        ("preplan", "schedule_load"),
        ("schedule_run", "schedule_run"),
    }
)


class ScheduleBusyError(RuntimeError):
    """Another reviewed scheduler instance owns the global collection lock."""


@dataclass(frozen=True)
class DatasetResult:
    dataset_id: str
    provider: str
    state: str
    exit_code: int
    error_codes: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    receipt_provenance: tuple[ReceiptJournalEntry, ...] = ()


@dataclass(frozen=True)
class SkippedResult:
    dataset_id: str
    provider: str
    state: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScheduleResult:
    exit_code: int
    mode: str
    executed: tuple[DatasetResult, ...]
    skipped: tuple[SkippedResult, ...]
    plans: tuple[ScheduledRun, ...] = ()

    def public_payload(self) -> dict[str, object]:
        planned = sum(item.state == "planned" for item in self.executed)
        terminal = len(self.executed) - planned
        datasets = []
        for item in self.executed:
            dataset = {
                "dataset_id": item.dataset_id,
                "provider": item.provider,
                "state": item.state,
            }
            if item.state not in _SUCCESS_STATES | {"planned"}:
                if item.error_codes:
                    dataset["error_codes"] = list(item.error_codes)
                if item.receipt_ids:
                    dataset["receipt_ids"] = list(item.receipt_ids)
            if item.receipt_provenance:
                provenance = []
                for entry in item.receipt_provenance:
                    row: dict[str, object] = {
                        "receipt_id": entry.receipt_id,
                        "status": entry.status,
                        "counts": (
                            None
                            if entry.counts is None
                            else {
                                "returned": entry.counts.returned,
                                "validated": entry.counts.validated,
                                "rejected": entry.counts.rejected,
                                "committed": entry.counts.committed,
                            }
                        ),
                        "error_layer": entry.error_layer,
                        "error_codes": list(entry.error_codes),
                        "validation_reasons": list(entry.validation_reasons),
                    }
                    provenance.append(row)
                dataset["receipt_provenance"] = provenance
            datasets.append(dataset)
        skipped = []
        for item in self.skipped:
            skip = {
                "dataset_id": item.dataset_id,
                "provider": item.provider,
                "state": item.state,
            }
            if item.state == "invalid_receipt_authority" and item.reasons:
                skip["reasons"] = list(item.reasons)
            skipped.append(skip)
        return {
            "datasets": datasets,
            "mode": self.mode,
            "skipped": skipped,
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


class RuntimeRateBudgetLedger:
    """Count every real provider call across the entire runner process."""

    def __init__(self, schedule: Schedule) -> None:
        self._schedule = schedule
        self._account: dict[str, int] = defaultdict(int)
        self._provider: dict[tuple[str, str], int] = defaultdict(int)
        self._api: dict[tuple[str, str, str], int] = defaultdict(int)

    def consume(self, plan: ScheduledRun, api_name: str) -> None:
        if api_name != plan.provider_api:
            raise RequestBudgetExceeded("provider API identity changed")
        budget = self._schedule.rate_budgets[plan.rate_budget_class]
        account_key = plan.rate_budget_class
        provider_key = (plan.rate_budget_class, plan.provider)
        api_key = (plan.rate_budget_class, plan.provider, plan.provider_api)
        api_limit = budget.api_overrides.get(
            plan.provider_api, budget.api_requests_per_run
        )
        if (
            self._account[account_key] >= budget.account_requests_per_run
            or self._provider[provider_key] >= budget.provider_requests_per_run
            or self._api[api_key] >= api_limit
        ):
            raise RequestBudgetExceeded("provider request budget exhausted")
        self._account[account_key] += 1
        self._provider[provider_key] += 1
        self._api[api_key] += 1


def _validated_collector_credentials() -> None:
    if any(os.environ.get(name) for name in _FORBIDDEN_COLLECTOR_CREDENTIALS):
        raise ValueError("collector credential source is not allowed")
    try:
        read_tushare_config()
    except RuntimeError as exc:
        raise ValueError("collector credentials are unavailable") from exc


def _read_receipt_provenance(
    db_path: Path,
    *,
    registry: DatasetRegistry,
    receipt_ids_by_dataset: dict[str, tuple[str, ...]],
) -> dict[str, tuple[ReceiptJournalEntry, ...]]:
    """Read selected persisted receipts in one bounded authority snapshot."""

    selected = {
        dataset_id: receipt_ids
        for dataset_id, receipt_ids in receipt_ids_by_dataset.items()
        if receipt_ids
    }
    if not selected:
        return {}
    try:
        db_uri = f"file:{db_path}?mode=ro"
        with sqlite3.connect(db_uri, uri=True) as conn:
            return dict(
                validated_receipt_journal_entries_by_dataset(
                    conn,
                    registry,
                    selected,
                    now=datetime.now(timezone.utc),
                )
            )
    except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError):
        # Provenance is observability only.  A readback failure must not turn a
        # persisted provider outcome into a different scheduler result.
        return {}


def _in_process_executor(
    plan: ScheduledRun,
    *,
    registry: DatasetRegistry,
    db_path: Path,
    started_at: str,
    attempt_id: str,
    rate_ledger: RuntimeRateBudgetLedger,
) -> DatasetResult:
    """Execute one plan while sharing the runner's actual-call budget ledger."""

    collector = TushareCollector(
        request_gate=lambda api_name: rate_ledger.consume(plan, api_name)
    )
    result = collect_provider_native_dataset(
        db_path,
        registry=registry,
        collector=collector,
        dataset_id=plan.dataset_id,
        request_window=plan.request_window,
        attempt_id=attempt_id,
        started_at=started_at,
        retry=RetrySettings(
            max_attempts=plan.retry.max_attempts,
            base_delay_seconds=plan.retry.base_delay_seconds,
            max_delay_seconds=plan.retry.max_delay_seconds,
            jitter_seconds=plan.retry_jitter_seconds,
        ),
    )
    if result.status == "success":
        return DatasetResult(
            plan.dataset_id,
            plan.provider,
            "success",
            0,
        )
    if result.status == "empty":
        return DatasetResult(
            plan.dataset_id,
            plan.provider,
            "empty",
            3,
        )
    if set(result.errors) & _VALIDATION_ERROR_CODES:
        return DatasetResult(
            plan.dataset_id,
            plan.provider,
            "validation",
            2,
            error_codes=result.errors,
            receipt_ids=result.receipt_ids,
        )
    return DatasetResult(
        plan.dataset_id,
        plan.provider,
        "failed",
        4,
        error_codes=result.errors,
        receipt_ids=result.receipt_ids,
    )


def run_schedule(
    *,
    registry: DatasetRegistry | None,
    schedule: Schedule | None,
    db_path: Path,
    now: datetime,
    execute: bool,
    executor: Callable[[ScheduledRun], DatasetResult] | None = None,
    activation_wave: str | None = None,
    activation_wave_manifest: Path = DEFAULT_ACTIVATION_WAVE_CONFIG,
    registry_source_path: Path = DEFAULT_RUNTIME_REGISTRY_CONFIG,
    schedule_source_path: Path = DEFAULT_SCHEDULE_CONFIG,
    current_only: bool = False,
) -> ScheduleResult:
    if current_only and activation_wave != _CURRENT_ONLY_ACTIVATION_WAVE:
        raise ValueError("current-only requires pilot_existing activation wave")
    selected_dataset_ids = None
    if activation_wave is not None:
        registry_payload = Path(registry_source_path).read_bytes()
        schedule_payload = Path(schedule_source_path).read_bytes()
        registry = _load_dataset_registry_bytes(registry_payload)
        schedule = load_schedule_bytes(schedule_payload)
        selected_dataset_ids = load_activation_wave(
            activation_wave_manifest,
            activation_wave,
            registry=registry,
            registry_payload=registry_payload,
            schedule_payload=schedule_payload,
        ).dataset_ids
    elif registry is None or schedule is None:
        raise ValueError("default schedule inputs are required")
    calendar_dataset_ids = frozenset(
        policy.calendar.dataset_id
        for policy in schedule.cadences.values()
        if policy.calendar is not None
    )
    state = load_planner_state(
        db_path,
        registry,
        now=now,
        calendar_dataset_ids=calendar_dataset_ids,
    )
    plans, planner_skips = _plan_runs(
        registry=registry,
        schedule=schedule,
        state=state,
        now=now,
        selected_dataset_ids=selected_dataset_ids,
        current_only=current_only,
    )
    if current_only and (
        selected_dataset_ids is None
        or any(
            plan.dataset_id not in selected_dataset_ids or plan.priority != "current"
            for plan in plans
        )
    ):
        raise ValueError("current-only plan escaped selection")
    skipped_results = []
    for item in planner_skips:
        reasons = ()
        if item.state == "invalid_receipt_authority":
            dataset = registry.resolve(item.dataset_id)
            binding = registry.provider_binding(item.dataset_id, item.provider)
            reasons = state.invalid_reasons(dataset, binding)
        skipped_results.append(
            SkippedResult(item.dataset_id, item.provider, item.state, reasons)
        )
    skipped = tuple(skipped_results)
    if not execute:
        planned = tuple(
            DatasetResult(plan.dataset_id, plan.provider, "planned", 0)
            for plan in plans
        )
        return ScheduleResult(0, "plan", planned, skipped, plans)
    started_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    rate_ledger = RuntimeRateBudgetLedger(schedule)
    run_attempt_id = str(uuid.uuid4())
    results: list[DatasetResult] = []
    for plan_index, plan in enumerate(plans):
        try:
            result = (
                executor(plan)
                if executor is not None
                else _in_process_executor(
                    plan,
                    registry=registry,
                    db_path=db_path,
                    started_at=started_at,
                    attempt_id=make_schedule_plan_attempt_id(
                        run_attempt_id,
                        plan_index=plan_index,
                    ),
                    rate_ledger=rate_ledger,
                )
            )
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
    receipt_ids_by_dataset = {
        item.dataset_id: item.receipt_ids
        for item in results
        if item.receipt_ids
    }
    provenance_by_dataset = _read_receipt_provenance(
        db_path,
        registry=registry,
        receipt_ids_by_dataset=receipt_ids_by_dataset,
    )
    results = [
        replace(
            item,
            receipt_provenance=provenance_by_dataset.get(
                item.dataset_id,
                item.receipt_provenance,
            ),
        )
        for item in results
    ]
    failed = any(item.state not in _SUCCESS_STATES for item in results)
    return ScheduleResult(1 if failed else 0, "execute", tuple(results), skipped, plans)


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
    parser.add_argument("--db-path", type=Path, default=provider_native_sqlite_path())
    parser.add_argument("--schedule-config", type=Path, default=DEFAULT_SCHEDULE_CONFIG)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--activation-wave")
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--now", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def validation_payload(*, mode: str, phase: str, reason: str) -> str:
    """Return a fixed, non-sensitive top-level validation payload."""
    if (phase, reason) not in _TOP_LEVEL_VALIDATION_PROVENANCE:
        raise ValueError("unrecognized validation provenance")
    return json.dumps(
        {
            "mode": mode,
            "phase": phase,
            "reason": reason,
            "state": "validation",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        args.execute
        and (args.now is not None or args.schedule_config != DEFAULT_SCHEDULE_CONFIG)
    ) or (
        args.current_only
        and args.activation_wave != _CURRENT_ONLY_ACTIVATION_WAVE
    ):
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
    if args.execute:
        try:
            _validated_collector_credentials()
        except Exception:
            print(
                validation_payload(
                    mode="execute",
                    phase="preplan",
                    reason="credential_validation",
                )
            )
            return 2
    try:
        with exclusive_schedule_lock(args.lock_path):
            if args.activation_wave is None:
                try:
                    registry = load_runtime_dataset_registry()
                except Exception:
                    print(
                        validation_payload(
                            mode="execute" if args.execute else "plan",
                            phase="preplan",
                            reason="registry_load",
                        )
                    )
                    return 2
                try:
                    schedule = load_schedule(args.schedule_config)
                except Exception:
                    print(
                        validation_payload(
                            mode="execute" if args.execute else "plan",
                            phase="preplan",
                            reason="schedule_load",
                        )
                    )
                    return 2
            else:
                registry = None
                schedule = None
            try:
                result = run_schedule(
                    registry=registry,
                    schedule=schedule,
                    db_path=args.db_path,
                    now=_now(args.now),
                    execute=args.execute,
                    activation_wave=args.activation_wave,
                    schedule_source_path=args.schedule_config,
                    current_only=args.current_only,
                )
            except Exception:
                print(
                    validation_payload(
                        mode="execute" if args.execute else "plan",
                        phase="schedule_run",
                        reason="schedule_run",
                    )
                )
                return 2
    except ScheduleBusyError:
        print('{"mode":"execute","state":"busy"}')
        return 75
    except Exception:
        print(
            validation_payload(
                mode="execute" if args.execute else "plan",
                phase="schedule_run",
                reason="schedule_run",
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
