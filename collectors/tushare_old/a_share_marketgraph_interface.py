#!/usr/bin/env python3
"""A-share client for the stable MarketGraph read interface.

A-share tools should import this module instead of reading
`../MarketGraph/data` directly.  Transport: local CSV through
MarketGraph/08-Market-Interfaces (default) or MCP stdio (set
env MARKGRAPH_TRANSPORT=mcp).  Set MG_MCP_SERVER to point to
the MCP server entrypoint (default: marketgraph_mcp_server.py).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from functools import lru_cache
from typing import Any

from a_share_common import MARKETGRAPH_ROOT


DEFAULT_MARKET = "Ashare"
MARKETGRAPH_GATEWAY = MARKETGRAPH_ROOT / "08-Market-Interfaces" / "tools" / "marketgraph_interface_gateway.py"
MCP_SERVER = os.environ.get(
    "MG_MCP_SERVER",
    str(MARKETGRAPH_ROOT / "08-Market-Interfaces" / "tools" / "marketgraph_mcp_server.py"),
)
TRANSPORT = os.environ.get("MARKGRAPH_TRANSPORT", "local")  # "local" | "mcp"


def _mcp_call(tool: str, args: dict | None = None) -> dict:
    """Call MarketGraph MCP server via stdio JSON-RPC.  Returns the tool result dict, or {'error': ...}."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
    try:
        proc = subprocess.run(
            [sys.executable, MCP_SERVER],
            input=json.dumps(req) + "\n",
            capture_output=True, text=True, timeout=120,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == 1:
                    content = resp.get("result", {}).get("content", [])
                    return json.loads(content[0]["text"]) if content else {}
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
        return {"error": "no MCP response"}
    except Exception as exc:
        return {"error": str(exc)}


@lru_cache(maxsize=1)
def _gateway_module() -> Any:
    if TRANSPORT == "mcp":
        return None  # MCP mode — no direct import
    spec = importlib.util.spec_from_file_location("_marketgraph_interface_gateway", MARKETGRAPH_GATEWAY)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load MarketGraph interface gateway: {MARKETGRAPH_GATEWAY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def marketgraph_interface_snapshot(*, market: str = DEFAULT_MARKET, include_rows: bool = False) -> dict[str, Any]:
    """Return the MarketGraph contract snapshot for this market."""
    if TRANSPORT == "mcp":
        return _mcp_call("read_market_interface_snapshot", {"market": market})
    try:
        return _gateway_module().read_market_interface_snapshot(
            market=market,
            project_root=MARKETGRAPH_ROOT,
            include_rows=include_rows,
        )
    except Exception as exc:
        return {
            "market": market,
            "contract_status": "unavailable",
            "access_mode": "read_only",
            "mcp_ready": TRANSPORT == "mcp",
            "transport": ["mcp"] if TRANSPORT == "mcp" else ["local_csv"],
            "tables": {},
            "error": str(exc),
            "marketgraph_root": str(MARKETGRAPH_ROOT),
            "boundary": "MarketGraph unavailable; A-share consumers must degrade without relaxing gates.",
        }


def read_marketgraph_fx_rates_latest() -> dict[str, Any]:
    """Read the latest FX/Rates context through the MarketGraph gateway.

    This is background context only. It never creates A-share trading
    permission and missing data must not relax local gates.
    """
    if TRANSPORT == "mcp":
        result = _mcp_call("read_fx_rates_latest")
        return result if isinstance(result, dict) else {"exists": bool(result)}
    try:
        payload = _gateway_module().read_fx_rates_latest(project_root=MARKETGRAPH_ROOT)
    except Exception as exc:
        return {
            "exists": False,
            "status": "unavailable",
            "indicators": [],
            "cross_source_checks": [],
            "error": str(exc),
            "freshness_policy": "FX/Rates recency unavailable; do not convert this into market direction or trading permission.",
            "boundary": "FX/Rates context unavailable; A-share consumers must continue without relaxing gates.",
        }
    return payload if isinstance(payload, dict) else {}


def _interface_error(
    error: str,
    table_id: str,
    market: str,
    *,
    missing_tables: list[str] | None = None,
    field_mismatches: list[str] | None = None,
) -> dict[str, Any]:
    """Build an error response for ``read_marketgraph_table``.

    When the gateway is reachable, the snapshot's ``missing_tables`` and
    ``field_mismatches`` arrays are reused so callers see the full contract
    picture. If the snapshot is unavailable, the requested ``table_id`` is
    conservatively reported as missing.
    """
    missing = list(missing_tables or [])
    mismatches = list(field_mismatches or [])
    if not missing and not mismatches:
        try:
            snapshot = marketgraph_interface_snapshot(market=market, include_rows=False)
            missing = list(snapshot.get("missing_tables") or [])
            mismatches = list(snapshot.get("field_mismatches") or [])
        except Exception:
            pass
    if not missing and not mismatches:
        missing = [table_id]
    return {
        "rows": [],
        "error": error,
        "missing_tables": missing,
        "field_mismatches": mismatches,
    }


def _rows_from_result(result: list[dict[str, str]] | dict[str, Any]) -> list[dict[str, str]]:
    """Extract rows from a successful list result or an error dict."""
    if isinstance(result, dict):
        rows = result.get("rows", [])
        return rows if isinstance(rows, list) else []
    return result


def read_marketgraph_table(
    table_id: str,
    *,
    market: str = DEFAULT_MARKET,
) -> list[dict[str, str]] | dict[str, Any]:
    """Read one MarketGraph table by contract id.

    On success this returns the list of CSV rows, preserving the legacy
    contract. On any failure (gateway missing, unknown table, field mismatch,
    etc.) it returns a dict with error details so problems are visible instead
    of silently degrading to ``[]``.

    Error dict shape::

        {
            "rows": [],
            "error": str,
            "missing_tables": [...],
            "field_mismatches": [...],
        }
    """
    if TRANSPORT == "mcp":
        result = _mcp_call("read_contract_table", {"table_id": table_id, "market": market, "include_rows": True})
        if result.get("error"):
            return _interface_error(result["error"], table_id, market)
        rows = result.get("rows", [])
        return rows if isinstance(rows, list) else _rows_from_result(result)
    try:
        table = _gateway_module().read_contract_table(
            table_id,
            market=market,
            project_root=MARKETGRAPH_ROOT,
            include_rows=True,
        )
    except Exception as exc:
        return _interface_error(str(exc), table_id, market)

    if not table.get("exists"):
        return _interface_error(
            f"MarketGraph table {table_id!r} is missing.",
            table_id,
            market,
            missing_tables=[table_id],
        )

    missing_fields = table.get("missing_required_fields") or []
    if missing_fields:
        return _interface_error(
            f"MarketGraph table {table_id!r} is missing required fields: {missing_fields!r}.",
            table_id,
            market,
            field_mismatches=[table_id],
        )

    rows = table.get("rows", [])
    return rows if isinstance(rows, list) else []


def read_marketgraph_tables(
    table_ids: list[str],
    *,
    market: str = DEFAULT_MARKET,
) -> dict[str, list[dict[str, str]] | dict[str, Any]]:
    """Read multiple MarketGraph tables by contract id.

    Values are either the row list (success) or the same error dict returned
    by ``read_marketgraph_table`` (failure). Use ``_rows_from_result`` to
    normalize a value to a row list when errors should degrade locally.
    """
    return {table_id: read_marketgraph_table(table_id, market=market) for table_id in table_ids}


def marketgraph_table_available(table_id: str, *, market: str = DEFAULT_MARKET) -> bool:
    try:
        table = _gateway_module().read_contract_table(
            table_id,
            market=market,
            project_root=MARKETGRAPH_ROOT,
            include_rows=False,
        )
    except Exception:
        return False
    return bool(table.get("exists")) and not bool(table.get("missing_required_fields"))


def marketgraph_interface_available(required_table_ids: list[str] | None = None, *, market: str = DEFAULT_MARKET) -> bool:
    snapshot = marketgraph_interface_snapshot(market=market, include_rows=False)
    if snapshot.get("contract_status") != "active":
        return False
    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        return False
    required = required_table_ids or ["market_knowledge_packages", "market_knowledge_edges"]
    for table_id in required:
        table = tables.get(table_id)
        if not isinstance(table, dict):
            return False
        if not table.get("exists") or table.get("missing_required_fields"):
            return False
    return True
