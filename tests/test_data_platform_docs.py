from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_core_docs_freeze_sharedsignals_product_boundary() -> None:
    agents = _read("AGENTS.md")
    readme = _read("README.md")
    status = _read("STATUS.md")
    collectors = _read("collectors/AGENTS.md")
    design = _read(
        "docs/superpowers/specs/"
        "2026-07-15-sharedsignals-external-data-platform-beta-design.md"
    )

    for document in (agents, readme, status):
        assert "独立外部多源金融数据平台" in document
        assert "GET /v1/catalog" in document
        assert "POST /v1/query" in document
        assert "SQLite ingest receipt" in document

    assert "不承载 opening gate" in agents
    assert "新增数据源不得新增公共 API 路由" in agents
    for document in (agents, readme, status):
        assert "类似 Tushare 的多源金融数据服务" in document
        assert "api_name + params + fields" in document
    assert "Tushare is a paid, existing upstream data capability" in design
    assert "The four-dataset pilot is only a zero-code path proof" in design
    assert "不得为每个 Tushare 接口编写独立 collector" in collectors
    assert "新增普通 Tushare dataset" in collectors
    assert "只改 registry/config" in collectors
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

    assert "Target V1 normative contract" in normative
    assert "v2" not in normative.casefold()
    assert "Tasks 1–6" in normative
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
    assert "Reserved unmapped-attempt tombstones" in receipts
    assert "must not change any registered dataset's runtime state" in receipts
    assert "unmapped.tushare.<sha256(provider_api)[:16]>" in receipts
    assert "Classification is independent" in receipts
    assert "Only a genuine registry alias miss" in receipts
    assert "future additive global audit bucket" in receipts
    assert "DuckDB" in recovery
    assert "must never automatically" in recovery
    assert "强制从 DuckDB 重建" not in recovery


def test_consumer_contract_docs_freeze_v1_handoff_and_truth_layers() -> None:
    readme = _read("README.md")
    contract = _read("API_CONTRACT.md")
    query_service = _read("docs/query_service.md")
    data_contract = _read("docs/data_contract.md")
    onboarding = _read("docs/data_source_onboarding.md")
    status = _read("STATUS.md")

    current_docs = (
        readme,
        contract.split(
            "## Appendix A — Legacy v1 compatibility inventory (non-normative)",
            1,
        )[0],
        query_service,
        data_contract,
        onboarding,
        status,
    )
    for document in current_docs:
        assert "GET /v1/catalog" in document
        assert "POST /v1/query" in document

    assert "exactly two target public data routes" in data_contract
    assert "provider-neutral dataset ID" in data_contract
    assert "independent dataset schema version" in data_contract
    assert "one verified SQLite snapshot" in data_contract
    assert "signed keyset cursor" in data_contract
    assert "global source flag" in data_contract
    assert "HTTP 200" in data_contract
    assert '"market": "Ashare"' in data_contract
    assert "catalog dataset.market remains `CN`" in data_contract
    for state in ("success", "empty", "unobserved", "paused", "failed", "stale"):
        assert f"`{state}`" in data_contract
    for metadata in ("freshness", "quality", "lineage"):
        assert f"`{metadata}`" in data_contract

    assert "same QueryService" in data_contract
    assert "does not add a public route" in onboarding
    for gate in (
        "registry and schema",
        "entitlement and activation evidence",
        "storage mapping",
        "normalization, validation, and deduplication",
        "same SQLite transaction",
        "query and metadata contract",
        "focused and full tests",
        "current documentation",
    ):
        assert gate in onboarding

    for responsibility in (
        "opening",
        "strategy",
        "capital",
        "position",
        "risk",
        "order",
        "fill",
    ):
        assert responsibility in data_contract

    for truth_layer in (
        "local worktree PASS",
        "local main",
        "origin/GitHub",
        "production checkout",
        "production runtime",
        "external route",
        "real dataset evidence",
    ):
        assert truth_layer in data_contract
        assert truth_layer in status
