from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from tools import health_sla


def _db(
    tmp_path,
    *,
    now: datetime | None = None,
    daily_age_hours: int = 1,
    event_age_hours: int = 40,
    pm_age_hours: int = 1,
):
    path = tmp_path / "marketdata.sqlite"
    now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?)", ((now - timedelta(hours=daily_age_hours)).isoformat(),))
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=event_age_hours)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(hours=pm_age_hours)).isoformat(),))
    conn.commit()
    conn.close()
    return path


def test_research_event_staleness_is_notice_not_degraded(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-01T04:00:00+00:00")
    db_path = _db(tmp_path, now=now, event_age_hours=40, pm_age_hours=1)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert report["summary"]["notice"] == 1
    assert report["violations"][0]["table"] == "market_events"
    assert report["violations"][0]["severity"] == "notice"


def test_trading_price_staleness_is_critical(tmp_path, monkeypatch):
    db_path = _db(tmp_path, event_age_hours=1, pm_age_hours=8)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla()

    assert report["status"] == "critical"
    assert report["summary"]["critical"] == 1
    assert report["violations"][0]["table"] == "market_pm_prices"
    assert report["violations"][0]["severity"] == "critical"


def test_weekend_daily_sla_expands_without_relaxing_pm_prices(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-05T04:00:00+00:00")
    db_path = _db(tmp_path, now=now, daily_age_hours=80, event_age_hours=1, pm_age_hours=8)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla(now=now)

    tables = {item["table"] for item in report["violations"]}
    assert "market_bars_daily" not in tables
    assert "market_pm_prices" in tables
    assert report["status"] == "critical"


def test_table_query_errors_are_reported_not_silently_ok(tmp_path, monkeypatch):
    path = tmp_path / "marketdata.sqlite"
    sqlite3.connect(path).close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=datetime.fromisoformat("2026-07-01T04:00:00+00:00"))

    assert report["status"] == "critical"
    assert report["summary"]["critical"] >= 1
    assert any(item["status"] == "error" for item in report["violations"])


def test_market_factors_uses_collected_at_before_period_event_time(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-05T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (event_time TEXT, collected_at TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?, ?)", ("2026Q1", (now - timedelta(hours=1)).isoformat()))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


def test_market_bars_daily_checks_us_freshness_by_market(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-08T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260708"),
            ("US", "20260703"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "critical"
    assert any(
        item.get("table") == "market_bars_daily" and item.get("market") == "US"
        for item in report["violations"]
    )
