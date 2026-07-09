#!/usr/bin/env python3
"""SharedSignals source governance monitor.

This monitor answers the operator question: are data sources configured,
scheduled, and exposed consistently enough for consumers to rely on the API?
It reads existing control-plane artifacts only; it does not call providers or
scan the marketdata database.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
AGENT_CONFIG_PATH = ROOT / "config" / "external_agent_api_config.json"
CAPABILITY_REGISTRY_PATH = ROOT / "tools" / "capability_registry.json"
HEALTH_SLA_PATH = ROOT / "logs" / "watchdog_inputs" / "health_sla.json"
CRONTAB_PATH = ROOT / "crontab.txt"
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "watchdog_inputs" / "source_governance.json"

REQUIRED_ENDPOINTS = {
    "/health",
    "/capabilities",
    "/agent_config",
    "/source_status",
    "/cache/status",
    "/cache/invalidate",
    "/market_data",
    "/realtime_5min",
    "/is_trading_day",
    "/events",
    "/sentiment",
    "/fundamentals",
    "/reference",
    "/industry",
    "/macro",
    "/capital_flow",
    "/crypto",
    "/pm_markets",
    "/pm_prices",
    "/associations",
    "/impacts",
    "/tushare",
}

REQUIRED_FREQUENCY_LABELS = {
    "Ashare_intraday",
    "Futures_intraday",
    "Crypto",
    "PredictionMarkets",
    "Events",
    "Low_frequency_bars",
}

REQUIRED_CRON_LINES = {
    "ashare_p0_5min": "*/5 9-15 * * 1-5 /opt/investment/SharedSignals/cron/collectors.sh --tier P0_trading_5min",
    "crypto_30min": "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
    "pm_30min": "1,31 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
    "event_full_30min": "*/30 8-23 * * 1-6 /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
    "event_news_major_15min_pilot": "15,45 8-23 * * 1-6 SHAREDSIGNALS_EVENT_APIS=news,major_news /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
    "low_frequency_weekly": "40 7 * * 0 /opt/investment/SharedSignals/cron/tushare_low_frequency_collect.sh",
    "health_sla_15min": "7-59/15 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
    "source_governance_daily": "5 8 * * * /opt/investment/SharedSignals/cron/source_governance_monitor.sh",
}

STATUS_ORDER = {"green": 0, "yellow": 1, "red": 2}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _check(name: str, status: str, message: str, **evidence: Any) -> dict[str, Any]:
    payload = {"name": name, "status": status, "message": message}
    if evidence:
        payload["evidence"] = evidence
    return payload


def _overall(checks: list[dict[str, Any]]) -> str:
    worst = "green"
    for check in checks:
        status = str(check.get("status") or "red")
        if STATUS_ORDER.get(status, 2) > STATUS_ORDER[worst]:
            worst = status
    return worst


def _recommendation(status: str) -> str:
    if status == "green":
        return "no action required"
    if status == "yellow":
        return "review warnings before expanding cadence or adding consumers"
    return "operator intervention required before relying on downstream trading decisions"


def _endpoint_paths(agent_config: dict[str, Any]) -> set[str]:
    return {
        str(item.get("path"))
        for item in agent_config.get("primary_endpoints", [])
        if isinstance(item, dict) and item.get("path")
    }


def _evaluate_agent_config(agent_config: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    endpoints = _endpoint_paths(agent_config)
    missing_endpoints = sorted(REQUIRED_ENDPOINTS - endpoints)
    endpoint_status = "green" if not missing_endpoints else "red"
    checks.append(
        _check(
            "api_endpoint_surface",
            endpoint_status,
            "all required external-agent endpoints are listed" if endpoint_status == "green" else "required endpoints are missing",
            endpoint_count=len(endpoints),
            missing=missing_endpoints,
        )
    )

    labels = set((agent_config.get("market_frequency_labels") or {}).keys())
    missing_labels = sorted(REQUIRED_FREQUENCY_LABELS - labels)
    checks.append(
        _check(
            "market_frequency_labels",
            "green" if not missing_labels else "red",
            "market cadence labels are present" if not missing_labels else "market cadence labels are missing",
            missing=missing_labels,
        )
    )

    tushare = agent_config.get("tushare_status") or {}
    allowlisted = int(tushare.get("allowlisted_api_names") or 0)
    active = int(tushare.get("scheduled_or_independent_or_event_lane") or 0)
    backlog = int(tushare.get("planned_activation_backlog") or 0)
    complete = allowlisted > 0 and active == allowlisted and backlog == 0
    checks.append(
        _check(
            "tushare_planned_backlog",
            "green" if complete else "red",
            "all allowlisted Tushare interfaces are assigned to active modes" if complete else "Tushare capability plan is not fully active",
            allowlisted=allowlisted,
            active=active,
            planned_backlog=backlog,
        )
    )
    return checks


def _evaluate_cron(crontab_text: str) -> dict[str, Any]:
    missing: list[str] = []
    duplicates: list[str] = []
    counts: dict[str, int] = {}
    for name, line in REQUIRED_CRON_LINES.items():
        count = crontab_text.count(line)
        counts[name] = count
        if count == 0:
            missing.append(name)
        elif count > 1:
            duplicates.append(name)
    status = "green" if not missing and not duplicates else "red"
    return _check(
        "cron_required_lines",
        status,
        "required collection and governance schedules are present once" if status == "green" else "required cron lines are missing or duplicated",
        missing=missing,
        duplicates=duplicates,
        counts=counts,
    )


def _evaluate_health_sla(health_sla_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(health_sla_report, dict) or not health_sla_report:
        return _check("health_sla_summary", "red", "health_sla report is missing")
    summary = health_sla_report.get("summary") or {}
    critical = int(summary.get("critical") or 0)
    warning = int(summary.get("warning") or 0)
    notice = int(summary.get("notice") or 0)
    missing = int(summary.get("missing_or_empty") or 0)
    if critical > 0 or missing > 0 or str(health_sla_report.get("status")) in {"critical", "missing", "invalid"}:
        status = "red"
    elif warning > 0 or notice > 0 or str(health_sla_report.get("status")) not in {"ok", "green"}:
        status = "yellow"
    else:
        status = "green"
    return _check(
        "health_sla_summary",
        status,
        "freshness SLA is clean" if status == "green" else "freshness SLA needs review",
        summary=summary,
        sla_status=health_sla_report.get("status"),
    )


def _evaluate_capability_registry(capability_registry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(capability_registry, dict) or not capability_registry:
        return _check("capability_registry", "yellow", "capability registry is missing; /capabilities will use fallback")
    summary = capability_registry.get("summary") or {}
    down = int(summary.get("down") or 0)
    degraded = int(summary.get("degraded") or 0)
    if down > 0:
        status = "red"
    elif degraded > 0:
        status = "yellow"
    else:
        status = "green"
    return _check(
        "capability_registry",
        status,
        "capability registry reports no degraded or down endpoints" if status == "green" else "capability registry has degraded endpoints",
        summary=summary,
    )


def evaluate_source_governance(
    *,
    agent_config: dict[str, Any],
    crontab_text: str,
    health_sla_report: dict[str, Any] | None = None,
    capability_registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    checks = []
    checks.extend(_evaluate_agent_config(agent_config))
    checks.append(_evaluate_cron(crontab_text))
    checks.append(_evaluate_health_sla(health_sla_report))
    checks.append(_evaluate_capability_registry(capability_registry))
    status = _overall(checks)
    tushare = agent_config.get("tushare_status") or {}
    endpoints = _endpoint_paths(agent_config)
    return {
        "status": status,
        "recommendation": _recommendation(status),
        "generated_at": generated_at or utc_now_iso(),
        "summary": {
            "endpoint_count": len(endpoints),
            "tushare_allowlisted": int(tushare.get("allowlisted_api_names") or 0),
            "tushare_active": int(tushare.get("scheduled_or_independent_or_event_lane") or 0),
            "tushare_planned_backlog": int(tushare.get("planned_activation_backlog") or 0),
            "green_checks": sum(1 for check in checks if check["status"] == "green"),
            "yellow_checks": sum(1 for check in checks if check["status"] == "yellow"),
            "red_checks": sum(1 for check in checks if check["status"] == "red"),
        },
        "checks": checks,
        "source_files": {
            "agent_config": str(AGENT_CONFIG_PATH),
            "crontab": str(CRONTAB_PATH),
            "health_sla": str(HEALTH_SLA_PATH),
            "capability_registry": str(CAPABILITY_REGISTRY_PATH),
        },
    }


def build_source_governance_report() -> dict[str, Any]:
    agent_config = _json_file(AGENT_CONFIG_PATH, {})
    capability_registry = _json_file(CAPABILITY_REGISTRY_PATH, {})
    health_sla_report = _json_file(HEALTH_SLA_PATH, {})
    crontab_text = CRONTAB_PATH.read_text(encoding="utf-8", errors="replace") if CRONTAB_PATH.exists() else ""
    return evaluate_source_governance(
        agent_config=agent_config,
        crontab_text=crontab_text,
        health_sla_report=health_sla_report,
        capability_registry=capability_registry,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SharedSignals source governance status")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    report = build_source_governance_report()
    output_path = args.output
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or output_path is None:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"green", "yellow"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
