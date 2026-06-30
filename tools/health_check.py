#!/usr/bin/env python3
"""SharedSignals health check — used by loop audit."""
import os, sys, sqlite3, urllib.request, subprocess
from pathlib import Path
from datetime import datetime

SS = Path("/opt/investment/SharedSignals")
sys.path.insert(0, str(SS))

env = SS / ".env"
if env.exists():
    for line in open(env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            if line.startswith("export "): line = line[7:]
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip().strip("\"'")

from reader import *

now = datetime.now().strftime("%Y-%m-%d %H:%M")
print(f"=== SharedSignals Health [{now}] ===")

# 1. Reader functions
funcs = [
    ("is_trading_day", is_trading_day("20260629")),
    ("market_data", get_market_data("600519.SH","20260601","20260630")),
    ("fundamentals", get_fundamentals("600519.SH")),
    ("reference", get_reference("stock_master")),
    ("macro", get_macro_factors("20260601","20260629")),
    ("capital_flow", get_capital_flow("20260628")),
    ("events", get_events("20260601","20260629")),
    ("sentiment", get_sentiment("20260601","20260629")),
    ("crypto", get_crypto_klines("BTCUSDT",5)),
    ("pm_markets", get_pm_markets(5)),
]
ok = []; degraded = []
for name, result in funcs:
    d = result[0].get("degraded","?") if result else "?"
    if d in (False, None): ok.append(name)
    else: degraded.append(name)
print(f"[FUNCTIONS] {len(ok)}/{len(funcs)} OK" + (f" | DEGRADED: {degraded}" if degraded else " | ALL CLEAN"))

# 2. Data freshness
con = sqlite3.connect("/opt/investment/MarketGraphRuntime/read_model/marketdata.sqlite")
today = datetime.now().strftime("%Y%m%d")
stale = []
for market in ["Ashare","Crypto","US"]:
    r = con.execute("SELECT MAX(trade_date) FROM market_bars_daily WHERE market=?",(market,)).fetchone()
    latest = r[0] or "?"
    days = (datetime.now() - datetime.strptime(latest,"%Y%m%d")).days if latest != "?" else 999
    status = "OK" if days <= 1 else f"STALE {days}d"
    if days > 1: stale.append(f"{market}({latest})")
    print(f"[DATA] {market}: {latest} [{status}]")
con.close()

# 3. API
try:
    urllib.request.urlopen("http://127.0.0.1:8082/health", timeout=3)
    print("[API] :8082 OK")
except:
    print("[API] :8082 DOWN")
    degraded.append("api")

# 4. Cron activity
r = subprocess.run(["find","/opt/investment/MarketGraphRuntime/staging/logs","-name","*.log","-mmin","-15"], capture_output=True, text=True)
active = len([l for l in r.stdout.splitlines() if l.strip()])
print(f"[CRON] {active} logs updated in 15min" + (" OK" if active > 0 else " CHECK"))

# 5. Architecture
r = (SS / "reader.py").read_text()
mg = sum(1 for l in r.splitlines() if "MARKETGRAPH_ROOT" in l and "MARKETGRAPH_ROOT =" not in l)
ashare = sum(1 for l in r.splitlines() if "ASHARE_ROOT" in l and "data" in l)
arch_ok = mg == 0 and ashare == 0
print(f"[ARCH] MG_refs={mg} Ashare_data_refs={ashare}" + (" OK" if arch_ok else " VIOLATION"))

# 6. Compile
try:
    for f in ["reader.py","api_server.py"]:
        compile((SS/f).read_text(), f, "exec")
    print("[COMPILE] OK")
except SyntaxError as e:
    print(f"[COMPILE] FAIL: {e}")

# Summary
all_ok = len(degraded) == 0 and len(stale) == 0 and arch_ok
print(f"\n{'ALL CLEAN' if all_ok else 'ISSUES: ' + str(degraded + stale)}")
