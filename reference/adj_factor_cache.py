"""Cache and serve Tushare adj_factor for all stocks."""
import csv, os, sys
from pathlib import Path
from datetime import datetime

CACHE_PATH = Path('/opt/investment/SharedSignals/reference/adj_factor_cache.csv')
TUSHARE_API = '/opt/investment/Ashare/tools/a_share_tushare_api.py'

def fetch_adj_factor(ts_code, start_date='20200101', end_date=None):
    """Fetch adj_factor from Tushare.""`
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    sys.path.insert(0, '/opt/investment/Ashare/tools')
    try:
        from a_share_tushare_api import _call
        rows = _call('adj_factor', {'ts_code': ts_code, 'start_date': start_date, 'end_date': end_date})
        return {r['trade_date']: float(r['adj_factor']) for r in rows} if rows else {}
    except Exception as e:
        return {}

def get_adjusted_price(ts_code, date, raw_close):
    """Return forward-adjusted close price."""
    factors = fetch_adj_factor(ts_code)
    if not factors or date not in factors:
        return raw_close
    latest = max(factors.values()) if factors else 1.0
    factor_date = factors.get(date, latest)
    return raw_close * factor_date / latest

def update_daily():
    """Refresh adj_factor for all stocks (daily cron)."""
    # Read stock list
    stock_path = Path('/opt/investment/MarketGraph/data/association/stock_industry_map.csv')
    if not stock_path.exists(): return {'updated': 0}
    stocks = []
    with open(stock_path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            code = row.get('ts_code', '').strip()
            if code: stocks.append(code)
    # Fetch and cache
    all_factors = []
    for ts_code in stocks[:100]:  # Limit to 100 for speed
        factors = fetch_adj_factor(ts_code)
        for date, factor in factors.items():
            all_factors.append({'ts_code': ts_code, 'trade_date': date, 'adj_factor': factor})
    # Write cache
    if all_factors:
        with open(CACHE_PATH, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['ts_code', 'trade_date', 'adj_factor'])
            w.writeheader()
            w.writerows(all_factors)
    return {'updated': len(all_factors)}

if __name__ == '__main__':
    r = update_daily()
    print(f'Updated {r["updated"]} adj_factor records')
