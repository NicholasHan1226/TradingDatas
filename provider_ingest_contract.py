"""Shared hash contract binding dataset ingest behavior to its transport profile."""

from __future__ import annotations

import hashlib
import json

from dataset_registry import DatasetDefinition, ProviderBinding
from provider_transport import provider_transport_profile


def provider_ingest_config_hash(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
) -> str:
    """Hash every registry and transport field that changes ingest behavior."""

    transport_profile = provider_transport_profile(binding.provider)
    payload = {
        "dataset_id": dataset.dataset_id,
        "schema_version": dataset.schema_version,
        "fields": [
            {
                "filterable": field.filterable,
                "logical_type": field.logical_type,
                "name": field.name,
                "nullable": field.nullable,
                "selectable": field.selectable,
                "sortable": field.sortable,
            }
            for field in dataset.fields
        ],
        "primary_key": list(dataset.primary_key),
        "as_of_field": dataset.as_of_field,
        "as_of_format": dataset.as_of_format,
        "partition_field": dataset.partition_field,
        "point_in_time": dataset.point_in_time,
        "empty_data_policy": dataset.empty_data_policy,
        "read_model_adapter": {
            "adapter_version": dataset.read_model_adapter.adapter_version,
            "primary_table": dataset.read_model_adapter.primary_table,
            "fixed_field_filters": [
                {
                    "field": item.field,
                    "allowed_values": list(item.allowed_values),
                }
                for item in dataset.read_model_adapter.fixed_field_filters
            ],
            "storage_kind": dataset.read_model_adapter.storage_kind,
            "row_key_strategy": dataset.read_model_adapter.row_key_strategy,
        },
        "provider": binding.provider,
        "api_name": binding.api_name,
        "adapter_version": binding.adapter_version,
        "read_discriminator_value": binding.read_discriminator_value,
        "target_tables": list(binding.target_tables),
        "transport_profile": transport_profile,
        "entitlement_state": binding.entitlement_state,
        "activation_state": binding.activation_state,
        "request_shape": binding.request_shape,
        "request_template": dict(binding.request_template),
        "request_variants": [dict(variant) for variant in binding.request_variants],
        "fanout": (
            None
            if binding.fanout is None
            else {
                "strategy": binding.fanout.strategy,
                "parameter": binding.fanout.parameter,
                "source_dataset_id": binding.fanout.source_dataset_id,
                "source_field": binding.fanout.source_field,
                "batch_size": binding.fanout.batch_size,
            }
        ),
        "pagination": (
            None
            if binding.pagination is None
            else {
                "strategy": binding.pagination.strategy,
                "limit_parameter": binding.pagination.limit_parameter,
                "offset_parameter": binding.pagination.offset_parameter,
                "page_size": binding.pagination.page_size,
                "max_pages": binding.pagination.max_pages,
            }
        ),
        "request_window_policy": (
            None
            if binding.request_window_policy is None
            else {
                "required_keys": list(binding.request_window_policy.required_keys),
                "formats": dict(binding.request_window_policy.formats),
                "range_start_key": binding.request_window_policy.range_start_key,
                "range_end_key": binding.request_window_policy.range_end_key,
                "max_span_days": binding.request_window_policy.max_span_days,
            }
        ),
        "response_completeness": (
            None
            if binding.response_completeness is None
            else {
                "strategy": binding.response_completeness.strategy,
                "date_field": binding.response_completeness.date_field,
                "request_start_key": binding.response_completeness.request_start_key,
                "request_end_key": binding.response_completeness.request_end_key,
                "partition_field": binding.response_completeness.partition_field,
                "request_partition_key": (
                    binding.response_completeness.request_partition_key
                ),
                "fixed_field_matches": dict(
                    binding.response_completeness.fixed_field_matches
                ),
                "reject_at_row_limit": (
                    binding.response_completeness.reject_at_row_limit
                ),
            }
        ),
        "requested_fields": list(binding.requested_fields),
        "budgets": {
            "max_batch_bytes": binding.max_batch_bytes,
            "max_nesting_depth": binding.max_nesting_depth,
            "max_payload_bytes_per_row": binding.max_payload_bytes_per_row,
            "max_rows_per_attempt": binding.max_rows_per_attempt,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
