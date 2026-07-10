from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import patrol
import heal


def test_data_artifact_guard_detects_retired_files(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    offender = staging / "retired.ndjson"
    offender.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(patrol, "STAGING_ROOT", staging)
    monkeypatch.setattr(patrol, "COLD_STORAGE_ROOT", tmp_path / "cold")

    result = patrol.check_data_artifact_guard()

    assert result["status"] == "alert"
    assert result["value"] == 1
    assert str(offender) in result["offenders"]


def test_data_freshness_checks_pm_prices_and_iso_dates(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE market_bars_daily (trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (collected_at TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (collected_at TEXT)")
    stale_iso = (now - timedelta(days=3)).isoformat()
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", (stale_iso,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(patrol, "DB_PATH", db_path)

    result = patrol.check_data_freshness()

    assert result["status"] == "stale"
    assert result["latest_date"] == stale_iso
    assert result["days_behind"] >= 2


def test_sqlite_patrol_uses_shallow_corruption_probe(tmp_path, monkeypatch):
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sample (id INTEGER)")
    conn.commit()
    conn.close()
    calls = []

    def fake_probe(path, *, deep_check=True):
        calls.append((path, deep_check))
        return {
            "status": "ok",
            "integrity_ok": True,
            "integrity_msg": "shallow_open_ok",
        }

    monkeypatch.setattr(patrol, "DB_PATH", db_path)
    monkeypatch.setattr(patrol.sqlite_recovery, "check_sqlite_corruption", fake_probe)

    result = patrol.check_sqlite_health()

    assert calls == [(db_path, False)]
    assert result["status"] == "ok"
    assert result["integrity_msg"] == "shallow_open_ok"


def test_heal_verification_uses_shallow_corruption_probe(tmp_path, monkeypatch):
    db_path = tmp_path / "marketdata.sqlite"
    db_path.write_bytes(b"sqlite-placeholder")
    calls = []

    def fake_probe(path, *, deep_check=True):
        calls.append((path, deep_check))
        return {"status": "ok"}

    monkeypatch.setattr(heal, "DB_PATH", db_path)
    monkeypatch.setattr(heal.sqlite_recovery, "check_sqlite_corruption", fake_probe)

    result = heal._verify_heal("sqlite_health", {})

    assert calls == [(db_path, False)]
    assert result["verified"] is True
