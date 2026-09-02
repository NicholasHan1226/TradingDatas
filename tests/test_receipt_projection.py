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
from storage.sqlite_authority_lock import sqlite_authority_lock
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


def test_verified_snapshot_accepts_checkpointed_empty_wal_sidecars(
    tmp_path: Path,
) -> None:
    """A clean WAL checkpoint can leave a zero-byte WAL beside a live SHM file.

    SQLite reads the fully checkpointed main database in this state.  The
    receipt authority must retain its normal binding checks without turning a
    safe read-only snapshot into a persistent 503 merely because no WAL frame
    is pending.
    """

    db_path = tmp_path / "provider_native.sqlite"
    writer = sqlite3.connect(db_path)
    try:
        writer.executescript(SCHEMA_SQL)
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.commit()
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)

        wal_path = db_path.with_name(f"{db_path.name}-wal")
        shm_path = db_path.with_name(f"{db_path.name}-shm")
        assert wal_path.is_file()
        assert wal_path.stat().st_size == 0
        assert shm_path.is_file()

        with sqlite_authority_lock(
            db_path,
            mode="exclusive",
            create=True,
        ):
            pass

        with projection_module.open_verified_read_model_snapshot(db_path) as snapshot:
            assert snapshot.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone() == (
                0,
            )
    finally:
        writer.close()


def test_verified_snapshot_rejects_zero_wal_with_nonempty_shm_epoch(
    tmp_path: Path,
) -> None:
    """A zero WAL is admissible only when SHM also proves an empty epoch."""

    db_path = tmp_path / "provider_native.sqlite"
    writer = sqlite3.connect(db_path)
    try:
        writer.executescript(SCHEMA_SQL)
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.commit()
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)

        shm_path = db_path.with_name(f"{db_path.name}-shm")
        with shm_path.open("r+b") as stream:
            # mxFrame is the seventh native-endian word in each SHM header.
            stream.seek(16)
            stream.write((1).to_bytes(4, sys.byteorder))
            stream.seek(64)
            stream.write((1).to_bytes(4, sys.byteorder))

        with sqlite_authority_lock(
            db_path,
            mode="exclusive",
            create=True,
        ):
            pass

        with pytest.raises(RuntimeProjectionError, match="sidecars are inconsistent"):
            with projection_module.open_verified_read_model_snapshot(db_path):
                pass
    finally:
        writer.close()


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
    errors: tuple[str, ...] | None = None,
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
        errors = (
            errors
            if errors is not None
            else (("provider_error",) if status == "failed" else ())
        )
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


def test_planner_history_exposes_resource_budget_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    identity = ProviderRequestIdentity(
        request_variant={}, fanout_parameter="ts_code",
        fanout_values=("000001.SZ",), page_offset=None, page_index=0,
        cursor_contract_version=2, frozen_universe_sha256="a" * 64,
        batch_index=1, batch_count=3, batch_values_sha256="b" * 64,
    )
    _insert_receipt(
        monkeypatch, conn, status="failed", attempt_id="budget-history",
        started_at="2026-08-19T07:00:00+00:00",
        finished_at="2026-08-19T07:05:00+00:00",
        data_through=None, request_identity=identity,
        errors=("resource_budget",),
    )
    base = load_dataset_registry()
    histories = projection_module.validated_receipt_histories_by_dataset(
        conn, DatasetRegistry((_dataset(),), query_defaults=base.query_defaults),
        now=datetime(2026, 8, 19, 8, tzinfo=timezone.utc),
    )
    entry = histories.entries_by_dataset["cn.equity.daily"][0]
    assert entry.status == "failed"
    assert entry.errors == ("resource_budget",)
    assert entry.batch_index == 1


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

    # Exercise stale isolation after the configured 16:30 CN daily window.
    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
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

    # Exercise stale isolation after the configured 16:30 CN daily window.
    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
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

    # Exercise stale isolation after the configured 16:30 CN daily window.
    projection = project_dataset_runtime(
        conn,
        _dataset(),
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
    )
    health = projection_module.project_unattributed_receipts(
        conn,
        now=datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
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


def _catalog_retry_boundary(monkeypatch, *, calls=(0, 1, 2), newer_count=98, conn=None, dataset=None):
    conn = _memory_db() if conn is None else conn
    dataset = _dataset() if dataset is None else dataset
    registry = DatasetRegistry((dataset,))
    ids = []
    for call in calls:
        ids.append(_insert_receipt(monkeypatch, conn, dataset=dataset,
            dataset_id=dataset.dataset_id, provider_api=dataset.provider_bindings[0].api_name,
            status="failed", errors=("provider_error",),
            attempt_id=make_provider_call_attempt_id("catalog-boundary-retry-" + dataset.dataset_id, call_index=call, retry_index=call),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=f"2026-07-15T00:01:0{call}+00:00", data_through=None))
    for index in range(newer_count):
        ids.append(_insert_receipt(monkeypatch, conn, dataset=dataset,
            dataset_id=dataset.dataset_id, provider_api=dataset.provider_bindings[0].api_name,
            status="success", attempt_id=f"catalog-newer-{dataset.dataset_id}-{index}",
            started_at="2026-07-15T00:02:00+00:00",
            finished_at=(datetime(2026, 7, 15, 0, 3, tzinfo=timezone.utc) + timedelta(seconds=index)).isoformat(),
            data_through="20260715"))
    return conn, registry, ids


def test_catalog_reuses_validated_seed_identity_without_reparsing(monkeypatch):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=100)
    original = projection_module.parse_provider_call_attempt_id
    parsed = []

    def count_parse(value):
        parsed.append(value)
        return original(value)

    monkeypatch.setattr(projection_module, "parse_provider_call_attempt_id", count_parse)
    try:
        report = project_catalog_runtime(
            conn, registry, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
            validation_cache={},
        )
        assert report["datasets"][registry.datasets[0].dataset_id]["state"] == "success"
        assert len(parsed) == 100
    finally:
        conn.close()


def _validated_single_catalog_seed(monkeypatch):
    conn, registry, ids = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=1)
    dataset = registry.datasets[0]
    seed = projection_module._scan_ingest_run_rows_by_ids(conn, (ids[0],))[0]
    validated = projection_module._validate_receipt_row(
        seed, dataset, frozenset({dataset.dataset_id}),
        datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )
    assert isinstance(validated, projection_module._Receipt)
    return conn, dataset.dataset_id, seed, validated.execution_id


@pytest.mark.parametrize("mutation", ["notes", "status", "source", "notes_type", "count_type"])
def test_catalog_seed_reuse_requires_full_raw_tuple_not_run_id(monkeypatch, mutation):
    conn, dataset_id, seed, execution_id = _validated_single_catalog_seed(monkeypatch)
    mapping = {seed.raw: (seed, execution_id)}
    updates = {
        "notes": "notes = notes || ' '",
        "status": "status = 'failed'",
        "source": "source = 'cn.equity.alternate'",
        "notes_type": "notes = CAST(notes AS BLOB)",
        "count_type": "rows_read = CAST(rows_read AS BLOB)",
    }
    conn.execute(f"UPDATE market_ingest_runs SET {updates[mutation]} WHERE run_id=?", (seed.raw[1],))
    source = "cn.equity.alternate" if mutation == "source" else dataset_id
    baseline = projection_module._scan_ingest_run_rows_by_execution_ids(conn, source, (execution_id,))
    classified = []
    original = projection_module._classify_ingest_run_row

    def counted(row):
        classified.append(row)
        return original(row)

    monkeypatch.setattr(projection_module, "_classify_ingest_run_row", counted)
    try:
        reused = projection_module._scan_ingest_run_rows_by_execution_ids(
            conn, source, (execution_id,), validated_seed_rows=mapping,
        )
        assert len(reused) == 1 and reused[0].raw == baseline[0].raw
        assert reused[0] is not seed
        assert classified == [baseline[0].raw]
        assert reused[0].raw[1] == seed.raw[1]
    finally:
        conn.close()


@pytest.mark.parametrize("budget", [0, 1])
def test_catalog_seed_reuse_still_charges_all_raw_reads(monkeypatch, budget):
    conn, dataset_id, seed, execution_id = _validated_single_catalog_seed(monkeypatch)
    read_budget = projection_module._ReceiptReadBudget(budget)
    try:
        if budget == 0:
            with pytest.raises(RuntimeProjectionError, match="budget"):
                projection_module._scan_ingest_run_rows_by_execution_ids(
                    conn, dataset_id, (execution_id,), read_budget=read_budget,
                    validated_seed_rows={seed.raw: (seed, execution_id)},
                )
        else:
            result = projection_module._scan_ingest_run_rows_by_execution_ids(
                conn, dataset_id, (execution_id,), read_budget=read_budget,
                validated_seed_rows={seed.raw: (seed, execution_id)},
            )
            assert result[0] is seed and read_budget.remaining == 0
    finally:
        conn.close()


def test_catalog_seed_reuse_does_not_admit_an_unselected_execution(monkeypatch):
    conn, dataset_id, seed, execution_id = _validated_single_catalog_seed(monkeypatch)
    try:
        assert projection_module._scan_ingest_run_rows_by_execution_ids(
            conn, dataset_id, (execution_id,),
            validated_seed_rows={seed.raw: (seed, "another-execution")},
        ) == ()
    finally:
        conn.close()


def test_catalog_seed_mapping_is_request_local_and_excludes_invalid_receipts(monkeypatch):
    conn, registry, ids = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=100)
    mappings = []
    original = projection_module._scan_ingest_run_rows_by_execution_ids

    def inspect_mapping(*args, **kwargs):
        mappings.append(kwargs["validated_seed_rows"])
        return original(*args, **kwargs)

    monkeypatch.setattr(projection_module, "_scan_ingest_run_rows_by_execution_ids", inspect_mapping)
    try:
        now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
        first = project_catalog_runtime(conn, registry, now=now, validation_cache={})
        assert first["datasets"][registry.datasets[0].dataset_id]["state"] == "success"
        conn.execute("UPDATE market_ingest_runs SET notes='not-json' WHERE run_id=?", (ids[0],))
        second = project_catalog_runtime(conn, registry, now=now, validation_cache={})
        assert second["datasets"][registry.datasets[0].dataset_id]["state"] == "failed"
        assert len(mappings) == 2 and mappings[0] is not mappings[1]
        assert len(mappings[0]) == 100 and len(mappings[1]) == 99
        assert ids[0] not in {raw[1] for raw in mappings[1]}
    finally:
        conn.close()


def test_catalog_completes_retry_prefix_cut_by_recent_100(monkeypatch):
    conn, registry, ids = _catalog_retry_boundary(monkeypatch)
    dataset = registry.datasets[0]
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    seeds = projection_module._scan_recent_ingest_run_rows(conn, per_dataset_limit=100)
    assert len(seeds) == 100 and ids[0] not in {row.raw[1] for row in seeds}
    assert project_dataset_runtime(conn, dataset, now=now, registry=registry).state == "success"
    catalog = project_catalog_runtime(conn, registry, now=now)
    assert catalog["datasets"][dataset.dataset_id]["state"] == "success"
    full = project_registry_runtime(conn, registry, now=now)
    assert full["interfaces"]["daily"]["state"] == "success"
    _, _, expanded, _ = projection_module._project_registry_datasets(conn, registry, now=now)
    assert {row.raw[1] for row in expanded} == set(ids)


@pytest.mark.parametrize("calls", [(1, 2), (0, 2)])
def test_catalog_completion_does_not_hide_missing_retry_receipt(monkeypatch, calls):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=calls, newer_count=99)
    entry = project_catalog_runtime(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))["datasets"][registry.datasets[0].dataset_id]
    assert entry["state"] == "failed"
    assert entry["reasons"] == ["receipt_execution_inconsistent"]


@pytest.mark.parametrize("victim", [0, -1])
def test_catalog_completion_preserves_invalid_seed_and_fetched_sibling(monkeypatch, victim):
    conn, registry, ids = _catalog_retry_boundary(monkeypatch)
    raw, = conn.execute("SELECT notes FROM market_ingest_runs WHERE run_id=?", (ids[victim],)).fetchone()
    payload = json.loads(raw)
    payload["schema_version"] = "invalid-synthetic-schema"
    conn.execute("UPDATE market_ingest_runs SET notes=? WHERE run_id=?",
                 (json.dumps(payload, sort_keys=True, separators=(",", ":")), ids[victim]))
    entry = project_catalog_runtime(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))["datasets"][registry.datasets[0].dataset_id]
    assert entry["state"] == "failed"
    # A missing validated retry zero can add an execution error, but neither
    # the corrupt fetched sibling nor corrupt original seed may disappear.
    _, _, rows, _ = projection_module._project_registry_datasets(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))
    assert any(row.raw[1] == ids[victim] for row in rows)


def test_catalog_completion_raw_budget_counts_duplicate_reads_across_sources(monkeypatch):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch)
    base = registry.datasets[0]
    other = replace(base, dataset_id="cn.equity.boundary_other", aliases=(),
        provider_bindings=(replace(base.provider_bindings[0], api_name="boundary_other",
                                  read_discriminator_value="boundary_other"),))
    _catalog_retry_boundary(monkeypatch, conn=conn, dataset=other)
    registry = DatasetRegistry((base, other))
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    # 200 seed rows + two 101-row sibling lookups = 402 raw reads. The union
    # has only 202 rows, so enforcing the cap after deduplication would be wrong.
    monkeypatch.setattr(projection_module, "_MAX_INGEST_RUN_SCAN_ROWS", 401)
    with pytest.raises(RuntimeProjectionError, match="execution scan row budget"):
        project_catalog_runtime(conn, registry, now=now)
    monkeypatch.setattr(projection_module, "_MAX_INGEST_RUN_SCAN_ROWS", 402)
    assert all(item["state"] == "success" for item in
               project_catalog_runtime(conn, registry, now=now)["datasets"].values())


@pytest.mark.parametrize("offset_text", [False, True])
def test_catalog_completion_checks_older_sibling_without_trusting_chronology(monkeypatch, offset_text):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=99)
    dataset = registry.datasets[0]
    # Call 0 is selected; call 1 sorts outside the seed window. Each receipt
    # is individually valid, but their execution start contexts disagree.
    for call, start, finish in (
        (0, "2026-07-15T00:02:00+00:00", "2026-07-15T00:03:00+00:00"),
        (1, "2026-07-15T00:00:00+00:00", "2026-07-15T00:01:00+00:00"),
    ):
        if offset_text and call == 0:
            start, finish = "2026-07-15T09:02:00+09:00", "2026-07-15T09:03:00+09:00"
        _insert_receipt(monkeypatch, conn, dataset=dataset, status="success",
            attempt_id=make_provider_call_attempt_id("catalog-context-mismatch", call_index=call, retry_index=0),
            started_at=start, finished_at=finish, data_through="20260715",
            request_identity=ProviderRequestIdentity(request_variant={"page": call},
                fanout_parameter=None, fanout_values=(), page_offset=call, page_index=call))
    result = project_registry_runtime(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))
    assert result["datasets"][dataset.dataset_id]["reasons"] == ["receipt_execution_inconsistent"]
    assert result["interfaces"]["daily"]["reasons"] == ["receipt_execution_inconsistent"]


def test_catalog_completion_handles_multiple_interleaved_executions(monkeypatch):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=96)
    dataset = registry.datasets[0]
    ids = set()
    for root in ("catalog-overlap-first", "catalog-overlap-second"):
        for call in range(3):
            ids.add(_insert_receipt(monkeypatch, conn, dataset=dataset,
                status="failed", errors=("provider_error",),
                attempt_id=make_provider_call_attempt_id(root, call_index=call, retry_index=call),
                started_at="2026-07-15T00:00:00+00:00",
                finished_at=f"2026-07-15T00:01:0{call}+00:00", data_through=None))
    now = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
    seeds = projection_module._scan_recent_ingest_run_rows(conn, per_dataset_limit=100)
    assert len(ids & {row.raw[1] for row in seeds}) == 4
    projections, _, expanded, _ = projection_module._project_registry_datasets(conn, registry, now=now)
    assert projections[0].state == "success"
    assert ids <= {row.raw[1] for row in expanded}


def test_catalog_completion_requires_zero_prefix_for_fully_read_execution(monkeypatch):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=(), newer_count=99)
    _insert_receipt(monkeypatch, conn, dataset=registry.datasets[0], status="success",
        attempt_id=make_provider_call_attempt_id("missing-earlier-logical-request", call_index=7, retry_index=0),
        started_at="2026-07-15T00:00:00+00:00", finished_at="2026-07-15T00:01:00+00:00",
        data_through="20260715")
    result = project_catalog_runtime(conn, registry, now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))
    assert result["datasets"][registry.datasets[0].dataset_id]["reasons"] == ["receipt_execution_inconsistent"]


def test_catalog_completion_validates_future_sibling_after_execution_integrity(monkeypatch):
    conn, registry, _ = _catalog_retry_boundary(monkeypatch, calls=())
    ids = []
    for call in range(3):
        ids.append(_insert_receipt(monkeypatch, conn, dataset=registry.datasets[0],
            status="failed", errors=("provider_error",),
            attempt_id=make_provider_call_attempt_id("catalog-future-retry", call_index=call, retry_index=call),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=("2026-07-15T00:01:00-10:00" if call == 0
                         else f"2026-07-15T00:01:0{call}+00:00"), data_through=None))
    entry = project_catalog_runtime(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))["datasets"][registry.datasets[0].dataset_id]
    assert entry["state"] == "failed"
    assert entry["receipt_id"] == ids[0]
    assert entry["reasons"] == ["receipt_timestamp_in_future"]


@pytest.mark.parametrize("include_second_variant", [False, True])
def test_catalog_completion_preserves_registered_variant_requirements(monkeypatch, include_second_variant):
    conn = _memory_db()
    base = _dataset()
    dataset = replace(base, provider_bindings=(replace(base.provider_bindings[0],
        request_variants=({"venue": "a"}, {"venue": "b"})),))
    registry = DatasetRegistry((dataset,))
    calls = [(0, 0, "a", "failed"), (1, 1, "a", "empty")]
    if include_second_variant:
        calls.append((2, 0, "b", "success"))
    for call, retry, venue, status in calls:
        _insert_receipt(monkeypatch, conn, dataset=dataset, status=status,
            attempt_id=make_provider_call_attempt_id("catalog-variant-retry", call_index=call, retry_index=retry),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=f"2026-07-15T00:01:0{call}+00:00",
            data_through="20260715" if status == "success" else None,
            request_identity=ProviderRequestIdentity(request_variant={"venue": venue},
                fanout_parameter=None, fanout_values=(), page_offset=None, page_index=0))
    monkeypatch.setattr(projection_module, "_MAX_INGEST_RUN_SCAN_ROWS_PER_DATASET", 1)
    entry = project_catalog_runtime(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))["datasets"][dataset.dataset_id]
    assert entry["state"] == ("success" if include_second_variant else "failed")
    if not include_second_variant:
        assert entry["reasons"] == ["variant_cohort_incomplete"]


def test_catalog_completion_accepts_large_complete_physical_execution(monkeypatch):
    conn = _memory_db()
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    ids = set()
    for call in range(128):
        ids.add(_insert_receipt(monkeypatch, conn, dataset=dataset, status="success",
            attempt_id=make_provider_call_attempt_id("catalog-large-execution", call_index=call, retry_index=0),
            started_at="2026-07-15T00:00:00+00:00",
            finished_at=(datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc) + timedelta(seconds=call)).isoformat(),
            data_through="20260715", request_identity=ProviderRequestIdentity(
                request_variant={}, fanout_parameter=None, fanout_values=(),
                page_offset=call, page_index=call)))
    projections, _, rows, _ = projection_module._project_registry_datasets(conn, registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc))
    assert projections[0].state == "success"
    assert {row.raw[1] for row in rows} == ids


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


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_execution_candidate_predicate_matches_original_sql_for_raw_material(encoding):
    conn = sqlite3.connect(":memory:")
    conn.execute(f"PRAGMA encoding='{encoding}'")
    conn.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, notes)")
    roots = ['exec-alpha', '执行记录', 'exec-"quote', 'exec-\\slash']
    fragments = []
    material = [None, 1, 1.5, "", b"", '{"unrelated":true}']
    for root in roots:
        ordinary = '"attempt_id":' + json.dumps(root, ensure_ascii=False)
        physical = '"attempt_id":' + json.dumps(root + ':provider-call:', ensure_ascii=False)[:-1]
        fragments.extend((ordinary, physical))
        material.extend([
            '{' + ordinary + '}',
            '{"attempt_id":"other",' + ordinary + '}',
            '{"nested":{' + ordinary + '}}',
            '{' + ordinary,
            '\x00' + ordinary,
            ordinary.encode('utf-8'),
            b'\x80\x00' + ordinary.encode('utf-8'),
            '{' + physical + '000000000000:retry:000000000000"}',
            '{"attempt_id":' + json.dumps(root + '-near-prefix') + '}',
            json.dumps(ordinary),
        ])
    conn.executemany("INSERT INTO candidates(notes) VALUES (?)", [(value,) for value in material])
    # Invalid TEXT must be filtered without Python decoding before the predicate.
    for value in [b'\x80unrelated', b'\x80' + fragments[0].encode('utf-8')]:
        conn.execute("INSERT INTO candidates(notes) VALUES (CAST(? AS TEXT))", (value,))
    old = " OR ".join("instr(notes, ?) > 0" for _ in fragments)
    expected = conn.execute(f"SELECT id FROM candidates WHERE {old}", fragments).fetchall()
    with projection_module._execution_candidate_predicate(conn, fragments) as (predicate, params):
        cursor = conn.execute(f"SELECT id FROM candidates WHERE {predicate}", params)
        try:
            assert cursor.fetchall() == expected
        finally:
            cursor.close()
    conn.close()


@pytest.mark.parametrize("fragments", [
    ["aba", "abab"],
    ["ababaX", "ababaY"],
    ["shared", "shared-tail"],
    ['"attempt_id":"exec-' + str(i).zfill(4) + '"' for i in range(200)],
    ['"attempt_id":"' + "x" * i + '"' for i in range(1, 25)],
    ["prefix-" + "x" * i for i in range(1, 17)],
    ["prefix-" + "x" * i for i in range(1, 18)],
    ["", "other"],
    ["unrelated", "different"],
])
def test_execution_candidate_literal_membership_preserves_all_raw_matches(fragments):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, notes)")
    material = [None, b"", b"no-match", b"ababab", b"abababaX", b"shared"]
    for fragment in fragments:
        literal = fragment.encode("utf-8")
        material.extend([
            literal, b"\xff\x00" + literal, literal + b"\x00\xff",
            literal[:-1], literal + literal,
            b'"attempt_id":"not-selected",' + literal,
        ])
    conn.executemany("INSERT INTO candidates(notes) VALUES (?)", [(value,) for value in material])
    old = " OR ".join("instr(notes, ?) > 0" for _ in fragments)
    expected = conn.execute(f"SELECT id FROM candidates WHERE {old}", fragments).fetchall()
    with projection_module._execution_candidate_predicate(conn, fragments) as (predicate, params):
        cursor = conn.execute(f"SELECT id FROM candidates WHERE {predicate}", params)
        assert cursor.fetchall() == expected
        cursor.close()
    conn.close()


@pytest.mark.parametrize("outcome", ["success", "budget", "interrupted"])
def test_execution_candidate_callback_is_removed_after_scan(monkeypatch, outcome):
    class TrackingConnection(sqlite3.Connection):
        registrations = []

        def create_function(self, name, narg, func, **kwargs):
            self.registrations.append((name, func is not None))
            return super().create_function(name, narg, func, **kwargs)

    conn = sqlite3.connect(":memory:", factory=TrackingConnection)
    conn.executescript(SCHEMA_SQL)
    _insert_receipt(
        monkeypatch, conn, status="success", attempt_id="lookup-cleanup",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T08:00:00+08:00",
    )
    if outcome == "interrupted":
        def authorizer(action, name, *_):
            if action == sqlite3.SQLITE_READ and name == "market_ingest_runs":
                conn.set_progress_handler(lambda: 1, 1)
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorizer)
    budget = projection_module._ReceiptReadBudget(0 if outcome == "budget" else 10)
    try:
        if outcome == "success":
            assert projection_module._scan_ingest_run_rows_by_execution_ids(
                conn, "cn.equity.daily", ("lookup-cleanup",), read_budget=budget
            )
        else:
            error = RuntimeProjectionError if outcome == "budget" else sqlite3.OperationalError
            with pytest.raises(error, match="budget|interrupted"):
                projection_module._scan_ingest_run_rows_by_execution_ids(
                    conn, "cn.equity.daily", ("lookup-cleanup",), read_budget=budget
                )
    finally:
        conn.set_progress_handler(None, 0)
        conn.set_authorizer(None)
    installed = [name for name, active in conn.registrations if active]
    removed = [name for name, active in conn.registrations if not active]
    assert len(installed) == 1
    assert installed == removed
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(f"SELECT {installed[0]}(?)", (b'"attempt_id":"lookup-cleanup"',)).fetchall()
    conn.close()


def test_execution_candidate_native_first_match_avoids_python_except_later_prefix():
    calls = []

    class CountingConnection(sqlite3.Connection):
        def create_function(self, name, narg, func, **kwargs):
            if func is None:
                return super().create_function(name, narg, func, **kwargs)

            def counted(value):
                calls.append(value)
                return func(value)

            return super().create_function(name, narg, counted, **kwargs)

    conn = sqlite3.connect(":memory:", factory=CountingConnection)
    conn.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, notes)")
    values = [None, b"nothing", b"ababaX", b"ababaZ", b"abababaX", b"ababaZababaY", b"ababaZababaQ"]
    conn.executemany("INSERT INTO candidates(notes) VALUES (?)", [(value,) for value in values])
    fragments = ["ababaX", "ababaY"]
    try:
        expected = conn.execute(
            "SELECT id FROM candidates WHERE instr(notes,?)>0 OR instr(notes,?)>0", fragments
        ).fetchall()
        with projection_module._execution_candidate_predicate(conn, fragments) as (predicate, params):
            cursor = conn.execute(f"SELECT id FROM candidates WHERE {predicate}", params)
            try:
                assert cursor.fetchall() == expected
            finally:
                cursor.close()
        assert calls == values[4:]
    finally:
        conn.close()


@pytest.mark.parametrize("bound", ["parameters", "connection_limit", "sql_bytes"])
def test_execution_candidate_native_bound_falls_back_without_losing_rows(monkeypatch, bound):
    calls = []

    class CountingConnection(sqlite3.Connection):
        def create_function(self, name, narg, func, **kwargs):
            if func is None:
                return super().create_function(name, narg, func, **kwargs)

            def counted(value):
                calls.append(value)
                return func(value)

            return super().create_function(name, narg, counted, **kwargs)

    fragments = (
        [f"prefix-{index:04d}" for index in range(800)]
        if bound == "parameters" else ["prefix-A", "prefix-B"]
    )
    conn = sqlite3.connect(":memory:", factory=CountingConnection)
    conn.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, notes)")
    values = [None, b"nothing", fragments[0].encode(), b"\x80\x00" + fragments[-1].encode()]
    conn.executemany("INSERT INTO candidates(notes) VALUES (?)", [(value,) for value in values])
    old = " OR ".join("instr(notes,?)>0" for _ in fragments)
    expected = conn.execute(f"SELECT id FROM candidates WHERE {old}", fragments).fetchall()
    if bound == "connection_limit":
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 5)
    elif bound == "sql_bytes":
        monkeypatch.setattr(projection_module, "_EXECUTION_CANDIDATE_MAX_SQL_BYTES", 10)
    try:
        with projection_module._execution_candidate_predicate(conn, fragments) as (predicate, params):
            assert params == ()
            cursor = conn.execute(f"SELECT id FROM candidates WHERE {predicate}", params)
            try:
                assert cursor.fetchall() == expected
            finally:
                cursor.close()
        assert calls == values
    finally:
        conn.close()


@pytest.mark.parametrize("variable_limit,native", [(7, False), (8, True)])
def test_execution_candidate_native_reserves_source_and_limit_parameters(variable_limit, native):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE candidates(source, notes)")
    conn.execute("INSERT INTO candidates VALUES ('chosen', 'prefix-A')")
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, variable_limit)
    try:
        with projection_module._execution_candidate_predicate(conn, ["prefix-A", "prefix-B"]) as (predicate, params):
            assert bool(params) is native
            cursor = conn.execute(
                f"SELECT source FROM candidates WHERE source=? AND ({predicate}) LIMIT ?",
                ("chosen", *params, 10),
            )
            try:
                assert cursor.fetchall() == [("chosen",)]
            finally:
                cursor.close()
    finally:
        conn.close()


def test_execution_candidate_callbacks_do_not_overlap_between_connections():
    first_callback = threading.Event()
    second_attempt = threading.Event()
    second_callback = threading.Event()
    release_first = threading.Event()
    outcomes = []
    removed = []

    def worker(index):
        class ObservedConnection(sqlite3.Connection):
            def create_function(self, name, narg, func, **kwargs):
                if func is None:
                    result = super().create_function(name, narg, func, **kwargs)
                    removed.append(index)
                    return result

                def observed(value):
                    if index == 0:
                        first_callback.set()
                        if not release_first.wait(5):
                            raise RuntimeError("test callback release timed out")
                    else:
                        second_callback.set()
                    return func(value)

                return super().create_function(name, narg, observed, **kwargs)

        conn = sqlite3.connect(":memory:", factory=ObservedConnection)
        try:
            if index == 1:
                second_attempt.set()
            with projection_module._execution_candidate_predicate(conn, ["needle", "other"]) as (predicate, params):
                cursor = conn.execute(
                    f"SELECT {predicate} FROM (SELECT ? AS notes)", (*params, b"needle")
                )
                try:
                    outcomes.append(cursor.fetchall())
                finally:
                    cursor.close()
        except (sqlite3.Error, RuntimeError, AssertionError) as error:
            outcomes.append(error)
        finally:
            conn.close()

    first = threading.Thread(target=worker, args=(0,), daemon=True)
    second = threading.Thread(target=worker, args=(1,), daemon=True)
    first.start()
    try:
        assert first_callback.wait(5)
        second.start()
        assert second_attempt.wait(5)
        assert not second_callback.wait(0.2)
    finally:
        release_first.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert outcomes == [[(1,)], [(1,)]]
    assert sorted(removed) == [0, 1]


@pytest.mark.parametrize("failure", ["registration", "query_body", "query_interrupted", "cleanup"])
def test_execution_candidate_releases_scan_lock_after_exception(failure):
    class FailingConnection(sqlite3.Connection):
        def create_function(self, name, narg, func, **kwargs):
            if failure == "registration" and func is not None:
                raise RuntimeError("synthetic registration failure")
            result = super().create_function(name, narg, func, **kwargs)
            if failure == "cleanup" and func is None:
                raise RuntimeError("synthetic cleanup failure")
            return result

    conn = sqlite3.connect(":memory:", factory=FailingConnection)
    try:
        error = sqlite3.OperationalError if failure == "query_interrupted" else RuntimeError
        with (
            pytest.raises(error, match="synthetic|interrupted"),
            projection_module._execution_candidate_predicate(conn, ["needle", "other"]) as (predicate, params),
        ):
            if failure == "query_interrupted":
                conn.set_progress_handler(lambda: 1, 1)
            cursor = conn.execute(
                f"SELECT {predicate} FROM (SELECT ? AS notes)", (*params, b"needle")
            )
            try:
                assert cursor.fetchall() == [(1,)]
            finally:
                cursor.close()
            if failure == "query_body":
                raise RuntimeError("synthetic query body failure")
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()

    outcomes = []

    def another_connection():
        other = sqlite3.connect(":memory:")
        try:
            with projection_module._execution_candidate_predicate(other, ["needle", "other"]) as (predicate, params):
                cursor = other.execute(
                    f"SELECT {predicate} FROM (SELECT ? AS notes)", (*params, b"needle")
                )
                try:
                    outcomes.append(cursor.fetchall())
                finally:
                    cursor.close()
        except (sqlite3.Error, RuntimeError, AssertionError) as error:
            outcomes.append(error)
        finally:
            other.close()

    thread = threading.Thread(target=another_connection, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    assert outcomes == [[(1,)]]


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_execution_candidate_nested_connection_or_non_utf8_does_not_deadlock(encoding):
    outcomes = []

    def query_other():
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(f"PRAGMA encoding='{encoding}'")
            conn.execute("CREATE TABLE notes(value)")
            with projection_module._execution_candidate_predicate(conn, ["needle", "other"]) as (predicate, params):
                cursor = conn.execute(
                    f"SELECT {predicate} FROM (SELECT 'needle' AS notes)", params
                )
                try:
                    outcomes.append(cursor.fetchall())
                finally:
                    cursor.close()
        except (sqlite3.Error, RuntimeError, AssertionError) as error:
            outcomes.append(error)
        finally:
            conn.close()

    def outer_query():
        outer = sqlite3.connect(":memory:")
        try:
            with projection_module._execution_candidate_predicate(outer, ["outer"]):
                if encoding == "UTF-8":
                    # The same thread may nest another connection's UDF lifetime.
                    query_other()
                else:
                    # Native SQLite fallback must not wait on the Python UDF gate.
                    thread = threading.Thread(target=query_other, daemon=True)
                    thread.start()
                    thread.join(2)
                    outcomes.append(not thread.is_alive())
        finally:
            outer.close()

    outer_thread = threading.Thread(target=outer_query, daemon=True)
    outer_thread.start()
    outer_thread.join(5)
    assert not outer_thread.is_alive()
    assert outcomes == ([[(1,)]] if encoding == "UTF-8" else [[(1,)], True])


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


def test_connection_epoch_evidence_is_bounded_by_latest_receipt() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                f"run-{index:05d}",
                "2026-09-01T00:00:00Z",
                "2026-09-01T00:00:01Z",
                "success",
                "provider-native",
                1,
                1,
                '{"receipt":true}',
            )
            for index in range(5_000)
        ),
    )
    conn.commit()
    progress_calls = 0

    def bounded_progress() -> int:
        nonlocal progress_calls
        progress_calls += 1
        return int(progress_calls > 200)

    conn.set_progress_handler(bounded_progress, 1)
    evidence = projection_module._connection_epoch_evidence(conn)
    conn.set_progress_handler(None, 0)

    assert "run-04999" in evidence
    assert progress_calls <= 200


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
        started_at="2026-07-15T07:00:00+00:00",
        finished_at="2026-07-15T07:01:00+00:00",
        data_through="2026-07-15T16:00:00",
    )
    dataset = _dataset(freshness_sla_seconds=3_600)
    # Evaluate the ordinary strict SLA after the 16:30 daily availability.
    boundary = datetime(2026, 7, 15, 9, tzinfo=timezone.utc)

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


def test_cn_session_minute_freshness_pauses_only_for_same_day_lunch_break(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="cn-session-minute-lunch",
        started_at="2026-07-15T03:29:00+00:00",
        finished_at="2026-07-15T03:30:00+00:00",
        data_through="2026-07-15T11:30:00+08:00",
    )
    dataset = _dataset(cadence_class="session_minute", freshness_sla_seconds=600)

    lunch = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 4, 30, tzinfo=timezone.utc),
    )
    afternoon_open = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 5, 0, tzinfo=timezone.utc),
    )

    assert lunch.state == "success"
    assert lunch.degraded is False
    assert afternoon_open.state == "stale"
    assert afternoon_open.reasons == ("freshness_sla_exceeded",)


def test_session_minute_lunch_break_does_not_apply_outside_cn_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="non-cn-session-minute-lunch",
        started_at="2026-07-15T03:29:00+00:00",
        finished_at="2026-07-15T03:30:00+00:00",
        data_through="2026-07-15T11:30:00+08:00",
    )
    dataset = replace(
        _dataset(cadence_class="session_minute", freshness_sla_seconds=600),
        market="CRYPTO",
    )

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 4, 30, tzinfo=timezone.utc),
    )

    assert projection.state == "stale"
    assert projection.reasons == ("freshness_sla_exceeded",)


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


def test_on_demand_month_partition_is_a_valid_runtime_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = load_dataset_registry().resolve("cn.dataset.broker_recommend")
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-current-month",
        started_at="2026-07-15T02:00:00+00:00",
        finished_at="2026-07-15T02:01:00+00:00",
        data_through="202607",
        request_window={"month": "202607"},
        dataset_id=dataset.dataset_id,
        provider_api="broker_recommend",
        dataset=dataset,
    )

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 3, tzinfo=timezone.utc),
    )

    assert projection.state == "success"
    assert projection.degraded is False
    assert projection.data_through == "202607"


def test_future_month_partition_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _memory_db()
    dataset = load_dataset_registry().resolve("cn.dataset.broker_recommend")
    receipt_id = _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-future-month",
        started_at="2026-07-15T02:00:00+00:00",
        finished_at="2026-07-15T02:01:00+00:00",
        data_through="202608",
        request_window={"month": "202608"},
        dataset_id=dataset.dataset_id,
        provider_api="broker_recommend",
        dataset=dataset,
    )

    projection = project_dataset_runtime(
        conn,
        dataset,
        now=datetime(2026, 7, 15, 3, tzinfo=timezone.utc),
    )

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.receipt_id == receipt_id
    assert projection.reasons == ("data_through_in_future",)


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


@pytest.mark.parametrize("cadence_class", ["event", "session_minute"])
def test_high_frequency_append_only_latest_failure_remains_visible(
    monkeypatch: pytest.MonkeyPatch,
    cadence_class: str,
) -> None:
    conn = _memory_db()
    dataset = replace(
        _dataset(cadence_class=cadence_class),
        point_in_time="append_only",
        timezone="UTC",
    )
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="attempt-high-frequency-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:00:00+00:00",
        dataset=dataset,
    )
    failed_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="attempt-high-frequency-failed",
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

    assert projection.state == "failed"
    assert projection.degraded is True
    assert projection.data_through == "2026-07-15T00:00:00+00:00"
    assert projection.receipt_id == failed_id
    assert projection.reasons == ("provider_error",)


@pytest.mark.parametrize("cadence_class", ["event", "session_minute"])
def test_catalog_high_frequency_failure_keeps_success_watermark_beyond_recent_window(
    monkeypatch: pytest.MonkeyPatch,
    cadence_class: str,
) -> None:
    conn = _memory_db()
    dataset = replace(
        _dataset(cadence_class=cadence_class),
        point_in_time="append_only",
        timezone="UTC",
    )
    registry = DatasetRegistry((dataset,))
    _insert_receipt(
        monkeypatch,
        conn,
        status="success",
        attempt_id="catalog-high-frequency-last-success",
        started_at="2026-07-15T00:00:00+00:00",
        finished_at="2026-07-15T00:01:00+00:00",
        data_through="2026-07-15T00:00:00+00:00",
        dataset=dataset,
    )
    malformed_id = _insert_receipt(
        monkeypatch,
        conn,
        status="failed",
        attempt_id="catalog-high-frequency-malformed",
        started_at="2026-07-15T00:01:01+00:00",
        finished_at="2026-07-15T00:01:02+00:00",
        data_through=None,
        dataset=dataset,
    )
    conn.execute(
        "UPDATE market_ingest_runs SET notes='not-json' WHERE run_id=?",
        (malformed_id,),
    )
    latest_failed_id = None
    for index in range(101):
        observed = datetime(2026, 7, 15, 0, 2, tzinfo=timezone.utc) + timedelta(
            seconds=index
        )
        latest_failed_id = _insert_receipt(
            monkeypatch,
            conn,
            status="failed",
            attempt_id=f"catalog-high-frequency-failure-{index:03d}",
            started_at=observed.isoformat(),
            finished_at=(observed + timedelta(milliseconds=500)).isoformat(),
            data_through=None,
            dataset=dataset,
        )

    entry = project_catalog_runtime(
        conn,
        registry,
        now=datetime(2026, 7, 15, 1, tzinfo=timezone.utc),
    )["datasets"][dataset.dataset_id]

    assert entry["state"] == "failed"
    assert entry["degraded"] is True
    assert entry["data_through"] == "2026-07-15T00:00:00+00:00"
    assert entry["receipt_id"] == latest_failed_id
    assert entry["reasons"] == ["provider_error"]


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


@pytest.mark.parametrize('cadence,watermark,expected', [
    ('session_minute', '2026-08-28T15:00:00+08:00', 'success'),
    ('session_minute', '2026-08-28T14:30:00+08:00', 'stale'),
    ('session_minute', '2026-08-27T15:00:00+08:00', 'stale'),
    ('postclose_daily', '20260828', 'success'),
    ('postclose_daily', '20260827', 'stale'),
    ('event', '2026-08-28T15:00:00+08:00', 'stale'),
])
def test_cn_weekend_preserves_last_session_without_hiding_missing_data(monkeypatch, cadence, watermark, expected):
    conn = _memory_db()
    dataset = _dataset(cadence_class=cadence, freshness_sla_seconds=600 if cadence == 'session_minute' else 86400)
    _insert_receipt(monkeypatch, conn, dataset=dataset, status='success', attempt_id='weekend',
                    started_at='2026-08-28T07:00:00Z', finished_at='2026-08-28T07:10:00Z', data_through=watermark)
    projection = project_dataset_runtime(conn, dataset, now=datetime(2026, 8, 30, 3, tzinfo=timezone.utc))
    assert projection.state == expected


def test_month_watermark_stays_current_for_its_whole_month(monkeypatch):
    conn = _memory_db()
    dataset = _dataset(cadence_class='monthly', freshness_sla_seconds=86400)
    _insert_receipt(monkeypatch, conn, dataset=dataset, status='success', attempt_id='month',
                    started_at='2026-08-01T01:00:00Z', finished_at='2026-08-01T01:01:00Z', data_through='202608')
    assert project_dataset_runtime(conn, dataset, now=datetime(2026, 8, 30, 3, tzinfo=timezone.utc)).state == 'success'
    assert project_dataset_runtime(conn, dataset, now=datetime(2026, 9, 2, 3, tzinfo=timezone.utc)).state == 'stale'


@pytest.mark.parametrize('market,now', [
    ('CRYPTO', datetime(2026, 8, 30, 3, tzinfo=timezone.utc)),
    ('CN', datetime(2026, 8, 31, 2, tzinfo=timezone.utc)),
])
def test_weekend_clock_never_hides_crypto_or_monday_session_gap(monkeypatch, market, now):
    conn = _memory_db()
    dataset = replace(_dataset(cadence_class='session_minute', freshness_sla_seconds=600), market=market)
    _insert_receipt(monkeypatch, conn, dataset=dataset, status='success', attempt_id='session-gap',
                    started_at='2026-08-28T07:00:00Z', finished_at='2026-08-28T07:01:00Z', data_through='2026-08-28T15:00:00+08:00')
    assert project_dataset_runtime(conn, dataset, now=now).state == 'stale'


@pytest.fixture
def cn_prewindow_schedule(monkeypatch):
    """Override only the immutable release's schedule bytes, never an env path."""
    path = (
        Path(projection_module.__file__).resolve().parents[1]
        / "config/provider_native_schedule.yaml"
    )
    read_bytes = Path.read_bytes
    payload = {"bytes": read_bytes(path), "reads": 0}
    loader = getattr(projection_module, "_cn_freshness_policies", None)
    if loader is not None:
        loader.cache_clear()

    def read(candidate):
        if candidate == path:
            payload["reads"] += 1
            value = payload["bytes"]
            if isinstance(value, Exception):
                raise value
            return value
        return read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", read)
    yield payload
    loader = getattr(projection_module, "_cn_freshness_policies", None)
    if loader is not None:
        loader.cache_clear()


@pytest.mark.parametrize(
    "cadence,watermark,local_now,expected",
    [
        (
            "session_minute",
            "2026-08-28T15:00:00+08:00",
            "2026-08-30T23:59:59+08:00",
            "success",
        ),
        (
            "session_minute",
            "2026-08-28T15:00:00+08:00",
            "2026-08-31T00:00:00+08:00",
            "success",
        ),
        (
            "session_minute",
            "2026-08-28T15:00:00+08:00",
            "2026-08-31T09:29:59.999999+08:00",
            "success",
        ),
        (
            "session_minute",
            "2026-08-28T15:00:00+08:00",
            "2026-08-31T09:30:00+08:00",
            "stale",
        ),
        (
            "session_minute",
            "2026-08-28T15:00:00+08:00",
            "2026-08-31T10:00:00+08:00",
            "stale",
        ),
        (
            "session_minute",
            "2026-08-28T14:30:00+08:00",
            "2026-08-31T00:00:00+08:00",
            "stale",
        ),
        (
            "session_minute",
            "2026-08-27T15:00:00+08:00",
            "2026-08-31T00:00:00+08:00",
            "stale",
        ),
        ("postclose_daily", "20260828", "2026-08-30T23:59:59+08:00", "success"),
        ("postclose_daily", "20260828", "2026-08-31T00:00:00+08:00", "success"),
        ("postclose_daily", "20260828", "2026-08-31T16:29:59.999999+08:00", "success"),
        ("postclose_daily", "20260828", "2026-08-31T16:30:00+08:00", "stale"),
        ("postclose_daily", "20260827", "2026-08-31T00:00:00+08:00", "stale"),
        ("postclose_daily", "20260831", "2026-09-01T00:00:00+08:00", "success"),
        ("postclose_daily", "20260828", "2026-09-01T00:00:00+08:00", "stale"),
    ],
)
def test_cn_prewindow_receipt_boundaries(
    monkeypatch, cadence, watermark, local_now, expected
):
    conn = _memory_db()
    dataset = _dataset(
        cadence_class=cadence,
        freshness_sla_seconds=600 if cadence == "session_minute" else 86400,
    )
    # Keep the receipt before the read clock and the declared partition end.
    finished = (
        "2026-08-31T09:00:00Z" if watermark == "20260831" else "2026-08-28T07:10:00Z"
    )
    _insert_receipt(
        monkeypatch,
        conn,
        dataset=dataset,
        status="success",
        attempt_id="prewindow",
        started_at=finished,
        finished_at=finished,
        data_through=watermark,
    )
    result = project_dataset_runtime(
        conn, dataset, now=datetime.fromisoformat(local_now)
    )
    assert result.state == expected
    assert result.data_through == watermark
    assert result.reasons == (
        () if expected == "success" else ("freshness_sla_exceeded",)
    )


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "yaml",
        "null_availability",
        "weekend",
        "empty_weekdays",
        "invalid_clock",
    ],
)
def test_cn_prewindow_invalid_schedule_fails_closed(
    monkeypatch, cn_prewindow_schedule, bad
):
    import yaml

    raw = yaml.safe_load(cn_prewindow_schedule["bytes"])
    if bad == "missing":
        value = FileNotFoundError("schedule absent")
    elif bad == "yaml":
        value = b"cadences: ["
    else:
        policy = raw["cadences"]["session_minute"]
        if bad == "null_availability":
            policy["availability_after_local"] = None
        elif bad == "weekend":
            policy["weekdays"] = [1, 2, 3, 4, 5, 6]
        elif bad == "empty_weekdays":
            policy["weekdays"] = []
        else:
            policy["availability_after_local"] = "25:00"
        value = yaml.safe_dump(raw).encode()
    cn_prewindow_schedule["bytes"] = value
    conn = _memory_db()
    dataset = _dataset(cadence_class="session_minute", freshness_sla_seconds=600)
    _insert_receipt(
        monkeypatch,
        conn,
        dataset=dataset,
        status="success",
        attempt_id="bad-policy",
        started_at="2026-08-28T07:00:00Z",
        finished_at="2026-08-28T07:10:00Z",
        data_through="2026-08-28T15:00:00+08:00",
    )
    with pytest.raises(RuntimeProjectionError, match="freshness schedule"):
        project_dataset_runtime(
            conn, dataset, now=datetime.fromisoformat("2026-08-31T00:00:00+08:00")
        )


def test_cn_prewindow_uses_configured_window_weekdays_and_cache(cn_prewindow_schedule):
    import yaml

    raw = yaml.safe_load(cn_prewindow_schedule["bytes"])
    raw["cadences"]["postclose_daily"]["availability_after_local"] = "17:15"
    raw["cadences"]["postclose_daily"]["weekdays"] = [2, 3, 4, 5]
    cn_prewindow_schedule["bytes"] = yaml.safe_dump(raw).encode()
    dataset = _dataset(cadence_class="postclose_daily")
    for now, expected in [
        ("2026-08-31T18:00:00+08:00", "2026-08-29T00:00:00+08:00"),
        ("2026-09-01T17:14:59+08:00", "2026-08-29T00:00:00+08:00"),
        ("2026-09-01T17:15:00+08:00", "2026-09-01T17:15:00+08:00"),
    ]:
        assert projection_module._freshness_clock_in_utc(
            dataset, datetime.fromisoformat(now)
        ) == datetime.fromisoformat(expected)
    assert cn_prewindow_schedule["reads"] == 1


@pytest.mark.parametrize(
    "market,tz,cadence",
    [
        ("CRYPTO", "Asia/Shanghai", "session_minute"),
        ("CN", "UTC", "postclose_daily"),
        ("CN", "Asia/Shanghai", "event"),
        ("CN", "Asia/Shanghai", "daily_reference"),
        ("CN", "Asia/Shanghai", "on_demand"),
    ],
)
def test_cn_prewindow_unrelated_clock_does_not_read_policy(
    cn_prewindow_schedule, market, tz, cadence
):
    cn_prewindow_schedule["bytes"] = FileNotFoundError(
        "unrelated policy must not be read"
    )
    dataset = replace(_dataset(cadence_class=cadence, timezone_name=tz), market=market)
    now = datetime.fromisoformat("2026-08-31T00:00:00+08:00")
    assert projection_module._freshness_clock_in_utc(dataset, now) == now
    assert cn_prewindow_schedule["reads"] == 0


@pytest.mark.parametrize(
    "status,config_mismatch,expected",
    [
        ("empty", False, "stale"),
        ("failed", False, "failed"),
        ("success", True, "unobserved"),
    ],
)
def test_cn_prewindow_preserves_non_success_paths(
    monkeypatch, cn_prewindow_schedule, status, config_mismatch, expected
):
    cn_prewindow_schedule["bytes"] = FileNotFoundError("must not load for this receipt")
    conn = _memory_db()
    dataset = _dataset(cadence_class="session_minute", freshness_sla_seconds=600)
    _insert_receipt(
        monkeypatch,
        conn,
        dataset=dataset,
        status=status,
        attempt_id="unchanged-path",
        config_hash="f" * 64 if config_mismatch else None,
        started_at="2026-08-28T07:00:00Z",
        finished_at="2026-08-28T07:10:00Z",
        data_through="2026-08-28T15:00:00+08:00" if status == "success" else None,
    )
    result = project_dataset_runtime(
        conn, dataset, now=datetime.fromisoformat("2026-08-31T00:00:00+08:00")
    )
    assert result.state == expected
    if status == "empty":
        assert result.reasons == ("freshness_sla_exceeded", "latest_receipt_empty")
    assert cn_prewindow_schedule["reads"] == 0


def test_cn_prewindow_rejects_symlink_schedule(
    monkeypatch, tmp_path, cn_prewindow_schedule
):
    root = tmp_path / "release"
    (root / "storage").mkdir(parents=True)
    (root / "config").mkdir()
    external = tmp_path / "outside.yaml"
    external.write_bytes(cn_prewindow_schedule["bytes"])
    (root / "config/provider_native_schedule.yaml").symlink_to(external)
    monkeypatch.setattr(
        projection_module, "__file__", str(root / "storage/receipt_projection.py")
    )
    with pytest.raises(RuntimeProjectionError, match="freshness schedule"):
        projection_module._freshness_clock_in_utc(
            _dataset(cadence_class="session_minute"),
            datetime.fromisoformat("2026-08-31T00:00:00+08:00"),
        )
