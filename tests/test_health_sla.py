from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

from tools import health_sla


def _db(
    tmp_path,
    *,
    now: datetime | None = None,
    daily_age_hours: int = 1,
    event_age_hours: int = 40,
    pm_age_hours: float = 0.1,
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
    db_path = _db(tmp_path, now=now, event_age_hours=40, pm_age_hours=0.1)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert report["summary"]["notice"] == 1
    assert report["violations"][0]["table"] == "market_events"
    assert report["violations"][0]["severity"] == "notice"


def test_research_event_missing_or_empty_degrades_health(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-01T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (collected_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "degraded"
    assert report["summary"]["notice"] == 1
    assert report["summary"]["missing_or_empty"] == 1
    assert report["violations"][0]["table"] == "market_events"
    assert report["violations"][0]["status"] == "empty"


def test_trading_price_staleness_is_critical(tmp_path, monkeypatch):
    db_path = _db(tmp_path, event_age_hours=1, pm_age_hours=1)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla()

    assert report["status"] == "critical"
    assert report["summary"]["critical"] == 1
    assert report["violations"][0]["table"] == "market_pm_prices"
    assert report["violations"][0]["severity"] == "critical"


def test_prediction_market_prices_within_45_minutes_are_fresh(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-01T04:00:00+00:00")
    db_path = _db(tmp_path, now=now, event_age_hours=1, pm_age_hours=40 / 60)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not [item for item in report["violations"] if item["table"] == "market_pm_prices"]


def test_us_independence_day_observed_gap_does_not_false_alarm(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-07T02:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260706"),
            ("US", "20260702"),
            ("Global", "20260703"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


def test_us_daily_still_critical_after_two_trading_days_lag(tmp_path, monkeypatch):
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
            ("US", "20260702"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "critical"
    assert any(
        item.get("market") == "US"
        and item.get("trading_days_behind") == 2
        and item.get("expected_latest_trade_date") == "20260707"
        for item in report["violations"]
    )


def test_global_daily_waits_until_scheduled_collection_window(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-07T00:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260706"),
            ("Global", "20260703"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


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
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
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
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "critical"
    assert any(
        item.get("table") == "market_bars_daily" and item.get("market") == "US"
        for item in report["violations"]
    )


def test_us_daily_sla_allows_monday_before_us_session_updates(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-06T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260706"),
            ("US", "20260702"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


def test_daily_sla_allows_monday_intraday_before_eod_daily_update(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-06T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.executemany(
        "INSERT INTO market_bars_daily VALUES (?, ?)",
        [
            ("Ashare", "20260703"),
            ("Futures", "20260703"),
        ],
    )
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


def test_crypto_daily_stale_uses_intraday_freshness(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-08T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (market TEXT, collected_at TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?, ?)", ("Crypto", "20260705"))
    conn.execute("INSERT INTO market_bars_intraday VALUES (?, ?)", ("Crypto", (now - timedelta(minutes=10)).isoformat()))
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not report["violations"]


def test_crypto_intraday_within_45_minutes_is_fresh(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-08T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (market TEXT, collected_at TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?, ?)", ("Crypto", "20260708"))
    conn.execute("INSERT INTO market_bars_intraday VALUES (?, ?)", ("Crypto", (now - timedelta(minutes=40)).isoformat()))
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not [item for item in report["violations"] if item.get("market") == "Crypto"]


def test_crypto_intraday_staleness_is_critical(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-08T04:00:00+00:00")
    path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_bars_daily (market TEXT, trade_date TEXT)")
    conn.execute("CREATE TABLE market_bars_intraday (market TEXT, collected_at TEXT)")
    conn.execute("CREATE TABLE market_events (event_time TEXT)")
    conn.execute("CREATE TABLE market_factors (trade_date TEXT)")
    conn.execute("CREATE TABLE market_pm_prices (updated_at TEXT)")
    conn.execute("INSERT INTO market_bars_daily VALUES (?, ?)", ("Crypto", "20260708"))
    conn.execute("INSERT INTO market_bars_intraday VALUES (?, ?)", ("Crypto", (now - timedelta(hours=2)).isoformat()))
    conn.execute("INSERT INTO market_events VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_factors VALUES (?)", ((now - timedelta(hours=1)).isoformat(),))
    conn.execute("INSERT INTO market_pm_prices VALUES (?)", ((now - timedelta(minutes=10)).isoformat(),))
    conn.commit()
    conn.close()
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "critical"
    assert any(
        item.get("table") == "market_bars_intraday"
        and item.get("market") == "Crypto"
        and item.get("source") == "market_bars_intraday_collected_at"
        for item in report["violations"]
    )


def _add_ashare_intraday_coverage(path, *, fresh_symbols: int, universe_symbols: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE market_assets (market TEXT, symbol TEXT, name TEXT, asset_type TEXT)"
    )
    conn.execute(
        """
        CREATE TABLE market_bars_intraday (
            market TEXT,
            symbol TEXT,
            trade_date TEXT,
            bar_time TEXT,
            interval TEXT,
            collected_at TEXT
        )
        """
    )
    symbols = [f"00{index:04d}.SZ" for index in range(universe_symbols)]
    conn.executemany(
        "INSERT INTO market_assets VALUES (?, ?, ?, ?)",
        [("Ashare", symbol, f"stock-{index}", "stock") for index, symbol in enumerate(symbols)],
    )
    conn.executemany(
        "INSERT INTO market_bars_intraday VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("Ashare", symbol, "20260710", "2026-07-10 13:30:00", "5min", "2026-07-10T05:30:10+00:00")
            for symbol in symbols[:fresh_symbols]
        ],
    )
    conn.commit()
    conn.close()


def test_ashare_intraday_partial_coverage_is_critical(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-10T05:32:00+00:00")
    path = _db(tmp_path, now=now, event_age_hours=1, pm_age_hours=0.1)
    _add_ashare_intraday_coverage(path, fresh_symbols=30, universe_symbols=100)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    violation = next(item for item in report["violations"] if item.get("market") == "Ashare")
    assert report["status"] == "critical"
    assert violation["source"] == "ashare_intraday_coverage"
    assert violation["fresh_symbols"] == 30
    assert violation["universe_symbols"] == 100
    assert violation["coverage_ratio"] == 0.3


def test_ashare_intraday_full_coverage_is_healthy(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-10T05:32:00+00:00")
    path = _db(tmp_path, now=now, event_age_hours=1, pm_age_hours=0.1)
    _add_ashare_intraday_coverage(path, fresh_symbols=90, universe_symbols=100)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    assert report["status"] == "ok"
    assert not [item for item in report["violations"] if item.get("market") == "Ashare"]


def test_ashare_intraday_zero_coverage_is_critical(tmp_path, monkeypatch):
    now = datetime.fromisoformat("2026-07-10T05:32:00+00:00")
    path = _db(tmp_path, now=now, event_age_hours=1, pm_age_hours=0.1)
    _add_ashare_intraday_coverage(path, fresh_symbols=0, universe_symbols=100)
    monkeypatch.setenv("MARKETDATA_SQLITE", str(path))

    report = health_sla.check_sla(now=now)

    violation = next(item for item in report["violations"] if item.get("market") == "Ashare")
    assert report["status"] == "critical"
    assert violation["status"] == "empty"
    assert violation["severity"] == "critical"


def test_critical_alert_timeout_does_not_abort_report(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="email_sender", timeout=15)

    monkeypatch.setattr(health_sla.subprocess, "run", fail)

    assert health_sla.send_critical_alert({"status": "critical", "violations": [{}]}) is False
