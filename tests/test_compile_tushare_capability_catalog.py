from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path

import pytest
import yaml

import tools.compile_tushare_capability_catalog as compiler
from tools.compile_tushare_capability_catalog import (
    compile_v2_from_paths,
    load_capability_catalog,
    load_mcp_snapshot,
    load_scope_document,
    load_scope_v2_document,
    parse_official_index,
    render_catalog,
    render_catalog_v2,
    resolve_official_rows,
    validate_catalog_document,
    validate_catalog_v2_document,
    validate_mcp_snapshot_document,
    validate_scope_document,
    validate_scope_v2_document,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "compile_tushare_capability_catalog.py"
SCOPE_PATH = ROOT / "config" / "tushare_capability_scope.v1.yaml"
CATALOG_PATH = ROOT / "config" / "tushare_capability_catalog.v1.yaml"
MCP_SNAPSHOT_PATH = ROOT / "config" / "tushare_mcp_capability_snapshot.v1.yaml"
SCOPE_V2_PATH = ROOT / "config" / "tushare_capability_scope.v2.yaml"

MCP_DOMESTIC_ADDITIONS = {
    "bo_cinema",
    "bo_daily",
    "bo_monthly",
    "bo_weekly",
    "cls_index",
    "cls_market_shock",
    "cls_member",
    "cls_stock_shock",
    "concept",
    "concept_detail",
    "film_record",
    "ft_tick",
    "fund_sales_vol",
    "hs_const",
    "index_member",
    "jygs_stock_shock",
    "kpl_concept",
    "limit_list",
    "margin_target",
    "ncov_num",
    "stock_mx",
    "stock_vx",
    "suspend",
    "teleplay_record",
}
V2_DENOMINATOR_ADDITIONS = MCP_DOMESTIC_ADDITIONS | {
    "dc_hot",
    "idx_anns",
    "ths_hot",
    "slb_len_mm",
    "slb_sec_detail",
    "slb_sec",
    "stk_account",
    "stk_account_old",
}
MCP_ABSENT_DOMESTIC = {
    "etf_mins",
    "etf_sh_cons",
    "etf_sz_cons",
    "fut_index_daily",
    "fut_trade_cal",
    "monetary_policy",
    "rt_etf_min",
    "rt_etf_min_daily",
    "sw_mins",
}
V2_RETIRED = {
    "slb_len_mm",
    "slb_sec_detail",
    "slb_sec",
    "stk_account",
    "stk_account_old",
    "margin_target",
    "suspend",
}


def _index(*rows: str, header: str | None = None, suffix: str = "") -> bytes:
    table_header = header or "| 在线文档 | 接口名 | 标题 | 分类 | 描述 |"
    document = "\n".join(
        (
            "",
            "",
            "# 接口列表",
            "",
            "根据需求确定接口，然后访问在线链接，读取具体的使用说明，比如入参，出参等。",
            "",
            table_header,
            "|:---|:---|:---|:---|:---|",
            *rows,
        )
    )
    return f"{document}{suffix}\n".encode()


def _row(
    api_name: str,
    document_id: int,
    *,
    title: str = "标题",
    category: str = "股票数据,基础数据",
    description: str = "描述",
) -> str:
    return (
        f"| https://tushare.pro/wctapi/documents/{document_id}.md "
        f"| {api_name} | {title} | {category} | {description} |"
    )


def _scope_classification_names(scope: dict[str, object]) -> dict[str, set[str]]:
    classifications = scope["classifications"]
    assert isinstance(classifications, list)
    result: dict[str, set[str]] = {}
    for entry in classifications:
        assert isinstance(entry, dict)
        state = entry["scope_state"]
        names = entry["api_names"]
        assert isinstance(state, str)
        assert isinstance(names, list)
        result.setdefault(state, set()).update(names)
    return result


def _scope_v2_dimension_names(
    scope: dict[str, object], dimension: str
) -> dict[str, set[str]]:
    dimensions = scope["dimensions"]
    assert isinstance(dimensions, dict)
    groups = dimensions[dimension]
    assert isinstance(groups, list)
    result: dict[str, set[str]] = {}
    for entry in groups:
        assert isinstance(entry, dict)
        value = entry["value"]
        names = entry["api_names"]
        assert isinstance(value, str)
        assert isinstance(names, list)
        result[value] = set(names)
    return result


def test_parser_preserves_official_fields_and_source_row_identity() -> None:
    source = _index(
        _row(
            "stock_basic",
            25,
            title="股票列表",
            description="获取基础信息",
        ),
        _row("daily", 27, title="历史日线", description=""),
    )

    rows = parse_official_index(source)

    assert [row.api_name for row in rows] == ["stock_basic", "daily"]
    assert rows[0].doc_url == "https://tushare.pro/wctapi/documents/25.md"
    assert rows[0].title == "股票列表"
    assert rows[0].category == "股票数据,基础数据"
    assert rows[0].description == "获取基础信息"
    assert rows[0].line_number == 9
    assert (
        rows[0].row_sha256
        == hashlib.sha256(
            _row(
                "stock_basic",
                25,
                title="股票列表",
                description="获取基础信息",
            ).encode()
        ).hexdigest()
    )
    assert rows[1].description == ""


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (
            _index(
                _row("daily", 27),
                header="| 在线文档 | 接口名 | 标题 | 分类 | 描述 | 未知字段 |",
            ),
            "header",
        ),
        (_index(_row("daily", 27), suffix="\nnot-a-table-row"), "format drift"),
        (_index("| only | four | cells | here |"), "five cells"),
        (
            _index("| https://example.invalid/27.md | daily | 标题 | 分类 | 描述 |"),
            "doc_url",
        ),
        (_index(_row("Daily", 27)), "api_name"),
        (_index(_row("daily", 27, title="")), "title"),
        (_index(_row("daily", 27, category="")), "category"),
    ],
)
def test_parser_rejects_format_drift_and_invalid_fields(
    source: bytes, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        parse_official_index(source)


def test_duplicate_api_requires_explicit_canonical_document_resolution() -> None:
    rows = parse_official_index(
        _index(
            _row("pro_bar", 146, title="复权行情", description=""),
            _row("pro_bar", 109, title="通用行情接口", description=""),
        )
    )

    with pytest.raises(ValueError, match="unreviewed duplicate api_name"):
        resolve_official_rows(rows, [])

    resolved = resolve_official_rows(
        rows,
        [
            {
                "api_name": "pro_bar",
                "canonical_doc_url": ("https://tushare.pro/wctapi/documents/109.md"),
                "reason": "Reviewed canonical unified API document.",
            }
        ],
    )

    assert len(resolved) == 1
    assert resolved[0]["api_name"] == "pro_bar"
    assert resolved[0]["doc_url"].endswith("/109.md")
    assert resolved[0]["title"] == "通用行情接口"
    assert {row["title"] for row in resolved[0]["source_rows"]} == {
        "复权行情",
        "通用行情接口",
    }
    assert [row["line_number"] for row in resolved[0]["source_rows"]] == [9, 10]


@pytest.mark.parametrize(
    "resolutions",
    [
        [
            {
                "api_name": "pro_bar",
                "canonical_doc_url": "https://tushare.pro/wctapi/documents/999.md",
                "reason": "Not a source row.",
            }
        ],
        [
            {
                "api_name": "daily",
                "canonical_doc_url": "https://tushare.pro/wctapi/documents/27.md",
                "reason": "Not duplicated.",
            }
        ],
        [
            {
                "api_name": "pro_bar",
                "canonical_doc_url": "https://tushare.pro/wctapi/documents/109.md",
                "reason": "First.",
            },
            {
                "api_name": "pro_bar",
                "canonical_doc_url": "https://tushare.pro/wctapi/documents/109.md",
                "reason": "Duplicate override.",
            },
        ],
    ],
)
def test_duplicate_resolution_rejects_unknown_ambiguous_or_repeated_entries(
    resolutions: list[dict[str, str]],
) -> None:
    rows = parse_official_index(
        _index(
            _row("daily", 27),
            _row("pro_bar", 146),
            _row("pro_bar", 109),
        )
    )

    with pytest.raises(ValueError):
        resolve_official_rows(rows, resolutions)


def test_checked_in_scope_is_exhaustive_and_does_not_claim_entitlement() -> None:
    scope = load_scope_document(SCOPE_PATH)
    names_by_state = _scope_classification_names(scope)

    assert {state: len(names) for state, names in names_by_state.items()} == {
        "in_scope": 190,
        "locked": 0,
        "unknown": 4,
        "excluded": 36,
        "retired": 5,
        "non_data_operation": 4,
    }
    assert names_by_state["unknown"] == {
        "idx_anns",
        "dc_hot",
        "ths_hot",
        "pro_bar",
    }
    assert names_by_state["retired"] == {
        "slb_len_mm",
        "slb_sec_detail",
        "slb_sec",
        "stk_account",
        "stk_account_old",
    }
    assert names_by_state["non_data_operation"] == {
        "p_save",
        "p_list",
        "p_delete",
        "p_get",
    }
    assert {
        "daily",
        "stock_basic",
        "trade_cal",
        "moneyflow_hsgt",
        "stock_hsgt",
        "hk_hold",
        "hsgt_top10",
    } <= names_by_state["in_scope"]
    structural_keys: set[str] = set()

    def collect_keys(value: object) -> None:
        if isinstance(value, dict):
            structural_keys.update(str(key) for key in value)
            for nested in value.values():
                collect_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_keys(nested)

    collect_keys(scope)
    assert structural_keys.isdisjoint(
        {"entitlement_state", "cadence", "requested_fields", "field_contract"}
    )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda scope: scope.update(unexpected=True), "unknown key"),
        (
            lambda scope: scope["classifications"][0].update(unexpected=True),
            "unknown key",
        ),
        (
            lambda scope: scope["classifications"][0].update(scope_state="active"),
            "scope_state",
        ),
        (
            lambda scope: scope["classifications"][0].update(reason=""),
            "reason",
        ),
        (
            lambda scope: scope["classifications"][1]["api_names"].append(
                scope["classifications"][0]["api_names"][0]
            ),
            "duplicate classification",
        ),
    ],
)
def test_scope_schema_rejects_unknown_invalid_and_duplicate_fields(
    mutation, error: str
) -> None:
    scope = yaml.safe_load(SCOPE_PATH.read_text(encoding="utf-8"))
    mutation(scope)

    with pytest.raises(ValueError, match=error):
        validate_scope_document(scope)


def test_checked_in_catalog_is_the_exact_239_api_snapshot() -> None:
    catalog = load_capability_catalog(CATALOG_PATH)
    capabilities = catalog["capabilities"]
    assert isinstance(capabilities, list)
    names = [item["api_name"] for item in capabilities]

    assert names == sorted(names)
    assert len(names) == len(set(names)) == 239
    assert catalog["provenance"] == {
        "repository_url": "https://github.com/waditu-tushare/skills.git",
        "pinned_commit": "5e12b31d09123e262c5fb38564e80c26d05cb830",
        "index_path": "tushare/references/数据接口.md",
        "index_sha256": (
            "0df85aa1265a59b963fca6660eb3f58bec232aa2347c9c44d763d0d55a1b9cb2"
        ),
    }
    assert catalog["counts"] == {
        "official_source_rows": 240,
        "official_unique_api_names": 239,
    }
    assert (
        catalog["scope"]["scope_sha256"]
        == hashlib.sha256(SCOPE_PATH.read_bytes()).hexdigest()
    )
    assert catalog["scope_counts"] == {
        "in_scope": 190,
        "locked": 0,
        "unknown": 4,
        "excluded": 36,
        "retired": 5,
        "non_data_operation": 4,
    }
    assert "legacy_coverage" not in catalog


def test_catalog_preserves_all_source_fields_and_pro_bar_variants() -> None:
    catalog = load_capability_catalog(CATALOG_PATH)
    capabilities = catalog["capabilities"]
    by_name = {item["api_name"]: item for item in capabilities}

    required = {
        "api_name",
        "doc_url",
        "title",
        "category",
        "description",
        "source_rows",
        "source_resolution",
        "scope_state",
        "scope_reason",
    }
    assert all(set(item) == required for item in capabilities)
    assert all(item["source_rows"] for item in capabilities)
    assert all(
        isinstance(item["description"], str)
        and isinstance(item["scope_reason"], str)
        and item["scope_reason"]
        for item in capabilities
    )
    pro_bar = by_name["pro_bar"]
    assert pro_bar["doc_url"].endswith("/109.md")
    assert pro_bar["title"] == "通用行情接口"
    assert {row["doc_url"] for row in pro_bar["source_rows"]} == {
        "https://tushare.pro/wctapi/documents/146.md",
        "https://tushare.pro/wctapi/documents/109.md",
    }
    assert {row["title"] for row in pro_bar["source_rows"]} == {
        "复权行情",
        "通用行情接口",
    }
    assert len(pro_bar["source_rows"]) == 2
    assert all(
        len(item["source_rows"]) == 1
        for name, item in by_name.items()
        if name != "pro_bar"
    )


def test_catalog_schema_rejects_unknown_fields_and_duplicate_api_names() -> None:
    catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    unknown = deepcopy(catalog)
    unknown["capabilities"][0]["entitlement_state"] = "active"
    with pytest.raises(ValueError, match="unknown key"):
        validate_catalog_document(unknown)

    duplicate = deepcopy(catalog)
    duplicate["capabilities"].append(deepcopy(duplicate["capabilities"][0]))
    with pytest.raises(ValueError, match="duplicate api_name"):
        validate_catalog_document(duplicate)


def test_catalog_rendering_is_byte_deterministic() -> None:
    catalog = load_capability_catalog(CATALOG_PATH)
    expected = CATALOG_PATH.read_bytes()

    assert render_catalog(catalog) == expected
    assert render_catalog(deepcopy(catalog)) == expected


def test_compiler_has_no_network_provider_or_dataset_specific_branch() -> None:
    source = TOOL_PATH.read_text(encoding="utf-8")
    for forbidden_import in (
        "import requests",
        "import httpx",
        "import urllib",
        "import socket",
        "collectors.tushare",
    ):
        assert forbidden_import not in source
    for api_name in (
        '"trade_cal"',
        '"stock_basic"',
        '"daily"',
        '"pro_bar"',
        '"p_save"',
        '"hk_daily"',
        '"us_daily"',
    ):
        assert api_name not in source


def test_source_checkout_head_and_scope_pin_fail_closed() -> None:
    with pytest.raises(ValueError, match="does not match"):
        compiler.compile_from_paths(
            source_root=ROOT,
            scope_path=SCOPE_PATH,
        )

    scope = load_scope_document(SCOPE_PATH)
    mutated = deepcopy(scope)
    mutated["official_source"]["index_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="frozen pin"):
        validate_scope_document(mutated)


def test_pinned_offline_checkout_rebuilds_checked_in_catalog_when_supplied() -> None:
    source_root_value = os.environ.get("TUSHARE_SKILLS_SOURCE_ROOT")
    if not source_root_value:
        pytest.skip("set TUSHARE_SKILLS_SOURCE_ROOT for pinned offline rebuild")

    rebuilt = compiler.compile_from_paths(
        source_root=Path(source_root_value),
        scope_path=SCOPE_PATH,
    )

    assert render_catalog(rebuilt) == CATALOG_PATH.read_bytes()


def test_mcp_snapshot_is_metadata_only_and_has_258_unique_tools() -> None:
    snapshot = load_mcp_snapshot(MCP_SNAPSHOT_PATH)
    tools = snapshot["tools"]
    assert isinstance(tools, list)
    names = [item["name"] for item in tools]

    assert set(snapshot) == {
        "version",
        "snapshot_id",
        "source",
        "entitlement_asserted",
        "tools",
    }
    assert snapshot["entitlement_asserted"] is False
    assert names == sorted(names)
    assert len(names) == len(set(names)) == 258
    assert all(set(item) == {"name", "parameter_schema_sha256"} for item in tools)
    assert all(
        len(item["parameter_schema_sha256"]) == 64
        and set(item["parameter_schema_sha256"]) <= set("0123456789abcdef")
        for item in tools
    )
    serialized = MCP_SNAPSHOT_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "description:",
        "runtime_result",
        "response:",
        "secret:",
        "token:",
        "credential:",
    ):
        assert forbidden not in serialized


def test_scope_v2_freezes_the_268_name_union_and_required_boundaries() -> None:
    official = load_capability_catalog(CATALOG_PATH)
    snapshot = load_mcp_snapshot(MCP_SNAPSHOT_PATH)
    scope = load_scope_v2_document(SCOPE_V2_PATH)
    official_names = {item["api_name"] for item in official["capabilities"]}
    mcp_names = {item["name"] for item in snapshot["tools"]}
    union_names = official_names | mcp_names

    assert len(official_names) == 239
    assert len(mcp_names) == 258
    assert len(union_names) == 268
    assert scope["expected_counts"] == {
        "official_unique_api_names": 239,
        "mcp_unique_tool_names": 258,
        "union_unique_names": 268,
        "domestic_read_dataset": 222,
        "excluded_overseas": 41,
        "account_operation": 4,
        "helper": 1,
        "denominator_additions": 32,
        "mcp_absent_domestic_datasets": 9,
    }
    product = _scope_v2_dimension_names(scope, "product_scope")
    assert {value: len(names) for value, names in product.items()} == {
        "domestic_read_dataset": 222,
        "excluded_overseas": 41,
        "account_operation": 4,
        "helper": 1,
    }
    assert set().union(*product.values()) == union_names
    assert product["account_operation"] == {"p_save", "p_delete", "p_list", "p_get"}
    assert product["helper"] == {"pro_bar"}
    assert product["excluded_overseas"] - official_names == {
        "ggt_monthly",
        "ncov_global",
        "rt_hk_tick",
        "tmt_twincome",
        "tmt_twincomedetail",
    }

    baseline = scope["baseline"]
    assert isinstance(baseline, dict)
    additions = baseline["denominator_additions"]
    absent = baseline["mcp_absent_domestic_datasets"]
    assert isinstance(additions, dict)
    assert isinstance(absent, dict)
    assert set(additions["api_names"]) == V2_DENOMINATOR_ADDITIONS
    assert len(V2_DENOMINATOR_ADDITIONS) == 32
    assert set(absent["api_names"]) == MCP_ABSENT_DOMESTIC
    assert len(MCP_ABSENT_DOMESTIC) == 9

    lifecycle = _scope_v2_dimension_names(scope, "lifecycle")
    contracts = _scope_v2_dimension_names(scope, "contract_state")
    visibility = _scope_v2_dimension_names(scope, "mcp_visibility")
    entitlement = _scope_v2_dimension_names(scope, "entitlement")
    activation = _scope_v2_dimension_names(scope, "activation")
    assert lifecycle["retired"] == V2_RETIRED
    assert contracts["review_required"] == {"idx_anns", "dc_hot", "ths_hot"}
    assert contracts["missing_official_contract"] == mcp_names - official_names
    assert visibility["visible"] == mcp_names
    assert visibility["absent"] == union_names - mcp_names
    assert entitlement["unobserved"] == union_names
    assert activation["paused"] == product["domestic_read_dataset"]
    assert (
        activation["not_applicable"] == union_names - product["domestic_read_dataset"]
    )


def test_v2_compiler_outputs_only_222_paused_domestic_datasets() -> None:
    catalog = compile_v2_from_paths(
        official_catalog_path=CATALOG_PATH,
        mcp_snapshot_path=MCP_SNAPSHOT_PATH,
        scope_path=SCOPE_V2_PATH,
    )
    datasets = catalog["datasets"]
    assert isinstance(datasets, list)
    by_name = {item["name"]: item for item in datasets}

    assert len(datasets) == len(by_name) == 222
    assert [item["name"] for item in datasets] == sorted(by_name)
    assert catalog["counts"] == {
        "official_unique_api_names": 239,
        "mcp_unique_tool_names": 258,
        "union_unique_names": 268,
        "domestic_read_dataset": 222,
        "excluded_overseas": 41,
        "account_operation": 4,
        "helper": 1,
        "denominator_additions": 32,
        "mcp_absent_domestic_datasets": 9,
    }
    assert all(
        set(item["dimensions"])
        == {
            "product_scope",
            "lifecycle",
            "contract_state",
            "mcp_visibility",
            "entitlement",
            "activation",
        }
        for item in datasets
    )
    assert all(item["dimensions"]["entitlement"] == "unobserved" for item in datasets)
    assert all(item["dimensions"]["activation"] == "paused" for item in datasets)
    for name in MCP_DOMESTIC_ADDITIONS:
        item = by_name[name]
        assert item["official_doc_url"] is None
        assert item["dimensions"]["contract_state"] == "missing_official_contract"
        assert item["dimensions"]["mcp_visibility"] == "visible"
    for name in MCP_ABSENT_DOMESTIC:
        item = by_name[name]
        assert item["official_doc_url"] is not None
        assert item["mcp_parameter_schema_sha256"] is None
        assert item["dimensions"]["mcp_visibility"] == "absent"
    for name in V2_RETIRED:
        assert by_name[name]["dimensions"]["lifecycle"] == "retired"
        assert by_name[name]["dimensions"]["activation"] == "paused"
    assert {"p_save", "p_delete", "p_list", "p_get", "pro_bar"}.isdisjoint(by_name)

    rendered = render_catalog_v2(catalog)
    assert render_catalog_v2(deepcopy(catalog)) == rendered
    assert validate_catalog_v2_document(yaml.safe_load(rendered)) == catalog
    rendered_text = rendered.decode("utf-8")
    assert "/v1/catalog" not in rendered_text
    assert "/v1/query" not in rendered_text
    structural_keys: set[str] = set()

    def collect_keys(value: object) -> None:
        if isinstance(value, dict):
            structural_keys.update(str(key) for key in value)
            for nested in value.values():
                collect_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_keys(nested)

    collect_keys(catalog)
    assert structural_keys.isdisjoint(
        {
            "strategy",
            "signal",
            "position",
            "risk",
            "order",
            "execution",
            "route",
            "public_route",
        }
    )


def test_scope_v2_inputs_fail_closed_on_entitlement_alias_and_source_drift() -> None:
    snapshot = yaml.safe_load(MCP_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    snapshot["entitlement_asserted"] = True
    with pytest.raises(ValueError, match="cannot assert entitlement"):
        validate_mcp_snapshot_document(snapshot)

    snapshot = yaml.safe_load(MCP_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    snapshot["tools"][0]["description"] = "must not be retained"
    with pytest.raises(ValueError, match="unknown key"):
        validate_mcp_snapshot_document(snapshot)

    scope = yaml.safe_load(SCOPE_V2_PATH.read_text(encoding="utf-8"))
    scope["dimensions"]["mcp_visibility"][1]["aliases"] = {}
    with pytest.raises(ValueError, match="unknown key"):
        validate_scope_v2_document(scope)

    scope = yaml.safe_load(SCOPE_V2_PATH.read_text(encoding="utf-8"))
    scope["sources"]["mcp_snapshot"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        compiler.compile_capability_catalog_v2(
            official_catalog_document=yaml.safe_load(
                CATALOG_PATH.read_text(encoding="utf-8")
            ),
            official_catalog_sha256=hashlib.sha256(
                CATALOG_PATH.read_bytes()
            ).hexdigest(),
            mcp_snapshot_document=yaml.safe_load(
                MCP_SNAPSHOT_PATH.read_text(encoding="utf-8")
            ),
            mcp_snapshot_sha256=hashlib.sha256(
                MCP_SNAPSHOT_PATH.read_bytes()
            ).hexdigest(),
            scope_document=scope,
            scope_sha256=hashlib.sha256(SCOPE_V2_PATH.read_bytes()).hexdigest(),
        )
