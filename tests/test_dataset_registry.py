from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

import dataset_registry as registry_module
from dataset_registry import (
    DATASET_REGISTRY_PATH,
    DatasetDefinition,
    ProviderBinding,
    load_dataset_registry,
)
from storage.schema_contract import get_table


FROZEN_TUSHARE_API_TO_TABLE_MAP = {
    "adj_factor": "market_bars_daily",
    "anns_d": "market_events",
    "bak_basic": "market_factors",
    "balancesheet": "market_factors",
    "block_trade": "market_events",
    "broker_recommend": "market_events",
    "cashflow": "market_factors",
    "cb_basic": "market_assets",
    "cb_daily": "market_bars_daily",
    "cb_issue": "market_events",
    "cctv_news": "market_events",
    "cn_cpi": "market_factors",
    "cn_gdp": "market_factors",
    "cn_m": "market_factors",
    "cn_pmi": "market_factors",
    "cn_ppi": "market_factors",
    "concept": "market_assets",
    "concept_detail": "market_relationships",
    "cyq_chips": "market_factors",
    "cyq_perf": "market_factors",
    "daily": "market_bars_daily",
    "daily_basic": "market_factors",
    "dc_daily": "market_bars_daily",
    "dc_index": "market_assets",
    "dc_member": "market_relationships",
    "dividend": "market_factors",
    "etf_basic": "market_assets",
    "express": "market_factors",
    "fina_audit": "market_factors",
    "fina_indicator": "market_factors",
    "fina_mainbz": "market_factors",
    "forecast": "market_factors",
    "ft_limit": "market_factors",
    "fund_adj": "market_factors",
    "fund_basic": "market_assets",
    "fund_daily": "market_bars_daily",
    "fund_div": "market_factors",
    "fund_nav": "market_factors",
    "fund_portfolio": "market_fund_portfolio",
    "fund_share": "market_factors",
    "fut_basic": "market_assets",
    "fut_daily": "market_bars_daily",
    "fut_holding": "market_factors",
    "fx_daily": "market_bars_daily",
    "hibor": "market_factors",
    "hk_balancesheet": "market_factors",
    "hk_basic": "market_assets",
    "hk_cashflow": "market_factors",
    "hk_daily": "market_bars_daily",
    "hk_income": "market_factors",
    "hs_const": "market_relationships",
    "income": "market_factors",
    "index_basic": "market_assets",
    "index_classify": "market_assets",
    "index_daily": "market_bars_daily",
    "index_dailybasic": "market_factors",
    "index_global": "market_bars_daily",
    "index_member": "market_relationships",
    "index_member_all": "market_relationships",
    "index_monthly": "market_bars_intraday",
    "index_weekly": "market_bars_intraday",
    "index_weight": "market_relationships",
    "libor": "market_factors",
    "limit_list": "market_events",
    "limit_list_d": "market_events",
    "limit_step": "market_factors",
    "major_news": "market_events",
    "margin": "market_factors",
    "margin_detail": "market_factors",
    "margin_secs": "market_factors",
    "moneyflow": "market_factors",
    "moneyflow_hsgt": "market_factors",
    "monthly": "market_bars_intraday",
    "namechange": "market_events",
    "news": "market_events",
    "opt_basic": "market_assets",
    "opt_daily": "market_bars_daily",
    "pledge_detail": "market_factors",
    "pledge_stat": "market_factors",
    "repo_daily": "market_factors",
    "report_rc": "market_events",
    "repurchase": "market_factors",
    "rt_fut_min": "market_bars_intraday",
    "rt_min": "market_bars_intraday",
    "sf_month": "market_factors",
    "share_float": "market_factors",
    "shibor": "market_factors",
    "shibor_lpr": "market_factors",
    "stk_auction": "market_factors",
    "stk_factor": "market_bars_daily",
    "stk_factor_pro": "market_factors",
    "stk_holdernumber": "market_factors",
    "stk_holdertrade": "market_factors",
    "stk_limit": "market_factors",
    "stk_managers": "market_factors",
    "stk_surv": "market_factors",
    "stock_basic": "market_assets",
    "stock_company": "market_factors",
    "suspend_d": "market_events",
    "ths_daily": "market_bars_daily",
    "ths_hot": "market_factors",
    "ths_index": "market_assets",
    "ths_member": "market_relationships",
    "top10_floatholders": "market_factors",
    "top10_holders": "market_factors",
    "top_inst": "market_factors",
    "top_list": "market_factors",
    "trade_cal": "market_factors",
    "us_basic": "market_assets",
    "us_daily": "market_bars_daily",
    "us_tbr": "market_factors",
    "us_tltr": "market_factors",
    "us_tycr": "market_factors",
    "weekly": "market_bars_intraday",
}

FROZEN_TUSHARE_MULTI_TARGET_TABLES = {
    "repo_daily": ("market_factors", "market_bars_daily"),
    "stk_factor": ("market_bars_daily", "market_factors"),
}

EXCLUDED_TUSHARE_APIS = frozenset(
    {
        "fx_daily",
        "hibor",
        "hk_balancesheet",
        "hk_basic",
        "hk_cashflow",
        "hk_daily",
        "hk_income",
        "hs_const",
        "index_global",
        "libor",
        "moneyflow_hsgt",
        "us_basic",
        "us_daily",
        "us_tbr",
        "us_tltr",
        "us_tycr",
    }
)

P2_FINANCIAL_APIS = frozenset(
    {
        "balancesheet",
        "cashflow",
        "dividend",
        "express",
        "fina_audit",
        "fina_indicator",
        "fina_mainbz",
        "forecast",
        "income",
        "stk_holdertrade",
        "top10_floatholders",
        "top10_holders",
        "top_inst",
    }
)

PROFILE_CONTRACT_KEYS = frozenset(
    {
        "fields",
        "primary_key",
        "default_projection",
        "max_page_size",
        "max_lookback_days",
        "point_in_time",
        "backfill_policy",
        "empty_data_policy",
        "required_scope",
        "quota_class",
    }
)


def _field(
    name: str,
    logical_type: str = "text",
    *,
    nullable: bool = True,
    selectable: bool = True,
    filterable: bool = False,
    sortable: bool = False,
    **overrides: object,
) -> dict[str, object]:
    field: dict[str, object] = {
        "name": name,
        "logical_type": logical_type,
        "nullable": nullable,
        "selectable": selectable,
        "filterable": filterable,
        "sortable": sortable,
    }
    field.update(overrides)
    return field


def _factor_fields() -> list[dict[str, object]]:
    return [
        _field("factor_hash", nullable=True, filterable=True, sortable=True),
        _field("market", filterable=True),
        _field("symbol", filterable=True),
        _field("factor_name", filterable=True),
        _field("event_time", filterable=True, sortable=True),
        _field("value", "float"),
        _field("provider"),
        _field("source_file", selectable=False),
        _field("collected_at", sortable=True),
        _field("raw_json", selectable=False),
    ]


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "provider": "tushare",
        "api_name": "example",
        "adapter_version": "tushare-direct-sqlite.v1",
        "read_discriminator_value": "tushare_example",
        "entitlement_state": "active",
        "activation_state": "active",
        "target_tables": ["market_factors"],
    }
    binding.update(overrides)
    return binding


def _read_model_adapter(**overrides: object) -> dict[str, object]:
    adapter: dict[str, object] = {
        "adapter_version": "sqlite-read-model.v1",
        "primary_table": "market_factors",
        "fixed_field_filters": [
            {"field": "provider", "allowed_values": ["tushare_example"]}
        ],
    }
    adapter.update(overrides)
    return adapter


def _dataset(
    dataset_id: str = "cn.example.dataset",
    *,
    aliases: list[str] | None = None,
    **overrides: object,
) -> dict[str, object]:
    fields = _factor_fields()
    dataset: dict[str, object] = {
        "dataset_id": dataset_id,
        "aliases": aliases if aliases is not None else ["tushare.example"],
        "domain": "reference",
        "market": "CN",
        "entity_type": "example",
        "data_classification": "objective_factual",
        "schema_version": "1.0.0",
        "fields": fields,
        "primary_key": ["factor_hash"],
        "default_projection": [
            field["name"] for field in fields if field["selectable"]
        ],
        "cadence_class": "preopen",
        "timezone": "Asia/Shanghai",
        "freshness_sla_seconds": 259_200,
        "max_page_size": 500,
        "max_lookback_days": None,
        "point_in_time": "current_snapshot",
        "backfill_policy": "provider_limited",
        "empty_data_policy": "allowed",
        "required_scope": "market_data",
        "quota_class": "beta_standard",
        "provider_bindings": [_binding()],
        "read_model_adapter": _read_model_adapter(),
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


def _factor_schema_profile(**overrides: object) -> dict[str, object]:
    fields = _factor_fields()
    profile: dict[str, object] = {
        "schema_version": "1.0.0",
        "fields": fields,
        "primary_key": ["factor_hash"],
        "default_projection": [
            field["name"] for field in fields if field["selectable"]
        ],
        "max_page_size": 500,
        "max_lookback_days": None,
        "point_in_time": "current_snapshot",
        "backfill_policy": "provider_limited",
        "empty_data_policy": "allowed",
        "required_scope": "market_data",
        "quota_class": "beta_standard",
    }
    profile.update(overrides)
    return profile


def _profiled_dataset(**overrides: object) -> dict[str, object]:
    dataset = _dataset(schema_profile="factor.v1")
    for key in PROFILE_CONTRACT_KEYS:
        dataset.pop(key)
    dataset.update(overrides)
    return dataset


def test_registry_import_matches_frozen_legacy_compatibility_surface() -> None:
    from api_server import ALLOWED_TUSHARE_APIS
    from dataset_registry import (
        TUSHARE_ALLOWED_API_NAMES,
        TUSHARE_API_TO_TABLE_MAP,
    )
    from storage.read_model_store import API_TO_TABLE_MAP

    registry = load_dataset_registry()
    expected_names = frozenset(FROZEN_TUSHARE_API_TO_TABLE_MAP)
    capability_plan = yaml.safe_load(
        Path("config/tushare_capability_plan.yaml").read_text(encoding="utf-8")
    )
    planned_names = {
        item["api_name"]
        for module in capability_plan["modules"]
        for item in module["apis"]
    }
    collector_config = yaml.safe_load(
        Path("collectors/tushare/config.yaml").read_text(encoding="utf-8")
    )
    configured_names = {
        item["api_name"]
        for items in collector_config["priorities"].values()
        for item in items
    }

    assert len(FROZEN_TUSHARE_API_TO_TABLE_MAP) == 114
    assert registry.compatibility_table_map("tushare") == (
        FROZEN_TUSHARE_API_TO_TABLE_MAP
    )
    assert registry.compatibility_api_names("tushare") == expected_names
    assert TUSHARE_API_TO_TABLE_MAP == FROZEN_TUSHARE_API_TO_TABLE_MAP
    assert TUSHARE_ALLOWED_API_NAMES == expected_names
    assert API_TO_TABLE_MAP is TUSHARE_API_TO_TABLE_MAP
    assert ALLOWED_TUSHARE_APIS is TUSHARE_ALLOWED_API_NAMES
    assert planned_names == expected_names
    assert configured_names | {"rt_fut_min"} == expected_names
    with pytest.raises(TypeError):
        TUSHARE_API_TO_TABLE_MAP["mutated"] = "market_factors"  # type: ignore[index]


def test_registry_exposes_datasets_as_an_immutable_declaration_order_tuple() -> None:
    registry = load_dataset_registry()

    datasets = registry.datasets

    assert isinstance(datasets, tuple)
    assert len(datasets) == 114
    assert datasets[0] is registry.resolve(datasets[0].dataset_id)
    assert tuple(dataset.dataset_id for dataset in datasets) == tuple(
        dataset["dataset_id"]
        for dataset in yaml.safe_load(
            DATASET_REGISTRY_PATH.read_text(encoding="utf-8")
        )["datasets"]
    )
    with pytest.raises(TypeError):
        datasets[0] = datasets[-1]  # type: ignore[index]


def test_imported_registry_entries_are_complete_paused_and_truthfully_excluded() -> (
    None
):
    registry = load_dataset_registry()

    for api_name, table_name in FROZEN_TUSHARE_API_TO_TABLE_MAP.items():
        dataset = registry.resolve(f"tushare.{api_name}")
        binding = registry.provider_binding(dataset.dataset_id, "tushare")

        assert dataset.dataset_id.startswith(("cn.", "hk.", "us.", "global."))
        assert "tushare" not in dataset.dataset_id
        assert dataset.aliases == (f"tushare.{api_name}",)
        assert dataset.data_classification == "objective_factual"
        assert dataset.schema_version
        assert dataset.fields
        assert dataset.primary_key
        assert dataset.default_projection
        assert dataset.cadence_class
        assert dataset.timezone
        assert dataset.freshness_sla_seconds > 0
        assert dataset.max_page_size > 0
        assert dataset.required_scope
        assert dataset.quota_class
        assert dataset.read_model_adapter.primary_table == table_name
        assert binding.api_name == api_name
        assert binding.adapter_version
        assert binding.target_tables == FROZEN_TUSHARE_MULTI_TARGET_TABLES.get(
            api_name,
            (table_name,),
        )
        assert binding.read_discriminator_value == f"tushare_{api_name}"
        assert binding.activation_state == "paused"
        assert binding.entitlement_state == (
            "excluded" if api_name in EXCLUDED_TUSHARE_APIS else "unknown"
        )

    for api_name in P2_FINANCIAL_APIS:
        binding = registry.provider_binding(
            registry.resolve(f"tushare.{api_name}").dataset_id,
            "tushare",
        )
        assert (binding.entitlement_state, binding.activation_state) == (
            "unknown",
            "paused",
        )

    assert registry.active_for_cadence("postclose_daily") == ()
    assert registry.resolve("tushare.rt_fut_min").cadence_class == (
        "futures_session_5min"
    )


def test_independent_futures_provider_has_its_own_read_discriminator() -> None:
    registry = load_dataset_registry()
    dataset = registry.resolve("tushare.rt_fut_min")

    assert registry.provider_binding(dataset.dataset_id, "sina") == ProviderBinding(
        provider="sina",
        api_name="futures_minute",
        adapter_version="sina-direct-sqlite.v1",
        read_discriminator_value="sina_futures_minute",
        entitlement_state="unknown",
        activation_state="paused",
        target_tables=("market_bars_intraday",),
    )
    assert dataset.read_model_adapter.fixed_field_filters == (
        registry_module.FixedFieldFilter(
            field="provider",
            allowed_values=("tushare_rt_fut_min", "sina_futures_minute"),
        ),
    )


def test_schema_profile_materializes_a_complete_immutable_dataset_contract(
    tmp_path: Path,
) -> None:
    registry = load_dataset_registry(
        _write_registry(
            tmp_path,
            [_profiled_dataset()],
            schema_profiles={"factor.v1": _factor_schema_profile()},
        )
    )
    dataset = registry.resolve("cn.example.dataset")

    assert dataset.schema_version == "1.0.0"
    assert dataset.fields == tuple(
        registry_module.DatasetField(**field) for field in _factor_fields()
    )
    assert dataset.primary_key == ("factor_hash",)
    assert dataset.max_page_size == 500
    assert dataset.point_in_time == "current_snapshot"
    with pytest.raises(FrozenInstanceError):
        setattr(dataset.fields[0], "selectable", False)


def test_loader_rejects_unknown_schema_profile(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown schema_profile"):
        load_dataset_registry(
            _write_registry(
                tmp_path,
                [_profiled_dataset(schema_profile="missing.v1")],
                schema_profiles={"factor.v1": _factor_schema_profile()},
            )
        )


def test_loader_rejects_schema_profile_version_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema_version.*schema_profile"):
        load_dataset_registry(
            _write_registry(
                tmp_path,
                [_profiled_dataset(schema_version="2.0.0")],
                schema_profiles={"factor.v1": _factor_schema_profile()},
            )
        )


def test_loader_rejects_inline_profile_contract_override(tmp_path: Path) -> None:
    dataset = _profiled_dataset(fields=_factor_fields())

    with pytest.raises(ValueError, match="schema_profile.*inline"):
        load_dataset_registry(
            _write_registry(
                tmp_path,
                [dataset],
                schema_profiles={"factor.v1": _factor_schema_profile()},
            )
        )


def test_repository_registry_exposes_complete_daily_contract() -> None:
    registry = load_dataset_registry()
    daily = registry.resolve("cn.equity.daily")

    assert DATASET_REGISTRY_PATH.name == "dataset_registry.yaml"
    assert isinstance(daily, DatasetDefinition)
    assert registry.resolve("tushare.daily") is daily
    assert daily.dataset_id == "cn.equity.daily"
    assert daily.max_page_size == 500
    assert daily.max_lookback_days is None
    assert daily.data_classification == "objective_factual"
    assert daily.backfill_policy == "provider_limited"
    assert daily.empty_data_policy == "allowed"
    assert daily.default_projection == (
        "market",
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "provider",
        "collected_at",
    )
    assert daily.fields[0] == registry_module.DatasetField(
        name="market",
        logical_type="text",
        nullable=False,
        selectable=True,
        filterable=True,
        sortable=True,
    )
    assert daily.provider_bindings == (
        ProviderBinding(
            provider="tushare",
            api_name="daily",
            adapter_version="tushare-direct-sqlite.v1",
            read_discriminator_value="tushare_daily",
            entitlement_state="unknown",
            activation_state="paused",
            target_tables=("market_bars_daily",),
        ),
    )
    assert daily.read_model_adapter == registry_module.ReadModelAdapter(
        adapter_version="sqlite-read-model.v1",
        primary_table="market_bars_daily",
        fixed_field_filters=(
            registry_module.FixedFieldFilter(
                field="provider", allowed_values=("tushare_daily",)
            ),
        ),
    )


def test_repository_entries_match_schema_types_nullable_and_discriminators() -> None:
    registry = load_dataset_registry()
    expected = {
        "cn.equity.daily": ("daily", "market_bars_daily"),
        "cn.market.trade_calendar": ("trade_cal", "market_factors"),
        "cn.event.major_news": ("major_news", "market_events"),
    }

    for dataset_id, (api_name, table_name) in expected.items():
        dataset = registry.resolve(dataset_id)
        table = get_table(table_name)
        binding = dataset.provider_bindings[0]
        fields = {field.name: field for field in dataset.fields}

        assert tuple(
            (field.name, field.logical_type, field.nullable) for field in dataset.fields
        ) == tuple(
            (column.name, column.logical_type, column.nullable)
            for column in table.columns
        )
        assert dataset.primary_key == table.primary_key
        assert set(dataset.default_projection) == {
            name for name, field in fields.items() if field.selectable
        }
        for internal_field in ("raw_json", "source_file"):
            assert (
                fields[internal_field].selectable,
                fields[internal_field].filterable,
                fields[internal_field].sortable,
            ) == (False, False, False)
        assert binding.target_tables == (table_name,)
        assert binding.read_discriminator_value == f"tushare_{api_name}"
        assert binding.entitlement_state == "unknown"
        assert binding.activation_state == "paused"
        assert dataset.read_model_adapter.primary_table == table_name
        assert dataset.read_model_adapter.fixed_field_filters == (
            registry_module.FixedFieldFilter(
                field="provider", allowed_values=(f"tushare_{api_name}",)
            ),
        )


def test_registry_compatibility_uses_dataset_read_adapter_and_paused_is_inactive() -> (
    None
):
    registry = load_dataset_registry()

    assert registry.compatibility_api_names("tushare") == frozenset(
        FROZEN_TUSHARE_API_TO_TABLE_MAP
    )
    assert (
        registry.compatibility_table_map("tushare") == FROZEN_TUSHARE_API_TO_TABLE_MAP
    )
    assert registry.active_for_cadence("postclose") == ()
    assert registry.active_for_cadence("preopen") == ()
    assert registry.active_for_cadence("event_30m") == ()
    assert (
        registry.provider_binding("cn.market.trade_calendar", "tushare").api_name
        == "trade_cal"
    )


def test_active_for_cadence_requires_entitlement_and_activation_active(
    tmp_path: Path,
) -> None:
    active = _dataset()
    paused = _dataset(
        "cn.example.paused",
        aliases=["tushare.paused"],
        provider_bindings=[
            _binding(
                api_name="paused",
                read_discriminator_value="tushare_paused",
                activation_state="paused",
            )
        ],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {"field": "provider", "allowed_values": ["tushare_paused"]}
            ]
        ),
    )
    registry = load_dataset_registry(_write_registry(tmp_path, [active, paused]))

    assert tuple(
        dataset.dataset_id for dataset in registry.active_for_cadence("preopen")
    ) == ("cn.example.dataset",)


def test_loaded_contract_is_deeply_immutable() -> None:
    daily = load_dataset_registry().resolve("cn.equity.daily")

    assert isinstance(daily.fields, tuple)
    assert isinstance(daily.fields[0], registry_module.DatasetField)
    assert isinstance(daily.default_projection, tuple)
    assert isinstance(daily.provider_bindings, tuple)
    assert isinstance(daily.provider_bindings[0].target_tables, tuple)
    assert isinstance(daily.read_model_adapter, registry_module.ReadModelAdapter)
    assert isinstance(daily.read_model_adapter.fixed_field_filters, tuple)
    assert isinstance(
        daily.read_model_adapter.fixed_field_filters[0].allowed_values,
        tuple,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(daily.fields[0], "selectable", False)
    with pytest.raises(FrozenInstanceError):
        setattr(daily.read_model_adapter, "primary_table", "mutated")
    with pytest.raises(FrozenInstanceError):
        setattr(
            daily.read_model_adapter.fixed_field_filters[0],
            "allowed_values",
            ("mutated",),
        )


def test_multi_provider_compatibility_maps_each_api_to_same_read_adapter(
    tmp_path: Path,
) -> None:
    dataset = _dataset(
        provider_bindings=[
            _binding(),
            _binding(
                provider="akshare",
                api_name="stock_zh_a_hist",
                adapter_version="akshare-direct-sqlite.v1",
                read_discriminator_value="akshare_stock_zh_a_hist",
            ),
        ],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {
                    "field": "provider",
                    "allowed_values": [
                        "tushare_example",
                        "akshare_stock_zh_a_hist",
                    ],
                }
            ]
        ),
    )
    registry = load_dataset_registry(_write_registry(tmp_path, [dataset]))

    assert registry.compatibility_table_map("tushare") == {"example": "market_factors"}
    assert registry.compatibility_table_map("akshare") == {
        "stock_zh_a_hist": "market_factors"
    }
    assert registry.resolve(
        "cn.example.dataset"
    ).read_model_adapter.fixed_field_filters == (
        registry_module.FixedFieldFilter(
            field="provider",
            allowed_values=("tushare_example", "akshare_stock_zh_a_hist"),
        ),
    )


def test_loader_rejects_read_discriminator_owned_by_multiple_datasets_on_same_table(
    tmp_path: Path,
) -> None:
    first = _dataset("cn.example.one", aliases=["tushare.one"])
    second = _dataset(
        "cn.example.two",
        aliases=["akshare.two"],
        provider_bindings=[
            _binding(
                provider="akshare",
                api_name="example_two",
                adapter_version="akshare-direct-sqlite.v1",
                read_discriminator_value="tushare_example",
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="read discriminator ownership.*multiple datasets",
    ):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_allows_same_read_discriminator_on_different_tables(
    tmp_path: Path,
) -> None:
    first = _dataset("cn.example.one", aliases=["tushare.one"])
    second = _dataset(
        "cn.example.two",
        aliases=["akshare.two"],
        provider_bindings=[
            _binding(
                provider="akshare",
                api_name="example_two",
                adapter_version="akshare-direct-sqlite.v1",
                read_discriminator_value="tushare_example",
                target_tables=["market_events"],
            )
        ],
        read_model_adapter=_read_model_adapter(primary_table="market_events"),
    )

    registry = load_dataset_registry(_write_registry(tmp_path, [first, second]))

    assert registry.resolve("cn.example.one").read_model_adapter.primary_table == (
        "market_factors"
    )
    assert registry.resolve("cn.example.two").read_model_adapter.primary_table == (
        "market_events"
    )


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
    second = _dataset(
        "cn.example.two",
        aliases=["tushare.shared"],
        provider_bindings=[
            _binding(
                api_name="example_two",
                read_discriminator_value="tushare_example_two",
            )
        ],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {
                    "field": "provider",
                    "allowed_values": ["tushare_example_two"],
                }
            ]
        ),
    )

    with pytest.raises(ValueError, match="resolves to multiple datasets"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_rejects_alias_that_collides_with_another_dataset_id(
    tmp_path: Path,
) -> None:
    first = _dataset("cn.example.one", aliases=["cn.example.two"])
    second = _dataset(
        "cn.example.two",
        aliases=["tushare.example_two"],
        provider_bindings=[
            _binding(
                api_name="example_two",
                read_discriminator_value="tushare_example_two",
            )
        ],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {
                    "field": "provider",
                    "allowed_values": ["tushare_example_two"],
                }
            ]
        ),
    )

    with pytest.raises(ValueError, match="resolves to multiple datasets"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


def test_loader_rejects_duplicate_provider_within_dataset(tmp_path: Path) -> None:
    dataset = _dataset(
        provider_bindings=[
            _binding(),
            _binding(
                api_name="example_two",
                read_discriminator_value="tushare_example_two",
            ),
        ],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {
                    "field": "provider",
                    "allowed_values": [
                        "tushare_example",
                        "tushare_example_two",
                    ],
                }
            ]
        ),
    )

    with pytest.raises(ValueError, match="duplicate provider"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


def test_loader_rejects_provider_api_owned_by_multiple_datasets(
    tmp_path: Path,
) -> None:
    first = _dataset("cn.example.one", aliases=["tushare.one"])
    second = _dataset("cn.example.two", aliases=["tushare.two"])

    with pytest.raises(ValueError, match="provider api_name.*multiple datasets"):
        load_dataset_registry(_write_registry(tmp_path, [first, second]))


@pytest.mark.parametrize(
    "primary_key",
    [[], ["missing"], ["factor_hash", "factor_hash"]],
)
def test_loader_rejects_missing_or_unknown_primary_key(
    tmp_path: Path,
    primary_key: list[str],
) -> None:
    dataset = _dataset(primary_key=primary_key)

    with pytest.raises(ValueError, match="primary_key"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("capability", ["selectable", "sortable"])
def test_loader_rejects_primary_key_without_query_capability(
    tmp_path: Path,
    capability: str,
) -> None:
    fields = _factor_fields()
    next(field for field in fields if field["name"] == "factor_hash")[capability] = (
        False
    )
    dataset = _dataset(
        fields=fields,
        default_projection=[field["name"] for field in fields if field["selectable"]],
    )

    with pytest.raises(ValueError, match="primary_key.*selectable and sortable"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_freshness_sla(
    tmp_path: Path,
    value: int,
) -> None:
    with pytest.raises(ValueError, match="freshness_sla_seconds"):
        load_dataset_registry(
            _write_registry(tmp_path, [_dataset(freshness_sla_seconds=value)])
        )


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_max_page_size(
    tmp_path: Path,
    value: int,
) -> None:
    with pytest.raises(ValueError, match="max_page_size"):
        load_dataset_registry(
            _write_registry(tmp_path, [_dataset(max_page_size=value)])
        )


@pytest.mark.parametrize("value", [0, -1])
def test_loader_rejects_non_positive_configured_lookback(
    tmp_path: Path,
    value: int,
) -> None:
    with pytest.raises(ValueError, match="max_lookback_days"):
        load_dataset_registry(
            _write_registry(tmp_path, [_dataset(max_lookback_days=value)])
        )


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("point_in_time", "latestish"),
        ("backfill_policy", "unbounded"),
        ("empty_data_policy", "pretend_success"),
        ("data_classification", "derived_opinion"),
    ],
)
def test_loader_rejects_invalid_dataset_policy_enums(
    tmp_path: Path,
    field_name: str,
    invalid: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        load_dataset_registry(
            _write_registry(tmp_path, [_dataset(**{field_name: invalid})])
        )


@pytest.mark.parametrize(
    ("binding_field", "invalid"),
    [
        ("entitlement_state", "maybe"),
        ("activation_state", "scheduled-ish"),
    ],
)
def test_loader_rejects_invalid_binding_state_enums(
    tmp_path: Path,
    binding_field: str,
    invalid: str,
) -> None:
    with pytest.raises(ValueError, match=binding_field):
        load_dataset_registry(
            _write_registry(
                tmp_path,
                [_dataset(provider_bindings=[_binding(**{binding_field: invalid})])],
            )
        )


@pytest.mark.parametrize(
    "entitlement_state", ["locked", "unknown", "excluded", "retired"]
)
def test_loader_rejects_active_binding_without_active_entitlement(
    tmp_path: Path,
    entitlement_state: str,
) -> None:
    dataset = _dataset(
        provider_bindings=[_binding(entitlement_state=entitlement_state)]
    )

    with pytest.raises(
        ValueError, match="activation_state=active.*entitlement_state=active"
    ):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    ("binding_override", "error"),
    [
        ({"adapter_version": ""}, "adapter_version"),
        ({"target_tables": []}, "target_tables"),
        ({"read_discriminator_value": ""}, "read_discriminator_value"),
    ],
)
def test_loader_rejects_paused_binding_without_complete_static_contract(
    tmp_path: Path,
    binding_override: dict[str, object],
    error: str,
) -> None:
    dataset = _dataset(
        provider_bindings=[
            _binding(
                entitlement_state="unknown",
                activation_state="paused",
                **binding_override,
            )
        ]
    )

    with pytest.raises(ValueError, match=error):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


def test_loader_rejects_duplicate_binding_discriminator_values(
    tmp_path: Path,
) -> None:
    dataset = _dataset(
        provider_bindings=[
            _binding(),
            _binding(
                provider="akshare",
                api_name="stock_zh_a_hist",
                adapter_version="akshare-direct-sqlite.v1",
                read_discriminator_value="tushare_example",
            ),
        ]
    )

    with pytest.raises(ValueError, match="duplicate read_discriminator_value"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    "allowed_values",
    [
        ["ghost_provider_value"],
        ["tushare_example", "ghost_provider_value"],
    ],
)
def test_loader_rejects_discriminator_filter_not_equal_to_binding_authority(
    tmp_path: Path,
    allowed_values: list[str],
) -> None:
    dataset = _dataset(
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {"field": "provider", "allowed_values": allowed_values}
            ]
        )
    )

    with pytest.raises(ValueError, match="read_discriminator_value.*allowed_values"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    ("adapter_override", "error"),
    [
        ({"adapter_version": ""}, "read_model_adapter.adapter_version"),
        ({"primary_table": ""}, "read_model_adapter.primary_table"),
        ({"fixed_field_filters": []}, "fixed_field_filters"),
    ],
)
def test_loader_rejects_incomplete_read_model_adapter(
    tmp_path: Path,
    adapter_override: dict[str, object],
    error: str,
) -> None:
    dataset = _dataset(read_model_adapter=_read_model_adapter(**adapter_override))

    with pytest.raises(ValueError, match=error):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


def test_loader_rejects_read_table_not_produced_by_binding(tmp_path: Path) -> None:
    dataset = _dataset(
        read_model_adapter=_read_model_adapter(primary_table="market_events")
    )

    with pytest.raises(ValueError, match="primary_table.*target_tables"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    "fixed_field_filters",
    [
        [{"field": "missing", "allowed_values": ["x"]}],
        [{"field": "provider", "allowed_values": []}],
        [{"field": "provider", "allowed_values": [""]}],
        [{"field": "provider", "allowed_values": ["x", "x"]}],
        [
            {"field": "provider", "allowed_values": ["tushare_example"]},
            {"field": "provider", "allowed_values": ["duplicate"]},
        ],
    ],
)
def test_loader_rejects_unknown_or_duplicate_adapter_filter_fields(
    tmp_path: Path,
    fixed_field_filters: list[dict[str, object]],
) -> None:
    dataset = _dataset(
        read_model_adapter=_read_model_adapter(fixed_field_filters=fixed_field_filters)
    )

    with pytest.raises(ValueError, match="fixed_field_filters"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    "fields",
    [
        [_field("factor_hash", logical_type="json")],
        [_field("factor_hash", nullable="yes")],
        [_field("factor_hash", selectable="yes")],
        [_field("factor_hash", filterable="yes")],
        [_field("factor_hash", sortable="yes")],
        [_field("factor_hash"), _field("factor_hash")],
    ],
)
def test_loader_rejects_invalid_or_duplicate_field_contracts(
    tmp_path: Path,
    fields: list[dict[str, object]],
) -> None:
    dataset = _dataset(
        fields=fields,
        primary_key=["factor_hash"],
        default_projection=["factor_hash"],
        read_model_adapter=_read_model_adapter(
            fixed_field_filters=[
                {"field": "factor_hash", "allowed_values": ["example"]}
            ]
        ),
    )

    with pytest.raises(ValueError, match="fields"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    "default_projection",
    [["missing"], ["raw_json"], ["factor_hash", "factor_hash"]],
)
def test_loader_rejects_unknown_unselectable_or_duplicate_default_projection(
    tmp_path: Path,
    default_projection: list[str],
) -> None:
    dataset = _dataset(default_projection=default_projection)

    with pytest.raises(ValueError, match="default_projection"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize("internal_field", ["raw_json", "source_file"])
@pytest.mark.parametrize("capability", ["selectable", "filterable", "sortable"])
def test_loader_rejects_internal_fields_with_query_capability(
    tmp_path: Path,
    internal_field: str,
    capability: str,
) -> None:
    fields = _factor_fields()
    next(field for field in fields if field["name"] == internal_field)[capability] = (
        True
    )
    dataset = _dataset(fields=fields)

    with pytest.raises(ValueError, match=f"{internal_field}.*{capability}"):
        load_dataset_registry(_write_registry(tmp_path, [dataset]))


@pytest.mark.parametrize(
    ("level", "unknown_key"),
    [
        ("root", "mystery_root"),
        ("schema_profile", "mystery_profile"),
        ("dataset", "runtime_state"),
        ("binding", "mystery_binding"),
        ("field", "mystery_field"),
        ("read_adapter", "mystery_adapter"),
        ("fixed_filter", "mystery_filter"),
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
    elif level == "schema_profile":
        profile = _factor_schema_profile()
        profile[unknown_key] = True
        root_overrides["schema_profiles"] = {"factor.v1": profile}
        dataset = _profiled_dataset()
    elif level == "dataset":
        dataset[unknown_key] = "must not be accepted"
    elif level == "binding":
        dataset["provider_bindings"][0][unknown_key] = True
    elif level == "field":
        dataset["fields"][0][unknown_key] = True
    elif level == "read_adapter":
        dataset["read_model_adapter"][unknown_key] = True
    else:
        dataset["read_model_adapter"]["fixed_field_filters"][0][unknown_key] = True

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
