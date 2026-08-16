from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

import dataset_registry as registry_module
from dataset_registry import load_dataset_registry


QUERY_DEFAULTS = {
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
}


def test_in_memory_provider_binding_keeps_ready_compatibility_defaults() -> None:
    binding = registry_module.ProviderBinding(
        provider="tushare",
        api_name="synthetic",
        adapter_version="tushare-provider-native.v1",
        read_discriminator_value="synthetic",
        entitlement_state="active",
        activation_state="active",
        target_tables=("provider_dataset_rows",),
    )

    assert binding.probe_state == "executable"
    assert binding.probe_block_reasons == ()
    assert binding.ingest_contract_state == "ready"
    assert binding.ingest_contract_block_reasons == ()


def _field(
    name: str,
    logical_type: str = "text",
    *,
    nullable: bool = False,
    filterable: bool = True,
    sortable: bool = True,
) -> dict[str, object]:
    return {
        "name": name,
        "logical_type": logical_type,
        "nullable": nullable,
        "selectable": True,
        "filterable": filterable,
        "sortable": sortable,
    }


def generic_dataset(**overrides: object) -> dict[str, object]:
    dataset: dict[str, object] = {
        "dataset_id": "cn.synthetic.native",
        "aliases": ["tushare.synthetic_native"],
        "domain": "reference",
        "market": "CN",
        "entity_type": "provider_row",
        "data_classification": "objective_factual",
        "schema_version": "2.1.0",
        "fields": [
            _field("ts_code"),
            _field("trade_date"),
            _field("close", "float", nullable=True, filterable=False),
            _field("sequence", "integer", nullable=True),
        ],
        "primary_key": ["ts_code", "trade_date"],
        "default_projection": ["ts_code", "trade_date", "close", "sequence"],
        "as_of_field": "trade_date",
        "as_of_format": "yyyymmdd",
        "range_field": "trade_date",
        "partition_field": "trade_date",
        "cadence_class": "postclose",
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
                "api_name": "synthetic_native",
                "adapter_version": "tushare-provider-native.v1",
                "read_discriminator_value": "tushare_synthetic_native",
                "entitlement_state": "active",
                "activation_state": "active",
                "probe_state": "executable",
                "probe_block_reasons": [],
                "ingest_contract_state": "ready",
                "ingest_contract_block_reasons": [],
                "target_tables": ["provider_dataset_rows"],
                "input_fields": [
                    {
                        "name": "start_date",
                        "declared_source_type": "str",
                        "required": False,
                    },
                    {
                        "name": "end_date",
                        "declared_source_type": "str",
                        "required": False,
                    },
                    {
                        "name": "exchange",
                        "declared_source_type": "str",
                        "required": None,
                    },
                ],
                "request_shape": "snapshot_or_date_range",
                "request_template": {
                    "start_date": "${window.start_date}",
                    "end_date": "${window.end_date}",
                    "exchange": "SSE",
                },
                "fanout": {"strategy": "none"},
                "pagination": {"strategy": "none"},
                "request_window_policy": {
                    "required_keys": ["start_date", "end_date"],
                    "formats": {
                        "start_date": "yyyymmdd",
                        "end_date": "yyyymmdd",
                    },
                    "range_start_key": "start_date",
                    "range_end_key": "end_date",
                    "max_span_days": 366,
                },
                "requested_fields": [
                    "ts_code",
                    "trade_date",
                    "close",
                    "sequence",
                ],
                "max_rows_per_attempt": 1000,
                "max_payload_bytes_per_row": 65_536,
                "max_batch_bytes": 4_194_304,
                "max_nesting_depth": 16,
            }
        ],
        "read_model_adapter": {
            "adapter_version": "provider-native-json.v1",
            "primary_table": "provider_dataset_rows",
            "fixed_field_filters": [],
            "storage_kind": "provider_native_rows",
            "row_key_strategy": "primary_key",
        },
    }
    dataset.update(overrides)
    return dataset


def generic_dataset_with_completeness(**overrides: object) -> dict[str, object]:
    dataset = generic_dataset(**overrides)
    dataset["empty_data_policy"] = "forbidden"
    dataset["provider_bindings"][0]["request_template"] = {  # type: ignore[index]
        "from_date": "${window.start_date}",
        "to_date": "${window.end_date}",
        "exchange": "SSE",
    }
    dataset["provider_bindings"][0]["response_completeness"] = {  # type: ignore[index]
        "strategy": "one_row_per_calendar_date",
        "date_field": "trade_date",
        "request_start_key": "start_date",
        "request_end_key": "end_date",
        "fixed_field_matches": {"ts_code": "exchange"},
    }
    return dataset


def write_registry(tmp_path: Path, dataset: dict[str, object]) -> Path:
    path = tmp_path / "dataset_registry.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "query_defaults": QUERY_DEFAULTS,
                "datasets": [dataset],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_generic_registry_materializes_frozen_storage_and_request_contract(
    tmp_path: Path,
) -> None:
    registry = load_dataset_registry(
        write_registry(tmp_path, generic_dataset_with_completeness())
    )
    dataset = registry.resolve("cn.synthetic.native")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")

    assert dataset.schema_major == 2
    assert dataset.read_model_adapter == registry_module.ReadModelAdapter(
        adapter_version="provider-native-json.v1",
        primary_table="provider_dataset_rows",
        fixed_field_filters=(),
        storage_kind="provider_native_rows",
        row_key_strategy="primary_key",
    )
    assert dict(binding.request_template) == {
        "exchange": "SSE",
        "from_date": "${window.start_date}",
        "to_date": "${window.end_date}",
    }
    assert binding.request_shape == "snapshot_or_date_range"
    assert binding.fanout == registry_module.FanoutPolicy(strategy="none")
    assert binding.pagination == registry_module.PaginationPolicy(strategy="none")
    assert binding.request_window_policy is not None
    assert binding.request_window_policy.required_keys == (
        "start_date",
        "end_date",
    )
    assert dict(binding.request_window_policy.formats) == {
        "end_date": "yyyymmdd",
        "start_date": "yyyymmdd",
    }
    assert binding.request_window_policy.range_start_key == "start_date"
    assert binding.request_window_policy.range_end_key == "end_date"
    assert binding.request_window_policy.max_span_days == 366
    assert binding.response_completeness is not None
    assert binding.response_completeness.strategy == "one_row_per_calendar_date"
    assert binding.response_completeness.date_field == "trade_date"
    assert dict(binding.response_completeness.fixed_field_matches) == {
        "ts_code": "exchange"
    }
    assert binding.requested_fields == (
        "ts_code",
        "trade_date",
        "close",
        "sequence",
    )
    assert binding.max_rows_per_attempt == 1000
    assert binding.max_payload_bytes_per_row == 65_536
    assert binding.max_batch_bytes == 4_194_304
    assert binding.max_nesting_depth == 16
    assert binding.input_fields == (
        registry_module.ProviderInputField(
            name="start_date",
            declared_source_type="str",
            required=False,
        ),
        registry_module.ProviderInputField(
            name="end_date",
            declared_source_type="str",
            required=False,
        ),
        registry_module.ProviderInputField(
            name="exchange",
            declared_source_type="str",
            required=None,
        ),
    )
    with pytest.raises(TypeError):
        binding.request_template["end_date"] = "mutated"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        binding.input_fields[0].name = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda binding: binding.pop("input_fields"),
            "missing key.*input_fields",
        ),
        (
            lambda binding: binding.update(input_fields=[]),
            "input_fields.*must not be empty",
        ),
        (
            lambda binding: binding["input_fields"].append(  # type: ignore[index,union-attr]
                deepcopy(binding["input_fields"][0])  # type: ignore[index]
            ),
            "input_fields.*duplicate",
        ),
        (
            lambda binding: binding["input_fields"][0].update(extra=True),  # type: ignore[index,union-attr]
            "unknown key.*input_fields",
        ),
        (
            lambda binding: binding["input_fields"][0].pop("required"),  # type: ignore[index,union-attr]
            "missing key.*required",
        ),
        (
            lambda binding: binding["input_fields"][0].update(  # type: ignore[index,union-attr]
                declared_source_type="string"
            ),
            "declared_source_type.*one of",
        ),
        (
            lambda binding: binding["input_fields"][0].update(required="N"),  # type: ignore[index,union-attr]
            "required.*boolean or null",
        ),
        (
            lambda binding: binding["input_fields"][0].update(required=1),  # type: ignore[index,union-attr]
            "required.*boolean or null",
        ),
    ],
)
def test_registry_input_field_contracts_fail_closed(
    mutator: object,
    message: str,
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    mutator(binding)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_registry_accepts_numeric_leading_payload_field_but_not_parameter(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    dataset["fields"].append(_field("1m", "float", nullable=True))  # type: ignore[union-attr]
    dataset["default_projection"].append("1m")  # type: ignore[union-attr]
    dataset["provider_bindings"][0]["requested_fields"].append("1m")  # type: ignore[index,union-attr]

    loaded = load_dataset_registry(write_registry(tmp_path, dataset))
    assert "1m" in {field.name for field in loaded.datasets[0].fields}

    dataset["provider_bindings"][0]["request_template"]["1m"] = "x"  # type: ignore[index]
    with pytest.raises(ValueError, match="parameter name grammar"):
        load_dataset_registry(write_registry(tmp_path, dataset))


@pytest.mark.parametrize("api_name", ["1api", "a" * 65])
def test_registry_rejects_api_names_outside_provider_parameter_grammar(
    tmp_path: Path,
    api_name: str,
) -> None:
    dataset = generic_dataset()
    dataset["provider_bindings"][0]["api_name"] = api_name  # type: ignore[index]

    with pytest.raises(ValueError, match="parameter name grammar"):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_request_variants_are_frozen_and_scoped_to_static_template_values(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_variants"] = [  # type: ignore[index]
        {"exchange": "SSE"},
        {"exchange": "SZSE"},
    ]

    loaded = load_dataset_registry(write_registry(tmp_path, dataset))
    variants = (
        loaded.resolve("cn.synthetic.native").provider_bindings[0].request_variants
    )

    assert tuple(dict(variant) for variant in variants) == (
        {"exchange": "SSE"},
        {"exchange": "SZSE"},
    )
    with pytest.raises(TypeError):
        variants[0]["exchange"] = "BSE"  # type: ignore[index]


def test_request_variants_preserve_finite_json_scalar_types(tmp_path: Path) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_template"]["limit"] = "100"  # type: ignore[index]
    binding["request_variants"] = [  # type: ignore[index]
        {"exchange": "SSE", "limit": "100"},
        {"exchange": "SZSE", "limit": 100},
        {"exchange": "BSE", "limit": 100.5},
        {"exchange": "OTHER", "limit": False},
    ]

    loaded = load_dataset_registry(write_registry(tmp_path, dataset))
    variants = (
        loaded.resolve("cn.synthetic.native").provider_bindings[0].request_variants
    )

    assert tuple(dict(variant) for variant in variants) == (
        {"exchange": "SSE", "limit": "100"},
        {"exchange": "SZSE", "limit": 100},
        {"exchange": "BSE", "limit": 100.5},
        {"exchange": "OTHER", "limit": False},
    )


@pytest.mark.parametrize("invalid", [None, ["SSE"], {"value": "SSE"}, float("nan")])
def test_request_variants_reject_non_finite_or_non_scalar_values(
    invalid: object,
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_variants"] = [{"exchange": invalid}]  # type: ignore[index]

    with pytest.raises(ValueError, match="request_variants.*finite JSON scalar"):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_request_shape_fanout_and_pagination_materialize_strict_policies(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding.update(  # type: ignore[union-attr]
        request_shape="entity_fanout",
        fanout={
            "strategy": "dataset_field",
            "parameter": "ts_code",
            "source_dataset_id": "cn.equity.security_master",
            "source_field": "ts_code",
            "batch_size": 200,
        },
        pagination={
            "strategy": "offset",
            "limit_parameter": "limit",
            "offset_parameter": "offset",
            "page_size": 5000,
            "max_pages": 20,
        },
    )

    loaded = load_dataset_registry(write_registry(tmp_path, dataset))
    policy = loaded.resolve("cn.synthetic.native").provider_bindings[0]

    assert policy.request_shape == "entity_fanout"
    assert policy.fanout == registry_module.FanoutPolicy(
        strategy="dataset_field",
        parameter="ts_code",
        source_dataset_id="cn.equity.security_master",
        source_field="ts_code",
        batch_size=200,
    )
    assert policy.pagination == registry_module.PaginationPolicy(
        strategy="offset",
        limit_parameter="limit",
        offset_parameter="offset",
        page_size=5000,
        max_pages=20,
    )


def test_dimension_literal_values_fanout_materializes_without_source_dataset(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding.update(  # type: ignore[union-attr]
        request_shape="dimension_fanout",
        fanout={
            "strategy": "literal_values",
            "parameter": "exchange",
            "values": ["SSE", "SZSE"],
            "batch_size": 1,
        },
    )

    loaded = load_dataset_registry(write_registry(tmp_path, dataset))
    policy = loaded.resolve("cn.synthetic.native").provider_bindings[0]

    assert policy.fanout == registry_module.FanoutPolicy(
        strategy="literal_values",
        parameter="exchange",
        values=("SSE", "SZSE"),
        batch_size=1,
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda binding: binding.update(request_shape="unsupported"),
            "request_shape",
        ),
        (
            lambda binding: binding.update(
                request_shape="entity_fanout", fanout={"strategy": "none"}
            ),
            "entity_fanout.*dataset_field",
        ),
        (
            lambda binding: binding.update(
                request_shape="entity_fanout",
                fanout={
                    "strategy": "literal_values",
                    "parameter": "exchange",
                    "values": ["SSE"],
                    "batch_size": 1,
                },
            ),
            "entity_fanout.*dataset_field",
        ),
        (
            lambda binding: binding.update(
                fanout={"strategy": "none", "batch_size": 1}
            ),
            "unknown key.*fanout",
        ),
        (
            lambda binding: binding.update(
                fanout={
                    "strategy": "dataset_field",
                    "parameter": "ts_code",
                    "source_dataset_id": "cn.equity.security_master",
                    "source_field": "ts_code",
                }
            ),
            "missing key.*fanout",
        ),
        (
            lambda binding: binding.update(
                pagination={"strategy": "none", "page_size": 1}
            ),
            "unknown key.*pagination",
        ),
        (
            lambda binding: binding.update(
                pagination={
                    "strategy": "offset",
                    "limit_parameter": "limit",
                    "offset_parameter": "offset",
                    "page_size": 5000,
                }
            ),
            "missing key.*pagination",
        ),
        (
            lambda binding: binding.update(
                pagination={
                    "strategy": "offset",
                    "limit_parameter": "offset",
                    "offset_parameter": "offset",
                    "page_size": 5000,
                    "max_pages": 20,
                }
            ),
            "pagination.*must differ",
        ),
    ],
)
def test_request_shape_fanout_and_pagination_fail_closed(
    mutator: object,
    message: str,
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    mutator(binding)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


@pytest.mark.parametrize(
    ("variants", "message"),
    [
        ([{"missing": "SSE"}], "request_variants.*request_template"),
        ([{"start_date": "20260720"}], "request_variants.*placeholder"),
        ([{"exchange": "SZSE"}], "request_variants.*template default"),
        ([{}, {"exchange": "SSE"}], "request_variants.*empty"),
        ([{"exchange": "SSE"}, {"exchange": "SSE"}], "request_variants.*duplicate"),
    ],
)
def test_request_variants_fail_closed_on_invalid_template_contract(
    variants: list[dict[str, str]],
    message: str,
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_variants"] = variants  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_default_registry_is_provider_native_clean_slate() -> None:
    daily = load_dataset_registry().resolve("cn.equity.daily")
    binding = daily.provider_bindings[0]

    assert daily.read_model_adapter.storage_kind == "provider_native_rows"
    assert daily.read_model_adapter.row_key_strategy == "primary_key"
    assert dict(binding.request_template) == {"trade_date": "${window.trade_date}"}
    assert binding.request_shape == "snapshot_or_date_range"
    assert binding.fanout == registry_module.FanoutPolicy(strategy="none")
    assert binding.pagination == registry_module.PaginationPolicy(strategy="none")
    assert binding.requested_fields
    assert binding.max_rows_per_attempt == 6000


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda dataset: dataset["read_model_adapter"].update(  # type: ignore[union-attr]
                storage_kind="typed_columns"
            ),
            "storage_kind",
        ),
        (
            lambda dataset: dataset["read_model_adapter"].update(  # type: ignore[union-attr]
                primary_table="facts_quotes"
            ),
            "primary_table.*provider_dataset_rows",
        ),
        (
            lambda dataset: dataset["read_model_adapter"].update(  # type: ignore[union-attr]
                fixed_field_filters=[
                    {"field": "provider", "allowed_values": ["tushare"]}
                ]
            ),
            "fixed_field_filters must be empty",
        ),
        (
            lambda dataset: dataset["provider_bindings"][0].update(  # type: ignore[index,union-attr]
                target_tables=["facts_quotes"]
            ),
            "target_tables must be exactly provider_dataset_rows",
        ),
    ],
)
def test_clean_slate_registry_rejects_legacy_storage_routes(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    dataset = generic_dataset()
    mutator(dataset)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item["read_model_adapter"].update(  # type: ignore[union-attr]
                storage_kind="mystery"
            ),
            "storage_kind",
        ),
        (
            lambda item: item["read_model_adapter"].update(  # type: ignore[union-attr]
                primary_table="market_factors"
            ),
            "provider_dataset_rows",
        ),
        (
            lambda item: item["read_model_adapter"].update(  # type: ignore[union-attr]
                row_key_strategy="payload_hash"
            ),
            "current_snapshot.*primary_key",
        ),
        (
            lambda item: item.update(point_in_time="append_only"),
            "append_only.*payload_hash",
        ),
        (
            lambda item: item.update(point_in_time="unsupported"),
            "unsupported",
        ),
        (
            lambda item: item["provider_bindings"][0].pop(  # type: ignore[index,union-attr]
                "request_template"
            ),
            "request_template",
        ),
        (
            lambda item: item["provider_bindings"][0].pop(  # type: ignore[index,union-attr]
                "request_shape"
            ),
            "request_shape",
        ),
        (
            lambda item: item["provider_bindings"][0].pop(  # type: ignore[index,union-attr]
                "fanout"
            ),
            "fanout",
        ),
        (
            lambda item: item["provider_bindings"][0].pop(  # type: ignore[index,union-attr]
                "pagination"
            ),
            "pagination",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index,union-attr]
                max_rows_per_attempt=0
            ),
            "max_rows_per_attempt",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index,union-attr]
                request_template={"date": "${window.trade-date}"}
            ),
            "request_template",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index,union-attr]
                requested_fields=["ts_code", "bad.field"]
            ),
            "requested_fields",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "request_window_policy"
            ].update(required_keys=["start_date"]),
            "required_keys",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "request_window_policy"
            ].update(max_span_days=0),
            "max_span_days",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "response_completeness"
            ].update(strategy="unsupported"),
            "strategy",
        ),
        (
            lambda item: item.update(as_of_format="rfc3339"),
            "yyyymmdd as_of_field",
        ),
        (
            lambda item: item.update(empty_data_policy="allowed"),
            "empty_data_policy.*forbidden",
        ),
        (
            lambda item: item.update(primary_key=["trade_date"]),
            "primary_key.*date_field.*fixed",
        ),
        (
            lambda item: item.update(range_field=None),
            "as_of/range/partition",
        ),
        (
            lambda item: item["fields"][0].update(logical_type="float"),  # type: ignore[index]
            "fixed_field_matches.*text",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index]
                requested_fields=["trade_date", "close", "sequence"]
            ),
            "requested_fields.*completeness",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index]
                max_rows_per_attempt=100
            ),
            "max_rows_per_attempt.*max_span_days",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "response_completeness"
            ].update(date_field="undeclared"),
            "date_field.*undeclared",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "response_completeness"
            ].update(request_start_key="missing"),
            "request_start_key",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "response_completeness"
            ].update(fixed_field_matches={"ts_code": "missing"}),
            "fixed_field_matches.*missing",
        ),
        (
            lambda item: item["provider_bindings"][0][  # type: ignore[index]
                "response_completeness"
            ].update(extra=True),
            "unknown key.*response_completeness",
        ),
        (
            lambda item: item.update(
                fields=[
                    *item["fields"],  # type: ignore[index]
                    _field("bad.field"),
                ]
            ),
            "field name",
        ),
        (
            lambda item: item.update(schema_version="2"),
            "schema_version",
        ),
        (
            lambda item: item["fields"][0].update(nullable=True),  # type: ignore[index]
            "primary_key fields must not be nullable",
        ),
    ],
)
def test_generic_registry_rejects_invalid_contracts(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    dataset = deepcopy(generic_dataset_with_completeness())
    mutator(dataset)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_append_only_requires_and_accepts_payload_identity(tmp_path: Path) -> None:
    dataset = generic_dataset(point_in_time="append_only")
    dataset["read_model_adapter"]["row_key_strategy"] = "payload_hash"  # type: ignore[index]

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]

    assert loaded.point_in_time == "append_only"
    assert loaded.read_model_adapter.row_key_strategy == "payload_hash"


def test_catalog_only_append_only_dataset_can_omit_unverified_primary_key(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset(
        point_in_time="append_only",
        primary_key=[],
    )
    dataset["read_model_adapter"]["row_key_strategy"] = "payload_hash"  # type: ignore[index]

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]

    assert loaded.primary_key == ()
    assert loaded.default_projection


def test_current_snapshot_dataset_cannot_omit_primary_key(tmp_path: Path) -> None:
    dataset = generic_dataset(primary_key=[])

    with pytest.raises(ValueError, match="current_snapshot.*non-empty primary_key"):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_known_future_window_is_reserved_for_trade_calendar(tmp_path: Path) -> None:
    dataset = generic_dataset(known_future_horizon_days=1)

    with pytest.raises(ValueError, match="requires entity_type trade_calendar"):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_existing_provider_native_contract_can_omit_response_completeness(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]

    assert loaded.provider_bindings[0].response_completeness is None


def test_response_completeness_policy_keeps_reject_at_row_limit_default() -> None:
    policy = registry_module.ResponseCompletenessPolicy(
        strategy="one_row_per_calendar_date",
        date_field="trade_date",
        request_start_key="start_date",
        request_end_key="end_date",
        fixed_field_matches={"ts_code": "exchange"},
    )

    assert policy.reject_at_row_limit is False


def test_generic_registry_materializes_snapshot_and_single_partition_completeness(
    tmp_path: Path,
) -> None:
    snapshot = generic_dataset()
    snapshot["empty_data_policy"] = "allowed"
    snapshot_binding = snapshot["provider_bindings"][0]  # type: ignore[index]
    snapshot_binding["request_template"] = {}  # type: ignore[index]
    snapshot_binding.pop("request_window_policy")  # type: ignore[index]
    snapshot_binding["response_completeness"] = {  # type: ignore[index]
        "strategy": "unique_primary_key_snapshot",
        "snapshot_field": "trade_date",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }

    partition = generic_dataset()
    partition["empty_data_policy"] = "allowed"
    partition_binding = partition["provider_bindings"][0]  # type: ignore[index]
    partition_binding["request_template"] = {  # type: ignore[index]
        "trade_date": "${window.trade_date}",
    }
    partition_binding["request_window_policy"] = {  # type: ignore[index]
        "required_keys": ["trade_date"],
        "formats": {"trade_date": "yyyymmdd"},
        "range_start_key": "trade_date",
        "range_end_key": "trade_date",
        "max_span_days": 1,
    }
    partition_binding["response_completeness"] = {  # type: ignore[index]
        "strategy": "single_partition_unique_primary_key",
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }

    snapshot_loaded = load_dataset_registry(write_registry(tmp_path, snapshot))
    snapshot_policy = snapshot_loaded.datasets[0].provider_bindings[0]
    partition_loaded = load_dataset_registry(write_registry(tmp_path, partition))
    partition_policy = partition_loaded.datasets[0].provider_bindings[0]

    assert snapshot_policy.request_window_policy is None
    assert snapshot_loaded.datasets[0].empty_data_policy == "allowed"
    assert snapshot_policy.response_completeness is not None
    assert (
        snapshot_policy.response_completeness.strategy == "unique_primary_key_snapshot"
    )
    assert snapshot_policy.response_completeness.reject_at_row_limit is True
    assert snapshot_policy.response_completeness.snapshot_field == "trade_date"
    assert partition_policy.request_window_policy is not None
    assert partition_loaded.datasets[0].empty_data_policy == "allowed"
    assert partition_policy.request_window_policy.range_start_key == "trade_date"
    assert partition_policy.request_window_policy.range_end_key == "trade_date"
    assert partition_policy.response_completeness is not None
    assert partition_policy.response_completeness.partition_field == "trade_date"
    assert partition_policy.response_completeness.request_partition_key == "trade_date"


def test_windowed_primary_key_completeness_requires_event_source_fanout(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset(
        fields=[
            _field("src"),
            _field("pub_time"),
            _field("title"),
        ],
        primary_key=["src", "pub_time", "title"],
        default_projection=["src", "pub_time", "title"],
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_shape"] = "event_or_intraday_window"
    binding["request_template"] = {
        "start_time": "${window.start_time}",
        "end_time": "${window.end_time}",
    }
    binding["request_window_policy"] = {
        "required_keys": ["start_time", "end_time"],
        "formats": {
            "start_time": "local_datetime_seconds",
            "end_time": "local_datetime_seconds",
        },
        "range_start_key": "start_time",
        "range_end_key": "end_time",
        "max_span_days": 1,
    }
    binding["fanout"] = {
        "strategy": "literal_values",
        "parameter": "src",
        "values": ["source_a", "source_b"],
        "batch_size": 1,
    }
    binding["requested_fields"] = ["src", "pub_time", "title"]
    binding["response_completeness"] = {
        "strategy": "windowed_unique_primary_key",
        "date_field": "pub_time",
        "request_start_key": "start_time",
        "request_end_key": "end_time",
        "fanout_field": "src",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]
    policy = loaded.provider_bindings[0].response_completeness

    assert policy is not None
    assert policy.strategy == "windowed_unique_primary_key"
    assert policy.date_field == "pub_time"
    assert policy.fanout_field == "src"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda binding: binding["response_completeness"].update(  # type: ignore[index]
                fanout_field="missing"
            ),
            "window fields are undeclared",
        ),
        (
            lambda binding: binding.update(fanout={"strategy": "none"}),
            "windowed strategy requires fanout",
        ),
    ],
)
def test_windowed_primary_key_completeness_rejects_invalid_contract(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    dataset = generic_dataset(
        fields=[_field("src"), _field("pub_time"), _field("title")],
        primary_key=["src", "pub_time", "title"],
        default_projection=["src", "pub_time", "title"],
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding.update(
        request_shape="event_or_intraday_window",
        request_template={
            "start_time": "${window.start_time}",
            "end_time": "${window.end_time}",
        },
        request_window_policy={
            "required_keys": ["start_time", "end_time"],
            "formats": {
                "start_time": "local_datetime_seconds",
                "end_time": "local_datetime_seconds",
            },
            "range_start_key": "start_time",
            "range_end_key": "end_time",
            "max_span_days": 1,
        },
        fanout={
            "strategy": "literal_values",
            "parameter": "src",
            "values": ["source_a"],
            "batch_size": 1,
        },
        requested_fields=["src", "pub_time", "title"],
        response_completeness={
            "strategy": "windowed_unique_primary_key",
            "date_field": "pub_time",
            "request_start_key": "start_time",
            "request_end_key": "end_time",
            "fanout_field": "src",
            "fixed_field_matches": {},
            "reject_at_row_limit": True,
        },
    )
    mutator(binding)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


def test_event_stream_completeness_materializes_without_fanout(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset(
        fields=[_field("datetime"), _field("title"), _field("content")],
        primary_key=["datetime", "title"],
        default_projection=["datetime", "title", "content"],
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding.update(
        request_shape="event_or_intraday_window",
        request_template={
            "start_time": "${window.start_time}",
            "end_time": "${window.end_time}",
        },
        request_window_policy={
            "required_keys": ["start_time", "end_time"],
            "formats": {
                "start_time": "local_datetime_seconds",
                "end_time": "local_datetime_seconds",
            },
            "range_start_key": "start_time",
            "range_end_key": "end_time",
            "max_span_days": 1,
        },
        fanout={"strategy": "none"},
        requested_fields=["datetime", "title", "content"],
        response_completeness={
            "strategy": "event_stream_unique_primary_key",
            "date_field": "datetime",
            "request_start_key": "start_time",
            "request_end_key": "end_time",
            "fixed_field_matches": {},
            "reject_at_row_limit": True,
        },
    )

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]
    policy = loaded.provider_bindings[0].response_completeness

    assert policy is not None
    assert policy.strategy == "event_stream_unique_primary_key"
    assert policy.date_field == "datetime"
    assert policy.fanout_field is None
    assert policy.reject_at_row_limit is True


def test_event_stream_completeness_rejects_non_datetime_window(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset(
        fields=[_field("datetime"), _field("title")],
        primary_key=["datetime", "title"],
        default_projection=["datetime", "title"],
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
    )
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding.update(
        request_shape="event_or_intraday_window",
        request_template={"trade_date": "${window.trade_date}"},
        request_window_policy={
            "required_keys": ["trade_date"],
            "formats": {"trade_date": "yyyymmdd"},
            "range_start_key": "trade_date",
            "range_end_key": "trade_date",
            "max_span_days": 1,
        },
        fanout={"strategy": "none"},
        requested_fields=["datetime", "title"],
        response_completeness={
            "strategy": "event_stream_unique_primary_key",
            "date_field": "datetime",
            "request_start_key": "trade_date",
            "request_end_key": "trade_date",
            "fixed_field_matches": {},
            "reject_at_row_limit": True,
        },
    )

    with pytest.raises(ValueError, match="local_datetime_seconds"):
        load_dataset_registry(write_registry(tmp_path, dataset))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item["provider_bindings"][0]["response_completeness"].update(  # type: ignore[index]
                strategy="unsupported"
            ),
            "strategy",
        ),
        (
            lambda item: item["provider_bindings"][0]["response_completeness"].update(  # type: ignore[index]
                date_field="trade_date"
            ),
            "unknown key",
        ),
        (
            lambda item: item["provider_bindings"][0]["response_completeness"].pop(  # type: ignore[index]
                "reject_at_row_limit"
            ),
            "missing key",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index]
                request_template={"trade_date": "${window.trade_date}"},
                request_window_policy={
                    "required_keys": ["trade_date"],
                    "formats": {"trade_date": "yyyymmdd"},
                    "range_start_key": "trade_date",
                    "range_end_key": "trade_date",
                    "max_span_days": 1,
                },
            ),
            "unique_primary_key_snapshot",
        ),
        (
            lambda item: item["provider_bindings"][0]["response_completeness"].update(  # type: ignore[index]
                snapshot_field="missing"
            ),
            "snapshot_field.*undeclared",
        ),
        (
            lambda item: item["provider_bindings"][0]["response_completeness"].update(  # type: ignore[index]
                reject_at_row_limit="true"
            ),
            "boolean",
        ),
    ],
)
def test_snapshot_completeness_rejects_invalid_shapes(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    dataset = generic_dataset()
    dataset["empty_data_policy"] = "forbidden"
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_template"] = {}
    binding.pop("request_window_policy")
    binding["response_completeness"] = {
        "strategy": "unique_primary_key_snapshot",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }
    mutator(dataset)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item["provider_bindings"][0].pop("request_window_policy"),  # type: ignore[index]
            "requires request_window_policy",
        ),
        (
            lambda item: item.update(primary_key=["ts_code"]),
            "partition_field.*primary_key",
        ),
        (
            lambda item: item["provider_bindings"][0].update(  # type: ignore[index]
                requested_fields=["ts_code"]
            ),
            "requested_fields.*completeness",
        ),
    ],
)
def test_partition_completeness_rejects_missing_identity_contract_fields(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    dataset = generic_dataset()
    dataset["empty_data_policy"] = "forbidden"
    binding = dataset["provider_bindings"][0]  # type: ignore[index]
    binding["request_template"] = {"trade_date": "${window.trade_date}"}
    binding["request_window_policy"] = {
        "required_keys": ["trade_date"],
        "formats": {"trade_date": "yyyymmdd"},
        "range_start_key": "trade_date",
        "range_end_key": "trade_date",
        "max_span_days": 1,
    }
    binding["response_completeness"] = {
        "strategy": "single_partition_unique_primary_key",
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }
    mutator(dataset)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_dataset_registry(write_registry(tmp_path, dataset))
