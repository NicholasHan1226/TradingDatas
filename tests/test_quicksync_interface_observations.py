from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
import yaml

from tools.compile_provider_native_registry import (
    compile_provider_native_registry,
    render_registry,
)
from tests.synthetic_activation_evidence import build_synthetic_activation_evidence


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
OBSERVATIONS_PATH = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
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
    assert activation_projection["candidate_count"] == 15
    assert activation_projection["active_count"] == 15
    assert activation_projection["paused_count"] == 175

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
        "validated_contract_match": 145,
        "numeric_field_repaired": 4,
        "schema_subset": 17,
        "quality_anomaly": 1,
        "empty": 3,
        "permission_denied": 14,
        "credential_rejected": 1,
        "unsupported": 5,
    }
    seen: set[str] = set()
    for classification, expected_count in expected_counts.items():
        group = classifications[classification]
        api_names = set(group if isinstance(group, list) else group)
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


def test_only_reviewed_formal_datasets_are_active_and_candidates_remain_paused() -> None:
    registry = _compiled()
    bindings = _bindings(registry)
    active = {
        api_name
        for api_name, dataset in bindings.items()
        if dataset["provider_bindings"][0]["activation_state"] == "active"  # type: ignore[index]
    }
    assert active == {
        "adj_factor",
        "hsgt_top10",
        "daily",
        "index_classify",
        "limit_list_ths",
        "moneyflow_ind_ths",
        "repurchase",
        "research_report",
        "stk_auction",
        "stk_limit",
        "stock_basic",
        "suspend_d",
        "sw_daily",
        "top_list",
        "trade_cal",
    }
    assert len(bindings) == 190
    assert sum(
        dataset["provider_bindings"][0]["activation_state"] == "paused"  # type: ignore[index]
        for dataset in bindings.values()
    ) == 175

    expected_direct_wave_ref = (
        "server-evidence/20260722TQkgWsk-1def337-provider-native"
    )
    active_evidence = _observations()["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert {
        api_name: active_evidence[api_name]
        for api_name in (
            "adj_factor",
            "hsgt_top10",
            "limit_list_ths",
            "moneyflow_ind_ths",
            "repurchase",
            "research_report",
            "stk_auction",
            "stk_limit",
            "suspend_d",
            "top_list",
        )
    } == {
        "adj_factor": expected_direct_wave_ref,
        "hsgt_top10": expected_direct_wave_ref,
        "limit_list_ths": expected_direct_wave_ref,
        "moneyflow_ind_ths": expected_direct_wave_ref,
        "repurchase": expected_direct_wave_ref,
        "research_report": expected_direct_wave_ref,
        "stk_auction": expected_direct_wave_ref,
        "stk_limit": expected_direct_wave_ref,
        "suspend_d": expected_direct_wave_ref,
        "top_list": expected_direct_wave_ref,
    }

    observations = _observations()["classifications"]
    assert isinstance(observations, dict)
    candidates = set(observations["validated_contract_match"]) | set(
        observations["numeric_field_repaired"]
    )
    assert len(candidates) == 149
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
    assert len(subsets) == 17

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


def test_numeric_repair_must_exist_in_current_contract() -> None:
    observations = _observations()
    classifications = observations["classifications"]
    assert isinstance(classifications, dict)
    repaired = classifications["numeric_field_repaired"]
    assert isinstance(repaired, dict)
    repaired["shibor"] = [*repaired["shibor"], "not_declared"]

    with pytest.raises(ValueError, match="repaired field remains absent"):
        _compiled(observations)


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
