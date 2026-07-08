from __future__ import annotations

import sqlite3
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

from collectors.tushare.backfill_fut_daily import (
    build_command as build_backfill_command,
    generate_dates,
    run_backfill,
)
from tools.collect_cn_futures_daily import build_command, main, run_collection
from storage.schema import SCHEMA_SQL
from tools import collect_cn_futures_5min


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


def test_cn_futures_5min_sina_provider_writes_read_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Frame:
        empty = False

        def __init__(self, rows: list[dict[str, object]]) -> None:
            self._rows = rows

        def tail(self, limit: int) -> "_Frame":
            return _Frame(self._rows[-limit:])

        def to_dict(self, orient: str) -> list[dict[str, object]]:
            assert orient == "records"
            return list(self._rows)

    fake_akshare = types.SimpleNamespace(
        futures_zh_minute_sina=lambda symbol, period: _Frame(
            [
                {"datetime": "2026-07-03 14:50:00", "open": 3500, "high": 3510, "low": 3490, "close": 3505, "volume": 100, "hold": 1000},
                {"datetime": "2026-07-03 14:55:00", "open": 3505, "high": 3520, "low": 3500, "close": 3515, "volume": 120, "hold": 1001},
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

    summary = collect_cn_futures_5min.run_collection(
        trade_date="20260703",
        symbols=["RB2609.SHF"],
        freq="5MIN",
        provider=collect_cn_futures_5min.SINA_PROVIDER,
        dry_run=False,
        sqlite_db_path=db_path,
    )

    assert summary["state"] == "ok"
    assert summary["provider"] == "sina_futures_minute"
    assert summary["sqlite_rows"] == 2
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT symbol, close, provider FROM market_bars_intraday WHERE market='Futures' ORDER BY bar_time"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("RB2609.SHF", 3505.0, "sina_futures_minute"),
        ("RB2609.SHF", 3515.0, "sina_futures_minute"),
    ]
