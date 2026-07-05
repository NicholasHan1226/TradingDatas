from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import patrol


def test_patrol_thresholds_can_be_overridden_by_env(monkeypatch):
    monkeypatch.setenv("PATROL_MAX_STAGING_FILES", "25")

    reloaded = importlib.reload(patrol)

    assert reloaded.MAX_STAGING_FILES == 25
    monkeypatch.delenv("PATROL_MAX_STAGING_FILES")
    importlib.reload(patrol)


def test_data_freshness_checks_pm_prices_and_iso_dates(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE market_bars_daily (trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (collected_at TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    stale_iso = (now - timedelta(days=3)).isoformat()
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", (stale_iso,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(patrol, "DB_PATH", db_path)

    result = patrol.check_data_freshness()

    assert result["status"] == "stale"
    assert result["latest_date"] == stale_iso
    assert result["days_behind"] >= 2
