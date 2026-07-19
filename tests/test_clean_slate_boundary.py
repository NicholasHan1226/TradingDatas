from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_retired_subsystems_are_not_present() -> None:
    retired = (
        "bridge",
        "cron",
        "memory",
        "collectors/crypto",
        "collectors/events",
        "collectors/polymarket",
        "legacy_query_compat.py",
        "reader.py",
        "scheduler.py",
        "sector_flow_v2.py",
        "duckdb_merge.py",
        "heal.py",
        "patrol.py",
        "patrol_heal_cron.sh",
        "crontab.txt",
        "deploy.sh",
        "rollback.sh",
        "storage/duckdb_schema.py",
        "config/dataset_registry.yaml",
        "config/api_module_catalog.yaml",
        "config/external_agent_api_config.json",
        "config/source_expansion_priority.yaml",
        "config/tushare_capability_plan.yaml",
    )

    present = [relative for relative in retired if (ROOT / relative).exists()]
    assert present == []


def test_active_runtime_has_no_sharedsignals_identity() -> None:
    roots = (
        ROOT / "collectors",
        ROOT / "config",
        ROOT / "deploy",
        ROOT / "storage",
        ROOT / "tools",
    )
    files = [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix
        in {".env", ".json", ".py", ".service", ".sh", ".timer", ".yaml", ".yml"}
    ]
    files.extend(
        path
        for path in (
            ROOT / "api_server.py",
            ROOT / "data_plane_runtime.py",
            ROOT / "runtime_paths.py",
        )
        if path.exists()
    )

    violations = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "sharedsignals" in text.casefold():
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_only_fixed_public_data_routes_are_documented_in_server() -> None:
    source = (ROOT / "api_server.py").read_text(encoding="utf-8")
    for retired_route in (
        "/tushare",
        "/source_status",
        "/opening_gate",
        "/crypto",
        "/pm_",
        "/v2/sector-flow",
    ):
        assert retired_route not in source
    assert "/v1/catalog" in source
    assert "/v1/query" in source
