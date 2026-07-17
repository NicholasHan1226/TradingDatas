"""Registry-driven Tushare provider-native collection entry point."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Protocol

from collectors.tushare.tushare_common import ProviderCallOutcome
from dataset_registry import DatasetDefinition, DatasetRegistry, ProviderBinding
from storage.ingest_receipts import IngestContext, IngestResult, write_terminal_receipt
from storage.provider_dataset_rows import (
    ProviderNativeAdmissionError,
    ingest_provider_native_rows,
    matches_declared_provider_time,
    validate_provider_dataset_store,
)


_WINDOW_PLACEHOLDER = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_MAX_WINDOW_VALUE_BYTES = 1024
_PROVIDER_ERROR_CODES = frozenset(
    {"permission_denied", "provider_error", "rate_limited"}
)


class _Collector(Protocol):
    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, str],
        fields: str | None = None,
    ) -> ProviderCallOutcome: ...


def _resolved_request(
    binding: ProviderBinding,
    request_window: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(request_window, Mapping):
        raise TypeError("request_window must be a mapping")
    window: dict[str, str] = {}
    for key, value in request_window.items():
        if (
            not isinstance(key, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key) is None
        ):
            raise ValueError("request_window keys must use the safe identifier grammar")
        if not isinstance(value, str) or not value:
            raise ValueError("request_window values must be non-empty strings")
        if len(value.encode("utf-8")) > _MAX_WINDOW_VALUE_BYTES:
            raise ValueError("request_window value exceeds the public string budget")
        if any(ord(character) < 32 for character in value):
            raise ValueError(
                "request_window values must not contain control characters"
            )
        window[key] = value

    referenced = {
        match.group(1)
        for value in binding.request_template.values()
        if (match := _WINDOW_PLACEHOLDER.fullmatch(value)) is not None
    }
    if set(window) != referenced:
        raise ValueError(
            "request_window must contain exactly the registry template window keys"
        )
    params = {
        key: (
            window[match.group(1)]
            if (match := _WINDOW_PLACEHOLDER.fullmatch(value)) is not None
            else value
        )
        for key, value in binding.request_template.items()
    }
    return dict(sorted(window.items())), dict(sorted(params.items()))


def _config_hash(dataset: DatasetDefinition, binding: ProviderBinding) -> str:
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
        "partition_field": dataset.partition_field,
        "point_in_time": dataset.point_in_time,
        "storage_kind": dataset.read_model_adapter.storage_kind,
        "row_key_strategy": dataset.read_model_adapter.row_key_strategy,
        "provider": binding.provider,
        "api_name": binding.api_name,
        "adapter_version": binding.adapter_version,
        "entitlement_state": binding.entitlement_state,
        "activation_state": binding.activation_state,
        "request_template": dict(binding.request_template),
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


def _matching_values(
    dataset: DatasetDefinition,
    rows: tuple[Mapping[str, Any], ...],
    field_name: str | None,
) -> list[str | int | float]:
    if field_name is None:
        return []
    field = next(field for field in dataset.fields if field.name == field_name)
    values: list[str | int | float] = []
    for row in rows:
        value = row.get(field_name)
        if field_name == dataset.as_of_field and not matches_declared_provider_time(
            value,
            dataset.as_of_format or "",
        ):
            continue
        if field.logical_type == "text" and isinstance(value, str):
            values.append(value)
        elif (
            field.logical_type == "integer"
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            values.append(value)
        elif (
            field.logical_type == "float"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        ):
            values.append(value)
    return values


def _data_through(
    dataset: DatasetDefinition,
    outcome: ProviderCallOutcome,
    started_at: str,
) -> str | None:
    for field_name in (dataset.as_of_field, dataset.partition_field):
        values = _matching_values(dataset, outcome.rows, field_name)
        if values:
            try:
                return str(max(values))
            except TypeError:
                continue
    if dataset.as_of_field is None and dataset.partition_field is None:
        return started_at
    return None


def _context(
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    request_window: Mapping[str, str],
    attempt_id: str,
    started_at: str,
    data_through: str | None,
) -> IngestContext:
    return IngestContext(
        attempt_id=attempt_id,
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window=request_window,
        config_hash=_config_hash(dataset, binding),
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=data_through,
    )


def collect_provider_native_dataset(
    db_path: Path,
    *,
    registry: DatasetRegistry,
    collector: _Collector,
    dataset_id: str,
    request_window: Mapping[str, str],
    attempt_id: str,
    started_at: str,
) -> IngestResult:
    """Resolve one Tushare dataset from registry and persist its typed outcome."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("dataset_id must be a non-empty string")
    dataset = registry.resolve(dataset_id)
    if dataset.dataset_id != dataset_id:
        raise ValueError("collection requires the canonical dataset_id, not an alias")
    binding = registry.provider_binding(dataset.dataset_id, "tushare")
    if dataset.read_model_adapter.storage_kind != "provider_native_rows":
        raise ValueError("dataset is not configured for provider-native collection")
    if binding.entitlement_state != "active" or binding.activation_state != "active":
        raise ValueError("dataset binding is not entitled and active")
    normalized_window, params = _resolved_request(binding, request_window)

    # Validate caller-owned attempt identity and start time before any provider call.
    terminal_context = _context(
        dataset=dataset,
        binding=binding,
        request_window=normalized_window,
        attempt_id=attempt_id,
        started_at=started_at,
        data_through=None,
    )
    validate_provider_dataset_store(db_path)
    if not callable(getattr(collector, "collect_outcome", None)):
        raise TypeError("collector must provide collect_outcome")
    requested_fields = (
        ",".join(binding.requested_fields) if binding.requested_fields else None
    )
    outcome = collector.collect_outcome(binding.api_name, params, requested_fields)
    if not isinstance(outcome, ProviderCallOutcome):
        raise TypeError("collector returned an invalid provider outcome")
    outcome.validate_invariants()

    if outcome.state == "empty":
        return write_terminal_receipt(
            db_path,
            context=terminal_context,
            status="empty",
            errors=(),
        )
    if outcome.state == "failed":
        error_code = (
            outcome.error_code
            if outcome.error_code in _PROVIDER_ERROR_CODES
            else "provider_error"
        )
        return write_terminal_receipt(
            db_path,
            context=terminal_context,
            status="failed",
            errors=(error_code,),
        )

    success_context = _context(
        dataset=dataset,
        binding=binding,
        request_window=normalized_window,
        attempt_id=attempt_id,
        started_at=started_at,
        data_through=_data_through(dataset, outcome, started_at),
    )
    try:
        return ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=outcome.mutable_rows(),
            context=success_context,
        )
    except ProviderNativeAdmissionError as exc:
        return write_terminal_receipt(
            db_path,
            context=terminal_context,
            status="failed",
            errors=(exc.error_code,),
        )
    except Exception as primary_error:
        try:
            return write_terminal_receipt(
                db_path,
                context=terminal_context,
                status="failed",
                errors=("storage_failed",),
            )
        except Exception:
            raise primary_error
