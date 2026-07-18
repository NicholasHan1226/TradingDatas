"""Registry-driven Tushare provider-native collection entry point."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta
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
    policy = binding.request_window_policy
    if policy is not None:
        if tuple(window) != tuple(sorted(window)):
            window = dict(sorted(window.items()))
        if set(window) != set(policy.required_keys):
            raise ValueError(
                "request_window keys must exactly match the registry window policy"
            )
        parsed_dates: dict[str, datetime] = {}
        for key in policy.required_keys:
            value = window[key]
            if policy.formats[key] != "yyyymmdd":
                raise ValueError("unsupported registry request_window format")
            if re.fullmatch(r"[0-9]{8}", value) is None:
                raise ValueError("request_window date must use exact YYYYMMDD format")
            try:
                parsed = datetime.strptime(value, "%Y%m%d")
            except ValueError as exc:
                raise ValueError("request_window date is invalid") from exc
            if parsed.strftime("%Y%m%d") != value:
                raise ValueError("request_window date must use exact YYYYMMDD format")
            parsed_dates[key] = parsed
        start = parsed_dates[policy.range_start_key]
        end = parsed_dates[policy.range_end_key]
        if start > end:
            raise ValueError("request_window range start must not exceed range end")
        if (end - start).days + 1 > policy.max_span_days:
            raise ValueError("request_window range exceeds max_span_days")
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
                "request_start_key": (
                    binding.response_completeness.request_start_key
                ),
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


def _strict_yyyymmdd(value: object) -> datetime:
    if type(value) is not str or re.fullmatch(r"[0-9]{8}", value) is None:
        raise ValueError("provider response date must use exact YYYYMMDD format")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("provider response date is invalid") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError("provider response date must use exact YYYYMMDD format")
    return parsed


def _validate_response_completeness(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    rows: tuple[Mapping[str, Any], ...],
    *,
    request_window: Mapping[str, str],
    resolved_params: Mapping[str, str],
) -> None:
    policy = binding.response_completeness
    if policy is None:
        raise ValueError("provider response completeness contract is missing")

    for row in rows:
        for row_field, request_param in policy.fixed_field_matches.items():
            if row.get(row_field) != resolved_params[request_param]:
                raise ValueError("provider response fixed field does not match request")
    if (
        policy.reject_at_row_limit
        and binding.max_rows_per_attempt is not None
        and len(rows) >= binding.max_rows_per_attempt
    ):
        raise ValueError("provider response reached the declared row limit")

    if policy.strategy == "one_row_per_calendar_date":
        _validate_calendar_dates(
            policy,
            rows,
            request_window=request_window,
        )
    elif policy.strategy == "unique_primary_key_snapshot":
        _validate_unique_primary_keys(dataset, rows)
    elif policy.strategy == "single_partition_unique_primary_key":
        _validate_single_partition(
            dataset,
            policy,
            rows,
            resolved_params=resolved_params,
        )
    else:
        raise ValueError("provider response completeness strategy is unsupported")


def _validate_calendar_dates(
    policy: Any,
    rows: tuple[Mapping[str, Any], ...],
    *,
    request_window: Mapping[str, str],
) -> None:
    if policy.date_field is None:
        raise ValueError("provider response calendar date field is missing")
    if policy.request_start_key is None or policy.request_end_key is None:
        raise ValueError("provider response calendar request keys are missing")

    start = _strict_yyyymmdd(request_window[policy.request_start_key])
    end = _strict_yyyymmdd(request_window[policy.request_end_key])
    expected_dates = {
        (start + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((end - start).days + 1)
    }
    if len(rows) != len(expected_dates):
        raise ValueError("provider response row count is incomplete")

    observed_dates: set[str] = set()
    for row in rows:
        raw_date = row.get(policy.date_field)
        parsed_date = _strict_yyyymmdd(raw_date)
        normalized_date = parsed_date.strftime("%Y%m%d")
        if normalized_date not in expected_dates:
            raise ValueError("provider response date falls outside the request window")
        if normalized_date in observed_dates:
            raise ValueError("provider response contains a duplicate calendar date")
        observed_dates.add(normalized_date)
    if observed_dates != expected_dates:
        raise ValueError("provider response is missing a requested calendar date")


def _usable_primary_key(
    dataset: DatasetDefinition,
    row: Mapping[str, Any],
) -> tuple[tuple[str, str | int | float], ...] | None:
    fields = {field.name: field for field in dataset.fields}
    key: list[tuple[str, str | int | float]] = []
    for field_name in dataset.primary_key:
        if field_name not in row:
            return None
        value = row[field_name]
        if value is None or value == "" or isinstance(value, (dict, list, tuple)):
            return None
        field = fields[field_name]
        if field.logical_type == "text":
            usable = isinstance(value, str)
        elif field.logical_type == "integer":
            usable = isinstance(value, int) and not isinstance(value, bool)
        else:
            usable = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (not isinstance(value, float) or math.isfinite(value))
            )
        if not usable:
            return None
        key.append((field_name, value))
    return tuple(key)


def _validate_unique_primary_keys(
    dataset: DatasetDefinition,
    rows: tuple[Mapping[str, Any], ...],
) -> None:
    observed: set[tuple[tuple[str, str | int | float], ...]] = set()
    for row in rows:
        identity = _usable_primary_key(dataset, row)
        if identity is None:
            continue
        if identity in observed:
            raise ValueError("provider response contains duplicate primary key")
        observed.add(identity)


def _validate_single_partition(
    dataset: DatasetDefinition,
    policy: Any,
    rows: tuple[Mapping[str, Any], ...],
    *,
    resolved_params: Mapping[str, str],
) -> None:
    if policy.partition_field is None or policy.request_partition_key is None:
        raise ValueError("provider response partition contract is incomplete")
    expected = _strict_yyyymmdd(resolved_params[policy.request_partition_key])
    expected_value = expected.strftime("%Y%m%d")
    for row in rows:
        actual = _strict_yyyymmdd(row.get(policy.partition_field))
        if actual.strftime("%Y%m%d") != expected_value:
            raise ValueError("provider response partition does not match request")
    _validate_unique_primary_keys(dataset, rows)


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
        if dataset.empty_data_policy == "forbidden":
            return write_terminal_receipt(
                db_path,
                context=terminal_context,
                status="failed",
                errors=("validation_failed",),
            )
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

    if binding.response_completeness is not None:
        try:
            _validate_response_completeness(
                dataset,
                binding,
                outcome.rows,
                request_window=normalized_window,
                resolved_params=params,
            )
        except ValueError:
            return write_terminal_receipt(
                db_path,
                context=terminal_context,
                status="failed",
                errors=("validation_failed",),
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
