#!/usr/bin/env python3
"""Check freshness of China futures 5-minute bars in the SharedSignals read model.

Reports whether rt_fut_min / market_bars_intraday Futures 5min data is fresh,
with optional next-session verification. This is a data-only health check:
it does not make trading decisions or trigger execution.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.csv_bridge import DEFAULT_SQLITE_PATH  # noqa: E402

logger = logging.getLogger(__name__)

CN_TZ = timezone(timedelta(hours=8))
DAY_SESSION_START = time(9, 0)
DAY_SESSION_END = time(15, 0)
NIGHT_SESSION_START = time(21, 0)
NIGHT_SESSION_END = time(2, 30)

DEFAULT_MAX_AGE_MINUTES = 10


def _next_weekday_on_or_after(day):
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _next_day_session_start_after(day):
    next_day = day + timedelta(days=1)
    return datetime.combine(_next_weekday_on_or_after(next_day), DAY_SESSION_START, tzinfo=CN_TZ)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a bar/collected timestamp and normalise to CN timezone."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Tushare rt_fut_min trade_time often uses a space separator.
    text = text.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN_TZ)
    return dt.astimezone(CN_TZ)


def _now_cn(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(CN_TZ)


def _session_info(now_cn: datetime) -> dict[str, Any]:
    """Determine current/next CN futures trading session in China local time."""
    t = now_cn.time()
    today = now_cn.date()
    weekday = today.weekday()

    if weekday >= 5:
        if weekday == 5 and t <= NIGHT_SESSION_END:
            yesterday = today - timedelta(days=1)
            return {
                "current": "night",
                "next_session_start": datetime.combine(yesterday, NIGHT_SESSION_START, tzinfo=CN_TZ),
                "in_session": True,
            }
        return {
            "current": "closed",
            "next_session_start": datetime.combine(_next_weekday_on_or_after(today), DAY_SESSION_START, tzinfo=CN_TZ),
            "in_session": False,
        }

    # Morning session: 09:00-11:30
    if DAY_SESSION_START <= t <= time(11, 30):
        return {
            "current": "day",
            "next_session_start": datetime.combine(today, DAY_SESSION_START, tzinfo=CN_TZ),
            "in_session": True,
        }

    # Lunch break phase 1: 11:31-11:59
    if time(11, 31) <= t <= time(11, 59):
        return {
            "current": "lunch",
            "next_session_start": datetime.combine(today, time(13, 0), tzinfo=CN_TZ),
            "in_session": False,
        }

    # Lunch pre-open phase: 12:00-12:59
    if time(12, 0) <= t <= time(12, 59):
        return {
            "current": "lunch_preopen",
            "next_session_start": datetime.combine(today, time(13, 0), tzinfo=CN_TZ),
            "in_session": False,
        }

    # Afternoon session: 13:00-15:00. Some CN futures products open at 13:00,
    # so the shared freshness check must not suppress 13:00-13:29 stale alerts.
    if time(13, 0) <= t <= DAY_SESSION_END:
        return {
            "current": "day",
            "next_session_start": datetime.combine(today, time(13, 0), tzinfo=CN_TZ),
            "in_session": True,
        }

    if t >= NIGHT_SESSION_START:
        return {
            "current": "night",
            "next_session_start": datetime.combine(today, NIGHT_SESSION_START, tzinfo=CN_TZ),
            "in_session": True,
        }

    if t <= NIGHT_SESSION_END:
        yesterday = today - timedelta(days=1)
        return {
            "current": "night",
            "next_session_start": datetime.combine(yesterday, NIGHT_SESSION_START, tzinfo=CN_TZ),
            "in_session": True,
        }

    if time(15, 0) < t < time(21, 0):
        next_start = (
            datetime.combine(today, NIGHT_SESSION_START, tzinfo=CN_TZ)
            if weekday <= 4
            else _next_day_session_start_after(today)
        )
        return {
            "current": "closed",
            "next_session_start": next_start,
            "in_session": False,
        }

    # Early morning before day session
    return {
        "current": "closed",
        "next_session_start": datetime.combine(today, DAY_SESSION_START, tzinfo=CN_TZ),
        "in_session": False,
    }


def _query_latest(db_path: Path) -> dict[str, Any] | None:
    """Return the latest Futures 5min bar from market_bars_intraday."""
    if not db_path.exists():
        return None

    sql = """
        SELECT
            bar_time,
            MAX(bar_time) AS latest_bar_time,
            COUNT(*) AS total_bars,
            COUNT(DISTINCT symbol) AS symbol_count
        FROM market_bars_intraday
        WHERE market = 'Futures'
          AND COALESCE(interval, '') IN ('5min', '5MIN', '5')
          AND provider LIKE '%rt_fut_min%'
    """
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql).fetchone()
    except Exception:
        logger.warning("failed to query futures 5min freshness from %s", db_path, exc_info=True)
        return None
    finally:
        if conn is not None:
            conn.close()

    if row is None:
        return None

    return {
        "latest_bar_time": str(row["latest_bar_time"]) if row["latest_bar_time"] is not None else None,
        "total_bars": int(row["total_bars"] or 0),
        "symbol_count": int(row["symbol_count"] or 0),
    }


def check_freshness(
    db_path: Path,
    *,
    now: datetime | None = None,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    """Return a structured freshness report for CN futures 5-minute bars."""
    now_cn = _now_cn(now)
    session = _session_info(now_cn)
    result: dict[str, Any] = {
        "sqlite_db": str(db_path),
        "checked_at": now_cn.isoformat(),
        "max_age_minutes": max(max_age_minutes, 1),
        "session": {
            "current": session["current"],
            "next_session_start": session["next_session_start"].isoformat(),
            "in_session": session["in_session"],
        },
    }

    latest = _query_latest(db_path)
    if latest is None:
        result["status"] = "error"
        result["error"] = "database missing or unreadable"
        return result

    if latest["total_bars"] == 0 or latest["latest_bar_time"] is None:
        result["status"] = "no_data"
        result["error"] = "no Futures 5min bars found in market_bars_intraday"
        result["latest_bar_time"] = None
        return result

    latest_dt = _parse_datetime(latest["latest_bar_time"])
    if latest_dt is None:
        result["status"] = "error"
        result["error"] = f"unable to parse latest bar time: {latest['latest_bar_time']!r}"
        result["latest_bar_time"] = latest["latest_bar_time"]
        return result

    age_minutes = (now_cn - latest_dt).total_seconds() / 60.0
    next_session_start = session["next_session_start"]
    next_session_has_data = latest_dt >= next_session_start

    status = "fresh"
    reasons: list[str] = []
    if session["in_session"] and age_minutes > max_age_minutes:
        status = "stale"
        reasons.append(f"latest bar is {age_minutes:.1f} minutes old (threshold {max_age_minutes})")
    if session["in_session"] and not next_session_has_data:
        status = "stale"
        reasons.append("current trading session has no 5min bars yet")

    result.update({
        "status": status,
        "latest_bar_time": latest_dt.isoformat(),
        "latest_bar_age_minutes": round(age_minutes, 2),
        "symbol_count": latest["symbol_count"],
        "total_bars": latest["total_bars"],
        "session": {
            "current": session["current"],
            "next_session_start": next_session_start.isoformat(),
            "in_session": session["in_session"],
            "next_session_has_data": next_session_has_data,
        },
    })
    if reasons:
        result["reasons"] = reasons

    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check freshness of CN futures 5-minute bars in market_bars_intraday."
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help="Path to the SQLite read model (default: %(default)s).",
    )
    parser.add_argument(
        "--now",
        type=_parse_cli_datetime,
        default=None,
        help="Reference time as ISO8601 or 'YYYY-MM-DD HH:MM:SS' (default: current UTC time).",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=int(os.environ.get("SHAREDSIGNALS_CN_FUTURES_5MIN_MAX_AGE_MINUTES", DEFAULT_MAX_AGE_MINUTES)),
        help="Stale threshold in minutes (default: %(default)s).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    return parser.parse_args(argv)


def _parse_cli_datetime(value: str) -> datetime:
    value = value.strip()
    # Allow space-separated local datetimes; assume China local time if no tz.
    if "T" not in value and " " in value:
        value = value.replace(" ", "T", 1)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN_TZ)
    return dt


def _format_human(report: dict[str, Any]) -> str:
    lines = [
        "=== CN Futures 5min Freshness ===",
        f"status: {report['status']}",
        f"latest_bar_time: {report.get('latest_bar_time') or 'N/A'}",
        f"latest_bar_age_minutes: {report.get('latest_bar_age_minutes', 'N/A')}",
        f"max_age_minutes: {report['max_age_minutes']}",
        f"symbols: {report.get('symbol_count', 'N/A')}",
        f"total_5min_bars: {report.get('total_bars', 'N/A')}",
        f"session: {report['session']['current']} (in_session={report['session']['in_session']})",
        f"next_session_start: {report['session']['next_session_start']}",
        f"next_session_has_data: {report['session'].get('next_session_has_data', 'N/A')}",
        f"checked_at: {report['checked_at']}",
        f"sqlite_db: {report['sqlite_db']}",
    ]
    if "reasons" in report:
        lines.append("reasons:")
        for reason in report["reasons"]:
            lines.append(f"  - {reason}")
    if "error" in report:
        lines.append(f"error: {report['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = check_freshness(
        args.sqlite_db,
        now=args.now,
        max_age_minutes=args.max_age_minutes,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(_format_human(report))

    status = report.get("status")
    if status == "error":
        return 2
    if status in {"stale", "no_data"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
