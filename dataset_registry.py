"""Provider-neutral dataset declarations for SharedSignals.

The registry describes static dataset and provider-binding contracts only.
Runtime collection state remains authoritative in ingest receipts and is not
loaded from this YAML file.
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
        "schema_version",
        "fields",
        "primary_key",
        "cadence_class",
        "timezone",
        "freshness_sla_seconds",
        "max_page_size",
        "max_lookback_days",
        "point_in_time",
        "required_scope",
        "quota_class",
        "provider_bindings",
    }
)
_BINDING_KEYS = frozenset(
    {
        "provider",
        "api_name",
        "adapter_version",
        "entitlement_state",
        "activation_state",
        "target_tables",
        "primary_read_model_table",
    }
)
_ENTITLEMENT_STATES = frozenset({"active", "locked", "unknown", "excluded", "retired"})
_ACTIVATION_STATES = frozenset({"active", "paused"})
_POINT_IN_TIME_MODES = frozenset({"append_only", "current_snapshot", "unsupported"})


@dataclass(frozen=True)
class ProviderBinding:
    provider: str
    api_name: str
    adapter_version: str
    entitlement_state: str
    activation_state: str
    target_tables: tuple[str, ...]
    primary_read_model_table: str | None


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    aliases: tuple[str, ...]
    domain: str
    market: str
    entity_type: str
    schema_version: str
    fields: tuple[str, ...]
    primary_key: tuple[str, ...]
    cadence_class: str
    timezone: str
    freshness_sla_seconds: int
    max_page_size: int
    max_lookback_days: int | None
    point_in_time: str
    required_scope: str
    quota_class: str
    provider_bindings: tuple[ProviderBinding, ...]


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
            binding.api_name: binding.primary_read_model_table
            for dataset in self._datasets
            for binding in dataset.provider_bindings
            if binding.provider == provider
            and binding.primary_read_model_table is not None
        }

    def active_for_cadence(self, cadence_class: str) -> tuple[DatasetDefinition, ...]:
        return tuple(
            dataset
            for dataset in self._datasets
            if dataset.cadence_class == cadence_class
            and any(
                binding.activation_state == "active"
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


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value.strip()


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
    adapter_version = _string(value["adapter_version"], f"{path}.adapter_version")
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
    target_tables = _string_tuple(
        value["target_tables"],
        f"{path}.target_tables",
        allow_empty=True,
    )
    primary_table_raw = value["primary_read_model_table"]
    primary_table = (
        None
        if primary_table_raw is None
        else _non_empty_string(primary_table_raw, f"{path}.primary_read_model_table")
    )

    if activation_state == "active":
        if entitlement_state in {"excluded", "retired"}:
            raise ValueError(
                f"{path} with entitlement_state={entitlement_state} cannot be active"
            )
        if not adapter_version:
            raise ValueError(
                f"{path}.adapter_version is required for an active binding"
            )
        if not target_tables:
            raise ValueError(f"{path}.target_tables is required for an active binding")
        if primary_table is None:
            raise ValueError(
                f"{path}.primary_read_model_table is required for an active binding"
            )
    if primary_table is not None and primary_table not in target_tables:
        raise ValueError(
            f"{path}.primary_read_model_table must be listed in target_tables"
        )

    return ProviderBinding(
        provider=provider,
        api_name=api_name,
        adapter_version=adapter_version,
        entitlement_state=entitlement_state,
        activation_state=activation_state,
        target_tables=target_tables,
        primary_read_model_table=primary_table,
    )


def _load_dataset(raw: Any, index: int) -> DatasetDefinition:
    path = f"datasets[{index}]"
    value = _mapping(raw, path)
    _reject_unknown_keys(value, _DATASET_KEYS, path)

    dataset_id = _non_empty_string(value["dataset_id"], f"{path}.dataset_id")
    fields = _string_tuple(value["fields"], f"dataset {dataset_id}.fields")
    primary_key = _string_tuple(
        value["primary_key"], f"dataset {dataset_id}.primary_key"
    )
    missing_primary_fields = sorted(set(primary_key) - set(fields))
    if missing_primary_fields:
        raise ValueError(
            f"dataset {dataset_id}.primary_key fields are not declared in fields: "
            f"{', '.join(missing_primary_fields)}"
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

    return DatasetDefinition(
        dataset_id=dataset_id,
        aliases=_string_tuple(value["aliases"], f"dataset {dataset_id}.aliases"),
        domain=_non_empty_string(value["domain"], f"dataset {dataset_id}.domain"),
        market=_non_empty_string(value["market"], f"dataset {dataset_id}.market"),
        entity_type=_non_empty_string(
            value["entity_type"], f"dataset {dataset_id}.entity_type"
        ),
        schema_version=_non_empty_string(
            value["schema_version"], f"dataset {dataset_id}.schema_version"
        ),
        fields=fields,
        primary_key=primary_key,
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
            value["max_lookback_days"],
            f"dataset {dataset_id}.max_lookback_days",
        ),
        point_in_time=_choice(
            value["point_in_time"],
            _POINT_IN_TIME_MODES,
            f"dataset {dataset_id}.point_in_time",
        ),
        required_scope=_non_empty_string(
            value["required_scope"], f"dataset {dataset_id}.required_scope"
        ),
        quota_class=_non_empty_string(
            value["quota_class"], f"dataset {dataset_id}.quota_class"
        ),
        provider_bindings=provider_bindings,
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
