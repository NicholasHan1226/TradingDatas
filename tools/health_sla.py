#!/usr/bin/env python3
"""Data health SLA monitor — alerts when freshness breaches thresholds."""
from __future__ import annotations
import json, os, sqlite3, urllib.request
from datetime import date as date_cls, datetime, time as time_cls, timezone, timedelta
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python fallback for constrained runtimes
    ZoneInfo = None

SLA_THRESHOLDS = {
    'market_bars_daily': {'max_age_hours': 72, 'market': 'all', 'lane': 'trading', 'severity': 'critical'},
    'market_factors': {'max_age_hours': 72, 'market': 'all', 'lane': 'trading', 'severity': 'warning'},
    'market_pm_prices': {'max_age_hours': 0.75, 'market': 'PM', 'lane': 'trading', 'severity': 'critical'},
    'market_events': {'max_age_hours': 36, 'market': 'all', 'lane': 'research', 'severity': 'notice'},
}
SLA_DATE_COLUMNS = {
    'market_bars_daily': ['trade_date', 'updated_at', 'collected_at'],
    'market_bars_intraday': ['collected_at', 'updated_at', 'bar_time', 'trade_date'],
    'market_factors': ['collected_at', 'updated_at', 'event_time', 'trade_date'],
    'market_pm_prices': ['collected_at', 'updated_at'],
    'market_events': ['event_time', 'collected_at', 'updated_at', 'trade_date'],
}
CRYPTO_INTRADAY_MAX_AGE_HOURS = float(os.getenv("SHAREDSIGNALS_CRYPTO_INTRADAY_MAX_AGE_MIN", "45")) / 60.0
RECENT_SAMPLE_LIMIT = int(os.getenv("SHAREDSIGNALS_HEALTH_SLA_RECENT_SAMPLE_LIMIT", "50000"))
RECENT_SAMPLE_TABLES = {
    "market_bars_daily",
    "market_bars_intraday",
    "market_factors",
    "market_pm_prices",
    "market_events",
}

def _table_violation(table: str, sla: dict, *, status: str, message: str, now: datetime) -> dict:
    return {
        'table': table,
        'status': status,
        'message': message,
        'checked_at': now.isoformat(),
        'lane': sla.get('lane', 'unknown'),
        'severity': sla.get('severity', 'warning'),
        'threshold_hours': sla.get('max_age_hours'),
    }


def _effective_max_age_hours(sla: dict, now: datetime) -> float:
    threshold = float(sla['max_age_hours'])
    cn_now = now.astimezone(timezone(timedelta(hours=8)))
    market = str(sla.get('market') or '').lower()
    lane = str(sla.get('lane') or '').lower()
    if market in {'crypto', 'pm'}:
        return threshold
    is_weekend = cn_now.weekday() >= 5
    is_monday = cn_now.weekday() == 0
    if market == 'us' and cn_now.weekday() == 0:
        return max(threshold, 120)
    if is_weekend or is_monday:
        if lane == 'trading':
            return max(threshold, 96)
        if lane == 'research':
            return max(threshold, 72)
    return threshold


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date_cls:
    day = date_cls(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date_cls:
    next_month = date_cls(year + int(month == 12), 1 if month == 12 else month + 1, 1)
    day = next_month - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date_cls:
    holiday = date_cls(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _easter_date(year: int) -> date_cls:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date_cls(year, month, day)


def _us_market_holidays(year: int) -> set[date_cls]:
    easter = _easter_date(year)
    return {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        easter - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }


def _is_market_trading_day(day: date_cls, market: str) -> bool:
    if day.weekday() >= 5:
        return False
    market_key = str(market or "").strip().lower()
    if market_key == "us":
        holidays = _us_market_holidays(day.year) | _us_market_holidays(day.year - 1) | _us_market_holidays(day.year + 1)
        return day not in holidays
    return True


def _previous_trading_day(day: date_cls, market: str) -> date_cls:
    current = day
    while not _is_market_trading_day(current, market):
        current -= timedelta(days=1)
    return current


def _expected_latest_daily_date(market: str, now: datetime) -> date_cls | None:
    market_key = str(market or "").strip().lower()
    if market_key == "us":
        if ZoneInfo:
            market_now = _as_utc(now).astimezone(ZoneInfo("America/New_York"))
        else:
            market_now = _as_utc(now).astimezone(timezone(timedelta(hours=-5)))
        cutoff_date = market_now.date()
        if market_now.time() < time_cls(18, 10):
            cutoff_date -= timedelta(days=1)
        return _previous_trading_day(cutoff_date, "us")
    if market_key == "global":
        cn_now = _as_utc(now).astimezone(timezone(timedelta(hours=8)))
        cutoff_date = cn_now.date() - timedelta(days=1 if cn_now.time() >= time_cls(8, 45) else 2)
        return _previous_trading_day(cutoff_date, "global")
    return None


def _daily_trading_days_behind(latest: date_cls, expected: date_cls, market: str) -> int:
    if latest >= expected:
        return 0
    count = 0
    day = latest + timedelta(days=1)
    while day <= expected:
        if _is_market_trading_day(day, market):
            count += 1
        day += timedelta(days=1)
    return count


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_freshness_value(value):
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
    return _as_utc(datetime.fromisoformat(text.replace('Z', '+00:00')))


def _append_daily_market_violation(violations: list, *, table: str, sla: dict, latest, now: datetime, market: str) -> bool:
    market_key = str(market or "").strip().lower()
    if market_key not in {"us", "global"}:
        return False
    latest_dt = _parse_freshness_value(latest)
    expected = _expected_latest_daily_date(market_key, now)
    if expected is None:
        return False
    latest_date = latest_dt.date()
    trading_days_behind = _daily_trading_days_behind(latest_date, expected, market_key)
    threshold_days = 1
    if trading_days_behind <= threshold_days:
        return True
    age_hours = (now - latest_dt).total_seconds() / 3600
    violations.append({
        'table': table,
        'age_hours': round(age_hours, 1),
        'threshold_hours': _effective_max_age_hours({**sla, 'market': market}, now),
        'base_threshold_hours': sla['max_age_hours'],
        'latest': str(latest_dt)[:19],
        'status': 'breached',
        'lane': sla.get('lane', 'unknown'),
        'severity': sla.get('severity', 'warning'),
        'market': market,
        'expected_latest_trade_date': expected.strftime("%Y%m%d"),
        'trading_days_behind': trading_days_behind,
        'threshold_trading_days_behind': threshold_days,
    })
    return True


def _append_freshness_violation(violations: list, *, table: str, sla: dict, latest, now: datetime, market: str | None = None) -> None:
    if table == 'market_bars_daily' and market:
        if _append_daily_market_violation(violations, table=table, sla=sla, latest=latest, now=now, market=str(market)):
            return
    latest_dt = _parse_freshness_value(latest)
    effective_max_age = _effective_max_age_hours({**sla, 'market': market or sla.get('market')}, now)
    age_hours = (now - latest_dt).total_seconds() / 3600
    if age_hours <= effective_max_age:
        return
    payload = {
        'table': table, 'age_hours': round(age_hours, 1),
        'threshold_hours': effective_max_age,
        'base_threshold_hours': sla['max_age_hours'], 'latest': str(latest_dt)[:19],
        'status': 'breached',
        'lane': sla.get('lane', 'unknown'),
        'severity': sla.get('severity', 'warning'),
    }
    if market:
        payload['market'] = market
    violations.append(payload)


def _crypto_intraday_violation(conn: sqlite3.Connection, now: datetime) -> dict | None:
    sla = {
        'max_age_hours': CRYPTO_INTRADAY_MAX_AGE_HOURS,
        'market': 'Crypto',
        'lane': 'trading',
        'severity': 'critical',
    }
    table = 'market_bars_intraday'
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if not cols:
        return _table_violation(table, sla, status='error', message='crypto intraday table not found', now=now)
    date_col = next((c for c in SLA_DATE_COLUMNS[table] if c in cols), None)
    if not date_col:
        return _table_violation(table, sla, status='error', message='crypto intraday freshness date column not found', now=now)
    latest = _latest_recent_value(
        conn,
        table,
        date_col,
        where_sql='WHERE lower(market)=lower(?)',
        params=('Crypto',),
    )
    if not latest:
        return _table_violation(table, sla, status='empty', message='no crypto intraday freshness timestamp found', now=now)
    latest_dt = _parse_freshness_value(latest)
    age_hours = (now - latest_dt).total_seconds() / 3600
    if age_hours <= CRYPTO_INTRADAY_MAX_AGE_HOURS:
        return None
    return {
        'table': table,
        'age_hours': round(age_hours, 2),
        'threshold_hours': CRYPTO_INTRADAY_MAX_AGE_HOURS,
        'base_threshold_hours': CRYPTO_INTRADAY_MAX_AGE_HOURS,
        'latest': str(latest_dt)[:19],
        'status': 'breached',
        'lane': sla['lane'],
        'severity': sla['severity'],
        'market': 'Crypto',
        'source': 'market_bars_intraday_collected_at',
    }


def _latest_recent_value(
    conn: sqlite3.Connection,
    table: str,
    date_col: str,
    *,
    where_sql: str = "",
    params: tuple = (),
    limit: int = RECENT_SAMPLE_LIMIT,
):
    query = f"""
        SELECT {date_col}
        FROM {table}
        {where_sql}
        ORDER BY rowid DESC
        LIMIT ?
    """
    rows = conn.execute(query, (*params, max(1, int(limit)))).fetchall()
    latest_dt = None
    latest_raw = None
    for (value,) in rows:
        if value in (None, ""):
            continue
        try:
            parsed = _parse_freshness_value(value)
        except Exception:
            continue
        if latest_dt is None or parsed > latest_dt:
            latest_dt = parsed
            latest_raw = value
    return latest_raw


def _latest_freshness_value(conn: sqlite3.Connection, table: str, date_col: str):
    if table in RECENT_SAMPLE_TABLES:
        return _latest_recent_value(conn, table, date_col)
    row = conn.execute(f'SELECT MAX({date_col}) FROM {table}').fetchone()
    return row[0] if row and row[0] else None


def _latest_daily_by_market_recent(conn: sqlite3.Connection, table: str, date_col: str):
    rows = conn.execute(
        f"""
        SELECT market, {date_col}
        FROM {table}
        ORDER BY rowid DESC
        LIMIT ?
        """,
        (max(1, RECENT_SAMPLE_LIMIT),),
    ).fetchall()
    latest_by_market: dict[str, tuple[datetime, object]] = {}
    for market, value in rows:
        if value in (None, ""):
            continue
        market_key = str(market or "unknown")
        try:
            parsed = _parse_freshness_value(value)
        except Exception:
            continue
        current = latest_by_market.get(market_key)
        if current is None or parsed > current[0]:
            latest_by_market[market_key] = (parsed, value)
    return [(market, value) for market, (_parsed, value) in latest_by_market.items()]


def check_sla(now: datetime | None = None):
    from runtime_paths import marketdata_sqlite_path

    db = str(marketdata_sqlite_path())
    if not os.path.exists(db):
        return {'status': 'critical', 'reason': 'DB not found', 'db': db, 'violations': []}
    
    violations = []
    now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=3000")
        for table, sla in SLA_THRESHOLDS.items():
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
                date_col = next((c for c in SLA_DATE_COLUMNS.get(table, ['trade_date','event_time','collected_at','updated_at']) if c in cols), None)
                if not date_col:
                    violations.append(_table_violation(table, sla, status='error', message='freshness date column not found', now=now))
                    continue

                if table == 'market_bars_daily' and 'market' in cols:
                    rows = _latest_daily_by_market_recent(conn, table, date_col)
                    if not rows:
                        violations.append(_table_violation(table, sla, status='empty', message='no freshness timestamp found', now=now))
                        continue
                    for market, latest in rows:
                        if str(market or '').strip().lower() == 'crypto':
                            violation = _crypto_intraday_violation(conn, now)
                            if violation:
                                violations.append(violation)
                            continue
                        if not latest:
                            violations.append(_table_violation(table, {**sla, 'market': market}, status='empty', message=f'no freshness timestamp found for market={market}', now=now))
                            continue
                        _append_freshness_violation(violations, table=table, sla=sla, latest=latest, now=now, market=str(market or 'unknown'))
                    continue

                latest = _latest_freshness_value(conn, table, date_col)
                if not latest:
                    violations.append(_table_violation(table, sla, status='empty', message='no freshness timestamp found', now=now))
                    continue

                _append_freshness_violation(violations, table=table, sla=sla, latest=latest, now=now)
            except Exception as exc:
                violations.append(_table_violation(table, sla, status='error', message=f'{exc.__class__.__name__}: {exc}', now=now))
    finally:
        conn.close()
    missing_or_empty_count = sum(1 for item in violations if item.get('status') in {'empty', 'error'})
    critical_count = sum(1 for item in violations if item.get('severity') == 'critical')
    warning_count = sum(
        1
        for item in violations
        if item.get('severity') == 'warning'
        or (item.get('severity') == 'notice' and item.get('status') in {'empty', 'error'})
    )
    status = 'critical' if critical_count else ('degraded' if warning_count else 'ok')
    return {
        'status': status,
        'checked_at': now.isoformat(),
        'violations': violations,
        'summary': {
            'critical': critical_count,
            'warning': warning_count,
            'notice': sum(1 for item in violations if item.get('severity') == 'notice'),
            'missing_or_empty': missing_or_empty_count,
        },
    }

if __name__ == '__main__':
    result = check_sla()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Send email if critical
    if result['status'] == 'critical':
        import subprocess, sys
        violation_count = len(result.get("violations") or [])
        subprocess.run([sys.executable, str(Path(__file__).parent / 'email_sender.py'),
            '--subject', f'[CRITICAL] Data health SLA breached — {violation_count} violations',
            '--body', json.dumps(result, indent=2), '--channel', 'system'], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
