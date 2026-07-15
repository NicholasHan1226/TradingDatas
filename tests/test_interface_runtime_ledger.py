from __future__ import annotations

import tools.interface_runtime_ledger as ledger_module
from tools.interface_runtime_ledger import (
    expected_tushare_api_names,
    record_tushare_stats,
)


def test_runtime_ledger_expected_names_come_from_registry_authority(
    monkeypatch,
) -> None:
    registry_names = frozenset({"registry_only", "rt_fut_min"})
    monkeypatch.setattr(
        ledger_module,
        "TUSHARE_ALLOWED_API_NAMES",
        registry_names,
        raising=False,
    )

    assert expected_tushare_api_names() == set(registry_names)


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
        "success": 1,
        "empty": 1,
        "degraded": 0,
        "failed": 1,
        "unobserved": 1,
    }
    assert report["interfaces"]["daily"]["last_success"] == "2026-07-10T08:01:00+00:00"
    assert report["interfaces"]["news"]["status"] == "empty"
    assert report["interfaces"]["news"]["last_success"] is None
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


def test_runtime_ledger_empty_is_yellow_and_does_not_advance_last_success(tmp_path):
    path = tmp_path / "interface_runtime.json"
    success = {
        "income": {
            "rows": 3,
            "calls": 1,
            "failure_count": 0,
            "sqlite_rows": 3,
            "sqlite_status": "ok",
            "sqlite_errors": [],
        }
    }
    empty = {
        "income": {
            "rows": 0,
            "calls": 1,
            "failure_count": 0,
            "sqlite_rows": 0,
            "sqlite_status": "empty",
            "sqlite_errors": [],
        }
    }

    record_tushare_stats(
        success,
        tier="P2_financial_daily",
        started_at="2026-07-10T08:00:00+00:00",
        finished_at="2026-07-10T08:01:00+00:00",
        expected_api_names={"income"},
        output_path=path,
    )
    report = record_tushare_stats(
        empty,
        tier="P2_financial_daily",
        started_at="2026-07-11T08:00:00+00:00",
        finished_at="2026-07-11T08:01:00+00:00",
        expected_api_names={"income"},
        output_path=path,
    )

    assert report["status"] == "yellow"
    assert report["summary"]["success"] == 0
    assert report["summary"]["empty"] == 1
    assert report["interfaces"]["income"]["status"] == "empty"
    assert report["interfaces"]["income"]["last_success"] == "2026-07-10T08:01:00+00:00"
    assert report["interfaces"]["income"]["last_attempt"] == "2026-07-11T08:01:00+00:00"


def test_runtime_ledger_treats_legacy_empty_success_as_yellow(tmp_path):
    path = tmp_path / "interface_runtime.json"
    path.write_text(
        '{"interfaces":{"income":{"status":"success","empty_reason":"provider_returned_no_rows"}}}\n',
        encoding="utf-8",
    )

    report = record_tushare_stats(
        {},
        tier="P2_financial_daily",
        started_at="2026-07-11T08:00:00+00:00",
        finished_at="2026-07-11T08:01:00+00:00",
        expected_api_names={"income"},
        output_path=path,
    )

    assert report["status"] == "yellow"
    assert report["summary"]["success"] == 0
    assert report["summary"]["empty"] == 1


def test_runtime_ledger_zero_completed_calls_is_degraded_not_empty(tmp_path):
    path = tmp_path / "interface_runtime.json"
    report = record_tushare_stats(
        {
            "income": {
                "rows": 0,
                "calls": 0,
                "failure_count": 0,
                "sqlite_rows": 0,
                "sqlite_status": "empty",
                "sqlite_errors": [],
            }
        },
        tier="P2_financial_daily",
        started_at="2026-07-11T08:00:00+00:00",
        finished_at="2026-07-11T08:01:00+00:00",
        expected_api_names={"income"},
        output_path=path,
    )

    assert report["status"] == "yellow"
    assert report["summary"]["degraded"] == 1
    assert report["summary"]["empty"] == 0
    assert report["interfaces"]["income"]["status"] == "degraded"
    assert (
        report["interfaces"]["income"]["status_reason"] == "no_provider_call_completed"
    )
    assert report["interfaces"]["income"]["empty_reason"] == ""
