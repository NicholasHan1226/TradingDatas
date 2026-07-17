"""Provider-neutral dataset declarations for SharedSignals.

The registry describes immutable dataset, ingest-adapter, and read-model
contracts only. Runtime collection state remains authoritative in SQLite ingest
receipts and is deliberately rejected from this YAML authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping

import yaml


DATASET_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "config" / "dataset_registry.yaml"
)
PROVIDER_NATIVE_DATASET_REGISTRY_PATH = (
    Path(__file__).resolve().parent
    / "config"
    / "provider_native_dataset_registry.yaml"
)
DATASET_REGISTRY_PATH_ENV = "SHAREDSIGNALS_DATASET_REGISTRY_PATH"

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
        "target_tables",
        "request_template",
        "requested_fields",
        "max_rows_per_attempt",
        "max_payload_bytes_per_row",
        "max_batch_bytes",
        "max_nesting_depth",
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
        "target_tables",
    }
)
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
    {"adapter_version", "primary_table", "fixed_field_filters"}
)
_FIXED_FILTER_KEYS = frozenset({"field", "allowed_values"})

_LOGICAL_TYPES = frozenset({"text", "float", "integer"})
_ENTITLEMENT_STATES = frozenset({"active", "locked", "unknown", "excluded", "retired"})
_ACTIVATION_STATES = frozenset({"active", "paused"})
_POINT_IN_TIME_MODES = frozenset({"append_only", "current_snapshot", "unsupported"})
_BACKFILL_POLICIES = frozenset({"provider_limited", "disabled"})
_EMPTY_DATA_POLICIES = frozenset({"allowed", "forbidden"})
_DATA_CLASSIFICATIONS = frozenset({"objective_factual"})
_INTERNAL_NON_QUERYABLE_FIELDS = frozenset({"raw_json", "source_file"})
_AS_OF_FORMATS = frozenset({"yyyymmdd", "rfc3339"})
_ORDERED_LOGICAL_TYPES = frozenset({"text", "float", "integer"})
_STORAGE_KINDS = frozenset({"typed_columns", "provider_native_rows"})
_ROW_KEY_STRATEGIES = frozenset({"primary_key", "payload_hash"})
_PROVIDER_FIELD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_WINDOW_PLACEHOLDER_PATTERN = re.compile(r"\$\{window\.([A-Za-z_][A-Za-z0-9_]{0,63})\}")
_SCHEMA_VERSION_PATTERN = re.compile(
    r"(?P<major>[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_GENERIC_BINDING_KEYS = frozenset(
    {
        "request_template",
        "requested_fields",
        "max_rows_per_attempt",
        "max_payload_bytes_per_row",
        "max_batch_bytes",
        "max_nesting_depth",
    }
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
    storage_kind: str = "typed_columns"
    row_key_strategy: str | None = None


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
    request_template: Mapping[str, str] = dataclass_field(
        default_factory=lambda: MappingProxyType({})
    )
    requested_fields: tuple[str, ...] = ()
    max_rows_per_attempt: int | None = None
    max_payload_bytes_per_row: int | None = None
    max_batch_bytes: int | None = None
    max_nesting_depth: int | None = None


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

    def compatibility_api_names(self, provider: str) -> frozenset[str]:
        return frozenset(
            binding.api_name
            for dataset in self._datasets
            for binding in dataset.provider_bindings
            if binding.provider == provider
        )

    def compatibility_table_map(self, provider: str) -> dict[str, str]:
        return {
            binding.api_name: dataset.read_model_adapter.primary_table
            for dataset in self._datasets
            for binding in dataset.provider_bindings
            if binding.provider == provider
        }

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


def _request_template(raw: Any, path: str) -> Mapping[str, str]:
    value = _mapping(raw, path)
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _provider_field_name(raw_key, f"{path} key")
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
    api_name = _non_empty_string(value["api_name"], f"{path}.api_name")
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
    target_tables = _string_tuple(value["target_tables"], f"{path}.target_tables")
    _reject_duplicate_strings(target_tables, f"{path}.target_tables")
    request_template = _request_template(
        value.get("request_template", {}),
        f"{path}.request_template",
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
    return ProviderBinding(
        provider=provider,
        api_name=api_name,
        adapter_version=adapter_version,
        read_discriminator_value=read_discriminator_value,
        entitlement_state=entitlement_state,
        activation_state=activation_state,
        target_tables=target_tables,
        request_template=request_template,
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
    fields_by_name: Mapping[str, DatasetField],
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
    raw_filters = value["fixed_field_filters"]
    if not isinstance(raw_filters, list):
        raise ValueError(f"{path}.fixed_field_filters must be a list")

    fixed_filters: list[FixedFieldFilter] = []
    seen_fields: set[str] = set()
    for index, raw_filter in enumerate(raw_filters):
        filter_path = f"{path}.fixed_field_filters[{index}]"
        filter_value = _mapping(raw_filter, filter_path)
        _reject_unknown_keys(filter_value, _FIXED_FILTER_KEYS, filter_path)
        field = _non_empty_string(filter_value["field"], f"{filter_path}.field")
        if field not in fields_by_name:
            raise ValueError(
                f"{path}.fixed_field_filters references unknown field: {field}"
            )
        if field in seen_fields:
            raise ValueError(
                f"{path}.fixed_field_filters contains duplicate field: {field}"
            )
        seen_fields.add(field)
        allowed_values = _string_tuple(
            filter_value["allowed_values"], f"{filter_path}.allowed_values"
        )
        _reject_duplicate_strings(allowed_values, f"{filter_path}.allowed_values")
        fixed_filters.append(
            FixedFieldFilter(
                field=field,
                allowed_values=allowed_values,
            )
        )

    return ReadModelAdapter(
        adapter_version=adapter_version,
        primary_table=primary_table,
        fixed_field_filters=tuple(fixed_filters),
        storage_kind=_choice(
            value.get("storage_kind", "typed_columns"),
            _STORAGE_KINDS,
            f"{path}.storage_kind",
        ),
        row_key_strategy=(
            None
            if value.get("row_key_strategy") is None
            else _choice(
                value["row_key_strategy"],
                _ROW_KEY_STRATEGIES,
                f"{path}.row_key_strategy",
            )
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

    primary_key = _string_tuple(value["primary_key"], f"{owner}.primary_key")
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
        point_in_time=_choice(
            value["point_in_time"], _POINT_IN_TIME_MODES, f"{owner}.point_in_time"
        ),
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
        fields_by_name=fields_by_name,
    )
    if read_model_adapter.storage_kind == "typed_columns":
        if read_model_adapter.row_key_strategy is not None:
            raise ValueError(
                f"dataset {dataset_id} typed_columns must not declare row_key_strategy"
            )
        if not read_model_adapter.fixed_field_filters:
            raise ValueError(
                f"dataset {dataset_id} typed_columns fixed_field_filters "
                "must be a non-empty list"
            )
        for raw_binding_index, raw_binding in enumerate(raw_bindings):
            binding_value = _mapping(
                raw_binding,
                f"dataset {dataset_id}.provider_bindings[{raw_binding_index}]",
            )
            unexpected = sorted(_GENERIC_BINDING_KEYS & set(binding_value))
            if unexpected:
                raise ValueError(
                    f"dataset {dataset_id} typed_columns binding must not declare "
                    f"generic request contract keys: {', '.join(unexpected)}"
                )
    else:
        if read_model_adapter.primary_table != "provider_dataset_rows":
            raise ValueError(
                f"dataset {dataset_id} provider_native_rows primary_table must be "
                "provider_dataset_rows"
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
            if binding.target_tables != ("provider_dataset_rows",):
                raise ValueError(
                    f"{binding_path}.target_tables must be exactly "
                    "provider_dataset_rows"
                )
            undeclared_requested_fields = sorted(
                set(binding.requested_fields) - set(fields_by_name)
            )
            if undeclared_requested_fields:
                raise ValueError(
                    f"{binding_path}.requested_fields reference undeclared field(s): "
                    f"{', '.join(undeclared_requested_fields)}"
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
    if read_model_adapter.storage_kind == "typed_columns":
        provider_filters = tuple(
            fixed_filter
            for fixed_filter in read_model_adapter.fixed_field_filters
            if fixed_filter.field == "provider"
        )
        if len(provider_filters) != 1 or set(provider_filters[0].allowed_values) != set(
            read_discriminator_values
        ):
            raise ValueError(
                f"dataset {dataset_id} provider binding read_discriminator_value "
                "values must exactly equal read_model_adapter provider allowed_values"
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

    An unset environment variable preserves the legacy compatibility registry.
    The only accepted override is the repository-owned provider-native target
    artifact. Request, tenant, dataset and ordinary CLI input therefore cannot
    redirect the process to an arbitrary contract.
    """

    raw_path = os.environ.get(DATASET_REGISTRY_PATH_ENV)
    if raw_path is None:
        return DATASET_REGISTRY_PATH
    if not raw_path or raw_path != raw_path.strip():
        raise ValueError(f"{DATASET_REGISTRY_PATH_ENV} is invalid")

    selected = Path(raw_path)
    expected = PROVIDER_NATIVE_DATASET_REGISTRY_PATH
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

    path = runtime_dataset_registry_path()
    if path == DATASET_REGISTRY_PATH:
        # Preserve the legacy no-argument loader seam for compatibility tests
        # and consumers that inject the default registry before runtime build.
        return load_dataset_registry()
    return load_dataset_registry(path)


_DEFAULT_DATASET_REGISTRY = load_dataset_registry()
TUSHARE_API_TO_TABLE_MAP: Mapping[str, str] = MappingProxyType(
    _DEFAULT_DATASET_REGISTRY.compatibility_table_map("tushare")
)
TUSHARE_ALLOWED_API_NAMES = _DEFAULT_DATASET_REGISTRY.compatibility_api_names("tushare")
