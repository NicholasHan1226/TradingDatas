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
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Iterator, MutableMapping
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    DATASET_REGISTRY_PATH_ENV,
    DatasetRegistry,
    load_runtime_dataset_registry,
)
from collectors.tushare.tushare_common import QUICKSYNC_API_URL  # noqa: E402
from runtime_paths import marketdata_sqlite_path  # noqa: E402
from tools.provider_native_cadence_planner import (  # noqa: E402
    Schedule,
    ScheduledRun,
    load_planner_state,
    load_schedule as _load_schedule,
    plan_runs as _plan_runs,
)


DEFAULT_SCHEDULE_CONFIG = ROOT / "config" / "provider_native_schedule.yaml"
DEFAULT_LOCK_PATH = Path("/run/sharedsignals/provider-native-collect.lock")


def load_schedule(path: Path = DEFAULT_SCHEDULE_CONFIG) -> Schedule:
    return _load_schedule(path)
INTERNAL_CURRENT_ROOT = Path("/opt/investment/releases/sharedsignals-v1/current")
PROVIDER_NATIVE_REGISTRY_RELATIVE = Path(
    "config/provider_native_dataset_registry.yaml"
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
    approved_host = urlsplit(QUICKSYNC_API_URL).hostname
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("collector API URL is invalid") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != approved_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("collector API URL is invalid")


def _pin_runtime_registry_to_release(
    *,
    environment: MutableMapping[str, str] = os.environ,
    current_root: Path = INTERNAL_CURRENT_ROOT,
    release_root: Path = ROOT,
) -> Path:
    """Bind the stable systemd pointer to this immutable release.

    The public profile is Git-owned and therefore names ``current``.  Before
    loading the registry or spawning collectors, the scheduler proves that
    pointer resolves to the release containing this executable, then replaces
    only its process-local environment value with the immutable target.
    """

    stable_path = current_root / PROVIDER_NATIVE_REGISTRY_RELATIVE
    immutable_path = release_root / PROVIDER_NATIVE_REGISTRY_RELATIVE
    configured = environment.get(DATASET_REGISTRY_PATH_ENV)
    if configured not in {str(stable_path), str(immutable_path)}:
        raise ValueError("runtime dataset registry pointer is invalid")
    if release_root.resolve(strict=True) != release_root:
        raise ValueError("scheduler release root is not canonical")
    if not immutable_path.is_file() or immutable_path.is_symlink():
        raise ValueError("immutable runtime dataset registry is invalid")
    if immutable_path.resolve(strict=True) != immutable_path:
        raise ValueError("immutable runtime dataset registry is not canonical")
    if current_root.resolve(strict=True) != release_root:
        raise ValueError("runtime current pointer targets another release")
    if stable_path.resolve(strict=True) != immutable_path:
        raise ValueError("runtime registry pointer targets another artifact")
    environment[DATASET_REGISTRY_PATH_ENV] = str(immutable_path)
    return immutable_path


def _subprocess_executor(
    plan: ScheduledRun,
    *,
    db_path: Path,
    timeout_seconds: int,
    started_at: str,
) -> DatasetResult:
    if plan.request_variant:
        return DatasetResult(plan.dataset_id, plan.provider, "failed", 4)
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
    return ScheduleResult(
        1 if failed else 0, "execute", tuple(results), skipped, plans
    )


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
            _pin_runtime_registry_to_release()
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
