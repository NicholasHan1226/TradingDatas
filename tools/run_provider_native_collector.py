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
from datetime import datetime, timedelta
import os
from pathlib import Path
import stat
import sys
from typing import Iterator
from zoneinfo import ZoneInfo


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
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")

# The installed oneshot has a 45-minute systemd start timeout.  Reserve five
# extra minutes so a broad wave admitted before this boundary cannot occupy the
# first live-session tick even when it reaches that timeout.
SESSION_MINUTE_RESERVATION_LEAD = timedelta(minutes=50)


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
    expected_selector = f"{ON_DEMAND_BATCH_ENV}={ON_DEMAND_BATCH_FILE}\n".encode(
        "utf-8"
    )
    try:
        if ON_DEMAND_ENV_FILE.read_bytes() != expected_selector:
            raise OnDemandBatchError("on-demand env file content is invalid")
    except OSError as exc:
        raise OnDemandBatchError("on-demand env file cannot be read") from exc
    try:
        ON_DEMAND_ENV_FILE.unlink()
    except OSError as exc:
        raise OnDemandBatchError("on-demand env file cannot be consumed") from exc
    try:
        _require_private_regular_file(ON_DEMAND_BATCH_FILE, name="on-demand batch file")
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


def _local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def _reserve_session_minute_cadence(now: datetime) -> bool:
    """Reserve the single collector for intraday cadence near open sessions.

    Long low-frequency waves can exceed one five-minute timer interval.  The
    lead window prevents a broad wave from starting shortly before a session;
    while reserved, the same registry runner selects every session-minute
    dataset generically and preserves the shared provider/SQLite lock.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("dispatcher clock must be timezone-aware")
    local_now = now.astimezone(LOCAL_TIMEZONE)
    schedule = run_provider_native_schedule.load_schedule()
    policy = schedule.cadences["session_minute"]
    if local_now.isoweekday() not in policy.weekdays:
        return False
    # Match the cadence planner's minute-granularity session comparison.  The
    # timer intentionally jitters by up to 15 seconds, so the whole declared
    # end minute must remain reserved for the final session snapshot.
    local_time = local_now.timetz().replace(second=0, microsecond=0, tzinfo=None)
    for start, end in policy.session_windows_local:
        reserved_start = (
            datetime.combine(local_now.date(), start, LOCAL_TIMEZONE)
            - SESSION_MINUTE_RESERVATION_LEAD
        ).time()
        if reserved_start <= local_time <= end:
            return True
    return False


def _run_automatic() -> int:
    args = [
        "--db-path",
        str(run_provider_native_schedule.provider_native_sqlite_path()),
        "--lock-path",
        str(COLLECT_LOCK_FILE),
    ]
    try:
        reserve_session_minute = _reserve_session_minute_cadence(_local_now())
    except Exception:
        print(
            run_provider_native_schedule.validation_payload(
                mode="execute",
                phase="preplan",
                reason="schedule_load",
            )
        )
        return 2
    if reserve_session_minute:
        args.extend(["--cadence-class", "session_minute"])
    args.append("--execute")
    return run_provider_native_schedule.main(args)


def main() -> int:
    try:
        with _consume_batch_selector() as batch_file:
            if batch_file is None:
                return _run_automatic()
            return _run_on_demand(batch_file)
    except OnDemandBatchError:
        print(
            run_provider_native_schedule.validation_payload(
                mode="execute",
                phase="dispatcher",
                reason="selector_validation",
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
