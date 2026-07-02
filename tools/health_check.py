#!/usr/bin/env python3
"""SharedSignals health check — importable by api_server and usable as CLI.

Public API:
    get_health_status() -> dict   Reusable, no side effects, fast enough for /health.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

SS = Path(os.environ.get("SHAREDSIGNALS_ROOT", "/opt/investment/SharedSignals"))
RUNTIME_ROOT = Path(
    os.environ.get("MARKETGRAPH_RUNTIME_ROOT", "/opt/investment/MarketGraphRuntime")
)

# ---------------------------------------------------------------------------
# .env loader (best-effort)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env = SS / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip("\"'")


# ---------------------------------------------------------------------------
# Core health check
# ---------------------------------------------------------------------------

def get_health_status(
    *,
    check_functions: bool = True,
    check_data_freshness: bool = True,
    check_cron: bool = True,
    check_arch: bool = True,
    check_compile: bool = True,
) -> dict[str, Any]:
    """Return a structured health status dict suitable for the /health endpoint.

    Each check section includes a ``status`` key: "ok", "degraded", or "error".
    The top-level ``status`` is the worst of all sections.
    """

    _load_env()

    checks: dict[str, Any] = {}
    overall = "ok"

    def _worse(a: str, b: str) -> str:
        order = {"ok": 0, "degraded": 1, "error": 2}
        return b if order.get(b, 0) > order.get(a, 0) else a

    # 1. Reader functions ---------------------------------------------------
    if check_functions:
        try:
            func_checks = _check_reader_functions()
            checks["functions"] = func_checks
            overall = _worse(overall, func_checks["status"])
        except Exception as exc:
            checks["functions"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 2. Data freshness ----------------------------------------------------
    if check_data_freshness:
        try:
            fresh = _check_data_freshness()
            checks["data_freshness"] = fresh
            overall = _worse(overall, fresh["status"])
        except Exception as exc:
            checks["data_freshness"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 3. Cron activity -----------------------------------------------------
    if check_cron:
        try:
            cron = _check_cron_activity()
            checks["cron"] = cron
            overall = _worse(overall, cron["status"])
        except Exception as exc:
            checks["cron"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 4. Architecture compliance -------------------------------------------
    if check_arch:
        try:
            arch = _check_architecture()
            checks["architecture"] = arch
            overall = _worse(overall, arch["status"])
        except Exception as exc:
            checks["architecture"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 5. Compile -----------------------------------------------------------
    if check_compile:
        try:
            comp = _check_compile()
            checks["compile"] = comp
            overall = _worse(overall, comp["status"])
        except Exception as exc:
            checks["compile"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    return {
        "status": overall,
        "checks": checks,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------

def _check_reader_functions() -> dict[str, Any]:
    if str(SS) not in sys.path:
        sys.path.insert(0, str(SS))

    # Use explicit imports instead of wildcard
    import reader  # noqa: E402

    today = datetime.now().strftime("%Y%m%d")
    funcs: list[tuple[str, Any]] = [
        ("is_trading_day", reader.is_trading_day(today)),
        ("market_data", reader.get_market_data("000001.SZ", "20260601", "20260630")),
        ("fundamentals", reader.get_fundamentals("000001.SZ")),
        ("reference", reader.get_reference("stock_master")),
        ("macro", reader.get_macro_factors("20260601", "20260629")),
        ("capital_flow", reader.get_capital_flow(today, ts_code="000001.SZ")),
        ("events", reader.get_events("20260601", "20260629")),
        ("sentiment", reader.get_sentiment("20260601", "20260629")),
        ("crypto", reader.get_crypto_klines("BTCUSDT", 5)),
        ("pm_markets", reader.get_pm_markets(5)),
        ("associations", reader.get_associations(ts_code="000001.SZ")),
        ("impacts", reader.get_impacts(event_type="policy")),
        ("industry", reader.get_industry("000001.SZ")),
        ("realtime_5min", reader.get_realtime_5min(ts_code="000001.SZ", date=today)),
        ("tushare", reader.get_tushare(api_name="stock_basic")),
    ]

    ok: list[str] = []
    degraded: list[str] = []
    for name, result in funcs:
        d = result[0].get("degraded", "?") if result else "?"
        if d in (False, None):
            ok.append(name)
        else:
            degraded.append(name)

    return {
        "status": "degraded" if degraded else "ok",
        "ok": len(ok),
        "total": len(funcs),
        "degraded": degraded,
    }


def _check_data_freshness() -> dict[str, Any]:
    db_path = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"
    if not db_path.exists():
        return {"status": "error", "message": f"database not found: {db_path}"}

    con = sqlite3.connect(str(db_path), timeout=5)
    try:
        markets: dict[str, Any] = {}
        degraded: list[str] = []
        today = datetime.now().strftime("%Y%m%d")
        for market in ["Ashare", "Crypto", "US"]:
            cur = con.execute(
                "SELECT MAX(trade_date) FROM market_bars_daily WHERE market=?",
                (market,),
            )
            row = cur.fetchone()
            latest = row[0] if row and row[0] else "?"
            if latest == "?":
                days = 999
            else:
                days = (datetime.now() - datetime.strptime(latest, "%Y%m%d")).days
            status = "ok" if days <= 1 else "degraded"
            if days > 1:
                degraded.append(f"{market}({latest})")
            markets[market] = {"latest": latest, "age_days": days, "status": status}

        return {
            "status": "degraded" if degraded else "ok",
            "markets": markets,
        }
    finally:
        con.close()


def _check_cron_activity() -> dict[str, Any]:
    log_dir = RUNTIME_ROOT / "staging" / "logs"
    if not log_dir.exists():
        return {"status": "degraded", "message": "log directory not found", "active_logs": 0}

    r = subprocess.run(
        ["find", str(log_dir), "-name", "*.log", "-mmin", "-15"],
        capture_output=True, text=True, timeout=10,
    )
    active = len([l for l in r.stdout.splitlines() if l.strip()])
    return {
        "status": "ok" if active > 0 else "degraded",
        "active_logs": active,
    }


def _check_architecture() -> dict[str, Any]:
    reader_path = SS / "reader.py"
    if not reader_path.exists():
        return {"status": "error", "message": "reader.py not found"}

    source = reader_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    mg_refs = sum(1 for l in lines if "MARKETGRAPH_ROOT" in l and "MARKETGRAPH_ROOT =" not in l)
    ashare_refs = sum(1 for l in lines if "ASHARE_ROOT" in l and "data" in l)
    violations = mg_refs + ashare_refs

    return {
        "status": "ok" if violations == 0 else "degraded",
        "marketgraph_refs": mg_refs,
        "ashare_data_refs": ashare_refs,
    }


def _check_compile() -> dict[str, Any]:
    failed: list[str] = []
    for fname in ["reader.py", "api_server.py"]:
        fpath = SS / fname
        if not fpath.exists():
            failed.append(f"{fname} (missing)")
            continue
        try:
            compile(fpath.read_text(encoding="utf-8"), fname, "exec")
        except SyntaxError as exc:
            failed.append(f"{fname}: {exc}")

    return {
        "status": "ok" if not failed else "error",
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# CLI entry point (original behaviour)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _load_env()

    import reader  # noqa: E402

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"=== SharedSignals Health [{now}] ===")

    result = get_health_status()
    for section, detail in result["checks"].items():
        status = detail.get("status", "?")
        marker = "OK" if status == "ok" else status.upper()
        if section == "functions":
            print(
                f"[FUNCTIONS] {detail.get('ok')}/{detail.get('total')} OK"
                + (f" | DEGRADED: {detail.get('degraded')}" if detail.get("degraded") else " | ALL CLEAN")
            )
        elif section == "data_freshness":
            for market, info in detail.get("markets", {}).items():
                print(f"[DATA] {market}: {info['latest']} [{info['status'].upper()}]")
        elif section == "cron":
            print(f"[CRON] {detail.get('active_logs')} logs updated in 15min [{marker}]")
        elif section == "architecture":
            print(
                f"[ARCH] MG_refs={detail.get('marketgraph_refs')} "
                f"Ashare_data_refs={detail.get('ashare_data_refs')} [{marker}]"
            )
        elif section == "compile":
            print(f"[COMPILE] {marker}" + (f" {detail.get('failed')}" if detail.get("failed") else ""))

    print(f"\n{'ALL CLEAN' if result['status'] == 'ok' else 'ISSUES: status=' + result['status']}")
