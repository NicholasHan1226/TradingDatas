from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from dataset_registry import (
    DATASET_REGISTRY_PATH,
    DatasetDefinition,
    ProviderBinding,
    load_dataset_registry,
)
from storage.schema_contract import get_table


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "provider": "tushare",
        "api_name": "example",
        "adapter_version": "sqlite-read-model.v1",
        "entitlement_state": "unknown",
        "activation_state": "active",
        "target_tables": ["market_factors"],
        "primary_read_model_table": "market_factors",
    }
    binding.update(overrides)
    return binding


def _dataset(
    dataset_id: str = "cn.example.dataset",
    *,
    aliases: list[str] | None = None,
    **overrides: object,
) -> dict[str, object]:
    dataset: dict[str, object] = {
        "dataset_id": dataset_id,
        "aliases": aliases if aliases is not None else ["tushare.example"],
        "domain": "reference",
        "market": "CN",
        "entity_type": "example",
        "schema_version": "1.0.0",
        "fields": [
            "factor_hash",
            "market",
            "symbol",
            "factor_name",
            "event_time",
            "value",
            "provider",
            "source_file",
            "collected_at",
            "raw_json",
        ],
        "primary_key": ["factor_hash"],
        "cadence_class": "preopen",
        "timezone": "Asia/Shanghai",
        "freshness_sla_seconds": 259_200,
        "max_page_size": 500,
        "max_lookback_days": None,
        "point_in_time": "current_snapshot",
        "required_scope": "market_data",
        "quota_class": "beta_standard",
        "provider_bindings": [_binding()],
    }
    dataset.update(overrides)
    return dataset


def _write_registry(
    tmp_path: Path,
    datasets: list[dict[str, object]],
    **root_overrides: object,
) -> Path:
    payload: dict[str, object] = {"version": 1, "datasets": datasets}
    payload.update(root_overrides)
    path = tmp_path / "dataset_registry.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_repository_registry_resolves_provider_neutral_daily_dataset() -> None:
    registry = load_dataset_registry()

    daily = registry.resolve("cn.equity.daily")

    assert DATASET_REGISTRY_PATH.name == "dataset_registry.yaml"
    assert isinstance(daily, DatasetDefinition)
    assert registry.resolve("tushare.daily") is daily
    assert daily.dataset_id == "cn.equity.daily"
    assert daily.max_page_size == 500
    assert daily.max_lookback_days is None
    assert daily.provider_bindings == (
        ProviderBinding(
            provider="tushare",
            api_name="daily",
            adapter_version="sqlite-read-model.v1",
            entitlement_state="unknown",
            activation_state="active",
            target_tables=("market_bars_daily",),
            primary_read_model_table="market_bars_daily",
        ),
    )


def test_repository_entries_match_existing_read_model_tables_and_keys() -> None:
    registry = load_dataset_registry()
    expected_tables = {
        "cn.equity.daily": "market_bars_daily",
        "cn.market.trade_calendar": "market_factors",
        "cn.event.major_news": "market_events",
    }

    for dataset_id, table_name in expected_tables.items():
        dataset = registry.resolve(dataset_id)
        table = get_table(table_name)
        binding = dataset.provider_bindings[0]

        assert dataset.fields == tuple(column.name for column in table.columns)
        assert dataset.primary_key == table.primary_key
        assert binding.target_tables == (table_name,)
        assert binding.primary_read_model_table == table_name


def test_registry_compatibility_and_active_cadence_views() -> None:
    registry = load_dataset_registry()

    assert registry.compatibility_api_names("tushare") == frozenset(
        {"daily", "trade_cal", "major_news"}
    )
    assert registry.compatibility_table_map("tushare") == {
        "daily": "market_bars_daily",
        "trade_cal": "market_factors",
        "major_news": "market_events",
    }
    assert tuple(
        dataset.dataset_id for dataset in registry.active_for_cadence("event_30m")
    ) == ("cn.event.major_news",)
    assert (
        registry.provider_binding("cn.market.trade_calendar", "tushare").api_name
        == "trade_cal"
    )


def test_loaded_definitions_are_immutable_and_sequences_are_tuples() -> None:
    daily = load_dataset_registry().resolve("cn.equity.daily")

    assert isinstance(daily.aliases, tuple)
    assert isinstance(daily.fields, tuple)
    assert isinstance(daily.primary_key, tuple)
    assert isinstance(daily.provider_bindings, tuple)
    assert isinstance(daily.provider_bindings[0].target_tables, tuple)
    with pytest.raises(FrozenInstanceError):
        setattr(daily, "domain", "mutated")
    with pytest.raises(FrozenInstanceError):
        setattr(daily.provider_bindings[0], "provider", "mutated")


def test_loader_rejects_duplicate_dataset_ids(tmp_path: Path) -> None:
    first = _dataset()
    second = deepcopy(first)

    with pytest.raises(ValueError, match="duplicate dataset_id"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_rejects_duplicate_aliases_within_one_dataset(tmp_path: Path) -> None:
    dataset = _dataset(aliases=["tushare.example", "tushare.example"])

    with pytest.raises(ValueError, match="duplicate alias"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


def test_loader_rejects_alias_shared_by_different_datasets(tmp_path: Path) -> None:
    first = _dataset("cn.example.one", aliases=["tushare.shared"])
    second = _dataset("cn.example.two", aliases=["tushare.shared"])
    second["provider_bindings"] = [_binding(api_name="example_two")]

    with pytest.raises(ValueError, match="resolves to multiple datasets"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_rejects_alias_that_collides_with_another_dataset_id(
    tmp_path: Path,
) -> None:
    first = _dataset("cn.example.one", aliases=["cn.example.two"])
    second = _dataset("cn.example.two", aliases=["tushare.example_two"])
    second["provider_bindings"] = [_binding(api_name="example_two")]

    with pytest.raises(ValueError, match="resolves to multiple datasets"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_rejects_missing_primary_key(tmp_path: Path) -> None:
    dataset = _dataset(primary_key=[])

    with pytest.raises(ValueError, match="primary_key"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_freshness_sla(
    tmp_path: Path,
    value: int,
) -> None:
    dataset = _dataset(freshness_sla_seconds=value)

    with pytest.raises(ValueError, match="freshness_sla_seconds"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_max_page_size(
    tmp_path: Path,
    value: int,
) -> None:
    dataset = _dataset(max_page_size=value)

    with pytest.raises(ValueError, match="max_page_size"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_configured_lookback(
    tmp_path: Path,
    value: int,
) -> None:
    dataset = _dataset(max_lookback_days=value)

    with pytest.raises(ValueError, match="max_lookback_days"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    ("binding_override", "error"),
    [
        ({"adapter_version": ""}, "adapter_version"),
        ({"target_tables": []}, "target_tables"),
        ({"primary_read_model_table": None}, "primary_read_model_table"),
    ],
)
def test_loader_rejects_active_binding_without_adapter_or_table(
    tmp_path: Path,
    binding_override: dict[str, object],
    error: str,
) -> None:
    dataset = _dataset(provider_bindings=[_binding(**binding_override)])

    with pytest.raises(ValueError, match=error):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("entitlement_state", ["excluded", "retired"])
def test_loader_rejects_excluded_or_retired_binding_marked_active(
    tmp_path: Path,
    entitlement_state: str,
) -> None:
    dataset = _dataset(
        provider_bindings=[_binding(entitlement_state=entitlement_state)]
    )

    with pytest.raises(ValueError, match="cannot be active"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    ("level", "unknown_key"),
    [
        ("root", "mystery_root"),
        ("dataset", "runtime_state"),
        ("binding", "mystery_binding"),
    ],
)
def test_loader_rejects_unknown_keys_at_every_level(
    tmp_path: Path,
    level: str,
    unknown_key: str,
) -> None:
    dataset = _dataset()
    root_overrides: dict[str, object] = {}
    if level == "root":
        root_overrides[unknown_key] = True
    elif level == "dataset":
        dataset[unknown_key] = "must not be accepted"
    else:
        bindings = dataset["provider_bindings"]
        assert isinstance(bindings, list)
        bindings[0][unknown_key] = True

    with pytest.raises(ValueError, match=unknown_key):
        load_dataset_registry(_write_registry(tmp_path, [dataset], **root_overrides))


def test_loader_uses_yaml_safe_load(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        "version: 1\ndatasets: !!python/object/apply:builtins.list [[]]\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.constructor.ConstructorError):
        load_dataset_registry(path)
