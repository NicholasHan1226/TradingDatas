"""No-window contracts retain optional proofs without weakening cohort gates."""

from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType
import json

import pytest

from dataset_registry import DatasetRegistry, load_dataset_registry
from query_cursor import SignedCursorCodec
from query_service import QueryService, QueryServiceUnavailable
import query_service as query_module
from storage.receipt_projection import ValidatedRowReceiptProof
from tests import test_provider_native_query as native_helpers

from tests.test_provider_native_query import (
    _insert_native_success_receipt,
    _insert_row,
    _proof_evidence,
    _request,
    _execute,
    NOW,
    SIGNING_KEY,
)


native_harness = native_helpers.native_harness


def _undated(native_harness):
    base = native_harness["dataset"]
    dataset = replace(
        base,
        cadence_class="on_demand",
        provider_bindings=tuple(
            replace(
                b,
                request_window_policy=None,
                request_template=MappingProxyType({}),
                response_completeness=None,
            )
            for b in base.provider_bindings
        ),
    )
    registry = DatasetRegistry(
        (dataset,), query_defaults=native_harness["registry"].query_defaults
    )
    return {
        **native_harness,
        "dataset": dataset,
        "registry": registry,
        "service": QueryService(
            db_path=native_harness["service"]._db_path,
            registry=registry,
            cursor_codec=SignedCursorCodec(SIGNING_KEY),
        ),
    }


def _observed(
    h, monkeypatch, execution="undated-success", window=None, symbol="UNDATED"
):
    receipt = _insert_native_success_receipt(
        monkeypatch,
        h["conn"],
        h["dataset"],
        execution_id=execution,
        call_index=0,
        page_offset=0,
        request_window={} if window is None else window,
    )
    _insert_row(
        h["conn"],
        row_key=execution,
        receipt_id=receipt,
        payload={"symbol": symbol, "trade_date": "20260715"},
    )
    h["conn"].commit()
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *a, **k: _proof_evidence((receipt,)),
    )
    return receipt


def test_on_demand_empty_window_proofs_keep_the_same_query_rows(
    native_harness, monkeypatch
):
    h = _undated(native_harness)
    receipt = _observed(h, monkeypatch)
    request = _request(filters={"symbol": {"eq": "UNDATED"}})
    plain = _execute(h, request)
    proved = _execute(h, replace(request, include_receipt_proofs=True))
    assert (
        proved["data"]
        == plain["data"]
        == [{"symbol": "UNDATED", "trade_date": "20260715"}]
    )
    proof = proved["metadata"]["row_receipt_proofs"][0]
    assert proof["receipt_id"] == receipt
    assert proof["request_window"] == {}
    assert len(proof["receipt_proof_sha256"]) == 64


@pytest.mark.parametrize(
    "damage",
    [
        "required_empty",
        "placeholder_without_policy",
        "invalid_date",
        "foreign_provider",
    ],
)
def test_empty_proof_exception_cannot_bypass_the_binding_contract(
    native_harness, monkeypatch, damage
):
    h = _undated(native_harness)
    window = {}
    if damage in ("required_empty", "invalid_date"):
        h = native_harness
        if damage == "invalid_date":
            window = {"trade_date": "20261399"}
    _observed(h, monkeypatch, window=window)
    if damage in ("placeholder_without_policy", "foreign_provider"):
        dataset = replace(
            h["dataset"],
            provider_bindings=tuple(
                replace(
                    b,
                    request_template=MappingProxyType(
                        {"trade_date": "${window.trade_date}"}
                    ),
                )
                if damage == "placeholder_without_policy"
                else replace(b, provider="foreign-" + b.provider)
                for b in h["dataset"].provider_bindings
            ),
        )
        # Exercise the formatter's exact provider binding defense using the
        # real query-selected proof, not an unrelated receipt substitution.
        original = query_module._row_receipt_proof_metadata
        monkeypatch.setattr(
            query_module,
            "_row_receipt_proof_metadata",
            lambda _dataset, *a, **k: original(dataset, *a, **k),
        )
    with pytest.raises(QueryServiceUnavailable):
        _execute(
            h,
            _request(
                filters={"symbol": {"eq": "UNDATED"}}, include_receipt_proofs=True
            ),
        )


def test_empty_window_proofs_still_reject_mixed_execution_cohorts(
    native_harness, monkeypatch
):
    h = _undated(native_harness)
    _observed(h, monkeypatch, execution="first-undated", symbol="UNDATED_A")
    _observed(h, monkeypatch, execution="second-undated", symbol="UNDATED_B")
    request = _request(filters={"symbol": {"in": ["UNDATED_A", "UNDATED_B"]}})
    assert len(_execute(h, request)["data"]) == 2
    with pytest.raises(QueryServiceUnavailable):
        _execute(h, replace(request, include_receipt_proofs=True))


@pytest.mark.parametrize(
    "dataset_id",
    [
        "cn.dataset.fund_basic",
        "cn.dataset.ci_index_member",
        "cn.dataset.index_member_all",
    ],
)
def test_existing_registry_undated_contracts_accept_empty_proof_window(dataset_id):
    dataset = load_dataset_registry().resolve(dataset_id)
    binding = dataset.provider_bindings[0]
    assert dataset.cadence_class == "on_demand"
    assert binding.request_window_policy is None
    receipt = "receipt:synthetic-undated-contract"
    proof = ValidatedRowReceiptProof(
        dataset_id=dataset_id,
        provider=binding.provider,
        receipt_id=receipt,
        status="success",
        execution_id="synthetic-execution",
        config_hash="a" * 64,
        request_window=MappingProxyType({}),
        data_through="2026-07-17T03:00:00Z",
        finished_at=datetime(2026, 7, 17, 3, tzinfo=timezone.utc),
        receipt_proof_sha256="b" * 64,
    )
    row = (
        json.dumps({"ts_code": "SYNTHETIC"}),
        binding.provider,
        "synthetic-row",
        "valid",
        "[]",
        receipt,
    )
    result = query_module._row_receipt_proof_metadata(
        dataset, (row,), {receipt: proof}, now=NOW
    )
    assert result[0]["receipt_id"] == receipt
    assert result[0]["request_window"] == {}


def test_historical_nonempty_window_is_not_reinterpreted_by_empty_exception(
    native_harness, monkeypatch
):
    h = _undated(native_harness)
    receipt = _observed(h, monkeypatch, window={"trade_date": "20260715"})
    result = _execute(
        h,
        _request(filters={"symbol": {"eq": "UNDATED"}}, include_receipt_proofs=True),
    )
    assert len(result["data"]) == 1
    assert result["metadata"]["row_receipt_proofs"][0]["receipt_id"] == receipt
