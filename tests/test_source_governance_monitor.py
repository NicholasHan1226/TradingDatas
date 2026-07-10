from __future__ import annotations

from tools import source_governance_monitor


def _agent_config() -> dict:
    return {
        "contract_version": "1.1.34",
        "primary_endpoints": [{"path": path} for path in sorted(source_governance_monitor.REQUIRED_ENDPOINTS)],
        "market_frequency_labels": {
            "Ashare_intraday": "5min trading-session intraday",
            "Futures_intraday": "5min configured day/night sessions",
            "Crypto": "30min ticker/intraday and 6-hour daily-bar support refresh",
            "PredictionMarkets": "30min markets/prices",
            "Events": "30min full event lane plus 15min news/major_news pilot refresh",
            "Low_frequency_bars": "weekly wrapper for weekly/monthly refresh",
        },
        "tushare_status": {
            "allowlisted_api_names": 115,
            "configured_in_production_tiers": 114,
            "scheduled_or_independent_or_event_lane": 115,
            "planned_activation_backlog": 0,
        },
        "data_source_onboarding": {
            "api_module_catalog": "config/api_module_catalog.yaml",
            "source_expansion_priority_plan": "config/source_expansion_priority.yaml",
        },
    }


def _api_module_catalog() -> dict:
    return {
        "status": "active_governance",
        "api_extension_policy": {
            "default": "reuse_existing_endpoint",
        },
        "canonical_modules": [
            {
                "module": "event_news_announcements_reports",
                "canonical_tables": ["market_events"],
                "default_http_surface": ["/events", "/sentiment", "/tushare"],
            },
            {
                "module": "macro_rates_fx",
                "canonical_tables": ["market_factors"],
                "default_http_surface": ["/macro", "/tushare"],
            },
        ],
    }


def _source_expansion_plan() -> dict:
    return {
        "status": "planned_only",
        "priority_batches": [
            {
                "batch": "B1_event_risk_official_sources",
                "candidates": [
                    {
                        "source_id": "official_exchange_announcements_cn",
                        "module": "event_news_announcements_reports",
                        "activation_mode": "planned",
                        "production_ready": False,
                        "target_tables": ["market_events"],
                        "http_surface": ["/events", "/sentiment"],
                        "write_path": "collectors/events/official_exchange_announcements.py",
                    }
                ],
            },
            {
                "batch": "B2_macro_official_sources",
                "candidates": [
                    {
                        "source_id": "fred_macro_rates",
                        "module": "macro_rates_fx",
                        "activation_mode": "planned",
                        "production_ready": False,
                        "target_tables": ["market_factors"],
                        "http_surface": ["/macro"],
                        "write_path": "collectors/macro/fred_macro_rates.py",
                    }
                ],
            },
        ],
    }


def _crontab_text() -> str:
    return "\n".join(
        [
            "*/5 9-15 * * 1-5 /opt/investment/SharedSignals/cron/collectors.sh --tier P0_trading_5min",
            "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
            "1,31 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
            "*/30 8-23 * * 1-6 /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
            "15,45 8-23 * * 1-6 SHAREDSIGNALS_EVENT_APIS=news,major_news /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
            "50 8 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase preopen",
            "35 9 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase morning_first_sample",
            "5 13 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase afternoon_resume",
            "5 15 * * 1-5 /opt/investment/SharedSignals/cron/opening_gate.sh --phase close_check",
            "40 7 * * 0 /opt/investment/SharedSignals/cron/tushare_low_frequency_collect.sh",
            "7-59/15 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
            "5 8 * * * /opt/investment/SharedSignals/cron/source_governance_monitor.sh",
            "10 8 * * * /opt/investment/SharedSignals/cron/green_gate_report.sh",
        ]
    )


def test_source_governance_monitor_returns_green_when_sources_are_complete() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={
            "status": "ok",
            "summary": {"critical": 0, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
    )

    assert report["status"] == "green"
    assert report["summary"]["tushare_planned_backlog"] == 0
    assert report["summary"]["endpoint_count"] == 23
    assert report["recommendation"] == "no action required"
    assert all(check["status"] == "green" for check in report["checks"])


def test_source_governance_monitor_returns_red_for_bad_module_mapping() -> None:
    plan = _source_expansion_plan()
    plan["priority_batches"][0]["candidates"][0]["target_tables"] = ["market_bars_intraday"]
    plan["priority_batches"][1]["candidates"][0]["activation_mode"] = "scheduled"

    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=plan,
        health_sla_report={
            "status": "ok",
            "summary": {"critical": 0, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
    )

    assert report["status"] == "red"
    red_checks = {check["name"]: check for check in report["checks"] if check["status"] == "red"}
    assert "api_module_catalog" in red_checks
    assert red_checks["api_module_catalog"]["evidence"]["table_offenders"]
    assert red_checks["api_module_catalog"]["evidence"]["activated_offenders"] == ["fred_macro_rates"]


def test_source_governance_monitor_returns_red_for_backlog_or_duplicate_cron() -> None:
    agent_config = _agent_config()
    agent_config["tushare_status"]["planned_activation_backlog"] = 1
    crontab_text = _crontab_text() + "\n" + "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh"

    report = source_governance_monitor.evaluate_source_governance(
        agent_config=agent_config,
        crontab_text=crontab_text,
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={
            "status": "critical",
            "summary": {"critical": 1, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
    )

    assert report["status"] == "red"
    red_checks = {check["name"] for check in report["checks"] if check["status"] == "red"}
    assert "tushare_planned_backlog" in red_checks
    assert "cron_required_lines" in red_checks
    assert "health_sla_summary" in red_checks


def test_source_governance_operator_summary_uses_chinese_status_frame() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={
            "status": "ok",
            "summary": {"critical": 0, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        generated_at="2026-07-09T00:05:00+00:00",
    )

    summary = source_governance_monitor.render_operator_summary(report)

    assert "结论：green" in summary
    assert "当前状态：外部 API 23 个端点" in summary
    assert "依据：green 检查 7 项，yellow 0 项，red 0 项" in summary
    assert "风险：无直接阻断" in summary
    assert "下一步：保持当前采集频率" in summary


def test_source_governance_reports_runtime_control_failures() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        opening_gate_report={"status": "red", "gate": "closed", "phase": "morning_first_sample"},
        duckdb_sync_report={"status": "error", "failed_tables": ["market_events"]},
    )

    assert report["status"] == "red"
    red_checks = {check["name"] for check in report["checks"] if check["status"] == "red"}
    assert {"opening_gate", "duckdb_sync"} <= red_checks
