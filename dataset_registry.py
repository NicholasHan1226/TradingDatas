"""Provider-neutral dataset declarations for SharedSignals.

The registry describes immutable dataset, ingest-adapter, and read-model
contracts only. Runtime collection state remains authoritative in SQLite ingest
receipts and is deliberately rejected from this YAML authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


DATASET_REGISTRY_PATH = (
    Path(__file__).resolve().parent / "config" / "dataset_registry.yaml"
)

_ROOT_KEYS = frozenset({"version", "datasets"})
_DATASET_KEYS = frozenset(
    {
        "dataset_id",
        "aliases",
        "domain",
        "market",
        "entity_type",
        "data_classification",
        "schema_version",
        "fields",
        "primary_key",
        "default_projection",
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
    }
)
_READ_MODEL_ADAPTER_KEYS = frozenset(
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


@dataclass(frozen=True)
class DatasetField:
    name: str
    logical_type: str
    nullable: bool
    selectable: bool
    filterable: bool
    sortable: bool


@dataclass(frozen=True)
class FixedFieldFilter:
    field: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class ReadModelAdapter:
    adapter_version: str
    primary_table: str
    fixed_field_filters: tuple[FixedFieldFilter, ...]


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
    cadence_class: str
    timezone: str
    freshness_sla_seconds: int
    max_page_size: int
    max_lookback_days: int | None
    point_in_time: str
    backfill_policy: str
    empty_data_policy: str
    required_scope: str
    quota_class: str
    provider_bindings: tuple[ProviderBinding, ...]
    read_model_adapter: ReadModelAdapter


class DatasetRegistry:
    """Immutable indexes over validated dataset definitions."""

    def __init__(self, datasets: tuple[DatasetDefinition, ...]) -> None:
        by_id: dict[str, DatasetDefinition] = {}
        by_name: dict[str, DatasetDefinition] = {}
        provider_api_owners: dict[tuple[str, str], str] = {}

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

        self._datasets = datasets
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
    value: Mapping[str, Any], allowed: frozenset[str], path: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown key(s) in {path}: {', '.join(unknown)}")
    missing = sorted(allowed - set(value))
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


def _choice(value: Any, allowed: frozenset[str], path: str) -> str:
    normalized = _non_empty_string(value, path)
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{path} must be one of: {choices}")
    return normalized


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
    _reject_unknown_keys(value, _BINDING_KEYS, path)

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
    )


def _load_read_model_adapter(
    raw: Any,
    *,
    dataset_id: str,
    fields_by_name: Mapping[str, DatasetField],
) -> ReadModelAdapter:
    path = f"dataset {dataset_id}.read_model_adapter"
    value = _mapping(raw, path)
    _reject_unknown_keys(value, _READ_MODEL_ADAPTER_KEYS, path)

    adapter_version = _non_empty_string(
        value["adapter_version"], f"{path}.adapter_version"
    )
    primary_table = _non_empty_string(value["primary_table"], f"{path}.primary_table")
    raw_filters = value["fixed_field_filters"]
    if not isinstance(raw_filters, list) or not raw_filters:
        raise ValueError(f"{path}.fixed_field_filters must be a non-empty list")

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
    )


def _load_dataset(raw: Any, index: int) -> DatasetDefinition:
    path = f"datasets[{index}]"
    value = _mapping(raw, path)
    _reject_unknown_keys(value, _DATASET_KEYS, path)

    dataset_id = _non_empty_string(value["dataset_id"], f"{path}.dataset_id")
    raw_fields = value["fields"]
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError(f"dataset {dataset_id}.fields must be a non-empty list")
    fields = tuple(
        _load_field(field, dataset_id=dataset_id, index=field_index)
        for field_index, field in enumerate(raw_fields)
    )
    fields_by_name: dict[str, DatasetField] = {}
    for field in fields:
        if field.name in fields_by_name:
            raise ValueError(
                f"dataset {dataset_id}.fields contains duplicate field: {field.name}"
            )
        fields_by_name[field.name] = field

    primary_key = _string_tuple(
        value["primary_key"], f"dataset {dataset_id}.primary_key"
    )
    _reject_duplicate_strings(primary_key, f"dataset {dataset_id}.primary_key")
    missing_primary_fields = sorted(set(primary_key) - set(fields_by_name))
    if missing_primary_fields:
        raise ValueError(
            f"dataset {dataset_id}.primary_key fields are not declared in fields: "
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
            f"dataset {dataset_id}.primary_key fields must be selectable and sortable: "
            f"{', '.join(invalid_primary_fields)}"
        )

    default_projection = _string_tuple(
        value["default_projection"], f"dataset {dataset_id}.default_projection"
    )
    _reject_duplicate_strings(
        default_projection, f"dataset {dataset_id}.default_projection"
    )
    for field_name in default_projection:
        field = fields_by_name.get(field_name)
        if field is None:
            raise ValueError(
                f"dataset {dataset_id}.default_projection references unknown field: "
                f"{field_name}"
            )
        if not field.selectable:
            raise ValueError(
                f"dataset {dataset_id}.default_projection field is not selectable: "
                f"{field_name}"
            )

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
    provider_filters = tuple(
        fixed_filter
        for fixed_filter in read_model_adapter.fixed_field_filters
        if fixed_filter.field == "provider"
    )
    if len(provider_filters) != 1 or set(provider_filters[0].allowed_values) != set(
        read_discriminator_values
    ):
        raise ValueError(
            f"dataset {dataset_id} provider binding read_discriminator_value values "
            "must exactly equal read_model_adapter provider allowed_values"
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
        schema_version=_non_empty_string(
            value["schema_version"], f"dataset {dataset_id}.schema_version"
        ),
        fields=fields,
        primary_key=primary_key,
        default_projection=default_projection,
        cadence_class=_non_empty_string(
            value["cadence_class"], f"dataset {dataset_id}.cadence_class"
        ),
        timezone=_non_empty_string(value["timezone"], f"dataset {dataset_id}.timezone"),
        freshness_sla_seconds=_positive_int(
            value["freshness_sla_seconds"],
            f"dataset {dataset_id}.freshness_sla_seconds",
        ),
        max_page_size=_positive_int(
            value["max_page_size"], f"dataset {dataset_id}.max_page_size"
        ),
        max_lookback_days=_optional_positive_int(
            value["max_lookback_days"], f"dataset {dataset_id}.max_lookback_days"
        ),
        point_in_time=_choice(
            value["point_in_time"],
            _POINT_IN_TIME_MODES,
            f"dataset {dataset_id}.point_in_time",
        ),
        backfill_policy=_choice(
            value["backfill_policy"],
            _BACKFILL_POLICIES,
            f"dataset {dataset_id}.backfill_policy",
        ),
        empty_data_policy=_choice(
            value["empty_data_policy"],
            _EMPTY_DATA_POLICIES,
            f"dataset {dataset_id}.empty_data_policy",
        ),
        required_scope=_non_empty_string(
            value["required_scope"], f"dataset {dataset_id}.required_scope"
        ),
        quota_class=_non_empty_string(
            value["quota_class"], f"dataset {dataset_id}.quota_class"
        ),
        provider_bindings=provider_bindings,
        read_model_adapter=read_model_adapter,
    )


def load_dataset_registry(
    path: Path = DATASET_REGISTRY_PATH,
) -> DatasetRegistry:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    root = _mapping(raw, "registry")
    _reject_unknown_keys(root, _ROOT_KEYS, "registry")

    version = root["version"]
    if isinstance(version, bool) or version != 1:
        raise ValueError("registry.version must be integer 1")
    raw_datasets = root["datasets"]
    if not isinstance(raw_datasets, list) or not raw_datasets:
        raise ValueError("registry.datasets must be a non-empty list")

    return DatasetRegistry(
        tuple(
            _load_dataset(dataset, index) for index, dataset in enumerate(raw_datasets)
        )
    )
