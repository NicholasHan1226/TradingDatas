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
BATCH_A_APIS = {"cb_rate", "cb_rating", "cb_share"}
BATCH_A_REF = "server-evidence/ashare-wave5-exact4-20260812T0618Z"
BATCH_B_APIS = {"top10_cb_holders"}
BATCH_B_REF = "server-evidence/ashare-wave5-exact4-20260812T0618Z"
WAVE7_FINANCIAL_APIS = {
    "balancesheet",
    "cashflow",
    "express",
    "fina_audit",
    "fina_indicator",
    "fina_mainbz",
    "income",
}
WAVE7_FINANCIAL_REF = "server-evidence/ashare-wave7-financial-exact7-20260812T1815CST"
WAVE7_TRADEDAY_APIS = {"cyq_chips", "cyq_perf", "daily_basic"}
SECURITY_MASTER_DEPENDENTS = {
    "balancesheet",
    "cashflow",
    "cyq_chips",
    "cyq_perf",
    "daily_basic",
    "express",
    "fina_audit",
    "fina_indicator",
    "fina_mainbz",
    "income",
    "pledge_stat",
    "rt_min_daily",
    "stk_mins",
    "stk_rewards",
    "top10_floatholders",
    "top10_holders",
}
SECURITY_MASTER_RECEIPT = (
    "receipt:653392e20e8ec6de05bc8729d2802d529e51ecf47dd261f82cb0a1938ca0a115"
)
SECURITY_MASTER_DATA_THROUGH = "2026-08-11T10:35:04.025706+00:00"


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


def test_formal_seed_receipts_resolve_only_exact_dependents() -> None:
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
            "data_through": "2026-08-11T21:22:19.352479Z",
            "dependent_api_names": sorted(TARGET_APIS),
        },
        {
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "schema_version": "2.0.0",
            "receipt_id": SECURITY_MASTER_RECEIPT,
            "data_through": SECURITY_MASTER_DATA_THROUGH,
            "dependent_api_names": sorted(SECURITY_MASTER_DEPENDENTS),
        },
    ]

    bindings = _bindings(_compiled(observations))
    assert {
        api
        for api, dataset in bindings.items()
        if dataset["provider_bindings"][0]["probe_state"] == "executable"  # type: ignore[index]
        and dataset["provider_bindings"][0]["activation_state"] == "paused"  # type: ignore[index]
    } & TARGET_APIS == set()
    for api in TARGET_APIS:
        binding = bindings[api]["provider_bindings"][0]
        assert binding["probe_state"] == "executable"
        assert binding["probe_block_reasons"] == []
        assert binding["ingest_contract_state"] == "ready"
        assert binding["ingest_contract_block_reasons"] == []
        assert binding["activation_state"] == (
            "active" if api in BATCH_A_APIS | BATCH_B_APIS else "paused"
        )

    for api in SECURITY_MASTER_DEPENDENTS:
        binding = bindings[api]["provider_bindings"][0]
        assert binding["probe_state"] == "executable"
        assert binding["probe_block_reasons"] == []
        assert binding["ingest_contract_state"] == "ready"
        assert binding["ingest_contract_block_reasons"] == []
        assert binding["activation_state"] == (
            "active" if api in WAVE7_FINANCIAL_APIS | WAVE7_TRADEDAY_APIS | {"pledge_stat", "stk_mins", "stk_rewards", "top10_floatholders", "top10_holders"} else "paused"
        )

    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert {api for api in BATCH_A_APIS if active_evidence[api] == BATCH_A_REF} == BATCH_A_APIS
    assert {api for api in BATCH_B_APIS if active_evidence[api] == BATCH_B_REF} == BATCH_B_APIS
    assert {
        api for api in WAVE7_FINANCIAL_APIS
        if active_evidence.get(api) == WAVE7_FINANCIAL_REF
    } == WAVE7_FINANCIAL_APIS

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
            and api not in TARGET_APIS | SECURITY_MASTER_DEPENDENTS
        ):
            binding = bindings[api]["provider_bindings"][0]
            assert binding["activation_state"] == "paused"
            assert binding["probe_state"] == "blocked"
            assert binding["ingest_contract_state"] == "blocked"

    active_count = sum(
        dataset["provider_bindings"][0]["activation_state"] == "active"
        for dataset in bindings.values()
    )
    assert active_count == 132
    assert len(bindings) - active_count == 58


def test_security_master_seed_authority_is_exact_and_fail_closed() -> None:
    observations = _yaml(OBSERVATIONS_PATH)
    authorities = deepcopy(observations["dependency_seed_authorities"])
    assert isinstance(authorities, list)
    security_authority = authorities[1]
    assert isinstance(security_authority, dict)

    security_authority["receipt_id"] = "receipt:not-a-sha256"
    observations["dependency_seed_authorities"] = authorities
    with pytest.raises(ValueError, match="receipt_id is invalid"):
        _compiled(observations)

    observations = _yaml(OBSERVATIONS_PATH)
    authorities = deepcopy(observations["dependency_seed_authorities"])
    assert isinstance(authorities, list)
    security_authority = authorities[1]
    assert isinstance(security_authority, dict)
    security_authority["data_through"] = "not-rfc3339"
    observations["dependency_seed_authorities"] = authorities
    with pytest.raises(ValueError, match="data_through must be RFC3339"):
        _compiled(observations)

    observations = _yaml(OBSERVATIONS_PATH)
    authorities = deepcopy(observations["dependency_seed_authorities"])
    assert isinstance(authorities, list)
    security_authority = authorities[1]
    assert isinstance(security_authority, dict)
    security_authority["dependent_api_names"] = sorted(
        [*security_authority["dependent_api_names"], "cb_price_chg"]
    )
    observations["dependency_seed_authorities"] = authorities
    with pytest.raises(ValueError, match="ineligible API: cb_price_chg"):
        _compiled(observations)

    for key, value, message in (
        ("field", "bond_short_name", "field does not match source dataset"),
        ("schema_version", "1.0.0", "schema_version does not match source dataset"),
    ):
        observations = _yaml(OBSERVATIONS_PATH)
        authorities = deepcopy(observations["dependency_seed_authorities"])
        assert isinstance(authorities, list)
        security_authority = authorities[1]
        assert isinstance(security_authority, dict)
        security_authority[key] = value
        observations["dependency_seed_authorities"] = authorities
        with pytest.raises(ValueError, match=message):
            _compiled(observations)


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
