#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share trading calendar helper backed by the SharedSignals read model.

This module intentionally does not call Tushare or any other live provider.
Collectors populate the SharedSignals database first; read-side consumers use
the cached `market_bars_daily` dates here.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Union


DateLike = Union[date, datetime, str]

RUNTIME_ROOT = Path(os.environ.get("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime"))
DEFAULT_DB_PATH = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"

_range_cache: dict[tuple[str, str, str], list[date]] = {}


class TradingCalendarUnavailableError(RuntimeError):
    """Raised when the cached trading calendar cannot answer a request."""


def _db_path() -> Path:
    return Path(os.environ.get("SHARED_SIGNALS_DB", str(DEFAULT_DB_PATH)))


def _to_date(d: DateLike) -> date:
    """Coerce date/datetime/str to datetime.date."""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        s = d.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"Cannot parse date: {d!r}")


def _from_db_date(s: str) -> date:
    s = str(s).strip()
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return datetime.strptime(s, "%Y%m%d").date()


def _to_db_date(d: DateLike) -> str:
    return _to_date(d).strftime("%Y%m%d")


def _range_contains_weekday(start: date, end: date) -> bool:
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            return True
        cursor += timedelta(days=1)
    return False


def _fetch_trading_days(start: date, end: date) -> list[date]:
    """Fetch trading days in [start, end] from SharedSignals cache."""
    path = _db_path()
    key = (str(path), start.isoformat(), end.isoformat())
    if key in _range_cache:
        return _range_cache[key]
    if not path.exists():
        raise TradingCalendarUnavailableError(f"market calendar database not found: {path}")

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        rows = conn.execute(
            """
            SELECT DISTINCT trade_date
            FROM market_bars_daily
            WHERE market='Ashare'
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date ASC
            """,
            (_to_db_date(start), _to_db_date(end)),
        ).fetchall()
    except sqlite3.Error as exc:
        raise TradingCalendarUnavailableError(f"market calendar database query failed: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    days: list[date] = []
    for (trade_date,) in rows:
        try:
            days.append(_from_db_date(str(trade_date)))
        except ValueError:
            continue
    if days:
        _range_cache[key] = days
        return days

    if _range_contains_weekday(start, end):
        raise TradingCalendarUnavailableError(
            f"no cached Ashare trading days for {start.isoformat()}..{end.isoformat()}"
        )
    _range_cache[key] = []
    return []


def is_trading_day(d: DateLike = None) -> bool:
    """Return True if d (default: today) is an A-share trading day."""
    target = _to_date(d) if d is not None else date.today()
    days = _fetch_trading_days(target, target)
    return target in days


def get_trading_days(start: DateLike, end: DateLike) -> list[date]:
    """Return all A-share trading days in the inclusive range [start, end]."""
    s, e = _to_date(start), _to_date(end)
    if s > e:
        s, e = e, s
    return _fetch_trading_days(s, e)


def get_next_trading_day(d: DateLike = None, *, include_today: bool = False) -> Optional[date]:
    """Return the next cached trading day after d, or None if not cached."""
    target = _to_date(d) if d is not None else date.today()
    if include_today and is_trading_day(target):
        return target

    horizon = target + timedelta(days=30)
    try:
        days = _fetch_trading_days(target, horizon)
    except TradingCalendarUnavailableError:
        return None
    for day in days:
        if day > target:
            return day
    return None


def clear_cache() -> None:
    """Clear the in-process range cache."""
    _range_cache.clear()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="A-share trading calendar helper")
    p.add_argument("--is-trading-day", metavar="DATE", help="check if DATE is a trading day")
    p.add_argument("--next", metavar="DATE", help="next trading day after DATE")
    p.add_argument("--range", nargs=2, metavar=("START", "END"), help="trading days in [START, END]")
    args = p.parse_args()
    if args.is_trading_day:
        print(f"{args.is_trading_day}: {'TRADING' if is_trading_day(args.is_trading_day) else 'CLOSED'}")
    elif args.next:
        nxt = get_next_trading_day(args.next)
        print(f"next trading day after {args.next}: {nxt}")
    elif args.range:
        days = get_trading_days(args.range[0], args.range[1])
        print(f"{len(days)} trading days:")
        for day in days:
            print(f"  {day}")
    else:
        p.print_help()
