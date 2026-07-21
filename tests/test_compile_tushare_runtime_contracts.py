from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
import yaml

from tools.compile_tushare_runtime_contracts import (
    RuntimeContractCompilationError,
    compile_runtime_contract_bundle as _compile_runtime_contract_bundle,
    render_contract_bundle,
)
from tools.compile_provider_native_registry import load_upstream_contract_bundle


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
OUTPUT = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
REQUEST_OBSERVATIONS = ROOT / "config" / "tushare_request_observations.v1.yaml"
TRANSPORT_OBSERVATIONS = ROOT / "config" / "quicksync_interface_observations.v1.yaml"


def _yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_bytes())
    assert isinstance(document, dict)
    return document


def _yaml_bytes(document: dict[str, object]) -> bytes:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def compile_runtime_contract_bundle(
    documents: dict[str, object],
    reviewed: dict[str, object],
    policy: dict[str, object],
) -> dict[str, object]:
    original_document_bytes = DOCUMENTS.read_bytes()
    original_reviewed_bytes = REVIEWED.read_bytes()
    document_bytes = (
        original_document_bytes
        if documents == _yaml(DOCUMENTS)
        else _yaml_bytes(documents)
    )
    reviewed_bytes = (
        original_reviewed_bytes
        if reviewed == _yaml(REVIEWED)
        else _yaml_bytes(reviewed)
    )
    policy_bytes = (
        POLICY.read_bytes() if policy == _yaml(POLICY) else _yaml_bytes(policy)
    )
    request_observations = _yaml(REQUEST_OBSERVATIONS)
    request_observations["provenance"]["official_contracts"]["sha256"] = hashlib.sha256(
        document_bytes
    ).hexdigest()
    request_observations["provenance"]["reviewed_contract_bundle"]["sha256"] = (
        hashlib.sha256(reviewed_bytes).hexdigest()
    )
    request_bytes = (
        REQUEST_OBSERVATIONS.read_bytes()
        if document_bytes == original_document_bytes
        and reviewed_bytes == original_reviewed_bytes
        else _yaml_bytes(request_observations)
    )
    transport_bytes = TRANSPORT_OBSERVATIONS.read_bytes()
    return _compile_runtime_contract_bundle(
        document_bytes,
        reviewed_bytes,
        policy_bytes,
        request_observations=request_bytes,
        transport_observations=transport_bytes,
        official_contract_sha256=hashlib.sha256(document_bytes).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_bytes).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )


def _canonical_sha256(value: object) -> str:
    rendered = yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _rebind_policy_to_documents(
    documents: dict[str, object], policy: dict[str, object]
) -> None:
    policy["source_snapshot_canonical_sha256"] = _canonical_sha256(documents)


def _expected_input_fields(document: dict[str, object]) -> list[dict[str, object]]:
    required_values = {"Y": True, "N": False, "": None}
    raw_fields = document["input_fields"]
    assert isinstance(raw_fields, list)
    return [
        {
            "name": field["name"],
            "declared_source_type": field["declared_type"],
            "required": required_values[field["required"]],
        }
        for field in raw_fields
    ]


def test_compiler_exposes_all_official_in_scope_interfaces_without_per_api_code() -> (
    None
):
    documents = _yaml(DOCUMENTS)
    reviewed = _yaml(REVIEWED)
    policy = _yaml(POLICY)

    compiled = compile_runtime_contract_bundle(documents, reviewed, policy)

    assert len(compiled["contracts"]) == 190
    assert len({item["dataset_id"] for item in compiled["contracts"]}) == 190
    assert len({item["api_name"] for item in compiled["contracts"]}) == 190
    assert {item["api_name"] for item in compiled["contracts"]} == {
        item["api_name"] for item in documents["contracts"]
    }


def test_compiler_projects_all_official_input_fields_into_runtime_contracts() -> None:
    documents = _yaml(DOCUMENTS)
    compiled = compile_runtime_contract_bundle(
        documents, _yaml(REVIEWED), _yaml(POLICY)
    )
    documents_by_api = {item["api_name"]: item for item in documents["contracts"]}

    assert len(compiled["contracts"]) == 190
    for contract in compiled["contracts"]:
        input_fields = contract["input_fields"]
        assert input_fields == _expected_input_fields(
            documents_by_api[contract["api_name"]]
        )
        assert all(
            set(field) == {"name", "declared_source_type", "required"}
            for field in input_fields
        )


def test_reviewed_contracts_are_preserved_and_unreviewed_are_honestly_paused_ready() -> (
    None
):
    reviewed = _yaml(REVIEWED)
    compiled = compile_runtime_contract_bundle(
        _yaml(DOCUMENTS), reviewed, _yaml(POLICY)
    )
    by_api = {item["api_name"]: item for item in compiled["contracts"]}

    normalized_reviewed = load_upstream_contract_bundle(reviewed)
    for contract in normalized_reviewed["contracts"]:
        compiled_contract = deepcopy(by_api[contract["api_name"]])
        compiled_contract.pop("input_fields")
        for key in (
            "probe_state",
            "probe_block_reasons",
            "ingest_contract_state",
            "ingest_contract_block_reasons",
        ):
            compiled_contract.pop(key)
        assert compiled_contract == contract

    documents_by_api = {
        item["api_name"]: item for item in _yaml(DOCUMENTS)["contracts"]
    }
    for api_name in ("daily", "stock_basic", "trade_cal"):
        assert by_api[api_name]["input_fields"] == _expected_input_fields(
            documents_by_api[api_name]
        )

    unreviewed = by_api["adj_factor"]
    assert unreviewed["dataset_id"] == "cn.dataset.adj_factor"
    assert unreviewed["aliases"] == ["tushare.adj_factor"]
    assert unreviewed["point_in_time"] == "append_only"
    assert unreviewed["primary_key"] == []
    assert unreviewed["response_completeness"] is None
    assert unreviewed["cadence_class"] == "on_demand"
    assert unreviewed["request_template"] == {"trade_date": "${window.trade_date}"}
    assert unreviewed["request_variants"] == [{}]
    assert unreviewed["requested_fields"] == []


def test_numeric_leading_provider_fields_are_preserved_in_query_schema() -> None:
    compiled = compile_runtime_contract_bundle(
        _yaml(DOCUMENTS), _yaml(REVIEWED), _yaml(POLICY)
    )
    shibor = next(
        item for item in compiled["contracts"] if item["api_name"] == "shibor"
    )

    assert "1w" in {field["name"] for field in shibor["fields"]}
    assert shibor["requested_fields"] == []


def test_documented_input_type_tokens_and_unknown_requiredness_are_preserved() -> None:
    compiled = compile_runtime_contract_bundle(
        _yaml(DOCUMENTS), _yaml(REVIEWED), _yaml(POLICY)
    )
    by_api = {item["api_name"]: item for item in compiled["contracts"]}

    fund_manager = {
        field["name"]: field for field in by_api["fund_manager"]["input_fields"]
    }
    assert fund_manager["offset"] == {
        "name": "offset",
        "declared_source_type": "intint",
        "required": False,
    }
    fund_company = by_api["fund_company"]["input_fields"]
    assert fund_company
    assert all(field["required"] is None for field in fund_company)


def test_compiler_is_deterministic_and_does_not_mutate_inputs() -> None:
    documents = _yaml(DOCUMENTS)
    reviewed = _yaml(REVIEWED)
    policy = _yaml(POLICY)
    originals = tuple(deepcopy(item) for item in (documents, reviewed, policy))

    first = compile_runtime_contract_bundle(documents, reviewed, policy)
    second = compile_runtime_contract_bundle(
        deepcopy(documents), deepcopy(reviewed), deepcopy(policy)
    )

    assert first == second
    assert render_contract_bundle(first) == render_contract_bundle(second)
    assert (documents, reviewed, policy) == originals


def test_checked_in_bundle_is_reproducible_and_loadable() -> None:
    compiled = compile_runtime_contract_bundle(
        _yaml(DOCUMENTS), _yaml(REVIEWED), _yaml(POLICY)
    )

    assert render_contract_bundle(compiled) == OUTPUT.read_text(encoding="utf-8")
    assert len(hashlib.sha256(OUTPUT.read_bytes()).hexdigest()) == 64


def test_compiler_rejects_document_or_reviewed_drift() -> None:
    documents = _yaml(DOCUMENTS)
    reviewed = _yaml(REVIEWED)
    policy = _yaml(POLICY)
    policy["source_snapshot_canonical_sha256"] = "0" * 64

    with pytest.raises(RuntimeContractCompilationError, match="snapshot SHA"):
        compile_runtime_contract_bundle(documents, reviewed, policy)

    policy = _yaml(POLICY)
    reviewed["contracts"][0]["source_document_sha256"] = "f" * 64
    with pytest.raises(RuntimeContractCompilationError, match="official document"):
        compile_runtime_contract_bundle(documents, reviewed, policy)


def test_compiler_rejects_missing_or_duplicate_official_api() -> None:
    documents = _yaml(DOCUMENTS)
    policy = _yaml(POLICY)
    documents["contracts"].pop()
    documents["counts"]["in_scope_contracts"] = 189
    _rebind_policy_to_documents(documents, policy)

    with pytest.raises(RuntimeContractCompilationError, match="exactly 190"):
        compile_runtime_contract_bundle(documents, _yaml(REVIEWED), policy)

    documents = _yaml(DOCUMENTS)
    policy = _yaml(POLICY)
    documents["contracts"].append(deepcopy(documents["contracts"][0]))
    documents["counts"]["in_scope_contracts"] = 191
    _rebind_policy_to_documents(documents, policy)
    with pytest.raises(RuntimeContractCompilationError, match="duplicate document API"):
        compile_runtime_contract_bundle(documents, _yaml(REVIEWED), policy)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_field", "duplicate input field"),
        ("unknown_required", "unsupported required marker"),
        ("unknown_type", "unsupported declared type"),
    ],
)
def test_compiler_rejects_invalid_official_input_contract(
    mutation: str, message: str
) -> None:
    documents = _yaml(DOCUMENTS)
    policy = _yaml(POLICY)
    first = documents["contracts"][0]
    if mutation == "duplicate_field":
        first["input_fields"].append(deepcopy(first["input_fields"][0]))
    elif mutation == "unknown_required":
        first["input_fields"][0]["required"] = "MAYBE"
    else:
        first["input_fields"][0]["declared_type"] = "decimal"
    _rebind_policy_to_documents(documents, policy)

    with pytest.raises(RuntimeContractCompilationError, match=message):
        compile_runtime_contract_bundle(documents, _yaml(REVIEWED), policy)
