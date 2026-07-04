#!/usr/bin/env python3
"""Polymarket data collector for SharedSignals."""
import json, sqlite3, os, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB = '/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite'
GAMMA = 'https://gamma-api.polymarket.com'

def safe_get(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'SharedSignals/1.0'})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except: return None

now = datetime.now(timezone.utc).isoformat()
conn = sqlite3.connect(DB)
conn.execute('PRAGMA busy_timeout=5000')
count = 0

markets = safe_get(f'{GAMMA}/markets?closed=false&limit=50')
if markets and isinstance(markets, list):
    for m in markets:
        if not isinstance(m, dict): continue
        try:
            conn.execute('''INSERT OR REPLACE INTO market_pm_markets
                (market_id, question, slug, end_date, volume, liquidity, active, closed, provider, collected_at)
                VALUES (?,?,?,?,?,?,?,"true","polymarket",?)''',
                (str(m.get('id','')), str(m.get('question',''))[:200], str(m.get('slug','')),
                 str(m.get('endDate','')), float(m.get('volume',0) or 0), float(m.get('liquidity',0) or 0),
                 now[:19]))
            count += 1
        except: pass
conn.commit(); conn.close()
print(f'PM collector: {count} markets at {now[:19]}')
