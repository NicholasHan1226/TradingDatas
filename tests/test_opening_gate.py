from datetime import datetime, timezone
from pathlib import Path

from tools.opening_gate import evaluate_phase, output_path


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
