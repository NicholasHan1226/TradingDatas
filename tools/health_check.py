#!/usr/bin/env python3
"""SharedSignals health check — importable by api_server and usable as CLI.

Public API:
    get_health_status() -> dict   Reusable, no side effects, fast enough for /health.
"""

from __future__ import annotations

import csv
import json
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
    check_sla: bool = True,
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

    # 4. Per-table SLA -----------------------------------------------------
    if check_sla:
        try:
            sla = _load_health_sla_report()
            checks["sla"] = sla
            overall = _worse(overall, sla["status"])
        except Exception as exc:
            checks["sla"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 5. Architecture compliance -------------------------------------------
    if check_arch:
        try:
            arch = _check_architecture()
            checks["architecture"] = arch
            overall = _worse(overall, arch["status"])
        except Exception as exc:
            checks["architecture"] = {"status": "error", "message": str(exc)}
            overall = _worse(overall, "error")

    # 6. Compile -----------------------------------------------------------
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

def _latest_csv_date(path: Path, column: str) -> str | None:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        latest = ""
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                value = str(row.get(column) or row.get("candidate_date") or row.get("collected_at_dt") or row.get("collected_at") or "").strip()
                if value.isdigit() and len(value) == 8:
                    try:
                        parsed = datetime.strptime(value, "%Y%m%d")
                    except ValueError:
                        continue
                    if parsed.year < 2020 or value > datetime.now().strftime("%Y%m%d"):
                        continue
                    latest = max(latest, value)
        return latest or None
    except Exception:
        return None


def _decode_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    index = 0
    latest: dict[str, Any] | None = None
    while index < len(text):
        brace = text.find("{", index)
        if brace < 0:
            break
        try:
            value, end = decoder.raw_decode(text[brace:])
        except json.JSONDecodeError:
            index = brace + 1
            continue
        if isinstance(value, dict):
            latest = value
        index = brace + end
    return latest


def _normalize_sla_report(raw: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    raw_status = str(raw.get("status") or "error")
    section_status = "error" if raw_status == "critical" else ("degraded" if raw_status in {"degraded", "missing", "invalid", "stale"} else "ok")
    result = {**raw, "sla_status": raw_status, "status": section_status}
    if path is not None:
        result["report_path"] = str(path)
        try:
            result["report_age_seconds"] = round(max(0.0, datetime.now().timestamp() - path.stat().st_mtime), 1)
        except OSError:
            pass
    return result


def _load_health_sla_report() -> dict[str, Any]:
    path = Path(os.environ.get("SHAREDSIGNALS_HEALTH_SLA_REPORT", str(SS / "logs" / "watchdog_inputs" / "health_sla.json")))
    if not path.exists():
        return _normalize_sla_report({"status": "missing", "message": "health_sla report not found"}, path=path)
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return _normalize_sla_report({"status": "invalid", "message": "health_sla report is empty"}, path=path)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = _decode_last_json_object(text)
    if not isinstance(raw, dict) or "summary" not in raw:
        return _normalize_sla_report({"status": "invalid", "message": "health_sla report is not a valid SLA payload"}, path=path)
    return _normalize_sla_report(raw, path=path)


def _reader_samples() -> dict[str, str]:
    samples = {
        "calendar_date": datetime.now().strftime("%Y%m%d"),
        "daily_symbol": "000001.SZ",
        "daily_date": "20260629",
        "moneyflow_symbol": "000001.SZ",
        "moneyflow_date": "20260629",
        "event_date": "20260629",
        "sentiment_date": "20260628",
        "industry_symbol": "000001.SZ",
        "intraday_symbol": "000001.SZ",
        "intraday_date": "20260629",
    }
    db_path = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"
    if db_path.exists():
        con = sqlite3.connect(str(db_path), timeout=5)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT symbol, trade_date FROM market_bars_daily WHERE market='Ashare' ORDER BY trade_date DESC LIMIT 1").fetchone()
            if row:
                samples["daily_symbol"] = str(row["symbol"] or samples["daily_symbol"])
                samples["daily_date"] = str(row["trade_date"] or samples["daily_date"])
            row = con.execute("SELECT symbol, event_time FROM market_factors WHERE market='Ashare' AND factor_name LIKE 'moneyflow:%' ORDER BY event_time DESC, collected_at DESC LIMIT 1").fetchone()
            if row:
                samples["moneyflow_symbol"] = str(row["symbol"] or samples["moneyflow_symbol"])
                samples["moneyflow_date"] = str(row["event_time"] or samples["moneyflow_date"])
            row = con.execute("SELECT trade_date FROM market_events WHERE COALESCE(trade_date, '') != '' ORDER BY trade_date DESC LIMIT 1").fetchone()
            if row:
                samples["event_date"] = str(row["trade_date"] or samples["event_date"])
            row = con.execute("SELECT symbol FROM market_assets WHERE market='Ashare' AND COALESCE(sector, '') != '' ORDER BY symbol LIMIT 1").fetchone()
            if row:
                samples["industry_symbol"] = str(row["symbol"] or samples["industry_symbol"])
            row = con.execute("SELECT symbol, trade_date FROM market_bars_intraday WHERE market='Ashare' ORDER BY trade_date DESC, bar_time DESC LIMIT 1").fetchone()
            if row:
                samples["intraday_symbol"] = str(row["symbol"] or samples["intraday_symbol"])
                samples["intraday_date"] = str(row["trade_date"] or samples["intraday_date"])
        finally:
            con.close()
    event_date = _latest_csv_date(SS / "data" / "intake" / "event_candidates.csv", "candidate_date")
    if event_date:
        samples["event_date"] = event_date
    sentiment_date = (
        _latest_csv_date(SS / "data" / "intake" / "sentiment_signals.csv", "source_date")
        or _latest_csv_date(SS / "data" / "sentiment_signals.csv", "source_date")
    )
    if sentiment_date:
        samples["sentiment_date"] = sentiment_date
    return samples


def _check_reader_functions() -> dict[str, Any]:
    if str(SS) not in sys.path:
        sys.path.insert(0, str(SS))

    # Use explicit imports instead of wildcard
    import reader  # noqa: E402

    samples = _reader_samples()
    funcs: list[tuple[str, Any]] = [
        ("is_trading_day", reader.is_trading_day(samples["calendar_date"])),
        ("market_data", reader.get_market_data(samples["daily_symbol"], samples["daily_date"], samples["daily_date"])),
        ("fundamentals", reader.get_fundamentals(samples["daily_symbol"])),
        ("reference", reader.get_reference("stock_master")),
        ("macro", reader.get_macro_factors("20260601", "20260629")),
        ("capital_flow", reader.get_capital_flow(samples["moneyflow_date"], ts_code=samples["moneyflow_symbol"])),
        ("sentiment", reader.get_sentiment(samples["sentiment_date"], samples["sentiment_date"])),
        ("crypto", reader.get_crypto_klines("BTCUSDT", 5)),
        ("pm_markets", reader.get_pm_markets(5)),
        ("industry", reader.get_industry(samples["industry_symbol"])),
        ("realtime_5min", reader.get_realtime_5min(ts_code=samples["intraday_symbol"], date=samples["intraday_date"])),
        ("tushare", reader.get_tushare(api_name="stock_basic", ts_code=samples["industry_symbol"])),
    ]
    skipped = {
        "events": "delegated_to_marketgraph_or_future_sharedsignals_event_collector",
        "associations": "marketgraph_research_graph_endpoint",
        "impacts": "marketgraph_research_graph_endpoint",
    }

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
        "total": len(funcs) + len(skipped),
        "degraded": degraded,
        "skipped": skipped,
        "samples": samples,
    }


def _check_data_freshness() -> dict[str, Any]:
    db_path = RUNTIME_ROOT / "read_model" / "marketdata.sqlite"
    if not db_path.exists():
        return {"status": "error", "message": f"database not found: {db_path}"}

    con = sqlite3.connect(str(db_path), timeout=5)
    try:
        markets: dict[str, Any] = {}
        degraded: list[str] = []
        today_dt = datetime.now()
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
                days = (today_dt - datetime.strptime(latest, "%Y%m%d")).days
            if market == "Crypto":
                max_age_days = 1
            elif market == "US" and today_dt.weekday() == 0:
                max_age_days = 4
            elif today_dt.weekday() in (5, 6, 0):
                max_age_days = 3
            else:
                max_age_days = 1
            status = "ok" if days <= max_age_days else "degraded"
            if days > max_age_days:
                degraded.append(f"{market}({latest})")
            markets[market] = {"latest": latest, "age_days": days, "max_age_days": max_age_days, "status": status}

        return {
            "status": "degraded" if degraded else "ok",
            "markets": markets,
        }
    finally:
        con.close()


def _check_cron_activity() -> dict[str, Any]:
    log_dirs = [
        Path(os.environ["SHAREDSIGNALS_CRON_LOG_DIR"])
        if os.environ.get("SHAREDSIGNALS_CRON_LOG_DIR")
        else None,
        SS / "logs" / "cron",
        SS / "logs",
        RUNTIME_ROOT / "staging" / "logs",
    ]
    existing = [path for path in log_dirs if path is not None and path.exists()]
    if not existing:
        return {
            "status": "degraded",
            "message": "log directory not found",
            "active_logs": 0,
            "checked_dirs": [str(path) for path in log_dirs if path is not None],
        }

    active_files: set[str] = set()
    errors: list[str] = []
    for log_dir in existing:
        try:
            r = subprocess.run(
                ["find", str(log_dir), "-name", "*.log", "-mmin", "-15"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if r.returncode != 0:
                errors.append(f"{log_dir}: {r.stderr.strip() or r.returncode}")
                continue
            active_files.update(l.strip() for l in r.stdout.splitlines() if l.strip())
        except Exception as exc:
            errors.append(f"{log_dir}: {exc}")

    active = len(active_files)
    result = {
        "status": "ok" if active > 0 else "degraded",
        "active_logs": active,
        "checked_dirs": [str(path) for path in existing],
    }
    if errors:
        result["errors"] = errors
    return result


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
