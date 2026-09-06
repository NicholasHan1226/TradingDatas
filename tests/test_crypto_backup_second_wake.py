from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.run_binance_spot_canary import latest_closed_window, run

ROOT = Path(__file__).resolve().parents[1]


def _five_minute_oncalendar_slots(timer_text: str) -> set[tuple[int, int]]:
    matches = re.findall(
        r"^OnCalendar=\*-\*-\* \*:(\d+)/5:(\d{2})$", timer_text, flags=re.M
    )
    assert matches, timer_text
    slots: set[tuple[int, int]] = set()
    for start_minute, second in matches:
        slots.update(
            (minute, int(second)) for minute in range(int(start_minute), 60, 5)
        )
    return slots


def test_close_plus_180s_uses_the_same_latest_closed_window() -> None:
    close = datetime(2026, 9, 5, 9, 5, tzinfo=timezone.utc)
    expected = {
        "start_open_time": "2026-09-05T08:55:00Z",
        "end_open_time": "2026-09-05T09:00:00Z",
    }
    primary_now = close + timedelta(seconds=10)
    first_backup = close + timedelta(seconds=70)
    second_backup = close + timedelta(seconds=180)

    assert latest_closed_window(primary_now) == expected
    assert latest_closed_window(first_backup) == expected
    assert latest_closed_window(second_backup) == expected
    planned = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=second_backup,
        backup_wake=True,
    )
    assert planned["windows"] == [expected]
    assert planned["state"] == "planned"


def test_backup_timer_has_fail_fast_second_wake_at_close_plus_180s() -> None:
    retry_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect-retry.timer"
    ).read_text()
    primary = _five_minute_oncalendar_slots(
        (ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.timer").read_text()
    )
    backup = _five_minute_oncalendar_slots(retry_timer)
    usdm = _five_minute_oncalendar_slots(
        (ROOT / "deploy/systemd/tradingdatas-crypto-binance-usdm-collect.timer").read_text()
    )
    book_ticker = _five_minute_oncalendar_slots(
        (ROOT / "deploy/systemd/tradingdatas-crypto-binance-book-ticker.timer").read_text()
    )

    assert "OnCalendar=*-*-* *:1/5:00" in retry_timer
    assert "OnCalendar=*-*-* *:3/5:00" in retry_timer
    assert backup == {(minute, 0) for minute in range(1, 60, 5)} | {
        (minute, 0) for minute in range(3, 60, 5)
    }
    occupied: dict[tuple[int, int], str] = {}
    for name, slots in (
        ("bar-primary", primary),
        ("bar-backup", backup),
        ("usdm", usdm),
        ("book-ticker", book_ticker),
    ):
        overlap = set(occupied).intersection(slots)
        assert not overlap, f"{name} shares {sorted(overlap)}"
        occupied.update(dict.fromkeys(slots, name))
