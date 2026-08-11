from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tools.compile_provider_native_registry import compile_provider_native_registry, render_registry


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
OBSERVATIONS_PATH = ROOT / "config" / "quicksync_interface_observations.v1.yaml"

TARGET_APIS = {"cb_rate", "cb_rating", "cb_share", "top10_cb_holders"}


def _yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _compiled(observations: dict[str, object] | None = None) -> dict[str, object]:
    return compile_provider_native_registry(
        _yaml(CONTRACTS_PATH),
        observations_document=_yaml(OBSERVATIONS_PATH)
        if observations is None
        else observations,
    )


def _bindings(registry: dict[str, object]) -> dict[str, dict[str, object]]:
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    return {
        item["provider_bindings"][0]["api_name"]: item  # type: ignore[index]
        for item in datasets
    }


def test_cb_basic_seed_receipt_resolves_only_exact_four_candidates() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    authorities = observations["dependency_seed_authorities"]
    assert authorities == [
        {
            "dataset_id": "cn.dataset.cb_basic",
            "field": "ts_code",
            "schema_version": "1.0.0",
                "receipt_id": (
                    "receipt:ce0ebc07db361e0bba68ee970521b623003b4171299e36027f4a02d082c357d9"
                ),
            "data_through": "2026-08-11T21:22:23.287010Z",
            "dependent_api_names": sorted(TARGET_APIS),
        }
    ]

    bindings = _bindings(_compiled(observations))
    assert {
        api
        for api, dataset in bindings.items()
        if dataset["provider_bindings"][0]["probe_state"] == "executable"  # type: ignore[index]
        and dataset["provider_bindings"][0]["activation_state"] == "paused"  # type: ignore[index]
    } & TARGET_APIS == TARGET_APIS
    for api in TARGET_APIS:
        binding = bindings[api]["provider_bindings"][0]
        assert binding["probe_state"] == "executable"
        assert binding["probe_block_reasons"] == []
        assert binding["ingest_contract_state"] == "ready"
        assert binding["ingest_contract_block_reasons"] == []
        assert binding["activation_state"] == "paused"

    for api in (
        "cb_price_chg",
        "forecast",
        "pledge_detail",
        "stk_nineturn",
        "opt_basic",
        "opt_daily",
    ):
        binding = bindings[api]["provider_bindings"][0]
        assert binding["activation_state"] == "paused"
    binding = bindings["cb_price_chg"]["provider_bindings"][0]
    assert binding["probe_state"] == "blocked"
    assert binding["probe_block_reasons"] == ["dependency_seed_receipt_unresolved"]
    assert binding["ingest_contract_state"] == "blocked"

    contracts = _yaml(CONTRACTS_PATH)["contracts"]
    assert isinstance(contracts, list)
    for contract in contracts:
        assert isinstance(contract, dict)
        api = contract["api_name"]
        if (
            set(contract["probe_block_reasons"])
            == {"dependency_seed_receipt_unresolved"}
            and api not in TARGET_APIS
        ):
            binding = bindings[api]["provider_bindings"][0]
            assert binding["activation_state"] == "paused"
            assert binding["probe_state"] == "blocked"
            assert binding["ingest_contract_state"] == "blocked"

    active_count = sum(
        dataset["provider_bindings"][0]["activation_state"] == "active"
        for dataset in bindings.values()
    )
    assert active_count == 113
    assert len(bindings) - active_count == 77


def test_cb_basic_seed_authority_rejects_ineligible_dependent() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    authorities = deepcopy(observations["dependency_seed_authorities"])
    assert isinstance(authorities, list)
    authority = authorities[0]
    assert isinstance(authority, dict)
    authority["dependent_api_names"] = sorted(
        [*authority["dependent_api_names"], "cb_basic"]
    )
    observations["dependency_seed_authorities"] = authorities

    with pytest.raises(ValueError, match="ineligible API: cb_basic"):
        _compiled(observations)


def test_cb_basic_seed_authority_rejects_unknown_or_mismatched_seed() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    authority = observations["dependency_seed_authorities"][0]
    assert isinstance(authority, dict)
    authority["field"] = "bond_short_name"

    with pytest.raises(ValueError, match="ineligible API"):
        _compiled(observations)


def test_cb_basic_seed_authority_rejects_invalid_receipt_binding() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    authority = observations["dependency_seed_authorities"][0]
    assert isinstance(authority, dict)
    authority["receipt_id"] = "receipt:not-a-sha256"

    with pytest.raises(ValueError, match="receipt_id is invalid"):
        _compiled(observations)


def test_cb_basic_seed_registry_renders_byte_identically_twice() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    first = render_registry(_compiled(observations))
    second = render_registry(_compiled(deepcopy(observations)))
    assert first == second
