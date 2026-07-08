from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.check_cn_futures_5min_freshness import (
    CN_TZ,
    _parse_datetime,
    _session_info,
    check_freshness,
    main,
    parse_args,
)


def _create_test_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """Create a minimal SQLite DB with market_bars_intraday rows."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE market_bars_intraday (
                market TEXT,
                symbol TEXT,
                bar_time TEXT,
                trade_date TEXT,
                interval TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                provider TEXT,
                source_file TEXT,
                collected_at TEXT,
                raw_json TEXT
            )
            """
        )
        for market, symbol, bar_time in rows:
            conn.execute(
                """
                INSERT INTO market_bars_intraday
                (market, symbol, bar_time, trade_date, interval, provider)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (market, symbol, bar_time, bar_time[:10].replace("-", ""), "5min", "tushare_rt_fut_min"),
            )
        conn.commit()
    finally:
        conn.close()


def test_parse_datetime_handles_space_separated_local_time() -> None:
    dt = _parse_datetime("2026-07-04 09:05:00")
    assert dt is not None
    assert dt.tzinfo == CN_TZ
    assert dt.isoformat() == "2026-07-04T09:05:00+08:00"


def test_parse_datetime_handles_iso_with_timezone() -> None:
    dt = _parse_datetime("2026-07-04T01:05:00+00:00")
    assert dt is not None
    assert dt.isoformat() == "2026-07-04T09:05:00+08:00"


def test_session_info_day_session() -> None:
    now = datetime(2026, 7, 3, 10, 5, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "day"
    assert info["in_session"] is True
    assert info["next_session_start"] == datetime(2026, 7, 3, 9, 0, tzinfo=CN_TZ)


def test_session_info_night_session_same_day() -> None:
    now = datetime(2026, 7, 3, 21, 5, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "night"
    assert info["in_session"] is True
    assert info["next_session_start"] == datetime(2026, 7, 3, 21, 0, tzinfo=CN_TZ)


def test_session_info_night_session_after_midnight() -> None:
    now = datetime(2026, 7, 4, 1, 30, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "night"
    assert info["in_session"] is True
    assert info["next_session_start"] == datetime(2026, 7, 3, 21, 0, tzinfo=CN_TZ)


def test_session_info_closed_between_sessions() -> None:
    now = datetime(2026, 7, 3, 18, 0, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "closed"
    assert info["in_session"] is False
    assert info["next_session_start"] == datetime(2026, 7, 3, 21, 0, tzinfo=CN_TZ)


def test_session_info_closed_before_day_session() -> None:
    now = datetime(2026, 7, 3, 8, 0, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "closed"
    assert info["in_session"] is False
    assert info["next_session_start"] == datetime(2026, 7, 3, 9, 0, tzinfo=CN_TZ)


def test_session_info_sunday_points_to_next_weekday_day_session() -> None:
    now = datetime(2026, 7, 5, 2, 53, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "closed"
    assert info["in_session"] is False
    assert info["next_session_start"] == datetime(2026, 7, 6, 9, 0, tzinfo=CN_TZ)


def test_session_info_saturday_evening_points_to_next_weekday_day_session() -> None:
    now = datetime(2026, 7, 4, 18, 0, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "closed"
    assert info["in_session"] is False
    assert info["next_session_start"] == datetime(2026, 7, 6, 9, 0, tzinfo=CN_TZ)


def test_check_freshness_reports_fresh_during_day_session(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:05:00")])

    now = datetime(2026, 7, 3, 9, 8, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "fresh"
    assert report["latest_bar_time"] == "2026-07-03T09:05:00+08:00"
    assert report["latest_bar_age_minutes"] == 3.0
    assert report["session"]["current"] == "day"
    assert report["session"]["next_session_has_data"] is True


def test_check_freshness_reports_stale_when_aged_out(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:00:00")])

    now = datetime(2026, 7, 3, 9, 15, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "stale"
    assert report["latest_bar_age_minutes"] == 15.0
    assert "latest bar is 15.0 minutes old" in report["reasons"][0]


def test_check_freshness_reports_stale_when_session_has_no_data(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    # Only yesterday's night session data, nothing for the current day session.
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-02 22:00:00")])

    now = datetime(2026, 7, 3, 10, 0, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=60)

    assert report["status"] == "stale"
    assert report["session"]["current"] == "day"
    assert report["session"]["next_session_has_data"] is False
    assert "current trading session has no 5min bars yet" in report["reasons"]


def test_check_freshness_reports_no_data_for_empty_table(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [])

    now = datetime(2026, 7, 3, 9, 5, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "no_data"
    assert report["latest_bar_time"] is None


def test_check_freshness_reports_error_for_missing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "does_not_exist.sqlite"

    now = datetime(2026, 7, 3, 9, 5, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "error"
    assert "database missing" in report["error"]


def test_check_freshness_counts_symbols_and_bars(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    rows = [
        ("Futures", "RB2609.SHF", "2026-07-03 09:05:00"),
        ("Futures", "CU2609.SHF", "2026-07-03 09:05:00"),
        ("Futures", "RB2609.SHF", "2026-07-03 09:00:00"),
    ]
    _create_test_db(db_path, rows)

    now = datetime(2026, 7, 3, 9, 6, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "fresh"
    assert report["symbol_count"] == 2
    assert report["total_bars"] == 3


def test_main_returns_zero_for_fresh_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:05:00")])

    code = main([
        "--sqlite-db", str(db_path),
        "--now", "2026-07-03T09:08:00+08:00",
        "--max-age-minutes", "10",
    ])
    out = capsys.readouterr().out

    assert code == 0
    assert "status: fresh" in out
    assert "RB2609" not in out  # human output does not list symbols


def test_main_returns_one_for_stale_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:00:00")])

    code = main([
        "--sqlite-db", str(db_path),
        "--now", "2026-07-03T09:15:00+08:00",
        "--max-age-minutes", "10",
    ])

    assert code == 1
    assert "status: stale" in capsys.readouterr().out


def test_main_returns_one_for_no_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [])

    code = main([
        "--sqlite-db", str(db_path),
        "--now", "2026-07-03T09:15:00+08:00",
        "--max-age-minutes", "10",
    ])

    assert code == 1
    assert "status: no_data" in capsys.readouterr().out


def test_main_emits_json_when_requested(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:05:00")])

    code = main([
        "--sqlite-db", str(db_path),
        "--now", "2026-07-03T09:08:00+08:00",
        "--json",
    ])
    out = capsys.readouterr().out

    assert code == 0
    assert '"status": "fresh"' in out
    assert '"latest_bar_time":' in out


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.sqlite_db == Path("/opt/investment/SharedSignals/runtime/read_model/marketdata.sqlite")
    assert args.max_age_minutes == 10
    assert args.json is False


def test_parse_args_custom_now() -> None:
    args = parse_args(["--now", "2026-07-04 09:05:00", "--max-age-minutes", "5", "--json"])
    assert args.now == datetime(2026, 7, 4, 9, 5, tzinfo=CN_TZ)
    assert args.max_age_minutes == 5
    assert args.json is True


def test_parse_args_space_separated_now_with_timezone() -> None:
    args = parse_args(["--now", "2026-07-04 01:05:00+00:00"])
    assert args.now == datetime(2026, 7, 4, 9, 5, tzinfo=CN_TZ)


# Lunch break session-info tests


def test_session_info_lunch_1131_to_1159() -> None:
    """11:31-11:59 should be recognised as lunch/closed, in_session=False."""
    now = datetime(2026, 7, 3, 11, 45, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "lunch"
    assert info["in_session"] is False


def test_session_info_lunch_preopen_1200_to_1259() -> None:
    """12:00-12:59 should be recognised as lunch_preopen, in_session=False."""
    now = datetime(2026, 7, 3, 12, 15, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "lunch_preopen"
    assert info["in_session"] is False


def test_session_info_afternoon_session_starts_at_1300() -> None:
    """13:00 starts the afternoon freshness window for shared CN futures checks."""
    now = datetime(2026, 7, 3, 13, 5, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "day"
    assert info["in_session"] is True


def test_session_info_afternoon_session_1330() -> None:
    """Afternoon session remains active at 13:30."""
    now = datetime(2026, 7, 3, 13, 35, tzinfo=CN_TZ)
    info = _session_info(now)
    assert info["current"] == "day"
    assert info["in_session"] is True


# Lunch break freshness tests


def test_check_freshness_not_stale_during_lunch_with_1130_bar(tmp_path: Path) -> None:
    """During lunch (12:15), an 11:30 bar should NOT be stale and should
    not return non-zero."""
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 11:30:00")])

    now = datetime(2026, 7, 3, 12, 15, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "fresh", f"unexpected status: {report}"
    assert report["session"]["current"] == "lunch_preopen"
    assert report["session"]["in_session"] is False


def test_main_returns_zero_during_lunch_with_1130_bar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() should return 0 during lunch (12:15) with an 11:30 bar."""
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 11:30:00")])

    code = main([
        "--sqlite-db", str(db_path),
        "--now", "2026-07-03T12:15:00+08:00",
        "--max-age-minutes", "10",
    ])

    assert code == 0, f"expected exit 0, got {code}"
    assert "status: fresh" in capsys.readouterr().out


# Preserve real day/night stale behaviour


def test_check_freshness_still_stale_in_day_session_when_aged(tmp_path: Path) -> None:
    """During day session (morning), stale-by-age should still apply."""
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 09:00:00")])

    now = datetime(2026, 7, 3, 9, 25, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "stale"
    assert report["session"]["in_session"] is True


def test_check_freshness_still_stale_in_day_afternoon_when_no_data(tmp_path: Path) -> None:
    """Afternoon session with only morning data → stale (no afternoon bars)."""
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 11:25:00")])

    now = datetime(2026, 7, 3, 13, 40, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "stale"
    assert report["session"]["current"] == "day"
    assert report["session"]["in_session"] is True


def test_check_freshness_still_stale_in_night_session_when_aged(tmp_path: Path) -> None:
    """During night session, stale-by-age should still apply."""
    db_path = tmp_path / "marketdata.sqlite"
    _create_test_db(db_path, [("Futures", "RB2609.SHF", "2026-07-03 21:00:00")])

    now = datetime(2026, 7, 3, 21, 25, tzinfo=CN_TZ)
    report = check_freshness(db_path, now=now, max_age_minutes=10)

    assert report["status"] == "stale"
    assert report["session"]["in_session"] is True
