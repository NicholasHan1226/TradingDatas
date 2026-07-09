from __future__ import annotations

from tools import source_governance_monitor


def _agent_config() -> dict:
    return {
        "contract_version": "1.1.32",
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
    }


def _crontab_text() -> str:
    return "\n".join(
        [
            "*/5 9-15 * * 1-5 /opt/investment/SharedSignals/cron/collectors.sh --tier P0_trading_5min",
            "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh",
            "1,31 * * * * /opt/investment/SharedSignals/cron/pm_collect.sh",
            "*/30 8-23 * * 1-6 /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
            "15,45 8-23 * * 1-6 SHAREDSIGNALS_EVENT_APIS=news,major_news /opt/investment/SharedSignals/cron/tushare_events_collect.sh",
            "40 7 * * 0 /opt/investment/SharedSignals/cron/tushare_low_frequency_collect.sh",
            "7-59/15 * * * * /opt/investment/SharedSignals/cron/health_sla.sh",
            "5 8 * * * /opt/investment/SharedSignals/cron/source_governance_monitor.sh",
        ]
    )


def test_source_governance_monitor_returns_green_when_sources_are_complete() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        health_sla_report={
            "status": "ok",
            "summary": {"critical": 0, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
    )

    assert report["status"] == "green"
    assert report["summary"]["tushare_planned_backlog"] == 0
    assert report["summary"]["endpoint_count"] == 22
    assert report["recommendation"] == "no action required"
    assert all(check["status"] == "green" for check in report["checks"])


def test_source_governance_monitor_returns_red_for_backlog_or_duplicate_cron() -> None:
    agent_config = _agent_config()
    agent_config["tushare_status"]["planned_activation_backlog"] = 1
    crontab_text = _crontab_text() + "\n" + "2,32 * * * * /opt/investment/SharedSignals/cron/crypto_collect.sh"

    report = source_governance_monitor.evaluate_source_governance(
        agent_config=agent_config,
        crontab_text=crontab_text,
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
        health_sla_report={
            "status": "ok",
            "summary": {"critical": 0, "warning": 0, "notice": 0, "missing_or_empty": 0},
        },
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        generated_at="2026-07-09T00:05:00+00:00",
    )

    summary = source_governance_monitor.render_operator_summary(report)

    assert "结论：green" in summary
    assert "当前状态：外部 API 22 个端点" in summary
    assert "依据：green 检查 6 项，yellow 0 项，red 0 项" in summary
    assert "风险：无直接阻断" in summary
    assert "下一步：保持当前采集频率" in summary
