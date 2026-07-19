from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
import yaml

from tools.compile_tushare_runtime_contracts import (
    RuntimeContractCompilationError,
    compile_runtime_contract_bundle,
    render_contract_bundle,
)
from tools.compile_provider_native_registry import load_upstream_contract_bundle


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
OUTPUT = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"


def _yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


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
        assert by_api[contract["api_name"]] == contract

    unreviewed = by_api["adj_factor"]
    assert unreviewed["dataset_id"] == "cn.dataset.adj_factor"
    assert unreviewed["aliases"] == ["tushare.adj_factor"]
    assert unreviewed["point_in_time"] == "append_only"
    assert unreviewed["primary_key"] == []
    assert unreviewed["response_completeness"] is None
    assert unreviewed["cadence_class"] == "on_demand"
    assert unreviewed["request_template"] == {}
    assert unreviewed["request_variants"] == [{}]
    assert unreviewed["requested_fields"] == []


def test_invalid_provider_field_names_remain_in_raw_payload_not_query_schema() -> None:
    compiled = compile_runtime_contract_bundle(
        _yaml(DOCUMENTS), _yaml(REVIEWED), _yaml(POLICY)
    )
    shibor = next(
        item for item in compiled["contracts"] if item["api_name"] == "shibor"
    )

    assert "1w" not in {field["name"] for field in shibor["fields"]}
    assert shibor["requested_fields"] == []


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
