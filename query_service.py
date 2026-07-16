"""Bounded provider-neutral queries over one verified SQLite snapshot."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
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
    open_verified_read_model_snapshot,
    project_dataset_runtime_evidence,
)


_AGGREGATE_SCOPES = frozenset({"external_read", "read", "full", "*"})
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z")
_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ORDER_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(asc|desc)\Z")
_FILTER_OPERATORS = frozenset({"eq", "in", "gte", "lte", "between"})
_EVIDENCE_ISO_TIMESTAMP_RE = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?"
    r"(?P<zone>Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?\Z"
)


@dataclass(frozen=True)
class _PreparedQuery:
    fields: tuple[str, ...]
    order: tuple[tuple[str, str], ...]
    as_of: ResolvedQueryAsOf
    empty_interval: bool


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


def _validate_filter_clause(
    field: DatasetField,
    clause: object,
    *,
    range_field: str | None,
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
    if field.name == range_field:
        dates = tuple(
            _parse_yyyymmdd(
                value,
                f"filters.{field.name}.{operator}",
            )
            for value in validated
        )
        if operator == "between" and dates[0] > dates[1]:
            raise QueryValidationError(
                f"filters.{field.name}.between lower bound exceeds upper bound"
            )
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
    dates = tuple(
        _parse_yyyymmdd(
            value,
            f"filters.{dataset.range_field}.{operator}",
        )
        for value in values
    )
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
    effective_fields = request.fields or dataset.default_projection
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
            range_field=dataset.range_field,
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

    raw_order = request.order or tuple(
        f"{field_name}:asc" for field_name in dataset.primary_key
    )
    order: list[tuple[str, str]] = []
    seen: set[str] = set()
    for term in raw_order:
        field_name, direction = term.rsplit(":", 1)
        field = field_map.get(field_name)
        if field is None or not field.selectable or not field.sortable:
            raise QueryValidationError(f"field {field_name!r} is not sortable")
        order.append((field_name, direction))
        seen.add(field_name)
    for field_name in dataset.primary_key:
        if field_name not in seen:
            field = field_map.get(field_name)
            if field is None or not field.selectable or not field.sortable:
                raise QueryServiceUnavailable("query service is unavailable")
            order.append((field_name, "asc"))

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
            dataset.range_field is not None
            and isinstance(request.filters.get(dataset.range_field), MappingProxyType)
            and "gte" in request.filters[dataset.range_field]
            and span == 0
            and _parse_yyyymmdd(
                request.filters[dataset.range_field]["gte"],
                f"filters.{dataset.range_field}.gte",
            )
            > (
                now.astimezone(ZoneInfo(dataset.timezone)).date()
                if as_of.resolved_as_of is None
                else datetime.fromisoformat(as_of.resolved_as_of)
                .astimezone(ZoneInfo(dataset.timezone))
                .date()
            )
        ),
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


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _compile_scalar_filter(
    identifier: str,
    operator: str,
    values: tuple[object, ...],
) -> tuple[str, list[object]]:
    if operator == "eq":
        if values[0] is None:
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
            parts.append(f"{identifier} IS NULL")
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
    for fixed in dataset.read_model_adapter.fixed_field_filters:
        identifier = _quote_identifier(fixed.field)
        placeholders = ", ".join("?" for _ in fixed.allowed_values)
        predicates.append(f"{identifier} IN ({placeholders})")
        params.extend(fixed.allowed_values)
    field_map = {field.name: field for field in dataset.fields}
    for field_name, clause in request.filters.items():
        operator, values = _validate_filter_clause(
            field_map[field_name],
            clause,
            range_field=dataset.range_field,
        )
        sql, values_params = _compile_scalar_filter(
            _quote_identifier(field_name),
            operator,
            values,
        )
        predicates.append(sql)
        params.extend(values_params)
    if prepared.as_of.field is not None:
        predicates.append(f"{_quote_identifier(prepared.as_of.field)} <= ?")
        params.append(prepared.as_of.encoded_cutoff)
    if options.any_of_eq_filters:
        branches: list[str] = []
        branch_params: list[object] = []
        for field_name, value in options.any_of_eq_filters:
            sql, values_params = _compile_scalar_filter(
                _quote_identifier(field_name),
                "eq",
                (value,),
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


def _validate_stored_value(value: object, field: DatasetField) -> object:
    if value is None:
        if field.nullable:
            return None
        raise QueryServiceUnavailable("query service is unavailable")
    try:
        return _validate_typed_value(
            value,
            field,
            operator="eq",
            name=f"stored.{field.name}",
        )
    except QueryValidationError:
        raise QueryServiceUnavailable("query service is unavailable") from None


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
    if len(value) == 8 and value.isascii() and value.isdigit():
        try:
            parsed_date = _parse_yyyymmdd(value, "data_through")
        except QueryValidationError:
            raise QueryServiceUnavailable("query service is unavailable") from None
        parsed = datetime.combine(parsed_date, datetime.min.time()).replace(
            tzinfo=dataset_timezone
        )
    else:
        parsed, aware = _parse_evidence_iso_timestamp(value)
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
    return _digest(
        {
            "dataset_id": dataset.dataset_id,
            "runtime_state": projection.state,
            "degraded": projection.degraded,
            "reasons": sorted(set(projection.reasons)),
            "current": {
                "receipt_id": projection.receipt_id,
                "data_through": projection.data_through,
                "observed_at": projection.observed_at,
                "status": evidence.current_receipt_status,
                "providers": list(evidence.current_providers),
            },
            "last_success": {
                "receipt_id": evidence.last_success_receipt_id,
                "data_through": evidence.last_success_data_through,
                "providers": list(evidence.last_success_providers),
            },
        }
    )


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
    private_routing = _digest(
        {
            "primary_table": dataset.read_model_adapter.primary_table,
            "fixed_field_filters": [
                [fixed.field, sorted(fixed.allowed_values)]
                for fixed in sorted(
                    dataset.read_model_adapter.fixed_field_filters,
                    key=lambda item: item.field,
                )
            ],
        }
    )
    return _digest([public_hash, private_routing])


def _validated_cursor_sort_key(
    sort_key: tuple[object, ...],
    prepared: _PreparedQuery,
    dataset: DatasetDefinition,
) -> tuple[object, ...]:
    if type(sort_key) is not tuple or len(sort_key) != 2 * len(prepared.order) + 1:
        raise InvalidCursor("cursor sort key is invalid")
    field_map = {field.name: field for field in dataset.fields}
    for index, (field_name, _direction) in enumerate(prepared.order):
        rank = sort_key[2 * index]
        value = sort_key[2 * index + 1]
        field = field_map[field_name]
        if type(rank) is not int or rank not in {0, 1}:
            raise InvalidCursor("cursor sort key is invalid")
        if rank == 1:
            if value is not None or not field.nullable:
                raise InvalidCursor("cursor sort key is invalid")
        else:
            if value is None:
                raise InvalidCursor("cursor sort key is invalid")
            try:
                _validate_stored_value(value, field)
            except QueryServiceUnavailable:
                raise InvalidCursor("cursor sort key is invalid") from None
    rowid = sort_key[-1]
    if type(rowid) is not int or rowid < -(2**63) or rowid > 2**63 - 1:
        raise InvalidCursor("cursor sort key is invalid")
    return sort_key


def _compile_keyset_predicate(
    prepared: _PreparedQuery,
    sort_key: tuple[object, ...],
) -> tuple[str, list[object]]:
    branches: list[str] = []
    branch_params: list[list[object]] = []
    prefix_sql: list[str] = []
    prefix_params: list[object] = []
    for index, (field_name, direction) in enumerate(prepared.order):
        identifier = _quote_identifier(field_name)
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

    branches.append(" AND ".join([*prefix_sql, "rowid > ?"]))
    branch_params.append([*prefix_params, sort_key[-1]])
    params = [value for values in branch_params for value in values]
    return "(" + ") OR (".join(branches) + ")", params


def _runtime_metadata(
    dataset: DatasetDefinition,
    prepared: _PreparedQuery,
    evidence: DatasetRuntimeEvidence,
    watermark: str,
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
        if evidence.current_receipt_status not in {None, "failed"}:
            raise QueryServiceUnavailable("query service is unavailable")
        allow_rows = prior_complete
        lineage_complete = current_complete or prior_complete
    else:
        if evidence.current_receipt_status not in {"success", "empty"}:
            raise QueryServiceUnavailable("query service is unavailable")
        allow_rows = prior_complete
        lineage_complete = prior_complete

    if state in {"success", "empty"} or allow_rows:
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

    if current_complete:
        try:
            observed_at = _normalize_aware_timestamp(projection.observed_at)
        except QueryServiceUnavailable:
            raise QueryServiceUnavailable("query service is unavailable") from None
        receipt_id: str | None = projection.receipt_id
    else:
        observed_at = None
        receipt_id = None

    providers: set[str] = set()
    if current_complete:
        providers.update(evidence.current_providers)
    if allow_rows and prior_complete:
        providers.update(evidence.last_success_providers)
    if not lineage_complete:
        providers.clear()

    metadata = {
        "state": "ready" if state == "success" and not projection.degraded else state,
        "runtime_state": state,
        "degraded": projection.degraded,
        "freshness": {
            "state": "fresh" if state == "success" else state,
            "stale": state == "stale",
            "sla_seconds": dataset.freshness_sla_seconds,
        },
        "quality": {
            "state": "valid" if state in {"success", "empty"} else "degraded",
            "valid": state in {"success", "empty"},
            "evidence": reasons,
        },
        "lineage": {
            "state": "complete" if lineage_complete else "incomplete",
            "complete": lineage_complete,
            "provider_neutral": True,
            "authority": "sqlite_ingest_receipts",
            "dataset_id": dataset.dataset_id,
            "providers": sorted(providers),
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


class QueryService:
    """Execute registry-owned queries from injected immutable dependencies."""

    __slots__ = ("_db_path", "_registry", "_cursor_codec")

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
                evidence = project_dataset_runtime_evidence(
                    conn,
                    dataset,
                    now=validated_now,
                    registry=self._registry,
                )
                predicates, params = _base_predicates(
                    validated_request,
                    validated_options,
                    dataset,
                    prepared,
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
                        f"{_quote_identifier(dataset.partition_field)}) "
                        "FROM main."
                        f"{_quote_identifier(dataset.read_model_adapter.primary_table)}"
                        f"{_where_clause(predicates)}"
                    )
                    partition_row = conn.execute(partition_sql, params).fetchone()
                    if partition_row is None or len(partition_row) != 1:
                        raise QueryServiceUnavailable("query service is unavailable")
                    resolved_partition = partition_row[0]
                    if resolved_partition is not None:
                        resolved_partition = _validate_stored_value(
                            resolved_partition,
                            partition_field,
                        )
                        predicates.append(
                            f"{_quote_identifier(dataset.partition_field)} = ?"
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
                    )
                    predicates.append(cursor_sql)
                    params.extend(cursor_params)

                metadata, allow_rows = _runtime_metadata(
                    dataset,
                    prepared,
                    evidence,
                    watermark,
                )
                rows: list[tuple[object, ...]] = []
                if allow_rows and not (
                    validated_options.latest_partition and resolved_partition is None
                ):
                    field_map = {field.name: field for field in dataset.fields}
                    selected_names = list(prepared.fields)
                    for field_name, _direction in prepared.order:
                        if field_name not in selected_names:
                            selected_names.append(field_name)
                    select_sql = ", ".join(
                        _quote_identifier(field_name) for field_name in selected_names
                    )
                    order_sql: list[str] = []
                    for field_name, direction in prepared.order:
                        identifier = _quote_identifier(field_name)
                        order_sql.append(
                            f"CASE WHEN {identifier} IS NULL THEN 1 ELSE 0 END ASC"
                        )
                        order_sql.append(f"{identifier} {direction.upper()}")
                    order_sql.append("rowid ASC")
                    row_sql = (
                        f"SELECT {select_sql}, rowid "
                        "FROM main."
                        f"{_quote_identifier(dataset.read_model_adapter.primary_table)}"
                        f"{_where_clause(predicates)} ORDER BY "
                        + ", ".join(order_sql)
                        + " LIMIT ?"
                    )
                    row_cursor = conn.execute(
                        row_sql,
                        [*params, validated_request.limit + 1],
                    )
                    rows = [
                        tuple(row)
                        for row in row_cursor.fetchmany(validated_request.limit + 1)
                    ]

                has_more = len(rows) > validated_request.limit
                selected_rows = rows[: validated_request.limit]
                data: list[dict[str, object]] = []
                sort_keys: list[tuple[object, ...]] = []
                if selected_rows:
                    field_map = {field.name: field for field in dataset.fields}
                    selected_names = list(prepared.fields)
                    for field_name, _direction in prepared.order:
                        if field_name not in selected_names:
                            selected_names.append(field_name)
                    for row in selected_rows:
                        if len(row) != len(selected_names) + 1:
                            raise QueryServiceUnavailable(
                                "query service is unavailable"
                            )
                        row_values = {
                            field_name: _validate_stored_value(
                                row[index],
                                field_map[field_name],
                            )
                            for index, field_name in enumerate(selected_names)
                        }
                        rowid = row[-1]
                        if (
                            type(rowid) is not int
                            or rowid < -(2**63)
                            or rowid > 2**63 - 1
                        ):
                            raise QueryServiceUnavailable(
                                "query service is unavailable"
                            )
                        data.append(
                            {
                                field_name: row_values[field_name]
                                for field_name in prepared.fields
                            }
                        )
                        flat_key: list[object] = []
                        for field_name, _direction in prepared.order:
                            value = row_values[field_name]
                            flat_key.extend((int(value is None), value))
                        flat_key.append(rowid)
                        sort_keys.append(tuple(flat_key))

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
