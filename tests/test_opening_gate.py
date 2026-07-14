import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import opening_gate
from tools.opening_gate import evaluate_phase, output_path


def _gate_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE market_bars_intraday ("
            "market TEXT, symbol TEXT, trade_date TEXT, bar_time TEXT, collected_at TEXT)"
        )


def _healthy_sla(path: Path, now: datetime) -> None:
    path.write_text(json.dumps({"summary": {"critical": 0}}), encoding="utf-8")
    os.utime(path, (now.timestamp(), now.timestamp()))


def test_preopen_gate_is_green_when_runtime_and_sla_are_ready() -> None:
    result = evaluate_phase(
        "preopen",
        now=datetime(2026, 7, 10, 0, 50, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[],
    )

    assert result["status"] == "green"
    assert result["gate"] == "open"
    assert result["phase"] == "preopen"


def test_first_sample_gate_closes_when_today_a_share_bar_is_missing() -> None:
    result = evaluate_phase(
        "morning_first_sample",
        now=datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[],
    )

    assert result["status"] == "red"
    assert result["gate"] == "closed"
    assert "Ashare" in result["action_required"]


def test_first_sample_gate_opens_for_recent_today_a_share_bar() -> None:
    result = evaluate_phase(
        "morning_first_sample",
        now=datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[
            {
                "market": "Ashare",
                "trade_date": "20260710",
                "bar_time": "202607100930",
                "collected_at": "2026-07-10T01:34:00+00:00",
            }
        ],
    )

    assert result["status"] == "green"
    assert result["gate"] == "open"
    assert result["checks"]["a_share_intraday"]["sample_count"] == 1


def test_first_sample_gate_opens_for_sql_datetime_bar_time() -> None:
    result = evaluate_phase(
        "morning_first_sample",
        now=datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[
            {
                "market": "Ashare",
                "trade_date": "20260710",
                "bar_time": "2026-07-10 09:30:00",
                "collected_at": "2026-07-10T01:34:00+00:00",
            }
        ],
    )

    assert result["status"] == "green"
    assert result["checks"]["a_share_intraday"]["sample_count"] == 1


def test_first_sample_gate_opens_for_clock_with_seconds() -> None:
    result = evaluate_phase(
        "morning_first_sample",
        now=datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[
            {
                "market": "Ashare",
                "trade_date": "20260710",
                "bar_time": "09:30:00",
                "collected_at": "2026-07-10T01:34:00+00:00",
            }
        ],
    )

    assert result["status"] == "green"
    assert result["checks"]["a_share_intraday"]["sample_count"] == 1


def test_first_sample_gate_rejects_future_naive_or_invalid_collected_at() -> None:
    now = datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc)

    for collected_at in (
        "2026-07-10T01:35:06+00:00",
        "2026-07-10T01:34:00",
        "not-a-timestamp",
    ):
        result = evaluate_phase(
            "morning_first_sample",
            now=now,
            db_ready=True,
            health_sla_ready=True,
            intraday_rows=[
                {
                    "market": "Ashare",
                    "trade_date": "20260710",
                    "bar_time": "202607100930",
                    "collected_at": collected_at,
                }
            ],
        )

        assert result["status"] == "red", collected_at
        assert result["gate"] == "closed", collected_at
        assert result["checks"]["a_share_intraday"]["sample_count"] == 0


def test_first_sample_gate_rejects_future_or_invalid_bar_time() -> None:
    now = datetime(2026, 7, 10, 1, 35, tzinfo=timezone.utc)

    for bar_time in ("202607100936", "not-a-bar-time"):
        result = evaluate_phase(
            "morning_first_sample",
            now=now,
            db_ready=True,
            health_sla_ready=True,
            intraday_rows=[
                {
                    "market": "Ashare",
                    "trade_date": "20260710",
                    "bar_time": bar_time,
                    "collected_at": "2026-07-10T01:34:00+00:00",
                }
            ],
        )

        assert result["status"] == "red", bar_time
        assert result["gate"] == "closed", bar_time
        assert result["checks"]["a_share_intraday"]["sample_count"] == 0


def test_close_gate_uses_last_available_rt_min_bar_without_calling_it_close_price() -> None:
    result = evaluate_phase(
        "close_check",
        now=datetime(2026, 7, 10, 7, 10, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=True,
        intraday_rows=[
            {
                "market": "Ashare",
                "trade_date": "20260710",
                "bar_time": "2026-07-10 14:45:00",
                "collected_at": "2026-07-10T07:09:00+00:00",
            }
        ],
    )

    assert result["status"] == "green"
    assert result["checks"]["a_share_intraday"]["minimum_bar_time"] == "14:45"
    assert result["checks"]["a_share_intraday"]["price_semantics"] == "last_available_rt_min_not_official_close"


def test_preopen_gate_is_yellow_when_sla_artifact_is_missing() -> None:
    result = evaluate_phase(
        "preopen",
        now=datetime(2026, 7, 10, 0, 50, tzinfo=timezone.utc),
        db_ready=True,
        health_sla_ready=False,
        intraday_rows=[],
    )

    assert result["status"] == "yellow"
    assert result["gate"] == "closed"


def test_opening_gate_artifact_defaults_to_sharedsignals_logs(monkeypatch) -> None:
    monkeypatch.setenv("SHAREDSIGNALS_ROOT", "/tmp/sharedsignals-test")
    monkeypatch.delenv("WATCHDOG_INPUT_DIR", raising=False)

    assert output_path() == Path("/tmp/sharedsignals-test/logs/watchdog_inputs/opening_gate.json")


def test_first_sample_gate_rechecks_when_p0_bar_arrives_within_bounded_window(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 1, 35, tzinfo=timezone.utc)
    db_path = tmp_path / "marketdata.sqlite"
    artifact_path = tmp_path / "health_sla.json"
    _gate_db(db_path)
    _healthy_sla(artifact_path, now)
    current = now
    elapsed = 0.0
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        nonlocal current, elapsed
        sleeps.append(seconds)
        elapsed += seconds
        current += timedelta(seconds=seconds)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO market_bars_intraday VALUES (?, ?, ?, ?, ?)",
                ("Ashare", "000001.SZ", "20260714", "202607140930", current.isoformat()),
            )

    result = opening_gate.collect_gate_with_retry(
        "morning_first_sample",
        db_path=db_path,
        artifact_path=artifact_path,
        retry_interval_seconds=5,
        retry_window_seconds=20,
        now_fn=lambda: current,
        monotonic_fn=lambda: elapsed,
        sleep_fn=sleep,
    )

    assert result["status"] == "green"
    assert result["attempt_count"] == 2
    assert result["retry"]["reason"] == "sample_arrived_within_retry_window"
    assert sleeps == [5]


def test_first_sample_gate_does_not_retry_database_or_sla_failure(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 1, 35, tzinfo=timezone.utc)
    sleeps: list[float] = []

    result = opening_gate.collect_gate_with_retry(
        "morning_first_sample",
        db_path=tmp_path / "missing.sqlite",
        artifact_path=tmp_path / "missing-health-sla.json",
        retry_interval_seconds=5,
        retry_window_seconds=20,
        now_fn=lambda: now,
        monotonic_fn=lambda: 0.0,
        sleep_fn=sleeps.append,
    )

    assert result["status"] == "red"
    assert result["attempt_count"] == 1
    assert result["retry"]["reason"] == "ineligible_failure"
    assert sleeps == []
