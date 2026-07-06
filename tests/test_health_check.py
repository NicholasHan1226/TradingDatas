from __future__ import annotations

import os
import json
import sqlite3
import subprocess
import time
from datetime import datetime, timezone

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
        health_check,
        "_load_health_sla_report",
        lambda: {"status": "degraded", "sla_status": "degraded", "summary": {"warning": 1}, "violations": [{"table": "market_events"}]},
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


def test_health_sla_report_reader_uses_last_valid_payload(tmp_path, monkeypatch) -> None:
    root = tmp_path / "SharedSignals"
    report = root / "logs" / "watchdog_inputs" / "health_sla.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"status": "sent", "provider": "cloudflare"})
        + "\n"
        + json.dumps({"status": "critical", "summary": {"critical": 1}, "violations": [{"table": "market_pm_prices"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(health_check, "SS", root)

    result = health_check._load_health_sla_report()

    assert result["status"] == "degraded"
    assert result["sla_status"] == "critical"
    assert result["summary"]["critical"] == 1


def test_data_freshness_uses_sla_and_crypto_intraday(tmp_path, monkeypatch) -> None:
    root = tmp_path / "SharedSignals"
    runtime = tmp_path / "runtime"
    db = runtime / "read_model" / "marketdata.sqlite"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (market TEXT, collected_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260706"),
            ("US", "20260702"),
            ("Global", "20260703"),
            ("Crypto", "20260701"),
        ],
    )
    conn.execute("INSERT INTO market_bars_intraday VALUES (?, ?)", ("Crypto", datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    monkeypatch.setattr(health_check, "SS", root)
    monkeypatch.setattr(health_check, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(
        health_check,
        "_load_health_sla_report",
        lambda: {"status": "ok", "sla_status": "ok", "summary": {}, "violations": []},
    )

    result = health_check._check_data_freshness()

    assert result["status"] == "ok"
    assert result["markets"]["US"]["status"] == "ok"
    assert result["markets"]["Global"]["status"] == "ok"
    assert result["markets"]["Crypto"]["status"] == "ok"
    assert result["markets"]["Crypto"]["source"] == "market_bars_intraday_collected_at"
