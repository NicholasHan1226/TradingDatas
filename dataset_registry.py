"""Provider-neutral dataset declarations for TradingDatas.

The registry describes immutable dataset, ingest-adapter, and read-model
contracts only. Runtime collection state remains authoritative in SQLite ingest
receipts and is deliberately rejected from this YAML authority.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, time, timedelta
import math
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping

import yaml


PROVIDER_NATIVE_DATASET_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "config" / "provider_native_dataset_registry.yaml"
)
BINANCE_SPOT_CANARY_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "config" / "crypto_binance_spot_canary_registry.v1.yaml"
)
DATASET_REGISTRY_PATH = PROVIDER_NATIVE_DATASET_REGISTRY_PATH
DATASET_REGISTRY_PATH_ENV = "TRADINGDATAS_REGISTRY_PATH"
CANARY_MODE_ENV = "TRADINGDATAS_CANARY_MODE"
BINANCE_SPOT_CANARY_MODE = "binance_spot_v1"

_ROOT_KEYS = frozenset({"version", "query_defaults", "schema_profiles", "datasets"})
_ROOT_REQUIRED_KEYS = frozenset({"version", "query_defaults", "datasets"})
_QUERY_DEFAULT_KEYS = frozenset(
    {
        "max_request_bytes",
        "max_response_bytes",
        "max_page_size",
        "max_lookback_days",
        "max_selected_fields",
        "max_filter_terms",
        "max_in_values",
        "max_order_terms",
        "max_catalog_search_chars",
        "cursor_ttl_seconds",
        "sqlite_progress_steps",
    }
)
_SCHEMA_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "fields",
        "primary_key",
        "default_projection",
        "as_of_field",
        "as_of_format",
        "range_field",
        "partition_field",
        "max_page_size",
        "max_lookback_days",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
    }
)
_SCHEMA_PROFILE_REQUIRED_KEYS = _SCHEMA_PROFILE_KEYS - {
    "max_page_size",
    "max_lookback_days",
}
_PROFILE_CONTRACT_KEYS = _SCHEMA_PROFILE_KEYS - {"schema_version"}
_PROFILE_CONTRACT_REQUIRED_KEYS = _SCHEMA_PROFILE_REQUIRED_KEYS - {"schema_version"}
_DATASET_KEYS = frozenset(
    {
        "dataset_id",
        "aliases",
        "domain",
        "market",
        "entity_type",
        "data_classification",
        "schema_version",
        "schema_profile",
        "fields",
        "primary_key",
        "default_projection",
        "as_of_field",
        "as_of_format",
        "range_field",
        "partition_field",
        "cadence_class",
        "timezone",
        "freshness_sla_seconds",
        "max_page_size",
        "max_lookback_days",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
        "provider_bindings",
        "read_model_adapter",
    }
)
_DATASET_REQUIRED_KEYS = _DATASET_KEYS - _PROFILE_CONTRACT_KEYS - {"schema_profile"}
_FIELD_KEYS = frozenset(
    {
        "name",
        "logical_type",
        "nullable",
        "selectable",
        "filterable",
        "sortable",
    }
)
_BINDING_KEYS = frozenset(
    {
        "provider",
        "api_name",
        "adapter_version",
        "read_discriminator_value",
        "entitlement_state",
        "activation_state",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
        "target_tables",
        "input_fields",
        "request_shape",
        "request_template",
        "request_variants",
        "fanout",
        "pagination",
        "request_window_policy",
        "response_completeness",
        "requested_fields",
        "max_rows_per_attempt",
        "max_payload_bytes_per_row",
        "max_batch_bytes",
        "max_nesting_depth",
    }
)
_REQUEST_WINDOW_POLICY_KEYS = frozenset(
    {
        "required_keys",
        "formats",
        "range_start_key",
        "range_end_key",
        "max_span_days",
    }
)
_FANOUT_KEYS = frozenset(
    {
        "strategy",
        "parameter",
        "source_dataset_id",
        "source_field",
        "batch_size",
        "source_equals",
        "source_date_field",
        "source_date_lte_days",
        "max_values",
        "source_order",
    }
)
_PAGINATION_KEYS = frozenset(
    {
        "strategy",
        "limit_parameter",
        "offset_parameter",
        "page_size",
        "max_pages",
    }
)
_RESPONSE_COMPLETENESS_KEYS = frozenset(
    {
        "strategy",
        "date_field",
        "request_start_key",
        "request_end_key",
        "partition_field",
        "request_partition_key",
        "fixed_field_matches",
        "reject_at_row_limit",
    }
)
_BINDING_REQUIRED_KEYS = frozenset(
    {
        "provider",
        "api_name",
        "adapter_version",
        "read_discriminator_value",
        "entitlement_state",
        "activation_state",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
        "target_tables",
        "input_fields",
    }
)
_INPUT_FIELD_KEYS = frozenset({"name", "declared_source_type", "required"})
_READ_MODEL_ADAPTER_KEYS = frozenset(
    {
        "adapter_version",
        "primary_table",
        "fixed_field_filters",
        "storage_kind",
        "row_key_strategy",
    }
)
_READ_MODEL_ADAPTER_REQUIRED_KEYS = frozenset(
    {
        "adapter_version",
        "primary_table",
        "fixed_field_filters",
        "storage_kind",
        "row_key_strategy",
    }
)
_FIXED_FILTER_KEYS = frozenset({"field", "allowed_values"})

_LOGICAL_TYPES = frozenset({"text", "float", "integer"})
_INPUT_DECLARED_SOURCE_TYPES = frozenset(
    {"None", "datetime", "float", "int", "intint", "str"}
)
_ENTITLEMENT_STATES = frozenset({"active", "locked", "unknown", "excluded", "retired"})
_ACTIVATION_STATES = frozenset({"active", "paused"})
_POINT_IN_TIME_MODES = frozenset({"append_only", "current_snapshot", "unsupported"})
_BACKFILL_POLICIES = frozenset({"provider_limited", "disabled"})
_EMPTY_DATA_POLICIES = frozenset({"allowed", "forbidden"})
_DATA_CLASSIFICATIONS = frozenset({"objective_factual"})
_INTERNAL_NON_QUERYABLE_FIELDS = frozenset({"raw_json", "source_file"})
_AS_OF_FORMATS = frozenset({"yyyymmdd", "rfc3339"})
_REQUEST_WINDOW_FORMATS = frozenset(
    {
        "identity",
        "local_datetime_seconds",
        "rfc3339",
        "yyyy_qn",
        "yyyymm",
        "yyyymmdd",
        "yyyyww",
    }
)
_RUNTIME_REQUEST_WINDOW_FORMATS = frozenset(
    {
        "local_datetime_seconds",
        "yyyy_qn",
        "yyyymm",
        "yyyymmdd",
        "yyyyww",
    }
)
_MAX_REQUEST_WINDOW_VALUE_BYTES = 1024
_SAFE_REQUEST_WINDOW_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_PROBE_STATES = frozenset({"executable", "blocked"})
_INGEST_CONTRACT_STATES = frozenset({"ready", "blocked"})
_PROBE_BLOCK_REASONS = frozenset(
    {
        "dependency_seed_receipt_unresolved",
        "official_requiredness_unknown",
        "request_anchor_unresolved",
        "required_enum_unresolved",
        "required_parameter_unresolved",
    }
)
_INGEST_CONTRACT_BLOCK_REASONS = _PROBE_BLOCK_REASONS | {
    "response_completeness_unresolved_at_observed_limit"
}
_REQUEST_SHAPES = frozenset(
    {
        "snapshot_or_date_range",
        "entity_fanout",
        "dimension_fanout",
        "event_or_intraday_window",
    }
)
_FANOUT_STRATEGIES = frozenset({"none", "dataset_field"})
_PAGINATION_STRATEGIES = frozenset({"none", "offset"})
_RESPONSE_COMPLETENESS_STRATEGIES = frozenset(
    {
        "one_row_per_calendar_date",
        "unique_primary_key_snapshot",
        "single_partition_unique_primary_key",
    }
)
_ORDERED_LOGICAL_TYPES = frozenset({"text", "float", "integer"})
_PROVIDER_NATIVE_STORAGE_KIND = "provider_native_rows"
_PROVIDER_NATIVE_TABLE = "provider_dataset_rows"
_STORAGE_KINDS = frozenset({_PROVIDER_NATIVE_STORAGE_KIND})
_ROW_KEY_STRATEGIES = frozenset({"primary_key", "payload_hash"})
_PROVIDER_FIELD_PATTERN = re.compile(r"[A-Za-z0-9_]{1,64}")
_PROVIDER_PARAMETER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WINDOW_PLACEHOLDER_PATTERN = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_SCHEMA_VERSION_PATTERN = re.compile(
    r"(?P<major>[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_GENERIC_BINDING_KEYS = frozenset(
    {
        "request_shape",
        "request_template",
        "requested_fields",
        "fanout",
        "pagination",
        "max_rows_per_attempt",
        "max_payload_bytes_per_row",
        "max_batch_bytes",
        "max_nesting_depth",
    }
)
_OPTIONAL_GENERIC_BINDING_KEYS = frozenset(
    {"request_window_policy", "response_completeness"}
)


@dataclass(frozen=True)
class QueryDefaults:
    max_request_bytes: int
    max_response_bytes: int
    max_page_size: int
    max_lookback_days: int
    max_selected_fields: int
    max_filter_terms: int
    max_in_values: int
    max_order_terms: int
    max_catalog_search_chars: int
    cursor_ttl_seconds: int
    sqlite_progress_steps: int


DEFAULT_QUERY_DEFAULTS = QueryDefaults(
    max_request_bytes=65_536,
    max_response_bytes=4_194_304,
    max_page_size=500,
    max_lookback_days=36_500,
    max_selected_fields=100,
    max_filter_terms=16,
    max_in_values=100,
    max_order_terms=8,
    max_catalog_search_chars=128,
    cursor_ttl_seconds=900,
    sqlite_progress_steps=1_000_000,
)


@dataclass(frozen=True)
class DatasetField:
    name: str
    logical_type: str
    nullable: bool
    selectable: bool
    filterable: bool
    sortable: bool


def field_filter_operators(field: DatasetField) -> tuple[str, ...]:
    """Return the deterministic public filter grammar for one field."""

    if not field.filterable:
        return ()
    operators = ("eq", "in")
    if field.logical_type in _ORDERED_LOGICAL_TYPES:
        operators += ("gte", "lte", "between")
    return operators


@dataclass(frozen=True)
class FixedFieldFilter:
    field: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class ReadModelAdapter:
    adapter_version: str
    primary_table: str
    fixed_field_filters: tuple[FixedFieldFilter, ...]
    storage_kind: str = _PROVIDER_NATIVE_STORAGE_KIND
    row_key_strategy: str | None = None


RequestScalar = str | int | float | bool


@dataclass(frozen=True)
class FanoutPolicy:
    """Provider-neutral request fanout declaration."""

    strategy: str
    parameter: str | None = None
    source_dataset_id: str | None = None
    source_field: str | None = None
    batch_size: int | None = None
    source_equals: tuple[tuple[str, str], ...] = ()
    source_date_field: str | None = None
    source_date_lte_days: int | None = None
    max_values: int | None = None
    source_order: str = "lexical"


@dataclass(frozen=True)
class PaginationPolicy:
    """Provider-neutral upstream pagination declaration."""

    strategy: str
    limit_parameter: str | None = None
    offset_parameter: str | None = None
    page_size: int | None = None
    max_pages: int | None = None


@dataclass(frozen=True)
class ProviderInputField:
    """One immutable provider request-input declaration."""

    name: str
    declared_source_type: str
    required: bool | None


@dataclass(frozen=True)
class ProviderBinding:
    """One provider ingest binding; public reads use ``ReadModelAdapter``."""

    provider: str
    api_name: str
    adapter_version: str
    read_discriminator_value: str
    entitlement_state: str
    activation_state: str
    target_tables: tuple[str, ...]
    probe_state: str = "executable"
    probe_block_reasons: tuple[str, ...] = ()
    ingest_contract_state: str = "ready"
    ingest_contract_block_reasons: tuple[str, ...] = ()
    input_fields: tuple[ProviderInputField, ...] = ()
    request_shape: str | None = None
    request_template: Mapping[str, str] = dataclass_field(
        default_factory=lambda: MappingProxyType({})
    )
    request_variants: tuple[Mapping[str, RequestScalar], ...] = dataclass_field(
        default_factory=lambda: (MappingProxyType({}),)
    )
    fanout: FanoutPolicy | None = None
    pagination: PaginationPolicy | None = None
    request_window_policy: RequestWindowPolicy | None = None
    response_completeness: ResponseCompletenessPolicy | None = None
    requested_fields: tuple[str, ...] = ()
    max_rows_per_attempt: int | None = None
    max_payload_bytes_per_row: int | None = None
    max_batch_bytes: int | None = None
    max_nesting_depth: int | None = None


@dataclass(frozen=True)
class RequestWindowPolicy:
    """Generic provider request-window validation owned by the registry."""

    required_keys: tuple[str, ...]
    formats: Mapping[str, str]
    range_start_key: str
    range_end_key: str
    max_span_days: int


@dataclass(frozen=True)
class DecodedRequestWindowValue:
    """Canonical comparable anchor and covered interval for one window value."""

    anchor: datetime
    interval_start: datetime
    interval_end: datetime


def _request_window_value_error(format_name: str) -> ValueError:
    return ValueError(f"request_window {format_name} value is invalid")


def decode_request_window_value(
    value: object,
    format_name: str,
) -> DecodedRequestWindowValue:
    """Decode one formally supported provider-neutral request-window value."""

    if format_name not in _RUNTIME_REQUEST_WINDOW_FORMATS:
        raise ValueError(
            f"runtime request_window format is unsupported: {format_name}"
        )
    if type(value) is not str:
        raise _request_window_value_error(format_name)
    try:
        if format_name == "yyyymmdd":
            if re.fullmatch(r"[0-9]{8}", value) is None:
                raise _request_window_value_error(format_name)
            start = datetime.strptime(value, "%Y%m%d")
            if start.strftime("%Y%m%d") != value:
                raise _request_window_value_error(format_name)
            end = start + timedelta(days=1, seconds=-1)
        elif format_name == "yyyymm":
            if re.fullmatch(r"[0-9]{6}", value) is None:
                raise _request_window_value_error(format_name)
            start = datetime.strptime(value, "%Y%m")
            if start.strftime("%Y%m") != value:
                raise _request_window_value_error(format_name)
            end = datetime(
                start.year,
                start.month,
                monthrange(start.year, start.month)[1],
                23,
                59,
                59,
            )
        elif format_name == "yyyy_qn":
            match = re.fullmatch(r"([0-9]{4})Q([1-4])", value)
            if match is None:
                raise _request_window_value_error(format_name)
            year, quarter = (int(item) for item in match.groups())
            start = datetime(year, 1 + (quarter - 1) * 3, 1)
            end_month = quarter * 3
            end = datetime(
                year,
                end_month,
                monthrange(year, end_month)[1],
                23,
                59,
                59,
            )
        elif format_name == "yyyyww":
            match = re.fullmatch(r"([0-9]{4})([0-9]{2})", value)
            if match is None:
                raise _request_window_value_error(format_name)
            iso_year, iso_week = (int(item) for item in match.groups())
            first = date.fromisocalendar(iso_year, iso_week, 1)
            start = datetime.combine(first, time.min)
            if start.strftime("%G%V") != value:
                raise _request_window_value_error(format_name)
            end = start + timedelta(days=7, seconds=-1)
        else:
            if re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}",
                value,
            ) is None:
                raise _request_window_value_error(format_name)
            start = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            if start.strftime("%Y-%m-%d %H:%M:%S") != value:
                raise _request_window_value_error(format_name)
            end = start
    except (OverflowError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("request_window "):
            raise
        raise _request_window_value_error(format_name) from exc
    return DecodedRequestWindowValue(start, start, end)


def encode_request_window_value(
    value: date | datetime,
    format_name: str,
) -> str:
    """Encode a trusted partition anchor using a runtime window format."""

    if format_name not in _RUNTIME_REQUEST_WINDOW_FORMATS:
        raise ValueError(
            f"runtime request_window format is unsupported: {format_name}"
        )
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("request_window datetime anchor must be timezone-aware")
        anchor = value
    elif type(value) is date:
        anchor = datetime.combine(value, time.min)
    else:
        raise TypeError("request_window anchor must be a date or datetime")
    if format_name == "yyyymmdd":
        return anchor.strftime("%Y%m%d")
    if format_name == "yyyymm":
        return anchor.strftime("%Y%m")
    if format_name == "yyyy_qn":
        return f"{anchor.year:04d}Q{((anchor.month - 1) // 3) + 1}"
    if format_name == "yyyyww":
        return anchor.strftime("%G%V")
    return anchor.strftime("%Y-%m-%d %H:%M:%S")


def normalize_request_window(
    policy: RequestWindowPolicy,
    request_window: Mapping[object, object],
) -> dict[str, str]:
    """Strictly validate and canonicalize one complete request window."""

    if not isinstance(policy, RequestWindowPolicy):
        raise TypeError("request_window policy is invalid")
    if not isinstance(request_window, Mapping):
        raise TypeError("request_window must be a mapping")
    window: dict[str, str] = {}
    for key, value in request_window.items():
        if type(key) is not str or _SAFE_REQUEST_WINDOW_KEY.fullmatch(key) is None:
            raise ValueError("request_window keys must use the safe identifier grammar")
        if type(value) is not str or not value:
            raise ValueError("request_window values must be non-empty strings")
        if len(value.encode("utf-8")) > _MAX_REQUEST_WINDOW_VALUE_BYTES:
            raise ValueError("request_window value exceeds the public string budget")
        if any(ord(character) < 32 for character in value):
            raise ValueError("request_window values must not contain control characters")
        window[key] = value
    if set(window) != set(policy.required_keys):
        raise ValueError(
            "request_window keys must exactly match the registry window policy"
        )
    decoded = {
        key: decode_request_window_value(window[key], policy.formats[key])
        for key in policy.required_keys
    }
    start = decoded[policy.range_start_key].anchor
    end = decoded[policy.range_end_key].anchor
    if start > end:
        raise ValueError("request_window range start must not exceed range end")
    if (end.date() - start.date()).days + 1 > policy.max_span_days:
        raise ValueError("request_window range exceeds max_span_days")
    return dict(sorted(window.items()))


def request_window_covered_dates(
    policy: RequestWindowPolicy,
    request_window: Mapping[object, object],
) -> tuple[date, ...]:
    """Return every calendar date covered by one canonical request window."""

    window = normalize_request_window(policy, request_window)
    start = decode_request_window_value(
        window[policy.range_start_key], policy.formats[policy.range_start_key]
    ).interval_start.date()
    end = decode_request_window_value(
        window[policy.range_end_key], policy.formats[policy.range_end_key]
    ).interval_end.date()
    return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))


@dataclass(frozen=True)
class ResponseCompletenessPolicy:
    """Generic provider response-shape assertion resolved from the registry."""

    strategy: str
    fixed_field_matches: Mapping[str, str]
    reject_at_row_limit: bool = False
    date_field: str | None = None
    request_start_key: str | None = None
    request_end_key: str | None = None
    partition_field: str | None = None
    request_partition_key: str | None = None
    snapshot_field: str | None = None


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    aliases: tuple[str, ...]
    domain: str
    market: str
    entity_type: str
    data_classification: str
    schema_version: str
    fields: tuple[DatasetField, ...]
    primary_key: tuple[str, ...]
    default_projection: tuple[str, ...]
    as_of_field: str | None
    as_of_format: str | None
    range_field: str | None
    partition_field: str | None
    cadence_class: str
    timezone: str
    freshness_sla_seconds: int
    max_page_size: int
    max_lookback_days: int
    point_in_time: str
    backfill_policy: str
    empty_data_policy: str
    required_scope: str
    quota_class: str
    provider_bindings: tuple[ProviderBinding, ...]
    read_model_adapter: ReadModelAdapter

    @property
    def schema_major(self) -> int:
        match = _SCHEMA_VERSION_PATTERN.fullmatch(self.schema_version)
        if match is None:
            raise ValueError(
                f"dataset {self.dataset_id}.schema_version must use MAJOR.MINOR.PATCH"
            )
        return int(match.group("major"))

    @property
    def filter_operators(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(
            {
                field.name: operators
                for field in self.fields
                if (operators := field_filter_operators(field))
            }
        )


@dataclass(frozen=True)
class DatasetSchemaProfile:
    schema_version: str
    fields: tuple[DatasetField, ...]
    primary_key: tuple[str, ...]
    default_projection: tuple[str, ...]
    as_of_field: str | None
    as_of_format: str | None
    range_field: str | None
    partition_field: str | None
    max_page_size: int
    max_lookback_days: int
    point_in_time: str
    backfill_policy: str
    empty_data_policy: str
    required_scope: str
    quota_class: str


class DatasetRegistry:
    """Immutable indexes over validated dataset definitions."""

    def __init__(
        self,
        datasets: tuple[DatasetDefinition, ...],
        query_defaults: QueryDefaults = DEFAULT_QUERY_DEFAULTS,
    ) -> None:
        by_id: dict[str, DatasetDefinition] = {}
        by_name: dict[str, DatasetDefinition] = {}
        provider_api_owners: dict[tuple[str, str], str] = {}
        read_discriminator_owners: dict[tuple[str, str], str] = {}

        for dataset in datasets:
            if dataset.dataset_id in by_id:
                raise ValueError(f"duplicate dataset_id: {dataset.dataset_id}")
            by_id[dataset.dataset_id] = dataset
            self._register_name(by_name, dataset.dataset_id, dataset)

            seen_aliases: set[str] = set()
            for alias in dataset.aliases:
                if alias in seen_aliases:
                    raise ValueError(
                        f"duplicate alias {alias!r} in dataset {dataset.dataset_id}"
                    )
                seen_aliases.add(alias)
                self._register_name(by_name, alias, dataset)

            seen_providers: set[str] = set()
            for binding in dataset.provider_bindings:
                if binding.provider in seen_providers:
                    raise ValueError(
                        f"duplicate provider {binding.provider!r} in dataset "
                        f"{dataset.dataset_id}"
                    )
                seen_providers.add(binding.provider)
                provider_api = (binding.provider, binding.api_name)
                previous = provider_api_owners.get(provider_api)
                if previous is not None and previous != dataset.dataset_id:
                    raise ValueError(
                        f"provider api_name {binding.provider}.{binding.api_name} "
                        f"maps to multiple datasets: {previous} and "
                        f"{dataset.dataset_id}"
                    )
                provider_api_owners[provider_api] = dataset.dataset_id

                read_discriminator = (
                    dataset.read_model_adapter.primary_table,
                    binding.read_discriminator_value,
                )
                previous = read_discriminator_owners.get(read_discriminator)
                if previous is not None and previous != dataset.dataset_id:
                    raise ValueError(
                        "read discriminator ownership "
                        f"{read_discriminator!r} maps to multiple datasets: "
                        f"{previous} and {dataset.dataset_id}"
                    )
                read_discriminator_owners[read_discriminator] = dataset.dataset_id

        self._datasets = datasets
        self._query_defaults = query_defaults
        self._by_id: Mapping[str, DatasetDefinition] = MappingProxyType(by_id)
        self._by_name: Mapping[str, DatasetDefinition] = MappingProxyType(by_name)

    @staticmethod
    def _register_name(
        by_name: dict[str, DatasetDefinition],
        name: str,
        dataset: DatasetDefinition,
    ) -> None:
        previous = by_name.get(name)
        if previous is not None and previous.dataset_id != dataset.dataset_id:
            raise ValueError(
                f"name {name!r} resolves to multiple datasets: "
                f"{previous.dataset_id} and {dataset.dataset_id}"
            )
        by_name[name] = dataset

    @property
    def datasets(self) -> tuple[DatasetDefinition, ...]:
        """Return the validated catalog in declaration order."""

        return self._datasets

    @property
    def query_defaults(self) -> QueryDefaults:
        return self._query_defaults

    def resolve(self, name: str) -> DatasetDefinition:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown dataset or alias: {name}") from exc

    def provider_binding(self, dataset_id: str, provider: str) -> ProviderBinding:
        try:
            dataset = self._by_id[dataset_id]
        except KeyError as exc:
            raise KeyError(f"unknown dataset_id: {dataset_id}") from exc
        for binding in dataset.provider_bindings:
            if binding.provider == provider:
                return binding
        raise KeyError(f"dataset {dataset_id} has no provider binding for {provider}")

    def active_for_cadence(self, cadence_class: str) -> tuple[DatasetDefinition, ...]:
        return tuple(
            dataset
            for dataset in self._datasets
            if dataset.cadence_class == cadence_class
            and any(
                binding.activation_state == "active"
                and binding.entitlement_state == "active"
                for binding in dataset.provider_bindings
            )
        )


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    return value


def _reject_unknown_keys(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    path: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown key(s) in {path}: {', '.join(unknown)}")
    missing = sorted((allowed if required is None else required) - set(value))
    if missing:
        raise ValueError(f"missing key(s) in {path}: {', '.join(missing)}")


def _non_empty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value


def _string_tuple(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    result = tuple(
        _non_empty_string(item, f"{path}[{index}]") for index, item in enumerate(value)
    )
    if not allow_empty and not result:
        raise ValueError(f"{path} must not be empty")
    return result


def _reject_duplicate_strings(values: tuple[str, ...], path: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{path} contains duplicate value: {value}")
        seen.add(value)


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _optional_positive_int(value: Any, path: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, path)


def _optional_non_empty_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, path)


def _choice(value: Any, allowed: frozenset[str], path: str) -> str:
    normalized = _non_empty_string(value, path)
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{path} must be one of: {choices}")
    return normalized


def _provider_field_name(value: Any, path: str) -> str:
    name = _non_empty_string(value, path)
    if _PROVIDER_FIELD_PATTERN.fullmatch(name) is None:
        raise ValueError(f"{path} must use the provider field name grammar")
    return name


def _provider_parameter_name(value: Any, path: str) -> str:
    name = _non_empty_string(value, path)
    if _PROVIDER_PARAMETER_PATTERN.fullmatch(name) is None:
        raise ValueError(f"{path} must use the provider parameter name grammar")
    return name


def _provider_input_fields(raw: Any, path: str) -> tuple[ProviderInputField, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be a list")
    if not raw:
        raise ValueError(f"{path} must not be empty")
    normalized: list[ProviderInputField] = []
    seen: set[str] = set()
    for index, raw_field in enumerate(raw):
        field_path = f"{path}[{index}]"
        value = _mapping(raw_field, field_path)
        _reject_unknown_keys(value, _INPUT_FIELD_KEYS, field_path)
        name = _provider_parameter_name(value["name"], f"{field_path}.name")
        if name in seen:
            raise ValueError(f"{path} contains duplicate name: {name}")
        seen.add(name)
        declared_source_type = _choice(
            value["declared_source_type"],
            _INPUT_DECLARED_SOURCE_TYPES,
            f"{field_path}.declared_source_type",
        )
        required = value["required"]
        if required is not None and type(required) is not bool:
            raise ValueError(f"{field_path}.required must be a boolean or null")
        normalized.append(
            ProviderInputField(
                name=name,
                declared_source_type=declared_source_type,
                required=required,
            )
        )
    return tuple(normalized)


def _request_template(raw: Any, path: str) -> Mapping[str, str]:
    value = _mapping(raw, path)
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _provider_parameter_name(raw_key, f"{path} key")
        if not isinstance(raw_value, str):
            raise ValueError(f"{path}.{key} must be a string")
        if any(ord(character) < 32 for character in raw_value):
            raise ValueError(f"{path}.{key} must not contain control characters")
        if (
            "${" in raw_value
            and _WINDOW_PLACEHOLDER_PATTERN.fullmatch(raw_value) is None
        ):
            raise ValueError(
                f"{path}.{key} must use an exact ${{window.<safe_key>}} placeholder"
            )
        normalized[key] = raw_value
    return MappingProxyType(dict(sorted(normalized.items())))


def _request_variants(
    raw: Any,
    *,
    path: str,
    request_template: Mapping[str, str],
) -> tuple[Mapping[str, RequestScalar], ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} must be a non-empty list")
    normalized: list[Mapping[str, RequestScalar]] = []
    expected_keys: frozenset[str] | None = None
    seen: set[tuple[tuple[str, tuple[str, RequestScalar]], ...]] = set()
    for index, raw_variant in enumerate(raw):
        value = _mapping(raw_variant, f"{path}[{index}]")
        variant: dict[str, RequestScalar] = {}
        for raw_key, raw_value in value.items():
            key = _provider_parameter_name(raw_key, f"{path}[{index}] key")
            if key not in request_template:
                raise ValueError(
                    f"{path}[{index}].{key} is missing from request_template"
                )
            if _WINDOW_PLACEHOLDER_PATTERN.fullmatch(request_template[key]):
                raise ValueError(
                    f"{path}[{index}].{key} cannot override a window placeholder"
                )
            item = _request_variant_scalar(raw_value, f"{path}[{index}].{key}")
            variant[key] = item
        keys = frozenset(variant)
        if not keys:
            if len(raw) != 1:
                raise ValueError(f"{path} empty variant must be the only variant")
        elif expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError(f"{path} variants must use the same keys")
        identity = tuple(
            (key, (type(item).__name__, item)) for key, item in sorted(variant.items())
        )
        if identity in seen:
            raise ValueError(f"{path} contains a duplicate variant")
        seen.add(identity)
        normalized.append(MappingProxyType(dict(sorted(variant.items()))))
    if expected_keys is not None:
        template_default = tuple(
            (key, (type(request_template[key]).__name__, request_template[key]))
            for key in sorted(expected_keys)
        )
        if template_default not in seen:
            raise ValueError(f"{path} must include the request_template default")
    return tuple(normalized)


def _request_variant_scalar(value: Any, path: str) -> RequestScalar:
    if isinstance(value, str):
        if (
            not value
            or any(ord(character) < 32 for character in value)
            or "${" in value
        ):
            raise ValueError(f"{path} must be a concrete finite JSON scalar")
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"{path} must be a concrete finite JSON scalar")


def _fanout_policy(raw: Any, *, path: str) -> FanoutPolicy:
    value = _mapping(raw, path)
    _reject_unknown_keys(value, _FANOUT_KEYS, path, required=frozenset({"strategy"}))
    strategy = _choice(value["strategy"], _FANOUT_STRATEGIES, f"{path}.strategy")
    if strategy == "none":
        _reject_unknown_keys(
            value,
            frozenset({"strategy"}),
            path,
            required=frozenset({"strategy"}),
        )
        return FanoutPolicy(strategy="none")
    required = frozenset(
        {"strategy", "parameter", "source_dataset_id", "source_field", "batch_size"}
    )
    _reject_unknown_keys(value, _FANOUT_KEYS, path, required=required)
    raw_equals = value.get("source_equals", {})
    equals = _mapping(raw_equals, f"{path}.source_equals")
    normalized_equals: list[tuple[str, str]] = []
    for field_name, expected in sorted(equals.items()):
        normalized_equals.append(
            (
                _provider_field_name(field_name, f"{path}.source_equals field"),
                _non_empty_string(expected, f"{path}.source_equals.{field_name}"),
            )
        )
    date_field = value.get("source_date_field")
    date_days = value.get("source_date_lte_days")
    if (date_field is None) != (date_days is None):
        raise ValueError(f"{path} source date selector is incomplete")
    return FanoutPolicy(
        strategy="dataset_field",
        parameter=_provider_parameter_name(value["parameter"], f"{path}.parameter"),
        source_dataset_id=_non_empty_string(
            value["source_dataset_id"], f"{path}.source_dataset_id"
        ),
        source_field=_provider_field_name(
            value["source_field"], f"{path}.source_field"
        ),
        batch_size=_positive_int(value["batch_size"], f"{path}.batch_size"),
        source_equals=tuple(normalized_equals),
        source_date_field=(
            None
            if date_field is None
            else _provider_field_name(date_field, f"{path}.source_date_field")
        ),
        source_date_lte_days=(
            None
            if date_days is None
            else _positive_int(date_days, f"{path}.source_date_lte_days")
        ),
        max_values=(
            None
            if value.get("max_values") is None
            else _positive_int(value["max_values"], f"{path}.max_values")
        ),
        source_order=_choice(
            value.get("source_order", "lexical"),
            frozenset({"lexical", "stable_hash"}),
            f"{path}.source_order",
        ),
    )


def _pagination_policy(raw: Any, *, path: str) -> PaginationPolicy:
    value = _mapping(raw, path)
    _reject_unknown_keys(
        value,
        _PAGINATION_KEYS,
        path,
        required=frozenset({"strategy"}),
    )
    strategy = _choice(value["strategy"], _PAGINATION_STRATEGIES, f"{path}.strategy")
    if strategy == "none":
        _reject_unknown_keys(
            value,
            frozenset({"strategy"}),
            path,
            required=frozenset({"strategy"}),
        )
        return PaginationPolicy(strategy="none")
    _reject_unknown_keys(value, _PAGINATION_KEYS, path, required=_PAGINATION_KEYS)
    limit_parameter = _provider_parameter_name(
        value["limit_parameter"], f"{path}.limit_parameter"
    )
    offset_parameter = _provider_parameter_name(
        value["offset_parameter"], f"{path}.offset_parameter"
    )
    if limit_parameter == offset_parameter:
        raise ValueError(f"{path} limit_parameter and offset_parameter must differ")
    return PaginationPolicy(
        strategy="offset",
        limit_parameter=limit_parameter,
        offset_parameter=offset_parameter,
        page_size=_positive_int(value["page_size"], f"{path}.page_size"),
        max_pages=_positive_int(value["max_pages"], f"{path}.max_pages"),
    )


def _request_window_policy(
    raw: Any,
    *,
    path: str,
    request_template: Mapping[str, str],
) -> RequestWindowPolicy | None:
    if raw is None:
        return None
    value = _mapping(raw, path)
    _reject_unknown_keys(
        value,
        _REQUEST_WINDOW_POLICY_KEYS,
        path,
        required=_REQUEST_WINDOW_POLICY_KEYS,
    )
    required_keys = _string_tuple(value["required_keys"], f"{path}.required_keys")
    _reject_duplicate_strings(required_keys, f"{path}.required_keys")
    formats_value = _mapping(value["formats"], f"{path}.formats")
    formats: dict[str, str] = {}
    for raw_key, raw_format in formats_value.items():
        key = _provider_parameter_name(raw_key, f"{path}.formats key")
        formats[key] = _choice(
            raw_format,
            _REQUEST_WINDOW_FORMATS,
            f"{path}.formats.{key}",
        )
    if set(formats) != set(required_keys):
        raise ValueError(f"{path}.formats keys must exactly equal required_keys")

    placeholders = tuple(
        match.group(1)
        for template_value in request_template.values()
        if (match := _WINDOW_PLACEHOLDER_PATTERN.fullmatch(template_value)) is not None
    )
    if len(placeholders) != len(set(placeholders)):
        raise ValueError(f"{path} request_template placeholders must be unique")
    if set(placeholders) != set(required_keys):
        raise ValueError(
            f"{path} request_template placeholders must exactly equal required_keys"
        )

    range_start_key = _provider_parameter_name(
        value["range_start_key"], f"{path}.range_start_key"
    )
    range_end_key = _provider_parameter_name(
        value["range_end_key"], f"{path}.range_end_key"
    )
    max_span_days = _positive_int(value["max_span_days"], f"{path}.max_span_days")
    if range_start_key == range_end_key and not (
        required_keys == (range_start_key,) and max_span_days == 1
    ):
        raise ValueError(
            f"{path} range start and end keys must differ unless one required key "
            "has max_span_days=1"
        )
    if {range_start_key, range_end_key} - set(required_keys):
        raise ValueError(f"{path} range keys must be declared in required_keys")
    if formats[range_start_key] != formats[range_end_key]:
        raise ValueError(f"{path} range start and end formats must match")

    return RequestWindowPolicy(
        required_keys=required_keys,
        formats=MappingProxyType(dict(sorted(formats.items()))),
        range_start_key=range_start_key,
        range_end_key=range_end_key,
        max_span_days=max_span_days,
    )


def _response_completeness_policy(
    raw: Any,
    *,
    path: str,
    request_template: Mapping[str, str],
    request_window_policy: RequestWindowPolicy | None,
) -> ResponseCompletenessPolicy | None:
    if raw is None:
        return None
    value = _mapping(raw, path)
    strategy = _choice(
        value["strategy"],
        _RESPONSE_COMPLETENESS_STRATEGIES,
        f"{path}.strategy",
    )
    required_keys = {
        "one_row_per_calendar_date": frozenset(
            {
                "strategy",
                "date_field",
                "request_start_key",
                "request_end_key",
                "fixed_field_matches",
            }
        ),
        "unique_primary_key_snapshot": frozenset(
            {"strategy", "fixed_field_matches", "reject_at_row_limit"}
        ),
        "single_partition_unique_primary_key": frozenset(
            {
                "strategy",
                "partition_field",
                "request_partition_key",
                "fixed_field_matches",
                "reject_at_row_limit",
            }
        ),
    }[strategy]
    allowed_keys = required_keys
    if strategy == "unique_primary_key_snapshot":
        allowed_keys = allowed_keys | {"snapshot_field"}
    if strategy == "one_row_per_calendar_date":
        allowed_keys = allowed_keys | {"reject_at_row_limit"}
    _reject_unknown_keys(value, allowed_keys, path, required=required_keys)
    reject_at_row_limit = _boolean(
        value.get("reject_at_row_limit", False), f"{path}.reject_at_row_limit"
    )

    date_field: str | None = None
    request_start_key: str | None = None
    request_end_key: str | None = None
    partition_field: str | None = None
    request_partition_key: str | None = None
    snapshot_field: str | None = None
    if strategy == "one_row_per_calendar_date":
        date_field = _provider_field_name(value["date_field"], f"{path}.date_field")
        request_start_key = _provider_parameter_name(
            value["request_start_key"], f"{path}.request_start_key"
        )
        request_end_key = _provider_parameter_name(
            value["request_end_key"], f"{path}.request_end_key"
        )
        if request_window_policy is None:
            raise ValueError(f"{path} requires request_window_policy")
        if request_start_key != request_window_policy.range_start_key:
            raise ValueError(
                f"{path}.request_start_key must equal the window range start"
            )
        if request_end_key != request_window_policy.range_end_key:
            raise ValueError(f"{path}.request_end_key must equal the window range end")
    elif strategy == "unique_primary_key_snapshot":
        if request_window_policy is not None:
            raise ValueError(
                f"{path}.unique_primary_key_snapshot must not use request_window_policy"
            )
        if "snapshot_field" in value:
            snapshot_field = _provider_field_name(
                value["snapshot_field"], f"{path}.snapshot_field"
            )
    else:
        partition_field = _provider_field_name(
            value["partition_field"], f"{path}.partition_field"
        )
        request_partition_key = _provider_parameter_name(
            value["request_partition_key"], f"{path}.request_partition_key"
        )
        if request_window_policy is None:
            raise ValueError(f"{path} requires request_window_policy")
        if (
            request_window_policy.required_keys != (request_partition_key,)
            or request_window_policy.range_start_key != request_partition_key
            or request_window_policy.range_end_key != request_partition_key
            or request_window_policy.max_span_days != 1
        ):
            raise ValueError(
                f"{path}.single_partition_unique_primary_key requires one "
                "max_span_days=1 request window key"
            )

    raw_matches = _mapping(value["fixed_field_matches"], f"{path}.fixed_field_matches")
    fixed_field_matches: dict[str, str] = {}
    for raw_field, raw_param in raw_matches.items():
        field_name = _provider_field_name(
            raw_field, f"{path}.fixed_field_matches row field"
        )
        param_name = _provider_parameter_name(
            raw_param, f"{path}.fixed_field_matches.{field_name}"
        )
        if param_name not in request_template:
            raise ValueError(
                f"{path}.fixed_field_matches target {param_name} is missing from "
                "request_template"
            )
        fixed_field_matches[field_name] = param_name
    return ResponseCompletenessPolicy(
        strategy=strategy,
        fixed_field_matches=MappingProxyType(dict(sorted(fixed_field_matches.items()))),
        reject_at_row_limit=reject_at_row_limit,
        date_field=date_field,
        request_start_key=request_start_key,
        request_end_key=request_end_key,
        partition_field=partition_field,
        request_partition_key=request_partition_key,
        snapshot_field=snapshot_field,
    )


def _load_query_defaults(raw: Any) -> QueryDefaults:
    value = _mapping(raw, "registry.query_defaults")
    _reject_unknown_keys(value, _QUERY_DEFAULT_KEYS, "registry.query_defaults")
    return QueryDefaults(
        **{
            key: _positive_int(value[key], f"registry.query_defaults.{key}")
            for key in sorted(_QUERY_DEFAULT_KEYS)
        }
    )


def _effective_profile_limit(
    value: Any,
    *,
    path: str,
    default: int,
) -> int:
    if value is None:
        return default
    limit = _positive_int(value, path)
    if limit > default:
        raise ValueError(f"{path} must not exceed registry default {default}")
    return limit


def _query_field(
    raw_name: Any,
    *,
    owner: str,
    capability: str,
    fields_by_name: Mapping[str, DatasetField],
    require_selectable: bool = False,
) -> str | None:
    field_name = _optional_non_empty_string(raw_name, f"{owner}.{capability}")
    if field_name is None:
        return None
    field = fields_by_name.get(field_name)
    if field is None:
        raise ValueError(f"{owner}.{capability} references unknown field: {field_name}")
    required = (
        ("selectable", field.selectable),
        ("filterable", field.filterable),
        ("sortable", field.sortable),
    )
    missing = [
        name
        for name, enabled in required
        if not enabled and (require_selectable or name != "selectable")
    ]
    if missing:
        required_label = (
            "selectable, filterable, and sortable"
            if require_selectable
            else "filterable and sortable"
        )
        raise ValueError(
            f"{owner}.{capability} field {field_name} must be {required_label}"
        )
    return field_name


def _load_field(raw: Any, *, dataset_id: str, index: int) -> DatasetField:
    path = f"dataset {dataset_id}.fields[{index}]"
    value = _mapping(raw, path)
    _reject_unknown_keys(value, _FIELD_KEYS, path)

    name = _non_empty_string(value["name"], f"{path}.name")
    selectable = _boolean(value["selectable"], f"{path}.selectable")
    filterable = _boolean(value["filterable"], f"{path}.filterable")
    sortable = _boolean(value["sortable"], f"{path}.sortable")
    if name in _INTERNAL_NON_QUERYABLE_FIELDS:
        for capability, enabled in (
            ("selectable", selectable),
            ("filterable", filterable),
            ("sortable", sortable),
        ):
            if enabled:
                raise ValueError(
                    f"dataset {dataset_id} field {name} must not be {capability}"
                )

    return DatasetField(
        name=name,
        logical_type=_choice(
            value["logical_type"], _LOGICAL_TYPES, f"{path}.logical_type"
        ),
        nullable=_boolean(value["nullable"], f"{path}.nullable"),
        selectable=selectable,
        filterable=filterable,
        sortable=sortable,
    )


def _load_binding(
    raw: Any,
    *,
    dataset_id: str,
    index: int,
) -> ProviderBinding:
    path = f"dataset {dataset_id}.provider_bindings[{index}]"
    value = _mapping(raw, path)
    _reject_unknown_keys(
        value,
        _BINDING_KEYS,
        path,
        required=_BINDING_REQUIRED_KEYS,
    )

    provider = _non_empty_string(value["provider"], f"{path}.provider")
    api_name = _provider_parameter_name(value["api_name"], f"{path}.api_name")
    adapter_version = _non_empty_string(
        value["adapter_version"], f"{path}.adapter_version"
    )
    read_discriminator_value = _non_empty_string(
        value["read_discriminator_value"], f"{path}.read_discriminator_value"
    )
    entitlement_state = _choice(
        value["entitlement_state"],
        _ENTITLEMENT_STATES,
        f"{path}.entitlement_state",
    )
    activation_state = _choice(
        value["activation_state"],
        _ACTIVATION_STATES,
        f"{path}.activation_state",
    )
    probe_state = _choice(value["probe_state"], _PROBE_STATES, f"{path}.probe_state")
    probe_block_reasons = _string_tuple(
        value["probe_block_reasons"],
        f"{path}.probe_block_reasons",
        allow_empty=True,
    )
    if (
        list(probe_block_reasons) != sorted(probe_block_reasons)
        or not set(probe_block_reasons).issubset(_PROBE_BLOCK_REASONS)
        or (probe_state == "executable") != (not probe_block_reasons)
    ):
        raise ValueError(f"{path}.probe_state/reasons are inconsistent")
    ingest_contract_state = _choice(
        value["ingest_contract_state"],
        _INGEST_CONTRACT_STATES,
        f"{path}.ingest_contract_state",
    )
    ingest_contract_block_reasons = _string_tuple(
        value["ingest_contract_block_reasons"],
        f"{path}.ingest_contract_block_reasons",
        allow_empty=True,
    )
    if (
        list(ingest_contract_block_reasons) != sorted(ingest_contract_block_reasons)
        or not set(ingest_contract_block_reasons).issubset(
            _INGEST_CONTRACT_BLOCK_REASONS
        )
        or (ingest_contract_state == "ready") != (not ingest_contract_block_reasons)
    ):
        raise ValueError(f"{path}.ingest_contract_state/reasons are inconsistent")
    target_tables = _string_tuple(value["target_tables"], f"{path}.target_tables")
    _reject_duplicate_strings(target_tables, f"{path}.target_tables")
    input_fields = _provider_input_fields(
        value["input_fields"],
        f"{path}.input_fields",
    )
    request_shape = (
        None
        if "request_shape" not in value
        else _choice(
            value["request_shape"],
            _REQUEST_SHAPES,
            f"{path}.request_shape",
        )
    )
    request_template = _request_template(
        value.get("request_template", {}),
        f"{path}.request_template",
    )
    request_variants = _request_variants(
        value.get("request_variants", [{}]),
        path=f"{path}.request_variants",
        request_template=request_template,
    )
    fanout = (
        None
        if "fanout" not in value
        else _fanout_policy(value["fanout"], path=f"{path}.fanout")
    )
    pagination = (
        None
        if "pagination" not in value
        else _pagination_policy(value["pagination"], path=f"{path}.pagination")
    )
    if request_shape in {"entity_fanout", "dimension_fanout"} and fanout is not None:
        if fanout.strategy != "dataset_field":
            raise ValueError(
                f"{path}.{request_shape} requires fanout.strategy=dataset_field"
            )
    elif request_shape is not None and fanout is not None and fanout.strategy != "none":
        raise ValueError(f"{path}.{request_shape} requires fanout.strategy=none")
    request_window_policy = _request_window_policy(
        value.get("request_window_policy"),
        path=f"{path}.request_window_policy",
        request_template=request_template,
    )
    response_completeness = _response_completeness_policy(
        value.get("response_completeness"),
        path=f"{path}.response_completeness",
        request_template=request_template,
        request_window_policy=request_window_policy,
    )
    requested_fields = _string_tuple(
        value.get("requested_fields", []),
        f"{path}.requested_fields",
        allow_empty=True,
    )
    requested_fields = tuple(
        _provider_field_name(field_name, f"{path}.requested_fields[{field_index}]")
        for field_index, field_name in enumerate(requested_fields)
    )
    _reject_duplicate_strings(requested_fields, f"{path}.requested_fields")

    if activation_state == "active":
        if entitlement_state != "active":
            raise ValueError(
                f"{path} activation_state=active requires entitlement_state=active"
            )
        if probe_state != "executable" or ingest_contract_state != "ready":
            raise ValueError(
                f"{path} activation_state=active requires executable/ready request contract"
            )
        if request_window_policy is not None and any(
            format_name not in _RUNTIME_REQUEST_WINDOW_FORMATS
            for format_name in request_window_policy.formats.values()
        ):
            raise ValueError(
                f"{path} activation_state=active requires a runtime request_window format"
            )
    return ProviderBinding(
        provider=provider,
        api_name=api_name,
        adapter_version=adapter_version,
        read_discriminator_value=read_discriminator_value,
        entitlement_state=entitlement_state,
        activation_state=activation_state,
        probe_state=probe_state,
        probe_block_reasons=probe_block_reasons,
        ingest_contract_state=ingest_contract_state,
        ingest_contract_block_reasons=ingest_contract_block_reasons,
        target_tables=target_tables,
        input_fields=input_fields,
        request_shape=request_shape,
        request_template=request_template,
        request_variants=request_variants,
        fanout=fanout,
        pagination=pagination,
        request_window_policy=request_window_policy,
        response_completeness=response_completeness,
        requested_fields=requested_fields,
        max_rows_per_attempt=_optional_positive_int(
            value.get("max_rows_per_attempt"),
            f"{path}.max_rows_per_attempt",
        ),
        max_payload_bytes_per_row=_optional_positive_int(
            value.get("max_payload_bytes_per_row"),
            f"{path}.max_payload_bytes_per_row",
        ),
        max_batch_bytes=_optional_positive_int(
            value.get("max_batch_bytes"),
            f"{path}.max_batch_bytes",
        ),
        max_nesting_depth=_optional_positive_int(
            value.get("max_nesting_depth"),
            f"{path}.max_nesting_depth",
        ),
    )


def _load_read_model_adapter(
    raw: Any,
    *,
    dataset_id: str,
) -> ReadModelAdapter:
    path = f"dataset {dataset_id}.read_model_adapter"
    value = _mapping(raw, path)
    _reject_unknown_keys(
        value,
        _READ_MODEL_ADAPTER_KEYS,
        path,
        required=_READ_MODEL_ADAPTER_REQUIRED_KEYS,
    )

    adapter_version = _non_empty_string(
        value["adapter_version"], f"{path}.adapter_version"
    )
    primary_table = _non_empty_string(value["primary_table"], f"{path}.primary_table")
    if primary_table != _PROVIDER_NATIVE_TABLE:
        raise ValueError(f"{path}.primary_table must be {_PROVIDER_NATIVE_TABLE}")
    raw_filters = value["fixed_field_filters"]
    if not isinstance(raw_filters, list):
        raise ValueError(f"{path}.fixed_field_filters must be a list")
    if raw_filters:
        raise ValueError(f"{path}.fixed_field_filters must be empty")

    return ReadModelAdapter(
        adapter_version=adapter_version,
        primary_table=primary_table,
        fixed_field_filters=(),
        storage_kind=_choice(
            value["storage_kind"],
            _STORAGE_KINDS,
            f"{path}.storage_kind",
        ),
        row_key_strategy=_choice(
            value["row_key_strategy"],
            _ROW_KEY_STRATEGIES,
            f"{path}.row_key_strategy",
        ),
    )


def _load_schema_contract(
    value: Mapping[str, Any],
    *,
    owner: str,
    query_defaults: QueryDefaults,
) -> DatasetSchemaProfile:
    raw_fields = value["fields"]
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError(f"{owner}.fields must be a non-empty list")
    fields = tuple(
        _load_field(field, dataset_id=owner, index=field_index)
        for field_index, field in enumerate(raw_fields)
    )
    fields_by_name: dict[str, DatasetField] = {}
    for field in fields:
        if field.name in fields_by_name:
            raise ValueError(f"{owner}.fields contains duplicate field: {field.name}")
        fields_by_name[field.name] = field

    primary_key = _string_tuple(
        value["primary_key"],
        f"{owner}.primary_key",
        allow_empty=True,
    )
    _reject_duplicate_strings(primary_key, f"{owner}.primary_key")
    missing_primary_fields = sorted(set(primary_key) - set(fields_by_name))
    if missing_primary_fields:
        raise ValueError(
            f"{owner}.primary_key fields are not declared in fields: "
            f"{', '.join(missing_primary_fields)}"
        )
    invalid_primary_fields = [
        field_name
        for field_name in primary_key
        if not fields_by_name[field_name].selectable
        or not fields_by_name[field_name].sortable
    ]
    if invalid_primary_fields:
        raise ValueError(
            f"{owner}.primary_key fields must be selectable and sortable: "
            f"{', '.join(invalid_primary_fields)}"
        )

    default_projection = _string_tuple(
        value["default_projection"], f"{owner}.default_projection"
    )
    _reject_duplicate_strings(default_projection, f"{owner}.default_projection")
    for field_name in default_projection:
        field = fields_by_name.get(field_name)
        if field is None:
            raise ValueError(
                f"{owner}.default_projection references unknown field: {field_name}"
            )
        if not field.selectable:
            raise ValueError(
                f"{owner}.default_projection field is not selectable: {field_name}"
            )

    as_of_field = _query_field(
        value["as_of_field"],
        owner=owner,
        capability="as_of_field",
        fields_by_name=fields_by_name,
        require_selectable=True,
    )
    as_of_format = _optional_non_empty_string(
        value["as_of_format"], f"{owner}.as_of_format"
    )
    if as_of_field is None:
        if as_of_format is not None:
            raise ValueError(f"{owner}.as_of_format requires as_of_field")
    else:
        if as_of_format is None:
            raise ValueError(f"{owner}.as_of_field requires as_of_format")
        if as_of_format not in _AS_OF_FORMATS:
            choices = ", ".join(sorted(_AS_OF_FORMATS))
            raise ValueError(f"{owner}.as_of_format must be one of: {choices}")
        if fields_by_name[as_of_field].logical_type != "text":
            raise ValueError(f"{owner}.as_of_field must use logical_type text")

    range_field = _query_field(
        value["range_field"],
        owner=owner,
        capability="range_field",
        fields_by_name=fields_by_name,
    )
    partition_field = _query_field(
        value["partition_field"],
        owner=owner,
        capability="partition_field",
        fields_by_name=fields_by_name,
    )

    point_in_time = _choice(
        value["point_in_time"], _POINT_IN_TIME_MODES, f"{owner}.point_in_time"
    )
    if point_in_time == "current_snapshot" and not primary_key:
        raise ValueError(f"{owner} current_snapshot requires a non-empty primary_key")

    return DatasetSchemaProfile(
        schema_version=_non_empty_string(
            value["schema_version"], f"{owner}.schema_version"
        ),
        fields=fields,
        primary_key=primary_key,
        default_projection=default_projection,
        as_of_field=as_of_field,
        as_of_format=as_of_format,
        range_field=range_field,
        partition_field=partition_field,
        max_page_size=_effective_profile_limit(
            value.get("max_page_size"),
            path=f"{owner}.max_page_size",
            default=query_defaults.max_page_size,
        ),
        max_lookback_days=_effective_profile_limit(
            value.get("max_lookback_days"),
            path=f"{owner}.max_lookback_days",
            default=query_defaults.max_lookback_days,
        ),
        point_in_time=point_in_time,
        backfill_policy=_choice(
            value["backfill_policy"],
            _BACKFILL_POLICIES,
            f"{owner}.backfill_policy",
        ),
        empty_data_policy=_choice(
            value["empty_data_policy"],
            _EMPTY_DATA_POLICIES,
            f"{owner}.empty_data_policy",
        ),
        required_scope=_non_empty_string(
            value["required_scope"], f"{owner}.required_scope"
        ),
        quota_class=_non_empty_string(value["quota_class"], f"{owner}.quota_class"),
    )


def _load_schema_profiles(
    raw: Any,
    *,
    query_defaults: QueryDefaults,
) -> Mapping[str, DatasetSchemaProfile]:
    if raw is None:
        return MappingProxyType({})
    values = _mapping(raw, "registry.schema_profiles")
    profiles: dict[str, DatasetSchemaProfile] = {}
    for raw_name, raw_profile in values.items():
        name = _non_empty_string(raw_name, "registry.schema_profiles key")
        path = f"registry.schema_profiles.{name}"
        profile_value = _mapping(raw_profile, path)
        _reject_unknown_keys(
            profile_value,
            _SCHEMA_PROFILE_KEYS,
            path,
            required=_SCHEMA_PROFILE_REQUIRED_KEYS,
        )
        profiles[name] = _load_schema_contract(
            profile_value,
            owner=f"schema_profile {name}",
            query_defaults=query_defaults,
        )
    return MappingProxyType(profiles)


def _load_dataset(
    raw: Any,
    index: int,
    schema_profiles: Mapping[str, DatasetSchemaProfile],
    query_defaults: QueryDefaults,
) -> DatasetDefinition:
    path = f"datasets[{index}]"
    value = _mapping(raw, path)
    _reject_unknown_keys(
        value,
        _DATASET_KEYS,
        path,
        required=_DATASET_REQUIRED_KEYS,
    )

    dataset_id = _non_empty_string(value["dataset_id"], f"{path}.dataset_id")
    schema_version = _non_empty_string(
        value["schema_version"], f"dataset {dataset_id}.schema_version"
    )
    schema_profile_name = value.get("schema_profile")
    if schema_profile_name is None:
        missing_contract_keys = sorted(_PROFILE_CONTRACT_REQUIRED_KEYS - set(value))
        if missing_contract_keys:
            raise ValueError(
                f"dataset {dataset_id} must declare an inline schema contract or "
                f"schema_profile; missing: {', '.join(missing_contract_keys)}"
            )
        schema_contract = _load_schema_contract(
            value,
            owner=f"dataset {dataset_id}",
            query_defaults=query_defaults,
        )
    else:
        schema_profile_name = _non_empty_string(
            schema_profile_name,
            f"dataset {dataset_id}.schema_profile",
        )
        inline_contract_keys = sorted(_PROFILE_CONTRACT_KEYS & set(value))
        if inline_contract_keys:
            raise ValueError(
                f"dataset {dataset_id} schema_profile entries must not declare inline "
                f"contract keys: {', '.join(inline_contract_keys)}"
            )
        try:
            schema_contract = schema_profiles[schema_profile_name]
        except KeyError as exc:
            raise ValueError(
                f"dataset {dataset_id} references unknown schema_profile: "
                f"{schema_profile_name}"
            ) from exc
        if schema_version != schema_contract.schema_version:
            raise ValueError(
                f"dataset {dataset_id}.schema_version {schema_version!r} does not "
                f"match schema_profile {schema_profile_name!r} version "
                f"{schema_contract.schema_version!r}"
            )

    fields = schema_contract.fields
    fields_by_name = {field.name: field for field in fields}
    primary_key = schema_contract.primary_key
    default_projection = schema_contract.default_projection

    raw_bindings = value["provider_bindings"]
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise ValueError(
            f"dataset {dataset_id}.provider_bindings must be a non-empty list"
        )
    provider_bindings = tuple(
        _load_binding(binding, dataset_id=dataset_id, index=binding_index)
        for binding_index, binding in enumerate(raw_bindings)
    )
    read_discriminator_values = tuple(
        binding.read_discriminator_value for binding in provider_bindings
    )
    if len(set(read_discriminator_values)) != len(read_discriminator_values):
        raise ValueError(
            f"dataset {dataset_id}.provider_bindings contains duplicate "
            "read_discriminator_value"
        )
    read_model_adapter = _load_read_model_adapter(
        value["read_model_adapter"],
        dataset_id=dataset_id,
    )
    if read_model_adapter.storage_kind == _PROVIDER_NATIVE_STORAGE_KIND:
        nullable_primary_fields = [
            field_name
            for field_name in primary_key
            if fields_by_name[field_name].nullable
        ]
        if nullable_primary_fields:
            raise ValueError(
                f"dataset {dataset_id}.primary_key fields must not be nullable: "
                f"{', '.join(nullable_primary_fields)}"
            )
        if read_model_adapter.primary_table != _PROVIDER_NATIVE_TABLE:
            raise ValueError(
                f"dataset {dataset_id} provider_native_rows primary_table must be "
                f"{_PROVIDER_NATIVE_TABLE}"
            )
        if read_model_adapter.fixed_field_filters:
            raise ValueError(
                f"dataset {dataset_id} provider_native_rows fixed_field_filters "
                "must be empty"
            )
        expected_strategy = {
            "current_snapshot": "primary_key",
            "append_only": "payload_hash",
        }.get(schema_contract.point_in_time)
        if expected_strategy is None:
            raise ValueError(
                f"dataset {dataset_id} point_in_time=unsupported cannot use "
                "provider_native_rows"
            )
        if read_model_adapter.row_key_strategy != expected_strategy:
            raise ValueError(
                f"dataset {dataset_id} {schema_contract.point_in_time} requires "
                f"row_key_strategy={expected_strategy}"
            )
        if _SCHEMA_VERSION_PATTERN.fullmatch(schema_version) is None:
            raise ValueError(
                f"dataset {dataset_id}.schema_version must use MAJOR.MINOR.PATCH"
            )
        invalid_field_names = sorted(
            field.name
            for field in fields
            if _PROVIDER_FIELD_PATTERN.fullmatch(field.name) is None
        )
        if invalid_field_names:
            raise ValueError(
                f"dataset {dataset_id} field name must use provider field grammar: "
                f"{', '.join(invalid_field_names)}"
            )
        for raw_binding_index, (raw_binding, binding) in enumerate(
            zip(raw_bindings, provider_bindings)
        ):
            binding_path = (
                f"dataset {dataset_id}.provider_bindings[{raw_binding_index}]"
            )
            binding_value = _mapping(raw_binding, binding_path)
            missing_generic_keys = sorted(_GENERIC_BINDING_KEYS - set(binding_value))
            if missing_generic_keys:
                raise ValueError(
                    f"{binding_path} missing generic request contract key(s): "
                    f"{', '.join(missing_generic_keys)}"
                )
            if binding.target_tables != (_PROVIDER_NATIVE_TABLE,):
                raise ValueError(
                    f"{binding_path}.target_tables must be exactly "
                    f"{_PROVIDER_NATIVE_TABLE}"
                )
            undeclared_requested_fields = sorted(
                set(binding.requested_fields) - set(fields_by_name)
            )
            if undeclared_requested_fields:
                raise ValueError(
                    f"{binding_path}.requested_fields reference undeclared field(s): "
                    f"{', '.join(undeclared_requested_fields)}"
                )
            completeness = binding.response_completeness
            if completeness is None:
                continue
            if (
                completeness.strategy == "one_row_per_calendar_date"
                and schema_contract.empty_data_policy != "forbidden"
            ):
                raise ValueError(
                    f"{binding_path}.response_completeness requires "
                    "empty_data_policy=forbidden"
                )
            undeclared_fixed_fields = sorted(
                set(completeness.fixed_field_matches) - set(fields_by_name)
            )
            if undeclared_fixed_fields:
                raise ValueError(
                    f"{binding_path}.response_completeness.fixed_field_matches "
                    f"reference undeclared field(s): {', '.join(undeclared_fixed_fields)}"
                )
            for fixed_field in completeness.fixed_field_matches:
                field_contract = fields_by_name[fixed_field]
                if field_contract.logical_type != "text" or field_contract.nullable:
                    raise ValueError(
                        f"{binding_path}.response_completeness.fixed_field_matches "
                        "fields must be non-null text"
                    )
            completeness_key_fields = set(primary_key) | set(
                completeness.fixed_field_matches
            )
            if completeness.strategy == "one_row_per_calendar_date":
                date_field = completeness.date_field
                if date_field not in fields_by_name:
                    raise ValueError(
                        f"{binding_path}.response_completeness.date_field is "
                        f"undeclared: {date_field}"
                    )
                if (
                    schema_contract.as_of_field != date_field
                    or schema_contract.as_of_format != "yyyymmdd"
                ):
                    raise ValueError(
                        f"{binding_path}.response_completeness.date_field must be "
                        "the dataset yyyymmdd as_of_field"
                    )
                if (
                    schema_contract.range_field != date_field
                    or schema_contract.partition_field != date_field
                ):
                    raise ValueError(
                        f"{binding_path}.response_completeness requires "
                        "as_of/range/partition to equal date_field"
                    )
                completeness_date = fields_by_name[date_field]
                if (
                    completeness_date.logical_type != "text"
                    or completeness_date.nullable
                ):
                    raise ValueError(
                        f"{binding_path}.response_completeness.date_field must be "
                        "non-null text"
                    )
                calendar_key_fields = {date_field, *completeness.fixed_field_matches}
                if set(primary_key) != calendar_key_fields:
                    raise ValueError(
                        f"{binding_path}.primary_key must exactly contain completeness "
                        "date_field and fixed row fields"
                    )
            elif completeness.strategy == "single_partition_unique_primary_key":
                partition_field = completeness.partition_field
                if partition_field not in fields_by_name:
                    raise ValueError(
                        f"{binding_path}.response_completeness.partition_field is "
                        f"undeclared: {partition_field}"
                    )
                if (
                    schema_contract.as_of_field != partition_field
                    or schema_contract.range_field != partition_field
                    or schema_contract.partition_field != partition_field
                    or schema_contract.as_of_format != "yyyymmdd"
                ):
                    raise ValueError(
                        f"{binding_path}.response_completeness.partition_field must "
                        "be the dataset yyyymmdd as_of/range/partition field"
                    )
                partition_contract = fields_by_name[partition_field]
                if (
                    partition_contract.logical_type != "text"
                    or partition_contract.nullable
                ):
                    raise ValueError(
                        f"{binding_path}.response_completeness.partition_field must "
                        "be non-null text"
                    )
                if partition_field not in primary_key:
                    raise ValueError(
                        f"{binding_path}.response_completeness.partition_field must "
                        "be in primary_key"
                    )
                completeness_key_fields.add(partition_field)
            if binding.requested_fields:
                missing_completeness_fields = sorted(
                    completeness_key_fields - set(binding.requested_fields)
                )
                if missing_completeness_fields:
                    raise ValueError(
                        f"{binding_path}.requested_fields must include completeness "
                        f"field(s): {', '.join(missing_completeness_fields)}"
                    )
            if completeness.snapshot_field is not None:
                snapshot_field = completeness.snapshot_field
                if snapshot_field not in fields_by_name:
                    raise ValueError(
                        f"{binding_path}.response_completeness.snapshot_field is "
                        "undeclared"
                    )
                if snapshot_field not in binding.requested_fields:
                    raise ValueError(
                        f"{binding_path}.requested_fields must include "
                        "response_completeness.snapshot_field"
                    )
            if binding.request_window_policy is not None:
                if (
                    binding.max_rows_per_attempt is None
                    or binding.max_rows_per_attempt
                    < binding.request_window_policy.max_span_days
                ):
                    raise ValueError(
                        f"{binding_path}.max_rows_per_attempt must be >= "
                        "request_window_policy.max_span_days"
                    )
    missing_read_tables = [
        binding.provider
        for binding in provider_bindings
        if read_model_adapter.primary_table not in binding.target_tables
    ]
    if missing_read_tables:
        raise ValueError(
            f"dataset {dataset_id}.read_model_adapter.primary_table must be listed in "
            "provider binding target_tables for: "
            f"{', '.join(missing_read_tables)}"
        )
    return DatasetDefinition(
        dataset_id=dataset_id,
        aliases=_string_tuple(value["aliases"], f"dataset {dataset_id}.aliases"),
        domain=_non_empty_string(value["domain"], f"dataset {dataset_id}.domain"),
        market=_non_empty_string(value["market"], f"dataset {dataset_id}.market"),
        entity_type=_non_empty_string(
            value["entity_type"], f"dataset {dataset_id}.entity_type"
        ),
        data_classification=_choice(
            value["data_classification"],
            _DATA_CLASSIFICATIONS,
            f"dataset {dataset_id}.data_classification",
        ),
        schema_version=schema_version,
        fields=fields,
        primary_key=primary_key,
        default_projection=default_projection,
        as_of_field=schema_contract.as_of_field,
        as_of_format=schema_contract.as_of_format,
        range_field=schema_contract.range_field,
        partition_field=schema_contract.partition_field,
        cadence_class=_non_empty_string(
            value["cadence_class"], f"dataset {dataset_id}.cadence_class"
        ),
        timezone=_non_empty_string(value["timezone"], f"dataset {dataset_id}.timezone"),
        freshness_sla_seconds=_positive_int(
            value["freshness_sla_seconds"],
            f"dataset {dataset_id}.freshness_sla_seconds",
        ),
        max_page_size=schema_contract.max_page_size,
        max_lookback_days=schema_contract.max_lookback_days,
        point_in_time=schema_contract.point_in_time,
        backfill_policy=schema_contract.backfill_policy,
        empty_data_policy=schema_contract.empty_data_policy,
        required_scope=schema_contract.required_scope,
        quota_class=schema_contract.quota_class,
        provider_bindings=provider_bindings,
        read_model_adapter=read_model_adapter,
    )


def load_dataset_registry(
    path: Path = DATASET_REGISTRY_PATH,
) -> DatasetRegistry:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    root = _mapping(raw, "registry")
    _reject_unknown_keys(
        root,
        _ROOT_KEYS,
        "registry",
        required=_ROOT_REQUIRED_KEYS,
    )

    version = root["version"]
    if isinstance(version, bool) or version != 1:
        raise ValueError("registry.version must be integer 1")
    raw_datasets = root["datasets"]
    if not isinstance(raw_datasets, list) or not raw_datasets:
        raise ValueError("registry.datasets must be a non-empty list")
    query_defaults = _load_query_defaults(root["query_defaults"])
    schema_profiles = _load_schema_profiles(
        root.get("schema_profiles"),
        query_defaults=query_defaults,
    )

    return DatasetRegistry(
        tuple(
            _load_dataset(dataset, index, schema_profiles, query_defaults)
            for index, dataset in enumerate(raw_datasets)
        ),
        query_defaults=query_defaults,
    )


def runtime_dataset_registry_path() -> Path:
    """Return the process-selected registry without exposing a path selector.

    The default and only accepted override are the repository-owned
    provider-native artifact. Request, tenant, dataset and ordinary CLI input
    therefore cannot redirect the process to an arbitrary contract.
    """

    raw_path = os.environ.get(DATASET_REGISTRY_PATH_ENV)
    canary_mode = os.environ.get(CANARY_MODE_ENV)
    if canary_mode not in {None, BINANCE_SPOT_CANARY_MODE}:
        raise ValueError(f"{CANARY_MODE_ENV} is invalid")
    if canary_mode == BINANCE_SPOT_CANARY_MODE:
        if raw_path is not None:
            raise ValueError("canary registry does not accept a path override")
        expected = BINANCE_SPOT_CANARY_REGISTRY_PATH
    else:
        expected = PROVIDER_NATIVE_DATASET_REGISTRY_PATH
    if raw_path is None:
        raw_path = os.fspath(expected)
    if not raw_path or raw_path != raw_path.strip():
        raise ValueError(f"{DATASET_REGISTRY_PATH_ENV} is invalid")

    selected = Path(raw_path)
    if not selected.is_absolute() or os.path.normpath(raw_path) != raw_path:
        raise ValueError(f"{DATASET_REGISTRY_PATH_ENV} must be canonical")
    if selected != expected:
        raise ValueError(f"{DATASET_REGISTRY_PATH_ENV} is not a trusted registry")

    for component in (expected.parent, expected):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError as exc:
            raise FileNotFoundError("trusted dataset registry is missing") from exc
        if stat.S_ISLNK(mode):
            raise ValueError("trusted dataset registry path cannot contain a symlink")
    if not stat.S_ISDIR(expected.parent.lstat().st_mode):
        raise ValueError("trusted dataset registry parent must be a directory")
    if not stat.S_ISREG(expected.lstat().st_mode):
        raise ValueError("trusted dataset registry must be a regular file")
    if expected.resolve(strict=True) != expected:
        raise ValueError("trusted dataset registry path is not canonical")
    return expected


def load_runtime_dataset_registry() -> DatasetRegistry:
    """Load the immutable registry chosen by trusted process configuration."""

    return load_dataset_registry(runtime_dataset_registry_path())
