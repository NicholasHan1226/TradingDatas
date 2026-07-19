"""Provider-neutral request, access, and catalog-version contracts for V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone
from hashlib import sha256
import json
from math import isfinite
import re
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dataset_registry import (
    DatasetDefinition,
    DatasetRegistry,
    QueryDefaults,
    load_dataset_registry,
)


_REQUEST_KEYS = frozenset(
    {
        "dataset_id",
        "schema_major",
        "fields",
        "filters",
        "as_of",
        "order",
        "limit",
        "cursor",
    }
)
_REQUEST_REQUIRED_KEYS = frozenset({"dataset_id", "schema_major"})
_FILTER_OPERATORS = frozenset({"eq", "in", "gte", "lte", "between"})
_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z")
_ORDER_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(asc|desc)\Z")
_RFC3339_RE = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?"
    r"(?:(?P<zulu>Z)|(?P<offset_sign>[+-])"
    r"(?P<offset_hour>[01][0-9]|2[0-3]):"
    r"(?P<offset_minute>[0-5][0-9]))\Z"
)
_YYYYMMDD_RE = re.compile(r"\d{8}\Z")
_QUERY_DEFAULTS = load_dataset_registry().query_defaults


class QueryValidationError(ValueError):
    """A deterministic public request-contract violation (HTTP 400)."""


class QueryBudgetError(QueryValidationError):
    """A valid-shaped request exceeds a frozen resource budget (HTTP 413)."""


@dataclass(frozen=True)
class QueryAccessContext:
    tenant_id: str
    scopes: tuple[str, ...]
    allowed_dataset_ids: tuple[str, ...]
    policy_id: str

    def __post_init__(self) -> None:
        normalized_tenant = _canonical_non_empty_string(self.tenant_id, "tenant_id")
        normalized_scopes = _normalized_string_grants(self.scopes, "scopes")
        normalized_datasets = _normalized_string_grants(
            self.allowed_dataset_ids,
            "allowed_dataset_ids",
        )
        object.__setattr__(self, "tenant_id", normalized_tenant)
        object.__setattr__(self, "scopes", normalized_scopes)
        object.__setattr__(self, "allowed_dataset_ids", normalized_datasets)
        object.__setattr__(
            self,
            "policy_id",
            access_policy_hash(
                normalized_tenant,
                normalized_scopes,
                normalized_datasets,
            ),
        )

    @classmethod
    def from_grants(
        cls,
        *,
        tenant_id: str,
        scopes: tuple[str, ...],
        allowed_dataset_ids: tuple[str, ...],
    ) -> QueryAccessContext:
        normalized_tenant = _canonical_non_empty_string(tenant_id, "tenant_id")
        normalized_scopes = _normalized_string_grants(scopes, "scopes")
        normalized_datasets = _normalized_string_grants(
            allowed_dataset_ids,
            "allowed_dataset_ids",
        )
        return cls(
            tenant_id=normalized_tenant,
            scopes=normalized_scopes,
            allowed_dataset_ids=normalized_datasets,
            policy_id=access_policy_hash(
                normalized_tenant,
                normalized_scopes,
                normalized_datasets,
            ),
        )


@dataclass(frozen=True)
class QueryRequest:
    dataset_id: str
    schema_major: int
    fields: tuple[str, ...]
    filters: Mapping[str, object]
    as_of: str | None
    order: tuple[str, ...] | None
    limit: int
    cursor: str | None

    def __post_init__(self) -> None:
        defaults = _QUERY_DEFAULTS
        dataset_id = _canonical_non_empty_string(self.dataset_id, "dataset_id")
        if _DATASET_ID_RE.fullmatch(dataset_id) is None:
            raise QueryValidationError(
                "dataset_id must be a canonical dataset identifier"
            )
        schema_major = _native_positive_int(self.schema_major, "schema_major")
        if type(self.fields) not in {tuple, list}:
            raise QueryValidationError("fields must be a tuple or list")
        fields = _parse_fields(list(self.fields), defaults)
        filters = _parse_filters(
            self.filters,
            defaults,
            allow_immutable=True,
        )
        as_of = (
            None
            if self.as_of is None
            else _canonical_rfc3339(_parse_aware_rfc3339(self.as_of, "as_of"))
        )
        if self.order is None:
            order = None
        elif type(self.order) in {tuple, list}:
            order = _parse_order(list(self.order), defaults)
        else:
            raise QueryValidationError("order must be a tuple or list")
        limit = _native_positive_int(self.limit, "limit")
        if limit > defaults.max_page_size:
            raise QueryBudgetError(
                f"limit exceeds max_page_size={defaults.max_page_size}"
            )
        cursor = (
            None
            if self.cursor is None
            else _canonical_non_empty_string(self.cursor, "cursor")
        )

        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "schema_major", schema_major)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "order", order)
        object.__setattr__(self, "limit", limit)
        object.__setattr__(self, "cursor", cursor)


@dataclass(frozen=True)
class QueryExecutionOptions:
    latest_partition: bool = False
    any_of_eq_filters: tuple[tuple[str, object], ...] = ()

    def __post_init__(self) -> None:
        if type(self.latest_partition) is not bool:
            raise QueryValidationError("latest_partition must be a boolean")
        if type(self.any_of_eq_filters) is not tuple:
            raise QueryValidationError("any_of_eq_filters must be a tuple")
        if len(self.any_of_eq_filters) > 4:
            raise QueryBudgetError("any_of_eq_filters supports at most 4 terms")

        normalized: list[tuple[str, object]] = []
        for index, term in enumerate(self.any_of_eq_filters):
            if type(term) is not tuple or len(term) != 2:
                raise QueryValidationError(
                    f"any_of_eq_filters[{index}] must be a (field, value) tuple"
                )
            field, value = term
            field_name = _field_name(field, f"any_of_eq_filters[{index}].field")
            normalized.append(
                (
                    field_name,
                    _json_scalar(value, f"any_of_eq_filters[{index}].value"),
                )
            )
        normalized.sort(key=lambda item: (item[0], _canonical_json(item[1])))
        object.__setattr__(self, "any_of_eq_filters", tuple(normalized))


@dataclass(frozen=True)
class ResolvedQueryAsOf:
    field: str | None
    requested_as_of: str | None
    resolved_as_of: str | None
    encoded_cutoff: str | None


def _canonical_non_empty_string(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise QueryValidationError(f"{name} must be a canonical non-empty string")
    return value


def _field_name(value: object, name: str) -> str:
    field = _canonical_non_empty_string(value, name)
    if _FIELD_NAME_RE.fullmatch(field) is None:
        raise QueryValidationError(f"{name} must be a field identifier")
    return field


def _native_positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise QueryValidationError(f"{name} must be a positive integer")
    return value


def _json_scalar(value: object, name: str) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float and isfinite(value):
        return value
    raise QueryValidationError(f"{name} must be a finite JSON scalar")


def _canonical_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if type(value) in {tuple, list}:
        return [_canonical_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalized_string_grants(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise QueryValidationError(f"{name} must be a tuple")
    normalized = {
        _canonical_non_empty_string(value, f"{name}[{index}]")
        for index, value in enumerate(values)
    }
    return tuple(sorted(normalized))


def _parse_aware_rfc3339(value: object, name: str) -> datetime:
    text = _canonical_non_empty_string(value, name)
    match = _RFC3339_RE.fullmatch(text)
    if match is None:
        raise QueryValidationError(
            f"{name} must be a supported timezone-aware RFC3339 timestamp"
        )

    fraction = match.group("fraction") or ""
    microsecond = int(fraction.ljust(6, "0")) if fraction else 0
    if match.group("zulu") is not None:
        tzinfo = datetime_timezone.utc
    else:
        offset_hour = int(match.group("offset_hour"))
        offset_minute = int(match.group("offset_minute"))
        offset_sign = match.group("offset_sign")
        if offset_sign == "-" and offset_hour == 0 and offset_minute == 0:
            raise QueryValidationError(
                f"{name} must not use RFC3339 unknown local offset -00:00"
            )
        offset = timedelta(hours=offset_hour, minutes=offset_minute)
        if offset_sign == "-":
            offset = -offset
        tzinfo = datetime_timezone(offset)

    try:
        parsed = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
            microsecond,
            tzinfo=tzinfo,
        )
    except ValueError as exc:
        raise QueryValidationError(
            f"{name} must be a supported timezone-aware RFC3339 timestamp"
        ) from exc
    return parsed


def _canonical_rfc3339(value: datetime) -> str:
    return value.isoformat(timespec="microseconds" if value.microsecond else "seconds")


def _parse_fields(value: object, defaults: QueryDefaults) -> tuple[str, ...]:
    if type(value) is not list:
        raise QueryValidationError("fields must be a list")
    if len(value) > defaults.max_selected_fields:
        raise QueryBudgetError(
            f"fields exceeds max_selected_fields={defaults.max_selected_fields}"
        )
    fields = tuple(
        _field_name(field, f"fields[{index}]") for index, field in enumerate(value)
    )
    if len(set(fields)) != len(fields):
        raise QueryValidationError("fields must not contain duplicates")
    return fields


def _normalize_filter_value(
    value: object,
    *,
    field: str,
    defaults: QueryDefaults,
    allow_immutable: bool = False,
) -> Mapping[str, object]:
    is_operator_mapping = (
        isinstance(value, Mapping) if allow_immutable else type(value) is dict
    )
    if not is_operator_mapping:
        return MappingProxyType({"eq": _json_scalar(value, f"filters.{field}")})
    if len(value) != 1:
        raise QueryValidationError(f"filters.{field} must contain exactly one operator")
    operator, operand = next(iter(value.items()))
    if type(operator) is not str or operator not in _FILTER_OPERATORS:
        raise QueryValidationError(f"filters.{field} uses an unsupported operator")
    if operator in {"eq", "gte", "lte"}:
        normalized: object = _json_scalar(
            operand,
            f"filters.{field}.{operator}",
        )
    else:
        valid_sequence = (
            type(operand) in {list, tuple} if allow_immutable else type(operand) is list
        )
        if not valid_sequence:
            raise QueryValidationError(f"filters.{field}.{operator} must be a list")
        expected_length = 2 if operator == "between" else None
        if expected_length is not None and len(operand) != expected_length:
            raise QueryValidationError(
                f"filters.{field}.between must contain exactly 2 values"
            )
        if operator == "in":
            if not operand:
                raise QueryValidationError(f"filters.{field}.in must not be empty")
            if len(operand) > defaults.max_in_values:
                raise QueryBudgetError(
                    f"filters.{field}.in exceeds max_in_values={defaults.max_in_values}"
                )
        values = tuple(
            _json_scalar(item, f"filters.{field}.{operator}[{index}]")
            for index, item in enumerate(operand)
        )
        if operator == "in":
            canonical_values = [_canonical_json(item) for item in values]
            if len(set(canonical_values)) != len(canonical_values):
                raise QueryValidationError(
                    f"filters.{field}.in must not contain duplicates"
                )
            values = tuple(
                value
                for _, value in sorted(
                    zip(canonical_values, values, strict=True),
                    key=lambda pair: pair[0],
                )
            )
        normalized = values
    return MappingProxyType({operator: normalized})


def _parse_filters(
    value: object,
    defaults: QueryDefaults,
    *,
    allow_immutable: bool = False,
) -> Mapping[str, object]:
    valid_mapping = (
        isinstance(value, Mapping) if allow_immutable else type(value) is dict
    )
    if not valid_mapping:
        raise QueryValidationError("filters must be an object")
    if len(value) > defaults.max_filter_terms:
        raise QueryBudgetError(
            f"filters exceeds max_filter_terms={defaults.max_filter_terms}"
        )
    filters: dict[str, object] = {}
    for raw_field, filter_value in sorted(
        value.items(),
        key=lambda item: str(item[0]),
    ):
        field = _field_name(raw_field, "filters field")
        filters[field] = _normalize_filter_value(
            filter_value,
            field=field,
            defaults=defaults,
            allow_immutable=allow_immutable,
        )
    return MappingProxyType(filters)


def _parse_order(value: object, defaults: QueryDefaults) -> tuple[str, ...] | None:
    if value is None:
        return None
    if type(value) is not list or not value:
        raise QueryValidationError("order must be a non-empty list when provided")
    if len(value) > defaults.max_order_terms:
        raise QueryBudgetError(
            f"order exceeds max_order_terms={defaults.max_order_terms}"
        )
    order: list[str] = []
    seen_fields: set[str] = set()
    for index, raw_term in enumerate(value):
        term = _canonical_non_empty_string(raw_term, f"order[{index}]")
        match = _ORDER_RE.fullmatch(term)
        if match is None:
            raise QueryValidationError(
                f"order[{index}] must be exactly field:asc or field:desc"
            )
        field = match.group(1)
        if field in seen_fields:
            raise QueryValidationError(f"order contains duplicate field: {field}")
        seen_fields.add(field)
        order.append(term)
    return tuple(order)


def parse_query_request(payload: object) -> QueryRequest:
    """Validate and canonicalize the provider-neutral public JSON shape."""

    defaults = _QUERY_DEFAULTS
    if type(payload) is not dict:
        raise QueryValidationError("query request must be a JSON object")
    try:
        request_size = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise QueryValidationError(
            "query request must contain only JSON values"
        ) from exc
    if request_size > defaults.max_request_bytes:
        raise QueryBudgetError(
            f"query request exceeds max_request_bytes={defaults.max_request_bytes}"
        )

    if any(type(key) is not str for key in payload):
        raise QueryValidationError("query request keys must be strings")
    unknown = sorted(set(payload) - _REQUEST_KEYS)
    if unknown:
        raise QueryValidationError(
            f"unknown query request key(s): {', '.join(unknown)}"
        )
    missing = sorted(_REQUEST_REQUIRED_KEYS - set(payload))
    if missing:
        raise QueryValidationError(
            f"missing query request key(s): {', '.join(missing)}"
        )

    dataset_id = _canonical_non_empty_string(payload["dataset_id"], "dataset_id")
    if _DATASET_ID_RE.fullmatch(dataset_id) is None:
        raise QueryValidationError("dataset_id must be a canonical dataset identifier")
    schema_major = _native_positive_int(payload["schema_major"], "schema_major")
    fields = _parse_fields(payload.get("fields", []), defaults)
    filters = _parse_filters(payload.get("filters", {}), defaults)

    raw_as_of = payload.get("as_of")
    as_of = (
        None
        if raw_as_of is None
        else _canonical_rfc3339(_parse_aware_rfc3339(raw_as_of, "as_of"))
    )
    order = _parse_order(payload.get("order"), defaults)
    limit = _native_positive_int(
        payload.get("limit", defaults.max_page_size),
        "limit",
    )
    if limit > defaults.max_page_size:
        raise QueryBudgetError(f"limit exceeds max_page_size={defaults.max_page_size}")

    raw_cursor = payload.get("cursor")
    cursor = (
        None
        if raw_cursor is None
        else _canonical_non_empty_string(raw_cursor, "cursor")
    )
    return QueryRequest(
        dataset_id=dataset_id,
        schema_major=schema_major,
        fields=fields,
        filters=filters,
        as_of=as_of,
        order=order,
        limit=limit,
        cursor=cursor,
    )


def access_policy_hash(
    tenant_id: str,
    scopes: tuple[str, ...],
    allowed_dataset_ids: tuple[str, ...],
) -> str:
    """Bind a Phase 2 access context without leaking credential material."""

    payload = {
        "tenant_id": _canonical_non_empty_string(tenant_id, "tenant_id"),
        "scopes": _normalized_string_grants(scopes, "scopes"),
        "allowed_dataset_ids": _normalized_string_grants(
            allowed_dataset_ids,
            "allowed_dataset_ids",
        ),
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def normalized_query_hash(
    request: QueryRequest,
    *,
    resolved_dataset_id: str | None = None,
    resolved_schema_version: str | None = None,
    effective_fields: tuple[str, ...] | None = None,
    effective_order: tuple[str, ...] | None = None,
    requested_as_of: str | None = None,
    resolved_as_of: str | None = None,
    options: QueryExecutionOptions = QueryExecutionOptions(),
    resolved_partition: object = None,
) -> str:
    """Hash every result-affecting query value except the cursor token itself."""

    payload = {
        "dataset_id": resolved_dataset_id or request.dataset_id,
        "schema": resolved_schema_version or request.schema_major,
        "fields": request.fields if effective_fields is None else effective_fields,
        "filters": request.filters,
        "order": request.order if effective_order is None else effective_order,
        "requested_as_of": request.as_of
        if requested_as_of is None
        else requested_as_of,
        "resolved_as_of": resolved_as_of,
        "limit": request.limit,
        "execution_options": {
            "latest_partition": options.latest_partition,
            "any_of_eq_filters": options.any_of_eq_filters,
            "resolved_partition": resolved_partition,
        },
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _explicit_as_of_upper_bounds(
    request: QueryRequest,
    field: str,
) -> tuple[tuple[str, object], ...]:
    raw_filter = request.filters.get(field)
    if not isinstance(raw_filter, Mapping):
        return ()
    if "eq" in raw_filter:
        return ((f"filters.{field}.eq", raw_filter["eq"]),)
    if "lte" in raw_filter:
        return ((f"filters.{field}.lte", raw_filter["lte"]),)
    if "between" in raw_filter:
        values = raw_filter["between"]
        if type(values) is tuple and len(values) == 2:
            return ((f"filters.{field}.between[1]", values[1]),)
    if "in" in raw_filter:
        values = raw_filter["in"]
        if type(values) is tuple:
            return tuple(
                (f"filters.{field}.in[{index}]", value)
                for index, value in enumerate(values)
            )
    return ()


def _decode_dataset_cutoff(
    value: object,
    *,
    as_of_format: str,
    timezone: ZoneInfo,
    name: str,
) -> datetime:
    if as_of_format == "yyyymmdd":
        text = _canonical_non_empty_string(value, name)
        if _YYYYMMDD_RE.fullmatch(text) is None:
            raise QueryValidationError(f"{name} must use yyyymmdd")
        try:
            parsed = datetime.strptime(text, "%Y%m%d")
        except ValueError as exc:
            raise QueryValidationError(f"{name} must use yyyymmdd") from exc
        return parsed.replace(tzinfo=timezone)
    if as_of_format == "rfc3339":
        return _parse_aware_rfc3339(value, name).astimezone(timezone)
    raise QueryValidationError("dataset declares an unsupported as_of_format")


def resolve_query_as_of(
    request: QueryRequest,
    dataset: DatasetDefinition,
) -> ResolvedQueryAsOf:
    """Resolve public as-of input to one registry-declared inclusive cutoff."""

    if request.as_of is None:
        return ResolvedQueryAsOf(
            field=None,
            requested_as_of=None,
            resolved_as_of=None,
            encoded_cutoff=None,
        )
    if dataset.as_of_field is None or dataset.as_of_format is None:
        raise QueryValidationError(
            f"dataset {dataset.dataset_id} does not support as_of queries"
        )
    try:
        timezone = ZoneInfo(dataset.timezone)
    except ZoneInfoNotFoundError as exc:
        raise QueryValidationError(
            f"dataset {dataset.dataset_id} has an invalid timezone"
        ) from exc

    requested = _parse_aware_rfc3339(request.as_of, "as_of")
    local_cutoff = requested.astimezone(timezone)
    if dataset.as_of_format == "yyyymmdd":
        local_cutoff = local_cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

    explicit_bounds = _explicit_as_of_upper_bounds(request, dataset.as_of_field)
    if explicit_bounds:
        explicit_cutoff = max(
            _decode_dataset_cutoff(
                bound,
                as_of_format=dataset.as_of_format,
                timezone=timezone,
                name=name,
            )
            for name, bound in explicit_bounds
        )
        local_cutoff = min(local_cutoff, explicit_cutoff)

    if dataset.as_of_format == "yyyymmdd":
        encoded_cutoff = local_cutoff.strftime("%Y%m%d")
    else:
        encoded_cutoff = _canonical_rfc3339(local_cutoff)
    return ResolvedQueryAsOf(
        field=dataset.as_of_field,
        requested_as_of=_canonical_rfc3339(requested),
        resolved_as_of=_canonical_rfc3339(local_cutoff),
        encoded_cutoff=encoded_cutoff,
    )


def public_catalog_version(registry: DatasetRegistry) -> str:
    """Fingerprint only the provider-neutral, tenant-visible catalog contract."""

    datasets: list[dict[str, object]] = []
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        datasets.append(
            {
                "dataset_id": dataset.dataset_id,
                "aliases": sorted(dataset.aliases),
                "domain": dataset.domain,
                "market": dataset.market,
                "entity_type": dataset.entity_type,
                "data_classification": dataset.data_classification,
                "schema_version": dataset.schema_version,
                "fields": [
                    {
                        "name": field.name,
                        "logical_type": field.logical_type,
                        "nullable": field.nullable,
                        "selectable": field.selectable,
                        "filterable": field.filterable,
                        "sortable": field.sortable,
                        "operators": dataset.filter_operators.get(field.name, ()),
                    }
                    for field in dataset.fields
                ],
                "primary_key": dataset.primary_key,
                "default_projection": dataset.default_projection,
                "as_of_field": dataset.as_of_field,
                "as_of_format": dataset.as_of_format,
                "range_field": dataset.range_field,
                "partition_field": dataset.partition_field,
                "cadence_class": dataset.cadence_class,
                "timezone": dataset.timezone,
                "freshness_sla_seconds": dataset.freshness_sla_seconds,
                "max_page_size": dataset.max_page_size,
                "max_lookback_days": dataset.max_lookback_days,
                "point_in_time": dataset.point_in_time,
                "backfill_policy": dataset.backfill_policy,
                "empty_data_policy": dataset.empty_data_policy,
                "required_scope": dataset.required_scope,
                "quota_class": dataset.quota_class,
                "availability": sorted(
                    {
                        (binding.entitlement_state, binding.activation_state)
                        for binding in dataset.provider_bindings
                    }
                ),
            }
        )
    public_contract = {
        "api_version": "v1",
        "query_defaults": asdict(registry.query_defaults),
        "datasets": datasets,
    }
    digest = sha256(_canonical_json(public_contract).encode("utf-8")).hexdigest()
    return f"v1-{digest[:16]}"
