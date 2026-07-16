from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_core_docs_freeze_sharedsignals_product_boundary() -> None:
    agents = _read("AGENTS.md")
    readme = _read("README.md")
    status = _read("STATUS.md")

    for document in (agents, readme, status):
        assert "独立外部多源金融数据平台" in document
        assert "GET /v1/catalog" in document
        assert "POST /v1/query" in document
        assert "SQLite ingest receipt" in document

    assert "不承载 opening gate" in agents
    assert "新增数据源不得新增公共 API 路由" in agents
    assert "本地候选" in status
    assert "生产未改变" in status
    assert "uv run --python 3.12" in readme
    assert "uv run --python 3.12" in status
    repo_wide_ruff = (
        "uv run --python 3.12 --with-requirements requirements.txt ruff check ."
    )
    assert repo_wide_ruff not in readme
    assert repo_wide_ruff not in status


def test_design_and_plan_freeze_authority_sequence_and_review_stop_line() -> None:
    design = _read(
        "docs/superpowers/specs/"
        "2026-07-15-sharedsignals-external-data-platform-beta-design.md"
    )
    plan = _read(
        "docs/superpowers/plans/"
        "2026-07-15-sharedsignals-phase1-registry-receipts-retirement.md"
    )

    for document in (design, plan):
        assert "Acceptance Freeze" in document
        assert "SQLite facts + transaction-scoped ingest receipts" in document
        assert "provider-neutral dataset registry" in document
        assert "same-UID malicious" in document

    task_10 = plan.split("## Task 10:", 1)[1].split("## Task 11:", 1)[0]
    assert "Green Gate" not in task_10
    assert "opening gate" not in task_10.lower()


def test_api_contract_labels_legacy_routes_as_compatibility_only() -> None:
    contract = _read("API_CONTRACT.md")
    normative, legacy = contract.split(
        "## Appendix A — Legacy v1 compatibility inventory (non-normative)",
        1,
    )

    assert "Target contract (not yet live)" in contract
    assert "GET /v1/catalog" in contract
    assert "POST /v1/query" in contract
    assert "legacy compatibility surface" in contract
    assert "不得按 provider 或 dataset 新增公共路由" in contract
    assert "唯一面向未来实现的规范层" in normative
    assert "公共数据路由恰好固定" in normative
    assert "数据运行权威固定" in normative
    assert "不属于 SharedSignals" in normative
    assert "不是部署证明" in normative
    assert "新增 API 边界" in legacy
    assert "`/source_status` 是外部 agent" in legacy
    assert "`/opening_gate`" in legacy


def test_supporting_docs_cannot_restore_old_authority_or_route_growth() -> None:
    docs_agents = _read("docs/AGENTS.md")
    onboarding = _read("docs/data_source_onboarding.md")
    capability = _read("docs/market_capability_matrix.md")
    recovery = _read("docs/sqlite_recovery_runbook.md")
    registry = _read("docs/dataset_registry.md")
    receipts = _read("docs/ingest_receipts.md")

    for document in (docs_agents, onboarding, capability, registry):
        assert "GET /v1/catalog" in document
        assert "POST /v1/query" in document

    assert "never adds a public route per provider or dataset" in onboarding
    assert "Green Gate" not in onboarding
    assert "provider-neutral dataset registry" in registry
    assert "transaction-scoped receipts" in receipts
    assert "DuckDB" in recovery
    assert "must never automatically" in recovery
    assert "强制从 DuckDB 重建" not in recovery
