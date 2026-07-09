from __future__ import annotations

from pathlib import Path

import yaml


PLAN_PATH = Path("config/source_expansion_priority.yaml")
CATALOG_PATH = Path("config/api_module_catalog.yaml")
REQUIRED_FIELDS = {
    "source_id",
    "provider",
    "market",
    "module",
    "api_name_or_dataset",
    "activation_mode",
    "cadence_class",
    "freshness_sla",
    "target_tables",
    "write_path",
    "rate_limit",
    "degraded_behavior",
    "http_surface",
    "owner_consumer",
    "expected_write_cost",
    "priority",
    "production_ready",
}


def _plan() -> dict:
    return yaml.safe_load(PLAN_PATH.read_text(encoding="utf-8"))


def _catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def _candidates() -> list[dict]:
    rows: list[dict] = []
    for batch in _plan().get("priority_batches", []):
        for item in batch.get("candidates", []):
            candidate = dict(item)
            candidate["batch"] = batch.get("batch")
            rows.append(candidate)
    return rows


def test_source_expansion_priority_plan_is_planned_only() -> None:
    plan = _plan()
    candidates = _candidates()

    assert plan["status"] == "planned_only"
    assert plan["activation_policy"]["pilot_before_scheduled"] is True
    assert plan["activation_policy"]["no_5min_without_hot_path_proof"] is True
    assert candidates
    assert all(item["activation_mode"] == "planned" for item in candidates)
    assert all(item["production_ready"] is False for item in candidates)


def test_source_expansion_candidates_have_required_onboarding_fields() -> None:
    missing: list[str] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()

    for item in _candidates():
        missing_fields = sorted(field for field in REQUIRED_FIELDS if field not in item or item[field] in ("", [], None))
        if missing_fields:
            missing.append(f"{item.get('source_id', item.get('batch'))}:{','.join(missing_fields)}")
        source_id = str(item["source_id"])
        if source_id in seen:
            duplicate_ids.append(source_id)
        seen.add(source_id)

    assert missing == []
    assert duplicate_ids == []


def test_source_expansion_candidates_are_not_installed_in_production_cron() -> None:
    crontab_text = "\n".join(path.read_text(encoding="utf-8") for path in (Path("crontab.txt"), Path("cron/crontab.txt")))
    offenders = [
        item["write_path"]
        for item in _candidates()
        if item["write_path"] in crontab_text
    ]

    assert offenders == []


def test_source_expansion_candidates_map_to_planned_api_modules() -> None:
    modules = {row["module"]: row for row in _catalog().get("canonical_modules", [])}
    missing_modules: list[str] = []
    table_offenders: list[str] = []
    surface_offenders: list[str] = []

    for item in _candidates():
        module = modules.get(item["module"])
        if module is None:
            missing_modules.append(f"{item['source_id']}:{item['module']}")
            continue

        allowed_tables = set(module["canonical_tables"])
        target_tables = set(item["target_tables"])
        if not target_tables <= allowed_tables:
            table_offenders.append(f"{item['source_id']}:{sorted(target_tables - allowed_tables)}")

        allowed_surfaces = set(module["default_http_surface"])
        surfaces = set(item["http_surface"])
        if not surfaces <= allowed_surfaces:
            surface_offenders.append(f"{item['source_id']}:{sorted(surfaces - allowed_surfaces)}")

    assert missing_modules == []
    assert table_offenders == []
    assert surface_offenders == []


def test_api_module_catalog_prefers_endpoint_reuse_before_expansion() -> None:
    catalog = _catalog()

    assert catalog["status"] == "active_governance"
    assert catalog["api_extension_policy"]["default"] == "reuse_existing_endpoint"
    assert "A new provider that writes the same read-model tables as an existing module." in catalog["api_extension_policy"]["never_add_endpoint_for"]
    assert {row["module"] for row in catalog["canonical_modules"]} >= {
        "event_news_announcements_reports",
        "macro_rates_fx",
        "crypto_price_redundancy",
        "prediction_market_redundancy",
    }


def test_source_expansion_plan_is_exposed_to_external_agent_config_and_docs() -> None:
    external_config = Path("config/external_agent_api_config.json").read_text(encoding="utf-8")
    onboarding_doc = Path("docs/data_source_onboarding.md").read_text(encoding="utf-8")
    matrix_doc = Path("docs/market_capability_matrix.md").read_text(encoding="utf-8")

    assert str(PLAN_PATH) in external_config
    assert str(CATALOG_PATH) in external_config
    assert str(PLAN_PATH) in onboarding_doc
    assert str(CATALOG_PATH) in onboarding_doc
    assert "B1_event_risk_official_sources" in matrix_doc
    assert "Module And API Catalog" in matrix_doc
