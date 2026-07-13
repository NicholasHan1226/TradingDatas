"""Persistent per-interface runtime evidence for configured Tushare collectors."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "watchdog_inputs" / "interface_runtime.json"
CAPABILITY_PLAN_PATH = ROOT / "config" / "tushare_capability_plan.yaml"


def expected_tushare_api_names(path: Path = CAPABILITY_PLAN_PATH) -> set[str]:
    if not path.exists():
        return set()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    names: set[str] = set()
    for module in payload.get("modules") or []:
        if not isinstance(module, dict):
            continue
        for item in module.get("apis") or []:
            if isinstance(item, dict) and item.get("api_name"):
                names.add(str(item["api_name"]))
    return names


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _status_for(stats: dict[str, Any]) -> tuple[str, str]:
    calls = int(stats.get("calls") or 0)
    failures = int(stats.get("failure_count") or 0)
    sqlite_status = str(stats.get("sqlite_status") or "empty")
    sqlite_errors = [str(item) for item in stats.get("sqlite_errors") or [] if item]
    rows = int(stats.get("rows") or 0)

    if sqlite_status == "failed" or sqlite_errors or (calls > 0 and failures >= calls):
        return "failed", "provider_or_sqlite_failure"
    if failures > 0:
        return "degraded", "partial_provider_failure"
    if calls <= 0:
        return "degraded", "no_provider_call_completed"
    if rows == 0:
        return "empty", "provider_returned_no_rows"
    return "success", ""


def _summarize(interfaces: dict[str, Any], expected: set[str]) -> dict[str, Any]:
    observed_names = expected.intersection(interfaces)
    empty_names = {
        name
        for name in observed_names
        if str((interfaces[name] or {}).get("status") or "") == "empty"
        or (interfaces[name] or {}).get("empty_reason") == "provider_returned_no_rows"
    }
    statuses = {
        name: str((interfaces.get(name) or {}).get("status") or "unobserved")
        for name in observed_names
    }
    summary = {
        "expected": len(expected),
        "observed": len(observed_names),
        "success": sum(
            1
            for name, status in statuses.items()
            if status == "success" and name not in empty_names
        ),
        "empty": len(empty_names),
        "degraded": sum(1 for status in statuses.values() if status == "degraded"),
        "failed": sum(1 for status in statuses.values() if status == "failed"),
        "unobserved": len(expected - observed_names),
    }
    if summary["failed"]:
        status = "red"
    elif summary["degraded"] or summary["empty"] or summary["unobserved"]:
        status = "yellow"
    else:
        status = "green"
    return {"status": status, "summary": summary}


def record_tushare_stats(
    stats: dict[str, Any],
    *,
    tier: str,
    started_at: str,
    finished_at: str,
    expected_api_names: Iterable[str] | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    """Merge one tier run into the durable interface runtime ledger."""
    previous = _load(output_path)
    interfaces = previous.get("interfaces") if isinstance(previous.get("interfaces"), dict) else {}
    interfaces = dict(interfaces)

    for api_name, raw in stats.items():
        if str(api_name).startswith("_") or not isinstance(raw, dict):
            continue
        status, status_reason = _status_for(raw)
        old = interfaces.get(api_name) if isinstance(interfaces.get(api_name), dict) else {}
        entry = {
            "source": f"tushare:{api_name}",
            "tier": tier,
            "status": status,
            "last_attempt": finished_at,
            "last_success": old.get("last_success"),
            "started_at": started_at,
            "rows_read": int(raw.get("rows") or 0),
            "rows_written": int(raw.get("sqlite_rows") or 0),
            "calls": int(raw.get("calls") or 0),
            "failure_count": int(raw.get("failure_count") or 0),
            "sqlite_status": str(raw.get("sqlite_status") or "empty"),
            "status_reason": status_reason,
            "empty_reason": status_reason if status == "empty" else "",
            "errors": [str(item) for item in raw.get("sqlite_errors") or [] if item],
        }
        if status == "success":
            entry["last_success"] = finished_at
        interfaces[str(api_name)] = entry

    expected = set(expected_api_names) if expected_api_names is not None else expected_tushare_api_names()
    summary = _summarize(interfaces, expected)
    report = {
        "status": summary["status"],
        "generated_at": finished_at,
        "summary": summary["summary"],
        "unobserved_api_names": sorted(expected - set(interfaces)),
        "interfaces": dict(sorted(interfaces.items())),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(output_path)
    return report
