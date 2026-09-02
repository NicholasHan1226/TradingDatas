"""Bounded provider-neutral queries over one verified SQLite snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from catalog_service import inspect_dataset_queryability, is_initial_release_eligible
from provider_ingest_contract import provider_ingest_config_hash
from provider_transport import (
    BINANCE_SPOT_DATA_PROVIDER,
    BINANCE_USDM_DATA_PROVIDER,
    BINANCE_USDM_DUMP_DATA_PROVIDER,
    BINANCE_USDM_RELAY_DATA_PROVIDER,
    TUSHARE_DATA_PROVIDER,
    provider_transport_profile,
)
from dataset_registry import DatasetDefinition, DatasetField, DatasetRegistry
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryExecutionOptions,
    QueryRequest,
    QueryValidationError,
    ResolvedQueryAsOf,
    normalized_query_hash,
    public_catalog_version,
    resolve_query_as_of,
)
from query_cursor import (
    CursorClaims,
    CursorConfigurationError,
    CursorExpectation,
    CursorMismatch,
    InvalidCursor,
    SignedCursorCodec,
)
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    RuntimeProjectionError,
    ValidatedRowReceiptProof,
    ValidatedRowReceiptProofSelection,
    classify_row_receipt_proofs,
    open_verified_read_model_snapshot,
    project_dataset_runtime_evidence,
    validated_receipt_history_for_dataset,
)


_AGGREGATE_SCOPES = frozenset({"external_read", "read", "full", "*"})
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z")
_FIELD_NAME_RE = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_ORDER_RE = re.compile(r"([A-Za-z0-9_]{1,64}):(asc|desc)\Z")
_FILTER_OPERATORS = frozenset({"eq", "in", "gte", "lte", "between"})
_PROVIDER_NATIVE_STORAGE_KIND = "provider_native_rows"
_PROVIDER_NATIVE_TABLE = "provider_dataset_rows"
_PROVIDER_NATIVE_PARTITION_INDEX = "provider_dataset_rows_partition_idx"
_PROVIDER_NATIVE_QUALITY_INDEX = "provider_dataset_rows_quality_idx"
_PROVIDER_NATIVE_ISSUE_RE = re.compile(
    r"(?:"
    r"(?:missing_field|unknown_field|null_not_allowed|integer_out_of_int64):"
    r"[A-Za-z0-9_]{1,64}"
    r"|unknown_field_sha256:[0-9a-f]{64}"
    r"|type_mismatch:[A-Za-z0-9_]{1,64}:(?:text|integer|float)"
    r"|time_format_mismatch:[A-Za-z0-9_]{1,64}:(?:yyyymm|yyyymmdd|rfc3339)"
    r"|snapshot_key_fallback:(?:missing|null|non_scalar|type_mismatch):"
    r"[A-Za-z0-9_]{1,64}"
    r")\Z"
)
_EVIDENCE_ISO_TIMESTAMP_RE = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?"
    r"(?P<zone>Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?\Z"
)
_PROVIDER_LOCAL_SNAPSHOT_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2} "
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?\Z"
)
_RESPONSE_COMPLETENESS_UNVERIFIED = "response_completeness_unverified"
_FRESHNESS_WATERMARK_UNVERIFIED = "freshness_watermark_unverified"
_MAX_FAILED_COHORT_FILTER_PASSES = 8


@dataclass(frozen=True)
class _PreparedQuery:
    fields: tuple[str, ...]
    order: tuple[tuple[str, str], ...]
    as_of: ResolvedQueryAsOf
    empty_interval: bool
    provider_native_full_payload: bool


class QueryAccessDenied(PermissionError):
    """A valid dataset query is not authorized (future HTTP 403)."""


class QueryDatasetNotFound(LookupError):
    """The requested dataset is unavailable for querying (future HTTP 404)."""


class QueryServiceUnavailable(RuntimeError):
    """The query authority or capacity is unavailable (future HTTP 503)."""


@contextmanager
def _sqlite_progress_budget(conn: sqlite3.Connection, step_budget: int):
    """Apply one VM-step budget across every statement in the request."""

    if type(step_budget) is not int or step_budget <= 0:
        raise QueryServiceUnavailable("query service is unavailable")
    quantum = min(1000, step_budget)
    consumed = 0

    def progress() -> int:
        nonlocal consumed
        consumed += quantum
        return int(consumed >= step_budget)

    try:
        conn.set_progress_handler(progress, quantum)
    except sqlite3.Error:
        raise QueryServiceUnavailable("query service is unavailable") from None
    try:
        yield
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except sqlite3.Error:
            raise QueryServiceUnavailable("query service is unavailable") from None


@contextmanager
def _query_snapshot(db_path: Path):
    """Translate snapshot-open, exit, and binding failures to one public 503."""

    try:
        with open_verified_read_model_snapshot(db_path) as conn:
            yield conn
    except (
        CursorMismatch,
        InvalidCursor,
        QueryAccessDenied,
        QueryBudgetError,
        QueryDatasetNotFound,
        QueryServiceUnavailable,
        QueryValidationError,
    ):
        raise
    except (OSError, RuntimeProjectionError, TimeoutError, sqlite3.Error):
        raise QueryServiceUnavailable("query service is unavailable") from None


def _request_scalar(value: object, name: str) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise QueryValidationError(f"{name} must be a finite JSON scalar")


def _request_scalar_key(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise QueryValidationError("request is invalid") from None


def _revalidate_request(request: object) -> QueryRequest:
    if type(request) is not QueryRequest:
        raise QueryValidationError("request must be QueryRequest")
    try:
        dataset_id = request.dataset_id
        schema_major = request.schema_major
        fields = request.fields
        filters = request.filters
        as_of = request.as_of
        order = request.order
        limit = request.limit
        cursor = request.cursor
        include_receipt_proofs = request.include_receipt_proofs
    except AttributeError:
        raise QueryValidationError("request is invalid") from None
    if (
        type(dataset_id) is not str
        or not dataset_id
        or dataset_id != dataset_id.strip()
        or _DATASET_ID_RE.fullmatch(dataset_id) is None
    ):
        raise QueryValidationError("dataset_id must be a canonical dataset identifier")
    if type(schema_major) is not int or schema_major <= 0:
        raise QueryValidationError("schema_major must be a positive integer")
    if type(include_receipt_proofs) is not bool:
        raise QueryValidationError("include_receipt_proofs must be a boolean")

    if type(fields) is not tuple:
        raise QueryValidationError("fields must be a tuple")
    if any(
        type(field) is not str or _FIELD_NAME_RE.fullmatch(field) is None
        for field in fields
    ):
        raise QueryValidationError("fields must contain field identifiers")
    if len(set(fields)) != len(fields):
        raise QueryValidationError("fields must not contain duplicates")
    owned_fields = tuple(field for field in fields)

    if not isinstance(filters, MappingProxyType):
        raise QueryValidationError("filters must be immutable")
    try:
        filter_items = tuple(filters.items())
    except RuntimeError:
        raise QueryValidationError("filters must be canonical") from None
    filter_names = tuple(field_name for field_name, _ in filter_items)
    if any(
        type(field_name) is not str or _FIELD_NAME_RE.fullmatch(field_name) is None
        for field_name in filter_names
    ):
        raise QueryValidationError("filters field must be a field identifier")
    if filter_names != tuple(sorted(filter_names)):
        raise QueryValidationError("filters must be canonical")
    owned_filters: dict[str, object] = {}
    for field_name, clause in filter_items:
        if not isinstance(clause, MappingProxyType):
            raise QueryValidationError(f"filters.{field_name} is invalid")
        try:
            clause_items = tuple(clause.items())
        except RuntimeError:
            raise QueryValidationError(f"filters.{field_name} is invalid") from None
        if len(clause_items) != 1:
            raise QueryValidationError(f"filters.{field_name} is invalid")
        operator, operand = clause_items[0]
        if type(operator) is not str or operator not in _FILTER_OPERATORS:
            raise QueryValidationError(
                f"filters.{field_name} uses an unsupported operator"
            )
        if operator in {"eq", "gte", "lte"}:
            owned_operand = _request_scalar(
                operand,
                f"filters.{field_name}.{operator}",
            )
            owned_filters[field_name] = MappingProxyType({operator: owned_operand})
            continue
        if type(operand) is not tuple:
            raise QueryValidationError(f"filters.{field_name}.{operator} is invalid")
        if operator == "between" and len(operand) != 2:
            raise QueryValidationError(
                f"filters.{field_name}.between must contain exactly 2 values"
            )
        if operator == "in":
            if not operand:
                raise QueryValidationError(f"filters.{field_name}.in must not be empty")
        owned_operand = tuple(
            _request_scalar(
                value,
                f"filters.{field_name}.{operator}[{index}]",
            )
            for index, value in enumerate(operand)
        )
        if operator == "in":
            keys = tuple(_request_scalar_key(value) for value in owned_operand)
            if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
                raise QueryValidationError(
                    f"filters.{field_name}.in must be canonical and unique"
                )
        owned_filters[field_name] = MappingProxyType({operator: owned_operand})
    frozen_filters = MappingProxyType(owned_filters)

    if as_of is not None:
        if type(as_of) is not str:
            raise QueryValidationError("as_of must be a canonical RFC3339 timestamp")
        match = _EVIDENCE_ISO_TIMESTAMP_RE.fullmatch(as_of)
        if match is None or match.group("zone") is None or as_of.endswith("-00:00"):
            raise QueryValidationError("as_of must be a canonical RFC3339 timestamp")
        try:
            parsed = datetime.fromisoformat(as_of)
        except (OverflowError, ValueError):
            raise QueryValidationError(
                "as_of must be a canonical RFC3339 timestamp"
            ) from None
        canonical = parsed.isoformat(
            timespec="microseconds" if parsed.microsecond else "seconds"
        )
        if as_of != canonical:
            raise QueryValidationError("as_of must be a canonical RFC3339 timestamp")

    owned_order: tuple[str, ...] | None = None
    if order is not None:
        if type(order) is not tuple or not order:
            raise QueryValidationError("order must be a non-empty tuple")
        ordered_fields: list[str] = []
        owned_order_terms: list[str] = []
        for term in order:
            if type(term) is not str or (match := _ORDER_RE.fullmatch(term)) is None:
                raise QueryValidationError(
                    "order terms must be exactly field:asc or field:desc"
                )
            ordered_fields.append(match.group(1))
            owned_order_terms.append(term)
        if len(set(ordered_fields)) != len(ordered_fields):
            raise QueryValidationError("order must not contain duplicate fields")
        owned_order = tuple(owned_order_terms)

    if type(limit) is not int or limit <= 0:
        raise QueryValidationError("limit must be a positive integer")
    if cursor is not None and (
        type(cursor) is not str or not cursor or cursor != cursor.strip()
    ):
        raise QueryValidationError("cursor must be a canonical non-empty string")

    snapshot = object.__new__(QueryRequest)
    object.__setattr__(snapshot, "dataset_id", dataset_id)
    object.__setattr__(snapshot, "schema_major", schema_major)
    object.__setattr__(snapshot, "fields", owned_fields)
    object.__setattr__(snapshot, "filters", frozen_filters)
    object.__setattr__(snapshot, "as_of", as_of)
    object.__setattr__(snapshot, "order", owned_order)
    object.__setattr__(snapshot, "limit", limit)
    object.__setattr__(snapshot, "cursor", cursor)
    object.__setattr__(snapshot, "include_receipt_proofs", include_receipt_proofs)
    return snapshot


def _revalidate_access(access: object) -> QueryAccessContext:
    if not isinstance(access, QueryAccessContext):
        raise QueryValidationError("access must be QueryAccessContext")
    rebuilt = QueryAccessContext(
        tenant_id=access.tenant_id,
        scopes=access.scopes,
        allowed_dataset_ids=access.allowed_dataset_ids,
        policy_id=access.policy_id,
    )
    if rebuilt != access:
        raise QueryValidationError("access is invalid")
    return rebuilt


def _revalidate_options(options: object) -> QueryExecutionOptions:
    if not isinstance(options, QueryExecutionOptions):
        raise QueryValidationError("options must be QueryExecutionOptions")
    rebuilt = QueryExecutionOptions(
        latest_partition=options.latest_partition,
        any_of_eq_filters=options.any_of_eq_filters,
    )
    if rebuilt != options:
        raise QueryValidationError("options are invalid")
    return rebuilt


def _enforce_root_budgets(
    request: QueryRequest,
    options: QueryExecutionOptions,
    registry: DatasetRegistry,
) -> None:
    defaults = registry.query_defaults
    if len(request.fields) > defaults.max_selected_fields:
        raise QueryBudgetError(
            f"fields exceeds max_selected_fields={defaults.max_selected_fields}"
        )
    if len(request.filters) > defaults.max_filter_terms:
        raise QueryBudgetError(
            f"filters exceeds max_filter_terms={defaults.max_filter_terms}"
        )
    for field, clause in request.filters.items():
        if "in" in clause and len(clause["in"]) > defaults.max_in_values:
            raise QueryBudgetError(
                f"filters.{field}.in exceeds max_in_values={defaults.max_in_values}"
            )
    if request.order is not None and len(request.order) > defaults.max_order_terms:
        raise QueryBudgetError(
            f"order exceeds max_order_terms={defaults.max_order_terms}"
        )
    if request.limit > defaults.max_page_size:
        raise QueryBudgetError(f"limit exceeds max_page_size={defaults.max_page_size}")
    if len(options.any_of_eq_filters) > 4:
        raise QueryBudgetError("any_of_eq_filters supports at most 4 terms")


def _canonical_request_id(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise QueryValidationError("request_id must be a canonical non-empty string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise QueryValidationError("request_id must be valid UTF-8 text") from None
    return value


def _validated_now(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise QueryServiceUnavailable("query service clock is unavailable")
    try:
        if value.utcoffset() is None:
            raise QueryServiceUnavailable("query service clock is unavailable")
        value.timestamp()
    except QueryServiceUnavailable:
        raise
    except (OverflowError, OSError, ValueError):
        raise QueryServiceUnavailable("query service clock is unavailable") from None
    return value


def _schema_major(dataset: DatasetDefinition) -> int:
    try:
        major = int(dataset.schema_version.split(".", 1)[0])
    except (AttributeError, TypeError, ValueError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if major <= 0:
        raise QueryServiceUnavailable("query service is unavailable")
    return major


def _validate_typed_value(
    value: object,
    field: DatasetField,
    *,
    operator: str,
    name: str,
) -> object:
    if value is None:
        if field.nullable and operator in {"eq", "in"}:
            return None
        raise QueryValidationError(f"{name} does not accept null")
    if field.logical_type == "text":
        if type(value) is not str:
            raise QueryValidationError(f"{name} must be text")
        return value
    if field.logical_type == "integer":
        if type(value) is not int:
            raise QueryValidationError(f"{name} must be an integer")
        return value
    if field.logical_type == "float":
        if type(value) not in {int, float} or not math.isfinite(value):
            raise QueryValidationError(f"{name} must be a finite number")
        return value
    raise QueryServiceUnavailable("query service is unavailable")


def _parse_yyyymmdd(value: object, name: str) -> date:
    if (
        type(value) is not str
        or len(value) != 8
        or not value.isascii()
        or not value.isdigit()
    ):
        raise QueryValidationError(f"{name} must use yyyymmdd")
    try:
        parsed = datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise QueryValidationError(f"{name} must use yyyymmdd") from None
    if parsed.strftime("%Y%m%d") != value:
        raise QueryValidationError(f"{name} must use yyyymmdd")
    return parsed


def _parse_yyyymm(value: object, name: str) -> date:
    """Parse one canonical monthly partition as its inclusive month start."""

    if (
        type(value) is not str
        or len(value) != 6
        or not value.isascii()
        or not value.isdigit()
    ):
        raise QueryValidationError(f"{name} must use yyyymm")
    try:
        parsed = datetime.strptime(value, "%Y%m").date()
    except ValueError:
        raise QueryValidationError(f"{name} must use yyyymm") from None
    if parsed.strftime("%Y%m") != value:
        raise QueryValidationError(f"{name} must use yyyymm")
    return parsed


def _parse_rfc3339_filter(value: object, name: str) -> datetime:
    """Accept one canonical, aware RFC3339 bound for a timestamp range."""

    if type(value) is not str or value != value.strip():
        raise QueryValidationError(f"{name} must use canonical RFC3339")
    match = _EVIDENCE_ISO_TIMESTAMP_RE.fullmatch(value)
    if match is None or match.group("zone") is None or value.endswith("-00:00"):
        raise QueryValidationError(f"{name} must use canonical RFC3339")
    try:
        parsed = datetime.fromisoformat(value)
    except (OverflowError, ValueError):
        raise QueryValidationError(f"{name} must use canonical RFC3339") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QueryValidationError(f"{name} must use canonical RFC3339")
    canonical = parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )
    if value != canonical:
        raise QueryValidationError(f"{name} must use canonical RFC3339")
    return parsed


def _range_filter_values(
    dataset: DatasetDefinition,
    values: tuple[object, ...],
    *,
    name: str,
) -> tuple[date | datetime, ...]:
    if dataset.as_of_format == "rfc3339":
        return tuple(_parse_rfc3339_filter(value, name) for value in values)
    if dataset.as_of_format == "yyyymm":
        return tuple(_parse_yyyymm(value, name) for value in values)
    return tuple(_parse_yyyymmdd(value, name) for value in values)


def _provider_rfc3339_milliseconds(value: datetime) -> str:
    """Match the UTC millisecond representation held in provider-native rows."""

    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_filter_clause(
    field: DatasetField,
    clause: object,
    *,
    dataset: DatasetDefinition,
) -> tuple[str, tuple[object, ...]]:
    if not isinstance(clause, MappingProxyType) or len(clause) != 1:
        raise QueryValidationError(f"filters.{field.name} is invalid")
    operator, raw_operand = next(iter(clause.items()))
    if operator not in {"eq", "in", "gte", "lte", "between"}:
        raise QueryValidationError(f"filters.{field.name} operator is invalid")
    if operator in {"in", "between"}:
        if type(raw_operand) is not tuple:
            raise QueryValidationError(f"filters.{field.name}.{operator} is invalid")
        operands = raw_operand
    else:
        operands = (raw_operand,)
    validated = tuple(
        _validate_typed_value(
            value,
            field,
            operator=operator,
            name=f"filters.{field.name}.{operator}",
        )
        for value in operands
    )
    if operator == "between" and validated[0] > validated[1]:
        raise QueryValidationError(
            f"filters.{field.name}.between lower bound exceeds upper bound"
        )
    if field.name == dataset.range_field:
        range_values = _range_filter_values(
            dataset,
            validated,
            name=f"filters.{field.name}.{operator}",
        )
        if operator == "between" and range_values[0] > range_values[1]:
            raise QueryValidationError(
                f"filters.{field.name}.between lower bound exceeds upper bound"
            )
        if dataset.as_of_format == "rfc3339":
            encoded = tuple(
                _provider_rfc3339_milliseconds(value)
                for value in range_values
                if isinstance(value, datetime)
            )
            if len(encoded) != len(range_values):
                raise QueryServiceUnavailable("query service is unavailable")
            validated = encoded
    return operator, validated


def _lookback_span_days(
    request: QueryRequest,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    as_of: ResolvedQueryAsOf,
) -> int | None:
    if dataset.range_field is None:
        return None
    clause = request.filters.get(dataset.range_field)
    if not isinstance(clause, MappingProxyType):
        return None
    operator, raw_operand = next(iter(clause.items()))
    values = raw_operand if type(raw_operand) is tuple else (raw_operand,)
    range_values = _range_filter_values(
        dataset,
        values,
        name=f"filters.{dataset.range_field}.{operator}",
    )
    if dataset.as_of_format == "rfc3339":
        datetimes = tuple(
            value for value in range_values if isinstance(value, datetime)
        )
        if len(datetimes) != len(range_values):
            raise QueryServiceUnavailable("query service is unavailable")
        dates = tuple(
            value.astimezone(ZoneInfo(dataset.timezone)).date()
            for value in datetimes
        )
    else:
        dates = tuple(value for value in range_values if isinstance(value, date))
    if operator == "eq":
        return 0
    if operator == "in":
        return (max(dates) - min(dates)).days
    if operator == "between":
        return (dates[1] - dates[0]).days
    if operator == "gte":
        try:
            dataset_timezone = ZoneInfo(dataset.timezone)
            cutoff = (
                now.astimezone(dataset_timezone).date()
                if as_of.resolved_as_of is None
                else datetime.fromisoformat(as_of.resolved_as_of)
                .astimezone(dataset_timezone)
                .date()
            )
        except (ValueError, ZoneInfoNotFoundError):
            raise QueryServiceUnavailable("query service is unavailable") from None
        return max(0, (cutoff - dates[0]).days)
    return None


def _range_gte_starts_after_cutoff(
    request: QueryRequest,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    as_of: ResolvedQueryAsOf,
) -> bool:
    if dataset.range_field is None:
        return False
    clause = request.filters.get(dataset.range_field)
    if not isinstance(clause, MappingProxyType) or "gte" not in clause:
        return False
    lower_bound = _range_filter_values(
        dataset,
        (clause["gte"],),
        name=f"filters.{dataset.range_field}.gte",
    )[0]
    try:
        dataset_timezone = ZoneInfo(dataset.timezone)
        if dataset.as_of_format == "rfc3339":
            if not isinstance(lower_bound, datetime):
                raise QueryServiceUnavailable("query service is unavailable")
            cutoff = (
                now.astimezone(dataset_timezone)
                if as_of.resolved_as_of is None
                else datetime.fromisoformat(as_of.resolved_as_of).astimezone(
                    dataset_timezone
                )
            )
            return lower_bound.astimezone(dataset_timezone) > cutoff
        if not isinstance(lower_bound, date):
            raise QueryServiceUnavailable("query service is unavailable")
        cutoff_date = (
            now.astimezone(dataset_timezone).date()
            if as_of.resolved_as_of is None
            else datetime.fromisoformat(as_of.resolved_as_of)
            .astimezone(dataset_timezone)
            .date()
        )
        return lower_bound > cutoff_date
    except (ValueError, ZoneInfoNotFoundError):
        raise QueryServiceUnavailable("query service is unavailable") from None


def _prepare_query(
    request: QueryRequest,
    options: QueryExecutionOptions,
    dataset: DatasetDefinition,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> _PreparedQuery:
    try:
        ZoneInfo(dataset.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if request.schema_major != _schema_major(dataset):
        raise QueryValidationError("schema_major is incompatible with dataset")
    field_map = {field.name: field for field in dataset.fields}
    provider_native_full_payload = not request.fields
    effective_fields = (
        ()
        if provider_native_full_payload
        else request.fields or dataset.default_projection
    )
    if len(effective_fields) > registry.query_defaults.max_selected_fields:
        raise QueryBudgetError(
            "fields exceeds max_selected_fields="
            f"{registry.query_defaults.max_selected_fields}"
        )
    for field_name in effective_fields:
        field = field_map.get(field_name)
        if field is None or not field.selectable:
            raise QueryValidationError(f"field {field_name!r} is not selectable")

    for field_name, clause in request.filters.items():
        field = field_map.get(field_name)
        if field is None or not field.filterable:
            raise QueryValidationError(f"field {field_name!r} is not filterable")
        operator = next(iter(clause))
        if operator not in dataset.filter_operators.get(field_name, ()):
            raise QueryValidationError(
                f"operator {operator!r} is not allowed for {field_name!r}"
            )
        _validate_filter_clause(
            field,
            clause,
            dataset=dataset,
        )

    if (
        len(request.filters) + len(options.any_of_eq_filters)
        > registry.query_defaults.max_filter_terms
    ):
        raise QueryBudgetError(
            "filters exceeds max_filter_terms="
            f"{registry.query_defaults.max_filter_terms}"
        )
    for field_name, value in options.any_of_eq_filters:
        field = field_map.get(field_name)
        if (
            field is None
            or not field.filterable
            or "eq" not in dataset.filter_operators.get(field_name, ())
        ):
            raise QueryValidationError(
                f"compatibility field {field_name!r} is not filterable"
            )
        _validate_typed_value(
            value,
            field,
            operator="eq",
            name=f"any_of_eq_filters.{field_name}",
        )
    if options.latest_partition and dataset.partition_field is None:
        raise QueryValidationError("dataset does not declare a partition field")

    if request.order is not None:
        raw_order = request.order
    else:
        raw_order = tuple(f"{field_name}:asc" for field_name in dataset.primary_key)
    order: list[tuple[str, str]] = []
    for term in raw_order:
        field_name, direction = term.rsplit(":", 1)
        field = field_map.get(field_name)
        if field is None or not field.selectable or not field.sortable:
            raise QueryValidationError(f"field {field_name!r} is not sortable")
        order.append((field_name, direction))
    if request.limit > dataset.max_page_size:
        raise QueryBudgetError(f"limit exceeds max_page_size={dataset.max_page_size}")
    try:
        as_of = resolve_query_as_of(request, dataset)
    except OverflowError:
        raise QueryValidationError("as_of is outside the supported range") from None
    span = _lookback_span_days(request, dataset, now=now, as_of=as_of)
    if span is not None and span > dataset.max_lookback_days:
        raise QueryBudgetError(
            f"lookback exceeds max_lookback_days={dataset.max_lookback_days}"
        )
    return _PreparedQuery(
        fields=tuple(effective_fields),
        order=tuple(order),
        as_of=as_of,
        empty_interval=(
            span == 0
            and _range_gte_starts_after_cutoff(
                request,
                dataset,
                now=now,
                as_of=as_of,
            )
        ),
        provider_native_full_payload=provider_native_full_payload,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _row_receipt_proof_semantic_key(
    dataset: DatasetDefinition,
    provider: str,
    schema_major: int,
    row_key: str,
) -> str:
    """Return a deterministic, payload-free identity for one read-model row."""

    return _digest(
        {
            "dataset_id": dataset.dataset_id,
            "provider": provider,
            "schema_major": schema_major,
            "row_key": row_key,
        }
    )


def _classified_page_receipt_proofs(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    rows: tuple[tuple[object, ...], ...],
    *,
    now: datetime,
) -> ValidatedRowReceiptProofSelection:
    """Validate every returned row's own authority, including default queries."""

    if not rows:
        return ValidatedRowReceiptProofSelection(
            proofs={},
            failed_cohort_success_receipt_ids=(),
        )
    receipt_ids = tuple(dict.fromkeys(row[5] for row in rows))
    if any(type(receipt_id) is not str or not receipt_id for receipt_id in receipt_ids):
        raise QueryServiceUnavailable("query service is unavailable")
    selection = classify_row_receipt_proofs(
        conn,
        registry,
        dataset,
        receipt_ids,
        now=now,
    )
    proofs = selection.proofs
    excluded = frozenset(selection.failed_cohort_success_receipt_ids)
    for row in rows:
        if row[5] in excluded:
            continue
        proof = proofs.get(row[5])
        if (
            proof is None
            or proof.dataset_id != dataset.dataset_id
            or proof.provider != row[1]
            or proof.receipt_id != row[5]
            or proof.status != "success"
        ):
            raise QueryServiceUnavailable("query service is unavailable")
    return selection


def _row_receipt_proof_metadata(
    dataset: DatasetDefinition,
    rows: tuple[tuple[object, ...], ...],
    proofs: Mapping[str, ValidatedRowReceiptProof],
    *,
    now: datetime,
) -> list[dict[str, object]]:
    """Format opt-in proofs with their additional single-cohort contract."""
    if not rows:
        return []
    cohort_identity: tuple[object, ...] | None = None
    output: list[dict[str, object]] = []
    no_window = dataset.cadence_class == "session_minute" and (
        dataset.partition_field is None
        and dataset.as_of_field is None
        and dataset.range_field is None
    )
    active_bindings = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )
    if (
        not no_window
        or not any(field.name == "time" for field in dataset.fields)
        or not active_bindings
        or any(
            binding.response_completeness is None
            or binding.response_completeness.snapshot_field != "time"
            for binding in active_bindings
        )
    ) and no_window:
        raise QueryServiceUnavailable("query service is unavailable")
    for row in rows:
        provider = row[1]
        row_key = row[2]
        receipt_id = row[5]
        if (
            type(provider) is not str
            or type(row_key) is not str
            or type(receipt_id) is not str
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        proof = proofs.get(receipt_id)
        if (
            proof is None
            or proof.dataset_id != dataset.dataset_id
            or proof.provider != provider
            or proof.receipt_id != receipt_id
            or proof.status != "success"
            or proof.data_through is None
            or proof.finished_at.tzinfo is None
            or proof.finished_at.utcoffset() is None
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        payload = _parse_provider_native_payload(row[0])
        if no_window:
            if proof.request_window:
                raise QueryServiceUnavailable("query service is unavailable")
            try:
                through = datetime.fromisoformat(
                    _normalize_data_through(proof.data_through, dataset)
                )
                event_time = datetime.fromisoformat(
                    _normalize_data_through(payload.get("time"), dataset)
                )
            except (TypeError, ValueError, QueryServiceUnavailable, ZoneInfoNotFoundError):
                raise QueryServiceUnavailable("query service is unavailable") from None
            if (
                through.tzinfo is None
                or through.utcoffset() is None
                or event_time.tzinfo is None
                or event_time.utcoffset() is None
                or through > now
                or event_time > now
                or event_time != through
            ):
                raise QueryServiceUnavailable("query service is unavailable")
        elif not proof.request_window:
            raise QueryServiceUnavailable("query service is unavailable")
        elif dataset.partition_field is not None:
            partition_value = payload.get(dataset.partition_field)
            window_value = proof.request_window.get(dataset.partition_field)
            if window_value is not None and partition_value != window_value:
                raise QueryServiceUnavailable("query service is unavailable")
        identity = (
            proof.execution_id,
            tuple(sorted(proof.request_window.items())),
            proof.config_hash,
            proof.data_through,
        )
        if cohort_identity is None:
            cohort_identity = identity
        elif identity != cohort_identity:
            raise QueryServiceUnavailable("query service is unavailable")
        row_identity_sha256 = _row_receipt_proof_semantic_key(
            dataset,
            provider,
            _schema_major(dataset),
            row_key,
        )
        if any(item["row_identity_sha256"] == row_identity_sha256 for item in output):
            raise QueryServiceUnavailable("query service is unavailable")
        output.append({
            "page_index": len(output),
            "row_identity_sha256": row_identity_sha256,
            "dataset_id": proof.dataset_id,
            "provider": proof.provider,
            "source": proof.provider,
            "receipt_id": proof.receipt_id,
            "status": proof.status,
            "execution_id": proof.execution_id,
            "config_hash": proof.config_hash,
            "request_window": dict(proof.request_window),
            "data_through": proof.data_through,
            "finished_at": proof.finished_at.astimezone(timezone.utc).isoformat(
                timespec="microseconds" if proof.finished_at.microsecond else "seconds"
            ),
            "receipt_proof_sha256": proof.receipt_proof_sha256,
        })
    return output


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _provider_json_path(field_name: str) -> str:
    if type(field_name) is not str or _FIELD_NAME_RE.fullmatch(field_name) is None:
        raise QueryServiceUnavailable("query service is unavailable")
    return f'$."{field_name}"'


def _field_expression(dataset: DatasetDefinition, field_name: str) -> str:
    # ``partition_value`` is the immutable, lossless read-model projection of
    # the declared partition field.  Reuse it for that one field so bounded
    # partition reads use the existing provider-native partition index instead
    # of scanning every JSON payload in the dataset.
    if field_name == dataset.partition_field:
        return _quote_identifier("partition_value")
    path = _provider_json_path(field_name)
    return f"json_extract({_quote_identifier('payload_json')}, '{path}')"


def _field_json_type_expression(
    dataset: DatasetDefinition,
    field_name: str,
) -> str | None:
    path = _provider_json_path(field_name)
    return f"json_type({_quote_identifier('payload_json')}, '{path}')"


def _provider_native_providers(dataset: DatasetDefinition) -> tuple[str, ...]:
    bindings = tuple(dataset.provider_bindings)
    active = {
        binding.provider
        for binding in bindings
        if binding.entitlement_state == "active"
    }
    eligible = active or {
        binding.provider
        for binding in bindings
        if binding.entitlement_state not in {"excluded", "retired"}
    }
    providers = tuple(sorted(eligible))
    if not providers or any(
        type(provider) is not str or not provider or provider != provider.strip()
        for provider in providers
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    return providers


def _provider_native_schema_major(dataset: DatasetDefinition) -> int:
    return _schema_major(dataset)


def _provider_native_isolation(
    dataset: DatasetDefinition,
) -> tuple[list[str], list[object]]:
    if (
        dataset.read_model_adapter.storage_kind != _PROVIDER_NATIVE_STORAGE_KIND
        or dataset.read_model_adapter.primary_table != _PROVIDER_NATIVE_TABLE
        or dataset.read_model_adapter.fixed_field_filters
        or any(
            binding.target_tables != (_PROVIDER_NATIVE_TABLE,)
            for binding in dataset.provider_bindings
        )
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    providers = _provider_native_providers(dataset)
    return (
        [
            f"{_quote_identifier('dataset_id')} = ?",
            f"{_quote_identifier('provider')} IN ({', '.join('?' for _ in providers)})",
            f"{_quote_identifier('schema_major')} = ?",
        ],
        [dataset.dataset_id, *providers, _provider_native_schema_major(dataset)],
    )


def _provider_native_query_table(
    dataset: DatasetDefinition,
    request: QueryRequest,
) -> str:
    """Return the bounded physical read path for one validated request.

    An exact declared-partition filter is the common daily/reference-data
    access pattern.  Its persisted ``partition_value`` projection has a
    mandatory index, so force that path instead of allowing SQLite to choose
    a payload-order scan that can exceed the request VM budget on history.
    Other query shapes retain the generic primary-table path.
    """

    partition_field = dataset.partition_field
    partition_clause = (
        request.filters.get(partition_field)
        if partition_field is not None
        else None
    )
    exact_partition = (
        isinstance(partition_clause, MappingProxyType)
        and tuple(partition_clause) == ("eq",)
    )
    table = f"main.{_quote_identifier(_PROVIDER_NATIVE_TABLE)}"
    if exact_partition:
        return f"{table} INDEXED BY {_quote_identifier(_PROVIDER_NATIVE_PARTITION_INDEX)}"
    return table


def _compile_scalar_filter(
    identifier: str,
    operator: str,
    values: tuple[object, ...],
    *,
    json_type_identifier: str | None = None,
) -> tuple[str, list[object]]:
    if operator == "eq":
        if values[0] is None:
            if json_type_identifier is not None:
                return f"{json_type_identifier} = 'null'", []
            return f"{identifier} IS NULL", []
        return f"{identifier} = ?", [values[0]]
    if operator == "in":
        non_null = [value for value in values if value is not None]
        has_null = len(non_null) != len(values)
        parts: list[str] = []
        params: list[object] = []
        if non_null:
            parts.append(f"{identifier} IN ({', '.join('?' for _ in non_null)})")
            params.extend(non_null)
        if has_null:
            parts.append(
                f"{json_type_identifier} = 'null'"
                if json_type_identifier is not None
                else f"{identifier} IS NULL"
            )
        return "(" + " OR ".join(parts) + ")", params
    if operator == "gte":
        return f"{identifier} >= ?", [values[0]]
    if operator == "lte":
        return f"{identifier} <= ?", [values[0]]
    if operator == "between":
        return f"{identifier} BETWEEN ? AND ?", [values[0], values[1]]
    raise QueryServiceUnavailable("query service is unavailable")


def _base_predicates(
    request: QueryRequest,
    options: QueryExecutionOptions,
    dataset: DatasetDefinition,
    prepared: _PreparedQuery,
) -> tuple[list[str], list[object]]:
    predicates: list[str] = []
    params: list[object] = []
    isolation_predicates, isolation_params = _provider_native_isolation(dataset)
    predicates.extend(isolation_predicates)
    params.extend(isolation_params)
    field_map = {field.name: field for field in dataset.fields}
    for field_name, clause in request.filters.items():
        operator, values = _validate_filter_clause(
            field_map[field_name],
            clause,
            dataset=dataset,
        )
        sql, values_params = _compile_scalar_filter(
            _field_expression(dataset, field_name),
            operator,
            values,
            json_type_identifier=_field_json_type_expression(dataset, field_name),
        )
        predicates.append(sql)
        params.extend(values_params)
    if prepared.as_of.field is not None:
        predicates.append(f"{_field_expression(dataset, prepared.as_of.field)} <= ?")
        encoded_cutoff = prepared.as_of.encoded_cutoff
        if dataset.as_of_format == "rfc3339":
            encoded_cutoff = _provider_rfc3339_milliseconds(
                _parse_rfc3339_filter(encoded_cutoff, "as_of")
            )
        params.append(encoded_cutoff)
    if options.any_of_eq_filters:
        branches: list[str] = []
        branch_params: list[object] = []
        for field_name, value in options.any_of_eq_filters:
            sql, values_params = _compile_scalar_filter(
                _field_expression(dataset, field_name),
                "eq",
                (value,),
                json_type_identifier=_field_json_type_expression(
                    dataset,
                    field_name,
                ),
            )
            branches.append(sql)
            branch_params.extend(values_params)
        predicates.append("(" + " OR ".join(branches) + ")")
        params.extend(branch_params)
    if prepared.empty_interval:
        predicates.append("0 = 1")
    return predicates, params


def _where_clause(predicates: list[str]) -> str:
    return "" if not predicates else " WHERE " + " AND ".join(predicates)


def _provider_native_valid_type_predicate(
    dataset: DatasetDefinition,
    field: DatasetField,
) -> str:
    value_expression = _field_expression(dataset, field.name)
    type_expression = _field_json_type_expression(dataset, field.name)
    absent_or_null = f"({type_expression} IS NULL OR {type_expression} = 'null')"
    if field.logical_type == "text":
        valid_value = f"{type_expression} = 'text'"
    elif field.logical_type == "integer":
        valid_value = (
            f"({type_expression} = 'integer' AND "
            f"typeof({value_expression}) = 'integer')"
        )
    elif field.logical_type == "float":
        valid_value = (
            f"({type_expression} = 'real' OR "
            f"({type_expression} = 'integer' AND "
            f"typeof({value_expression}) = 'integer'))"
        )
    else:
        raise QueryServiceUnavailable("query service is unavailable")
    return f"({absent_or_null} OR {valid_value})"


def _provider_native_receipt_predicate(
    permitted_receipt_ids: tuple[str, ...] | None,
) -> tuple[str | None, list[object]]:
    if permitted_receipt_ids is None:
        return None, []
    if (
        type(permitted_receipt_ids) is not tuple
        or not permitted_receipt_ids
        or len(set(permitted_receipt_ids)) != len(permitted_receipt_ids)
        or any(
            type(receipt_id) is not str
            or not receipt_id
            or receipt_id != receipt_id.strip()
            for receipt_id in permitted_receipt_ids
        )
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    return (
        (
            f"{_quote_identifier('receipt_id')} IN "
            "(SELECT value FROM json_each(?) WHERE type = 'text')"
        ),
        [
            json.dumps(
                list(permitted_receipt_ids),
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
        ],
    )


def _provider_native_validate_operation_fields(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    request: QueryRequest,
    options: QueryExecutionOptions,
    prepared: _PreparedQuery,
    *,
    dataset_degraded: bool,
    permitted_receipt_ids: tuple[str, ...] | None = None,
) -> None:
    if type(dataset_degraded) is not bool:
        raise QueryServiceUnavailable("query service is unavailable")
    if not dataset_degraded:
        return
    field_map = {field.name: field for field in dataset.fields}
    names = set(request.filters)
    names.update(field_name for field_name, _direction in prepared.order)
    names.update(field_name for field_name, _value in options.any_of_eq_filters)
    if prepared.as_of.field is not None:
        names.add(prepared.as_of.field)
    if options.latest_partition and dataset.partition_field is not None:
        names.add(dataset.partition_field)
    isolation, params = _provider_native_isolation(dataset)
    receipt_predicate, receipt_params = _provider_native_receipt_predicate(
        permitted_receipt_ids
    )
    if receipt_predicate is not None:
        isolation.append(receipt_predicate)
        params.extend(receipt_params)
    degraded_predicate = f"{_quote_identifier('quality_state')} = 'degraded'"
    indexed_table = (
        f"main.{_quote_identifier(_PROVIDER_NATIVE_TABLE)} INDEXED BY "
        f"{_quote_identifier(_PROVIDER_NATIVE_QUALITY_INDEX)}"
    )
    for field_name in sorted(names):
        field = field_map.get(field_name)
        if field is None:
            raise QueryServiceUnavailable("query service is unavailable")
        valid_type = _provider_native_valid_type_predicate(dataset, field)
        issue_values = (
            f"time_format_mismatch:{field_name}:yyyymmdd",
            f"time_format_mismatch:{field_name}:rfc3339",
        )
        invalid_declared_time = (
            "EXISTS (SELECT 1 FROM json_each("
            f"{_quote_identifier('quality_issues_json')}) AS quality_issue "
            "WHERE quality_issue.type = 'text' "
            "AND quality_issue.value IN (?, ?))"
        )
        sql = (
            f"SELECT 1 FROM {indexed_table}"
            f"{_where_clause([*isolation, degraded_predicate, f'(NOT {valid_type} OR {invalid_declared_time})'])} "
            "LIMIT 1"
        )
        if conn.execute(sql, [*params, *issue_values]).fetchone() is not None:
            raise QueryServiceUnavailable("query service is unavailable")


def _provider_native_dataset_quality_degraded(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    permitted_receipt_ids: tuple[str, ...] | None = None,
) -> bool:
    isolation, params = _provider_native_isolation(dataset)
    receipt_predicate, receipt_params = _provider_native_receipt_predicate(
        permitted_receipt_ids
    )
    if receipt_predicate is not None:
        isolation.append(receipt_predicate)
        params.extend(receipt_params)
    table = (
        f"main.{_quote_identifier(_PROVIDER_NATIVE_TABLE)} INDEXED BY "
        f"{_quote_identifier(_PROVIDER_NATIVE_QUALITY_INDEX)}"
    )
    degraded_predicate = f"{_quote_identifier('quality_state')} = 'degraded'"
    degraded = (
        conn.execute(
            f"SELECT 1 FROM {table}"
            f"{_where_clause([*isolation, degraded_predicate])} "
            "LIMIT 1",
            params,
        ).fetchone()
        is not None
    )
    if not degraded:
        return False
    issues = _quote_identifier("quality_issues_json")
    invalid_degraded_contract = (
        f"json_valid({issues}) != 1"
        f" OR json_type({issues}) != 'array'"
        f" OR json_array_length({issues}) = 0"
    )
    if (
        conn.execute(
            f"SELECT 1 FROM {table}"
            f"{_where_clause([*isolation, degraded_predicate, f'({invalid_degraded_contract})'])} "
            "LIMIT 1",
            params,
        ).fetchone()
        is not None
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    return True


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constant")


def _parse_provider_native_payload(value: object) -> dict[str, object]:
    if type(value) is not str:
        raise QueryServiceUnavailable("query service is unavailable")
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (RecursionError, TypeError, ValueError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if type(parsed) is not dict or any(type(key) is not str for key in parsed):
        raise QueryServiceUnavailable("query service is unavailable")
    return parsed


def _parse_provider_native_quality(
    state: object,
    value: object,
) -> tuple[str, ...]:
    if state not in {"valid", "degraded"} or type(value) is not str:
        raise QueryServiceUnavailable("query service is unavailable")
    try:
        parsed = json.loads(value, parse_constant=_reject_json_constant)
    except (RecursionError, TypeError, ValueError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if (
        type(parsed) is not list
        or any(
            type(issue) is not str
            or len(issue) > 160
            or _PROVIDER_NATIVE_ISSUE_RE.fullmatch(issue) is None
            for issue in parsed
        )
        or parsed != sorted(set(parsed))
        or (state == "valid") != (not parsed)
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    return tuple(parsed)


def _parse_evidence_iso_timestamp(value: object) -> tuple[datetime, bool]:
    if type(value) is not str or not value or value != value.strip():
        raise QueryServiceUnavailable("query service is unavailable")
    match = _EVIDENCE_ISO_TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise QueryServiceUnavailable("query service is unavailable")
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
        aware = match.group("zone") is not None
        if aware and (parsed.tzinfo is None or parsed.utcoffset() is None):
            raise ValueError
        if not aware and parsed.tzinfo is not None:
            raise ValueError
    except (OverflowError, ValueError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    return parsed, aware


def _localize_unambiguous_timestamp(
    parsed: datetime,
    dataset_timezone: ZoneInfo,
) -> datetime:
    candidates: list[datetime] = []
    try:
        for fold in (0, 1):
            candidate = parsed.replace(tzinfo=dataset_timezone, fold=fold)
            round_trip = candidate.astimezone(timezone.utc).astimezone(dataset_timezone)
            if round_trip.replace(tzinfo=None) == parsed:
                candidates.append(candidate)
        offsets = {candidate.utcoffset() for candidate in candidates}
    except (OverflowError, ValueError):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if not candidates or len(offsets) != 1 or None in offsets:
        raise QueryServiceUnavailable("query service is unavailable")
    return candidates[0].replace(fold=0)


def _normalize_aware_timestamp(value: object) -> str:
    parsed, aware = _parse_evidence_iso_timestamp(value)
    if not aware:
        raise QueryServiceUnavailable("query service is unavailable")
    return parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )


def _normalize_data_through(value: object, dataset: DatasetDefinition) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise QueryServiceUnavailable("query service is unavailable")
    try:
        dataset_timezone = ZoneInfo(dataset.timezone)
    except ZoneInfoNotFoundError:
        raise QueryServiceUnavailable("query service is unavailable") from None
    if len(value) == 6 and value.isascii() and value.isdigit():
        try:
            parsed_date = _parse_yyyymm(value, "data_through")
        except QueryValidationError:
            raise QueryServiceUnavailable("query service is unavailable") from None
        parsed = datetime.combine(parsed_date, datetime.min.time()).replace(
            tzinfo=dataset_timezone
        )
    elif len(value) == 8 and value.isascii() and value.isdigit():
        try:
            parsed_date = _parse_yyyymmdd(value, "data_through")
        except QueryValidationError:
            raise QueryServiceUnavailable("query service is unavailable") from None
        parsed = datetime.combine(parsed_date, datetime.min.time()).replace(
            tzinfo=dataset_timezone
        )
    else:
        # Provider minute bars use a local ``YYYY-MM-DD HH:MM:SS`` value for
        # their snapshot watermark.  It is receipt-internal evidence, not a
        # client ``as_of`` value; normalize only this exact unzoned shape
        # before applying the normal strict ISO parser.
        normalized_value = (
            value.replace(" ", "T", 1)
            if _PROVIDER_LOCAL_SNAPSHOT_TIMESTAMP_RE.fullmatch(value) is not None
            else value
        )
        parsed, aware = _parse_evidence_iso_timestamp(normalized_value)
        if not aware:
            parsed = _localize_unambiguous_timestamp(parsed, dataset_timezone)
    return parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )


def _receipt_watermark(
    dataset: DatasetDefinition,
    evidence: DatasetRuntimeEvidence,
) -> str:
    projection = evidence.projection
    payload = {
        "dataset_id": dataset.dataset_id,
        "runtime_state": projection.state,
        "degraded": projection.degraded,
        "reasons": sorted(set(projection.reasons)),
        "current": {
            "receipt_id": projection.receipt_id,
            "receipt_ids": list(evidence.current_receipt_ids),
            "data_through": projection.data_through,
            "observed_at": projection.observed_at,
            "status": evidence.current_receipt_status,
            "providers": list(evidence.current_providers),
        },
        "last_success": {
            "receipt_id": evidence.last_success_receipt_id,
            "receipt_ids": list(evidence.last_success_receipt_ids),
            "data_through": evidence.last_success_data_through,
            "providers": list(evidence.last_success_providers),
        },
    }
    if evidence.as_of_success_receipt_ids:
        payload["as_of_success_receipt_ids"] = list(
            evidence.as_of_success_receipt_ids
        )
    return _digest(payload)


def _evidence_as_of(prepared: _PreparedQuery) -> datetime | None:
    requested = prepared.as_of.requested_as_of
    if requested is None:
        return None
    try:
        cutoff = datetime.fromisoformat(requested)
    except ValueError:
        raise QueryServiceUnavailable("query service is unavailable") from None
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise QueryServiceUnavailable("query service is unavailable")
    return cutoff


def _as_of_receipt_collection_window(
    request: QueryRequest,
    dataset: DatasetDefinition,
    prepared: _PreparedQuery,
) -> tuple[datetime, datetime] | None:
    """Bound lineage for an RFC3339 rolling-window as-of query."""

    if (
        prepared.as_of.resolved_as_of is None
        or dataset.as_of_format != "rfc3339"
        or dataset.range_field is None
    ):
        return None
    clause = request.filters.get(dataset.range_field)
    if not isinstance(clause, MappingProxyType) or tuple(clause) != ("between",):
        return None
    raw_values = clause["between"]
    if type(raw_values) is not tuple or len(raw_values) != 2:
        raise QueryServiceUnavailable("query service is unavailable")
    range_values = _range_filter_values(
        dataset,
        raw_values,
        name=f"filters.{dataset.range_field}.between",
    )
    if len(range_values) != 2 or not all(
        isinstance(value, datetime) for value in range_values
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    window_start = range_values[0].astimezone(timezone.utc)
    cutoff = _evidence_as_of(prepared)
    if cutoff is None:
        raise QueryServiceUnavailable("query service is unavailable")
    cutoff = cutoff.astimezone(timezone.utc)
    if window_start > cutoff:
        return None
    return window_start, cutoff


def _exact_request_partition_evidence(
    dataset: DatasetDefinition,
    request: QueryRequest,
) -> tuple[str, str] | None:
    """Bind receipt authority only for an exact declared partition query.

    The registry guarantees the single-partition completeness shape.  Other
    request shapes deliberately retain dataset-wide evidence, so a range or
    unbounded query cannot accidentally inherit one partition's receipt.
    """

    active_bindings = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )
    policies = tuple(
        binding.response_completeness for binding in active_bindings
    )
    if not policies or any(
        policy is None
        or policy.strategy != "single_partition_unique_primary_key"
        or policy.partition_field is None
        or policy.request_partition_key is None
        for policy in policies
    ):
        return None
    policy_partition_fields = {
        policy.partition_field for policy in policies if policy is not None
    }
    if len(policy_partition_fields) != 1:
        return None
    policy_partition_field = next(iter(policy_partition_fields))
    partition_field = dataset.partition_field or policy_partition_field
    if (
        dataset.partition_field is not None
        and dataset.partition_field != policy_partition_field
    ):
        return None
    clause = request.filters.get(partition_field)
    if not isinstance(clause, MappingProxyType) or tuple(clause) != ("eq",):
        return None
    request_keys = {
        policy.request_partition_key for policy in policies if policy is not None
    }
    if len(request_keys) != 1:
        return None
    field = next(field for field in dataset.fields if field.name == partition_field)
    operator, values = _validate_filter_clause(field, clause, dataset=dataset)
    if operator != "eq" or len(values) != 1 or type(values[0]) is not str:
        return None
    return next(iter(request_keys)), values[0]


def _exact_session_minute_slot(
    dataset: DatasetDefinition,
    request: QueryRequest,
    *,
    now: datetime,
) -> datetime | None:
    """Resolve an explicit historical slot for a no-window minute dataset."""

    if not (
        dataset.cadence_class == "session_minute"
        and dataset.partition_field is None
        and dataset.as_of_field is None
        and dataset.range_field is None
    ):
        return None
    clause = request.filters.get("time")
    if not isinstance(clause, MappingProxyType) or tuple(clause) != ("eq",):
        return None
    active_bindings = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )
    if (
        not any(field.name == "time" for field in dataset.fields)
        or not active_bindings
        or any(
            binding.response_completeness is None
            or binding.response_completeness.snapshot_field != "time"
            for binding in active_bindings
        )
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    try:
        normalized = _normalize_data_through(clause["eq"], dataset)
        slot = datetime.fromisoformat(normalized)
    except (TypeError, ValueError, QueryServiceUnavailable):
        raise QueryServiceUnavailable("query service is unavailable") from None
    if slot.tzinfo is None or slot.utcoffset() is None or slot > now:
        raise QueryServiceUnavailable("query service is unavailable")
    return slot


def _exact_session_minute_receipt_ids(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    slot: datetime,
    *,
    now: datetime,
) -> tuple[str, ...]:
    histories = validated_receipt_history_for_dataset(
        conn,
        registry,
        dataset,
        now=now,
    )
    if dataset.dataset_id in histories.failures_by_dataset:
        raise RuntimeProjectionError("receipt history authority is invalid")
    slot_value = slot.isoformat(
        timespec="microseconds" if slot.microsecond else "seconds"
    )
    active_config_keys = {
        (binding.provider, provider_ingest_config_hash(dataset, binding))
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    }
    entries = [
        entry
        for entry in histories.entries_by_dataset.get(dataset.dataset_id, ())
        if entry.status == "success"
        and entry.cohort_status == "success"
        and entry.data_through is not None
        and _normalize_data_through(entry.data_through, dataset) == slot_value
        and entry.finished_at <= now
        and (entry.provider, entry.config_hash) in active_config_keys
    ]
    providers = {entry.provider for entry in entries}
    configs = {entry.config_hash for entry in entries}
    data_throughs = {
        _normalize_data_through(entry.data_through, dataset) for entry in entries
    }
    if (
        not entries
        or len(providers) != 1
        or len(configs) != 1
        or data_throughs != {slot_value}
    ):
        return ()
    # Correction overlap can observe one closed bar in multiple independently
    # complete executions.  Keep every validated receipt eligible so immutable
    # append-only facts retain their original receipt authority; row proof
    # classification below still rejects a returned page that mixes collection
    # sequences when the caller requests per-row proofs.
    return tuple(sorted(entry.receipt_id for entry in entries))


def _execution_query_hash(
    request: QueryRequest,
    options: QueryExecutionOptions,
    dataset: DatasetDefinition,
    prepared: _PreparedQuery,
    *,
    resolved_partition: object,
) -> str:
    public_hash = normalized_query_hash(
        request,
        resolved_dataset_id=dataset.dataset_id,
        resolved_schema_version=dataset.schema_version,
        effective_fields=prepared.fields,
        effective_order=tuple(
            f"{field_name}:{direction}" for field_name, direction in prepared.order
        ),
        requested_as_of=prepared.as_of.requested_as_of,
        resolved_as_of=prepared.as_of.resolved_as_of,
        options=options,
        resolved_partition=resolved_partition,
    )
    private_routing_payload: dict[str, object] = {
        "primary_table": _PROVIDER_NATIVE_TABLE,
        "storage_kind": _PROVIDER_NATIVE_STORAGE_KIND,
        "providers": list(_provider_native_providers(dataset)),
        "schema_major": _provider_native_schema_major(dataset),
        "row_key_strategy": dataset.read_model_adapter.row_key_strategy,
    }
    private_routing = _digest(private_routing_payload)
    return _digest([public_hash, private_routing])


def _validated_cursor_sort_key(
    sort_key: tuple[object, ...],
    prepared: _PreparedQuery,
    dataset: DatasetDefinition,
) -> tuple[object, ...]:
    expected_size = 2 * len(prepared.order) + 2
    if type(sort_key) is not tuple or len(sort_key) != expected_size:
        raise InvalidCursor("cursor sort key is invalid")
    field_map = {field.name: field for field in dataset.fields}
    for index, (field_name, _direction) in enumerate(prepared.order):
        rank = sort_key[2 * index]
        value = sort_key[2 * index + 1]
        field = field_map[field_name]
        if type(rank) is not int or rank not in {0, 1}:
            raise InvalidCursor("cursor sort key is invalid")
        if rank == 1:
            if value is not None:
                raise InvalidCursor("cursor sort key is invalid")
        else:
            if value is None:
                raise InvalidCursor("cursor sort key is invalid")
            try:
                _validate_typed_value(
                    value,
                    field,
                    operator="eq",
                    name=f"cursor.{field_name}",
                )
            except (QueryServiceUnavailable, QueryValidationError):
                raise InvalidCursor("cursor sort key is invalid") from None
    provider, row_key = sort_key[-2:]
    if provider not in _provider_native_providers(dataset):
        raise InvalidCursor("cursor sort key is invalid")
    if (
        type(row_key) is not str
        or not row_key
        or row_key != row_key.strip()
        or len(row_key) > 256
    ):
        raise InvalidCursor("cursor sort key is invalid")
    return sort_key


def _compile_keyset_predicate(
    prepared: _PreparedQuery,
    sort_key: tuple[object, ...],
    dataset: DatasetDefinition,
) -> tuple[str, list[object]]:
    branches: list[str] = []
    branch_params: list[list[object]] = []
    prefix_sql: list[str] = []
    prefix_params: list[object] = []
    for index, (field_name, direction) in enumerate(prepared.order):
        identifier = _field_expression(dataset, field_name)
        rank_expression = f"CASE WHEN {identifier} IS NULL THEN 1 ELSE 0 END"
        rank = sort_key[2 * index]
        value = sort_key[2 * index + 1]

        branches.append(" AND ".join([*prefix_sql, f"{rank_expression} > ?"]))
        branch_params.append([*prefix_params, rank])
        if rank == 0:
            comparator = ">" if direction == "asc" else "<"
            branches.append(
                " AND ".join(
                    [
                        *prefix_sql,
                        f"{rank_expression} = ?",
                        f"{identifier} {comparator} ?",
                    ]
                )
            )
            branch_params.append([*prefix_params, rank, value])
        prefix_sql.extend((f"{rank_expression} = ?", f"{identifier} IS ?"))
        prefix_params.extend((rank, value))

    provider, row_key = sort_key[-2:]
    provider_identifier = _quote_identifier("provider")
    row_key_identifier = _quote_identifier("row_key")
    branches.append(" AND ".join([*prefix_sql, f"{provider_identifier} > ?"]))
    branch_params.append([*prefix_params, provider])
    branches.append(
        " AND ".join(
            [
                *prefix_sql,
                f"{provider_identifier} = ?",
                f"{row_key_identifier} > ?",
            ]
        )
    )
    branch_params.append([*prefix_params, provider, row_key])
    params = [value for values in branch_params for value in values]
    compiled = "(" + ") OR (".join(branches) + ")"
    return f"({compiled})", params


def _runtime_metadata(
    dataset: DatasetDefinition,
    prepared: _PreparedQuery,
    evidence: DatasetRuntimeEvidence,
    watermark: str,
    *,
    historical_partition_compatibility: bool = False,
) -> tuple[dict[str, object], bool]:
    projection = evidence.projection
    if projection.dataset_id != dataset.dataset_id or projection.state not in {
        "success",
        "empty",
        "unobserved",
        "paused",
        "failed",
        "stale",
    }:
        raise QueryServiceUnavailable("query service is unavailable")
    expected_degraded = projection.state not in {"success", "empty"}
    if (
        type(projection.degraded) is not bool
        or projection.degraded != expected_degraded
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    reasons: list[str] = []
    for reason in projection.reasons:
        if (
            type(reason) is not str
            or not reason
            or len(reason) > 128
            or re.fullmatch(r"[a-z0-9_]+", reason) is None
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        reasons.append(reason)
    reasons = sorted(set(reasons))

    current_complete = bool(
        evidence.current_receipt_status is not None
        and evidence.current_providers
        and type(projection.receipt_id) is str
        and projection.receipt_id
        and type(projection.observed_at) is str
        and projection.observed_at
    )
    prior_complete = bool(
        type(evidence.last_success_receipt_id) is str
        and evidence.last_success_receipt_id
        and evidence.last_success_providers
        and type(evidence.last_success_data_through) is str
        and evidence.last_success_data_through
    )

    state = projection.state
    active_bindings = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )
    response_completeness_unverified = bool(
        state in {"success", "empty"}
        and any(
            binding.response_completeness is None for binding in active_bindings
        )
    )
    freshness_watermark_unverified = bool(
        response_completeness_unverified
        and any(
            binding.request_window_policy is not None for binding in active_bindings
        )
        and dataset.as_of_field is None
        and dataset.range_field is None
        and dataset.partition_field is None
    )
    if response_completeness_unverified:
        reasons = sorted(set([*reasons, _RESPONSE_COMPLETENESS_UNVERIFIED]))
    if freshness_watermark_unverified:
        reasons = sorted(set([*reasons, _FRESHNESS_WATERMARK_UNVERIFIED]))
    allow_invalid_time_current_rows = False
    if state == "success":
        if (
            projection.degraded
            or evidence.current_receipt_status != "success"
            or not current_complete
            or projection.data_through is None
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        allow_rows = True
        lineage_complete = True
    elif state == "empty":
        if (
            projection.degraded
            or evidence.current_receipt_status != "empty"
            or not current_complete
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        allow_rows = False
        lineage_complete = True
    elif state in {"unobserved", "paused"}:
        allow_rows = False
        lineage_complete = False
    elif state == "failed":
        allow_invalid_time_current_rows = bool(
            current_complete
            and evidence.current_receipt_status == "success"
            and projection.data_through is None
            and type(projection.reasons) is tuple
            and projection.reasons == ("invalid_data_through",)
        )
        if allow_invalid_time_current_rows:
            allow_rows = True
            lineage_complete = True
        else:
            if evidence.current_receipt_status not in {None, "failed"}:
                raise QueryServiceUnavailable("query service is unavailable")
            allow_rows = False
            lineage_complete = current_complete or prior_complete
    else:
        if evidence.current_receipt_status not in {"success", "empty"}:
            raise QueryServiceUnavailable("query service is unavailable")
        allow_rows = prior_complete
        lineage_complete = prior_complete

    if allow_invalid_time_current_rows:
        data_through = None
    elif state in {"success", "empty"} or allow_rows:
        try:
            data_through = _normalize_data_through(projection.data_through, dataset)
        except QueryServiceUnavailable:
            raise QueryServiceUnavailable("query service is unavailable") from None
        if state == "success" or allow_rows:
            if data_through is None:
                raise QueryServiceUnavailable("query service is unavailable")
    else:
        try:
            data_through = _normalize_data_through(projection.data_through, dataset)
        except QueryServiceUnavailable:
            data_through = None
            reasons = sorted(set([*reasons, "invalid_data_through"]))
    if freshness_watermark_unverified:
        data_through = None

    if current_complete:
        try:
            observed_at = _normalize_aware_timestamp(projection.observed_at)
        except QueryServiceUnavailable:
            raise QueryServiceUnavailable("query service is unavailable") from None
        receipt_id: str | None = projection.receipt_id
    else:
        observed_at = None
        receipt_id = None

    evidence_as_of = _evidence_as_of(prepared)
    if evidence_as_of is not None:
        permitted_receipt_ids = frozenset(evidence.as_of_success_receipt_ids)
        if state == "success" and (
            receipt_id not in permitted_receipt_ids
            or not set(evidence.current_receipt_ids).issubset(
                permitted_receipt_ids
            )
            or not set(evidence.last_success_receipt_ids).issubset(
                permitted_receipt_ids
            )
        ):
            raise QueryServiceUnavailable("query service is unavailable")
        observation_cutoff_utc = evidence_as_of.astimezone(timezone.utc)
        try:
            data_cutoff_utc = datetime.fromisoformat(
                prepared.as_of.resolved_as_of or ""
            ).astimezone(timezone.utc)
        except ValueError:
            raise QueryServiceUnavailable("query service is unavailable") from None
        if data_through is not None:
            try:
                data_through_value = datetime.fromisoformat(data_through)
            except ValueError:
                raise QueryServiceUnavailable(
                    "query service is unavailable"
                ) from None
            if (
                data_through_value.tzinfo is None
                or data_through_value.utcoffset() is None
                or data_through_value.astimezone(timezone.utc) > data_cutoff_utc
            ):
                raise QueryServiceUnavailable("query service is unavailable")
        if observed_at is not None:
            try:
                observed_value = datetime.fromisoformat(observed_at)
            except ValueError:
                raise QueryServiceUnavailable(
                    "query service is unavailable"
                ) from None
            if (
                observed_value.tzinfo is None
                or observed_value.utcoffset() is None
                or observed_value.astimezone(timezone.utc)
                > observation_cutoff_utc
            ):
                raise QueryServiceUnavailable("query service is unavailable")

    providers: set[str] = set()
    provider_config_hashes: set[tuple[str, str]] = set()
    if current_complete:
        providers.update(evidence.current_providers)
        provider_config_hashes.update(evidence.current_provider_config_hashes)
    # A current successful receipt is the authority for the current complete
    # partition.  Older successful receipts can legitimately have a different
    # config hash after a schema-major contract correction; folding them into
    # the current transport proof would incorrectly degrade an otherwise
    # verified current response.  Stale fallback still binds both cohorts.
    if allow_rows and prior_complete and state != "success":
        providers.update(evidence.last_success_providers)
        provider_config_hashes.update(evidence.last_success_provider_config_hashes)
    if not lineage_complete:
        providers.clear()
        provider_config_hashes.clear()
    transport_profile = None
    if len(providers) == 1:
        try:
            transport_profile = provider_transport_profile(next(iter(providers)))
        except KeyError:
            transport_profile = None
    expected_provider_config_hashes = {
        (
            binding.provider,
            provider_ingest_config_hash(dataset, binding),
        )
        for binding in dataset.provider_bindings
        if binding.provider in providers
    }
    if historical_partition_compatibility:
        predecessor = replace(dataset, partition_field=None)
        compatible_provider_config_hashes = {
            *expected_provider_config_hashes,
            *{
                (
                    binding.provider,
                    provider_ingest_config_hash(predecessor, binding),
                )
                for binding in dataset.provider_bindings
                if binding.provider in providers
            },
        }
        transport_profile_proven = bool(
            transport_profile is not None
            and provider_config_hashes
            and provider_config_hashes.issubset(
                compatible_provider_config_hashes
            )
            and {provider for provider, _config_hash in provider_config_hashes}
            == providers
        )
    else:
        transport_profile_proven = (
            transport_profile is not None
            and provider_config_hashes == expected_provider_config_hashes
        )
    transport_profile_unverified = bool(
        providers
        & {
            TUSHARE_DATA_PROVIDER,
            BINANCE_SPOT_DATA_PROVIDER,
            BINANCE_USDM_DATA_PROVIDER,
            BINANCE_USDM_DUMP_DATA_PROVIDER,
            BINANCE_USDM_RELAY_DATA_PROVIDER,
        }
    ) and not transport_profile_proven
    if transport_profile_unverified:
        lineage_complete = False
        allow_rows = False
        reasons = sorted(set([*reasons, "transport_profile_unverified"]))
    transport_service = (
        transport_profile["transport_service"] if transport_profile_proven else None
    )
    effective_degraded = bool(
        projection.degraded
        or transport_profile_unverified
        or response_completeness_unverified
    )
    effective_state = (
        "failed"
        if transport_profile_unverified
        else "partial"
        if response_completeness_unverified
        else state
    )
    freshness_state = (
        "unknown"
        if freshness_watermark_unverified
        else "fresh"
        if state == "success" and not transport_profile_unverified
        else effective_state
    )

    metadata = {
        "state": (
            "ready"
            if effective_state == "success" and not effective_degraded
            else effective_state
        ),
        "runtime_state": state,
        "degraded": effective_degraded,
        "freshness": {
            "state": freshness_state,
            "stale": state == "stale",
            "sla_seconds": dataset.freshness_sla_seconds,
        },
        "quality": {
            "state": (
                "valid"
                if effective_state in {"success", "empty"}
                else "degraded"
            ),
            "valid": effective_state in {"success", "empty"},
            "evidence": reasons,
        },
        "lineage": {
            "state": "complete" if lineage_complete else "incomplete",
            "complete": lineage_complete,
            "provider_neutral": True,
            "authority": "sqlite_ingest_receipts",
            "dataset_id": dataset.dataset_id,
            "providers": sorted(providers),
            "transport_service": transport_service,
            "transport_profile_id": (
                transport_profile["profile_id"]
                if transport_service is not None
                else None
            ),
            "transport_profile_sha256": (
                transport_profile["profile_sha256"]
                if transport_service is not None
                else None
            ),
            "receipt_watermark": watermark,
        },
        "receipt_id": receipt_id,
        "data_through": data_through,
        "observed_at": observed_at,
        "requested_as_of": prepared.as_of.requested_as_of,
        "resolved_as_of": prepared.as_of.resolved_as_of,
        "reasons": reasons,
    }
    return metadata, allow_rows


def _merge_provider_native_quality(
    metadata: dict[str, object],
    *,
    dataset_degraded: bool,
    page_issues: set[str],
) -> None:
    if type(dataset_degraded) is not bool or any(
        type(issue) is not str or _PROVIDER_NATIVE_ISSUE_RE.fullmatch(issue) is None
        for issue in page_issues
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    quality = metadata.get("quality")
    if type(quality) is not dict:
        raise QueryServiceUnavailable("query service is unavailable")
    runtime_evidence = quality.get("evidence")
    if type(runtime_evidence) is not list or any(
        type(reason) is not str for reason in runtime_evidence
    ):
        raise QueryServiceUnavailable("query service is unavailable")
    provider_quality_degraded = dataset_degraded or bool(page_issues)
    evidence = set(runtime_evidence)
    if dataset_degraded:
        evidence.add("provider_dataset_quality_degraded")
    evidence.update(page_issues)
    runtime_quality_valid = quality.get("valid") is True
    quality["valid"] = runtime_quality_valid and not provider_quality_degraded
    quality["state"] = "valid" if quality["valid"] else "degraded"
    quality["evidence"] = sorted(evidence)
    runtime_degraded = metadata.get("degraded")
    if type(runtime_degraded) is not bool:
        raise QueryServiceUnavailable("query service is unavailable")
    metadata["degraded"] = runtime_degraded or provider_quality_degraded
    if metadata["degraded"] and metadata.get("state") == "ready":
        runtime_state = metadata.get("runtime_state")
        if type(runtime_state) is not str or not runtime_state:
            raise QueryServiceUnavailable("query service is unavailable")
        metadata["state"] = runtime_state


class QueryService:
    """Execute registry-owned queries from injected immutable dependencies."""

    __slots__ = ("_db_path", "_registry", "_cursor_codec", "_validation_cache")

    def __init__(
        self,
        *,
        db_path: Path,
        registry: DatasetRegistry,
        cursor_codec: SignedCursorCodec,
    ) -> None:
        if not isinstance(db_path, Path):
            raise TypeError("db_path must be pathlib.Path")
        canonical_path = Path(os.path.abspath(os.fspath(db_path)))
        if db_path != canonical_path:
            raise ValueError("db_path must be canonical")
        if not isinstance(registry, DatasetRegistry):
            raise TypeError("registry must be DatasetRegistry")
        if not isinstance(cursor_codec, SignedCursorCodec):
            raise TypeError("cursor_codec must be SignedCursorCodec")
        self._db_path = canonical_path
        self._registry = registry
        self._cursor_codec = cursor_codec
        # Process-wide receipt-validation memo shared with the catalog side so
        # per-query evidence projections only validate receipts written since
        # the previous query instead of the full append-only history (#297).
        self._validation_cache: dict = {}

    def execute(
        self,
        request: QueryRequest,
        *,
        access: QueryAccessContext,
        now: object,
        request_id: str,
        options: QueryExecutionOptions = QueryExecutionOptions(),
    ) -> dict[str, object]:
        """Validate one provider-neutral query before opening SQLite."""

        validated_now = _validated_now(now)
        canonical_request_id = _canonical_request_id(request_id)
        validated_request = _revalidate_request(request)
        validated_access = _revalidate_access(access)
        validated_options = _revalidate_options(options)
        _enforce_root_budgets(
            validated_request,
            validated_options,
            self._registry,
        )
        try:
            dataset = self._registry.resolve(validated_request.dataset_id)
        except KeyError:
            raise QueryDatasetNotFound("dataset is not available") from None
        if not is_initial_release_eligible(dataset):
            raise QueryDatasetNotFound("dataset is not available")
        prepared = _prepare_query(
            validated_request,
            validated_options,
            dataset,
            self._registry,
            now=validated_now,
        )
        with (
            _query_snapshot(self._db_path) as conn,
            _sqlite_progress_budget(
                conn,
                self._registry.query_defaults.sqlite_progress_steps,
            ),
        ):
            try:
                if not conn.in_transaction:
                    conn.execute("BEGIN")
                queryability = inspect_dataset_queryability(conn, dataset)
            except (
                KeyError,
                TypeError,
                ValueError,
                sqlite3.Error,
                RuntimeProjectionError,
            ):
                raise QueryServiceUnavailable("query service is unavailable") from None
            if not queryability.queryable:
                raise QueryDatasetNotFound("dataset is not available")
            grants = set(validated_access.scopes)
            authorized = bool(
                dataset.required_scope in grants
                or grants & _AGGREGATE_SCOPES
                or dataset.dataset_id in validated_access.allowed_dataset_ids
            )
            if not authorized:
                raise QueryAccessDenied("query access is denied")
            try:
                request_partition = _exact_request_partition_evidence(
                    dataset,
                    validated_request,
                )
                exact_session_minute_slot = _exact_session_minute_slot(
                    dataset,
                    validated_request,
                    now=validated_now,
                )
                if (
                    prepared.as_of.resolved_as_of is not None
                    and dataset.partition_field is None
                ):
                    # Null business partitions gain current-cohort scoping in
                    # this compatibility path only; historical queries retain
                    # their established explicit-as_of receipt semantics.
                    request_partition = None
                receipt_collection_window = _as_of_receipt_collection_window(
                    validated_request,
                    dataset,
                    prepared,
                )
                evidence = project_dataset_runtime_evidence(
                    conn,
                    dataset,
                    now=validated_now,
                    registry=self._registry,
                    evidence_as_of=_evidence_as_of(prepared),
                    data_through_as_of=(
                        None
                        if prepared.as_of.resolved_as_of is None
                        else datetime.fromisoformat(prepared.as_of.resolved_as_of)
                    ),
                    receipt_collection_window=receipt_collection_window,
                    request_partition=request_partition,
                    validation_cache=self._validation_cache,
                )
                exact_session_minute_receipt_ids = None
                if exact_session_minute_slot is not None:
                    exact_session_minute_receipt_ids = _exact_session_minute_receipt_ids(
                        conn,
                        self._registry,
                        dataset,
                        exact_session_minute_slot,
                        now=validated_now,
                    )
                    if not exact_session_minute_receipt_ids:
                        raise QueryServiceUnavailable("query service is unavailable")
                current_partition_receipt_ids: tuple[str, ...] | None = None
                if (
                    request_partition is not None
                    and prepared.as_of.resolved_as_of is None
                ):
                    current_partition_receipt_ids = evidence.current_receipt_ids
                    if not current_partition_receipt_ids:
                        raise QueryServiceUnavailable(
                            "query service is unavailable"
                        )
                if exact_session_minute_receipt_ids is not None:
                    current_partition_receipt_ids = exact_session_minute_receipt_ids
                provider_native_dataset_degraded = (
                    _provider_native_dataset_quality_degraded(
                        conn,
                        dataset,
                        permitted_receipt_ids=current_partition_receipt_ids,
                    )
                )
                _provider_native_validate_operation_fields(
                    conn,
                    dataset,
                    validated_request,
                    validated_options,
                    prepared,
                    dataset_degraded=provider_native_dataset_degraded,
                    permitted_receipt_ids=current_partition_receipt_ids,
                )
                predicates, params = _base_predicates(
                    validated_request,
                    validated_options,
                    dataset,
                    prepared,
                )
                current_receipt_predicate, current_receipt_params = (
                    _provider_native_receipt_predicate(
                        current_partition_receipt_ids
                    )
                )
                if current_receipt_predicate is not None:
                    predicates.append(current_receipt_predicate)
                    params.extend(current_receipt_params)
                if prepared.as_of.resolved_as_of is not None:
                    if not evidence.as_of_success_receipt_ids:
                        raise QueryServiceUnavailable(
                            "query service is unavailable"
                        )
                    predicates.append(
                        f"{_quote_identifier('receipt_id')} IN "
                        "(SELECT value FROM json_each(?) WHERE type = 'text')"
                    )
                    params.append(
                        json.dumps(
                            list(evidence.as_of_success_receipt_ids),
                            ensure_ascii=True,
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    )
                resolved_partition: object = None
                if validated_options.latest_partition:
                    if dataset.partition_field is None:
                        raise QueryServiceUnavailable("query service is unavailable")
                    partition_field = next(
                        field
                        for field in dataset.fields
                        if field.name == dataset.partition_field
                    )
                    partition_sql = (
                        "SELECT MAX("
                        f"{_field_expression(dataset, dataset.partition_field)}) "
                        f"FROM main.{_quote_identifier(_PROVIDER_NATIVE_TABLE)}"
                        " INDEXED BY "
                        + _quote_identifier(_PROVIDER_NATIVE_PARTITION_INDEX)
                        + f"{_where_clause(predicates)}"
                    )
                    partition_row = conn.execute(partition_sql, params).fetchone()
                    if partition_row is None or len(partition_row) != 1:
                        raise QueryServiceUnavailable("query service is unavailable")
                    resolved_partition = partition_row[0]
                    if resolved_partition is not None:
                        try:
                            resolved_partition = _validate_typed_value(
                                resolved_partition,
                                partition_field,
                                operator="eq",
                                name=f"stored.{partition_field.name}",
                            )
                        except QueryValidationError:
                            raise QueryServiceUnavailable(
                                "query service is unavailable"
                            ) from None
                        predicates.append(
                            f"{_field_expression(dataset, dataset.partition_field)} = ?"
                        )
                        params.append(resolved_partition)

                watermark = _receipt_watermark(dataset, evidence)
                query_hash = _execution_query_hash(
                    validated_request,
                    validated_options,
                    dataset,
                    prepared,
                    resolved_partition=resolved_partition,
                )
                if validated_request.cursor is not None:
                    claims = self._cursor_codec.decode(
                        validated_request.cursor,
                        expected=CursorExpectation(
                            kind="query",
                            catalog_version=public_catalog_version(self._registry),
                            dataset_id=dataset.dataset_id,
                            schema_major=_schema_major(dataset),
                            query_hash=query_hash,
                            policy_id=validated_access.policy_id,
                            receipt_watermark=watermark,
                        ),
                        now=validated_now,
                    )
                    cursor_key = _validated_cursor_sort_key(
                        claims.sort_key,
                        prepared,
                        dataset,
                    )
                    cursor_sql, cursor_params = _compile_keyset_predicate(
                        prepared,
                        cursor_key,
                        dataset,
                    )
                    predicates.append(cursor_sql)
                    params.extend(cursor_params)

                metadata, allow_rows = _runtime_metadata(
                    dataset,
                    prepared,
                    evidence,
                    watermark,
                    historical_partition_compatibility=(
                        receipt_collection_window is not None
                    ),
                )
                if exact_session_minute_receipt_ids is not None:
                    # Keep the latest runtime state in metadata, but scope row
                    # selection to the independently validated historical slot.
                    allow_rows = True
                rows: list[tuple[object, ...]] = []
                row_proofs: Mapping[str, ValidatedRowReceiptProof] = {}
                if allow_rows and not (
                    validated_options.latest_partition and resolved_partition is None
                ):
                    field_map = {field.name: field for field in dataset.fields}
                    order_sql: list[str] = []
                    for field_name, direction in prepared.order:
                        identifier = _field_expression(dataset, field_name)
                        order_sql.append(
                            f"CASE WHEN {identifier} IS NULL THEN 1 ELSE 0 END ASC"
                        )
                        order_sql.append(f"{identifier} {direction.upper()}")
                    select_parts = [
                        _quote_identifier("payload_json"),
                        _quote_identifier("provider"),
                        _quote_identifier("row_key"),
                        _quote_identifier("quality_state"),
                        _quote_identifier("quality_issues_json"),
                        _quote_identifier("receipt_id"),
                        *(
                            _field_expression(dataset, field_name)
                            for field_name, _direction in prepared.order
                        ),
                    ]
                    order_sql.extend(
                        (
                            f"{_quote_identifier('provider')} ASC",
                            f"{_quote_identifier('row_key')} ASC",
                        )
                    )
                    row_sql = (
                        f"SELECT {', '.join(select_parts)} "
                        f"FROM {_provider_native_query_table(dataset, validated_request)}"
                        f"{_where_clause(predicates)} ORDER BY "
                        + ", ".join(order_sql)
                        + " LIMIT ?"
                    )
                    for _ in range(_MAX_FAILED_COHORT_FILTER_PASSES):
                        row_cursor = conn.execute(
                            row_sql,
                            [*params, validated_request.limit + 1],
                        )
                        rows = [
                            tuple(row)
                            for row in row_cursor.fetchmany(
                                validated_request.limit + 1
                            )
                        ]
                        selected_rows = rows[: validated_request.limit]
                        proof_selection = _classified_page_receipt_proofs(
                            conn,
                            self._registry,
                            dataset,
                            tuple(selected_rows),
                            now=validated_now,
                        )
                        excluded_receipt_ids = (
                            proof_selection.failed_cohort_success_receipt_ids
                        )
                        if not excluded_receipt_ids:
                            row_proofs = proof_selection.proofs
                            break
                        excluded_predicate, excluded_params = (
                            _provider_native_receipt_predicate(
                                excluded_receipt_ids
                            )
                        )
                        assert excluded_predicate is not None
                        predicates.append(f"NOT ({excluded_predicate})")
                        params.extend(excluded_params)
                        row_sql = (
                            f"SELECT {', '.join(select_parts)} "
                            f"FROM {_provider_native_query_table(dataset, validated_request)}"
                            f"{_where_clause(predicates)} ORDER BY "
                            + ", ".join(order_sql)
                            + " LIMIT ?"
                        )
                    else:
                        raise QueryServiceUnavailable(
                            "query service is unavailable"
                        )

                has_more = len(rows) > validated_request.limit
                selected_rows = rows[: validated_request.limit]
                data: list[dict[str, object]] = []
                sort_keys: list[tuple[object, ...]] = []
                page_quality_issues: set[str] = set()
                if selected_rows:
                    field_map = {field.name: field for field in dataset.fields}
                    for row in selected_rows:
                        if len(row) != len(prepared.order) + 6:
                            raise QueryServiceUnavailable(
                                "query service is unavailable"
                            )
                        payload = _parse_provider_native_payload(row[0])
                        provider = row[1]
                        row_key = row[2]
                        row_receipt_id = row[5]
                        if (
                            provider not in _provider_native_providers(dataset)
                            or type(row_key) is not str
                            or not row_key
                            or row_key != row_key.strip()
                            or len(row_key) > 256
                            or type(row_receipt_id) is not str
                            or not row_receipt_id
                            or (
                                prepared.as_of.resolved_as_of is not None
                                and row_receipt_id
                                not in evidence.as_of_success_receipt_ids
                            )
                            or (
                                current_partition_receipt_ids is not None
                                and row_receipt_id
                                not in current_partition_receipt_ids
                            )
                        ):
                            raise QueryServiceUnavailable(
                                "query service is unavailable"
                            )
                        issues = _parse_provider_native_quality(row[3], row[4])
                        page_quality_issues.update(issues)
                        projected = (
                            dict(payload)
                            if prepared.provider_native_full_payload
                            else {
                                field_name: payload[field_name]
                                for field_name in prepared.fields
                                if field_name in payload
                            }
                        )
                        data.append(projected)
                        flat_key: list[object] = []
                        for index, (field_name, _direction) in enumerate(
                            prepared.order
                        ):
                            value = row[6 + index]
                            if value is not None:
                                try:
                                    _validate_typed_value(
                                        value,
                                        field_map[field_name],
                                        operator="eq",
                                        name=f"stored.{field_name}",
                                    )
                                except QueryValidationError:
                                    raise QueryServiceUnavailable(
                                        "query service is unavailable"
                                    ) from None
                            flat_key.extend((int(value is None), value))
                        flat_key.extend((provider, row_key))
                        sort_keys.append(tuple(flat_key))

                _merge_provider_native_quality(
                    metadata,
                    dataset_degraded=provider_native_dataset_degraded,
                    page_issues=page_quality_issues,
                )
                if validated_request.include_receipt_proofs:
                    metadata["row_receipt_proofs"] = _row_receipt_proof_metadata(
                        dataset,
                        tuple(selected_rows),
                        row_proofs,
                        now=validated_now,
                    )

                next_cursor = None
                if has_more:
                    next_cursor = self._cursor_codec.encode(
                        CursorClaims(
                            kind="query",
                            catalog_version=public_catalog_version(self._registry),
                            dataset_id=dataset.dataset_id,
                            schema_major=_schema_major(dataset),
                            query_hash=query_hash,
                            policy_id=validated_access.policy_id,
                            receipt_watermark=watermark,
                            sort_key=sort_keys[-1],
                            expires_at=(
                                math.floor(validated_now.timestamp())
                                + self._registry.query_defaults.cursor_ttl_seconds
                            ),
                        )
                    )
                response = {
                    "api_version": "v1",
                    "catalog_version": public_catalog_version(self._registry),
                    "request_id": canonical_request_id,
                    "dataset_id": dataset.dataset_id,
                    "schema_version": dataset.schema_version,
                    "data": data,
                    "next_cursor": next_cursor,
                    "metadata": metadata,
                }
                try:
                    encoded = _canonical_json_bytes(response)
                except (
                    OverflowError,
                    RecursionError,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ):
                    raise QueryServiceUnavailable(
                        "query service is unavailable"
                    ) from None
                if len(encoded) > self._registry.query_defaults.max_response_bytes:
                    raise QueryBudgetError(
                        "response exceeds max_response_bytes="
                        f"{self._registry.query_defaults.max_response_bytes}"
                    )
                return response
            except (QueryBudgetError, InvalidCursor, CursorMismatch):
                raise
            except (
                AttributeError,
                CursorConfigurationError,
                KeyError,
                OverflowError,
                RecursionError,
                RuntimeProjectionError,
                StopIteration,
                TypeError,
                UnicodeError,
                ValueError,
                sqlite3.Error,
            ):
                raise QueryServiceUnavailable("query service is unavailable") from None
