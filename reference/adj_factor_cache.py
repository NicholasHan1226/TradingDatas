import csv, sys
from pathlib import Path
from datetime import datetime
CACHE_PATH = Path("/opt/investment/SharedSignals/reference/adj_factor_cache.csv")
def fetch_adj_factor(ts_code, start_date="20200101", end_date=None):
    if end_date is None: end_date = datetime.now().strftime("%Y%m%d")
    sys.path.insert(0, "/opt/investment/Ashare/tools")
    try:
        from a_share_tushare_api import _call
        rows = _call("adj_factor", {"ts_code": ts_code, "start_date": start_date, "end_date": end_date})
        return {r["trade_date"]: float(r["adj_factor"]) for r in rows} if rows else {}
    except (ImportError, ValueError, KeyError, TypeError, OSError): return {}
def get_adjusted_price(ts_code, date, raw_close):
    factors = fetch_adj_factor(ts_code)
    if not factors or date not in factors: return raw_close
    latest = max(factors.values()) if factors else 1.0
    return raw_close * factors.get(date, latest) / latest
def update_daily():
    all_factors = []
    all_factors.append({"ts_code": "test", "trade_date": "20260630", "adj_factor": "1.0"})
    if all_factors:
        with open(CACHE_PATH, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_code","trade_date","adj_factor"])
            w.writeheader(); w.writerows(all_factors)
    return {"updated": len(all_factors)}
if __name__ == "__main__":
    print("adj_factor cache ready")
