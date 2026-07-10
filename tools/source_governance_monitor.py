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

import yaml

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[1]))
AGENT_CONFIG_PATH = ROOT / "config" / "external_agent_api_config.json"
API_MODULE_CATALOG_PATH = ROOT / "config" / "api_module_catalog.yaml"
SOURCE_EXPANSION_PRIORITY_PATH = ROOT / "config" / "source_expansion_priority.yaml"
CAPABILITY_REGISTRY_PATH = ROOT / "tools" / "capability_registry.json"
HEALTH_SLA_PATH = ROOT / "logs" / "watchdog_inputs" / "health_sla.json"
OPENING_GATE_PATH = ROOT / "logs" / "watchdog_inputs" / "opening_gate.json"
DUCKDB_SYNC_PATH = ROOT / "logs" / "watchdog_inputs" / "duckdb_sync.json"
INTERFACE_RUNTIME_PATH = ROOT / "logs" / "watchdog_inputs" / "interface_runtime.json"
EXTERNAL_API_PROBE_PATH = ROOT / "logs" / "watchdog_inputs" / "external_api_probe.json"
CRONTAB_PATH = ROOT / "crontab.txt"
DEFAULT_OUTPUT_PATH = ROOT / "logs" / "watchdog_inputs" / "source_governance.json"

REQUIRED_ENDPOINTS = {
    "/health",
    "/capabilities",
    "/agent_config",
    "/source_status",
    "/opening_gate",
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
    "green_gate_daily": "10 8 * * * /opt/investment/SharedSignals/cron/green_gate_report.sh",
    "external_api_probe_5min": "3-58/5 * * * * /opt/investment/SharedSignals/cron/external_api_probe.sh",
    "opening_gate_preopen": "50 8 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase preopen",
    "opening_gate_morning": "35 9 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase morning_first_sample",
    "opening_gate_afternoon": "5 13 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase afternoon_resume",
    "opening_gate_close": "5 15 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase close_check",
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


def _yaml_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return default
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
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


def _source_candidates(source_expansion_plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in source_expansion_plan.get("priority_batches", []):
        if not isinstance(batch, dict):
            continue
        for item in batch.get("candidates", []):
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            candidate["batch"] = batch.get("batch")
            rows.append(candidate)
    return rows


def _evaluate_api_module_catalog(
    *,
    agent_config: dict[str, Any],
    api_module_catalog: dict[str, Any] | None,
    source_expansion_plan: dict[str, Any] | None,
    crontab_text: str,
) -> dict[str, Any]:
    onboarding = agent_config.get("data_source_onboarding") if isinstance(agent_config.get("data_source_onboarding"), dict) else {}
    missing_config_refs = [
        name
        for name in ("api_module_catalog", "source_expansion_priority_plan")
        if not onboarding.get(name)
    ]
    if not isinstance(api_module_catalog, dict) or not api_module_catalog:
        return _check(
            "api_module_catalog",
            "red",
            "API/module catalog is missing or unreadable",
            missing_config_refs=missing_config_refs,
        )
    if not isinstance(source_expansion_plan, dict) or not source_expansion_plan:
        return _check(
            "api_module_catalog",
            "red",
            "source expansion plan is missing or unreadable",
            missing_config_refs=missing_config_refs,
        )

    module_rows = [
        row
        for row in api_module_catalog.get("canonical_modules", [])
        if isinstance(row, dict) and row.get("module")
    ]
    module_names = [str(row["module"]) for row in module_rows]
    modules = {str(row["module"]): row for row in module_rows}
    candidates = _source_candidates(source_expansion_plan)
    duplicate_modules = sorted(name for name in set(module_names) if module_names.count(name) > 1)
    missing_modules: list[str] = []
    table_offenders: list[str] = []
    surface_offenders: list[str] = []
    activated_offenders: list[str] = []
    cron_offenders: list[str] = []

    for item in candidates:
        source_id = str(item.get("source_id") or item.get("batch") or "unknown")
        if item.get("activation_mode") != "planned" or item.get("production_ready") is not False:
            activated_offenders.append(source_id)

        write_path = str(item.get("write_path") or "")
        if write_path and write_path in crontab_text:
            cron_offenders.append(source_id)

        module = modules.get(str(item.get("module")))
        if module is None:
            missing_modules.append(f"{source_id}:{item.get('module')}")
            continue

        allowed_tables = set(module.get("canonical_tables") or [])
        target_tables = set(item.get("target_tables") or [])
        if not target_tables <= allowed_tables:
            table_offenders.append(f"{source_id}:{sorted(target_tables - allowed_tables)}")

        allowed_surfaces = set(module.get("default_http_surface") or [])
        surfaces = set(item.get("http_surface") or [])
        if not surfaces <= allowed_surfaces:
            surface_offenders.append(f"{source_id}:{sorted(surfaces - allowed_surfaces)}")

    endpoint_reuse = (api_module_catalog.get("api_extension_policy") or {}).get("default") == "reuse_existing_endpoint"
    catalog_active = api_module_catalog.get("status") == "active_governance"
    plan_planned_only = source_expansion_plan.get("status") == "planned_only"
    offenders = (
        missing_config_refs
        + duplicate_modules
        + missing_modules
        + table_offenders
        + surface_offenders
        + activated_offenders
        + cron_offenders
    )
    status = "green" if catalog_active and endpoint_reuse and plan_planned_only and not offenders else "red"
    return _check(
        "api_module_catalog",
        status,
        "source expansion candidates map to planned modules and reusable APIs" if status == "green" else "source expansion module/API mapping needs review",
        module_count=len(modules),
        candidate_count=len(candidates),
        catalog_active=catalog_active,
        endpoint_reuse_default=endpoint_reuse,
        plan_planned_only=plan_planned_only,
        missing_config_refs=missing_config_refs,
        duplicate_modules=duplicate_modules,
        missing_modules=missing_modules,
        table_offenders=table_offenders,
        surface_offenders=surface_offenders,
        activated_offenders=activated_offenders,
        cron_offenders=cron_offenders,
    )


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


def _evaluate_runtime_report(name: str, report: dict[str, Any] | None, healthy_status: str) -> dict[str, Any]:
    if not isinstance(report, dict) or not report:
        return _check(name, "red", f"{name} report is missing")
    raw_status = str(report.get("status") or "missing")
    status = "green" if raw_status == healthy_status else "red"
    return _check(
        name,
        status,
        f"{name} is healthy" if status == "green" else f"{name} requires operator attention",
        runtime_status=raw_status,
        phase=report.get("phase"),
        failed_tables=report.get("failed_tables") or [],
    )


def _evaluate_interface_runtime(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict) or not report:
        return _check("interface_runtime_ledger", "yellow", "interface runtime ledger has not been initialized")
    raw_status = str(report.get("status") or "red")
    status = raw_status if raw_status in STATUS_ORDER else "red"
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return _check(
        "interface_runtime_ledger",
        status,
        "all configured interfaces have runtime evidence"
        if status == "green"
        else "configured interfaces still have failed, degraded, or unobserved runtime evidence",
        failed=int(summary.get("failed") or 0),
        degraded=int(summary.get("degraded") or 0),
        unobserved=int(summary.get("unobserved") or 0),
        observed=int(summary.get("observed") or 0),
        expected=int(summary.get("expected") or 0),
    )


def _evaluate_external_api_probe(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict) or not report:
        return _check("external_api_probe", "yellow", "external API probe has not been initialized")
    status = "green" if report.get("status") == "green" else "red"
    return _check(
        "external_api_probe",
        status,
        "public route reached the SharedSignals API boundary"
        if status == "green"
        else "public route did not reach the SharedSignals API boundary",
        http_status=report.get("http_status"),
        checked_at=report.get("checked_at"),
        latency_ms=report.get("latency_ms"),
    )


def evaluate_source_governance(
    *,
    agent_config: dict[str, Any],
    crontab_text: str,
    api_module_catalog: dict[str, Any] | None = None,
    source_expansion_plan: dict[str, Any] | None = None,
    health_sla_report: dict[str, Any] | None = None,
    capability_registry: dict[str, Any] | None = None,
    opening_gate_report: dict[str, Any] | None = None,
    duckdb_sync_report: dict[str, Any] | None = None,
    interface_runtime_report: dict[str, Any] | None = None,
    external_api_probe_report: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    checks = []
    checks.extend(_evaluate_agent_config(agent_config))
    checks.append(
        _evaluate_api_module_catalog(
            agent_config=agent_config,
            api_module_catalog=api_module_catalog,
            source_expansion_plan=source_expansion_plan,
            crontab_text=crontab_text,
        )
    )
    checks.append(_evaluate_cron(crontab_text))
    checks.append(_evaluate_health_sla(health_sla_report))
    checks.append(_evaluate_capability_registry(capability_registry))
    if opening_gate_report is not None:
        checks.append(_evaluate_runtime_report("opening_gate", opening_gate_report, "green"))
    if duckdb_sync_report is not None:
        checks.append(_evaluate_runtime_report("duckdb_sync", duckdb_sync_report, "ok"))
    if interface_runtime_report is not None:
        checks.append(_evaluate_interface_runtime(interface_runtime_report))
    if external_api_probe_report is not None:
        checks.append(_evaluate_external_api_probe(external_api_probe_report))
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
            "api_module_catalog": str(API_MODULE_CATALOG_PATH),
            "source_expansion_priority": str(SOURCE_EXPANSION_PRIORITY_PATH),
            "crontab": str(CRONTAB_PATH),
            "health_sla": str(HEALTH_SLA_PATH),
            "capability_registry": str(CAPABILITY_REGISTRY_PATH),
            "opening_gate": str(OPENING_GATE_PATH),
            "duckdb_sync": str(DUCKDB_SYNC_PATH),
            "interface_runtime": str(INTERFACE_RUNTIME_PATH),
            "external_api_probe": str(EXTERNAL_API_PROBE_PATH),
        },
    }


def render_operator_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    status = str(report.get("status") or "red")
    generated_at = str(report.get("generated_at") or "")
    endpoint_count = int(summary.get("endpoint_count") or 0)
    allowlisted = int(summary.get("tushare_allowlisted") or 0)
    active = int(summary.get("tushare_active") or 0)
    backlog = int(summary.get("tushare_planned_backlog") or 0)
    green = int(summary.get("green_checks") or 0)
    yellow = int(summary.get("yellow_checks") or 0)
    red = int(summary.get("red_checks") or 0)

    if status == "green":
        risk = "无直接阻断"
        next_step = "保持当前采集频率，等待下一个交易日自动观察"
    elif status == "yellow":
        risk = "存在降级项，下游可继续读取但不应扩频或扩消费方"
        next_step = "优先处理 yellow 检查项，再扩展数据源或频率"
    else:
        risk = "存在红灯项，交易前置检查应按 fail-closed 处理"
        next_step = "先修复 red 检查项，再恢复下游交易判断"

    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    non_green = [
        f"{check.get('name')}: {check.get('status')} - {check.get('message')}"
        for check in checks
        if isinstance(check, dict) and check.get("status") != "green"
    ]
    evidence = f"green 检查 {green} 项，yellow {yellow} 项，red {red} 项"
    if non_green:
        evidence += "；需关注：" + "；".join(non_green[:5])

    lines = [
        f"结论：{status}",
        f"当前状态：外部 API {endpoint_count} 个端点；Tushare {active}/{allowlisted} 个接口已纳入活跃模式；待激活 {backlog} 个；生成时间 {generated_at}",
        f"依据：{evidence}",
        f"风险：{risk}",
        f"下一步：{next_step}",
    ]
    return "\n".join(lines) + "\n"


def build_source_governance_report() -> dict[str, Any]:
    agent_config = _json_file(AGENT_CONFIG_PATH, {})
    api_module_catalog = _yaml_file(API_MODULE_CATALOG_PATH, {})
    source_expansion_plan = _yaml_file(SOURCE_EXPANSION_PRIORITY_PATH, {})
    capability_registry = _json_file(CAPABILITY_REGISTRY_PATH, {})
    health_sla_report = _json_file(HEALTH_SLA_PATH, {})
    opening_gate_report = _json_file(OPENING_GATE_PATH, {})
    duckdb_sync_report = _json_file(DUCKDB_SYNC_PATH, {})
    interface_runtime_report = _json_file(INTERFACE_RUNTIME_PATH, {})
    external_api_probe_report = _json_file(EXTERNAL_API_PROBE_PATH, {})
    crontab_text = CRONTAB_PATH.read_text(encoding="utf-8", errors="replace") if CRONTAB_PATH.exists() else ""
    return evaluate_source_governance(
        agent_config=agent_config,
        crontab_text=crontab_text,
        api_module_catalog=api_module_catalog,
        source_expansion_plan=source_expansion_plan,
        health_sla_report=health_sla_report,
        capability_registry=capability_registry,
        opening_gate_report=opening_gate_report,
        duckdb_sync_report=duckdb_sync_report,
        interface_runtime_report=interface_runtime_report,
        external_api_probe_report=external_api_probe_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SharedSignals source governance status")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    parser.add_argument("--summary-output", type=Path, default=None, help="Optional operator summary text output path")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    report = build_source_governance_report()
    output_path = args.output
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(render_operator_summary(report), encoding="utf-8")
    if args.json or output_path is None:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"green", "yellow"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
