from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import patrol


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
