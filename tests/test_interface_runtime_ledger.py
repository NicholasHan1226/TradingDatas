from __future__ import annotations

from tools.interface_runtime_ledger import record_tushare_stats


def test_runtime_ledger_distinguishes_success_empty_failure_and_unobserved(tmp_path):
    path = tmp_path / "interface_runtime.json"
    stats = {
        "daily": {
            "rows": 10,
            "calls": 1,
            "failure_count": 0,
            "sqlite_rows": 10,
            "sqlite_status": "ok",
            "sqlite_errors": [],
        },
        "news": {
            "rows": 0,
            "calls": 1,
            "failure_count": 0,
            "sqlite_rows": 0,
            "sqlite_status": "empty",
            "sqlite_errors": [],
        },
        "margin": {
            "rows": 0,
            "calls": 1,
            "failure_count": 1,
            "sqlite_rows": 0,
            "sqlite_status": "empty",
            "sqlite_errors": [],
        },
        "_tier_summary": {},
    }

    report = record_tushare_stats(
        stats,
        tier="P1_eod_daily",
        started_at="2026-07-10T08:00:00+00:00",
        finished_at="2026-07-10T08:01:00+00:00",
        expected_api_names={"daily", "news", "margin", "weekly"},
        output_path=path,
    )

    assert report["status"] == "red"
    assert report["summary"] == {
        "expected": 4,
        "observed": 3,
        "success": 2,
        "empty": 1,
        "degraded": 0,
        "failed": 1,
        "unobserved": 1,
    }
    assert report["interfaces"]["daily"]["last_success"] == "2026-07-10T08:01:00+00:00"
    assert report["interfaces"]["news"]["empty_reason"] == "provider_returned_no_rows"
    assert report["interfaces"]["margin"]["status"] == "failed"
    assert report["unobserved_api_names"] == ["weekly"]


def test_runtime_ledger_preserves_last_success_after_later_failure(tmp_path):
    path = tmp_path / "interface_runtime.json"
    success = {
        "daily": {
            "rows": 5,
            "calls": 1,
            "failure_count": 0,
            "sqlite_rows": 5,
            "sqlite_status": "ok",
            "sqlite_errors": [],
        }
    }
    failure = {
        "daily": {
            "rows": 0,
            "calls": 1,
            "failure_count": 1,
            "sqlite_rows": 0,
            "sqlite_status": "empty",
            "sqlite_errors": [],
        }
    }

    record_tushare_stats(
        success,
        tier="P1_eod_daily",
        started_at="2026-07-10T08:00:00+00:00",
        finished_at="2026-07-10T08:01:00+00:00",
        expected_api_names={"daily"},
        output_path=path,
    )
    report = record_tushare_stats(
        failure,
        tier="P1_eod_daily",
        started_at="2026-07-11T08:00:00+00:00",
        finished_at="2026-07-11T08:01:00+00:00",
        expected_api_names={"daily"},
        output_path=path,
    )

    assert report["interfaces"]["daily"]["last_success"] == "2026-07-10T08:01:00+00:00"
    assert report["interfaces"]["daily"]["last_attempt"] == "2026-07-11T08:01:00+00:00"
