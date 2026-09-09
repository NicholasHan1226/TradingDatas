"""Finite minute histories keep their own receipt/window authority."""

from dataclasses import replace

import pytest

from dataset_registry import DatasetRegistry, load_dataset_registry
from query_contract import QueryRequest
from query_cursor import SignedCursorCodec
from query_service import QueryService, QueryServiceUnavailable
import query_service as query_module
from tests import test_provider_native_query as native

native_harness = native.native_harness
WINDOW = {"start_time": "2026-07-17 00:00:00", "end_time": "2026-07-17 23:59:59"}
THROUGH = "2026-07-17 11:16:00"


@pytest.fixture
def window_harness(native_harness):
    h = native_harness
    minute = native._minute_dataset(h["dataset"])
    template = (
        load_dataset_registry().resolve("cn.dataset.rt_min_daily").provider_bindings[0]
    )
    minute = replace(
        minute,
        point_in_time="append_only",
        provider_bindings=tuple(
            replace(
                b,
                response_completeness=replace(
                    template.response_completeness, fanout_field="symbol"
                ),
                request_window_policy=template.request_window_policy,
            )
            for b in minute.provider_bindings
        ),
    )
    registry = DatasetRegistry((minute,), query_defaults=h["registry"].query_defaults)
    return {
        **h,
        "dataset": minute,
        "registry": registry,
        "service": QueryService(
            db_path=h["service"]._db_path,
            registry=registry,
            cursor_codec=SignedCursorCodec(native.SIGNING_KEY),
        ),
    }


def _seed(
    h,
    monkeypatch,
    *,
    execution="windowed-success",
    times=("2026-07-17 11:15:00", THROUGH),
    window=None,
    through=THROUGH,
    config=None,
):
    receipt = native._insert_native_success_receipt(
        monkeypatch,
        h["conn"],
        h["dataset"],
        execution_id=execution,
        call_index=0,
        page_offset=0,
        request_window=WINDOW if window is None else window,
        data_through=through,
        finished_at="2026-07-17T03:17:00+00:00",
        config_hash=config,
    )
    for i, t in enumerate(times):
        native._insert_row(
            h["conn"],
            dataset_id=h["dataset"].dataset_id,
            provider="provider-a",
            row_key=f"{execution}-{i}",
            payload={"symbol": f"SYNTHETIC_{i}", "time": t},
            receipt_id=receipt,
        )
    h["conn"].commit()
    evidence = native._proof_evidence((receipt,))
    evidence = replace(
        evidence,
        projection=replace(
            evidence.projection,
            dataset_id=h["dataset"].dataset_id,
            data_through=through,
            observed_at="2026-07-17T03:17:00+00:00",
        ),
        last_success_data_through=through,
    )
    monkeypatch.setattr(
        query_module, "project_dataset_runtime_evidence", lambda *a, **k: evidence
    )
    return receipt


def _query(h, *, proofs=False, time=None, limit=5, cursor=None):
    request = QueryRequest(
        dataset_id=h["dataset"].dataset_id,
        schema_major=1,
        fields=("symbol", "time"),
        filters={} if time is None else {"time": {"eq": time}},
        as_of=None,
        order=("time:asc", "symbol:asc"),
        limit=limit,
        cursor=cursor,
        include_receipt_proofs=proofs,
    )
    return h["service"].execute(
        request, access=h["access"], now=native.NOW, request_id="windowed-minute-test"
    )


def test_windowed_rows_before_max_through_have_true_proofs(window_harness, monkeypatch):
    h = window_harness
    receipt = _seed(h, monkeypatch)
    plain = _query(h)
    proved = _query(h, proofs=True)
    assert proved["data"] == plain["data"]
    assert len(proved["data"]) == 2
    assert {p["receipt_id"] for p in proved["metadata"]["row_receipt_proofs"]} == {
        receipt
    }
    assert all(
        p["data_through"] == THROUGH for p in proved["metadata"]["row_receipt_proofs"]
    )
    page = _query(h, proofs=True, limit=1)
    next_page = _query(h, proofs=True, limit=1, cursor=page["next_cursor"])
    assert page["data"] + next_page["data"] == proved["data"]


def test_exact_earlier_slot_uses_covering_receipt_not_only_max_through(
    window_harness, monkeypatch
):
    h = window_harness
    receipt = _seed(h, monkeypatch)
    result = _query(h, proofs=True, time="2026-07-17 11:15:00")
    assert len(result["data"]) == 1
    assert result["data"][0]["time"] == "2026-07-17 11:15:00"
    assert result["metadata"]["row_receipt_proofs"][0]["receipt_id"] == receipt


@pytest.mark.parametrize(
    "time",
    ["2026-07-16 23:59:59", "2026-07-17 11:17:00", "2026-07-17 12:01:00", "20260717"],
)
def test_windowed_proof_rejects_invalid_event_time(window_harness, monkeypatch, time):
    h = window_harness
    _seed(h, monkeypatch, times=(time,))
    with pytest.raises(QueryServiceUnavailable):
        _query(h, proofs=True)


@pytest.mark.parametrize(
    "window",
    [
        {},
        {"start_time": "2026-07-17 00:00:00"},
        {
            "start_time": "2026-07-17 00:00:00",
            "end_time": "2026-07-17 23:59:59",
            "unknown": "bad",
        },
        {"start_time": "2026-07-17 11:16:00", "end_time": "2026-07-17 23:59:59"},
        {"start_time": "bad", "end_time": "2026-07-17 23:59:59"},
    ],
)
def test_windowed_proof_rejects_missing_malformed_or_uncovering_window(
    window_harness, monkeypatch, window
):
    h = window_harness
    _seed(h, monkeypatch, window=window)
    with pytest.raises(QueryServiceUnavailable):
        _query(h, proofs=True)


def test_exact_slot_rejects_foreign_active_config(window_harness, monkeypatch):
    h = window_harness
    _seed(h, monkeypatch, config="c" * 64)
    with pytest.raises(QueryServiceUnavailable):
        _query(h, proofs=True, time="2026-07-17 11:15:00")


def test_exact_slot_with_no_covering_success_fails_closed(window_harness, monkeypatch):
    h = window_harness
    _seed(h, monkeypatch)
    with pytest.raises(QueryServiceUnavailable):
        _query(h, time="2026-07-17 11:17:00")


def test_windowed_proofs_still_reject_mixed_execution(window_harness, monkeypatch):
    h = window_harness
    _seed(h, monkeypatch, execution="one", times=("2026-07-17 11:15:00",))
    _seed(h, monkeypatch, execution="two", times=(THROUGH,))
    assert len(_query(h)["data"]) == 2
    with pytest.raises(QueryServiceUnavailable):
        _query(h, proofs=True)
