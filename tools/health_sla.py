#!/usr/bin/env python3
"""Data health SLA monitor — alerts when freshness breaches thresholds."""
from __future__ import annotations
import json, os, sqlite3, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SLA_THRESHOLDS = {
    'market_bars_daily': {'max_age_hours': 24, 'market': 'all'},
    'market_events': {'max_age_hours': 12, 'market': 'all'},
    'market_factors': {'max_age_hours': 24, 'market': 'all'},
    'market_pm_prices': {'max_age_hours': 6, 'market': 'PM'},
}

def check_sla():
    db = '/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite'
    if not os.path.exists(db): return {'status': 'critical', 'reason': 'DB not found'}
    
    violations = []
    conn = sqlite3.connect(db)
    now = datetime.now(timezone.utc)
    
    for table, sla in SLA_THRESHOLDS.items():
        try:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
            date_col = next((c for c in ['trade_date','event_time','collected_at','updated_at'] if c in cols), None)
            if not date_col: continue
            
            row = conn.execute(f'SELECT MAX({date_col}) FROM {table}').fetchone()
            if not row or not row[0]: continue
            
            latest = row[0]
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest.replace('Z', '+00:00'))
            
            age_hours = (now - latest.replace(tzinfo=timezone.utc)).total_seconds() / 3600
            if age_hours > sla['max_age_hours']:
                violations.append({
                    'table': table, 'age_hours': round(age_hours, 1),
                    'threshold_hours': sla['max_age_hours'], 'latest': str(latest)[:19],
                    'status': 'breached'
                })
        except: pass
    
    conn.close()
    status = 'critical' if len(violations) > 2 else ('degraded' if violations else 'ok')
    return {'status': status, 'checked_at': now.isoformat(), 'violations': violations}

if __name__ == '__main__':
    result = check_sla()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Send email if critical
    if result['status'] == 'critical':
        import subprocess, sys
        subprocess.run([sys.executable, str(Path(__file__).parent / 'email_sender.py'),
            '--subject', f'[CRITICAL] Data health SLA breached — {len(result["violations"])} violations',
            '--body', json.dumps(result, indent=2), '--channel', 'system'], timeout=15)
