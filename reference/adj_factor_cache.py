#!/usr/bin/env python3
"""Adjusted-price helper backed by SharedSignals cache.

This read-side helper never calls Tushare directly. The collector layer is
responsible for populating adjustment factors into the read model.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from runtime_paths import marketdata_sqlite_path

def _db_path() -> Path:
    return marketdata_sqlite_path()


def _normalize_date(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return text


def _read_from_db(ts_code: str, start_date: str, end_date: str) -> dict[str, float]:
    path = _db_path()
    if not path.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        rows = conn.execute(
            """
            SELECT event_time, value
            FROM market_factors
            WHERE market='Ashare'
              AND symbol=?
              AND factor_name IN ('adj_factor', 'tushare:adj_factor')
              AND event_time BETWEEN ? AND ?
            ORDER BY event_time ASC
            """,
            (ts_code, start_date, end_date),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    factors: dict[str, float] = {}
    for trade_date, value in rows:
        try:
            factors[_normalize_date(str(trade_date))] = float(value)
        except (TypeError, ValueError):
            continue
    return factors


def fetch_adj_factor(ts_code: str, start_date: str = "20200101", end_date: str | None = None) -> dict[str, float]:
    """Return cached adjustment factors keyed by YYYYMMDD."""
    code = str(ts_code or "").strip()
    if not code:
        return {}
    start = _normalize_date(start_date) or "20200101"
    end = _normalize_date(end_date) if end_date else datetime.now().strftime("%Y%m%d")
    return _read_from_db(code, start, end)


def get_adjusted_price(ts_code: str, date: str, raw_close: float) -> float:
    factors = fetch_adj_factor(ts_code)
    trade_date = _normalize_date(date)
    if not factors or trade_date not in factors:
        return raw_close
    latest = max(factors.values()) if factors else 1.0
    if latest == 0:
        return raw_close
    return raw_close * factors.get(trade_date, latest) / latest


def update_daily() -> dict[str, int | str]:
    """Read-side cache files are produced by collectors; this helper is no-op."""
    return {"updated": 0, "status": "read_side_noop"}


if __name__ == "__main__":
    print("adj_factor cache read-side helper ready")
