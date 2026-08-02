#!/usr/bin/env python3
"""Dispatch the single installed collector between cadence and bounded batch modes.

The normal timer has no batch manifest and therefore executes the unchanged
registry cadence planner.  A release operator may stage exactly one bounded
on-demand manifest inside the unit's ``RuntimeDirectory`` before manually
starting the same service.  The dispatcher consumes the environment selector
before the provider call so a later timer wakeup cannot replay that batch.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import sys
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import collect_provider_dataset  # noqa: E402
from tools import run_provider_native_schedule  # noqa: E402


RUNTIME_DIRECTORY = Path("/run/tradingdatas")
ON_DEMAND_ENV_FILE = RUNTIME_DIRECTORY / "on-demand.env"
ON_DEMAND_BATCH_FILE = RUNTIME_DIRECTORY / "on-demand-batch.json"
COLLECT_LOCK_FILE = RUNTIME_DIRECTORY / "collect.lock"
ON_DEMAND_BATCH_ENV = "TRADINGDATAS_ON_DEMAND_BATCH_FILE"


class OnDemandBatchError(ValueError):
    """The one-shot selector is unsafe or incomplete."""


def _require_private_regular_file(path: Path, *, name: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OnDemandBatchError(f"{name} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OnDemandBatchError(f"{name} must be a regular file")
    if metadata.st_nlink != 1:
        raise OnDemandBatchError(f"{name} must have one link")
    if metadata.st_uid != os.getuid() or metadata.st_gid != os.getgid():
        raise OnDemandBatchError(f"{name} ownership is invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OnDemandBatchError(f"{name} mode is invalid")


@contextmanager
def _consume_batch_selector() -> Iterator[Path | None]:
    raw = os.environ.get(ON_DEMAND_BATCH_ENV)
    if raw is None:
        yield None
        return
    if raw != str(ON_DEMAND_BATCH_FILE):
        raise OnDemandBatchError("on-demand batch path is invalid")
    _require_private_regular_file(ON_DEMAND_ENV_FILE, name="on-demand env file")
    _require_private_regular_file(ON_DEMAND_BATCH_FILE, name="on-demand batch file")
    try:
        ON_DEMAND_ENV_FILE.unlink()
    except OSError as exc:
        raise OnDemandBatchError("on-demand env file cannot be consumed") from exc
    try:
        yield ON_DEMAND_BATCH_FILE
    finally:
        try:
            ON_DEMAND_BATCH_FILE.unlink()
        except FileNotFoundError:
            pass


def _run_on_demand(batch_file: Path) -> int:
    try:
        with run_provider_native_schedule.exclusive_schedule_lock(COLLECT_LOCK_FILE):
            return collect_provider_dataset.main(
                [
                    "--db-path",
                    str(run_provider_native_schedule.provider_native_sqlite_path()),
                    "--batch-file",
                    str(batch_file),
                    "--execute",
                ]
            )
    except run_provider_native_schedule.ScheduleBusyError:
        print('{"mode":"execute","state":"busy"}')
        return 75


def main() -> int:
    try:
        with _consume_batch_selector() as batch_file:
            if batch_file is None:
                return run_provider_native_schedule.main(
                    [
                        "--db-path",
                        str(run_provider_native_schedule.provider_native_sqlite_path()),
                        "--lock-path",
                        str(COLLECT_LOCK_FILE),
                        "--execute",
                    ]
                )
            return _run_on_demand(batch_file)
    except OnDemandBatchError:
        print('{"mode":"execute","state":"validation"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
