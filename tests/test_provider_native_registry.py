from __future__ import annotations

from copy import deepcopy
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
                "target_tables": ["provider_dataset_rows"],
                "request_template": {
                    "start_date": "${window.start_date}",
                    "end_date": "${window.end_date}",
                    "exchange": "SSE",
                },
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
    with pytest.raises(TypeError):
        binding.request_template["end_date"] = "mutated"  # type: ignore[index]


def test_existing_registry_remains_legacy_typed_by_default() -> None:
    daily = load_dataset_registry().resolve("cn.equity.daily")
    binding = daily.provider_bindings[0]

    assert daily.read_model_adapter.storage_kind == "typed_columns"
    assert daily.read_model_adapter.row_key_strategy is None
    assert dict(binding.request_template) == {}
    assert binding.requested_fields == ()
    assert binding.max_rows_per_attempt is None
    assert binding.max_payload_bytes_per_row is None
    assert binding.max_batch_bytes is None
    assert binding.max_nesting_depth is None


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


def test_existing_provider_native_contract_can_omit_response_completeness(
    tmp_path: Path,
) -> None:
    dataset = generic_dataset()

    loaded = load_dataset_registry(write_registry(tmp_path, dataset)).datasets[0]

    assert loaded.provider_bindings[0].response_completeness is None
