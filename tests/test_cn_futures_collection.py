from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from collectors.tushare.backfill_fut_daily import (
    build_command as build_backfill_command,
    generate_dates,
    run_backfill,
)
from tools.collect_cn_futures_daily import build_command, main, run_collection


def test_daily_wrapper_builds_fut_daily_only_command() -> None:
    cmd = build_command("20260703")

    assert cmd[1].endswith("collectors/tushare/sync_daily.py")
    assert "--tier" in cmd
    assert "P6_other_daily" in cmd
    assert "--only-api" in cmd
    assert "fut_daily" in cmd
    assert "--trade-date" in cmd
    assert "20260703" in cmd
    assert "--exit-on-failure" in cmd
    assert "--dry-run" not in cmd


def test_daily_wrapper_has_no_csv_only_success_switch() -> None:
    cmd = build_command("20260703")

    assert "--no-sqlite-bridge" not in cmd


def test_daily_wrapper_dry_run_does_not_spawn_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert run_collection("20260703", dry_run=True) == 0
    assert calls == []


def test_daily_wrapper_rejects_bad_trade_date() -> None:
    assert main(["--trade-date", "2026-07-03", "--dry-run"]) == 2


def test_backfill_generate_dates_skips_weekends() -> None:
    dates = generate_dates(
        datetime.strptime("20260703", "%Y%m%d"),
        datetime.strptime("20260706", "%Y%m%d"),
        skip_weekends=True,
    )

    assert dates == ["20260703", "20260706"]


def test_backfill_builds_existing_sync_daily_command() -> None:
    cmd = build_backfill_command("python3", "20260703")

    assert cmd[0] == "python3"
    assert cmd[1].endswith("collectors/tushare/sync_daily.py")
    assert "--only-api" in cmd
    assert "fut_daily" in cmd
    assert "--trade-date" in cmd
    assert "20260703" in cmd
    assert "--no-sqlite-bridge" not in cmd


def test_backfill_summary_continues_after_failed_day(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        cmd: list[str],
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture_output, text
        returncode = 2 if "20260702" in cmd else 0
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = run_backfill(
        "20260701",
        "20260703",
        skip_weekends=False,
        python_bin="python3",
    )

    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["failed"][0]["date"] == "20260702"


def test_backfill_fail_fast_stops_after_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run(
        cmd: list[str],
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture_output, text
        trade_date = cmd[cmd.index("--trade-date") + 1]
        seen.append(trade_date)
        returncode = 2 if trade_date == "20260702" else 0
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = run_backfill(
        "20260701",
        "20260703",
        skip_weekends=False,
        fail_fast=True,
        python_bin="python3",
    )

    assert seen == ["20260701", "20260702"]
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1
