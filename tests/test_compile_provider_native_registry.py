from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from dataset_registry import load_dataset_registry
from tools.compile_provider_native_registry import (
    compile_provider_native_registry,
    load_upstream_contract_bundle,
    render_compilation,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "dataset_registry.yaml"
PLAN_PATH = ROOT / "config" / "tushare_capability_plan.yaml"
COLLECTOR_CONFIG_PATH = ROOT / "collectors" / "tushare" / "config.yaml"
CONTRACT_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
TARGET_REGISTRY_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"


def _read_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset() -> dict[str, object]:
    return {
        "dataset_id": "cn.synthetic.compiler",
        "aliases": ["tushare.synthetic_compiler"],
        "domain": "reference",
        "market": "CN",
        "entity_type": "provider_row",
        "data_classification": "objective_factual",
        "schema_version": "1.0.0",
        "schema_profile": "legacy_wrong.v1",
        "cadence_class": "legacy_daily",
        "timezone": "Asia/Shanghai",
        "freshness_sla_seconds": 86_400,
        "provider_bindings": [
            {
                "provider": "tushare",
                "api_name": "synthetic_compiler",
                "adapter_version": "legacy.v1",
                "read_discriminator_value": "tushare_synthetic_compiler",
                "entitlement_state": "active",
                "activation_state": "active",
                "target_tables": ["market_factors"],
            }
        ],
        "read_model_adapter": {
            "adapter_version": "sqlite-read-model.v1",
            "primary_table": "market_factors",
            "fixed_field_filters": [
                {"field": "provider", "allowed_values": ["synthetic_compiler"]}
            ],
        },
    }


def _documents() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    registry = {
        "version": 1,
        "query_defaults": {
            "max_request_bytes": 65_536,
            "max_response_bytes": 4_194_304,
            "max_page_size": 500,
            "max_lookback_days": 36_500,
            "max_selected_fields": 100,
            "max_filter_terms": 16,
            "max_in_values": 100,
            "max_order_terms": 8,
            "max_catalog_search_chars": 128,
            "cursor_ttl_seconds": 900,
            "sqlite_progress_steps": 1_000_000,
        },
        "schema_profiles": {
            "legacy_wrong.v1": {
                "schema_version": "1.0.0",
                "fields": [
                    {
                        "name": "factor_name",
                        "logical_type": "text",
                        "nullable": False,
                        "selectable": True,
                        "filterable": True,
                        "sortable": True,
                    }
                ],
                "primary_key": ["factor_name"],
                "default_projection": ["factor_name"],
                "as_of_field": None,
                "as_of_format": None,
                "range_field": None,
                "partition_field": None,
                "point_in_time": "current_snapshot",
                "backfill_policy": "provider_limited",
                "empty_data_policy": "allowed",
                "required_scope": "market_data",
                "quota_class": "beta_standard",
            }
        },
        "datasets": [_dataset()],
    }
    plan = {
        "version": 1,
        "modules": [
            {
                "module": "synthetic",
                "market": "Ashare",
                "default_cadence": "postclose_daily",
                "apis": [
                    {
                        "api_name": "synthetic_compiler",
                        "mode": "scheduled",
                        "tier": "P1_eod_daily",
                        "cadence": "postclose_daily",
                    }
                ],
            }
        ],
    }
    collector = {
        "priorities": {
            "P1_eod_daily": [
                {
                    "api_name": "synthetic_compiler",
                    "frequency": "daily",
                    "params": {"wrong": "{wrong}"},
                    "fields": "factor_name",
                    "per_stock": False,
                }
            ]
        }
    }
    return registry, plan, collector


def _contract_bundle(*, contracts: list[dict[str, object]] | None = None) -> dict[str, object]:
    contract = {
        "dataset_id": "cn.synthetic.compiler",
        "provider": "tushare",
        "api_name": "synthetic_compiler",
        "source_document_url": "https://example.invalid/doc.md",
        "source_document_sha256": "b" * 64,
        "schema_version": "2.0.0",
        "fields": [
            {
                "name": "exchange",
                "declared_source_type": "str",
                "logical_type": "text",
                "nullable": False,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
            {
                "name": "cal_date",
                "declared_source_type": "str",
                "logical_type": "text",
                "nullable": False,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
            {
                "name": "is_open",
                "declared_source_type": "str",
                "logical_type": "integer",
                "nullable": False,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
            {
                "name": "pretrade_date",
                "declared_source_type": "str",
                "logical_type": "text",
                "nullable": True,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
        ],
        "primary_key": ["exchange", "cal_date"],
        "default_projection": ["exchange", "cal_date", "is_open", "pretrade_date"],
        "as_of_field": "cal_date",
        "as_of_format": "yyyymmdd",
        "range_field": "cal_date",
        "partition_field": "cal_date",
        "cadence_class": "daily_reference",
        "point_in_time": "current_snapshot",
        "backfill_policy": "provider_limited",
        "empty_data_policy": "forbidden",
        "required_scope": "market_data",
        "quota_class": "beta_standard",
        "request_template": {
            "exchange": "SSE",
            "start_date": "${window.start_date}",
            "end_date": "${window.end_date}",
        },
        "request_window_policy": {
            "required_keys": ["start_date", "end_date"],
            "formats": {"start_date": "yyyymmdd", "end_date": "yyyymmdd"},
            "range_start_key": "start_date",
            "range_end_key": "end_date",
            "max_span_days": 366,
        },
        "response_completeness": {
            "strategy": "one_row_per_calendar_date",
            "date_field": "cal_date",
            "request_start_key": "start_date",
            "request_end_key": "end_date",
            "fixed_field_matches": {"exchange": "exchange"},
        },
        "requested_fields": [],
        "budgets": {
            "max_rows_per_attempt": 1000,
            "max_payload_bytes_per_row": 65_536,
            "max_batch_bytes": 4_194_304,
            "max_nesting_depth": 16,
        },
        "reviewed_type_overrides": [
            {
                "field": "is_open",
                "declared_source_type": "str",
                "observed_json_type": "integer",
                "logical_type": "integer",
                "reason": "bounded provider response uses a JSON integer",
                "evidence": "isolated bounded transport probe",
            }
        ],
    }
    return {
        "version": 1,
        "bundle_id": "tushare-upstream-contracts.v1",
        "provider": "tushare",
        "provenance": {
            "repository_url": "https://github.com/waditu-tushare/skills.git",
            "pinned_commit": "a" * 40,
            "index_path": "tushare/references/data.md",
            "index_sha256": "c" * 64,
        },
        "contracts": [contract] if contracts is None else contracts,
    }


def test_compiler_replaces_legacy_schema_with_reviewed_provider_contract(tmp_path: Path) -> None:
    registry, plan, collector = _documents()
    source = deepcopy(registry)

    candidate, report = compile_provider_native_registry(
        registry,
        plan,
        collector,
        _contract_bundle(),
    )
    path = tmp_path / "candidate.yaml"
    path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
    compiled = load_dataset_registry(path).resolve("cn.synthetic.compiler")
    binding = compiled.provider_bindings[0]

    assert registry == source
    assert candidate.get("schema_profiles") is None
    assert compiled.schema_version == "2.0.0"
    assert [field.name for field in compiled.fields] == [
        "exchange",
        "cal_date",
        "is_open",
        "pretrade_date",
    ]
    assert "factor_name" not in {field.name for field in compiled.fields}
    assert compiled.primary_key == ("exchange", "cal_date")
    assert compiled.empty_data_policy == "forbidden"
    assert dict(binding.request_template) == {
        "end_date": "${window.end_date}",
        "exchange": "SSE",
        "start_date": "${window.start_date}",
    }
    assert binding.requested_fields == ()
    assert binding.request_window_policy is not None
    assert binding.request_window_policy.max_span_days == 366
    assert binding.response_completeness is not None
    assert binding.response_completeness.strategy == "one_row_per_calendar_date"
    assert binding.response_completeness.date_field == "cal_date"
    assert binding.response_completeness.request_start_key == "start_date"
    assert binding.response_completeness.request_end_key == "end_date"
    assert dict(binding.response_completeness.fixed_field_matches) == {
        "exchange": "exchange"
    }
    assert report["totals"] == {
        "registry_datasets": 1,
        "converted_datasets": 1,
        "unresolved_datasets": 0,
        "conflict_records": 0,
        "global_conflicts": 0,
    }
    assert report["resolved"][0]["source_document_sha256"] == "b" * 64
    assert report["resolved"][0]["reviewed_type_overrides"] == ["is_open"]


def test_missing_contract_is_absent_and_deterministically_unresolved() -> None:
    registry, plan, collector = _documents()

    candidate, report = compile_provider_native_registry(
        registry,
        plan,
        collector,
        _contract_bundle(contracts=[]),
    )

    assert candidate["datasets"] == []
    assert report["totals"]["converted_datasets"] == 0
    assert report["unresolved"] == [
        {
            "dataset_id": "cn.synthetic.compiler",
            "api_name": "synthetic_compiler",
            "reason_codes": ["missing_upstream_contract"],
        }
    ]
    assert "legacy_wrong.v1" not in render_compilation(candidate, report, kind="bundle")


def test_contract_without_registry_owner_is_a_deterministic_global_conflict() -> None:
    registry, plan, collector = _documents()
    bundle = _contract_bundle()
    extra = deepcopy(bundle["contracts"][0])  # type: ignore[index]
    extra["dataset_id"] = "cn.synthetic.orphan"
    extra["api_name"] = "synthetic_orphan"
    bundle["contracts"].append(extra)  # type: ignore[union-attr]

    candidate, report = compile_provider_native_registry(
        registry,
        plan,
        collector,
        bundle,
    )

    assert len(candidate["datasets"]) == 1
    assert report["conflicts"] == [
        {
            "code": "upstream_contract_without_registry_owner",
            "dataset_id": None,
            "api_name": "synthetic_orphan",
            "details": ["cn.synthetic.orphan"],
        }
    ]
    assert report["totals"]["global_conflicts"] == 1


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda bundle: bundle.update(extra=True), "unknown key"),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                primary_key=["undeclared"]
            ),
            "primary_key.*undeclared",
        ),
        (
            lambda bundle: bundle["contracts"].append(  # type: ignore[union-attr]
                deepcopy(bundle["contracts"][0])  # type: ignore[index]
            ),
            "duplicate dataset_id",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(strategy="unsupported"),
            "response_completeness.strategy",
        ),
        (
            lambda bundle: bundle["contracts"][0].pop(  # type: ignore[index,union-attr]
                "response_completeness"
            ),
            "response_completeness",
        ),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                as_of_format="rfc3339"
            ),
            "yyyymmdd as_of_field",
        ),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                empty_data_policy="allowed"
            ),
            "empty_data_policy.*forbidden",
        ),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                primary_key=["cal_date"]
            ),
            "primary_key.*date_field.*fixed",
        ),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                range_field=None
            ),
            "as_of/range/partition",
        ),
        (
            lambda bundle: bundle["contracts"][0]["fields"][0].update(  # type: ignore[index]
                declared_source_type="int", logical_type="integer"
            ),
            "fixed_field_matches.*text",
        ),
        (
            lambda bundle: bundle["contracts"][0].update(  # type: ignore[index]
                requested_fields=["cal_date", "is_open", "pretrade_date"]
            ),
            "requested_fields.*completeness",
        ),
        (
            lambda bundle: bundle["contracts"][0]["budgets"].update(  # type: ignore[index]
                max_rows_per_attempt=100
            ),
            "max_rows_per_attempt.*max_span_days",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(date_field="undeclared"),
            "date_field.*undeclared",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(request_start_key="missing"),
            "request_start_key",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(fixed_field_matches={"undeclared": "exchange"}),
            "fixed_field_matches.*undeclared",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(fixed_field_matches={"exchange": "missing_param"}),
            "fixed_field_matches.*missing_param",
        ),
        (
            lambda bundle: bundle["contracts"][0][  # type: ignore[index]
                "response_completeness"
            ].update(extra=True),
            "response_completeness.*unknown key",
        ),
    ],
)
def test_bundle_parser_rejects_invalid_or_conflicting_contracts(
    mutator: object,
    message: str,
) -> None:
    bundle = _contract_bundle()
    mutator(bundle)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_upstream_contract_bundle(bundle)


def test_repository_inputs_compile_only_reviewed_contracts_deterministically(
    tmp_path: Path,
) -> None:
    registry = _read_yaml(REGISTRY_PATH)
    plan = _read_yaml(PLAN_PATH)
    collector = _read_yaml(COLLECTOR_CONFIG_PATH)
    contracts = _read_yaml(CONTRACT_PATH)

    first_candidate, first_report = compile_provider_native_registry(
        registry, plan, collector, contracts
    )
    second_candidate, second_report = compile_provider_native_registry(
        deepcopy(registry), deepcopy(plan), deepcopy(collector), deepcopy(contracts)
    )

    assert render_compilation(first_candidate, first_report, kind="bundle") == (
        render_compilation(second_candidate, second_report, kind="bundle")
    )
    assert first_report["totals"]["registry_datasets"] == 114
    assert first_report["totals"]["converted_datasets"] == 3
    assert first_report["totals"]["unresolved_datasets"] == 111
    assert [item["dataset_id"] for item in first_candidate["datasets"]] == [
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar"
    ]

    candidate_path = tmp_path / "candidate.yaml"
    candidate_path.write_text(
        yaml.safe_dump(first_candidate, sort_keys=False), encoding="utf-8"
    )
    loaded = load_dataset_registry(candidate_path)
    trade_cal = loaded.resolve("cn.market.trade_calendar")
    assert trade_cal.schema_major == 2
    assert [field.name for field in trade_cal.fields] == [
        "exchange",
        "cal_date",
        "is_open",
        "pretrade_date",
    ]
    completeness = trade_cal.provider_bindings[0].response_completeness
    assert completeness is not None
    assert completeness.strategy == "one_row_per_calendar_date"


def test_repository_bundle_resolves_stock_basic_and_daily_contracts_deterministically(
    tmp_path: Path,
) -> None:
    registry = _read_yaml(REGISTRY_PATH)
    plan = _read_yaml(PLAN_PATH)
    collector = _read_yaml(COLLECTOR_CONFIG_PATH)
    contracts = _read_yaml(CONTRACT_PATH)

    first_candidate, first_report = compile_provider_native_registry(
        registry, plan, collector, contracts
    )
    second_candidate, second_report = compile_provider_native_registry(
        deepcopy(registry), deepcopy(plan), deepcopy(collector), deepcopy(contracts)
    )

    assert render_compilation(first_candidate, first_report, kind="bundle") == (
        render_compilation(second_candidate, second_report, kind="bundle")
    )
    assert first_candidate == _read_yaml(TARGET_REGISTRY_PATH)
    assert render_compilation(first_candidate, first_report, kind="candidate") == (
        TARGET_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    assert first_report["totals"]["converted_datasets"] == 3
    assert first_report["totals"]["unresolved_datasets"] == 111
    assert [item["dataset_id"] for item in first_candidate["datasets"]] == [
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    ]
    assert first_report["resolved"][0]["request_window_fields"] == ["trade_date"]
    assert first_report["resolved"][1]["request_window_fields"] == []

    candidate_path = tmp_path / "candidate.yaml"
    candidate_path.write_text(
        yaml.safe_dump(first_candidate, sort_keys=False), encoding="utf-8"
    )
    target = load_dataset_registry(candidate_path)
    snapshot = target.resolve("tushare.stock_basic")
    daily = target.resolve("tushare.daily")
    trade_cal = target.resolve("tushare.trade_cal")
    contract_by_dataset = {
        contract["dataset_id"]: contract
        for contract in contracts["contracts"]  # type: ignore[index]
    }
    snapshot_contract = contract_by_dataset[snapshot.dataset_id]
    daily_contract = contract_by_dataset[daily.dataset_id]
    trade_cal_contract = contract_by_dataset[trade_cal.dataset_id]
    snapshot_fields = tuple(
        field["name"] for field in snapshot_contract["fields"]
    )
    daily_fields = tuple(field["name"] for field in daily_contract["fields"])
    assert snapshot.dataset_id == "cn.equity.security_master"
    assert daily.dataset_id == "cn.equity.daily"
    assert tuple(snapshot_contract["requested_fields"]) == snapshot_fields
    assert tuple(daily_contract["requested_fields"]) == daily_fields
    assert snapshot.provider_bindings[0].requested_fields == snapshot_fields
    assert daily.provider_bindings[0].requested_fields == daily_fields
    assert trade_cal_contract["requested_fields"] == []
    assert trade_cal.provider_bindings[0].requested_fields == ()


def test_completeness_window_keys_are_not_provider_parameter_names() -> None:
    registry, plan, collector = _documents()
    bundle = _contract_bundle()
    contract = bundle["contracts"][0]  # type: ignore[index]
    contract["request_template"] = {
        "exchange": "SSE",
        "from_date": "${window.start_date}",
        "to_date": "${window.end_date}",
    }

    candidate, _ = compile_provider_native_registry(
        registry, plan, collector, bundle
    )

    binding = candidate["datasets"][0]["provider_bindings"][0]
    assert binding["response_completeness"]["request_start_key"] == "start_date"
    assert binding["response_completeness"]["request_end_key"] == "end_date"
    assert set(binding["request_template"]) == {"exchange", "from_date", "to_date"}


def test_compiler_accepts_snapshot_and_single_partition_contracts_and_reports_windows() -> None:
    registry, plan, collector = _documents()
    snapshot_bundle = _contract_bundle()
    snapshot = snapshot_bundle["contracts"][0]  # type: ignore[index]
    snapshot["empty_data_policy"] = "allowed"
    snapshot["request_template"] = {}
    snapshot.pop("request_window_policy")
    snapshot["response_completeness"] = {
        "strategy": "unique_primary_key_snapshot",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }
    partition_bundle = _contract_bundle()
    partition = partition_bundle["contracts"][0]  # type: ignore[index]
    partition["empty_data_policy"] = "allowed"
    partition["request_template"] = {
        "cal_date": "${window.cal_date}",
        "exchange": "SSE",
    }
    partition["request_window_policy"] = {
        "required_keys": ["cal_date"],
        "formats": {"cal_date": "yyyymmdd"},
        "range_start_key": "cal_date",
        "range_end_key": "cal_date",
        "max_span_days": 1,
    }
    partition["response_completeness"] = {
        "strategy": "single_partition_unique_primary_key",
        "partition_field": "cal_date",
        "request_partition_key": "cal_date",
        "fixed_field_matches": {"exchange": "exchange"},
        "reject_at_row_limit": True,
    }

    _, calendar_report = compile_provider_native_registry(
        registry, plan, collector, _contract_bundle()
    )
    snapshot_candidate, snapshot_report = compile_provider_native_registry(
        registry, plan, collector, snapshot_bundle
    )
    partition_candidate, partition_report = compile_provider_native_registry(
        registry, plan, collector, partition_bundle
    )

    snapshot_binding = snapshot_candidate["datasets"][0]["provider_bindings"][0]
    partition_binding = partition_candidate["datasets"][0]["provider_bindings"][0]
    assert snapshot_binding["request_window_policy"] is None
    assert snapshot_candidate["datasets"][0]["empty_data_policy"] == "allowed"
    assert snapshot_binding["response_completeness"]["strategy"] == (
        "unique_primary_key_snapshot"
    )
    assert snapshot_binding["response_completeness"]["reject_at_row_limit"] is True
    assert partition_binding["request_window_policy"]["range_start_key"] == "cal_date"
    assert partition_candidate["datasets"][0]["empty_data_policy"] == "allowed"
    assert partition_binding["request_window_policy"]["range_end_key"] == "cal_date"
    assert partition_binding["response_completeness"]["partition_field"] == "cal_date"
    assert partition_binding["response_completeness"]["request_partition_key"] == (
        "cal_date"
    )
    assert calendar_report["resolved"][0]["request_window_fields"] == [
        "start_date",
        "end_date",
    ]
    assert snapshot_report["resolved"][0]["request_window_fields"] == []
    assert partition_report["resolved"][0]["request_window_fields"] == ["cal_date"]


def test_cli_uses_frozen_bundle_and_never_changes_inputs(tmp_path: Path) -> None:
    before = {
        path: _sha256(path)
        for path in (REGISTRY_PATH, PLAN_PATH, COLLECTOR_CONFIG_PATH, CONTRACT_PATH)
    }
    output = tmp_path / "compiled.yaml"
    command = [
        sys.executable,
        str(ROOT / "tools" / "compile_provider_native_registry.py"),
        "--kind",
        "candidate",
        "--output",
        str(output),
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == ""
    assert completed.stderr == ""
    assert len(load_dataset_registry(output).datasets) == 3
    assert before == {path: _sha256(path) for path in before}


def test_task_three_changed_paths_stay_within_the_frozen_write_domain() -> None:
    task_two_freeze = "1b1edae6a37e9ee488b3a41d400e77cf80302d66"
    task_three_freeze = "630211eaa1dc8b9ee16f7377ead5a5716a32eb01"
    approved_paths = {
        "collectors/tushare/collector.py",
        "collectors/tushare/tushare_common.py",
        "config/tushare_upstream_contracts.v1.yaml",
        "config/provider_native_dataset_registry.yaml",
        "tests/test_compile_provider_native_registry.py",
        "tests/test_provider_native_zero_code.py",
        "tests/test_tushare_common.py",
        "tests/test_tushare_sync_daily.py",
        "tests/test_v1_api.py",
        "tests/test_query_service.py",
        "tests/test_dual_dataset_registry_runtime.py",
        "tests/test_reader.py",
        "docs/dataset_registry.md",
    }
    completed = subprocess.run(
        ["git", "diff", "--name-only", task_two_freeze, task_three_freeze],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed_paths = {
        path for path in completed.stdout.splitlines() if path
    }

    assert changed_paths <= approved_paths


def test_renderer_rejects_unknown_output_kind() -> None:
    with pytest.raises(ValueError, match="output kind"):
        render_compilation({}, {}, kind="unknown")
