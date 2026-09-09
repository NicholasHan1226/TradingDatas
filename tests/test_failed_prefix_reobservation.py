"""Real SQLite writer recovery keeps the reader's failed-cohort boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType
import sqlite3

import pytest

from dataset_registry import DatasetRegistry
from query_contract import QueryAccessContext, QueryRequest
from query_cursor import SignedCursorCodec
from query_service import QueryService
import query_service as query_module
import storage.ingest_receipts as receipts
import storage.provider_dataset_rows as writer
from storage.receipt_projection import RuntimeProjectionError
from storage.schema import SCHEMA_SQL
from tests.test_provider_native_query import (
    _native_dataset,
    _proof_evidence,
    _synthetic_transport_profile,
    SIGNING_KEY,
)


def _context(dataset, execution, call, variant, config):
    binding = dataset.provider_bindings[0]
    return receipts.IngestContext(
        attempt_id=receipts.make_provider_call_attempt_id(
            execution, call_index=call, retry_index=0
        ),
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window={"trade_date": "20260715"},
        config_hash=config,
        adapter_version=binding.adapter_version,
        started_at="2026-07-17T03:00:00+00:00",
        data_through="20260715",
        request_identity=receipts.ProviderRequestIdentity(
            request_variant={"market": variant},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=0,
            page_index=0,
        ),
    )


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    base = _native_dataset()
    binding = replace(
        base.provider_bindings[0],
        request_variants=(
            MappingProxyType({"market": "E"}),
            MappingProxyType({"market": "O"}),
        ),
    )
    old = replace(
        base,
        point_in_time="append_only",
        provider_bindings=(binding,),
        read_model_adapter=replace(
            base.read_model_adapter, row_key_strategy="payload_hash"
        ),
    )
    current = replace(
        old,
        provider_bindings=(
            replace(binding, request_variants=(MappingProxyType({"market": "E"}),)),
        ),
    )
    path = tmp_path / "facts.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
    monkeypatch.setattr(receipts, "_utc_now", lambda: "2026-07-17T03:01:00+00:00")
    payload = {
        "symbol": "REOBSERVED",
        "trade_date": "20260715",
        "note": "same",
        "big": 1,
    }
    first = writer.ingest_provider_native_rows(
        path,
        dataset=old,
        binding=binding,
        rows=[payload],
        context=_context(old, "original", 0, "E", "a" * 64),
    )
    return path, old, current, payload, first


def _finish(path, old, monkeypatch, status="failed", call=1, retry=0):
    monkeypatch.setattr(receipts, "_utc_now", lambda: "2026-07-17T03:02:00+00:00")
    with sqlite3.connect(path) as conn:
        receipts.insert_ingest_receipt(
            conn,
            context=replace(
                _context(old, "original", call, "O", "a" * 64),
                attempt_id=receipts.make_provider_call_attempt_id(
                    "original", call_index=call, retry_index=retry
                ),
            ),
            target_table=None,
            transaction_index=call,
            status=status,
            counts=receipts.IngestCounts(
                returned=0,
                validated=0,
                inserted=0,
                updated=0,
                unchanged=0,
                rejected=0,
                committed=0,
                count_semantics="terminal_no_data_transaction",
            ),
            errors=("provider_error",) if status == "failed" else (),
            payload_fingerprint="b" * 64,
        )


def _fact(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT * FROM provider_dataset_rows").fetchone()


def _reobserve(recovery, monkeypatch):
    path, _, current, payload, _ = recovery
    monkeypatch.setattr(receipts, "_utc_now", lambda: "2026-07-17T03:04:00+00:00")
    return writer.ingest_provider_native_rows(
        path,
        dataset=current,
        binding=current.provider_bindings[0],
        rows=[payload],
        context=replace(
            _context(current, "new-independent", 0, "E", "c" * 64),
            started_at="2026-07-17T03:03:00+00:00",
        ),
    )


@pytest.mark.parametrize("metadata_drift", [False, True])
def test_real_reobservation_recovers_failed_prefix_and_query_proof(
    recovery, monkeypatch, metadata_drift
):
    path, old, current, payload, first = recovery
    _finish(path, old, monkeypatch)
    if metadata_drift:
        current = replace(current, partition_field=None)
        recovery = path, old, current, payload, first
    before = _fact(path)
    result = _reobserve(recovery, monkeypatch)
    after = _fact(path)
    assert (result.counts.inserted, result.counts.updated, result.counts.unchanged) == (
        0,
        0,
        1,
    )
    assert after[:11] == before[:11]
    assert after[13] == before[13] == 1
    assert after[12] == result.receipt_ids[0] != first.receipt_ids[0]
    assert after[11] == "2026-07-17T03:03:00+00:00"
    # Use the existing synthetic dataset projection, but the actual database,
    # row proof validator and query filtering. No row-proof mock is involved.
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *a, **k: _proof_evidence(result.receipt_ids),
    )
    monkeypatch.setattr(
        query_module, "provider_transport_profile", _synthetic_transport_profile
    )
    monkeypatch.setattr(
        query_module, "provider_ingest_config_hash", lambda *a: "c" * 64
    )
    service = QueryService(
        db_path=path,
        registry=DatasetRegistry((current,)),
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    request = QueryRequest(
        dataset_id=current.dataset_id,
        schema_major=1,
        fields=("symbol", "trade_date"),
        filters={},
        as_of=None,
        order=("symbol:asc",),
        limit=5,
        cursor=None,
        include_receipt_proofs=True,
    )
    response = service.execute(
        request,
        access=QueryAccessContext.from_grants(
            tenant_id="synthetic", scopes=("market_data",), allowed_dataset_ids=()
        ),
        now=datetime(2026, 7, 17, 4, tzinfo=timezone.utc),
        request_id="recovery",
    )
    assert response["data"] == [{"symbol": "REOBSERVED", "trade_date": "20260715"}]
    assert (
        response["metadata"]["row_receipt_proofs"][0]["receipt_id"]
        == result.receipt_ids[0]
    )


@pytest.mark.parametrize("status", ["healthy", "incomplete"])
def test_healthy_or_incomplete_history_does_not_rebind(recovery, monkeypatch, status):
    path, old, *_ = recovery
    if status == "healthy":
        _finish(path, old, monkeypatch, status="empty")
    before = _fact(path)
    _reobserve(recovery, monkeypatch)
    assert _fact(path) == before


@pytest.mark.parametrize("damage", ["missing", "malformed", "call_gap"])
def test_invalid_authority_cannot_authorize_recovery(recovery, monkeypatch, damage):
    path, old, _, _, first = recovery
    _finish(path, old, monkeypatch, call=2 if damage == "call_gap" else 1)
    with sqlite3.connect(path) as conn:
        if damage == "missing":
            conn.execute(
                "DELETE FROM market_ingest_runs WHERE run_id=?", first.receipt_ids
            )
        elif damage == "malformed":
            conn.execute(
                "UPDATE market_ingest_runs SET notes='{' WHERE run_id=?",
                first.receipt_ids,
            )
    before = _fact(path)
    with pytest.raises(RuntimeProjectionError):
        _reobserve(recovery, monkeypatch)
    assert _fact(path) == before


def test_recovery_rolls_back_when_new_receipt_fails(recovery, monkeypatch):
    path, old, *_ = recovery
    _finish(path, old, monkeypatch)
    before = _fact(path)

    def fail(*a, **k):
        raise RuntimeError("injected receipt failure")

    monkeypatch.setattr(writer, "insert_ingest_receipt_with_evidence", fail)
    with pytest.raises(RuntimeError, match="injected"):
        _reobserve(recovery, monkeypatch)
    assert _fact(path) == before


def test_failed_attempt_followed_by_successful_retry_is_not_repair_authority(
    recovery, monkeypatch
):
    path, old, *_ = recovery
    _finish(path, old, monkeypatch)
    _finish(path, old, monkeypatch, status="empty", call=2, retry=1)
    before = _fact(path)
    _reobserve(recovery, monkeypatch)
    assert _fact(path) == before


def test_foreign_provider_receipt_is_not_repair_authority(recovery, monkeypatch):
    path, old, current, payload, first = recovery
    _finish(path, old, monkeypatch)
    # A fact in another registered provider lane cannot borrow this lane's
    # otherwise well-formed failed execution.
    foreign = replace(current.provider_bindings[0], provider="provider-b")
    current = replace(current, provider_bindings=(*current.provider_bindings, foreign))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE provider_dataset_rows SET provider='provider-b'")
    before = _fact(path)
    with pytest.raises(RuntimeProjectionError):
        writer.ingest_provider_native_rows(
            path,
            dataset=current,
            binding=foreign,
            rows=[payload],
            context=replace(
                _context(current, "foreign-reobserve", 0, "E", "c" * 64),
                provider="provider-b",
            ),
        )
    assert _fact(path) == before


@pytest.mark.parametrize("failed_prefix", [False, True])
def test_duplicate_payload_in_one_transaction_uses_verified_identity(
    recovery, monkeypatch, failed_prefix
):
    path, old, current, payload, first = recovery
    if failed_prefix:
        _finish(path, old, monkeypatch)
    else:
        with sqlite3.connect(path) as conn:
            conn.execute("DELETE FROM provider_dataset_rows")
            conn.execute("DELETE FROM market_ingest_runs")
    monkeypatch.setattr(receipts, "_utc_now", lambda: "2026-07-17T03:04:00+00:00")
    result = writer.ingest_provider_native_rows(
        path,
        dataset=current,
        binding=current.provider_bindings[0],
        rows=[payload, payload],
        context=replace(
            _context(current, "duplicate-batch", 0, "E", "c" * 64),
            started_at="2026-07-17T03:03:00+00:00",
        ),
    )
    fact = _fact(path)
    assert result.counts.inserted == (0 if failed_prefix else 1)
    assert result.counts.unchanged == (2 if failed_prefix else 1)
    assert result.counts.updated == 0
    assert fact[12] == result.receipt_ids[0]
    assert fact[13] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_dataset_rows"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM market_ingest_runs WHERE run_id=?", result.receipt_ids
        ).fetchone() == (1,)
