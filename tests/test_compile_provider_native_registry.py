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
    render_compilation,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "dataset_registry.yaml"
PLAN_PATH = ROOT / "config" / "tushare_capability_plan.yaml"
COLLECTOR_CONFIG_PATH = ROOT / "collectors" / "tushare" / "config.yaml"


def _read_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_documents(
    *,
    fields: str | None = None,
    params: dict[str, object] | None = None,
    include_collector: bool = True,
    activation_state: str = "active",
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    dataset = {
        "dataset_id": "cn.synthetic.compiler",
        "aliases": ["tushare.synthetic_compiler"],
        "domain": "reference",
        "market": "CN",
        "entity_type": "provider_row",
        "data_classification": "objective_factual",
        "schema_version": "1.0.0",
        "fields": [
            {
                "name": "ts_code",
                "logical_type": "text",
                "nullable": False,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
            {
                "name": "trade_date",
                "logical_type": "text",
                "nullable": False,
                "selectable": True,
                "filterable": True,
                "sortable": True,
            },
        ],
        "primary_key": ["ts_code", "trade_date"],
        "default_projection": ["ts_code", "trade_date"],
        "as_of_field": "trade_date",
        "as_of_format": "yyyymmdd",
        "range_field": "trade_date",
        "partition_field": "trade_date",
        "cadence_class": "legacy_daily",
        "timezone": "Asia/Shanghai",
        "freshness_sla_seconds": 86_400,
        "max_page_size": 500,
        "max_lookback_days": 3650,
        "point_in_time": "current_snapshot",
        "backfill_policy": "provider_limited",
        "empty_data_policy": "allowed",
        "required_scope": "market_data",
        "quota_class": "beta_standard",
        "provider_bindings": [
            {
                "provider": "tushare",
                "api_name": "synthetic_compiler",
                "adapter_version": "legacy.v1",
                "read_discriminator_value": "tushare_synthetic_compiler",
                "entitlement_state": "active",
                "activation_state": activation_state,
                "target_tables": ["market_factors"],
            }
        ],
        "read_model_adapter": {
            "adapter_version": "sqlite-read-model.v1",
            "primary_table": "market_factors",
            "fixed_field_filters": [
                {
                    "field": "ts_code",
                    "allowed_values": ["synthetic"],
                }
            ],
        },
    }
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
        "datasets": [dataset],
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
    item: dict[str, object] = {
        "api_name": "synthetic_compiler",
        "frequency": "daily",
        "params": params
        if params is not None
        else {"trade_date": "{trade_date}", "exchange": "SSE"},
        "per_stock": False,
    }
    if fields is not None:
        item["fields"] = fields
    collector = {"priorities": {"P1_eod_daily": [item] if include_collector else []}}
    return registry, plan, collector


def test_compiler_mechanically_converts_one_dataset_without_per_api_code(
    tmp_path: Path,
) -> None:
    registry, plan, collector = _fixture_documents(fields="ts_code,trade_date")

    candidate, report = compile_provider_native_registry(registry, plan, collector)
    output = tmp_path / "candidate.yaml"
    output.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
    compiled = load_dataset_registry(output).resolve("cn.synthetic.compiler")
    binding = compiled.provider_bindings[0]

    assert report["totals"] == {
        "registry_datasets": 1,
        "converted_datasets": 1,
        "unresolved_datasets": 0,
        "conflict_records": 0,
        "global_conflicts": 0,
    }
    assert compiled.cadence_class == "postclose_daily"
    assert compiled.read_model_adapter.storage_kind == "provider_native_rows"
    assert compiled.read_model_adapter.primary_table == "provider_dataset_rows"
    assert compiled.read_model_adapter.row_key_strategy == "primary_key"
    assert binding.adapter_version == "tushare-provider-native.v1"
    assert binding.target_tables == ("provider_dataset_rows",)
    assert dict(binding.request_template) == {
        "exchange": "SSE",
        "trade_date": "${window.trade_date}",
    }
    assert binding.requested_fields == ()
    assert binding.entitlement_state == "active"
    assert binding.activation_state == "active"
    assert binding.max_rows_per_attempt > 0
    assert binding.max_payload_bytes_per_row > 0
    assert binding.max_batch_bytes > 0
    assert binding.max_nesting_depth > 0
    assert report["resolved"][0]["mode"] == "scheduled"
    assert report["resolved"][0]["legacy_fields_hint_count"] == 2
    assert report["resolved"][0]["requested_fields_source"] == "upstream_all"


def test_compiler_preserves_schema_query_and_activation_contracts() -> None:
    registry, plan, collector = _fixture_documents(fields="ts_code,trade_date")
    original = deepcopy(registry)
    preserved_keys = (
        "dataset_id",
        "aliases",
        "domain",
        "market",
        "entity_type",
        "data_classification",
        "schema_version",
        "fields",
        "primary_key",
        "default_projection",
        "as_of_field",
        "as_of_format",
        "range_field",
        "partition_field",
        "timezone",
        "freshness_sla_seconds",
        "max_page_size",
        "max_lookback_days",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
    )

    candidate, _report = compile_provider_native_registry(registry, plan, collector)
    source_dataset = original["datasets"][0]
    candidate_dataset = candidate["datasets"][0]

    assert registry == original
    assert {key: candidate_dataset[key] for key in preserved_keys} == {
        key: source_dataset[key] for key in preserved_keys
    }
    assert (
        candidate_dataset["provider_bindings"][0]["entitlement_state"]
        == (source_dataset["provider_bindings"][0]["entitlement_state"])
    )
    assert (
        candidate_dataset["provider_bindings"][0]["activation_state"]
        == (source_dataset["provider_bindings"][0]["activation_state"])
    )


def test_explicit_row_guard_tightens_generic_default() -> None:
    registry, plan, collector = _fixture_documents(fields="ts_code,trade_date")
    collector["priorities"]["P1_eod_daily"][0]["row_limit_guard"] = 123

    candidate, _report = compile_provider_native_registry(registry, plan, collector)

    assert (
        candidate["datasets"][0]["provider_bindings"][0]["max_rows_per_attempt"] == 123
    )


def test_missing_fields_requests_all_upstream_fields() -> None:
    registry, plan, collector = _fixture_documents(fields=None)

    candidate, report = compile_provider_native_registry(registry, plan, collector)
    binding = candidate["datasets"][0]["provider_bindings"][0]

    assert binding["requested_fields"] == []
    assert report["resolved"][0]["requested_fields_source"] == "upstream_all"


def test_missing_config_is_fail_closed_and_paused_without_guessing() -> None:
    registry, plan, collector = _fixture_documents(
        include_collector=False,
        activation_state="active",
    )

    candidate, report = compile_provider_native_registry(registry, plan, collector)
    dataset = candidate["datasets"][0]
    binding = dataset["provider_bindings"][0]

    assert (
        dataset["read_model_adapter"].get("storage_kind", "typed_columns")
        == "typed_columns"
    )
    assert binding["activation_state"] == "paused"
    assert report["totals"]["converted_datasets"] == 0
    assert report["unresolved"][0]["reason_codes"] == ["missing_collector_config"]


def test_legacy_fields_hint_never_projects_or_blocks_provider_native_payload() -> None:
    registry, plan, collector = _fixture_documents(fields="ts_code,provider_only_field")

    candidate, report = compile_provider_native_registry(registry, plan, collector)
    binding = candidate["datasets"][0]["provider_bindings"][0]

    assert binding["requested_fields"] == []
    assert candidate["datasets"][0]["read_model_adapter"]["primary_table"] == (
        "provider_dataset_rows"
    )
    assert report["totals"]["converted_datasets"] == 1
    assert report["totals"]["unresolved_datasets"] == 0
    assert report["resolved"][0]["legacy_fields_hint_count"] == 2


def test_invalid_placeholder_is_unresolved_instead_of_rewritten() -> None:
    registry, plan, collector = _fixture_documents(
        params={"trade_date": "prefix-{trade_date}"}
    )

    _candidate, report = compile_provider_native_registry(registry, plan, collector)

    assert report["unresolved"][0]["reason_codes"] == ["invalid_param_template"]


def test_repository_inputs_compile_deterministically_and_keep_rt_fut_min_paused(
    tmp_path: Path,
) -> None:
    registry = _read_yaml(REGISTRY_PATH)
    plan = _read_yaml(PLAN_PATH)
    collector = _read_yaml(COLLECTOR_CONFIG_PATH)

    first_candidate, first_report = compile_provider_native_registry(
        registry, plan, collector
    )
    second_candidate, second_report = compile_provider_native_registry(
        deepcopy(registry), deepcopy(plan), deepcopy(collector)
    )

    assert render_compilation(first_candidate, first_report, kind="bundle") == (
        render_compilation(second_candidate, second_report, kind="bundle")
    )
    assert first_report["totals"]["registry_datasets"] == 114
    assert first_report["totals"]["converted_datasets"] == 113
    assert first_report["totals"]["unresolved_datasets"] == 1
    rt_fut = next(
        dataset
        for dataset in first_candidate["datasets"]
        if dataset["dataset_id"] == "cn.future.intraday_5m"
    )
    rt_binding = next(
        binding
        for binding in rt_fut["provider_bindings"]
        if binding["provider"] == "tushare"
    )
    rt_report = next(
        item for item in first_report["unresolved"] if item["api_name"] == "rt_fut_min"
    )

    assert rt_binding["activation_state"] == "paused"
    assert rt_report["reason_codes"] == [
        "additional_provider_binding",
        "missing_collector_config",
    ]

    candidate_path = tmp_path / "candidate.yaml"
    candidate_path.write_text(
        yaml.safe_dump(first_candidate, sort_keys=False), encoding="utf-8"
    )
    loaded = load_dataset_registry(candidate_path)
    assert len(loaded.datasets) == 114
    assert (
        sum(
            dataset.read_model_adapter.storage_kind == "provider_native_rows"
            for dataset in loaded.datasets
        )
        == 113
    )


def test_cli_defaults_to_stdout_and_never_changes_source_registry(
    tmp_path: Path,
) -> None:
    before = {
        path: _sha256(path)
        for path in (REGISTRY_PATH, PLAN_PATH, COLLECTOR_CONFIG_PATH)
    }
    command = [
        sys.executable,
        str(ROOT / "tools" / "compile_provider_native_registry.py"),
        "--kind",
        "report",
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = yaml.safe_load(completed.stdout)
    assert payload["totals"]["registry_datasets"] == 114
    assert completed.stderr == ""
    assert not list(tmp_path.iterdir())
    assert before == {path: _sha256(path) for path in before}


def test_cli_writes_only_an_explicit_non_input_output(tmp_path: Path) -> None:
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
    assert len(load_dataset_registry(output).datasets) == 114

    forbidden = subprocess.run(
        [*command[:-1], str(REGISTRY_PATH)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert forbidden.returncode != 0
    assert "refusing to overwrite an input file" in forbidden.stderr


def test_renderer_rejects_unknown_output_kind() -> None:
    with pytest.raises(ValueError, match="output kind"):
        render_compilation({}, {}, kind="unknown")
