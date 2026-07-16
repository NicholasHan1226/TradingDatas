from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from dataset_registry import DatasetRegistry, load_dataset_registry
from tools import source_governance_monitor


def _agent_config(*, include_industry: bool = False) -> dict:
    endpoints = set(source_governance_monitor.REQUIRED_ENDPOINTS)
    if include_industry:
        endpoints.update(source_governance_monitor.SW2021_REQUIRED_ENDPOINTS)
    return {
        "contract_version": "1.1.34",
        "primary_endpoints": [{"path": path} for path in sorted(endpoints)],
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


def _crontab_text(*, include_sw2021: bool = False) -> str:
    lines = [
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
            "3-58/5 * * * * /opt/investment/SharedSignals/cron/external_api_probe.sh",
    ]
    if include_sw2021:
        lines.extend(
            [
                source_governance_monitor.SQLITE_MAINTENANCE_CRON_LINE,
                source_governance_monitor.SW2021_REFERENCE_CRON_LINE,
            ]
        )
    return "\n".join(lines)


def _active_sw2021_report() -> dict:
    return {
        "owner": "SharedSignals",
        "status": "active",
        "exit_code": 0,
        "completed_at": "2026-07-11T06:30:00+00:00",
        "snapshot_id": "snap-a",
    }


def _green_maintenance_report() -> dict:
    return {
        "owner": "SharedSignals",
        "status": "green",
        "completed_at": "2026-07-11T03:20:00+00:00",
        "wal_checkpoint": {"busy": 0, "log_frames": 0, "checkpointed_frames": 0},
        "optimized": True,
        "integrity": "not_run",
    }


def _active_dataset_registry() -> DatasetRegistry:
    registry = load_dataset_registry()
    return DatasetRegistry(
        tuple(
            replace(
                dataset,
                provider_bindings=tuple(
                    replace(
                        binding,
                        entitlement_state="active",
                        activation_state="active",
                    )
                    for binding in dataset.provider_bindings
                ),
            )
            for dataset in registry.datasets
        )
    )


def _eligible_active_dataset_registry() -> DatasetRegistry:
    registry = load_dataset_registry()
    return DatasetRegistry(
        tuple(
            replace(
                dataset,
                provider_bindings=tuple(
                    binding
                    if binding.entitlement_state == "excluded"
                    else replace(
                        binding,
                        entitlement_state="active",
                        activation_state="active",
                    )
                    for binding in dataset.provider_bindings
                ),
            )
            for dataset in registry.datasets
        )
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
        dataset_registry=_active_dataset_registry(),
    )

    assert report["status"] == "green"
    assert report["summary"]["tushare_planned_backlog"] == 0
    assert report["summary"]["endpoint_count"] == 23
    assert report["recommendation"] == "no action required"
    assert all(check["status"] == "green" for check in report["checks"])


def test_excluded_tushare_bindings_do_not_make_complete_plan_red() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_eligible_active_dataset_registry(),
    )

    check = next(
        item
        for item in report["checks"]
        if item["name"] == "tushare_planned_backlog"
    )
    assert check["status"] == "green"
    assert check["evidence"]["active"] == 98
    assert check["evidence"]["excluded"] == 16
    assert check["evidence"]["planned_backlog"] == 0


def test_source_governance_uses_current_registry_not_legacy_tushare_counts() -> None:
    registry = load_dataset_registry()
    agent_config = _agent_config()
    agent_config["tushare_status"] = {
        "allowlisted_api_names": 999,
        "configured_in_production_tiers": 999,
        "scheduled_or_independent_or_event_lane": 999,
        "planned_activation_backlog": 0,
    }

    report = source_governance_monitor.evaluate_source_governance(
        agent_config=agent_config,
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=registry,
    )

    check = next(
        item for item in report["checks"]
        if item["name"] == "tushare_planned_backlog"
    )
    assert report["status"] == "red"
    assert report["summary"]["tushare_allowlisted"] == 114
    assert report["summary"]["tushare_active"] == 0
    assert report["summary"]["tushare_paused"] == 114
    assert report["summary"]["tushare_planned_backlog"] == 98
    assert check["status"] == "red"
    assert check["evidence"]["allowlisted"] == 114
    assert check["evidence"]["active"] == 0
    assert check["evidence"]["paused"] == 114
    assert check["evidence"]["planned_backlog"] == 98
    assert check["evidence"]["legacy_agent_config"]["allowlisted"] == 999


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
        dataset_registry=_active_dataset_registry(),
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
        interface_runtime_report={"status": "red", "summary": {"failed": 1, "unobserved": 2}},
    )

    assert report["status"] == "red"
    red_checks = {check["name"] for check in report["checks"] if check["status"] == "red"}
    assert {"opening_gate", "duckdb_sync", "interface_runtime_ledger"} <= red_checks


def test_source_governance_preserves_unobserved_interface_runtime_as_yellow() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_active_dataset_registry(),
        interface_runtime_report={
            "status": "yellow",
            "summary": {"failed": 0, "degraded": 0, "unobserved": 10},
        },
    )

    assert report["status"] == "yellow"
    check = next(item for item in report["checks"] if item["name"] == "interface_runtime_ledger")
    assert check["status"] == "yellow"
    assert check["evidence"]["unobserved"] == 10


def test_source_governance_preserves_empty_interface_runtime_as_yellow() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_active_dataset_registry(),
        interface_runtime_report={
            "status": "yellow",
            "summary": {"failed": 0, "degraded": 0, "empty": 11, "unobserved": 0},
        },
    )

    assert report["status"] == "yellow"
    check = next(item for item in report["checks"] if item["name"] == "interface_runtime_ledger")
    assert check["status"] == "yellow"
    assert check["evidence"]["empty"] == 11


def test_source_governance_reports_external_api_probe_failure() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        external_api_probe_report={
            "status": "red",
            "http_status": 525,
            "checked_at": "2026-07-10T08:00:00+00:00",
        },
    )

    check = next(item for item in report["checks"] if item["name"] == "external_api_probe")
    assert report["status"] == "red"
    assert check["evidence"]["http_status"] == 525


def test_sw2021_active_requires_endpoints_cron_and_recent_maintenance() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(include_industry=True),
        crontab_text=_crontab_text(include_sw2021=True),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_active_dataset_registry(),
        sw2021_reference_report=_active_sw2021_report(),
        sqlite_maintenance_report=_green_maintenance_report(),
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "green"
    assert check["status"] == "green"
    assert check["evidence"]["state"] == "active"
    assert check["evidence"]["missing_endpoints"] == []
    assert check["evidence"]["missing_cron"] == []
    assert check["evidence"]["maintenance_status"] == "green"


def test_sw2021_active_fails_closed_when_activation_evidence_is_incomplete() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        sw2021_reference_report=_active_sw2021_report(),
        sqlite_maintenance_report={},
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "red"
    assert check["evidence"]["missing_endpoints"] == sorted(
        source_governance_monitor.SW2021_REQUIRED_ENDPOINTS
    )
    assert set(check["evidence"]["missing_cron"]) == {
        "sqlite_maintenance",
        "sw2021_reference",
    }
    assert check["evidence"]["maintenance_status"] == "missing"


def test_sw2021_active_rejects_incomplete_green_maintenance_evidence() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(include_industry=True),
        crontab_text=_crontab_text(include_sw2021=True),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        sw2021_reference_report=_active_sw2021_report(),
        sqlite_maintenance_report={
            "owner": "SharedSignals",
            "status": "green",
            "optimized": True,
            "integrity": "not_run",
            "completed_at": "2026-07-11T03:20:00+00:00",
        },
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "red"
    assert check["evidence"]["maintenance_evidence_complete"] is False


def test_sw2021_active_rejects_incomplete_source_evidence() -> None:
    source_report = _active_sw2021_report()
    source_report.pop("snapshot_id")
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(include_industry=True),
        crontab_text=_crontab_text(include_sw2021=True),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        sw2021_reference_report=source_report,
        sqlite_maintenance_report=_green_maintenance_report(),
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "red"
    assert check["evidence"]["source_evidence_complete"] is False


def test_sw2021_commented_cron_declarations_do_not_satisfy_active_state() -> None:
    crontab_text = _crontab_text() + "\n" + "\n".join(
        [
            f"# {source_governance_monitor.SQLITE_MAINTENANCE_CRON_LINE}",
            f"# {source_governance_monitor.SW2021_REFERENCE_CRON_LINE}",
        ]
    )

    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(include_industry=True),
        crontab_text=crontab_text,
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        sw2021_reference_report=_active_sw2021_report(),
        sqlite_maintenance_report=_green_maintenance_report(),
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert check["status"] == "red"
    assert len(check["evidence"]["missing_cron"]) == 2


def test_sw2021_rejected_and_stale_states_are_red() -> None:
    for source_report in (
        {"status": "rejected", "completed_at": "2026-07-11T06:50:00+00:00"},
        {"status": "stale", "completed_at": "2026-07-01T06:50:00+00:00"},
        {"status": "active", "completed_at": "2026-07-01T06:50:00+00:00"},
    ):
        report = source_governance_monitor.evaluate_source_governance(
            agent_config=_agent_config(),
            crontab_text=_crontab_text(),
            api_module_catalog=_api_module_catalog(),
            source_expansion_plan=_source_expansion_plan(),
            health_sla_report={"status": "ok", "summary": {}},
            capability_registry={"summary": {"down": 0, "degraded": 0}},
            sw2021_reference_report=source_report,
            generated_at="2026-07-11T07:00:00+00:00",
        )

        check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
        assert report["status"] == "red"
        assert check["status"] == "red"
        assert check["evidence"]["state"] in {"rejected", "stale"}


def test_sw2021_disabled_by_operator_is_yellow_without_heal_or_cron_requirements() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_active_dataset_registry(),
        sw2021_reference_report={"status": "disabled_by_operator"},
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "yellow"
    assert check["status"] == "yellow"
    assert check["evidence"]["state"] == "disabled_by_operator"
    assert check["evidence"]["automatic_heal_allowed"] is False
    assert check["evidence"]["restart_requested"] is False
    assert check["evidence"]["missing_cron"] == []


def test_sw2021_implemented_unscheduled_is_yellow_until_pilot() -> None:
    report = source_governance_monitor.evaluate_source_governance(
        agent_config=_agent_config(),
        crontab_text=_crontab_text(),
        api_module_catalog=_api_module_catalog(),
        source_expansion_plan=_source_expansion_plan(),
        health_sla_report={"status": "ok", "summary": {}},
        capability_registry={"summary": {"down": 0, "degraded": 0}},
        dataset_registry=_active_dataset_registry(),
        sw2021_reference_report={"status": "implemented_unscheduled"},
        generated_at="2026-07-11T07:00:00+00:00",
    )

    check = next(item for item in report["checks"] if item["name"] == "sw2021_reference")
    assert report["status"] == "yellow"
    assert check["evidence"]["state"] == "implemented_unscheduled"
    assert check["evidence"]["automatic_heal_allowed"] is False
    assert check["evidence"]["missing_cron"] == []


def test_build_source_governance_projects_current_registry_and_wall_clock_from_db(
    monkeypatch,
    tmp_path,
) -> None:
    registry = load_dataset_registry()
    db_path = tmp_path / "marketdata.sqlite"
    cache_path = tmp_path / "interface_runtime.json"
    cache_path.write_text(
        '{"status":"green","summary":{"expected":0,"success":0}}\n',
        encoding="utf-8",
    )
    observed: dict = {}

    def fake_load_runtime(candidate_db, candidate_registry, *, now):
        observed.update(
            {
                "db_path": candidate_db,
                "registry": candidate_registry,
                "now": now,
            }
        )
        expected = len(candidate_registry.datasets)
        return {
            "report_version": "sharedsignals.interface_runtime.v2",
            "authority": "sqlite_ingest_receipts",
            "status": "red",
            "generated_at": now.isoformat(),
            "summary": {
                "expected": expected,
                "observed": expected - 1,
                "success": expected - 1,
                "empty": 0,
                "unobserved": 0,
                "paused": 0,
                "failed": 1,
                "stale": 0,
                "degraded": 1,
            },
            "datasets": {},
            "interfaces": {},
        }

    original_json_file = source_governance_monitor._json_file

    def guarded_json_file(path, default):
        assert path != cache_path, "interface_runtime.json must never be public authority"
        return original_json_file(path, default)

    monkeypatch.setattr(source_governance_monitor, "INTERFACE_RUNTIME_PATH", cache_path)
    monkeypatch.setattr(source_governance_monitor, "load_dataset_registry", lambda: registry)
    monkeypatch.setattr(source_governance_monitor, "marketdata_sqlite_path", lambda: db_path)
    monkeypatch.setattr(
        source_governance_monitor,
        "load_interface_runtime_report",
        fake_load_runtime,
    )
    monkeypatch.setattr(source_governance_monitor, "_json_file", guarded_json_file)

    report = source_governance_monitor.build_source_governance_report()

    runtime_check = next(
        check for check in report["checks"]
        if check["name"] == "interface_runtime_ledger"
    )
    assert observed["db_path"] == db_path
    assert observed["registry"] is registry
    assert observed["now"] == datetime.fromisoformat(report["generated_at"])
    assert observed["now"].tzinfo == timezone.utc
    assert runtime_check["status"] == "red"
    assert runtime_check["evidence"]["expected"] == len(registry.datasets)
    assert runtime_check["evidence"]["failed"] == 1
    assert report["source_files"]["interface_runtime"] == (
        f"{db_path}#market_ingest_runs"
    )


def test_build_source_governance_fails_closed_when_receipt_db_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    missing_db = tmp_path / "missing" / "marketdata.sqlite"
    cache_path = tmp_path / "interface_runtime.json"
    crafted_cache = (
        '{"status":"green","summary":{"expected":114,"success":114}}\n'
    )
    cache_path.write_text(crafted_cache, encoding="utf-8")
    registry = load_dataset_registry()

    monkeypatch.setattr(source_governance_monitor, "INTERFACE_RUNTIME_PATH", cache_path)
    monkeypatch.setattr(source_governance_monitor, "marketdata_sqlite_path", lambda: missing_db)

    report = source_governance_monitor.build_source_governance_report()

    runtime_check = next(
        check for check in report["checks"]
        if check["name"] == "interface_runtime_ledger"
    )
    assert report["status"] == "red"
    assert runtime_check["status"] == "red"
    assert runtime_check["evidence"]["expected"] == len(registry.datasets)
    assert runtime_check["evidence"]["failed"] == len(registry.datasets)
    assert runtime_check["evidence"]["degraded"] == len(registry.datasets)
    assert runtime_check["evidence"]["authority"] == "sqlite_ingest_receipts"
    assert runtime_check["evidence"]["authority_error"] == (
        "receipt_database_unavailable"
    )
    assert not missing_db.exists()
    assert cache_path.read_text(encoding="utf-8") == crafted_cache


def test_green_gate_inherits_db_authority_failure_from_source_governance(
    monkeypatch,
    tmp_path,
) -> None:
    from tools import green_gate_report

    missing_db = tmp_path / "marketdata.sqlite"
    cache_path = tmp_path / "interface_runtime.json"
    cache_path.write_text(
        '{"status":"green","summary":{"success":999}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(source_governance_monitor, "INTERFACE_RUNTIME_PATH", cache_path)
    monkeypatch.setattr(source_governance_monitor, "marketdata_sqlite_path", lambda: missing_db)
    monkeypatch.setattr(
        green_gate_report.patrol,
        "check_data_artifact_guard",
        lambda: {"status": "ok", "value": 0, "threshold": 0, "offenders": []},
    )

    payload = green_gate_report.build_green_gate_payload()

    runtime_check = next(
        check for check in payload["source_governance"]["checks"]
        if check["name"] == "interface_runtime_ledger"
    )
    assert payload["status"] == "red"
    assert runtime_check["status"] == "red"
    assert runtime_check["evidence"]["authority"] == "sqlite_ingest_receipts"
    assert not missing_db.exists()
