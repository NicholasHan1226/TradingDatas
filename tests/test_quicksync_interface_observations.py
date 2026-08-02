from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tests.synthetic_activation_evidence import build_synthetic_activation_evidence
from tools.compile_provider_native_registry import (
    compile_provider_native_registry,
    render_registry,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
OBSERVATIONS_PATH = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
REQUEST_OBSERVATIONS_PATH = ROOT / "config" / "tushare_request_observations.v1.yaml"
EXPECTED_MATRIX_SHA256 = (
    "ea102cd7b189e1c7d8d0c208c303b308ebf3a07bd4c9b682c8b10ada9ccfb1e1"
)
EXPECTED_API_NAMES_SHA256 = (
    "5662a3b76827ac153086c37c0da74e1dbc675c13c67c9f68485a8002cd6e7de0"
)


def _yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _contracts() -> dict[str, object]:
    return deepcopy(_yaml(CONTRACTS_PATH))


def _observations() -> dict[str, object]:
    return deepcopy(_yaml(OBSERVATIONS_PATH))


def _synthetic_activation_evidence() -> dict[str, object]:
    return build_synthetic_activation_evidence(_contracts(), _observations())


def _compiled(
    observations: dict[str, object] | None = None,
) -> dict[str, object]:
    return compile_provider_native_registry(
        _contracts(),
        observations_document=_observations() if observations is None else observations,
    )


def _compiled_with_activation(
    activation_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    return compile_provider_native_registry(
        _contracts(),
        observations_document=_observations(),
        activation_evidence_document=(
            _synthetic_activation_evidence()
            if activation_evidence is None
            else activation_evidence
        ),
        compilation_mode="preactivation_candidate",
    )


def test_synthetic_https_activation_evidence_freezes_safe_schema_and_bindings() -> None:
    document = _synthetic_activation_evidence()
    evidence = document["evidence"]
    results = document["results"]
    assert isinstance(evidence, dict)
    assert isinstance(results, list)

    assert evidence["promotion_stage"] == "preactivation_candidate"
    assert evidence["transport"] == {
        "endpoint_host": "api.quicksync.cn",
        "scheme": "https",
    }
    assert evidence["retries"] == 0
    assert evidence["production_ready"] is False
    assert evidence["raw_data_persisted"] is False
    assert evidence["credential_persisted"] is False
    assert evidence["request_values_persisted"] is False
    assert len(results) == evidence["interface_count"]
    assert [item["api_name"] for item in results] == sorted(
        item["api_name"] for item in results
    )
    assert len({item["api_name"] for item in results}) == len(results)
    activation_projection = document["activation_projection"]
    assert isinstance(activation_projection, dict)
    active_evidence = _observations()["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert activation_projection["candidate_count"] == len(active_evidence)
    assert activation_projection["active_count"] == len(active_evidence)
    assert activation_projection["paused_count"] == len(_contracts()["contracts"]) - len(
        active_evidence
    )

    _compiled_with_activation(document)

    serialized = yaml.safe_dump(document, sort_keys=False).lower()
    for forbidden in ("token:", "params:", "raw_rows:", "raw_payload:"):
        assert forbidden not in serialized


def test_https_activation_evidence_plan_binding_drift_fails_closed() -> None:
    activation = _synthetic_activation_evidence()
    evidence = activation["evidence"]
    assert isinstance(evidence, dict)
    evidence["request_plan_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="bindings_sha256"):
        _compiled_with_activation(activation)


def _bindings(registry: dict[str, object]) -> dict[str, dict[str, object]]:
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    return {
        item["provider_bindings"][0]["api_name"]: item  # type: ignore[index]
        for item in datasets
    }


def test_frozen_matrix_identity_and_classifications_cover_190_once() -> None:
    document = _observations()
    evidence = document["matrix_evidence"]
    classifications = document["classifications"]
    assert isinstance(evidence, dict)
    assert isinstance(classifications, dict)

    assert evidence["sha256"] == EXPECTED_MATRIX_SHA256
    assert evidence["api_names_sha256"] == EXPECTED_API_NAMES_SHA256
    assert evidence["interface_count"] == 190
    assert evidence["raw_data_persisted"] is False
    assert evidence["credential_persisted"] is False
    assert evidence["interface_probe_scheme"] == "http"
    assert evidence["production_ready"] is False
    assert (
        evidence["production_transport_alignment"]
        == "blocked_until_safe_pre_request_dns_failover_is_implemented_and_verified"
    )
    expected_counts = {
        "validated_contract_match": 146,
        "numeric_field_repaired": 4,
        "schema_subset": 16,
        "quality_anomaly": 1,
        "empty": 3,
        "permission_denied": 14,
        "credential_rejected": 1,
        "unsupported": 5,
    }
    seen: set[str] = set()
    for classification, expected_count in expected_counts.items():
        group = classifications[classification]
        api_names = set(group)
        assert len(api_names) == expected_count
        assert seen.isdisjoint(api_names)
        seen.update(api_names)
    assert len(seen) == 190
    assert (
        sum(
            len(fields) for fields in classifications["numeric_field_repaired"].values()
        )
        == 29
    )
    assert (
        hashlib.sha256(("\n".join(sorted(seen)) + "\n").encode()).hexdigest()
        == EXPECTED_API_NAMES_SHA256
    )


def test_request_observations_pin_current_quicksync_observation_bytes() -> None:
    request_observations = _yaml(REQUEST_OBSERVATIONS_PATH)
    provenance = request_observations["provenance"]
    assert isinstance(provenance, dict)
    quicksync = provenance["quicksync_interface_observations"]
    assert isinstance(quicksync, dict)
    assert quicksync == {
        "path": "config/quicksync_interface_observations.v1.yaml",
        "sha256": hashlib.sha256(OBSERVATIONS_PATH.read_bytes()).hexdigest(),
    }
    registered = provenance["registered_contract_bundle"]
    assert isinstance(registered, dict)
    assert registered == {
        "path": "config/tushare_upstream_contracts.v1.yaml",
        "sha256": hashlib.sha256(CONTRACTS_PATH.read_bytes()).hexdigest(),
    }


def test_only_reviewed_formal_datasets_are_active_and_candidates_remain_paused() -> None:
    registry = _compiled()
    bindings = _bindings(registry)
    active = {
        api_name
        for api_name, dataset in bindings.items()
        if dataset["provider_bindings"][0]["activation_state"] == "active"  # type: ignore[index]
    }
    active_evidence = _observations()["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert active == set(active_evidence)
    assert len(bindings) == 190
    paused_count = sum(
        dataset["provider_bindings"][0]["activation_state"] == "paused"  # type: ignore[index]
        for dataset in bindings.values()
    )
    assert paused_count == len(bindings) - len(active)

    expected_direct_wave_ref = (
        "server-evidence/20260722TQkgWsk-1def337-provider-native"
    )
    direct_api_names = (
        "adj_factor",
        "cb_issue",
        "daily_info",
        "disclosure_date",
        "fund_div",
        "hsgt_top10",
        "index_dailybasic",
        "limit_cpt_list",
        "limit_list_ths",
        "limit_step",
        "moneyflow_hsgt",
        "moneyflow_ind_ths",
        "repurchase",
        "research_report",
        "share_float",
        "stk_auction",
        "stk_limit",
        "stk_managers",
        "suspend_d",
        "sz_daily_info",
        "top_list",
    )
    assert {
        api_name: active_evidence[api_name] for api_name in direct_api_names
    } == {api_name: expected_direct_wave_ref for api_name in direct_api_names}

    observations = _observations()["classifications"]
    assert isinstance(observations, dict)
    candidates = set(observations["validated_contract_match"]) | set(
        observations["numeric_field_repaired"]
    )
    assert len(candidates) == 150
    for api_name in candidates - active:
        binding = bindings[api_name]["provider_bindings"][0]  # type: ignore[index]
        assert binding["entitlement_state"] == "active"
        assert binding["activation_state"] == "paused"


def test_fail_closed_state_classes_map_without_becoming_active() -> None:
    registry = _compiled()
    bindings = _bindings(registry)
    classifications = _observations()["classifications"]
    assert isinstance(classifications, dict)
    expected = {
        "quality_anomaly": "active",
        "empty": "active",
        "permission_denied": "locked",
        "credential_rejected": "unknown",
        "unsupported": "excluded",
    }
    for classification, entitlement in expected.items():
        for api_name in classifications[classification]:
            binding = bindings[api_name]["provider_bindings"][0]  # type: ignore[index]
            assert binding["entitlement_state"] == entitlement
            assert binding["activation_state"] == "paused"


def test_schema_subset_removes_only_observed_non_structural_fields() -> None:
    contracts = _contracts()["contracts"]
    assert isinstance(contracts, list)
    source_by_api = {item["api_name"]: item for item in contracts}
    registry_by_api = _bindings(_compiled())
    classifications = _observations()["classifications"]
    assert isinstance(classifications, dict)
    subsets = classifications["schema_subset"]
    assert isinstance(subsets, dict)
    assert len(subsets) == 16

    for api_name, missing_fields in subsets.items():
        source = source_by_api[api_name]
        target = registry_by_api[api_name]
        source_fields = {field["name"] for field in source["fields"]}
        target_fields = {field["name"] for field in target["fields"]}
        missing = set(missing_fields)
        assert target_fields == source_fields - missing
        protected = set(source["primary_key"])
        protected.update(
            field
            for field in (
                source["as_of_field"],
                source["range_field"],
                source["partition_field"],
            )
            if field is not None
        )
        completeness = source["response_completeness"]
        if completeness is not None:
            protected.update(completeness["fixed_field_matches"])
            protected.update(
                completeness[key]
                for key in ("date_field", "partition_field")
                if key in completeness
            )
        assert missing.isdisjoint(protected)
        assert target["primary_key"] == source["primary_key"]
        assert target["as_of_field"] == source["as_of_field"]
        assert target["range_field"] == source["range_field"]
        assert target["partition_field"] == source["partition_field"]
        target_binding = target["provider_bindings"][0]
        assert (
            target_binding["response_completeness"] == source["response_completeness"]
        )

    assert "freq" in {
        field["name"] for field in registry_by_api["rt_min_daily"]["fields"]
    }


def test_observed_response_contract_deltas_are_small_and_schema_versioned() -> None:
    source_by_api = {
        item["api_name"]: item for item in _contracts()["contracts"]
    }
    registry_by_api = _bindings(_compiled())
    overrides = _observations()["response_contract_overrides"]
    assert isinstance(overrides, dict)
    assert set(overrides) == {
        "anns_d",
        "bak_basic",
        "cb_daily",
        "cb_issue",
        "dc_daily",
        "disclosure_date",
        "fut_settle",
        "moneyflow",
        "stk_holdertrade",
        "stk_managers",
        "ths_daily",
        "top_inst",
    }

    for api_name, override in overrides.items():
        assert isinstance(override, dict)
        source = source_by_api[api_name]
        target = registry_by_api[api_name]
        assert source["schema_version"] == "1.0.0"
        assert target["schema_version"] == (
            "3.0.0" if api_name == "dc_daily" else "2.0.0"
        )
        source_fields = {field["name"] for field in source["fields"]}
        target_fields = {field["name"] for field in target["fields"]}
        missing = set(override["missing_fields"])
        additions = {field["name"] for field in override["additional_fields"]}
        assert target_fields == (source_fields - missing) | additions

    assert "rec_time" not in {
        field["name"] for field in registry_by_api["anns_d"]["fields"]
    }
    assert "category" in {
        field["name"] for field in registry_by_api["dc_daily"]["fields"]
    }
    assert "category" in registry_by_api["dc_daily"]["provider_bindings"][0][
        "requested_fields"
    ]
    assert registry_by_api["dc_daily"]["schema_version"] == "3.0.0"
    assert {
        field["name"]: field["logical_type"]
        for field in registry_by_api["moneyflow"]["fields"]
        if field["name"].endswith("_vol")
    }["net_mf_vol"] == "text"
    assert {
        field["name"]: field["logical_type"]
        for field in registry_by_api["top_inst"]["fields"]
    }["side"] == "integer"


def test_observed_response_contract_cannot_remove_structural_field() -> None:
    observations = _observations()
    overrides = observations["response_contract_overrides"]
    assert isinstance(overrides, dict)
    overrides["daily"] = {
        "evidence_ref": "docs/adr/ADR-0011-quicksync-observed-response-contracts.md",
        "schema_version": "3.0.0",
        "missing_fields": ["trade_date"],
        "type_overrides": [],
        "additional_fields": [],
    }

    with pytest.raises(ValueError, match="cannot remove structural field"):
        _compiled(observations)


def test_observed_response_contract_requires_a_new_schema_major() -> None:
    observations = _observations()
    overrides = observations["response_contract_overrides"]
    assert isinstance(overrides, dict)
    override = overrides["anns_d"]
    assert isinstance(override, dict)
    override["schema_version"] = "1.0.1"

    with pytest.raises(ValueError, match="advance the source contract major"):
        _compiled(observations)


def test_numeric_repair_must_exist_in_current_contract() -> None:
    observations = _observations()
    classifications = observations["classifications"]
    assert isinstance(classifications, dict)
    repaired = classifications["numeric_field_repaired"]
    assert isinstance(repaired, dict)
    repaired["shibor"] = [*repaired["shibor"], "not_declared"]

    with pytest.raises(ValueError, match="repaired field remains absent"):
        _compiled(observations)


def test_numeric_repair_can_activate_only_after_declared_field_validation() -> None:
    registry = _compiled()
    bindings = _bindings(registry)

    for api_name in ("shibor", "shibor_quote"):
        binding = bindings[api_name]["provider_bindings"][0]  # type: ignore[index]
        assert binding["entitlement_state"] == "active"
        assert binding["activation_state"] == "active"


def test_numeric_repair_without_explicit_evidence_remains_paused() -> None:
    registry = _compiled()
    binding = _bindings(registry)["shibor_lpr"]["provider_bindings"][0]  # type: ignore[index]

    assert binding["entitlement_state"] == "active"
    assert binding["activation_state"] == "paused"


def test_structural_schema_field_cannot_be_removed() -> None:
    observations = _observations()
    classifications = observations["classifications"]
    active = observations["active_evidence"]
    assert isinstance(classifications, dict)
    assert isinstance(active, dict)
    classifications["validated_contract_match"].remove("daily")
    classifications["schema_subset"]["daily"] = ["ts_code"]
    del active["daily"]

    with pytest.raises(ValueError, match="cannot remove structural field"):
        _compiled(observations)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item["classifications"]["empty"].append("daily"),
            "overlaps classifications",
        ),
        (
            lambda item: item["classifications"]["validated_contract_match"].pop(),
            "API set must exactly match",
        ),
        (
            lambda item: item["matrix_evidence"].update(api_names_sha256="0" * 64),
            "api_names_sha256 does not match",
        ),
        (
            lambda item: item["matrix_evidence"].update(raw_data_persisted=True),
            "raw_data_persisted must be false",
        ),
        (
            lambda item: item["matrix_evidence"].update(interface_probe_scheme="https"),
            "interface_probe_scheme must be http",
        ),
        (
            lambda item: item["matrix_evidence"].update(production_ready=True),
            "production_ready must be false",
        ),
        (
            lambda item: item.update(token="sensitive"),
            "unknown key",
        ),
        (
            lambda item: item["active_evidence"].update(
                daily="server-evidence/token-secret"
            ),
            "non-sensitive relative reference",
        ),
    ],
)
def test_observation_contradictions_and_sensitive_content_fail_closed(
    mutator: object, message: str
) -> None:
    observations = _observations()
    mutator(observations)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        _compiled(observations)


def test_two_compilations_are_byte_identical() -> None:
    observations = _observations()
    first = render_registry(_compiled(observations))
    second = render_registry(_compiled(deepcopy(observations)))

    assert first.encode("utf-8") == second.encode("utf-8")
