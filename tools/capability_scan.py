#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SharedSignals Capability Scanner — hourly smoke test of all reader functions.

Scans 15 reader functions across SharedSignals reference/, bridge/ and
collectors/, records health status, writes capability_registry.json, generates
API_CONTRACT.md, and tracks changes in capability_changes.jsonl.

Usage:
    python3 capability_scan.py                  # full scan + registry + doc + changes
    python3 capability_scan.py --json           # full scan, print JSON to stdout
    python3 capability_scan.py --test-only      # self-test: get_market_data, is_trading_day, get_reference
    python3 capability_scan.py --dry-run        # scan but don't write files
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

# ---- Path setup ----
TOOLS_DIR = Path(__file__).resolve().parent
SHARED_SIGNALS = TOOLS_DIR.parent
REFERENCE_DIR = SHARED_SIGNALS / "reference"
BRIDGE_DIR = SHARED_SIGNALS / "bridge"
COLLECTORS_DIR = SHARED_SIGNALS / "collectors"
DOCS_DIR = SHARED_SIGNALS / "docs"

REGISTRY_PATH = TOOLS_DIR / "capability_registry.json"
CHANGES_PATH = TOOLS_DIR / "capability_changes.jsonl"
DOC_PATH = DOCS_DIR / "API_CONTRACT.md"

for _d in (str(REFERENCE_DIR), str(BRIDGE_DIR), str(COLLECTORS_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

UTC = timezone.utc
CST = timezone(timedelta(hours=8))


# ============================================================================
# Reader function definitions (15 functions across 3 modules)
# ============================================================================

READER_REGISTRY: dict[str, dict[str, Any]] = {
    # --- market_calendar.py (reference/) ---
    "is_trading_day": {
        "module": "market_calendar",
        "func": "is_trading_day",
        "path": "reference/market_calendar.py",
        "category": "calendar",
        "description": "Check if a given date is an A-share trading day",
        "smoke_args": [],
        "version": "1.0.0",
        "fields": ["date", "result"],
        "sla_hours": 24,
    },
    "get_trading_days": {
        "module": "market_calendar",
        "func": "get_trading_days",
        "path": "reference/market_calendar.py",
        "category": "calendar",
        "description": "Return all A-share trading days in a date range",
        "smoke_args": ["2026-06-01", "2026-06-30"],
        "version": "1.0.0",
        "fields": ["start", "end", "trading_days"],
        "sla_hours": 24,
    },

    # --- a_share_tushare_api.py (reference/, symlinked) ---
    "get_market_data": {
        "module": "a_share_tushare_api",
        "func": "get_daily",
        "path": "reference/a_share_tushare_api.py",
        "category": "market_data",
        "description": "Get A-share daily OHLCV data for one or more stocks",
        "smoke_args": ["601698.SH", "2026-06-26", "2026-06-26"],
        "version": "2.0.0",
        "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
        "sla_hours": 24,
    },
    "get_moneyflow": {
        "module": "a_share_tushare_api",
        "func": "get_moneyflow",
        "path": "reference/a_share_tushare_api.py",
        "category": "market_depth",
        "description": "Get A-share money flow data for a trading day",
        "smoke_args": ["20260626"],
        "version": "1.0.0",
        "fields": ["ts_code", "trade_date", "buy_sm_vol", "sell_sm_vol", "net_mf_vol"],
        "sla_hours": 24,
    },
    "get_margin": {
        "module": "a_share_tushare_api",
        "func": "get_margin",
        "path": "reference/a_share_tushare_api.py",
        "category": "market_depth",
        "description": "Get margin trading summary for a trading day",
        "smoke_args": ["20260626"],
        "version": "1.0.0",
        "fields": ["trade_date", "rzye", "rzmre", "rqye", "rqmcl"],
        "sla_hours": 24,
    },
    "get_limit_list": {
        "module": "a_share_tushare_api",
        "func": "get_limit_list_d",
        "path": "reference/a_share_tushare_api.py",
        "category": "market_depth",
        "description": "Get limit-up/limit-down list for a trading day",
        "smoke_args": ["20260626"],
        "version": "1.0.0",
        "fields": ["ts_code", "trade_date", "limit", "pct_chg", "close"],
        "sla_hours": 24,
    },
    "get_hk_hold": {
        "module": "a_share_tushare_api",
        "func": "get_hk_hold",
        "path": "reference/a_share_tushare_api.py",
        "category": "cross_border",
        "description": "Get northbound (HK->A) holdings for a trading day",
        "smoke_args": ["20260626"],
        "version": "1.0.0",
        "fields": ["ts_code", "trade_date", "vol", "hold_vol", "hold_ratio"],
        "sla_hours": 24,
    },
    "get_stock_minutes": {
        "module": "a_share_tushare_api",
        "func": "get_stk_mins",
        "path": "reference/a_share_tushare_api.py",
        "category": "intraday",
        "description": "Get intraday minute-level bars for a stock",
        "smoke_args": ["000001.SZ", "20260626"],
        "version": "1.0.0",
        "fields": ["ts_code", "trade_time", "open", "high", "low", "close", "vol"],
        "sla_hours": 6,
    },
    "get_news_list": {
        "module": "a_share_tushare_api",
        "func": "get_news",
        "path": "reference/a_share_tushare_api.py",
        "category": "events",
        "description": "Get news headlines for a date range",
        "smoke_args": ["20260626", "20260626"],
        "version": "1.0.0",
        "fields": ["datetime", "content", "source", "title"],
        "sla_hours": 6,
    },

    # --- bridge/ (marketgraph unified marketdata DB) ---
    "get_crypto_klines": {
        "module": "marketgraph_marketdata_db",
        "func": "read_daily",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "crypto",
        "description": "Read Crypto daily OHLCV from unified marketdata DB",
        "smoke_args": ["Crypto", "BTCUSDT", "", "", 10],
        "version": "1.0.0",
        "fields": ["symbol", "trade_date", "open", "high", "low", "close", "volume"],
        "sla_hours": 6,
    },
    "get_us_daily": {
        "module": "marketgraph_marketdata_db",
        "func": "read_daily",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "us_market",
        "description": "Read US stock daily data from unified marketdata DB",
        "smoke_args": ["US", "AAPL", "", "", 10],
        "version": "1.0.0",
        "fields": ["symbol", "trade_date", "open", "high", "low", "close", "volume"],
        "sla_hours": 24,
    },
    "get_hk_etf": {
        "module": "marketgraph_marketdata_db",
        "func": "read_daily",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "hk_market",
        "description": "Read HK ETF daily data from unified marketdata DB",
        "smoke_args": ["HK", "159920.SZ", "", "", 10],
        "version": "1.0.0",
        "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol"],
        "sla_hours": 24,
    },
    "get_hk_index": {
        "module": "marketgraph_marketdata_db",
        "func": "read_daily",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "hk_market",
        "description": "Read HSI index data from unified marketdata DB",
        "smoke_args": ["HK", "", "", "", 10],
        "version": "1.0.0",
        "fields": ["symbol", "trade_date", "open", "high", "low", "close", "volume"],
        "sla_hours": 24,
    },
    "get_pm_markets": {
        "module": "marketgraph_marketdata_db",
        "func": "read_pm_markets",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "prediction_markets",
        "description": "Read Polymarket market list from unified marketdata DB",
        "smoke_args": [50],
        "version": "1.0.0",
        "fields": ["market_name", "outcome", "price", "volume", "updated_at"],
        "sla_hours": 6,
    },

    # --- reference/ (coverage & registry) ---
    "get_reference": {
        "module": "marketgraph_marketdata_db",
        "func": "read_coverage_status",
        "path": "bridge/marketgraph_marketdata_db.py",
        "category": "reference",
        "description": "Read data coverage status from unified marketdata DB",
        "smoke_args": [],
        "version": "1.0.0",
        "fields": ["market", "symbol_count", "earliest_date", "latest_date", "status"],
        "sla_hours": 24,
    },
}


# ============================================================================
# Core scanner
# ============================================================================

def _to_cst(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(UTC)
    return dt.astimezone(CST).isoformat(timespec="seconds")


def _import_module(mod_name: str) -> Optional[Any]:
    try:
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        return importlib.import_module(mod_name)
    except Exception:
        return None


def _call_func(mod: Any, func_name: str, args: list) -> dict[str, Any]:
    start = time.perf_counter()
    result = None
    rows = 0
    error = None
    try:
        fn = getattr(mod, func_name, None)
        if fn is None:
            error = f"Function '{func_name}' not found in module"
        elif not callable(fn):
            error = f"'{func_name}' is not callable (type={type(fn).__name__})"
        else:
            result = fn(*args)
            if isinstance(result, list):
                rows = len(result)
            elif isinstance(result, dict):
                for v in result.values():
                    if isinstance(v, list):
                        rows = max(rows, len(v))
                if rows == 0 and result:
                    rows = 1
            elif result is not None:
                rows = 1
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    return {"result": result, "rows": rows, "error": error, "latency_ms": elapsed_ms}


def _determine_status(error: Optional[str], rows: int) -> str:
    """Determine endpoint status: ok / degraded / down.

    - down: hard failures — missing module, function not found, network unreachable
    - degraded: soft failures — auth/config missing, empty result, partial errors
    - ok: function returned data successfully
    """
    if error:
        err_lower = error.lower()
        # Hard failures → down
        if "no module named" in err_lower or "modulenotfound" in err_lower:
            return "down"
        if "has no attribute" in err_lower or "not callable" in err_lower:
            return "down"
        if "connection refused" in err_lower or "network is unreachable" in err_lower:
            return "down"
        # Soft failures → degraded (auth/config/empty results)
        return "degraded"
    if rows == 0:
        return "degraded"
    return "ok"


def _load_previous_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _compute_summary(endpoints: list[dict]) -> dict[str, int]:
    total = len(endpoints)
    ok = sum(1 for ep in endpoints if ep["status"] == "ok")
    degraded = sum(1 for ep in endpoints if ep["status"] == "degraded")
    down = sum(1 for ep in endpoints if ep["status"] == "down")
    return {"total": total, "ok": ok, "degraded": degraded, "down": down}


# ============================================================================
# Change detection
# ============================================================================

def _detect_changes(
    new_endpoints: list[dict],
    prev_registry: dict[str, Any],
    scan_time: str,
) -> list[dict]:
    changes: list[dict] = []
    prev_eps = prev_registry.get("endpoints", [])
    prev_map = {ep["name"]: ep for ep in prev_eps}
    new_map = {ep["name"]: ep for ep in new_endpoints}

    for name, ep in new_map.items():
        prev = prev_map.get(name)
        if prev is None:
            changes.append({
                "timestamp": scan_time,
                "endpoint": name,
                "type": "new",
                "detail": f"New endpoint registered: {name}",
                "status": ep["status"],
            })
            continue
        if prev["status"] in ("ok", "degraded") and ep["status"] == "down":
            changes.append({
                "timestamp": scan_time,
                "endpoint": name,
                "type": "fault",
                "detail": f"Went down: {prev['status']} -> {ep['status']} (error: {ep.get('error', '')[:200]})",
                "status": ep["status"],
            })
        elif prev["status"] == "down" and ep["status"] in ("ok", "degraded"):
            changes.append({
                "timestamp": scan_time,
                "endpoint": name,
                "type": "recovered",
                "detail": f"Recovered: {prev['status']} -> {ep['status']}",
                "status": ep["status"],
            })
        elif prev["status"] != ep["status"]:
            changes.append({
                "timestamp": scan_time,
                "endpoint": name,
                "type": "status_change",
                "detail": f"{prev['status']} -> {ep['status']}",
                "status": ep["status"],
            })

    removed = set(prev_map) - set(new_map)
    for name in removed:
        changes.append({
            "timestamp": scan_time,
            "endpoint": name,
            "type": "deprecated",
            "detail": f"Endpoint removed from registry: {name}",
            "status": "deprecated",
        })
    return changes


def _write_changes(changes: list[dict]) -> None:
    if not changes:
        return
    CHANGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHANGES_PATH.open("a", encoding="utf-8") as fh:
        for change in changes:
            fh.write(json.dumps(change, ensure_ascii=False) + "\n")


# ============================================================================
# Auto-doc: API_CONTRACT.md generation
# ============================================================================

def _generate_api_contract_md(endpoints: list[dict], scan_time: str, summary: dict) -> str:
    lines: list[str] = []
    lines.append("# SharedSignals API Contract")
    lines.append("")
    lines.append(f"> Auto-generated from `capability_registry.json` at {scan_time}")
    lines.append(f"> Service: SharedSignals v1.0.0")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Total endpoints | {summary['total']} |")
    lines.append(f"| OK | {summary['ok']} |")
    lines.append(f"| Degraded | {summary['degraded']} |")
    lines.append(f"| Down | {summary['down']} |")
    if summary.get("new_this_week"):
        lines.append(f"| New this week | {summary['new_this_week']} |")
    if summary.get("deprecated"):
        lines.append(f"| Deprecated | {summary['deprecated']} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    by_category: dict[str, list[dict]] = {}
    for ep in endpoints:
        cat = ep.get("category", "uncategorized")
        by_category.setdefault(cat, []).append(ep)

    for cat, eps in sorted(by_category.items()):
        lines.append(f"## {cat.replace('_', ' ').title()}")
        lines.append("")
        for ep in eps:
            status_icon = {"ok": "[OK]", "degraded": "[DEGRADED]", "down": "[DOWN]"}.get(ep["status"], "[?]")
            lines.append(f"### {status_icon} `{ep['name']}`")
            lines.append("")
            lines.append(f"- **Status**: `{ep['status']}`")
            lines.append(f"- **Path**: `{ep.get('path', 'N/A')}`")
            lines.append(f"- **Version**: `{ep.get('version', 'N/A')}`")
            lines.append(f"- **Latency**: {ep.get('latency_ms', 'N/A')}ms")
            lines.append(f"- **Rows returned**: {ep.get('rows', 0)}")
            lines.append(f"- **SLA**: {ep.get('sla_hours', 24)}h freshness")
            lines.append(f"- **Fields**: {', '.join(ep.get('fields', []))}")
            lines.append(f"- **Description**: {ep.get('description', 'N/A')}")
            if ep.get("last_success"):
                lines.append(f"- **Last success**: {ep['last_success']}")
            if ep.get("error"):
                lines.append(f"- **Last error**: `{ep['error'][:200]}`")
            if ep.get("degraded"):
                lines.append(f"- **Degraded reason**: {ep['degraded']}")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## All Endpoints")
    lines.append("")
    lines.append("| Name | Status | Latency (ms) | Rows | SLA (h) | Category | Path |")
    lines.append("|------|--------|-------------|------|---------|----------|------|")
    for ep in endpoints:
        name = ep["name"]
        status = ep["status"]
        lat = ep.get("latency_ms", "-")
        rows = ep.get("rows", 0)
        sla = ep.get("sla_hours", "-")
        cat = ep.get("category", "-")
        path = ep.get("path", "-")
        lines.append(f"| `{name}` | `{status}` | {lat} | {rows} | {sla} | {cat} | `{path}` |")
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# Main scan entry point
# ============================================================================

def run_scan(dry_run: bool = False, test_only: bool = False) -> dict[str, Any]:
    scan_time = _to_cst()
    prev_registry = _load_previous_registry()

    if test_only:
        target_names = {"get_market_data", "is_trading_day", "get_reference"}
        endpoints_to_scan = {k: v for k, v in READER_REGISTRY.items() if k in target_names}
    else:
        endpoints_to_scan = READER_REGISTRY

    # Pre-import modules
    module_cache: dict[str, Any] = {}
    for ep in endpoints_to_scan.values():
        mod_name = ep["module"]
        if mod_name not in module_cache:
            module_cache[mod_name] = _import_module(mod_name)

    # Scan each endpoint
    endpoints: list[dict] = []
    prev_ep_map = {ep["name"]: ep for ep in prev_registry.get("endpoints", [])}

    for name, meta in endpoints_to_scan.items():
        mod = module_cache.get(meta["module"])
        prev_ep = prev_ep_map.get(name, {})

        if mod is None:
            result = {
                "name": name,
                "path": meta["path"],
                "status": "degraded",
                "latency_ms": 0,
                "rows": 0,
                "error": f"Module '{meta['module']}' could not be imported (missing deps or auth)",
                "last_success": prev_ep.get("last_success", ""),
                "timestamp": scan_time,
                "version": meta.get("version", "1.0.0"),
                "fields": meta.get("fields", []),
                "freshness": meta.get("sla_hours", 24),
                "degraded": f"Module '{meta['module']}' import failed (check deps/auth/env)",
            }
        else:
            call_result = _call_func(mod, meta["func"], meta.get("smoke_args", []))
            status = _determine_status(call_result["error"], call_result["rows"])

            last_success = prev_ep.get("last_success", "")
            if status == "ok":
                last_success = scan_time

            degraded = None
            if status == "degraded":
                if call_result["error"]:
                    err = call_result["error"]
                    if "token" in err.lower() or "keyerror" in err.lower():
                        degraded = f"Auth/config missing: {err[:200]}"
                    elif "timeout" in err.lower():
                        degraded = f"Response timeout: {err[:200]}"
                    elif call_result["rows"] == 0:
                        degraded = f"Returned 0 rows + error: {err[:200]}"
                    else:
                        degraded = f"Partial error: {err[:200]}"
                elif call_result["rows"] == 0:
                    degraded = "Returned 0 rows (possibly stale or empty)"

            result = {
                "name": name,
                "path": meta["path"],
                "status": status,
                "latency_ms": call_result["latency_ms"],
                "rows": call_result["rows"],
                "error": call_result["error"],
                "last_success": last_success,
                "timestamp": scan_time,
                "version": meta.get("version", "1.0.0"),
                "fields": meta.get("fields", []),
                "freshness": meta.get("sla_hours", 24),
                "degraded": degraded,
            }
        endpoints.append(result)

    summary = _compute_summary(endpoints)

    # New/deprecated counts
    prev_names = {ep["name"] for ep in prev_registry.get("endpoints", [])}
    new_names = {ep["name"] for ep in endpoints}
    summary["new_this_week"] = len(new_names - prev_names)
    summary["deprecated"] = len(prev_names - new_names)

    # Build registry
    registry: dict[str, Any] = {
        "scan_time": scan_time,
        "endpoints": endpoints,
        "summary": summary,
    }

    # Detect and write changes
    changes = _detect_changes(endpoints, prev_registry, scan_time)
    if not dry_run:
        _write_changes(changes)

    # Write registry
    if not dry_run:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REGISTRY_PATH.open("w", encoding="utf-8") as fh:
            json.dump(registry, fh, ensure_ascii=False, indent=2)

    # Generate and write API_CONTRACT.md
    doc_md = _generate_api_contract_md(endpoints, scan_time, summary)
    if not dry_run:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(doc_md, encoding="utf-8")

    return {"registry": registry, "changes": changes, "doc_path": str(DOC_PATH) if not dry_run else "(dry-run)"}


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description="SharedSignals Capability Scanner")
    ap.add_argument("--json", action="store_true", help="Print registry as JSON to stdout")
    ap.add_argument("--dry-run", action="store_true", help="Scan but do not write files")
    ap.add_argument("--test-only", action="store_true",
                    help="Self-test: scan only get_market_data, is_trading_day, get_reference")
    args = ap.parse_args()

    result = run_scan(dry_run=args.dry_run, test_only=args.test_only)
    registry = result["registry"]

    if args.json:
        print(json.dumps(registry, ensure_ascii=False, indent=2))
        return

    scan_time = registry["scan_time"]
    summary = registry["summary"]
    endpoints = registry["endpoints"]

    print(f"Capability Scan @ {scan_time}")
    print(f"  Total: {summary['total']}  OK: {summary['ok']}  Degraded: {summary['degraded']}  Down: {summary['down']}")
    if summary.get("new_this_week"):
        print(f"  New this week: {summary['new_this_week']}")
    if summary.get("deprecated"):
        print(f"  Deprecated: {summary['deprecated']}")
    print()

    for ep in endpoints:
        icon = {"ok": "+", "degraded": "~", "down": "X"}.get(ep["status"], "?")
        extra = ""
        if ep.get("error"):
            extra = f"  ERR: {ep['error'][:120]}"
        elif ep.get("degraded"):
            extra = f"  WARN: {ep['degraded'][:120]}"
        print(f"  {icon} {ep['name']:<28s} {ep['status']:<10s} {ep['latency_ms']:>7.1f}ms  rows={ep['rows']:>5d}{extra}")

    if not args.dry_run:
        print(f"\nRegistry written to: {REGISTRY_PATH}")
        print(f"Contract doc written to: {DOC_PATH}")
        if result["changes"]:
            print(f"Changes appended to: {CHANGES_PATH} ({len(result['changes'])} events)")
        else:
            print("No status changes detected.")

    if summary["down"] > 0:
        sys.exit(2)
    elif summary["degraded"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
