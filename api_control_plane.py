"""Control-plane response helpers for SharedSignals HTTP API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def json_file_payload(path: Path) -> tuple[Any, dict[str, Any], str | None]:
    stat = path.stat()
    payload = json.loads(path.read_text())
    age_hours = max((datetime.now(timezone.utc).timestamp() - stat.st_mtime) / 3600.0, 0.0)
    metadata = {
        "freshness": {
            "stale": False,
            "age_hours": round(age_hours, 4),
            "score": 1.0,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        },
        "quality": {"score": 1.0, "completeness": 1.0},
        "degraded": False,
    }
    return payload, metadata, path.name


def capability_fallback_payload(
    *,
    capability_path: Path,
    scope_map: dict[str, set[str]],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Return a deterministic capability summary when the generated registry is absent."""

    unique_endpoints = sorted(
        {
            endpoint
            for endpoints_for_scope in scope_map.values()
            for endpoint in endpoints_for_scope
            if endpoint != "*"
        }
    )
    payload = {
        "status": "degraded",
        "reason": f"missing generated registry: {capability_path}",
        "next_action": "run tools/capability_scan.py; cron/capability_scan.sh keeps this file refreshed in production",
        "summary": {
            "total": len(unique_endpoints),
            "ok": 0,
            "degraded": len(unique_endpoints),
            "down": 0,
        },
        "endpoints": [
            {
                "name": endpoint.strip("/") or "root",
                "path": endpoint,
                "status": "degraded",
                "category": _endpoint_category(endpoint, scope_map),
                "description": "Generated registry missing; endpoint is listed from auth scope map.",
            }
            for endpoint in unique_endpoints
        ],
    }
    metadata = {
        "freshness": None,
        "quality": {"score": 0.5, "completeness": 0.5},
        "degraded": True,
        "degraded_reasons": [payload["reason"]],
        "lineage": {"source": "auth.SCOPE_ENDPOINTS", "registry_path": str(capability_path)},
    }
    return payload, metadata, "capability_fallback"


def capabilities_payload(
    *,
    capability_path: Path,
    scope_map: dict[str, set[str]],
) -> tuple[Any, dict[str, Any], str | None]:
    if capability_path.exists():
        return json_file_payload(capability_path)
    return capability_fallback_payload(capability_path=capability_path, scope_map=scope_map)


def agent_config_payload(agent_config_path: Path) -> tuple[Any, dict[str, Any], str | None]:
    payload, metadata, source = json_file_payload(agent_config_path)
    metadata["lineage"] = {
        "source": "config/external_agent_api_config.json",
        "contract_version": payload.get("contract_version") if isinstance(payload, dict) else None,
    }
    return payload, metadata, source


def source_status_payload() -> tuple[dict[str, Any], dict[str, Any], str]:
    from tools.source_governance_monitor import build_source_governance_report

    payload = build_source_governance_report()
    metadata = {
        "freshness": None,
        "quality": {"score": 1.0 if payload.get("status") == "green" else 0.75},
        "degraded": payload.get("status") != "green",
        "degraded_reasons": [
            check["name"]
            for check in payload.get("checks", [])
            if check.get("status") in {"yellow", "red"}
        ],
        "lineage": {"source": "tools/source_governance_monitor.py"},
    }
    return payload, metadata, "source_governance_monitor"


def opening_gate_payload() -> tuple[dict[str, Any], dict[str, Any], str]:
    path = Path(__import__("os").environ.get("WATCHDOG_INPUT_DIR", "logs/watchdog_inputs")) / "opening_gate.json"
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    if not path.exists():
        payload = {
            "status": "yellow",
            "gate": "closed",
            "phase": "unknown",
            "action_required": "opening_gate artifact is not available; run cron/opening_gate.sh",
        }
        return payload, {"degraded": True, "degraded_reasons": ["opening_gate artifact missing"]}, "opening_gate_missing"
    payload, metadata, source = json_file_payload(path)
    metadata["lineage"] = {"source": "tools/opening_gate.py", "artifact": str(path)}
    metadata["degraded"] = payload.get("status") != "green"
    metadata["degraded_reasons"] = [] if payload.get("status") == "green" else [payload.get("action_required", "opening gate closed")]
    return payload, metadata, source


def _endpoint_category(endpoint: str, scope_map: dict[str, set[str]]) -> str:
    for scope, endpoints in scope_map.items():
        if scope == "read":
            continue
        if endpoint in endpoints:
            return scope
    return "unknown"
