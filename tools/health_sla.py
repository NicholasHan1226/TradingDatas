#!/usr/bin/env python3
"""Data health SLA monitor — alerts when freshness breaches thresholds."""
from __future__ import annotations
import json, os, sqlite3, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SLA_THRESHOLDS = {
    'market_bars_daily': {'max_age_hours': 72, 'market': 'all', 'lane': 'trading', 'severity': 'critical'},
    'market_factors': {'max_age_hours': 72, 'market': 'all', 'lane': 'trading', 'severity': 'warning'},
    'market_pm_prices': {'max_age_hours': 6, 'market': 'PM', 'lane': 'trading', 'severity': 'critical'},
    'market_events': {'max_age_hours': 36, 'market': 'all', 'lane': 'research', 'severity': 'notice'},
}
SLA_DATE_COLUMNS = {
    'market_bars_daily': ['trade_date', 'updated_at', 'collected_at'],
    'market_factors': ['collected_at', 'updated_at', 'event_time', 'trade_date'],
    'market_pm_prices': ['updated_at', 'collected_at'],
    'market_events': ['event_time', 'collected_at', 'updated_at', 'trade_date'],
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


def _effective_max_age_hours(sla: dict, now: datetime) -> int:
    threshold = int(sla['max_age_hours'])
    cn_now = now.astimezone(timezone(timedelta(hours=8)))
    market = str(sla.get('market') or '').lower()
    lane = str(sla.get('lane') or '').lower()
    if market in {'crypto', 'pm'}:
        return threshold
    is_weekend = cn_now.weekday() >= 5
    is_monday_pre_open = cn_now.weekday() == 0 and cn_now.hour < 10
    if is_weekend or is_monday_pre_open:
        if lane == 'trading':
            return max(threshold, 96)
        if lane == 'research':
            return max(threshold, 72)
    return threshold


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def check_sla(now: datetime | None = None):
    db = (
        os.getenv("MARKETDATA_SQLITE")
        or os.getenv("SHAREDSIGNALS_MARKETDATA_DB")
        or str(Path(os.getenv("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime")) / "read_model" / "marketdata.sqlite")
    )
    if not os.path.exists(db):
        return {'status': 'critical', 'reason': 'DB not found', 'db': db, 'violations': []}
    
    violations = []
    now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for table, sla in SLA_THRESHOLDS.items():
            try:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
                date_col = next((c for c in SLA_DATE_COLUMNS.get(table, ['trade_date','event_time','collected_at','updated_at']) if c in cols), None)
                if not date_col:
                    violations.append(_table_violation(table, sla, status='error', message='freshness date column not found', now=now))
                    continue

                row = conn.execute(f'SELECT MAX({date_col}) FROM {table}').fetchone()
                if not row or not row[0]:
                    violations.append(_table_violation(table, sla, status='empty', message='no freshness timestamp found', now=now))
                    continue

                latest = row[0]
                if isinstance(latest, str):
                    latest = datetime.fromisoformat(latest.replace('Z', '+00:00'))
                latest = _as_utc(latest)

                effective_max_age = _effective_max_age_hours(sla, now)
                age_hours = (now - latest).total_seconds() / 3600
                if age_hours > effective_max_age:
                    violations.append({
                        'table': table, 'age_hours': round(age_hours, 1),
                        'threshold_hours': effective_max_age,
                        'base_threshold_hours': sla['max_age_hours'], 'latest': str(latest)[:19],
                        'status': 'breached',
                        'lane': sla.get('lane', 'unknown'),
                        'severity': sla.get('severity', 'warning'),
                    })
            except Exception as exc:
                violations.append(_table_violation(table, sla, status='error', message=f'{exc.__class__.__name__}: {exc}', now=now))
    finally:
        conn.close()
    critical_count = sum(1 for item in violations if item.get('severity') == 'critical')
    warning_count = sum(1 for item in violations if item.get('severity') == 'warning')
    status = 'critical' if critical_count else ('degraded' if warning_count else 'ok')
    return {
        'status': status,
        'checked_at': now.isoformat(),
        'violations': violations,
        'summary': {
            'critical': critical_count,
            'warning': warning_count,
            'notice': sum(1 for item in violations if item.get('severity') == 'notice'),
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
            '--body', json.dumps(result, indent=2), '--channel', 'system'], timeout=15)
