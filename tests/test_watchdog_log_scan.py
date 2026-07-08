from __future__ import annotations

import os
import time
from pathlib import Path

from tools.watchdog import check_collector_status


def test_collector_status_detects_uppercase_error_and_db_lock(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "collectors.log"
    log_file.write_text(
        "[2026-07-04T18:00:00+08:00] START collectors tiers=P6_other_daily\n"
        "2026-07-04 18:00:43,531 WARNING SQLITE_ERRORS: "
        "[\'fund_basic:/tmp/fund_basic.csv:database is locked\']\n"
        "2026-07-04 18:00:43,531 ERROR Tushare sync failed threshold: "
        "api_failures=0 sqlite_failures=1\n",
        encoding="utf-8",
    )
    now = time.time()
    os.utime(log_file, (now, now))
    monkeypatch.delenv("WATCHDOG_COLLECTOR_LOG_EXCLUDE", raising=False)

    result = check_collector_status(log_dir, max_age_minutes=15)

    assert result["status"] == "critical"
    assert result["score_factor"] == 0.0
    assert result["failure_patterns"]
    patterns = set(result["failure_patterns"][0]["patterns"])
    assert "ERROR" in patterns
    assert "database is locked" in patterns


def test_collector_status_ignores_zero_error_counters_after_ok(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "collectors.log"
    log_file.write_text(
        "[2026-07-04T18:30:00+08:00] START collectors tiers=P4_macro_daily\n"
        "2026-07-04 18:30:38,570 INFO [P4_macro_daily] COMPLETE: "
        "17 APIs, api_failures=0/17, sqlite_errors=0, 10.9s total\n"
        "[2026-07-04T18:30:38+08:00] OK collectors\n",
        encoding="utf-8",
    )
    now = time.time()
    os.utime(log_file, (now, now))
    monkeypatch.delenv("WATCHDOG_COLLECTOR_LOG_EXCLUDE", raising=False)

    result = check_collector_status(log_dir, max_age_minutes=15)

    assert result["status"] == "ok"
    assert result["failure_patterns"] == []
