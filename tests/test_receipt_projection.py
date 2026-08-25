from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from typing import Any
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import storage.ingest_receipts as receipt_module
import storage.receipt_projection as projection_module
from dataset_registry import (
    BINANCE_CANARY_REGISTRY_PATH,
    DatasetDefinition,
    DatasetRegistry,
    load_dataset_registry,
)
from provider_ingest_contract import provider_ingest_config_hash
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    ProviderRequestIdentity,
    insert_ingest_receipt,
    make_provider_call_attempt_id,
    make_schedule_plan_attempt_id,
)
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    ReceiptJournalEntry,
    RuntimeProjectionError,
    load_interface_runtime_report,
    project_catalog_runtime,
    project_dataset_runtime,
    project_dataset_runtime_evidence,
    project_registry_runtime,
    validated_receipt_journal_entries,
    validated_row_receipt_proofs,
)
from storage.schema import SCHEMA_SQL


CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64


def _dataset(
    *,
    active: bool = True,
    freshness_sla_seconds: int = 3_600,
    timezone_name: str = "Asia/Shanghai",
    cadence_class: str | None = None,
) -> DatasetDefinition:
    base = load_dataset_registry().resolve("tushare.daily")
    binding = replace(
        base.provider_bindings[0],
        entitlement_state="active",
        activation_state="active" if active else "paused",
    )
    replacements: dict[str, Any] = {
        "provider_bindings": (binding,),
        "freshness_sla_seconds": freshness_sla_seconds,
        "timezone": timezone_name,
    }
    if cadence_class is not None:
        replacements["cadence_class"] = cadence_class
    return replace(base, **replacements)


def _memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _insert_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    status: str,
    attempt_id: str,
    started_at: str,
    finished_at: str,
    data_through: str | None,
    transaction_index: int = 0,
    request_identity: ProviderRequestIdentity | None = None,
    request_window: dict[str, str] | None = None,
    dataset_id: str = "cn.equity.daily",
    provider_api: str = "daily",
    config_hash: str | None = None,
    dataset: DatasetDefinition | None = None,
    commit: bool = True,
) -> str:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    dataset = _dataset() if dataset is None else dataset
    binding = dataset.provider_bindings[0]
    context = IngestContext(
        attempt_id=attempt_id,
        dataset_id=dataset_id,
        provider=binding.provider,
        provider_api=provider_api,
        request_window=request_window or {"trade_date": "20260715"},
        config_hash=(
            provider_ingest_config_hash(dataset, binding)
            if config_hash is None
            else config_hash
        ),
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=data_through,
        request_identity=request_identity or ProviderRequestIdentity.trivial(),
    )
    if status == "success":
        counts = IngestCounts(
            returned=1,
            validated=1,
            inserted=1,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1,
            count_semantics="exact_row_outcomes",
        )
        target_table = "provider_dataset_rows"
        errors: tuple[str, ...] = ()
    else:
        count_semantics = (
            "storage_failure_before_commit"
            if status == "failed"
            else "terminal_no_data_transaction"
        )
        counts = IngestCounts(
            returned=0,
            validated=0,
            inserted=0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=0,
            count_semantics=count_semantics,
        )
        target_table = None
        errors = ("provider_error",) if status == "failed" else ()
    receipt_id = insert_ingest_receipt(
        conn,
        context=context,
        target_table=target_table,
        transaction_index=transaction_index,
        status=status,
        counts=counts,
        errors=errors,
        payload_fingerprint=PAYLOAD_FINGERPRINT,
    )
    if commit:
        conn.commit()
    return receipt_id


def _insert_unmapped_tushare_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    attempt_id: str = (
        "11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222"
    ),
    provider_api: str = "not_registered",
    dataset_id: str | None = None,
    provider: str = "tushare",
    adapter_version: str = "unresolved.v1",
    error: str = "unmapped_dataset",
    count_semantics: str = "terminal_no_data_transaction",
    request_window: dict[str, str] | None = None,
    started_at: str = "2026-07-15T00:10:00+00:00",
    finished_at: str = "2026-07-15T00:11:00+00:00",
    data_through: str = "20260715",
) -> str:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    resolved_dataset_id = dataset_id or (
        "unmapped.tushare."
        + hashlib.sha256(provider_api.encode("utf-8")).hexdigest()[:16]
    )
    context = IngestContext(
        attempt_id=attempt_id,
        dataset_id=resolved_dataset_id,
        provider=provider,
        provider_api=provider_api,
        request_window=request_window
        or {
            "end_date": "20260715",
            "source_name": f"{provider_api}_20260715",
            "start_date": "20260708",
            "tier": "P1_eod_daily",
            "trade_date": "20260715",
        },
        config_hash=CONFIG_HASH,
        adapter_version=adapter_version,
        started_at=started_at,
        data_through=data_through,
    )
    counts = IngestCounts(
        returned=0,
        validated=0,
        inserted=0,
        updated=0,
        unchanged=0,
        rejected=0,
        committed=0,
        count_semantics=count_semantics,
    )
    receipt_id = insert_ingest_receipt(
        conn,
        context=context,
        target_table=None,
        transaction_index=0,
        status="failed",
        counts=counts,
        errors=(error,),
        payload_fingerprint=hashlib.sha256(b"").hexdigest(),
    )
    conn.commit()
    return receipt_id


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _tamper_notes(
    conn: sqlite3.Connection,
    receipt_id: str,
    field: str,
    value: object,
) -> None:
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    if field.startswith("counts."):
        payload["counts"][field.removeprefix("counts.")] = value
    else:
        payload[field] = value
    conn.execute(
        "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
        (_canonical_json(payload), receipt_id),
    )
    conn.commit()


def test_projector_returns_unobserved_without_a_recognized_receipt() -> None:
    conn = _memory_db()
    conn.execute(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-run",
            "2026-07-15T00:00:00+00:00",
            "2026-07-15T00:01:00+00:00",
            "success",
            "cn.equity.daily",
            1,
            1,
            "legacy audit row",
        ),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "unobserved"
    assert projection.degraded is True
    assert projection.data_through is None
    assert projection.observed_at is None
    assert projection.receipt_id is None
    assert projection.reasons == ("no_recognized_receipt",)


def test_projector_labels_valid_superseded_contract_receipts_as_unrecognized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior 5-shard contract must remain denied but leave a precise gap."""

    conn = _memory_db()
    for shard in range(5):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id=f"prior-contract-shard-{shard}",
            started_at="2026-07-15T00:00:00+00:00",
            finished_at="2026-07-15T00:01:00+00:00",
            data_through="20260715",
            config_hash="c" * 64,
        )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "unobserved"
    assert projection.degraded is True
    assert projection.data_through is None
    assert projection.receipt_id is None
    assert projection.reasons == ("active_config_receipt_mismatch",)


def test_validated_receipt_history_is_typed_and_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="history-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    base = load_dataset_registry()
    registry = DatasetRegistry((_dataset(),), query_defaults=base.query_defaults)

    history = projection_module.validated_receipt_history(
        conn,
        registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert len(history) == 1
    entry = history[0]
    assert entry.receipt_id == receipt_id
    assert entry.dataset_id == "cn.equity.daily"
    assert entry.provider == "tushare"
    assert entry.status == "success"
    assert entry.finished_at == datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc)
    assert dict(entry.request_window) == {"trade_date": "20260715"}
    with pytest.raises(FrozenInstanceError):
        entry.status = "failed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        entry.request_window["trade_date"] = "20260716"  # type: ignore[index]


def test_receipt_journal_entries_redact_invalid_counts_and_keep_reason_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="journal-tampered",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    _tamper_notes(conn, receipt_id, "counts.validated", 0)
    base = load_dataset_registry()
    registry = DatasetRegistry((_dataset(),), query_defaults=base.query_defaults)

    entries = validated_receipt_journal_entries(
        conn,
        registry,
        "cn.equity.daily",
        (receipt_id,),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert entries == (
        ReceiptJournalEntry(
            receipt_id=receipt_id,
            status="invalid",
            counts=None,
            error_layer="receipt_validation",
            error_codes=(),
            validation_reasons=("receipt_counts_invalid",),
        ),
    )


def test_receipt_journal_invalid_attempt_context_dominates_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    first = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="shared-attempt",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        request_window={"trade_date": "20260715"},
        request_identity=ProviderRequestIdentity(
            request_variant={"probe": "a"},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        ),
    )
    second = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="shared-attempt",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:02:00+00:00",
        data_through="20260715",
        request_window={"trade_date": "20260716"},
        request_identity=ProviderRequestIdentity(
            request_variant={"probe": "b"},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        ),
    )
    base = load_dataset_registry()
    registry = DatasetRegistry((_dataset(),), query_defaults=base.query_defaults)

    entries = validated_receipt_journal_entries(
        conn,
        registry,
        "cn.equity.daily",
        (first, second),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert len(entries) == 2
    by_id = {entry.receipt_id: entry for entry in entries}
    assert by_id[first].status == "success"
    assert by_id[first].counts is not None
    assert by_id[second].status == "invalid"
    assert by_id[second].counts is None
    assert by_id[second].validation_reasons == ("receipt_attempt_inconsistent",)


def test_receipt_journal_invalid_execution_context_dominates_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    root = "execution-root"
    first = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=root,
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    second = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=make_provider_call_attempt_id(
            root,
            call_index=0,
            retry_index=0,
        ),
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:02:00+00:00",
        data_through="20260715",
    )
    base = load_dataset_registry()
    registry = DatasetRegistry((_dataset(),), query_defaults=base.query_defaults)

    entries = validated_receipt_journal_entries(
        conn,
        registry,
        "cn.equity.daily",
        (first, second),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert len(entries) == 2
    by_id = {entry.receipt_id: entry for entry in entries}
    assert by_id[first].status == "success"
    assert by_id[first].counts is not None
    assert by_id[second].status == "invalid"
    assert by_id[second].counts is None
    assert by_id[second].validation_reasons == ("receipt_execution_inconsistent",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("counts.validated", 0),
        ("counts.count_semantics", "terminal_no_data_transaction"),
        ("errors", ["provider_error"]),
        ("payload_fingerprint", "not-a-sha256"),
    ],
)
def test_validated_receipt_history_rejects_canonical_shaped_tampering(
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=f"history-tampered-{field}",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    _tamper_notes(conn, receipt_id, field, value)
    base = load_dataset_registry()
    registry = DatasetRegistry((_dataset(),), query_defaults=base.query_defaults)

    with pytest.raises(RuntimeProjectionError, match="receipt history"):
        projection_module.validated_receipt_history(
            conn,
            registry,
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def test_dataset_scoped_history_does_not_cross_attest_invalid_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    base = load_dataset_registry()
    valid = _dataset()
    invalid = replace(
        valid,
        dataset_id="cn.equity.daily.other",
        aliases=(),
        provider_bindings=(
            replace(
                valid.provider_bindings[0],
                api_name="daily_other",
                read_discriminator_value="tushare_daily_other",
            ),
        ),
    )
    registry = DatasetRegistry((valid, invalid), query_defaults=base.query_defaults)
    valid_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="history-valid",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    invalid_receipt = _insert_receipt(
        monkeypatch,
        conn,
        dataset=invalid,
        dataset_id=invalid.dataset_id,
        provider_api="daily_other",
        status="success",
        attempt_id="history-invalid",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    _tamper_notes(conn, invalid_receipt, "counts.validated", 0)

    histories = projection_module.validated_receipt_histories_by_dataset(
        conn, registry, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    )

    assert [
        entry.receipt_id for entry in histories.entries_by_dataset[valid.dataset_id]
    ] == [valid_receipt]
    assert set(histories.failures_by_dataset) == {invalid.dataset_id}
    assert histories.failures_by_dataset[invalid.dataset_id]


def test_dataset_scoped_history_keeps_malformed_known_receipt_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed receipt's stored source still isolates its planner failure."""

    conn = _memory_db()
    base = load_dataset_registry()
    valid = _dataset()
    invalid = replace(
        valid,
        dataset_id="cn.equity.daily.other",
        aliases=(),
        provider_bindings=(
            replace(
                valid.provider_bindings[0],
                api_name="daily_other",
                read_discriminator_value="tushare_daily_other",
            ),
        ),
    )
    registry = DatasetRegistry((valid, invalid), query_defaults=base.query_defaults)
    valid_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="malformed-history-valid",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    invalid_receipt = _insert_receipt(
        monkeypatch,
        conn,
        dataset=invalid,
        dataset_id=invalid.dataset_id,
        provider_api="daily_other",
        status="success",
        attempt_id="malformed-history-invalid",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    conn.execute(
        "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
        ("{malformed", invalid_receipt),
    )

    histories = projection_module.validated_receipt_histories_by_dataset(
        conn, registry, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    )

    assert [
        entry.receipt_id for entry in histories.entries_by_dataset[valid.dataset_id]
    ] == [valid_receipt]
    assert set(histories.failures_by_dataset) == {invalid.dataset_id}
    assert histories.failures_by_dataset[invalid.dataset_id] == (
        "receipt_payload_invalid",
    )


def test_dataset_scoped_history_keeps_unknown_receipt_owner_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    base = load_dataset_registry()
    first = _dataset()
    second = replace(
        first,
        dataset_id="cn.equity.daily.other",
        aliases=(),
        provider_bindings=(
            replace(
                first.provider_bindings[0],
                api_name="daily_other",
                read_discriminator_value="tushare_daily_other",
            ),
        ),
    )
    registry = DatasetRegistry((first, second), query_defaults=base.query_defaults)
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="history-unknown-owner",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    conn.execute(
        "UPDATE market_ingest_runs SET source = ? WHERE run_id = ?",
        ("unknown.dataset", receipt_id),
    )
    conn.commit()

    histories = projection_module.validated_receipt_histories_by_dataset(
        conn, registry, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        registry=registry,
    )

    # The unknown-owner row fails neither dataset's history; the tripwire
    # keeps it visible on the global surface instead.  The envelope source was
    # rewritten, so the precise global reason is an envelope mismatch.
    assert histories.failures_by_dataset == {}
    assert [
        (anomaly.receipt_id, anomaly.source, anomaly.reason)
        for anomaly in health.anomalies
    ] == [(receipt_id, "unknown.dataset", "receipt_envelope_mismatch")]


def test_projector_returns_paused_from_registry_activation() -> None:
    conn = _memory_db()

    projection = project_dataset_runtime(
        conn,
        _dataset(active=False),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "paused"
    assert projection.degraded is True
    assert projection.reasons == ("registry_activation_paused",)


@pytest.mark.parametrize(
    ("status", "expected_degraded", "expected_reason"),
    [
        ("success", False, ()),
        ("empty", False, ("provider_returned_no_rows",)),
    ],
)
def test_projector_accepts_recognized_success_and_empty_receipts(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected_degraded: bool,
    expected_reason: tuple[str, ...],
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status=status,
        attempt_id=f"attempt-{status}",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == status
    assert projection.degraded is expected_degraded
    assert projection.data_through == (
        "2026-07-15T08:00:00+08:00" if status == "success" else None
    )
    assert projection.observed_at == "2026-07-15T00:01:00+00:00"
    assert projection.receipt_id == receipt_id
    assert projection.reasons == expected_reason


def test_asof_evidence_excludes_later_receipt_and_binds_internal_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    first_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-asof-first",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:00:00+00:00",
    )
    later_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-asof-later",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through="2026-07-15T00:10:00+00:00",
    )
    dataset = _dataset(timezone_name="UTC")

    current = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
    )
    historical = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
        evidence_as_of=datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc),
    )

    assert current.projection.receipt_id == later_receipt
    assert current.projection.data_through == "2026-07-15T00:10:00+00:00"
    assert current.as_of_success_receipt_ids == ()
    assert historical.projection.state == "success"
    assert historical.projection.receipt_id == first_receipt
    assert historical.projection.data_through == "2026-07-15T00:00:00+00:00"
    assert historical.projection.observed_at == "2026-07-15T00:01:00+00:00"
    assert historical.current_receipt_ids == (first_receipt,)
    assert historical.last_success_receipt_ids == (first_receipt,)
    assert historical.as_of_success_receipt_ids == (first_receipt,)


def test_evidence_projection_replays_from_shared_validation_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second evidence projection over the same rows must not re-validate.

    Long-lived API services share one process-wide memo between the catalog
    and query sides; without it every row query pays the full append-only
    canonicalization cost again (#297). The cache is keyed by row content, so
    a shared dict must yield identical projections with zero direct
    ``_validate_receipt_row`` calls on the replayed scan.
    """

    conn = _memory_db()
    dataset = _dataset()
    first_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-cache-first",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:00:00+00:00",
    )
    later_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-cache-later",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through="2026-07-15T00:10:00+00:00",
    )
    now = datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc)
    validation_cache: dict = {}

    current = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=now,
        validation_cache=validation_cache,
    )
    # Known-source success receipts are pure functions of their row content;
    # both must have been memoized by the first full-history scan.
    assert len(validation_cache) >= 2

    direct_calls = {"count": 0}
    real_validate = projection_module._validate_receipt_row

    def counting_validate(*args: Any, **kwargs: Any) -> Any:
        direct_calls["count"] += 1
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(
        projection_module, "_validate_receipt_row", counting_validate
    )

    replayed = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=now,
        validation_cache=validation_cache,
    )

    assert direct_calls["count"] == 0
    assert replayed.projection.receipt_id == current.projection.receipt_id
    assert replayed.projection.receipt_id == later_receipt
    assert replayed.current_receipt_ids == current.current_receipt_ids


def test_validated_row_receipt_proofs_join_same_execution_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    first = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=make_provider_call_attempt_id("shared-proof-execution", call_index=0, retry_index=0),
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        request_identity=ProviderRequestIdentity(
            request_variant={}, fanout_parameter=None,
            fanout_values=(), page_offset=0, page_index=0,
        ),
        dataset=dataset,
    )
    second = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=make_provider_call_attempt_id("shared-proof-execution", call_index=1, retry_index=0),
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:02:00+00:00",
        data_through="20260715",
        transaction_index=1,
        request_identity=ProviderRequestIdentity(
            request_variant={}, fanout_parameter=None,
            fanout_values=(), page_offset=1, page_index=1,
        ),
        dataset=dataset,
    )
    registry = DatasetRegistry((dataset,), query_defaults=load_dataset_registry().query_defaults)
    now = datetime(2026, 7, 15, 3, tzinfo=timezone.utc)
    first_result = validated_row_receipt_proofs(
        conn, registry, dataset, (first, second), now=now
    )
    second_result = validated_row_receipt_proofs(
        conn, registry, dataset, (second, first), now=now
    )
    assert tuple(first_result) == tuple(sorted((first, second)))
    assert dict(first_result) == dict(second_result)
    assert all(proof.execution_id == "shared-proof-execution" for proof in first_result.values())
    assert all(proof.data_through == "20260715" for proof in first_result.values())
    assert all(len(proof.receipt_proof_sha256) == 64 for proof in first_result.values())


def test_validated_row_receipt_proofs_uses_only_bounded_run_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="bounded-proof",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        dataset=dataset,
    )
    registry = DatasetRegistry((dataset,), query_defaults=load_dataset_registry().query_defaults)

    def fail_global_scan(*args: object, **kwargs: object) -> tuple[object, ...]:
        raise AssertionError("global receipt scan must not be used by row proofs")

    monkeypatch.setattr(projection_module, "_scan_ingest_run_rows", fail_global_scan)
    result = validated_row_receipt_proofs(
        conn,
        registry,
        dataset,
        (receipt_id,),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )
    assert tuple(result) == (receipt_id,)
    assert result[receipt_id].status == "success"


def test_validated_row_receipt_proofs_bounded_ids_survive_large_registry_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row-proof join must not scan 190 datasets of unrelated receipts."""

    conn = _memory_db()
    target = _dataset(timezone_name="UTC")
    base_binding = target.provider_bindings[0]
    unrelated: list[DatasetDefinition] = []
    for index in range(189):
        dataset_id = f"cn.synthetic.unrelated.{index:03d}"
        binding = replace(
            base_binding,
            api_name=f"daily_unrelated_{index:03d}",
            read_discriminator_value=f"daily_unrelated_{index:03d}",
        )
        unrelated.append(
            replace(
                target,
                dataset_id=dataset_id,
                aliases=(f"synthetic.unrelated.{index:03d}",),
                provider_bindings=(binding,),
            )
        )
    registry = DatasetRegistry(
        (target, *unrelated),
        query_defaults=load_dataset_registry().query_defaults,
    )
    selected: list[str] = []
    for page_index in range(6):
        selected.append(
            _insert_receipt(
                monkeypatch,
                conn,
                status="success",
                attempt_id=make_provider_call_attempt_id(
                    "selected-proof-execution", call_index=page_index, retry_index=0
                ),
                started_at="2026-07-15T00:00:00+00:00",
                finished_at=f"2026-07-15T00:0{page_index + 1}:00+00:00",
                data_through="20260715",
                transaction_index=page_index,
                request_identity=ProviderRequestIdentity(
                    request_variant={},
                    fanout_parameter=None,
                    fanout_values=(),
                    page_offset=page_index,
                    page_index=page_index,
                ),
                dataset=target,
                dataset_id=target.dataset_id,
            )
        )
    for receipt_index in range(240):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id=f"target-unselected-{receipt_index:03d}",
            started_at="2026-07-14T00:00:00+00:00",
            finished_at="2026-07-14T00:01:00+00:00",
            data_through="20260714",
            dataset=target,
            dataset_id=target.dataset_id,
            provider_api=target.provider_bindings[0].api_name,
            commit=False,
        )
    for dataset_index, dataset in enumerate(unrelated):
        for receipt_index in range(240):
            _insert_receipt(
                monkeypatch,
                conn,
                status="success",
                attempt_id=f"unrelated-{dataset_index:03d}-{receipt_index:02d}",
                started_at="2026-07-14T00:00:00+00:00",
                finished_at="2026-07-14T00:01:00+00:00",
                data_through="20260714",
                dataset=dataset,
                dataset_id=dataset.dataset_id,
                provider_api=dataset.provider_bindings[0].api_name,
                commit=False,
            )
    conn.commit()
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)

    # Use an explicit bounded budget so the unbounded scan is interrupted while
    # the bounded row-proof join stays within budget, independent of the
    # registry's default progress budget.
    budget = 1_000_000

    def with_unchanged_budget(call):
        steps = 0

        def interrupt_at_budget() -> int:
            nonlocal steps
            steps += 1_000
            return int(steps > budget)

        conn.set_progress_handler(interrupt_at_budget, 1_000)
        try:
            return call()
        finally:
            conn.set_progress_handler(None, 0)

    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        with_unchanged_budget(lambda: projection_module._scan_ingest_run_rows(conn))

    first_five = with_unchanged_budget(
        lambda: validated_row_receipt_proofs(
            conn, registry, target, tuple(selected[:5]), now=now
        )
    )
    all_six = with_unchanged_budget(
        lambda: validated_row_receipt_proofs(
            conn, registry, target, tuple(selected), now=now
        )
    )

    assert tuple(first_five) == tuple(sorted(selected[:5]))
    assert tuple(all_six) == tuple(sorted(selected))
    assert all(proof.execution_id == "selected-proof-execution" for proof in all_six.values())


def test_validated_row_receipt_proofs_fail_closed_for_missing_or_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    failed_id = _insert_receipt(
        monkeypatch, conn, status="failed", attempt_id="failed-proof",
        started_at="2026-07-15T00:00:00+00:00", finished_at="2026-07-15T00:01:00+00:00",
        data_through=None, dataset=dataset,
    )
    registry = DatasetRegistry((dataset,), query_defaults=load_dataset_registry().query_defaults)
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    for bad_ids in ((failed_id,), ("missing-receipt",)):
        with pytest.raises(RuntimeProjectionError):
            validated_row_receipt_proofs(conn, registry, dataset, bad_ids, now=now)


def test_validated_row_receipt_proofs_fail_closed_for_malformed_selected_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="malformed-selected-proof",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        dataset=dataset,
    )
    conn.execute(
        "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
        ("{\"malformed\":", receipt_id),
    )
    conn.commit()
    registry = DatasetRegistry((dataset,), query_defaults=load_dataset_registry().query_defaults)
    with pytest.raises(RuntimeProjectionError):
        validated_row_receipt_proofs(
            conn,
            registry,
            dataset,
            (receipt_id,),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def test_validated_row_receipt_proofs_reject_wrong_dataset_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="wrong-dataset-proof",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        dataset=dataset,
    )
    registry = DatasetRegistry((dataset,), query_defaults=load_dataset_registry().query_defaults)
    wrong_dataset = replace(dataset, dataset_id="cn.equity.other")
    with pytest.raises(RuntimeProjectionError):
        validated_row_receipt_proofs(
            conn,
            registry,
            wrong_dataset,
            (receipt_id,),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )
    wrong_provider_dataset = replace(
        dataset,
        provider_bindings=(replace(dataset.provider_bindings[0], provider="other-provider"),),
    )
    with pytest.raises(RuntimeProjectionError):
        validated_row_receipt_proofs(
            conn,
            registry,
            wrong_provider_dataset,
            (receipt_id,),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )
    other_dataset = replace(
        dataset,
        dataset_id="cn.equity.other",
        aliases=("tushare.other",),
        provider_bindings=(
            replace(
                dataset.provider_bindings[0],
                api_name="daily.other",
                read_discriminator_value="daily.other",
            ),
        ),
    )
    registry_with_other = DatasetRegistry(
        (dataset, other_dataset),
        query_defaults=load_dataset_registry().query_defaults,
    )
    other_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="wrong-dataset-receipt",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        dataset=other_dataset,
        dataset_id=other_dataset.dataset_id,
        commit=True,
    )
    with pytest.raises(RuntimeProjectionError):
        validated_row_receipt_proofs(
            conn,
            registry_with_other,
            dataset,
            (other_receipt_id,),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        validated_row_receipt_proofs(conn, registry, dataset, (), now=now)
    with pytest.raises(ValueError):
        validated_row_receipt_proofs(conn, registry, dataset, (receipt_id, receipt_id), now=now)
    over_bound = tuple(f"receipt-{index}" for index in range(registry.query_defaults.max_page_size + 1))
    with pytest.raises(ValueError):
        validated_row_receipt_proofs(conn, registry, dataset, over_bound, now=now)


def test_asof_receipt_collection_window_bounds_more_than_2000_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset(timezone_name="UTC")
    for index in range(2_001):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id=f"attempt-asof-old-{index}",
            started_at="2026-07-14T23:00:00+00:00",
            finished_at="2026-07-14T23:01:00+00:00",
            data_through="2026-07-14T23:00:00+00:00",
            dataset=dataset,
            commit=False,
        )
    conn.commit()
    relevant_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-asof-window-relevant",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through="2026-07-15T00:10:00+00:00",
        dataset=dataset,
    )

    evidence = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
        evidence_as_of=datetime(2026, 7, 15, 0, 15, tzinfo=timezone.utc),
        receipt_collection_window=(
            datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 0, 15, tzinfo=timezone.utc),
        ),
    )

    assert evidence.as_of_success_receipt_ids == (relevant_receipt,)


def test_asof_window_accepts_partition_declaration_predecessor_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    registry = load_dataset_registry(BINANCE_CANARY_REGISTRY_PATH)
    dataset = registry.resolve("crypto.spot.binance.btcusdt.5m")
    binding = dataset.provider_bindings[0]
    predecessor = replace(dataset, partition_field=None)
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-asof-active-before-predecessor",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-14T23:59:59.999+00:00",
        dataset_id=dataset.dataset_id,
        provider_api=binding.api_name,
        request_window={
            "start_open_time": "2026-07-14T23:50:00Z",
            "end_open_time": "2026-07-14T23:55:00Z",
        },
        config_hash=provider_ingest_config_hash(predecessor, binding),
        dataset=predecessor,
    )
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-asof-partition-predecessor",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through="2026-07-15T00:09:59.999+00:00",
        dataset_id=dataset.dataset_id,
        provider_api=binding.api_name,
        request_window={
            "start_open_time": "2026-07-15T00:00:00Z",
            "end_open_time": "2026-07-15T00:05:00Z",
        },
        config_hash=provider_ingest_config_hash(predecessor, binding),
        dataset=dataset,
    )

    evidence = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
        evidence_as_of=datetime(2026, 7, 15, 0, 15, tzinfo=timezone.utc),
        receipt_collection_window=(
            datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 0, 15, tzinfo=timezone.utc),
        ),
    )

    assert evidence.projection.state == "success"
    assert evidence.projection.reasons == ()
    assert evidence.current_provider_config_hashes == (
        (binding.provider, provider_ingest_config_hash(predecessor, binding)),
    )
    assert evidence.as_of_success_receipt_ids == (receipt_id,)

    session_minute = replace(
        dataset,
        cadence_class="session_minute",
        freshness_sla_seconds=600,
    )
    current = project_dataset_runtime_evidence(
        conn,
        session_minute,
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
    )
    assert current.projection.state == "stale"
    assert current.current_provider_config_hashes == (
        (binding.provider, provider_ingest_config_hash(dataset, binding)),
    )


def test_asof_evidence_does_not_treat_collection_time_backfill_as_historical_pit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-collection-time-backfill",
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:01:00+00:00",
        data_through="2026-07-01T00:00:00+00:00",
    )
    dataset = _dataset(
        freshness_sla_seconds=60 * 60 * 24 * 30,
        timezone_name="UTC",
    )

    historical = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 20, 0, 5, tzinfo=timezone.utc),
        evidence_as_of=datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc),
    )
    current = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=datetime(2026, 7, 20, 0, 5, tzinfo=timezone.utc),
    )

    assert historical.projection.state == "unobserved"
    assert historical.projection.receipt_id is None
    assert historical.as_of_success_receipt_ids == ()
    assert current.projection.receipt_id == receipt_id
    assert current.projection.observed_at == "2026-07-20T00:01:00+00:00"


def test_projector_round_trips_complete_cursor_v2_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    identity = ProviderRequestIdentity(
        request_variant={}, fanout_parameter="ts_code",
        fanout_values=("000001.SZ",), page_offset=None, page_index=0,
        cursor_contract_version=2, frozen_universe_sha256="a" * 64,
        batch_index=0, batch_count=2, batch_values_sha256="b" * 64,
    )
    receipt_id = _insert_receipt(
        monkeypatch, conn, status="success", attempt_id="cursor-roundtrip",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00", request_identity=identity,
    )
    base = load_dataset_registry()
    histories = projection_module.validated_receipt_histories_by_dataset(
        conn, DatasetRegistry((_dataset(),), query_defaults=base.query_defaults),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )
    entry = histories.entries_by_dataset["cn.equity.daily"][0]
    assert entry.receipt_id == receipt_id
    assert entry.cursor_contract_version == 2
    assert entry.frozen_universe_sha256 == "a" * 64
    assert (entry.batch_index, entry.batch_count) == (0, 2)
    assert entry.batch_values_sha256 == "b" * 64


@pytest.mark.parametrize(
    "extra",
    [
        {"cursor_contract_version": 2},
        {
            "cursor_contract_version": 1,
            "frozen_universe_sha256": "a" * 64,
            "batch_index": 0,
            "batch_count": 1,
            "batch_values_sha256": "b" * 64,
        },
    ],
)
def test_projector_rejects_incomplete_or_malformed_cursor_identity(extra) -> None:
    raw = {
        "request_variant": {},
        "fanout_parameter": "ts_code",
        "fanout_values": ["000001.SZ"],
        "page_offset": None,
        "page_index": 0,
    }
    raw.update(extra)
    with pytest.raises(ValueError, match="receipt_request_identity_invalid"):
        projection_module._validate_request_identity({"request_identity": raw})


def test_projector_binds_complete_singular_provider_request_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    request_identity = ProviderRequestIdentity(
        request_variant={},
        fanout_parameter="ts_code",
        fanout_values=("000001.SZ",),
        page_offset=100,
        page_index=1,
    )
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-singular-provider-call",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
        request_identity=request_identity,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.receipt_id == receipt_id


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    [
        (
            lambda payload: payload["request_identity"].__setitem__("page_index", 2),
            "receipt_identity_mismatch",
        ),
        (
            lambda payload: payload["request_identity"].__setitem__(
                "fanout_values", "000001.SZ"
            ),
            "receipt_request_identity_invalid",
        ),
        (
            lambda payload: payload.__setitem__(
                "requests", [payload["request_identity"]]
            ),
            "receipt_payload_invalid",
        ),
    ],
)
def test_projector_rejects_tampered_or_aggregate_request_identity(
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    expected_reason: str,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=f"attempt-request-identity-{expected_reason}",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
        request_identity=ProviderRequestIdentity(
            request_variant={"adjustment": "qfq"},
            fanout_parameter="ts_code",
            fanout_values=("000001.SZ",),
            page_offset=0,
            page_index=0,
        ),
    )
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    mutate(payload)
    conn.execute(
        "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
        (_canonical_json(payload), receipt_id),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.receipt_id == receipt_id
    assert projection.reasons == (expected_reason,)


def test_terminal_failure_overrides_higher_index_success_chunks_in_same_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    for transaction_index, finished_at in (
        (0, "2026-07-15T00:01:00+00:00"),
        (1, "2026-07-15T00:02:00+00:00"),
    ):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id="attempt-partial-then-failed",
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=finished_at,
            data_through="2026-07-15T08:00:00+08:00",
            transaction_index=transaction_index,
        )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-partial-then-failed",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through=None,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through is None
    assert projection.observed_at == "2026-07-15T00:03:00+00:00"
    assert projection.receipt_id == failed_receipt_id
    assert projection.reasons == ("provider_error",)


def test_same_attempt_cannot_split_on_started_at_to_hide_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-split",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:12:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-split",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
        transaction_index=1,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == failed_receipt_id
    assert projection.reasons == ("receipt_attempt_inconsistent",)


def test_same_attempt_requires_one_config_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    first_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-context",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    second_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-context",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:02:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
        transaction_index=1,
    )
    _tamper_notes(conn, second_receipt_id, "config_hash", "c" * 64)

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id in {first_receipt_id, second_receipt_id}
    assert projection.reasons == ("receipt_attempt_inconsistent",)


def test_latest_failed_receipt_degrades_but_preserves_last_success_data_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through=None,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.observed_at == "2026-07-15T01:01:00+00:00"
    assert projection.receipt_id == failed_receipt_id
    assert projection.reasons == ("provider_error",)


def test_later_backfill_success_cannot_regress_dataset_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    current_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-current-partition",
        started_at="2026-07-20T08:00:00+00:00",
        finished_at="2026-07-20T08:01:00+00:00",
        data_through="20260720",
        request_window={"trade_date": "20260720"},
    )
    backfill_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-older-backfill",
        started_at="2026-07-20T08:10:00+00:00",
        finished_at="2026-07-20T08:11:00+00:00",
        data_through="20260701",
        request_window={"trade_date": "20260701"},
    )

    evidence = project_dataset_runtime_evidence(
        conn,
        _dataset(freshness_sla_seconds=86_400),
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )

    assert evidence.projection.state == "success"
    assert evidence.projection.data_through == "20260720"
    assert evidence.projection.receipt_id == backfill_receipt_id
    assert evidence.projection.observed_at == "2026-07-20T08:11:00+00:00"
    assert evidence.last_success_receipt_id == current_receipt_id
    assert evidence.last_success_data_through == "20260720"


def test_scheduler_run_uses_max_target_window_for_current_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    run_root = "11111111-1111-4111-8111-111111111111"
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=make_schedule_plan_attempt_id(run_root, plan_index=1),
        started_at="2026-07-20T08:00:00+00:00",
        finished_at="2026-07-20T08:02:00+00:00",
        data_through="20260701",
        request_window={"trade_date": "20260701"},
    )
    current_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id=make_schedule_plan_attempt_id(run_root, plan_index=0),
        started_at="2026-07-20T08:00:00+00:00",
        finished_at="2026-07-20T08:01:00+00:00",
        data_through=None,
        request_window={"trade_date": "20260720"},
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(freshness_sla_seconds=30 * 86_400),
        now=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )

    assert projection.state == "empty"
    assert projection.degraded is False
    assert projection.data_through == "20260701"
    assert projection.receipt_id == current_receipt_id
    assert projection.reasons == ("provider_returned_no_rows",)


def test_unassignable_malformed_receipt_like_row_reported_globally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    success_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through=None,
    )
    conn.execute(
        "UPDATE market_ingest_runs SET source = ?, notes = ? WHERE run_id = ?",
        ("ghost.dataset", "{malformed", failed_receipt_id),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    # A malformed receipt-like row from an unknown source is inert for the
    # dataset's own projection and reported by the global tripwire instead.
    assert projection.state == "stale"
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.receipt_id == success_receipt_id
    assert projection.reasons == ("freshness_sla_exceeded",)
    assert [
        (anomaly.receipt_id, anomaly.source, anomaly.reason)
        for anomaly in health.anomalies
    ] == [(failed_receipt_id, "ghost.dataset", "receipt_payload_invalid")]


def test_jointly_tampered_unknown_dataset_reported_globally_not_per_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receipt stolen to a ghost dataset no longer fails every dataset.

    Proposal A narrows the tamper tripwire blast radius: the stolen row is
    inert for per-dataset projections but must remain globally visible via
    ``project_unattributed_receipts`` so tampering cannot escape notice.
    """
    conn = _memory_db()
    success_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through=None,
    )
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (failed_receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    payload["dataset_id"] = "ghost.dataset"
    conn.execute(
        "UPDATE market_ingest_runs SET source = ?, notes = ? WHERE run_id = ?",
        ("ghost.dataset", _canonical_json(payload), failed_receipt_id),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    assert projection.state == "stale"
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.receipt_id == success_receipt_id
    assert projection.reasons == ("freshness_sla_exceeded",)
    assert [
        (anomaly.receipt_id, anomaly.source, anomaly.reason)
        for anomaly in health.anomalies
    ] == [(failed_receipt_id, "ghost.dataset", "receipt_dataset_unknown")]


def test_valid_unmapped_tushare_attempt_does_not_poison_registered_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    success_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _insert_unmapped_tushare_receipt(monkeypatch, conn)

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.receipt_id == success_receipt_id
    assert projection.reasons == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset_id": "unmapped.tushare.0000000000000000"},
        {"provider": "other-provider"},
        {"adapter_version": "other-adapter.v1"},
        {"error": "provider_error"},
        {"count_semantics": "storage_failure_before_commit"},
        {"request_window": {"trade_date": "20260715"}},
        {"attempt_id": "not-a-collector-attempt"},
        {"data_through": "20300101"},
        {
            "started_at": "2030-01-01T00:10:00+00:00",
            "finished_at": "2030-01-01T00:11:00+00:00",
            "data_through": "20300101",
            "request_window": {
                "end_date": "20300101",
                "source_name": "not_registered_20300101",
                "start_date": "20291225",
                "tier": "P1_eod_daily",
                "trade_date": "20300101",
            },
        },
    ],
)
def test_tombstone_like_unknown_receipt_reported_as_global_anomaly(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    conn = _memory_db()
    success_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    tombstone_receipt_id = _insert_unmapped_tushare_receipt(
        monkeypatch,
        conn,
        **overrides,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    # Per-dataset projection stays accurate; the invalid tombstone variant is
    # surfaced globally instead of failing the dataset.
    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.receipt_id == success_receipt_id
    assert projection.reasons == ()
    assert [
        (anomaly.receipt_id, anomaly.reason) for anomaly in health.anomalies
    ] == [(tombstone_receipt_id, "receipt_dataset_unknown")]


def test_historical_unmapped_tombstone_stays_isolated_after_api_onboarding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    success_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _insert_unmapped_tushare_receipt(
        monkeypatch,
        conn,
        provider_api="daily",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.receipt_id == success_receipt_id


@pytest.mark.parametrize(
    ("payload_variant", "expected_reason"),
    [
        ("current_schema", "receipt_dataset_unknown"),
        ("schema_removed", "unknown_receipt_schema"),
        ("malformed_json", "receipt_payload_invalid"),
    ],
)
def test_run_id_and_source_tampering_cannot_escape_receipt_scan(
    monkeypatch: pytest.MonkeyPatch,
    payload_variant: str,
    expected_reason: str,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through=None,
    )
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (failed_receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    payload["dataset_id"] = "ghost.dataset"
    payload["receipt_id"] = "tampered-no-prefix"
    if payload_variant == "schema_removed":
        payload.pop("schema_version")
    tampered_notes = (
        "{malformed"
        if payload_variant == "malformed_json"
        else _canonical_json(payload)
    )
    conn.execute(
        """UPDATE market_ingest_runs
           SET run_id = ?, source = ?, notes = ?
           WHERE run_id = ?""",
        (
            "tampered-no-prefix",
            "ghost.dataset",
            tampered_notes,
            failed_receipt_id,
        ),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    # Tampering cannot escape: the row leaves the dataset's projection alone
    # but is reported globally under the same reason vocabulary.
    assert projection.state == "stale"
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.reasons == ("freshness_sla_exceeded",)
    assert [
        (anomaly.receipt_id, anomaly.source, anomaly.reason)
        for anomaly in health.anomalies
    ] == [("tampered-no-prefix", "ghost.dataset", expected_reason)]


def test_uppercase_receipt_marker_with_plain_notes_cannot_hide_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    failed_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through=None,
    )
    uppercase_receipt_id = failed_receipt_id.upper()
    conn.execute(
        """UPDATE market_ingest_runs
           SET run_id = ?, notes = ?
           WHERE run_id = ?""",
        (uppercase_receipt_id, "tampered receipt payload", failed_receipt_id),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.receipt_id == uppercase_receipt_id
    assert projection.reasons == ("receipt_payload_invalid",)


def test_receipt_scan_row_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    conn.executemany(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"legacy-run-{index}",
                "2026-07-15T00:00:00+00:00",
                "2026-07-15T00:01:00+00:00",
                "success",
                "legacy:provider",
                1,
                1,
                "legacy audit row",
            )
            for index in range(3)
        ],
    )
    conn.commit()
    monkeypatch.setattr(
        projection_module,
        "_MAX_INGEST_RUN_SCAN_ROWS",
        2,
        raising=False,
    )

    with pytest.raises(RuntimeProjectionError, match="row budget exceeded"):
        project_dataset_runtime(
            conn,
            _dataset(),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def test_registry_projection_scans_ingest_runs_once_with_a_hard_limit() -> None:
    conn = _memory_db()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    project_registry_runtime(
        conn,
        load_dataset_registry(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    receipt_scans = [
        statement for statement in statements if "FROM market_ingest_runs" in statement
    ]
    assert len(receipt_scans) == 1
    assert "WHERE source" not in receipt_scans[0]
    assert "run_id LIKE" not in receipt_scans[0]
    assert "ROW_NUMBER() OVER" in receipt_scans[0]
    assert "rn <=" in receipt_scans[0]


def test_registry_projection_classifies_each_ingest_row_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    conn.executemany(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"legacy-run-{index}",
                "2026-07-15T00:00:00+00:00",
                "2026-07-15T00:01:00+00:00",
                "success",
                "legacy:provider",
                1,
                1,
                _canonical_json({"legacy": index}),
            )
            for index in range(3)
        ],
    )
    conn.commit()
    original_loads = projection_module.json.loads
    calls = 0

    def counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(projection_module.json, "loads", counted_loads)

    project_registry_runtime(
        conn,
        load_dataset_registry(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert calls == 3


def test_recent_ingest_run_scan_returns_bounded_per_dataset_window() -> None:
    conn = _memory_db()
    source = "cn.equity.daily"
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    conn.executemany(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"recent-run-{index:03d}",
                (base + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                (base + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
                "success",
                source,
                1,
                1,
                _canonical_json({"legacy": index}),
            )
            for index in range(105)
        ],
    )
    conn.commit()

    scanned = projection_module._scan_recent_ingest_run_rows(
        conn,
        per_dataset_limit=100,
    )

    assert len(scanned) == 100
    assert {row.raw[9] for row in scanned} == {source}
    assert scanned[0].raw[1] == "recent-run-104"
    assert scanned[-1].raw[1] == "recent-run-005"


def test_recent_ingest_run_scan_fails_closed_on_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    monkeypatch.setattr(
        projection_module,
        "_MAX_INGEST_RUN_SCAN_ROWS",
        3,
        raising=False,
    )
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    rows: list[tuple[object, ...]] = []
    for source_index in range(3):
        source = f"cn.equity.daily.{source_index}"
        for index in range(2):
            finished = (base + timedelta(minutes=index)).isoformat().replace(
                "+00:00", "Z"
            )
            rows.append(
                (
                    f"run-{source_index}-{index}",
                    finished,
                    finished,
                    "success",
                    source,
                    1,
                    1,
                    _canonical_json({"legacy": index}),
                )
            )
    conn.executemany(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    with pytest.raises(RuntimeProjectionError, match="row budget exceeded"):
        projection_module._scan_recent_ingest_run_rows(
            conn,
            per_dataset_limit=2,
        )


def test_catalog_projection_survives_full_scan_budget_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog projection must not fail closed on the old full-table scan budget."""

    conn = _memory_db()
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="catalog-survives-budget",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)

    def fail_global_scan(*args: object, **kwargs: object) -> tuple[object, ...]:
        raise RuntimeProjectionError("receipt scan row budget exceeded")

    monkeypatch.setattr(projection_module, "_scan_ingest_run_rows", fail_global_scan)

    catalog = project_catalog_runtime(conn, registry, now=now)
    assert catalog["datasets"][dataset.dataset_id]["state"] == "success"


def test_catalog_projection_recent_scan_preserves_dataset_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-dataset recent receipts keep dataset and interface projections intact."""

    conn = _memory_db()
    base = _dataset()
    success = base
    failed_binding = replace(
        base.provider_bindings[0],
        api_name="daily_failed",
        read_discriminator_value="daily_failed",
    )
    failed = replace(
        base,
        dataset_id="cn.equity.daily.failed",
        aliases=("daily.failed",),
        provider_bindings=(failed_binding,),
    )
    registry = DatasetRegistry((success, failed))

    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="recent-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
        dataset=success,
        dataset_id=success.dataset_id,
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="recent-failed",
        started_at="2026-07-15T00:02:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through=None,
        dataset=failed,
        dataset_id=failed.dataset_id,
        provider_api="daily_failed",
    )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)

    catalog = project_catalog_runtime(conn, registry, now=now)
    assert catalog["datasets"][success.dataset_id]["state"] == "success"
    assert catalog["datasets"][failed.dataset_id]["state"] == "failed"

    full = project_registry_runtime(conn, registry, now=now)
    assert full["interfaces"]["daily"]["state"] == "success"
    assert full["interfaces"]["daily_failed"]["state"] == "failed"


def test_catalog_projection_matches_dataset_rows_without_binding_reprojection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset()
    binding = dataset.provider_bindings[0]
    alternate = replace(
        binding,
        provider="alternate",
        api_name="daily_alt",
        read_discriminator_value="alternate_daily",
    )
    registry = DatasetRegistry(
        (replace(dataset, provider_bindings=(binding, alternate)),)
    )
    calls: list[object] = []
    original = projection_module._project_dataset_runtime

    def counted(*args: object, **kwargs: object):
        calls.append(kwargs.get("expected_binding"))
        return original(*args, **kwargs)

    monkeypatch.setattr(projection_module, "_project_dataset_runtime", counted)
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)

    catalog = project_catalog_runtime(conn, registry, now=now)
    full = project_registry_runtime(conn, registry, now=now)

    assert catalog == {"datasets": full["datasets"]}
    assert calls.count(None) == 2
    assert calls.count(binding) == 1
    assert calls.count(alternate) == 1


def test_catalog_projection_validates_only_rows_related_to_each_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    base = load_dataset_registry()
    first = _dataset()
    second = replace(
        first,
        dataset_id="cn.equity.daily.other",
        aliases=(),
        provider_bindings=(
            replace(
                first.provider_bindings[0],
                api_name="daily_other",
                read_discriminator_value="tushare_daily_other",
            ),
        ),
    )
    registry = DatasetRegistry((first, second), query_defaults=base.query_defaults)
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="catalog-related-first",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    _insert_receipt(
        monkeypatch,
        conn,
        dataset=second,
        dataset_id=second.dataset_id,
        provider_api="daily_other",
        status="success",
        attempt_id="catalog-related-second",
        started_at="2026-07-15T00:02:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through="20260715",
    )
    calls: list[tuple[str, object]] = []
    original = projection_module._validate_receipt_row_memoized

    def counted(scanned: Any, dataset: DatasetDefinition, *args: object) -> object:
        calls.append((dataset.dataset_id, scanned.raw[9]))
        return original(scanned, dataset, *args)

    monkeypatch.setattr(
        projection_module,
        "_validate_receipt_row_memoized",
        counted,
    )

    report = project_catalog_runtime(
        conn,
        registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert report["datasets"][first.dataset_id]["state"] == "success"
    assert report["datasets"][second.dataset_id]["state"] == "success"
    assert calls == [
        (first.dataset_id, first.dataset_id),
        (second.dataset_id, second.dataset_id),
    ]


def test_catalog_projection_keeps_cross_dataset_envelope_mismatch_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    base = load_dataset_registry()
    first = _dataset()
    second = replace(
        first,
        dataset_id="cn.equity.daily.other",
        aliases=(),
        provider_bindings=(
            replace(
                first.provider_bindings[0],
                api_name="daily_other",
                read_discriminator_value="tushare_daily_other",
            ),
        ),
    )
    registry = DatasetRegistry((first, second), query_defaults=base.query_defaults)
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="catalog-cross-envelope",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    conn.execute(
        "UPDATE market_ingest_runs SET source = ? WHERE run_id = ?",
        (second.dataset_id, receipt_id),
    )
    conn.commit()

    report = project_catalog_runtime(
        conn,
        registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert report["datasets"][first.dataset_id]["state"] == "failed"
    assert report["datasets"][second.dataset_id]["state"] == "failed"
    assert report["datasets"][first.dataset_id]["reasons"] == [
        "receipt_envelope_mismatch"
    ]
    assert report["datasets"][second.dataset_id]["reasons"] == [
        "receipt_envelope_mismatch"
    ]


def test_catalog_projection_memoizes_own_dataset_receipt_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared cache revalidates only receipts written since the prior call."""

    conn = _memory_db()
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="memoized-validation-1",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    cache: dict = {}
    calls = 0
    original = projection_module._validate_receipt_row

    def counted(*args: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(projection_module, "_validate_receipt_row", counted)

    first = project_catalog_runtime(conn, registry, now=now, validation_cache=cache)
    assert calls == 1
    second = project_catalog_runtime(conn, registry, now=now, validation_cache=cache)
    assert calls == 1
    assert first == second

    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="memoized-validation-2",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through="20260715",
    )
    later = datetime(2026, 7, 15, 2, tzinfo=timezone.utc)
    third = project_catalog_runtime(conn, registry, now=later, validation_cache=cache)
    assert calls == 2
    assert third["datasets"][dataset.dataset_id]["observed_at"] != (
        first["datasets"][dataset.dataset_id]["observed_at"]
    )


def test_catalog_projection_memoized_cache_revalidates_rewritten_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache key binds row content, so a recycled run_id is revalidated."""

    conn = _memory_db()
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="memoized-rewrite-1",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    cache: dict = {}
    calls = 0
    original = projection_module._validate_receipt_row

    def counted(*args: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(projection_module, "_validate_receipt_row", counted)

    first = project_catalog_runtime(conn, registry, now=now, validation_cache=cache)
    assert calls == 1
    assert first["datasets"][dataset.dataset_id]["state"] == "success"

    _tamper_notes(conn, receipt_id, "status", "failed")
    second = project_catalog_runtime(conn, registry, now=now, validation_cache=cache)
    assert calls == 2
    assert second["datasets"][dataset.dataset_id]["state"] != "success"


def test_catalog_projection_without_cache_keeps_direct_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers without a cache keep the per-request validation behavior."""

    conn = _memory_db()
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="uncached-validation-1",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    calls = 0
    original = projection_module._validate_receipt_row

    def counted(*args: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(projection_module, "_validate_receipt_row", counted)

    first = project_catalog_runtime(conn, registry, now=now)
    second = project_catalog_runtime(conn, registry, now=now)
    assert calls == 2
    assert first == second


def test_interface_projection_is_scoped_to_its_provider_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = _dataset()
    tushare_binding = dataset.provider_bindings[0]
    alternate_binding = replace(
        tushare_binding,
        provider="alternate",
        api_name="daily_alt",
        read_discriminator_value="alternate_daily",
    )
    registry = DatasetRegistry(
        (replace(dataset, provider_bindings=(tushare_binding, alternate_binding)),)
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-tushare-only",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )

    report = project_registry_runtime(
        conn,
        registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert report["interfaces"]["daily"]["state"] == "success"
    assert report["interfaces"]["alternate:daily_alt"]["state"] == "unobserved"
    assert report["interfaces"]["alternate:daily_alt"]["receipt_id"] is None


def test_file_projection_rejects_ingest_schema_without_primary_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing-primary-key.sqlite"
    (tmp_path / f".{db_path.name}.tradingdatas.lock").touch()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE market_ingest_runs (
               run_id TEXT,
               started_at TEXT,
               finished_at TEXT,
               status TEXT,
               source TEXT,
               rows_read INTEGER,
               rows_written INTEGER,
               notes TEXT
           )"""
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeProjectionError, match="schema"):
        load_interface_runtime_report(
            db_path,
            load_dataset_registry(),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def test_file_projection_rejects_hidden_generated_ingest_column(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "hidden-column.sqlite"
    (tmp_path / f".{db_path.name}.tradingdatas.lock").touch()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "ALTER TABLE market_ingest_runs ADD COLUMN hidden_copy TEXT "
        "GENERATED ALWAYS AS (run_id) VIRTUAL"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeProjectionError, match="schema"):
        load_interface_runtime_report(
            db_path,
            load_dataset_registry(),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def test_file_projection_rejects_legacy_or_business_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-table.sqlite"
    (tmp_path / f".{db_path.name}.tradingdatas.lock").touch()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute("CREATE TABLE market_bars_daily (symbol TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeProjectionError, match="schema"):
        load_interface_runtime_report(
            db_path,
            load_dataset_registry(),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )


def _exclusive_lock_available(path: Path) -> bool:
    script = (
        "import fcntl,os,sys; "
        "fd=os.open(sys.argv[1], os.O_RDWR); "
        "\ntry:\n fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n os.close(fd); sys.exit(1)\n"
        "fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)"
    )
    return (
        subprocess.run(
            [sys.executable, "-c", script, str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def test_large_projection_holds_one_shared_authority_lock_until_read_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    authority_lock = tmp_path / f".{db_path.name}.tradingdatas.lock"
    authority_lock.touch()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    projection_started = threading.Event()
    release_projection = threading.Event()
    calls = 0
    expected_report = {"status": "green", "datasets": {}}

    def slow_projection(*_args, **_kwargs) -> dict[str, object]:
        nonlocal calls
        calls += 1
        projection_started.set()
        assert release_projection.wait(timeout=5)
        return expected_report

    monkeypatch.setattr(
        projection_module,
        "project_registry_runtime",
        slow_projection,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            load_interface_runtime_report,
            db_path,
            DatasetRegistry(()),
            now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
        )
        assert projection_started.wait(timeout=5)
        try:
            assert _exclusive_lock_available(authority_lock) is False
        finally:
            release_projection.set()
        assert future.result(timeout=5) == expected_report

    assert calls == 1
    assert _exclusive_lock_available(authority_lock) is True


def test_primary_connection_is_closed_when_snapshot_setup_exits_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = sqlite3.connect(":memory:")
    verifier = sqlite3.connect(":memory:")
    binding = object()

    @contextlib.contextmanager
    def fail_after_setup(_path: Path, **_kwargs: object):
        yield
        raise OSError("injected setup cleanup failure")

    monkeypatch.setattr(
        projection_module,
        "sqlite_authority_lock",
        fail_after_setup,
    )
    monkeypatch.setattr(
        projection_module,
        "_open_receipt_database_ro",
        lambda _path: (primary, binding),
    )
    monkeypatch.setattr(
        projection_module,
        "_connection_epoch_evidence",
        lambda _conn: ("same-epoch",),
        raising=False,
    )
    monkeypatch.setattr(
        projection_module,
        "_open_bound_receipt_database_ro",
        lambda _binding: verifier,
    )

    with pytest.raises(RuntimeProjectionError, match="projection failed closed"):
        with projection_module.open_verified_read_model_snapshot(
            Path("/private/tmp/unused.sqlite")
        ):
            pass
    with pytest.raises(sqlite3.ProgrammingError):
        primary.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        verifier.execute("SELECT 1")


def test_primary_connection_is_closed_when_lightweight_verifier_open_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = sqlite3.connect(":memory:")
    binding = object()
    monkeypatch.setattr(
        projection_module,
        "sqlite_authority_lock",
        lambda _path, **_kwargs: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        projection_module,
        "_open_receipt_database_ro",
        lambda _path: (primary, binding),
    )
    monkeypatch.setattr(
        projection_module,
        "_connection_epoch_evidence",
        lambda _conn: ("same-epoch",),
        raising=False,
    )

    def fail_verifier(_binding: object) -> sqlite3.Connection:
        raise RuntimeProjectionError("injected verifier failure")

    monkeypatch.setattr(
        projection_module,
        "_open_bound_receipt_database_ro",
        fail_verifier,
    )

    with pytest.raises(RuntimeProjectionError, match="injected verifier failure"):
        with projection_module.open_verified_read_model_snapshot(
            Path("/private/tmp/unused.sqlite")
        ):
            pass
    with pytest.raises(sqlite3.ProgrammingError):
        primary.execute("SELECT 1")


def test_snapshot_reader_waits_for_bounded_writer_release(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with projection_module.sqlite_authority_lock(db_path, mode="exclusive", create=True, timeout=0.0):
            future = executor.submit(_snapshot_select_one, db_path)
            time.sleep(0.05)
        assert future.result(timeout=1.0) == (1,)


def test_snapshot_reader_lock_wait_beyond_bound_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    monkeypatch.setattr(projection_module, "_SNAPSHOT_READER_LOCK_TIMEOUT_SECONDS", 0.1)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with projection_module.sqlite_authority_lock(db_path, mode="exclusive", create=True, timeout=0.0):
            future = executor.submit(_snapshot_select_one, db_path)
            with pytest.raises(RuntimeProjectionError, match="timed out|projection failed closed"):
                future.result(timeout=1.0)


def _snapshot_select_one(db_path: Path) -> tuple[object, ...]:
    with projection_module.open_verified_read_model_snapshot(db_path) as conn:
        return tuple(conn.execute("SELECT 1").fetchone())


def test_backwards_receipt_chronology_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-backwards",
        started_at="2026-07-15T01:00:00+00:00",
        finished_at="2026-07-15T01:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    payload["finished_at"] = "2026-07-15T00:59:59+00:00"
    conn.execute(
        "UPDATE market_ingest_runs SET finished_at = ?, notes = ? WHERE run_id = ?",
        (payload["finished_at"], _canonical_json(payload), receipt_id),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("receipt_chronology_invalid",)


def test_equal_started_and_finished_timestamps_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-instant",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:00:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False


def test_future_receipt_cannot_override_current_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-old-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-current-failed",
        started_at="2026-07-15T00:10:00+00:00",
        finished_at="2026-07-15T00:11:00+00:00",
        data_through=None,
    )
    future_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-future",
        started_at="2030-01-01T00:00:00+00:00",
        finished_at="2030-01-01T00:01:00+00:00",
        data_through="2030-01-01T00:00:00+00:00",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.receipt_id == future_receipt_id
    assert projection.reasons == ("receipt_timestamp_in_future",)


def test_future_data_through_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-future-data",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T01:00:00+00:00",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 59, 59, 999999, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through is None
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("data_through_in_future",)


def test_trade_calendar_allows_next_known_calendar_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="calendar-next-known-day",
        started_at="2026-07-28T06:00:00+00:00",
        finished_at="2026-07-28T06:01:00+00:00",
        data_through="2026-07-29T00:00:00+08:00",
    )

    projection = project_dataset_runtime(
        conn,
        replace(_dataset(), entity_type="trade_calendar"),
        now=datetime(2026, 7, 28, 6, 2, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.receipt_id == receipt_id
    assert projection.data_through == "2026-07-28T06:01:00+00:00"


def test_receipt_and_data_through_equal_to_now_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-now-boundary",
        started_at="2026-07-15T00:01:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:01:00+00:00",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False


def test_stale_transition_is_strictly_after_the_sla_boundary_in_dataset_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T03:00:00+00:00",
        finished_at="2026-07-15T03:01:00+00:00",
        data_through="2026-07-15T12:00:00",
    )
    dataset = _dataset(freshness_sla_seconds=3_600)
    boundary = datetime(2026, 7, 15, 5, tzinfo=timezone.utc)

    exact = project_dataset_runtime(conn, dataset, now=boundary)
    stale = project_dataset_runtime(
        conn,
        dataset,
        now=boundary + timedelta(microseconds=1),
    )

    assert exact.state == "success"
    assert exact.degraded is False
    assert stale.state == "stale"
    assert stale.degraded is True
    assert stale.reasons == ("freshness_sla_exceeded",)


def test_on_demand_success_never_marks_stale_past_sla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-ondemand",
        started_at="2026-07-15T03:00:00+00:00",
        finished_at="2026-07-15T03:01:00+00:00",
        data_through="2026-07-15T12:00:00",
    )
    dataset = _dataset(cadence_class="on_demand", freshness_sla_seconds=3_600)

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 18, 3, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.reasons == ()


def test_on_demand_empty_observation_never_marks_stale_past_sla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id="attempt-ondemand-empty",
        started_at="2026-07-15T03:00:00+00:00",
        finished_at="2026-07-15T03:01:00+00:00",
        data_through=None,
    )
    dataset = _dataset(cadence_class="on_demand", freshness_sla_seconds=3_600)

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 18, 3, tzinfo=timezone.utc),
    )

    assert projection.state == "empty"
    assert projection.degraded is False
    assert projection.reasons == ("provider_returned_no_rows",)


def test_future_data_through_does_not_cascade_execution_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-execution future-dated receipts must surface their own reason.

    Integrity checks run on the full validated set, so removing a future
    data_through receipt cannot orphan sibling calls into a bogus
    receipt_execution_inconsistent verdict.
    """

    conn = _memory_db()
    future_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id=make_provider_call_attempt_id(
            "exec-future-window", call_index=0, retry_index=0
        ),
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T23:59:00+00:00",
        transaction_index=0,
        request_identity=ProviderRequestIdentity(
            request_variant={"window": "a"},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=0,
            page_index=0,
        ),
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id=make_provider_call_attempt_id(
            "exec-future-window", call_index=1, retry_index=0
        ),
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:30+00:00",
        data_through=None,
        transaction_index=1,
        request_identity=ProviderRequestIdentity(
            request_variant={"window": "b"},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=1,
            page_index=1,
        ),
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 0, 2, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.receipt_id == future_id
    assert projection.reasons == ("data_through_in_future",)


def test_bounded_projection_accepts_contiguous_execution_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    root = "bounded-execution-suffix"
    for transaction_index, call_index in enumerate((7, 8)):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id=make_provider_call_attempt_id(
                root,
                call_index=call_index,
                retry_index=0,
            ),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=f"2026-07-15T00:0{transaction_index + 1}:00+00:00",
            data_through="20260715",
            transaction_index=transaction_index,
            request_identity=ProviderRequestIdentity(
                request_variant={"page": call_index},
                fanout_parameter=None,
                fanout_values=(),
                page_offset=call_index,
                page_index=call_index,
            ),
        )

    dataset = _dataset()
    known_dataset_ids = frozenset({dataset.dataset_id})
    receipts = [
        validated
        for scanned in projection_module._scan_ingest_run_rows(conn)
        if isinstance(
            (
                validated := projection_module._validate_receipt_row(
                    scanned,
                    dataset,
                    known_dataset_ids,
                    datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
                )
            ),
            projection_module._Receipt,
        )
    ]

    assert projection_module._execution_context_failures(receipts) == ()


def test_bounded_projection_rejects_gap_inside_execution_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    root = "bounded-execution-gap"
    for transaction_index, call_index in enumerate((7, 9)):
        _insert_receipt(
            monkeypatch,
            conn,
            status="success",
            attempt_id=make_provider_call_attempt_id(
                root,
                call_index=call_index,
                retry_index=0,
            ),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=f"2026-07-15T00:0{transaction_index + 1}:00+00:00",
            data_through="20260715",
            transaction_index=transaction_index,
            request_identity=ProviderRequestIdentity(
                request_variant={"page": call_index},
                fanout_parameter=None,
                fanout_values=(),
                page_offset=call_index,
                page_index=call_index,
            ),
        )

    dataset = _dataset()
    known_dataset_ids = frozenset({dataset.dataset_id})
    receipts = [
        validated
        for scanned in projection_module._scan_ingest_run_rows(conn)
        if isinstance(
            (
                validated := projection_module._validate_receipt_row(
                    scanned,
                    dataset,
                    known_dataset_ids,
                    datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
                )
            ),
            projection_module._Receipt,
        )
    ]
    failures = projection_module._execution_context_failures(receipts)

    assert [failure.reason for failure in failures] == [
        "receipt_execution_inconsistent"
    ]


def test_postclose_date_partition_stays_fresh_through_its_local_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-friday-close",
        started_at="2026-07-27T12:00:00+00:00",
        finished_at="2026-07-27T12:01:00+00:00",
        data_through="2026-07-24",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(freshness_sla_seconds=3 * 86_400),
        now=datetime(2026, 7, 27, 12, 2, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False


def test_event_cadence_date_partition_stays_fresh_through_its_local_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A date-only success watermark is fresh until end of its data day."""

    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-event-day",
        started_at="2026-07-15T02:00:00+00:00",
        finished_at="2026-07-15T02:01:00+00:00",
        data_through="20260715",
    )
    dataset = replace(
        _dataset(freshness_sla_seconds=3_600),
        cadence_class="event",
    )

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 16, 30, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False


def test_empty_receipt_uses_receipt_observation_for_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id="attempt-empty",
        started_at="2026-07-15T03:00:00+00:00",
        finished_at="2026-07-15T03:01:00+00:00",
        data_through="2026-07-15T12:00:00",
    )
    dataset = _dataset(freshness_sla_seconds=3_600)
    boundary = datetime(2026, 7, 15, 4, 1, tzinfo=timezone.utc)

    exact = project_dataset_runtime(conn, dataset, now=boundary)
    after_boundary = project_dataset_runtime(
        conn,
        dataset,
        now=boundary + timedelta(microseconds=1),
    )

    assert exact.state == "empty"
    assert exact.degraded is False
    assert after_boundary.state == "stale"
    assert after_boundary.degraded is True
    assert after_boundary.data_through is None
    assert after_boundary.reasons == ("freshness_sla_exceeded", "latest_receipt_empty")


def test_current_empty_receipt_is_not_staled_by_an_older_success_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-old-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id="attempt-current-empty",
        started_at="2026-07-20T03:00:00+00:00",
        finished_at="2026-07-20T03:01:00+00:00",
        data_through=None,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(freshness_sla_seconds=3_600),
        now=datetime(2026, 7, 20, 3, 30, tzinfo=timezone.utc),
    )

    assert projection.state == "empty"
    assert projection.degraded is False
    assert projection.receipt_id == receipt_id
    assert projection.data_through == "2026-07-15T08:00:00+08:00"
    assert projection.reasons == ("provider_returned_no_rows",)


def test_exact_request_partition_uses_its_own_receipt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later empty partition must not mask an earlier exact partition."""

    conn = _memory_db()
    dataset = _dataset(freshness_sla_seconds=3 * 86_400)
    success_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-partition-success",
        started_at="2026-07-14T00:00:00+00:00",
        finished_at="2026-07-14T00:01:00+00:00",
        data_through="20260714",
        request_window={"trade_date": "20260714"},
        dataset=dataset,
    )
    empty_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="empty",
        attempt_id="attempt-partition-empty",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through=None,
        request_window={"trade_date": "20260715"},
        dataset=dataset,
    )
    now = datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc)

    unbounded = project_dataset_runtime_evidence(conn, dataset, now=now)
    historical = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=now,
        request_partition=("trade_date", "20260714"),
    )
    empty_partition = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=now,
        request_partition=("trade_date", "20260715"),
    )

    assert unbounded.projection.state == "empty"
    assert unbounded.projection.receipt_id == empty_receipt
    assert historical.projection.state == "success"
    assert historical.projection.receipt_id == success_receipt
    assert historical.current_receipt_ids == (success_receipt,)
    assert empty_partition.projection.state == "empty"
    assert empty_partition.projection.receipt_id == empty_receipt


def test_exact_request_partition_keeps_all_success_receipts_for_accumulated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated success runs of one partition keep every complete success
    receipt as current read authority so delta-accumulated rows stay
    queryable instead of being scoped to only the latest run's receipts."""

    conn = _memory_db()
    dataset = _dataset(freshness_sla_seconds=3 * 86_400)
    first_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-partition-success-1",
        started_at="2026-07-14T00:00:00+00:00",
        finished_at="2026-07-14T00:01:00+00:00",
        data_through="20260714",
        request_window={"trade_date": "20260714"},
        dataset=dataset,
    )
    second_receipt = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-partition-success-2",
        started_at="2026-07-14T01:00:00+00:00",
        finished_at="2026-07-14T01:01:00+00:00",
        data_through="20260714",
        request_window={"trade_date": "20260714"},
        dataset=dataset,
    )
    now = datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc)

    historical = project_dataset_runtime_evidence(
        conn,
        dataset,
        now=now,
        request_partition=("trade_date", "20260714"),
    )

    assert historical.projection.state == "success"
    assert set(historical.current_receipt_ids) == {first_receipt, second_receipt}


def test_superseded_config_receipt_cannot_advance_current_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical receipt config cannot make old rows appear freshly ingested."""

    conn = _memory_db()
    current_receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-current-contract",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-superseded-contract",
        started_at="2026-07-20T00:00:00+00:00",
        finished_at="2026-07-20T00:01:00+00:00",
        data_through="20260720",
        config_hash="c" * 64,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(freshness_sla_seconds=3_600),
        now=datetime(2026, 7, 20, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "stale"
    assert projection.degraded is True
    assert projection.receipt_id == current_receipt_id
    assert projection.data_through == "20260715"
    assert projection.reasons == ("freshness_sla_exceeded",)


def test_receipt_like_unknown_schema_fails_closed() -> None:
    conn = _memory_db()
    receipt_id = "receipt:unknown-schema"
    payload = {
        "dataset_id": "cn.equity.daily",
        "receipt_id": receipt_id,
        "schema_version": "tradingdatas.ingest_receipt.v999",
    }
    conn.execute(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            receipt_id,
            "2026-07-15T00:00:00+00:00",
            "2026-07-15T00:01:00+00:00",
            "success",
            "cn.equity.daily",
            1,
            1,
            _canonical_json(payload),
        ),
    )
    conn.commit()

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("unknown_receipt_schema",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("receipt_id", "receipt:spoofed", "receipt_identity_mismatch"),
        ("provider", "other-provider", "provider_binding_mismatch"),
        ("provider_api", "other-api", "provider_binding_mismatch"),
        ("adapter_version", "other-adapter.v1", "adapter_version_mismatch"),
        ("target_table", "market_events", "target_table_mismatch"),
        ("counts.returned", 2, "receipt_counts_invalid"),
        ("payload_fingerprint", "not-a-sha256", "receipt_payload_invalid"),
    ],
)
def test_identity_binding_adapter_table_and_counts_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    reason: str,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _tamper_notes(conn, receipt_id, field, value)

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == (reason,)


@pytest.mark.parametrize(
    ("status", "tampered_semantics"),
    [
        ("success", "terminal_no_data_transaction"),
        ("success", "unknown_success_semantics"),
        ("empty", "storage_failure_before_commit"),
    ],
)
def test_count_semantics_must_match_status_and_count_shape(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    tampered_semantics: str,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status=status,
        attempt_id=f"attempt-{status}",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through=("2026-07-15T08:00:00+08:00" if status != "failed" else None),
    )
    _tamper_notes(
        conn,
        receipt_id,
        "counts.count_semantics",
        tampered_semantics,
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("receipt_counts_invalid",)


def test_failed_zero_receipt_accepts_terminal_no_data_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through=None,
    )
    _tamper_notes(
        conn,
        receipt_id,
        "counts.count_semantics",
        "terminal_no_data_transaction",
    )

    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("provider_error",)


def test_runtime_projection_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(FrozenInstanceError):
        projection.state = "failed"  # type: ignore[misc]


def test_dataset_runtime_evidence_uses_one_scan_and_preserves_typed_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    success_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    failed_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T00:02:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through=None,
    )
    original_scan = projection_module._scan_ingest_run_rows
    scans = 0

    def counted_scan(connection: sqlite3.Connection):
        nonlocal scans
        scans += 1
        return original_scan(connection)

    monkeypatch.setattr(projection_module, "_scan_ingest_run_rows", counted_scan)

    evidence = project_dataset_runtime_evidence(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert scans == 1
    assert isinstance(evidence, DatasetRuntimeEvidence)
    assert evidence.projection.state == "failed"
    assert evidence.projection.receipt_id == failed_id
    assert evidence.current_receipt_status == "failed"
    assert evidence.current_providers == ("tushare",)
    assert evidence.last_success_receipt_id == success_id
    assert evidence.last_success_providers == ("tushare",)
    assert evidence.last_success_data_through == "20260715"
    with pytest.raises(FrozenInstanceError):
        evidence.current_receipt_status = "success"  # type: ignore[misc]


def test_dataset_runtime_evidence_never_trusts_tampered_current_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    success_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715",
    )
    failed_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-failed",
        started_at="2026-07-15T00:02:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through=None,
    )
    _tamper_notes(conn, failed_id, "provider", "untrusted-provider")

    evidence = project_dataset_runtime_evidence(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )

    assert evidence.projection.state == "failed"
    assert evidence.current_receipt_status is None
    assert evidence.current_providers == ()
    assert evidence.last_success_receipt_id == success_id
    assert evidence.last_success_providers == ("tushare",)


def test_transient_latest_failure_does_not_hide_fresh_append_only_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = replace(_dataset(), point_in_time="append_only", timezone="UTC")
    success_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success-then-transient",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:00:00+00:00",
        dataset=dataset,
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-transient-later",
        started_at="2026-07-15T00:02:00+00:00",
        finished_at="2026-07-15T00:03:00+00:00",
        data_through=None,
        dataset=dataset,
    )
    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )
    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.data_through == "2026-07-15T00:00:00+00:00"
    assert projection.receipt_id == success_id


def test_snapshot_retries_transient_epoch_skew_under_concurrent_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib
    import storage.receipt_projection as projection_module

    calls = {"n": 0}
    real = projection_module._connection_epoch_evidence

    def flaky_epoch(c):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeProjectionError("receipt database connection target changed")
        return real(c)

    monkeypatch.setattr(projection_module, "_connection_epoch_evidence", flaky_epoch)

    @contextlib.contextmanager
    def _fake_lock(db_path, *, mode, create, timeout):
        yield

    monkeypatch.setattr(projection_module, "sqlite_authority_lock", _fake_lock)

    def _fake_open(db_path):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return conn, ("dev", 0, 1)

    def _fake_bound(binding):
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return conn

    monkeypatch.setattr(projection_module, "_open_receipt_database_ro", _fake_open)
    monkeypatch.setattr(projection_module, "_open_bound_receipt_database_ro", _fake_bound)

    with projection_module.open_verified_read_model_snapshot(Path("/fake/provider_native.sqlite")) as snapshot:
        assert tuple(snapshot.execute("SELECT 1").fetchone()) == (1,)
    assert calls["n"] >= 3


def test_full_table_scan_budget_covers_current_read_model_footprint() -> None:
    # The crypto read model reached ~131k market_ingest_runs rows in Aug 2026
    # and the append-only table keeps growing; the budget must stay above that
    # footprint or every dataset-scoped validation fails closed again.
    assert projection_module._MAX_INGEST_RUN_SCAN_ROWS >= 400_000


def _runs_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _insert_run(conn: sqlite3.Connection, run_id: str, source: str) -> None:
    conn.execute(
        "INSERT INTO market_ingest_runs "
        "(run_id, started_at, finished_at, status, source, rows_read, "
        "rows_written, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            "2026-07-15T04:00:00+00:00",
            "2026-07-15T04:01:00+00:00",
            "success",
            source,
            1,
            1,
            None,
        ),
    )
    conn.commit()


def test_scan_ingest_run_rows_for_dataset_authority_bounds_by_dataset() -> None:
    conn = _runs_conn()
    try:
        _insert_run(conn, "run-a1", "ds.a")
        _insert_run(conn, "run-a2", "ds.a")
        _insert_run(conn, "run-b1", "ds.b")
        _insert_run(conn, "run-b2", "ds.b")
        _insert_run(conn, "run-x1", "rogue.unknown")

        # Own rows only: foreign known-dataset rows AND unattributed rows are
        # excluded from the per-dataset authority snapshot; they are reported
        # globally by project_unattributed_receipts instead of poisoning this
        # dataset.
        own_rows = projection_module._scan_ingest_run_rows_for_dataset_authority(
            conn,
            dataset_id="ds.a",
            known_dataset_ids=frozenset({"ds.a", "ds.b"}),
        )
        assert [row.raw[1] for row in own_rows] == ["run-a1", "run-a2"]
        assert all(row.raw[9] == "ds.a" for row in own_rows)

        sole_rows = projection_module._scan_ingest_run_rows_for_dataset_authority(
            conn,
            dataset_id="ds.a",
            known_dataset_ids=frozenset({"ds.a"}),
        )
        assert [row.raw[1] for row in sole_rows] == ["run-a1", "run-a2"]

        full_rows = projection_module._scan_ingest_run_rows(conn)
        assert len(full_rows) == 5
    finally:
        conn.close()


def test_unattributed_health_counts_valid_tombstones_as_benign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    _insert_unmapped_tushare_receipt(monkeypatch, conn)

    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 0, 30, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    # A deliberate historical tombstone is counted, not alerted.
    assert health.anomalies == ()
    assert health.benign_tombstones == 1


def test_unattributed_health_reports_envelope_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    notes = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (receipt_id,),
    ).fetchone()[0]
    payload = json.loads(notes)
    payload["dataset_id"] = "other.ghost"
    conn.execute(
        "UPDATE market_ingest_runs SET source = ?, notes = ? WHERE run_id = ?",
        ("ghost.dataset", _canonical_json(payload), receipt_id),
    )
    conn.commit()

    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 2, tzinfo=timezone.utc),
        registry=load_dataset_registry(),
    )

    assert [
        (anomaly.receipt_id, anomaly.source, anomaly.reason)
        for anomaly in health.anomalies
    ] == [(receipt_id, "ghost.dataset", "receipt_envelope_mismatch")]
    assert health.benign_tombstones == 0
