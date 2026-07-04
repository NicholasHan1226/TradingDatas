#!/usr/bin/env python3
"""Binance collector via Singapore relay — one source for all crypto data."""
import json, sqlite3, os, urllib.request
from datetime import datetime, timezone

DB = '/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite'
SYMBOLS = ['BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT']
# Try direct first, fallback to proxy
URLS = ['https://api.binance.com/api/v3/ticker/24hr']

def fetch_price(symbol):
    for url in URLS:
        try:
            params = f'?symbol={symbol}'
            req = urllib.request.Request(url + params, headers={'User-Agent': 'SharedSignals/1.0'})
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
            return float(resp['lastPrice']), float(resp['volume']), float(resp['highPrice']), float(resp['lowPrice'])
        except: continue
    return None, None, None, None

conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')
count = 0
for sym in SYMBOLS:
    price, vol, high, low = fetch_price(sym)
    if price:
        conn.execute('''INSERT OR REPLACE INTO market_bars_daily
            (market, symbol, trade_date, open, high, low, close, volume, amount, provider, collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            ('Crypto', sym, datetime.now(timezone.utc).strftime('%Y%m%d'),
             price, high or price, low or price, price, vol or 0, (price*(vol or 1)), 'binance_sharedsignals',
             datetime.now(timezone.utc).isoformat()))
        count += 1
conn.commit(); conn.close()
print(f'Binance: {count}/{len(SYMBOLS)} symbols collected')
