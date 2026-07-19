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
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
from typing import Callable, Iterator
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
from tools.provider_native_cadence_planner import (  # noqa: E402
    Schedule,
    ScheduledRun,
    load_planner_state,
    load_schedule as _load_schedule,
    plan_runs as _plan_runs,
)


DEFAULT_SCHEDULE_CONFIG = Path(
    os.environ.get(
        "TRADINGDATAS_SCHEDULE_PATH",
        ROOT / "config" / "provider_native_schedule.yaml",
    )
)
DEFAULT_LOCK_PATH = Path(
    os.environ.get(
        "TRADINGDATAS_COLLECT_LOCK",
        "/run/lock/tradingdatas-collect.lock",
    )
)


def load_schedule(path: Path = DEFAULT_SCHEDULE_CONFIG) -> Schedule:
    return _load_schedule(path)


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


class ScheduleBusyError(RuntimeError):
    """Another reviewed scheduler instance owns the global collection lock."""


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
    plans: tuple[ScheduledRun, ...] = ()

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
        if (
            self._account[account_key] >= budget.account_requests_per_run
            or self._provider[provider_key] >= budget.provider_requests_per_run
            or self._api[api_key] >= budget.api_requests_per_run
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


def _in_process_executor(
    plan: ScheduledRun,
    *,
    registry: DatasetRegistry,
    db_path: Path,
    started_at: str,
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
        request_variant=plan.request_variant,
        attempt_id=str(uuid.uuid4()),
        started_at=started_at,
        retry=RetrySettings(
            max_attempts=plan.retry.max_attempts,
            base_delay_seconds=plan.retry.base_delay_seconds,
            max_delay_seconds=plan.retry.max_delay_seconds,
            jitter_seconds=plan.retry_jitter_seconds,
        ),
    )
    if result.status == "success":
        return DatasetResult(plan.dataset_id, plan.provider, "success", 0)
    if result.status == "empty":
        return DatasetResult(plan.dataset_id, plan.provider, "empty", 3)
    if set(result.errors) & _VALIDATION_ERROR_CODES:
        return DatasetResult(plan.dataset_id, plan.provider, "validation", 2)
    return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)


def run_schedule(
    *,
    registry: DatasetRegistry,
    schedule: Schedule,
    db_path: Path,
    now: datetime,
    execute: bool,
    executor: Callable[[ScheduledRun], DatasetResult] | None = None,
) -> ScheduleResult:
    state = load_planner_state(db_path, registry, now=now)
    plans, planner_skips = _plan_runs(
        registry=registry,
        schedule=schedule,
        state=state,
        now=now,
    )
    skipped = tuple(
        SkippedResult(item.dataset_id, item.provider, item.state)
        for item in planner_skips
    )
    if not execute:
        planned = tuple(
            DatasetResult(plan.dataset_id, plan.provider, "planned", 0)
            for plan in plans
        )
        return ScheduleResult(0, "plan", planned, skipped, plans)
    started_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    rate_ledger = RuntimeRateBudgetLedger(schedule)
    execute_one = executor or (
        lambda plan: _in_process_executor(
            plan,
            registry=registry,
            db_path=db_path,
            started_at=started_at,
            rate_ledger=rate_ledger,
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
