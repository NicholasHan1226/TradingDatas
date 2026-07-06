from __future__ import annotations

import os
import subprocess
import time

from tools import health_sla
from tools import health_check


def test_cron_activity_checks_sharedsignals_cron_log_dir(tmp_path, monkeypatch) -> None:
    root = tmp_path / "SharedSignals"
    cron_dir = root / "logs" / "cron"
    cron_dir.mkdir(parents=True)
    log_path = cron_dir / "collectors.log"
    log_path.write_text("ok\n", encoding="utf-8")
    now = time.time()
    os.utime(log_path, (now, now))
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(health_check, "SS", root)
    monkeypatch.setattr(health_check, "RUNTIME_ROOT", runtime_root)

    result = health_check._check_cron_activity()

    assert result["status"] == "ok"
    assert result["active_logs"] == 1
    assert str(cron_dir) in result["checked_dirs"]


def test_cron_activity_reports_find_errors(tmp_path, monkeypatch) -> None:
    root = tmp_path / "SharedSignals"
    cron_dir = root / "logs" / "cron"
    cron_dir.mkdir(parents=True)
    monkeypatch.setattr(health_check, "SS", root)
    monkeypatch.setattr(health_check, "RUNTIME_ROOT", tmp_path / "runtime")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="permission denied")

    monkeypatch.setattr(health_check.subprocess, "run", fake_run)

    result = health_check._check_cron_activity()

    assert result["status"] == "degraded"
    assert result["active_logs"] == 0
    assert result["errors"]


def test_health_status_includes_per_table_sla(monkeypatch) -> None:
    monkeypatch.setattr(
        health_sla,
        "check_sla",
        lambda: {"status": "degraded", "summary": {"warning": 1}, "violations": [{"table": "market_events"}]},
    )

    result = health_check.get_health_status(
        check_functions=False,
        check_data_freshness=False,
        check_cron=False,
        check_arch=False,
        check_compile=False,
    )

    assert result["status"] == "degraded"
    assert result["checks"]["sla"]["status"] == "degraded"
    assert result["checks"]["sla"]["sla_status"] == "degraded"
