#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share trading calendar helper backed by the Tushare trade_cal API.

Wraps the existing Ashare Tushare wrapper (symlinked at
reference/a_share_tushare_api.py) so all consumers in SharedSignals share a
single, cached definition of "trading day".  Results are LRU-cached by the
underlying wrapper and additionally memoised in-process per (start, end) range.

Public API
----------
- is_trading_day(date)  -> bool
- get_next_trading_day(date) -> date | None
- get_trading_days(start, end) -> list[date]

Dates may be datetime.date, datetime.datetime, or str in
YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD form; return values are
datetime.date.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Make the Ashare wrapper importable.  a_share_tushare_api lives next to
# this file (as a symlink) but its sibling dependency a_share_common lives
# in the real Ashare/tools directory, so we add that directory to sys.path.
# ---------------------------------------------------------------------------
_ASHARE_TOOLS = Path(__file__).resolve().parent
import sys as _sys
if str(_ASHARE_TOOLS) not in _sys.path:
    _sys.path.insert(0, str(_ASHARE_TOOLS))

try:
    from a_share_tushare_api import _call  # type: ignore
except Exception as _import_err:  # pragma: no cover - import guard
    _call = None  # type: ignore
    logger.warning(
        "market_calendar: a_share_tushare_api unavailable (%s); "
        "calendar calls will raise on use", _import_err
    )


DateLike = Union[date, datetime, str]

# In-process cache: (start_iso, end_iso) -> list[date]
_range_cache: dict[tuple[str, str], list[date]] = {}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

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


def _to_tushare_date(d: DateLike) -> str:
    """Return YYYYMMDD string expected by the trade_cal API."""
    return _to_date(d).strftime("%Y%m%d")


def _from_tushare_date(s: str) -> date:
    """Parse YYYYMMDD (or YYYY-MM-DD) from Tushare into date."""
    s = str(s).strip()
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return datetime.strptime(s, "%Y%m%d").date()


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def _fetch_trading_days(start: date, end: date) -> list[date]:
    """Fetch trading days in [start, end] from Tushare, with caching."""
    key = (start.isoformat(), end.isoformat())
    if key in _range_cache:
        return _range_cache[key]

    if _call is None:
        raise RuntimeError(
            "market_calendar: Tushare wrapper unavailable (a_share_tushare_api "
            "import failed); cannot resolve trading days"
        )

    # Tushare trade_cal returns is_open=1 for trading days.
    rows = _call("trade_cal", {
        "exchange": "SSE",
        "start_date": _to_tushare_date(start),
        "end_date": _to_tushare_date(end),
    })
    days: list[date] = []
    for row in rows:
        if str(row.get("is_open", "")) in ("1", "1.0"):
            cal = row.get("cal_date")
            if cal:
                try:
                    days.append(_from_tushare_date(str(cal)))
                except ValueError:
                    continue
    days.sort()
    _range_cache[key] = days
    return days


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
    """Return the next trading day strictly after d (default: today).

    If include_today=True and d is itself a trading day, return d.
    Returns None if no trading day is found within the search horizon
    (looks ahead up to ~30 calendar days).
    """
    target = _to_date(d) if d is not None else date.today()
    if include_today and is_trading_day(target):
        return target

    # Look ahead up to 30 calendar days to bound the query.
    horizon = target + timedelta(days=30)
    days = _fetch_trading_days(target, horizon)
    for day in days:
        if day > target:
            return day
    return None


def clear_cache() -> None:
    """Clear the in-process range cache (useful for tests / forced refresh)."""
    _range_cache.clear()


if __name__ == "__main__":
    # Smoke test
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
