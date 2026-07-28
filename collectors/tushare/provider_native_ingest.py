"""Registry-driven Tushare provider-native collection entry point."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from collectors.tushare.tushare_common import (
    ProviderCallOutcome,
    SensitiveScanBudget,
)
from dataset_registry import (
    DatasetDefinition,
    DatasetRegistry,
    PaginationPolicy,
    ProviderBinding,
    RequestScalar,
    normalize_request_window,
)
from provider_ingest_contract import provider_ingest_config_hash
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    IngestResult,
    ProviderRequestIdentity,
    make_provider_call_attempt_id,
    write_terminal_receipt,
)
from storage.provider_dataset_rows import (
    ProviderNativeAdmissionError,
    ingest_provider_native_rows,
    matches_declared_provider_time,
    validate_provider_dataset_store,
)
from storage.receipt_projection import (
    RuntimeProjectionError,
    validated_success_receipt_ids,
)
from storage.sqlite_authority_lock import (
    SqliteAuthorityLockError,
    sqlite_authority_lock,
)


_WINDOW_PLACEHOLDER = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_MAX_WINDOW_VALUE_BYTES = 1024
_PROVIDER_SCAN_FIELD_HEADROOM = 16
_PROVIDER_SCAN_FIXED_NODE_HEADROOM = 4_096
# Must stay in lock-step with the compiler: node budgeting, rather than an
# arbitrary narrow schema ceiling, is the final transport safety bound.
_PROVIDER_SCAN_ABSOLUTE_MAX_FIELDS = 512
_PROVIDER_SCAN_ABSOLUTE_MAX_NODES = 2_000_000
_PROVIDER_SCAN_ENVELOPE_DEPTH = 4
_PROVIDER_SCAN_ABSOLUTE_MAX_DEPTH = 64
_PROVIDER_ERROR_CODES = frozenset(
    {
        "permission_denied",
        "provider_error",
        "rate_limited",
        "resource_budget",
    }
)
_RETRYABLE_PROVIDER_ERRORS = frozenset({"rate_limited"})


@dataclass(frozen=True)
class RetrySettings:
    """Bounded provider retry policy supplied by the trusted scheduler."""

    max_attempts: int = 1
    base_delay_seconds: int = 0
    max_delay_seconds: int = 0
    jitter_seconds: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_attempts",
            "base_delay_seconds",
            "max_delay_seconds",
            "jitter_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name == "max_attempts" else 0):
                raise ValueError(f"{name} is invalid")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("retry delay is invalid")


@dataclass(frozen=True)
class FanoutBatch:
    """One deterministic provider parameter batch derived from SQLite facts."""

    parameter: str | None
    values: tuple[RequestScalar, ...]

    def __post_init__(self) -> None:
        if self.parameter is None:
            if self.values:
                raise ValueError("fanout=none cannot carry values")
            return
        if not self.parameter or not self.values:
            raise ValueError("dataset-field fanout requires a parameter and values")


@dataclass(frozen=True)
class ProviderCall:
    """One real provider call/response pair for a future SQLite transaction."""

    identity: ProviderRequestIdentity
    outcome: ProviderCallOutcome
    call_index: int
    retry_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProviderRequestIdentity):
            raise TypeError("identity must be ProviderRequestIdentity")
        if not isinstance(self.outcome, ProviderCallOutcome):
            raise TypeError("outcome must be ProviderCallOutcome")
        for field_name in ("call_index", "retry_index"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")


@dataclass(frozen=True)
class ProviderExecution:
    outcome: ProviderCallOutcome
    calls: tuple[ProviderCall, ...]


class _Collector(Protocol):
    def collect_outcome(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
        *,
        scan_budget: SensitiveScanBudget | None = None,
    ) -> ProviderCallOutcome: ...


def _provider_scan_budget(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
) -> SensitiveScanBudget:
    """Derive one bounded transport scan budget from the trusted registry."""

    row_limit = binding.max_rows_per_attempt
    nesting_limit = binding.max_nesting_depth
    if row_limit is None or nesting_limit is None:
        raise ValueError("provider scan budget requires registry resource limits")

    declared_fields = max(len(dataset.fields), len(binding.requested_fields))
    field_budget = declared_fields + _PROVIDER_SCAN_FIELD_HEADROOM
    if field_budget > _PROVIDER_SCAN_ABSOLUTE_MAX_FIELDS:
        raise ValueError("provider scan field budget exceeds the absolute limit")

    max_nodes = (
        _PROVIDER_SCAN_FIXED_NODE_HEADROOM + 1 + row_limit * (1 + 2 * field_budget)
    )
    max_depth = nesting_limit + _PROVIDER_SCAN_ENVELOPE_DEPTH
    if max_nodes > _PROVIDER_SCAN_ABSOLUTE_MAX_NODES:
        raise ValueError("provider scan node budget exceeds the absolute limit")
    if max_depth > _PROVIDER_SCAN_ABSOLUTE_MAX_DEPTH:
        raise ValueError("provider scan depth budget exceeds the absolute limit")
    return SensitiveScanBudget(max_depth=max_depth, max_nodes=max_nodes)


def _resolved_request(
    binding: ProviderBinding,
    request_window: Mapping[str, str],
    *,
    request_variant: Mapping[str, RequestScalar] | None = None,
) -> tuple[dict[str, str], dict[str, RequestScalar]]:
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
        window = normalize_request_window(policy, window)
    params: dict[str, RequestScalar] = {
        key: (
            window[match.group(1)]
            if (match := _WINDOW_PLACEHOLDER.fullmatch(value)) is not None
            else value
        )
        for key, value in binding.request_template.items()
    }
    selected = (
        binding.request_variants[0] if request_variant is None else request_variant
    )
    selected_identity = _variant_identity(selected)
    known = {_variant_identity(variant) for variant in binding.request_variants}
    if selected_identity not in known:
        raise ValueError("request_variant must be one registered request variant")
    for key, value in selected.items():
        if key not in binding.request_template:
            raise ValueError("request_variant key is absent from request_template")
        if _WINDOW_PLACEHOLDER.fullmatch(binding.request_template[key]):
            raise ValueError("request_variant cannot replace a window placeholder")
        params[key] = value
    return dict(sorted(window.items())), dict(sorted(params.items()))


def _variant_identity(
    variant: Mapping[str, RequestScalar],
) -> tuple[tuple[str, tuple[str, RequestScalar]], ...]:
    if not isinstance(variant, Mapping):
        raise TypeError("request_variant must be a mapping")
    identity: list[tuple[str, tuple[str, RequestScalar]]] = []
    for key, value in sorted(variant.items()):
        if type(key) is not str:
            raise ValueError("request_variant keys must be strings")
        if type(value) not in {str, bool, int, float} or (
            type(value) is float and not math.isfinite(value)
        ):
            raise ValueError("request_variant values must be finite JSON scalars")
        identity.append((key, (type(value).__name__, value)))
    return tuple(identity)


def _stable_fanout_batches(
    values: Sequence[RequestScalar],
    *,
    parameter: str,
    batch_size: int,
    max_values: int | None = None,
    source_order: str = "lexical",
) -> tuple[FanoutBatch, ...]:
    """Deduplicate typed source values and produce stable bounded batches."""

    if type(parameter) is not str or not parameter:
        raise ValueError("fanout parameter is invalid")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("fanout batch_size is invalid")
    if max_values is not None and (type(max_values) is not int or max_values <= 0):
        raise ValueError("fanout max_values is invalid")
    if source_order not in {"lexical", "stable_hash"}:
        raise ValueError("fanout source_order is invalid")
    unique: dict[tuple[str, RequestScalar], RequestScalar] = {}
    for value in values:
        if type(value) not in {str, bool, int, float} or (
            type(value) is float and not math.isfinite(value)
        ):
            raise ValueError("fanout source contains a non-scalar value")
        if type(value) is str and not value:
            raise ValueError("fanout source contains an empty string")
        unique[(type(value).__name__, value)] = value
    if source_order == "stable_hash":
        def sort_key(item: tuple[str, RequestScalar]) -> tuple[str, str]:
            return (
                hashlib.sha256(
                    json.dumps(item[1], ensure_ascii=False, allow_nan=False).encode("utf-8")
                ).hexdigest(),
                item[0],
            )
    else:
        def sort_key(item: tuple[str, RequestScalar]) -> tuple[str, str]:
            return (
                item[0],
                json.dumps(item[1], ensure_ascii=False, allow_nan=False),
            )
    ordered = tuple(
        unique[key]
        for key in sorted(
            unique,
            key=sort_key,
        )
    )
    if max_values is not None:
        if len(ordered) < max_values:
            raise ValueError("fanout source has fewer values than max_values")
        ordered = ordered[:max_values]
    return tuple(
        FanoutBatch(parameter=parameter, values=ordered[index : index + batch_size])
        for index in range(0, len(ordered), batch_size)
    )


def _source_binding(
    dataset: DatasetDefinition,
    *,
    preferred_provider: str,
) -> ProviderBinding:
    candidates = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.entitlement_state == "active"
        and binding.activation_state == "active"
    )
    preferred = tuple(
        binding for binding in candidates if binding.provider == preferred_provider
    )
    selected = preferred or candidates
    if len(selected) != 1:
        raise ValueError("fanout source requires one completed active binding")
    return selected[0]


def _load_completed_fanout_batches(
    db_path: Path,
    *,
    registry: DatasetRegistry,
    binding: ProviderBinding,
) -> tuple[FanoutBatch, ...]:
    policy = binding.fanout
    if policy is None or policy.strategy == "none":
        return (FanoutBatch(parameter=None, values=()),)
    if (
        policy.strategy != "dataset_field"
        or policy.parameter is None
        or policy.source_dataset_id is None
        or policy.source_field is None
        or policy.batch_size is None
    ):
        raise ValueError("fanout contract is incomplete")
    source = registry.resolve(policy.source_dataset_id)
    if source.dataset_id != policy.source_dataset_id:
        raise ValueError("fanout source_dataset_id must be canonical")
    source_binding = _source_binding(source, preferred_provider=binding.provider)
    source_field = next(
        (field for field in source.fields if field.name == policy.source_field),
        None,
    )
    if source_field is None:
        raise ValueError("fanout source_field is not declared by its dataset")
    try:
        with sqlite_authority_lock(db_path, mode="shared"):
            uri = f"{db_path.resolve(strict=True).as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.execute("PRAGMA query_only = ON")
                valid_receipt_ids = validated_success_receipt_ids(
                    conn,
                    registry,
                    source,
                    source_binding,
                    now=datetime.now(timezone.utc),
                )
                rows = conn.execute(
                    "SELECT p.payload_json, p.payload_hash, p.receipt_id "
                    "FROM provider_dataset_rows AS p "
                    "WHERE p.dataset_id=? AND p.provider=? AND p.schema_major=? "
                    "ORDER BY p.row_key",
                    (source.dataset_id, source_binding.provider, source.schema_major),
                ).fetchall()
    except (
        OSError,
        RuntimeProjectionError,
        SqliteAuthorityLockError,
        sqlite3.Error,
    ) as exc:
        raise ValueError("fanout source authority is unavailable") from exc
    now = datetime.now(ZoneInfo(source.timezone)).date()
    cutoff = (
        None
        if policy.source_date_lte_days is None
        else now - timedelta(days=policy.source_date_lte_days)
    )
    values: list[RequestScalar] = []
    for payload_json, payload_hash, receipt_id in rows:
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("fanout source payload is invalid") from exc
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if (
            type(receipt_id) is not str
            or receipt_id not in valid_receipt_ids
            or type(payload_hash) is not str
            or canonical_payload != payload_json
            or hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != payload_hash
        ):
            raise ValueError("fanout source receipt is not completed authority")
        if type(payload) is not dict or policy.source_field not in payload:
            raise ValueError("fanout source payload is missing its declared field")
        for field, expected in policy.source_equals:
            if field not in payload:
                raise ValueError("fanout source payload is missing selector field")
            if payload[field] != expected:
                break
        else:
            if cutoff is not None:
                if policy.source_date_field is None:
                    raise ValueError("fanout source date selector is incomplete")
                raw_date = payload.get(policy.source_date_field)
                if type(raw_date) is not str or len(raw_date) != 8 or not raw_date.isdigit():
                    raise ValueError("fanout source date selector is invalid")
                try:
                    listed = datetime.strptime(raw_date, "%Y%m%d").date()
                except ValueError as exc:
                    raise ValueError("fanout source date selector is invalid") from exc
                if listed > cutoff:
                    continue
            value = payload[policy.source_field]
            if source_field.logical_type == "text":
                valid = type(value) is str and bool(value)
            elif source_field.logical_type == "integer":
                valid = type(value) is int
            else:
                valid = type(value) in {int, float} and (
                    type(value) is not float or math.isfinite(value)
                )
            if not valid:
                raise ValueError("fanout source value violates its declared type")
            values.append(value)
            continue
    batches = _stable_fanout_batches(
        values,
        parameter=policy.parameter,
        batch_size=policy.batch_size,
        max_values=policy.max_values,
        source_order=policy.source_order,
    )
    if not batches:
        raise ValueError("fanout source has no completed values")
    return batches


def _fanout_parameter_value(values: tuple[RequestScalar, ...]) -> RequestScalar:
    if len(values) == 1:
        return values[0]
    return ",".join(str(value) for value in values)


def _resource_failure(
    *,
    scan_budget: SensitiveScanBudget,
) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=None,
        error_code="resource_budget",
        error_message="provider request resource budget exceeded",
        scan_budget=scan_budget,
    )


def _collect_with_retry(
    *,
    collector: _Collector,
    binding: ProviderBinding,
    params: dict[str, RequestScalar],
    requested_fields: str | None,
    scan_budget: SensitiveScanBudget,
    retry: RetrySettings,
    sleep: Callable[[float], None],
    identity: ProviderRequestIdentity,
    first_call_index: int,
) -> tuple[ProviderCall, ...]:
    calls: list[ProviderCall] = []
    for retry_index in range(retry.max_attempts):
        outcome = collector.collect_outcome(
            binding.api_name,
            params,
            requested_fields,
            scan_budget=scan_budget,
        )
        if not isinstance(outcome, ProviderCallOutcome):
            raise TypeError("collector returned an invalid provider outcome")
        outcome.validate_invariants()
        singular_identity = ProviderRequestIdentity(
            request_variant=identity.request_variant,
            fanout_parameter=identity.fanout_parameter,
            fanout_values=identity.fanout_values,
            page_offset=identity.page_offset,
            page_index=identity.page_index,
        )
        calls.append(
            ProviderCall(
                identity=singular_identity,
                outcome=outcome,
                call_index=first_call_index + retry_index,
                retry_index=retry_index,
            )
        )
        if (
            outcome.state != "failed"
            or outcome.error_code not in _RETRYABLE_PROVIDER_ERRORS
            or retry_index + 1 == retry.max_attempts
        ):
            return tuple(calls)
        exponential = retry.base_delay_seconds * (2**retry_index)
        delay = min(exponential, retry.max_delay_seconds) + retry.jitter_seconds
        if delay:
            sleep(delay)
    raise RuntimeError("retry loop terminated without an outcome")


def _batch_size_bytes(rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    total = 2
    largest = 0
    for index, row in enumerate(rows):
        payload = json.dumps(
            row,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        largest = max(largest, len(payload))
        total += len(payload) + (1 if index else 0)
    return largest, total


def _execute_provider_requests(
    *,
    collector: _Collector,
    binding: ProviderBinding,
    base_params: Mapping[str, RequestScalar],
    request_variant: Mapping[str, RequestScalar],
    fanout_batches: tuple[FanoutBatch, ...],
    requested_fields: str | None,
    scan_budget: SensitiveScanBudget,
    retry: RetrySettings,
    first_call_index: int = 0,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderExecution:
    """Execute generic variant/fanout/pagination requests without row rewriting."""

    pagination = binding.pagination or PaginationPolicy(strategy="none")
    rows: list[dict[str, Any]] = []
    calls: list[ProviderCall] = []
    for batch in fanout_batches:
        params = dict(base_params)
        if batch.parameter is not None:
            params[batch.parameter] = _fanout_parameter_value(batch.values)
        page_count = pagination.max_pages if pagination.strategy == "offset" else 1
        if page_count is None:
            raise ValueError("offset pagination max_pages is missing")
        for page_index in range(page_count):
            page_params = dict(params)
            page_offset: int | None = None
            if pagination.strategy == "offset":
                if (
                    pagination.limit_parameter is None
                    or pagination.offset_parameter is None
                    or pagination.page_size is None
                ):
                    raise ValueError("offset pagination contract is incomplete")
                page_offset = page_index * pagination.page_size
                page_params[pagination.limit_parameter] = pagination.page_size
                page_params[pagination.offset_parameter] = page_offset
            elif pagination.strategy != "none":
                raise ValueError("pagination strategy is unsupported")
            identity = ProviderRequestIdentity(
                request_variant=request_variant,
                fanout_parameter=batch.parameter,
                fanout_values=batch.values,
                page_offset=page_offset,
                page_index=page_index,
            )
            attempt_calls = _collect_with_retry(
                collector=collector,
                binding=binding,
                params=page_params,
                requested_fields=requested_fields,
                scan_budget=scan_budget,
                retry=retry,
                sleep=sleep,
                identity=identity,
                first_call_index=first_call_index + len(calls),
            )
            calls.extend(attempt_calls)
            outcome = attempt_calls[-1].outcome
            if outcome.state == "failed":
                return ProviderExecution(outcome=outcome, calls=tuple(calls))
            page_rows = outcome.mutable_rows()
            rows.extend(page_rows)
            largest, total = _batch_size_bytes(rows)
            if (
                binding.max_rows_per_attempt is None
                or binding.max_payload_bytes_per_row is None
                or binding.max_batch_bytes is None
                or len(rows) > binding.max_rows_per_attempt
                or largest > binding.max_payload_bytes_per_row
                or total > binding.max_batch_bytes
            ):
                return ProviderExecution(
                    outcome=_resource_failure(scan_budget=scan_budget),
                    calls=tuple(calls),
                )
            if pagination.strategy == "none":
                break
            assert pagination.page_size is not None
            if len(page_rows) < pagination.page_size:
                break
            if page_index + 1 == page_count:
                return ProviderExecution(
                    outcome=_resource_failure(scan_budget=scan_budget),
                    calls=tuple(calls),
                )
    combined = ProviderCallOutcome(
        state="success" if rows else "empty",
        rows=tuple(rows),
        provider_code=0,
        error_code=None,
        error_message=None,
        scan_budget=scan_budget,
    )
    return ProviderExecution(outcome=combined, calls=tuple(calls))


def _config_hash(dataset: DatasetDefinition, binding: ProviderBinding) -> str:
    return provider_ingest_config_hash(dataset, binding)


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
    calls: Sequence[ProviderCall],
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
        if policy.fanout_field is not None:
            _validate_fanout_snapshot(policy, rows, calls=calls)
        elif policy.snapshot_field is not None:
            _validate_homogeneous_snapshot_field(policy.snapshot_field, rows)
    elif policy.strategy == "single_partition_unique_primary_key":
        _validate_single_partition(
            dataset,
            policy,
            rows,
            resolved_params=resolved_params,
        )
    else:
        raise ValueError("provider response completeness strategy is unsupported")


def _validate_fanout_snapshot(
    policy: Any,
    rows: tuple[Mapping[str, Any], ...],
    *,
    calls: Sequence[ProviderCall],
) -> None:
    """Validate an exact fanout cohort at one provider snapshot timestamp."""

    if policy.fanout_field is None and policy.snapshot_field is None:
        return
    if policy.fanout_field is None or policy.snapshot_field is None:
        raise ValueError("provider response fanout snapshot contract is incomplete")
    expected = {value for call in calls for value in call.identity.fanout_values}
    if not expected:
        raise ValueError("provider response fanout snapshot has no requested values")
    observed: set[str] = set()
    snapshots: set[str] = set()
    for row in rows:
        value = row.get(policy.fanout_field)
        snapshot = row.get(policy.snapshot_field)
        if type(value) is not str or not value:
            raise ValueError("provider response fanout field is invalid")
        if type(snapshot) is not str or not snapshot:
            raise ValueError("provider response snapshot field is invalid")
        if value in observed:
            raise ValueError("provider response contains duplicate fanout value")
        observed.add(value)
        snapshots.add(snapshot)
    if observed != expected:
        raise ValueError("provider response fanout coverage is incomplete")
    if len(snapshots) != 1:
        raise ValueError("provider response fanout snapshot time is inconsistent")


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


def _validate_homogeneous_snapshot_field(
    snapshot_field: str,
    rows: tuple[Mapping[str, Any], ...],
) -> None:
    """Require one provider observation value across a snapshot response."""

    observed = {row.get(snapshot_field) for row in rows}
    if len(observed) != 1 or None in observed or "" in observed:
        raise ValueError("provider response snapshot field is not homogeneous")


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
    request_identity: ProviderRequestIdentity | None = None,
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
        request_identity=(
            ProviderRequestIdentity.trivial()
            if request_identity is None
            else request_identity
        ),
    )


def _provider_call_attempt_id(root_attempt_id: str, call: ProviderCall) -> str:
    """Derive one deterministic physical-call identity from the caller root."""

    return make_provider_call_attempt_id(
        root_attempt_id,
        call_index=call.call_index,
        retry_index=call.retry_index,
    )


def _provider_error_code(outcome: ProviderCallOutcome) -> str:
    if outcome.error_code in _PROVIDER_ERROR_CODES:
        return str(outcome.error_code)
    return "provider_error"


def _provider_call_context(
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    provider_call: ProviderCall,
    normalized_window: Mapping[str, str],
    root_attempt_id: str,
    started_at: str,
    data_through: str | None,
) -> IngestContext:
    return _context(
        dataset=dataset,
        binding=binding,
        request_window=normalized_window,
        attempt_id=_provider_call_attempt_id(root_attempt_id, provider_call),
        started_at=started_at,
        data_through=data_through,
        request_identity=provider_call.identity,
    )


def _persist_provider_call(
    db_path: Path,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    provider_call: ProviderCall,
    normalized_window: Mapping[str, str],
    root_attempt_id: str,
    started_at: str,
) -> IngestResult:
    """Singular storage handoff for exactly one provider call/response.

    Every physical call receives its own deterministic attempt ID and one
    singular request identity.  Retry ordinals never pollute provider request
    parameters and no aggregate ``requests`` payload is created.
    """

    outcome = provider_call.outcome
    call_context = _provider_call_context(
        dataset=dataset,
        binding=binding,
        provider_call=provider_call,
        normalized_window=normalized_window,
        root_attempt_id=root_attempt_id,
        started_at=started_at,
        data_through=(
            _data_through(dataset, outcome, started_at)
            if outcome.state == "success"
            else None
        ),
    )
    if outcome.state == "empty":
        return write_terminal_receipt(
            db_path,
            context=call_context,
            status="empty",
            errors=(),
        )
    if outcome.state == "failed":
        return write_terminal_receipt(
            db_path,
            context=call_context,
            status="failed",
            errors=(_provider_error_code(outcome),),
        )
    failure_context = _provider_call_context(
        dataset=dataset,
        binding=binding,
        provider_call=provider_call,
        normalized_window=normalized_window,
        root_attempt_id=root_attempt_id,
        started_at=started_at,
        data_through=None,
    )
    try:
        return ingest_provider_native_rows(
            db_path,
            dataset=dataset,
            binding=binding,
            rows=outcome.mutable_rows(),
            context=call_context,
        )
    except ProviderNativeAdmissionError as exc:
        return write_terminal_receipt(
            db_path,
            context=failure_context,
            status="failed",
            errors=(exc.error_code,),
        )
    except Exception as primary_error:
        try:
            return write_terminal_receipt(
                db_path,
                context=failure_context,
                status="failed",
                errors=("storage_failed",),
            )
        except Exception:
            raise primary_error


def _zero_counts() -> IngestCounts:
    return IngestCounts(
        returned=0,
        validated=0,
        inserted=0,
        updated=0,
        unchanged=0,
        rejected=0,
        committed=0,
        count_semantics="terminal_no_data_transaction",
    )


def _aggregate_counts(
    results: Sequence[IngestResult],
    *,
    count_semantics: str,
) -> IngestCounts:
    def total(field_name: str) -> int | None:
        values = tuple(getattr(result.counts, field_name) for result in results)
        if any(value is None for value in values):
            return None
        return sum(int(value) for value in values)

    return IngestCounts(
        returned=sum(result.counts.returned for result in results),
        validated=sum(result.counts.validated for result in results),
        inserted=total("inserted"),
        updated=total("updated"),
        unchanged=total("unchanged"),
        rejected=sum(result.counts.rejected for result in results),
        committed=sum(result.counts.committed for result in results),
        count_semantics=count_semantics,
    )


def _aggregate_success_results(results: Sequence[IngestResult]) -> IngestResult:
    counts = _aggregate_counts(
        results,
        count_semantics="aggregate_physical_call_transactions",
    )
    return IngestResult(
        status="success",
        counts=counts,
        receipt_ids=tuple(
            receipt_id for result in results for receipt_id in result.receipt_ids
        ),
        errors=(),
    )


def _persist_failed_execution(
    db_path: Path,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    calls: Sequence[ProviderCall],
    normalized_window: Mapping[str, str],
    root_attempt_id: str,
    started_at: str,
    overall_error: str,
    terminal_context: IngestContext,
) -> IngestResult:
    receipt_ids: list[str] = []
    if not calls:
        result = write_terminal_receipt(
            db_path,
            context=terminal_context,
            status="failed",
            errors=(overall_error,),
        )
        receipt_ids.extend(result.receipt_ids)
    for call in calls:
        call_error = (
            _provider_error_code(call.outcome)
            if call.outcome.state == "failed"
            else overall_error
        )
        context = _provider_call_context(
            dataset=dataset,
            binding=binding,
            provider_call=call,
            normalized_window=normalized_window,
            root_attempt_id=root_attempt_id,
            started_at=started_at,
            data_through=None,
        )
        result = write_terminal_receipt(
            db_path,
            context=context,
            status="failed",
            errors=(call_error,),
        )
        receipt_ids.extend(result.receipt_ids)
    return IngestResult(
        status="failed",
        counts=_zero_counts(),
        receipt_ids=tuple(receipt_ids),
        errors=(overall_error,),
    )


def _persist_provider_execution(
    db_path: Path,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    execution: ProviderExecution,
    normalized_window: Mapping[str, str],
    resolved_params: Mapping[str, RequestScalar],
    attempt_id: str,
    started_at: str,
    terminal_context: IngestContext,
    enforce_empty_policy: bool = True,
) -> IngestResult:
    """Persist one independent terminal transaction for every real call."""

    if execution.outcome.state == "failed":
        error_code = _provider_error_code(execution.outcome)
        return _persist_failed_execution(
            db_path,
            dataset=dataset,
            binding=binding,
            calls=execution.calls,
            normalized_window=normalized_window,
            root_attempt_id=attempt_id,
            started_at=started_at,
            overall_error=error_code,
            terminal_context=terminal_context,
        )
    if execution.outcome.state == "empty":
        if enforce_empty_policy and dataset.empty_data_policy == "forbidden":
            return _persist_failed_execution(
                db_path,
                dataset=dataset,
                binding=binding,
                calls=execution.calls,
                normalized_window=normalized_window,
                root_attempt_id=attempt_id,
                started_at=started_at,
                overall_error="validation_failed",
                terminal_context=terminal_context,
            )
        results = tuple(
            _persist_provider_call(
                db_path,
                dataset=dataset,
                binding=binding,
                provider_call=call,
                normalized_window=normalized_window,
                root_attempt_id=attempt_id,
                started_at=started_at,
            )
            for call in execution.calls
        )
        return IngestResult(
            status="empty",
            counts=_zero_counts(),
            receipt_ids=tuple(
                receipt_id for result in results for receipt_id in result.receipt_ids
            ),
            errors=(),
        )

    if binding.response_completeness is not None:
        try:
            _validate_response_completeness(
                dataset,
                binding,
                execution.outcome.rows,
                request_window=normalized_window,
                resolved_params=resolved_params,
                calls=execution.calls,
            )
        except ValueError:
            return _persist_failed_execution(
                db_path,
                dataset=dataset,
                binding=binding,
                calls=execution.calls,
                normalized_window=normalized_window,
                root_attempt_id=attempt_id,
                started_at=started_at,
                overall_error="validation_failed",
                terminal_context=terminal_context,
            )

    results = tuple(
        _persist_provider_call(
            db_path,
            dataset=dataset,
            binding=binding,
            provider_call=call,
            normalized_window=normalized_window,
            root_attempt_id=attempt_id,
            started_at=started_at,
        )
        for call in execution.calls
    )
    if any(
        result.status == "failed" and call.outcome.state != "failed"
        for call, result in zip(execution.calls, results, strict=True)
    ):
        errors = tuple(
            dict.fromkeys(error for result in results for error in result.errors)
        )
        committed_results = tuple(
            result for result in results if result.status == "success"
        )
        counts = (
            _aggregate_counts(
                committed_results,
                count_semantics=("aggregate_partial_physical_call_transactions"),
            )
            if committed_results
            else _zero_counts()
        )
        return IngestResult(
            status="failed",
            counts=counts,
            receipt_ids=tuple(
                receipt_id for result in results for receipt_id in result.receipt_ids
            ),
            errors=errors or ("storage_failed",),
        )
    return _aggregate_success_results(results)


def _aggregate_variant_results(
    dataset: DatasetDefinition,
    results: Sequence[IngestResult],
) -> IngestResult:
    """Aggregate one complete registry variant cohort without rewriting receipts."""

    if len(results) == 1:
        return results[0]
    receipt_ids = tuple(
        receipt_id for result in results for receipt_id in result.receipt_ids
    )
    failed = tuple(result for result in results if result.status == "failed")
    if failed:
        committed = tuple(
            result for result in results if result.counts.committed > 0
        )
        return IngestResult(
            status="failed",
            counts=(
                _aggregate_counts(
                    committed,
                    count_semantics="aggregate_partial_physical_call_transactions",
                )
                if committed
                else _zero_counts()
            ),
            receipt_ids=receipt_ids,
            errors=tuple(
                dict.fromkeys(error for result in failed for error in result.errors)
            )
            or ("storage_failed",),
        )
    successful = tuple(result for result in results if result.status == "success")
    if successful:
        return IngestResult(
            status="success",
            counts=_aggregate_counts(
                results,
                count_semantics="aggregate_variant_physical_call_transactions",
            ),
            receipt_ids=receipt_ids,
            errors=(),
        )
    if dataset.empty_data_policy == "forbidden":
        return IngestResult(
            status="failed",
            counts=_zero_counts(),
            receipt_ids=receipt_ids,
            errors=("validation_failed",),
        )
    return IngestResult(
        status="empty",
        counts=_zero_counts(),
        receipt_ids=receipt_ids,
        errors=(),
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
    request_variant: Mapping[str, RequestScalar] | None = None,
    retry: RetrySettings = RetrySettings(),
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
    active_bindings = tuple(
        item for item in dataset.provider_bindings
        if item.entitlement_state == "active" and item.activation_state == "active"
    )
    if len(active_bindings) != 1:
        raise ValueError("collection requires exactly one active provider binding")
    binding = active_bindings[0]
    if dataset.read_model_adapter.storage_kind != "provider_native_rows":
        raise ValueError("dataset is not configured for provider-native collection")
    if binding.entitlement_state != "active" or binding.activation_state != "active":
        raise ValueError("dataset binding is not entitled and active")
    scan_budget = _provider_scan_budget(dataset, binding)
    variants = (
        binding.request_variants
        if request_variant is None
        else (dict(request_variant),)
    )
    defer_empty_policy = request_variant is None and len(variants) > 1
    normalized_window, _ = _resolved_request(
        binding,
        request_window,
        request_variant=variants[0],
    )

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
    try:
        fanout_batches = _load_completed_fanout_batches(
            db_path,
            registry=registry,
            binding=binding,
        )
    except (TypeError, ValueError):
        return write_terminal_receipt(
            db_path,
            context=terminal_context,
            status="failed",
            errors=("config_error",),
        )
    requested_fields = (
        ",".join(binding.requested_fields) if binding.requested_fields else None
    )
    results: list[IngestResult] = []
    next_call_index = 0
    for variant in variants:
        variant_window, params = _resolved_request(
            binding,
            request_window,
            request_variant=variant,
        )
        if variant_window != normalized_window:
            raise ValueError("request variants must share one normalized window")
        execution = _execute_provider_requests(
            collector=collector,
            binding=binding,
            base_params=params,
            request_variant=variant,
            fanout_batches=fanout_batches,
            requested_fields=requested_fields,
            scan_budget=scan_budget,
            retry=retry,
            first_call_index=next_call_index,
        )
        next_call_index += len(execution.calls)
        results.append(
            _persist_provider_execution(
                db_path,
                dataset=dataset,
                binding=binding,
                execution=execution,
                normalized_window=normalized_window,
                resolved_params=params,
                attempt_id=attempt_id,
                started_at=started_at,
                terminal_context=terminal_context,
                enforce_empty_policy=not defer_empty_policy,
            )
        )
    return _aggregate_variant_results(dataset, results)
