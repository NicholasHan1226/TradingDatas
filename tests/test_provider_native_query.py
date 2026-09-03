from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType

import pytest

import query_service as query_module
from catalog_service import inspect_dataset_queryability
from dataset_registry import (
    DatasetDefinition,
    DatasetField,
    DatasetRegistry,
    ProviderBinding,
    RequestWindowPolicy,
    load_dataset_registry,
)
from query_contract import QueryAccessContext, QueryExecutionOptions, QueryRequest
from query_cursor import SignedCursorCodec
from query_service import QueryService, QueryServiceUnavailable
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    DatasetRuntimeProjection,
    ValidatedReceiptHistories,
    validated_receipt_history_for_dataset,
)
import storage.ingest_receipts as receipt_module
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    ProviderRequestIdentity,
    insert_ingest_receipt,
    make_provider_call_attempt_id,
)


NOW = datetime(2026, 7, 17, 4, 0, tzinfo=timezone.utc)
SIGNING_KEY = b"provider-native-query-signing-key"


def _synthetic_transport_profile(provider: str) -> dict[str, object]:
    """Return a credential-free profile that cannot be mistaken for QuickSync."""

    payload: dict[str, object] = {
        "data_provider": provider,
        "endpoint": "memory://provider-native-query-fixture",
        "profile_id": f"synthetic-provider-native-query.{provider}.v1",
        "transport_service": "synthetic-test-harness",
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        **payload,
        "profile_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _synthetic_ingest_config_hash(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
) -> str:
    payload = {
        "api_name": binding.api_name,
        "dataset_id": dataset.dataset_id,
        "provider": binding.provider,
        "read_discriminator_value": binding.read_discriminator_value,
        "schema_version": dataset.schema_version,
        "transport_profile": _synthetic_transport_profile(binding.provider),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_numeric_leading_provider_field_uses_safe_json_path() -> None:
    assert query_module._provider_json_path("1m") == '$."1m"'
    assert query_module._provider_json_path("10day") == '$."10day"'
    with pytest.raises(QueryServiceUnavailable):
        query_module._provider_json_path('1m"].x')
    with pytest.raises(QueryServiceUnavailable):
        query_module._provider_json_path("a" * 65)


@lru_cache(maxsize=1)
def _native_dataset():
    base = load_dataset_registry().resolve("tushare.daily")
    fields = (
        DatasetField("symbol", "text", False, True, True, True),
        DatasetField("trade_date", "text", False, True, True, True),
        DatasetField("note", "text", True, True, True, True),
        DatasetField("big", "integer", True, True, True, True),
    )
    providers = (
        replace(
            base.provider_bindings[0],
            provider="provider-a",
            api_name="native_a",
            read_discriminator_value="native-a",
            target_tables=("provider_dataset_rows",),
            request_template=MappingProxyType({"trade_date": "${window.trade_date}"}),
            requested_fields=tuple(field.name for field in fields),
            max_rows_per_attempt=100,
            max_payload_bytes_per_row=4_096,
            max_batch_bytes=65_536,
            max_nesting_depth=4,
        ),
        replace(
            base.provider_bindings[0],
            provider="provider-b",
            api_name="native_b",
            read_discriminator_value="native-b",
            target_tables=("provider_dataset_rows",),
            request_template=MappingProxyType({"trade_date": "${window.trade_date}"}),
            requested_fields=tuple(field.name for field in fields),
            max_rows_per_attempt=100,
            max_payload_bytes_per_row=4_096,
            max_batch_bytes=65_536,
            max_nesting_depth=4,
        ),
    )
    return replace(
        base,
        dataset_id="cn.native.query",
        aliases=("tushare.native_query",),
        schema_version="1.2.0",
        fields=fields,
        primary_key=("symbol", "trade_date"),
        default_projection=("symbol", "trade_date", "note", "big"),
        as_of_field="trade_date",
        as_of_format="yyyymmdd",
        range_field="trade_date",
        partition_field="trade_date",
        max_page_size=10,
        max_lookback_days=365,
        point_in_time="current_snapshot",
        provider_bindings=providers,
        read_model_adapter=replace(
            base.read_model_adapter,
            storage_kind="provider_native_rows",
            row_key_strategy="primary_key",
            primary_table="provider_dataset_rows",
            fixed_field_filters=(),
        ),
    )


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE provider_dataset_rows ("
        "dataset_id TEXT NOT NULL, provider TEXT NOT NULL, "
        "schema_major INTEGER NOT NULL, ingested_schema_version TEXT NOT NULL, "
        "row_key TEXT NOT NULL, observed_at TEXT, partition_value TEXT, "
        "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "quality_state TEXT NOT NULL, quality_issues_json TEXT NOT NULL, "
        "collected_at TEXT NOT NULL, receipt_id TEXT NOT NULL, "
        "revision INTEGER NOT NULL, "
        "PRIMARY KEY(dataset_id, provider, schema_major, row_key)"
        ") WITHOUT ROWID"
    )
    conn.execute(
        "CREATE INDEX provider_dataset_rows_quality_idx "
        "ON provider_dataset_rows(dataset_id, provider, schema_major, quality_state)"
    )
    # Production DDL always carries the mandatory partition index; the
    # latest-partition MAX path force-uses it via INDEXED BY.
    conn.execute(
        "CREATE INDEX provider_dataset_rows_partition_idx "
        "ON provider_dataset_rows("
        "dataset_id, provider, schema_major, partition_value, row_key)"
    )
    conn.execute(
        "CREATE TABLE market_ingest_runs ("
        "run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, "
        "finished_at TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, "
        "rows_read INTEGER NOT NULL, rows_written INTEGER NOT NULL, notes TEXT NOT NULL"
        ")"
    )


def _insert_row(
    conn: sqlite3.Connection,
    *,
    dataset_id: str = "cn.native.query",
    provider: str = "provider-a",
    schema_major: int = 1,
    row_key: str,
    payload: dict[str, object],
    issues: tuple[str, ...] = (),
    receipt_id: str | None = None,
) -> str:
    # Query fixtures now carry real receipt envelopes. A fabricated ID alone
    # must no longer satisfy the production row-authority contract.
    if receipt_id is None and dataset_id == "cn.native.query" and provider in {
        "provider-a", "provider-b"
    }:
        with pytest.MonkeyPatch.context() as patch:
            receipt_id = _insert_native_success_receipt(
                patch, conn, _native_dataset(),
                execution_id="fixture." + hashlib.sha256(
                    f"{provider}:{schema_major}:{row_key}".encode()
                ).hexdigest()[:16],
                call_index=0, page_offset=0, provider=provider,
                request_window={"trade_date": str(payload.get("trade_date", "20260715"))},
                data_through=str(payload.get("trade_date", "20260715")),
            )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    conn.execute(
        "INSERT INTO provider_dataset_rows VALUES "
        "(?, ?, ?, '1.2.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            dataset_id,
            provider,
            schema_major,
            row_key,
            payload.get("trade_date"),
            payload.get("trade_date"),
            canonical,
            "a" * 64,
            "degraded" if issues else "valid",
            json.dumps(list(issues), separators=(",", ":")),
            "2026-07-17T03:00:00+00:00",
            receipt_id or f"receipt:{provider}:{row_key}",
        ),
    )
    return receipt_id or f"receipt:{provider}:{row_key}"


def _insert_native_success_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    execution_id: str,
    call_index: int,
    page_offset: int,
    retry_index: int = 0,
    request_page_index: int | None = None,
    request_window: dict[str, str] | None = None,
    provider: str = "provider-a",
    config_hash: str | None = None,
    data_through: str | None = "20260715",
    started_at: str = "2026-07-17T03:00:00+00:00",
    finished_at: str | None = None,
) -> str:
    finished_at = finished_at or f"2026-07-17T03:0{call_index + 1}:00+00:00"
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    binding = next(item for item in dataset.provider_bindings if item.provider == provider)
    context = IngestContext(
        attempt_id=make_provider_call_attempt_id(
            execution_id,
            call_index=call_index,
            retry_index=retry_index,
        ),
        dataset_id=dataset.dataset_id,
        provider=provider,
        provider_api=binding.api_name,
        request_window=(
            {"trade_date": "20260715"}
            if request_window is None
            else request_window
        ),
        config_hash=config_hash or _synthetic_ingest_config_hash(dataset, binding),
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=data_through,
        request_identity=ProviderRequestIdentity(
            request_variant={},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=page_offset,
            page_index=(
                call_index if request_page_index is None else request_page_index
            ),
        ),
    )
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
    return insert_ingest_receipt(
        conn,
        context=context,
        target_table="provider_dataset_rows",
        transaction_index=call_index,
        status="success",
        counts=counts,
        errors=(),
        payload_fingerprint="b" * 64,
    )


def _insert_native_failed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    execution_id: str,
    call_index: int,
    retry_index: int = 0,
    request_window: dict[str, str] | None = None,
    data_through: str | None = "20260715",
    started_at: str = "2026-07-17T03:00:00+00:00",
    finished_at: str = "2026-07-17T03:03:00+00:00",
) -> str:
    binding = next(item for item in dataset.provider_bindings if item.provider == "provider-a")
    context = IngestContext(
        attempt_id=make_provider_call_attempt_id(
            execution_id, call_index=call_index, retry_index=retry_index
        ),
        dataset_id=dataset.dataset_id,
        provider="provider-a",
        provider_api=binding.api_name,
        request_window=(
            {"trade_date": "20260715"}
            if request_window is None
            else request_window
        ),
        config_hash=_synthetic_ingest_config_hash(dataset, binding),
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=data_through,
        request_identity=ProviderRequestIdentity(
            request_variant={},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=call_index,
            page_index=call_index,
        ),
    )
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    return insert_ingest_receipt(
        conn,
        context=context,
        target_table=None,
        transaction_index=call_index,
        status="failed",
        counts=IngestCounts(
            returned=0,
            validated=0,
            inserted=0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=0,
            count_semantics="terminal_no_data_transaction",
        ),
        errors=("provider_error",),
        payload_fingerprint="c" * 64,
    )


@pytest.fixture
def native_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dataset = _native_dataset()
    source = load_dataset_registry()
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(
            source.query_defaults,
            cursor_ttl_seconds=60,
            sqlite_progress_steps=1_000_000,
        ),
    )
    conn = sqlite3.connect(":memory:")
    _create_table(conn)
    _insert_row(
        conn,
        provider="provider-a",
        row_key="row-a",
        payload={
            "symbol": "AAA",
            "trade_date": "20260715",
            "big": 2**70,
            "dataset_id": "forged-dataset",
            "provider": "forged-provider",
            "schema_major": 999,
        },
        issues=(
            "integer_out_of_int64:big",
            "missing_field:note",
            "unknown_field:dataset_id",
            "unknown_field:provider",
            "unknown_field:schema_major",
        ),
    )
    _insert_row(
        conn,
        provider="provider-a",
        row_key="row-b",
        payload={
            "symbol": "BBB",
            "trade_date": "20260716",
            "note": None,
            "big": 2,
        },
    )
    _insert_row(
        conn,
        provider="provider-b",
        row_key="row-c",
        payload={
            "symbol": "BBB",
            "trade_date": "20260716",
            "note": "provider-b",
            "big": 3,
        },
    )
    _insert_row(
        conn,
        dataset_id="cn.other.dataset",
        provider="provider-a",
        row_key="leak-dataset",
        payload={"symbol": "LEAK-DATASET", "trade_date": "20260716"},
    )
    _insert_row(
        conn,
        provider="rogue-provider",
        row_key="leak-provider",
        payload={"symbol": "LEAK-PROVIDER", "trade_date": "20260716"},
    )
    _insert_row(
        conn,
        provider="provider-a",
        schema_major=2,
        row_key="leak-schema",
        payload={"symbol": "LEAK-SCHEMA", "trade_date": "20260716"},
    )
    conn.commit()

    @contextmanager
    def snapshot(_path: Path):
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="success",
            degraded=False,
            data_through="20260716",
            observed_at="2026-07-16T15:00:00+00:00",
            receipt_id="receipt-current",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("provider-a", "provider-b"),
        last_success_receipt_id="receipt-current",
        last_success_providers=("provider-a", "provider-b"),
        last_success_data_through="20260716",
        current_receipt_ids=("receipt-current",),
        last_success_receipt_ids=("receipt-current",),
    )

    baseline_receipt_ids = tuple(sorted({
        "receipt-current",
        *(row[0] for row in conn.execute(
            "SELECT receipt_id FROM provider_dataset_rows "
            "WHERE dataset_id = ? AND schema_major = 1 AND provider IN (?, ?)",
            (dataset.dataset_id, "provider-a", "provider-b"),
        )),
    }))

    def project(*_args: object, **kwargs: object) -> DatasetRuntimeEvidence:
        if kwargs.get("evidence_as_of") is None:
            return evidence
        return replace(
            evidence,
            as_of_success_receipt_ids=baseline_receipt_ids,
        )

    monkeypatch.setattr(
        query_module,
        "provider_transport_profile",
        _synthetic_transport_profile,
    )
    monkeypatch.setattr(
        query_module,
        "provider_ingest_config_hash",
        _synthetic_ingest_config_hash,
    )
    monkeypatch.setattr(query_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", project)
    yield {
        "conn": conn,
        "dataset": dataset,
        "registry": registry,
        "service": QueryService(
            db_path=(tmp_path / "native.sqlite").absolute(),
            registry=registry,
            cursor_codec=SignedCursorCodec(SIGNING_KEY),
        ),
        "access": QueryAccessContext.from_grants(
            tenant_id="tenant-native",
            scopes=("market_data",),
            allowed_dataset_ids=(),
        ),
    }
    conn.close()


def _request(
    *,
    fields: tuple[str, ...] = ("symbol", "trade_date", "note", "big"),
    filters: dict[str, object] | None = None,
    order: tuple[str, ...] | None = ("symbol:asc",),
    as_of: str | None = None,
    limit: int = 10,
    cursor: str | None = None,
    include_receipt_proofs: bool = False,
) -> QueryRequest:
    return QueryRequest(
        dataset_id="cn.native.query",
        schema_major=1,
        fields=fields,
        filters={} if filters is None else filters,
        as_of=as_of,
        order=order,
        limit=limit,
        cursor=cursor,
        include_receipt_proofs=include_receipt_proofs,
    )


def _execute(
    harness: dict[str, object],
    request: QueryRequest,
    *,
    options: QueryExecutionOptions = QueryExecutionOptions(),
) -> dict[str, object]:
    return harness["service"].execute(
        request,
        access=harness["access"],
        now=NOW,
        request_id="request-native",
        options=options,
    )


def _proof_evidence(receipt_ids: tuple[str, ...]) -> DatasetRuntimeEvidence:
    return DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id="cn.native.query",
            state="success",
            degraded=False,
            data_through="20260715",
            observed_at="2026-07-17T03:02:00+00:00",
            receipt_id=receipt_ids[-1],
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("provider-a",),
        last_success_receipt_id=receipt_ids[-1],
        last_success_providers=("provider-a",),
        last_success_data_through="20260715",
        current_receipt_ids=tuple(sorted(receipt_ids)),
        last_success_receipt_ids=tuple(sorted(receipt_ids)),
    )


def _minute_dataset(base: DatasetDefinition) -> DatasetDefinition:
    fields = (*base.fields, DatasetField("time", "text", False, True, True, True))
    bindings = tuple(
        replace(
            binding,
            requested_fields=tuple(field.name for field in fields),
            response_completeness=replace(
                binding.response_completeness,
                snapshot_field="time",
            ),
            request_window_policy=RequestWindowPolicy(
                required_keys=("bar_time",),
                formats=MappingProxyType({"bar_time": "local_datetime_seconds"}),
                range_start_key="bar_time",
                range_end_key="bar_time",
                max_span_days=1,
            ),
        )
        for binding in base.provider_bindings
    )
    return replace(
        base,
        dataset_id="cn.native.minute",
        aliases=("tushare.native_minute",),
        fields=fields,
        primary_key=("symbol", "time"),
        default_projection=("symbol", "time"),
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
        cadence_class="session_minute",
        provider_bindings=bindings,
    )


def _minute_service_harness(
    native_harness: dict[str, object],
) -> tuple[DatasetDefinition, DatasetRegistry, QueryService]:
    minute = _minute_dataset(native_harness["dataset"])
    registry = DatasetRegistry((minute,), query_defaults=native_harness["registry"].query_defaults)
    return minute, registry, QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )


def _large_minute_service_harness(
    native_harness: dict[str, object],
) -> tuple[DatasetDefinition, DatasetRegistry]:
    minute = _minute_dataset(native_harness["dataset"])
    unrelated = tuple(
        replace(
            minute,
            dataset_id=f"cn.native.unrelated.{index:03d}",
            aliases=(),
            provider_bindings=tuple(
                replace(
                    binding,
                    api_name=f"{binding.api_name}.unrelated.{index:03d}",
                    read_discriminator_value=f"{binding.read_discriminator_value}.unrelated.{index:03d}",
                )
                for binding in minute.provider_bindings
            ),
        )
        for index in range(189)
    )
    registry = DatasetRegistry(
        (minute, *unrelated),
        query_defaults=native_harness["registry"].query_defaults,
    )
    return minute, registry


def test_opt_in_query_returns_each_row_receipt_proof_from_real_receipts(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    first = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="proof-execution", call_index=0, page_offset=0
    )
    second = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="proof-execution", call_index=1, page_offset=1
    )
    _insert_row(conn, provider="provider-a", row_key="proof-a", payload={"symbol": "PROOF_A", "trade_date": "20260715"}, receipt_id=first)
    _insert_row(conn, provider="provider-a", row_key="proof-b", payload={"symbol": "PROOF_B", "trade_date": "20260715"}, receipt_id=second)
    conn.commit()
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: _proof_evidence((first, second)))
    request = _request(
        fields=("symbol",),
        filters={"symbol": {"in": ["PROOF_A", "PROOF_B"]}},
        limit=10,
    )
    legacy = _execute(native_harness, request)
    opt_in = _execute(native_harness, replace(request, include_receipt_proofs=True))
    explicit_false = _execute(native_harness, replace(request, include_receipt_proofs=False))
    assert "row_receipt_proofs" not in legacy["metadata"]
    assert query_module._canonical_json_bytes(legacy) == query_module._canonical_json_bytes(explicit_false)
    proofs = opt_in["metadata"]["row_receipt_proofs"]
    assert len(opt_in["data"]) == len(proofs) == 2
    assert [row["symbol"] for row in opt_in["data"]] == ["PROOF_A", "PROOF_B"]
    assert [item["page_index"] for item in proofs] == [0, 1]
    assert [item["receipt_id"] for item in proofs] == [first, second]
    assert [item["provider"] for item in proofs] == ["provider-a", "provider-a"]
    assert all(item["source"] == item["provider"] for item in proofs)
    assert all(item["row_identity_sha256"] for item in proofs)

    first_page = _execute(
        native_harness,
        replace(request, include_receipt_proofs=True, limit=1),
    )
    second_page = _execute(
        native_harness,
        replace(
            request,
            include_receipt_proofs=True,
            limit=1,
            cursor=first_page["next_cursor"],
        ),
    )
    assert [row["symbol"] for row in first_page["data"]] == ["PROOF_A"]
    assert [item["page_index"] for item in first_page["metadata"]["row_receipt_proofs"]] == [0]
    assert [row["symbol"] for row in second_page["data"]] == ["PROOF_B"]
    assert [item["page_index"] for item in second_page["metadata"]["row_receipt_proofs"]] == [0]
    assert first_page["metadata"]["row_receipt_proofs"][0]["receipt_id"] == first
    assert second_page["metadata"]["row_receipt_proofs"][0]["receipt_id"] == second


def test_b2_full_query_uses_target_receipt_history_under_large_registry(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    base = _minute_dataset(native_harness["dataset"])
    unrelated = tuple(
        replace(
            base,
            dataset_id=f"cn.native.unrelated.{index:03d}",
            aliases=(),
            provider_bindings=tuple(
                replace(
                    binding,
                    api_name=f"{binding.api_name}.unrelated.{index:03d}",
                    read_discriminator_value=f"{binding.read_discriminator_value}.unrelated.{index:03d}",
                )
                for binding in base.provider_bindings
            ),
        )
        for index in range(189)
    )
    registry = DatasetRegistry(
        (base, *unrelated),
        query_defaults=native_harness["registry"].query_defaults,
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    slot = "2026-08-13 09:40:00"
    receipt_ids: list[str] = []
    for call_index in range(6):
        receipt_ids.append(
            _insert_native_success_receipt(
                monkeypatch,
                conn,
                base,
                execution_id="slot-success",
                call_index=call_index,
                page_offset=call_index,
                request_window={},
                data_through=slot,
                started_at="2026-08-13T01:39:00+00:00",
                finished_at=f"2026-08-13T01:40:{call_index:02d}+00:00",
            )
        )
    for index in range(30):
        _insert_row(
            conn,
            dataset_id=base.dataset_id,
            provider="provider-a",
            row_key=f"slot-{index:02d}",
            payload={"symbol": f"SLOT_{index:02d}", "time": slot},
            receipt_id=receipt_ids[index % 5],
        )
    for index, dataset in enumerate(unrelated):
        _insert_native_success_receipt(
            monkeypatch,
            conn,
            dataset,
            execution_id=f"unrelated-{index:03d}",
            call_index=0,
            page_offset=0,
            request_window={},
            data_through=slot,
            started_at="2026-08-13T01:39:00+00:00",
            finished_at="2026-08-13T01:40:00+00:00",
        )
    conn.execute(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("receipt:unrelated-malformed", "2026-08-13T01:39:00+00:00", "2026-08-13T01:40:00+00:00", "success", unrelated[0].dataset_id, 1, 1, "{"),
    )
    later_failed = _insert_native_failed_receipt(
        monkeypatch, conn, base, execution_id="slot-later-failed", call_index=0,
        request_window={}, data_through="2026-08-13 11:10:00",
        started_at="2026-08-13T03:09:00+00:00", finished_at="2026-08-13T03:10:00+00:00",
    )
    conn.commit()
    latest = replace(
        _proof_evidence((later_failed,)),
        projection=replace(_proof_evidence((later_failed,)).projection, dataset_id=base.dataset_id, state="failed", degraded=True),
        current_receipt_status="failed", current_receipt_ids=(later_failed,),
        last_success_receipt_ids=tuple(sorted(receipt_ids)),
    )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: latest)
    request = QueryRequest(
        dataset_id=base.dataset_id, schema_major=1, fields=("symbol", "time"),
        filters={"time": {"eq": slot}}, as_of=None,
        order=("time:asc", "symbol:asc"), limit=10, cursor=None, include_receipt_proofs=True,
    )
    now = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    response = service.execute(request, access=native_harness["access"], now=now, request_id="b2-full")
    proofs = response["metadata"]["row_receipt_proofs"]
    assert len(response["data"]) == len(proofs) == 10
    assert [row["symbol"] for row in response["data"]] == [f"SLOT_{i:02d}" for i in range(10)]
    assert [item["receipt_id"] for item in proofs] == [receipt_ids[i % 5] for i in range(10)]
    first = response
    second = service.execute(replace(request, cursor=first["next_cursor"]), access=native_harness["access"], now=now, request_id="b2-page-2")
    third = service.execute(replace(request, cursor=second["next_cursor"]), access=native_harness["access"], now=now, request_id="b2-page-3")
    assert len(first["data"]) == len(first["metadata"]["row_receipt_proofs"]) == 10
    assert len(second["data"]) == len(second["metadata"]["row_receipt_proofs"]) == 10
    assert len(third["data"]) == len(third["metadata"]["row_receipt_proofs"]) == 10
    assert [row["symbol"] for row in second["data"]] == [f"SLOT_{i:02d}" for i in range(10, 20)]
    assert [row["symbol"] for row in third["data"]] == [f"SLOT_{i:02d}" for i in range(20, 30)]


def test_explicit_no_window_slot_selects_prior_success_over_latest_failed_cohort(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute, registry, service = _minute_service_harness(native_harness)
    slot = "2026-08-13 09:40:00"
    slot_rows: list[tuple[str, str]] = []
    slot_receipts: list[str] = []
    for call_index in range(6):
        receipt_id = _insert_native_success_receipt(
            monkeypatch,
            conn,
            minute,
            execution_id="slot-success",
            call_index=call_index,
            page_offset=call_index,
            request_window={},
            data_through=slot,
            started_at="2026-08-13T01:39:00+00:00",
            finished_at=f"2026-08-13T01:40:{call_index:02d}+00:00",
        )
        symbol = f"SLOT_{call_index:02d}"
        slot_receipts.append(receipt_id)
        slot_rows.append((symbol, receipt_id))
        _insert_row(
            conn,
            dataset_id=minute.dataset_id,
            provider="provider-a",
            row_key=f"slot-success-{call_index}",
            payload={"symbol": symbol, "time": slot},
            receipt_id=receipt_id,
        )
    for call_index in range(6):
        _insert_native_success_receipt(
            monkeypatch,
            conn,
            minute,
            execution_id="slot-overlap-success",
            call_index=call_index,
            page_offset=call_index,
            request_window={},
            data_through=slot,
            started_at="2026-08-13T01:41:00+00:00",
            finished_at=f"2026-08-13T01:42:{call_index:02d}+00:00",
        )
    failed = _insert_native_failed_receipt(
        monkeypatch,
        conn,
        minute,
        execution_id="slot-failed",
        call_index=0,
        request_window={},
        data_through="2026-08-13 11:10:00",
        started_at="2026-08-13T03:09:00+00:00",
        finished_at="2026-08-13T03:10:00+00:00",
    )
    conn.commit()
    latest = replace(
        _proof_evidence((failed,)),
        projection=replace(_proof_evidence((failed,)).projection, dataset_id=minute.dataset_id, state="failed", degraded=True),
        current_receipt_status="failed",
        current_receipt_ids=(failed,),
        last_success_receipt_ids=tuple(sorted(slot_receipts)),
    )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: latest)
    request = QueryRequest(
        dataset_id=minute.dataset_id, schema_major=1, fields=("symbol", "time"),
        filters={"time": {"eq": slot}}, as_of=None,
        order=("time:asc", "symbol:asc"), limit=10, cursor=None, include_receipt_proofs=True,
    )
    slot_now = datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc)
    response = service.execute(request, access=native_harness["access"], now=slot_now, request_id="explicit-slot")
    assert [row["symbol"] for row in response["data"]] == [f"SLOT_{i:02d}" for i in range(6)]
    assert response["metadata"]["runtime_state"] == "failed"
    assert [item["receipt_id"] for item in response["metadata"]["row_receipt_proofs"]] == slot_receipts
    assert len(response["data"]) == len(response["metadata"]["row_receipt_proofs"]) == 6

    default = service.execute(
        replace(request, filters={"symbol": {"in": [symbol for symbol, _ in slot_rows]}}),
        access=native_harness["access"], now=slot_now, request_id="latest-slot",
    )
    assert default["data"] == []
    assert default["metadata"]["runtime_state"] == "failed"

    first_page = service.execute(
        replace(request, limit=3),
        access=native_harness["access"], now=slot_now, request_id="explicit-slot-page-1",
    )
    second_page = service.execute(
        replace(
            request,
            include_receipt_proofs=True,
            limit=3,
            cursor=first_page["next_cursor"],
        ),
        access=native_harness["access"], now=slot_now, request_id="explicit-slot-page-2",
    )
    assert [row["symbol"] for row in first_page["data"]] == [f"SLOT_{i:02d}" for i in range(3)]
    assert [row["symbol"] for row in second_page["data"]] == [f"SLOT_{i:02d}" for i in range(3, 6)]
    assert [item["receipt_id"] for item in first_page["metadata"]["row_receipt_proofs"]] == slot_receipts[:3]
    assert [item["receipt_id"] for item in second_page["metadata"]["row_receipt_proofs"]] == slot_receipts[3:]


def test_target_history_uses_source_filter_with_large_registry(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute, registry = _large_minute_service_harness(native_harness)
    slot = "2026-08-13 09:40:00"
    slot_receipts: list[str] = []
    for call_index in range(6):
        slot_receipts.append(
            _insert_native_success_receipt(
                monkeypatch,
                conn,
                minute,
                execution_id="slot-success",
                call_index=call_index,
                page_offset=call_index,
                request_window={},
                data_through=slot,
                started_at="2026-08-13T01:39:00+00:00",
                finished_at=f"2026-08-13T01:40:{call_index:02d}+00:00",
            )
        )
    for dataset_index, unrelated_dataset in enumerate(registry.datasets[1:]):
        for call_index in range(20):
            _insert_native_success_receipt(
                monkeypatch,
                conn,
                unrelated_dataset,
                execution_id=f"unrelated-{dataset_index:03d}",
                call_index=call_index,
                page_offset=call_index,
                request_window={},
                data_through=slot,
                started_at="2026-08-13T01:39:00+00:00",
                finished_at=f"2026-08-13T01:40:{call_index % 60:02d}+00:00",
            )
    conn.execute(
        "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "receipt:unrelated-malformed",
            "2026-08-13T01:39:00+00:00",
            "2026-08-13T01:40:00+00:00",
            "success",
            registry.datasets[1].dataset_id,
            1,
            1,
            "{",
        ),
    )
    conn.commit()
    histories = validated_receipt_history_for_dataset(
        conn,
        registry,
        minute,
        now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc),
    )
    assert not histories.failures_by_dataset
    assert tuple(entry.receipt_id for entry in histories.entries_by_dataset[minute.dataset_id]) == tuple(slot_receipts)


@pytest.mark.parametrize("kind", ("missing", "failed_only"))
def test_explicit_no_window_slot_requires_successful_requested_cohort(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    conn = native_harness["conn"]
    minute, _registry, service = _minute_service_harness(native_harness)
    requested = "2026-08-13 09:40:00"
    if kind == "missing":
        receipt_id = _insert_native_success_receipt(
            monkeypatch,
            conn,
            minute,
            execution_id="other-slot",
            call_index=0,
            page_offset=0,
            request_window={},
            data_through="2026-08-13 09:35:00",
            started_at="2026-08-13T01:34:00+00:00",
            finished_at="2026-08-13T01:35:00+00:00",
        )
    else:
        receipt_id = _insert_native_failed_receipt(
            monkeypatch,
            conn,
            minute,
            execution_id="failed-slot",
            call_index=0,
            request_window={},
            data_through=requested,
            started_at="2026-08-13T01:39:00+00:00",
            finished_at="2026-08-13T01:40:00+00:00",
        )
    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key=f"{kind}-slot",
        payload={"symbol": kind.upper(), "time": requested},
        receipt_id=receipt_id,
    )
    conn.commit()
    evidence = replace(
        _proof_evidence((receipt_id,)),
        projection=replace(
            _proof_evidence((receipt_id,)).projection,
            dataset_id=minute.dataset_id,
            state="failed" if kind == "failed_only" else "success",
        ),
        current_receipt_status="failed" if kind == "failed_only" else "success",
        current_receipt_ids=(receipt_id,),
    )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: evidence)
    request = QueryRequest(
        dataset_id=minute.dataset_id,
        schema_major=1,
        fields=("symbol", "time"),
        filters={"time": {"eq": requested}},
        as_of=None,
        order=("time:asc", "symbol:asc"),
        limit=10,
        cursor=None,
        include_receipt_proofs=True,
    )
    with pytest.raises(QueryServiceUnavailable):
        service.execute(
            request,
            access=native_harness["access"],
            now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc),
            request_id=f"missing-slot-{kind}",
        )


def test_explicit_no_window_slot_ignores_unrelated_dataset_authority_failure(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute = _minute_dataset(native_harness["dataset"])
    unrelated = replace(
        minute,
        dataset_id="cn.native.unrelated",
        aliases=(),
        provider_bindings=tuple(
            replace(
                binding,
                api_name=f"{binding.api_name}_unrelated",
                read_discriminator_value=f"{binding.read_discriminator_value}-unrelated",
            )
            for binding in minute.provider_bindings
        ),
    )
    registry = DatasetRegistry(
        (minute, unrelated), query_defaults=native_harness["registry"].query_defaults
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    slot = "2026-08-13 09:40:00"
    receipt_id = _insert_native_success_receipt(
        monkeypatch,
        conn,
        minute,
        execution_id="unrelated-authority-current",
        call_index=0,
        page_offset=0,
        request_window={},
        data_through=slot,
        started_at="2026-08-13T01:39:00+00:00",
        finished_at="2026-08-13T01:40:00+00:00",
    )
    _insert_native_success_receipt(
        monkeypatch,
        conn,
        unrelated,
        execution_id="unrelated-authority-invalid",
        call_index=0,
        page_offset=0,
        request_window={},
        data_through=None,
        started_at="2026-08-13T01:39:00+00:00",
        finished_at="2026-08-13T01:40:00+00:00",
    )
    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key="unrelated-authority-row",
        payload={"symbol": "UNRELATED_AUTHORITY", "time": slot},
        receipt_id=receipt_id,
    )
    conn.commit()
    evidence = replace(
        _proof_evidence((receipt_id,)),
        projection=replace(_proof_evidence((receipt_id,)).projection, dataset_id=minute.dataset_id),
        current_receipt_ids=(receipt_id,),
    )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: evidence)
    response = service.execute(
        QueryRequest(
            dataset_id=minute.dataset_id,
            schema_major=1,
            fields=("symbol", "time"),
            filters={"time": {"eq": slot}},
            as_of=None,
            order=("time:asc", "symbol:asc"),
            limit=10,
            cursor=None,
            include_receipt_proofs=True,
        ),
        access=native_harness["access"],
        now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc),
        request_id="unrelated-authority",
    )
    assert response["data"] == [{"symbol": "UNRELATED_AUTHORITY", "time": slot}]


def test_explicit_no_window_slot_rejects_target_dataset_authority_failure(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    minute, _registry, service = _minute_service_harness(native_harness)
    histories = ValidatedReceiptHistories(
        entries_by_dataset={},
        failures_by_dataset={minute.dataset_id: ("receipt_execution_inconsistent",)},
    )
    monkeypatch.setattr(
        query_module,
        "validated_receipt_history_for_dataset",
        lambda *args, **kwargs: histories,
    )
    with pytest.raises(QueryServiceUnavailable):
        service.execute(
            QueryRequest(
                dataset_id=minute.dataset_id,
                schema_major=1,
                fields=("symbol", "time"),
                filters={"time": {"eq": "2026-08-13 09:40:00"}},
                as_of=None,
                order=("time:asc", "symbol:asc"),
                limit=10,
                cursor=None,
                include_receipt_proofs=True,
            ),
            access=native_harness["access"],
            now=datetime(2026, 8, 13, 4, 0, tzinfo=timezone.utc),
            request_id="target-authority",
        )


def test_opt_in_query_rejects_row_provider_mismatch_and_cross_window(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    first = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="proof-mismatch", call_index=0, page_offset=0
    )
    second = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="proof-other-window", call_index=1, page_offset=1, request_window={"trade_date": "20260716"}
    )
    _insert_row(conn, provider="provider-b", row_key="proof-provider-mismatch", payload={"symbol": "MISMATCH_PROVIDER", "trade_date": "20260715"}, receipt_id=first)
    _insert_row(conn, provider="provider-a", row_key="proof-cross-window", payload={"symbol": "MISMATCH_WINDOW", "trade_date": "20260716"}, receipt_id=second)
    conn.commit()
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: _proof_evidence((first, second)))
    request = _request(
        fields=("symbol",),
        filters={"symbol": {"in": ["MISMATCH_PROVIDER", "MISMATCH_WINDOW"]}},
        limit=10,
        include_receipt_proofs=True,
    )
    with pytest.raises(QueryServiceUnavailable):
        _execute(native_harness, request)


@pytest.mark.parametrize("failure_kind", ("missing", "failed"))
def test_opt_in_query_rejects_missing_or_failed_receipt_proof(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    receipt_id = (
        "receipt:missing-proof"
        if failure_kind == "missing"
        else _insert_native_failed_receipt(
            monkeypatch, conn, dataset, execution_id="proof-failed", call_index=0
        )
    )
    _insert_row(
        conn,
        provider="provider-a",
        row_key=f"proof-{failure_kind}",
        payload={"symbol": f"MISSING_{failure_kind.upper()}", "trade_date": "20260715"},
        receipt_id=receipt_id,
    )
    conn.commit()
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: _proof_evidence((receipt_id,)),
    )
    request = _request(
        fields=("symbol",),
        filters={"symbol": {"in": [f"MISSING_{failure_kind.upper()}"]}},
        include_receipt_proofs=True,
    )
    with pytest.raises(QueryServiceUnavailable):
        _execute(native_harness, request)


def test_opt_in_query_accepts_single_receipt_and_rejects_cross_execution_config_data_through(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    receipt_id = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="single-proof", call_index=0, page_offset=0
    )
    _insert_row(
        conn,
        provider="provider-a",
        row_key="proof-single",
        payload={"symbol": "SINGLE_PROOF", "trade_date": "20260715"},
        receipt_id=receipt_id,
    )
    conn.commit()
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: _proof_evidence((receipt_id,)),
    )
    response = _execute(
        native_harness,
        _request(
            fields=("symbol",),
            filters={"symbol": {"in": ["SINGLE_PROOF"]}},
            include_receipt_proofs=True,
        ),
    )
    assert len(response["data"]) == len(response["metadata"]["row_receipt_proofs"]) == 1

    for suffix, kwargs in (
        ("execution", {"config_hash": None}),
        ("config", {"config_hash": "d" * 64}),
        ("through", {"data_through": "20260716"}),
    ):
        other = _insert_native_success_receipt(
            monkeypatch,
            conn,
            dataset,
            execution_id=f"other-{suffix}-proof",
            call_index=1,
            page_offset=1,
            **kwargs,
        )
        symbol = f"MISMATCH_{suffix.upper()}"
        _insert_row(
            conn,
            provider="provider-a",
            row_key=f"proof-{suffix}",
            payload={"symbol": symbol, "trade_date": "20260715"},
            receipt_id=other,
        )
        conn.commit()
        monkeypatch.setattr(
            query_module,
            "project_dataset_runtime_evidence",
            lambda *args, ids=(receipt_id, other), **kwargs: _proof_evidence(ids),
        )
        with pytest.raises(QueryServiceUnavailable):
            _execute(
                native_harness,
                _request(
                    fields=("symbol",),
                    filters={"symbol": {"in": ["SINGLE_PROOF", symbol]}},
                    include_receipt_proofs=True,
                ),
            )


def test_opt_in_no_window_session_minute_requires_exact_closed_slot_time(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute = _minute_dataset(native_harness["dataset"])
    registry = DatasetRegistry(
        (minute,), query_defaults=native_harness["registry"].query_defaults
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    first = _insert_native_success_receipt(
        monkeypatch, conn, minute, execution_id="minute-proof", call_index=0, page_offset=0,
        request_window={},
        data_through="2026-07-17 11:40:00",
    )
    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key="minute-a",
        payload={"symbol": "MINUTE_A", "time": "2026-07-17 11:40:00"},
        receipt_id=first,
    )
    conn.commit()
    evidence = replace(_proof_evidence((first,)), projection=replace(
        _proof_evidence((first,)).projection, dataset_id=minute.dataset_id,
    ))
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: evidence)
    request = QueryRequest(
        dataset_id=minute.dataset_id,
        schema_major=1,
        fields=("symbol", "time"),
        filters={"symbol": {"in": ["MINUTE_A"]}},
        as_of=None,
        order=("time:asc", "symbol:asc"),
        limit=10,
        cursor=None,
        include_receipt_proofs=True,
    )
    result = service.execute(
        request,
        access=native_harness["access"],
        now=NOW,
        request_id="request-minute-proof",
    )
    assert result["data"][0]["time"] == "2026-07-17 11:40:00"
    assert result["metadata"]["row_receipt_proofs"][0]["receipt_id"] == first

    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key="minute-b",
        payload={"symbol": "MINUTE_B", "time": "2026-07-17T03:41:00+00:00"},
        receipt_id=first,
    )
    conn.commit()
    with pytest.raises(QueryServiceUnavailable):
        service.execute(
            replace(request, filters={"symbol": {"in": ["MINUTE_A", "MINUTE_B"]}}),
            access=native_harness["access"],
            now=NOW,
            request_id="request-minute-proof-mismatch",
        )


def test_no_window_session_minute_accepts_consistent_request_window(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute = _minute_dataset(native_harness["dataset"])
    registry = DatasetRegistry(
        (minute,), query_defaults=native_harness["registry"].query_defaults
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    receipt = _insert_native_success_receipt(
        monkeypatch,
        conn,
        minute,
        execution_id="minute-window-proof",
        call_index=0,
        page_offset=0,
        request_window={"bar_time": "2026-07-17 11:35:00"},
        data_through="2026-07-17 11:40:00",
    )
    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key="minute-window-a",
        payload={"symbol": "MINUTE_WINDOW_A", "time": "2026-07-17 11:40:00"},
        receipt_id=receipt,
    )
    conn.commit()
    evidence = replace(
        _proof_evidence((receipt,)),
        projection=replace(
            _proof_evidence((receipt,)).projection,
            dataset_id=minute.dataset_id,
        ),
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: evidence,
    )
    request = QueryRequest(
        dataset_id=minute.dataset_id,
        schema_major=1,
        fields=("symbol", "time"),
        filters={
            "symbol": {"eq": "MINUTE_WINDOW_A"},
            "time": {"eq": "2026-07-17 11:40:00"},
        },
        as_of=None,
        order=("time:asc", "symbol:asc"),
        limit=10,
        cursor=None,
        include_receipt_proofs=True,
    )
    result = service.execute(
        request,
        access=native_harness["access"],
        now=NOW,
        request_id="request-minute-window-proof",
    )
    assert result["data"][0]["symbol"] == "MINUTE_WINDOW_A"
    assert result["metadata"]["row_receipt_proofs"][0]["receipt_id"] == receipt

    future_window_receipt = _insert_native_success_receipt(
        monkeypatch,
        conn,
        minute,
        execution_id="minute-window-after-event",
        call_index=0,
        page_offset=0,
        request_window={"bar_time": "2026-07-17 11:45:00"},
        data_through="2026-07-17 11:40:00",
    )
    _insert_row(
        conn,
        dataset_id=minute.dataset_id,
        provider="provider-a",
        row_key="minute-window-after-event",
        payload={"symbol": "MINUTE_WINDOW_AFTER", "time": "2026-07-17 11:40:00"},
        receipt_id=future_window_receipt,
    )
    conn.commit()
    with pytest.raises(QueryServiceUnavailable):
        service.execute(
            replace(
                request,
                filters={
                    "symbol": {"eq": "MINUTE_WINDOW_AFTER"},
                    "time": {"eq": "2026-07-17 11:40:00"},
                },
            ),
            access=native_harness["access"],
            now=NOW,
            request_id="request-minute-window-after-event",
        )


@pytest.mark.parametrize(
    "variant",
    ("wrong_cadence", "missing_snapshot", "future", "missing_data_through", "row_mismatch"),
)
def test_opt_in_no_window_session_minute_fail_closed_boundaries(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    conn = native_harness["conn"]
    minute = _minute_dataset(native_harness["dataset"])
    if variant == "wrong_cadence":
        minute = replace(minute, cadence_class="postclose_daily")
    elif variant == "missing_snapshot":
        minute = replace(
            minute,
            provider_bindings=tuple(
                replace(binding, response_completeness=replace(binding.response_completeness, snapshot_field=None))
                for binding in minute.provider_bindings
            ),
        )
    registry = DatasetRegistry((minute,), query_defaults=native_harness["registry"].query_defaults)
    service = QueryService(db_path=native_harness["service"]._db_path, registry=registry, cursor_codec=SignedCursorCodec(SIGNING_KEY))
    through = (
        "2026-07-17 13:00:00"
        if variant == "future"
        else None
        if variant == "missing_data_through"
        else "2026-07-17 11:40:00"
    )
    receipt = _insert_native_success_receipt(
        monkeypatch, conn, minute, execution_id=f"negative-{variant}", call_index=0,
        page_offset=0, request_window={}, data_through=through,
    )
    row_time = (
        "2026-07-17 11:41:00"
        if variant == "row_mismatch"
        else "2026-07-17 11:40:00"
    )
    _insert_row(conn, dataset_id=minute.dataset_id, provider="provider-a", row_key=f"negative-{variant}",
                payload={"symbol": f"NEG_{variant.upper()}", "time": row_time}, receipt_id=receipt)
    conn.commit()
    evidence = replace(_proof_evidence((receipt,)), projection=replace(_proof_evidence((receipt,)).projection, dataset_id=minute.dataset_id))
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: evidence)
    request = QueryRequest(dataset_id=minute.dataset_id, schema_major=1, fields=("symbol", "time"),
                           filters={"symbol": {"in": [f"NEG_{variant.upper()}"]}}, as_of=None,
                           order=("time:asc", "symbol:asc"), limit=10, cursor=None, include_receipt_proofs=True)
    with pytest.raises(QueryServiceUnavailable):
        service.execute(request, access=native_harness["access"], now=NOW, request_id=f"negative-{variant}")


def test_opt_in_no_window_session_minute_rejects_same_execution_data_through_mismatch(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    minute = _minute_dataset(native_harness["dataset"])
    registry = DatasetRegistry((minute,), query_defaults=native_harness["registry"].query_defaults)
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    first = _insert_native_success_receipt(
        monkeypatch, conn, minute, execution_id="same-execution", call_index=0,
        page_offset=0, request_window={}, data_through="2026-07-17 11:40:00",
    )
    second = _insert_native_success_receipt(
        monkeypatch, conn, minute, execution_id="same-execution", call_index=1,
        page_offset=1, request_window={}, data_through="2026-07-17 11:41:00",
    )
    _insert_row(
        conn, dataset_id=minute.dataset_id, provider="provider-a", row_key="through-a",
        payload={"symbol": "THROUGH_A", "time": "2026-07-17 11:40:00"}, receipt_id=first,
    )
    _insert_row(
        conn, dataset_id=minute.dataset_id, provider="provider-a", row_key="through-b",
        payload={"symbol": "THROUGH_B", "time": "2026-07-17 11:41:00"}, receipt_id=second,
    )
    conn.commit()
    evidence = replace(
        _proof_evidence((first, second)),
        projection=replace(_proof_evidence((first, second)).projection, dataset_id=minute.dataset_id),
    )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *args, **kwargs: evidence)
    request = QueryRequest(
        dataset_id=minute.dataset_id,
        schema_major=1,
        fields=("symbol", "time"),
        filters={"symbol": {"in": ["THROUGH_A", "THROUGH_B"]}},
        as_of=None,
        order=("time:asc", "symbol:asc"),
        limit=10,
        cursor=None,
        include_receipt_proofs=True,
    )
    with pytest.raises(QueryServiceUnavailable):
        service.execute(request, access=native_harness["access"], now=NOW, request_id="same-execution-through")


def _failed_success_evidence(
    dataset_id: str,
    *,
    reasons: tuple[str, ...] = ("invalid_data_through",),
    data_through: str | None = None,
    observed_at: str | None = "2026-07-17T03:00:00+00:00",
) -> DatasetRuntimeEvidence:
    return DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset_id,
            state="failed",
            degraded=True,
            data_through=data_through,
            observed_at=observed_at,
            receipt_id="receipt-invalid-data-through",
            reasons=reasons,
        ),
        current_receipt_status="success",
        current_providers=("provider-a",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
    )


def test_catalog_checks_fixed_generic_columns_json_and_not_provider_fields(
    native_harness: dict[str, object],
) -> None:
    result = inspect_dataset_queryability(
        native_harness["conn"], native_harness["dataset"]
    )
    assert result.queryable is True
    assert result.reasons == ()


def test_native_query_python_projection_preserves_missing_null_and_large_integer(
    native_harness: dict[str, object],
) -> None:
    response = _execute(native_harness, _request())

    assert [row["symbol"] for row in response["data"]] == ["AAA", "BBB", "BBB"]
    assert "note" not in response["data"][0]
    assert response["data"][0]["big"] == 2**70
    assert response["data"][1]["note"] is None
    assert response["data"][2]["note"] == "provider-b"
    assert all(
        "payload_json" not in row and "row_key" not in row for row in response["data"]
    )
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["state"] == "success"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["quality"]["state"] == "degraded"
    assert response["metadata"]["lineage"]["transport_service"] is None
    assert response["metadata"]["lineage"]["transport_profile_id"] is None
    assert response["metadata"]["lineage"]["transport_profile_sha256"] is None
    assert "integer_out_of_int64:big" in response["metadata"]["quality"]["evidence"]


def test_partial_query_without_business_watermark_returns_rows_as_unknown_freshness(
    native_harness: dict[str, object],
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows WHERE quality_state = 'degraded'")
    conn.commit()
    base = native_harness["dataset"]
    dataset = replace(
        base,
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
        provider_bindings=tuple(
            replace(binding, response_completeness=None)
            for binding in base.provider_bindings
        ),
    )
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=native_harness["registry"].query_defaults,
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )

    response = service.execute(
        _request(fields=("symbol",)),
        access=native_harness["access"],
        now=NOW,
        request_id="request-partial-without-business-watermark",
    )

    assert response["data"] == [{"symbol": "BBB"}, {"symbol": "BBB"}]
    assert response["metadata"]["state"] == "partial"
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["freshness"] == {
        "state": "unknown",
        "stale": False,
        "sla_seconds": dataset.freshness_sla_seconds,
    }
    assert response["metadata"]["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": [
            "freshness_watermark_unverified",
            "response_completeness_unverified",
        ],
    }
    assert response["metadata"]["data_through"] is None
    assert response["metadata"]["reasons"] == [
        "freshness_watermark_unverified",
        "response_completeness_unverified",
    ]
    assert response["metadata"]["lineage"]["complete"] is True


def test_native_query_omitted_fields_returns_complete_provider_payload(
    native_harness: dict[str, object],
) -> None:
    response = _execute(native_harness, _request(fields=()))

    first = response["data"][0]
    assert first == {
        "big": 2**70,
        "dataset_id": "forged-dataset",
        "provider": "forged-provider",
        "schema_major": 999,
        "symbol": "AAA",
        "trade_date": "20260715",
    }
    assert "payload_json" not in first
    assert "row_key" not in first
    assert "receipt_id" not in first


def test_native_query_explicit_null_filter_does_not_match_missing_key(
    native_harness: dict[str, object],
) -> None:
    response = _execute(
        native_harness,
        _request(fields=("symbol", "note"), filters={"note": {"eq": None}}),
    )
    assert response["data"] == [{"symbol": "BBB", "note": None}]

    in_response = _execute(
        native_harness,
        _request(
            fields=("symbol", "note"),
            filters={"note": {"in": [None, "provider-b"]}},
        ),
    )
    assert in_response["data"] == [
        {"symbol": "BBB", "note": None},
        {"symbol": "BBB", "note": "provider-b"},
    ]


def test_native_query_isolates_technical_dataset_provider_and_schema_columns(
    native_harness: dict[str, object],
) -> None:
    response = _execute(native_harness, _request(fields=("symbol",)))
    assert [row["symbol"] for row in response["data"]] == ["AAA", "BBB", "BBB"]
    assert not any(row["symbol"].startswith("LEAK-") for row in response["data"])


def test_native_query_filter_order_asof_and_partition_are_registry_compiled(
    native_harness: dict[str, object],
) -> None:
    response = _execute(
        native_harness,
        _request(
            fields=("symbol", "trade_date"),
            filters={"trade_date": {"gte": "20260715"}},
            order=("trade_date:asc", "symbol:asc"),
            as_of="2026-07-16T23:59:59+08:00",
        ),
        options=QueryExecutionOptions(latest_partition=True),
    )
    assert response["data"] == [
        {"symbol": "BBB", "trade_date": "20260716"},
        {"symbol": "BBB", "trade_date": "20260716"},
    ]
    assert response["metadata"]["receipt_id"] == "receipt-current"
    assert (
        response["metadata"]["data_through"]
        == "2026-07-16T00:00:00+08:00"
    )
    assert response["metadata"]["observed_at"] == "2026-07-16T15:00:00+00:00"


def test_asof_query_excludes_rows_bound_only_to_a_later_receipt(
    native_harness: dict[str, object],
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="later-receipt-row",
        payload={
            "symbol": "LATER",
            "trade_date": "20260716",
            "note": "not observable at cutoff",
            "big": 4,
        },
    )
    native_harness["conn"].commit()

    historical = _execute(
        native_harness,
        _request(
            fields=("symbol",),
            as_of="2026-07-16T23:59:59+08:00",
            order=("symbol:asc",),
        ),
    )
    current = _execute(
        native_harness,
        _request(fields=("symbol",), order=("symbol:asc",)),
    )

    assert [row["symbol"] for row in historical["data"]] == ["AAA", "BBB", "BBB"]
    assert [row["symbol"] for row in current["data"]] == [
        "AAA",
        "BBB",
        "BBB",
        "LATER",
    ]


def test_asof_query_without_a_matching_success_receipt_fails_closed(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = query_module.project_dataset_runtime_evidence

    def without_matching_receipt(
        *args: object, **kwargs: object
    ) -> DatasetRuntimeEvidence:
        return replace(
            project(*args, **kwargs),
            as_of_success_receipt_ids=(),
        )

    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        without_matching_receipt,
    )

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(
            native_harness,
            _request(
                fields=("symbol",),
                as_of="2026-07-16T23:59:59+08:00",
            ),
        )


def test_asof_cursor_remains_terminal_when_a_later_receipt_row_exists(
    native_harness: dict[str, object],
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="later-receipt-pagination-row",
        payload={
            "symbol": "ZZZ",
            "trade_date": "20260716",
            "note": "not observable at cutoff",
            "big": 4,
        },
    )
    native_harness["conn"].commit()

    request = _request(
        fields=("symbol",),
        as_of="2026-07-16T23:59:59+08:00",
        order=("symbol:asc",),
        limit=1,
    )
    rows: list[dict[str, object]] = []
    while True:
        response = _execute(native_harness, request)
        rows.extend(response["data"])
        if response["next_cursor"] is None:
            break
        request = replace(request, cursor=response["next_cursor"])

    assert [row["symbol"] for row in rows] == ["AAA", "BBB", "BBB"]


def test_append_only_overlap_replay_keeps_exact_terminal_window_after_later_receipt(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    append_only_dataset = replace(
        native_harness["dataset"],
        point_in_time="append_only",
        max_page_size=13,
    )
    append_only_registry = DatasetRegistry(
        (append_only_dataset,),
        query_defaults=native_harness["registry"].query_defaults,
    )
    harness = {
        **native_harness,
        "dataset": append_only_dataset,
        "registry": append_only_registry,
        "service": QueryService(
            db_path=(tmp_path / "append-only-query.sqlite").absolute(),
            registry=append_only_registry,
            cursor_codec=SignedCursorCodec(SIGNING_KEY),
        ),
    }
    permitted = {row[0] for row in native_harness["conn"].execute(
        "SELECT receipt_id FROM provider_dataset_rows WHERE dataset_id = ? AND schema_major = 1",
        (append_only_dataset.dataset_id,),
    )}
    permitted.add("receipt-current")  # The fixture's projected dataset receipt.
    for index, symbol in enumerate("CDEFGHIJKL", start=1):
        receipt_id = _insert_row(
            native_harness["conn"],
            provider="provider-a",
            row_key=f"append-only-first-{index}",
            payload={
                "symbol": symbol,
                "trade_date": "20260716",
                "note": "first append-only provenance",
                "big": index,
            },
        )
        permitted.add(receipt_id)
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="append-only-later-overlap",
        payload={
            "symbol": "ZZZ",
            "trade_date": "20260716",
            "note": "later receipt outside cutoff",
            "big": 99,
        },
    )
    native_harness["conn"].commit()

    original_project = query_module.project_dataset_runtime_evidence

    def append_only_authority(
        *args: object, **kwargs: object
    ) -> DatasetRuntimeEvidence:
        evidence = original_project(*args, **kwargs)
        if kwargs.get("evidence_as_of") is None:
            return evidence
        return replace(
            evidence,
            as_of_success_receipt_ids=tuple(sorted(permitted)),
        )

    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        append_only_authority,
    )
    request = _request(
        fields=("symbol", "trade_date"),
        as_of="2026-07-16T23:59:59+08:00",
        order=("symbol:asc",),
        limit=13,
    )

    first = _execute(harness, request)
    replay = _execute(harness, request)

    assert len(first["data"]) == 13
    assert first["next_cursor"] is None
    assert first["data"] == replay["data"]
    assert first["metadata"] == replay["metadata"]
    assert all(row["symbol"] != "ZZZ" for row in first["data"])

    current_request = replace(request, as_of=None)
    current_first = _execute(harness, current_request)
    assert len(current_first["data"]) == 13
    assert current_first["next_cursor"] is not None
    current_second = _execute(
        harness,
        replace(current_request, cursor=current_first["next_cursor"]),
    )
    assert current_second["data"] == [
        {"symbol": "ZZZ", "trade_date": "20260716"}
    ]
    assert current_second["next_cursor"] is None


@pytest.mark.parametrize(
    "query_request",
    [
        _request(fields=("symbol",), filters={"big": {"eq": 2**70}}),
        _request(fields=("symbol",), order=("big:asc",)),
    ],
)
def test_native_query_large_integer_operation_fails_closed(
    native_harness: dict[str, object],
    query_request: QueryRequest,
) -> None:
    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(native_harness, query_request)


@pytest.mark.parametrize(
    ("as_of", "options"),
    [
        ("2026-07-16T23:59:59+08:00", QueryExecutionOptions()),
        (None, QueryExecutionOptions(latest_partition=True)),
    ],
)
def test_native_query_asof_and_partition_type_mismatch_fail_closed(
    native_harness: dict[str, object],
    as_of: str | None,
    options: QueryExecutionOptions,
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="bad-date",
        payload={"symbol": "BAD", "trade_date": 20260716, "big": 1},
        issues=("type_mismatch:trade_date:text", "missing_field:note"),
    )
    native_harness["conn"].commit()

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(
            native_harness,
            _request(fields=("symbol",), as_of=as_of),
            options=options,
        )


def test_native_query_dataset_quality_is_visible_when_page_is_clean(
    native_harness: dict[str, object],
) -> None:
    response = _execute(
        native_harness,
        _request(
            fields=("symbol", "note"),
            filters={"symbol": {"eq": "BBB"}},
        ),
    )
    assert response["metadata"]["runtime_state"] == "success"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": ["provider_dataset_quality_degraded"],
    }


def test_current_exact_partition_uses_only_projected_receipt_cohort(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    _insert_row(
        conn,
        provider="provider-a",
        row_key="older-degraded-duplicate",
        payload={
            "symbol": "DUP",
            "trade_date": "20260716",
            "big": 1,
        },
        issues=(
            "missing_field:note",
            "time_format_mismatch:trade_date:yyyymmdd",
        ),
    )
    current_receipt = _insert_row(
        conn,
        provider="provider-a",
        row_key="current-valid-duplicate",
        payload={
            "symbol": "DUP",
            "trade_date": "20260716",
            "note": "current full-field row",
            "big": 2,
        },
    )
    conn.commit()
    original_project = query_module.project_dataset_runtime_evidence
    def current_authority(*args: object, **kwargs: object) -> DatasetRuntimeEvidence:
        evidence = original_project(*args, **kwargs)
        return replace(
            evidence, projection=replace(evidence.projection, receipt_id=current_receipt),
            last_success_receipt_id=current_receipt,
            current_receipt_ids=(current_receipt,), last_success_receipt_ids=(current_receipt,),
        )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", current_authority)

    exact = _execute(
        native_harness,
        _request(
            fields=("symbol", "trade_date", "note", "big"),
            filters={"trade_date": {"eq": "20260716"}},
        ),
    )
    non_exact = _execute(
        native_harness,
        _request(fields=("symbol", "trade_date", "note", "big")),
    )

    assert exact["data"] == [
        {
            "symbol": "DUP",
            "trade_date": "20260716",
            "note": "current full-field row",
            "big": 2,
        }
    ]
    assert exact["metadata"]["degraded"] is False
    assert exact["metadata"]["quality"] == {
        "state": "valid",
        "valid": True,
        "evidence": [],
    }
    assert non_exact["data"] == [
        {
            "symbol": "DUP",
            "trade_date": "20260716",
            "note": "current full-field row",
            "big": 2,
        },
        {"symbol": "DUP", "trade_date": "20260716", "big": 1},
    ]
    assert non_exact["metadata"]["degraded"] is True
    assert non_exact["metadata"]["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": [
            "missing_field:note",
            "provider_dataset_quality_degraded",
            "time_format_mismatch:trade_date:yyyymmdd",
        ],
    }


def test_current_exact_request_partition_scopes_null_business_partition_receipts(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    _insert_row(
        conn,
        provider="provider-a",
        row_key="historical-degraded-duplicate",
        payload={
            "symbol": "DUP",
            "trade_date": "20260716",
            "big": 1,
        },
        issues=(
            "missing_field:note",
            "time_format_mismatch:trade_date:yyyymmdd",
        ),
    )
    current_receipt = _insert_row(
        conn,
        provider="provider-a",
        row_key="current-valid-duplicate",
        payload={
            "symbol": "DUP",
            "trade_date": "20260716",
            "note": "current full-field row",
            "big": 2,
        },
    )
    conn.commit()
    original_project = query_module.project_dataset_runtime_evidence
    def current_authority(*args: object, **kwargs: object) -> DatasetRuntimeEvidence:
        evidence = original_project(*args, **kwargs)
        return replace(
            evidence, projection=replace(evidence.projection, receipt_id=current_receipt),
            last_success_receipt_id=current_receipt,
            current_receipt_ids=(current_receipt,), last_success_receipt_ids=(current_receipt,),
        )
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", current_authority)

    dataset = replace(native_harness["dataset"], partition_field=None)
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=native_harness["registry"].query_defaults,
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )

    def execute(request: QueryRequest) -> dict[str, object]:
        return service.execute(
            request,
            access=native_harness["access"],
            now=NOW,
            request_id="request-null-business-partition",
        )

    exact = execute(
        _request(
            fields=("symbol", "trade_date", "note", "big"),
            filters={"trade_date": {"eq": "20260716"}},
        )
    )
    non_exact = execute(_request(fields=("symbol", "trade_date", "note", "big")))

    assert exact["data"] == [
        {
            "symbol": "DUP",
            "trade_date": "20260716",
            "note": "current full-field row",
            "big": 2,
        }
    ]
    assert exact["metadata"]["state"] == "ready"
    assert exact["metadata"]["degraded"] is False
    assert exact["metadata"]["quality"] == {
        "state": "valid",
        "valid": True,
        "evidence": [],
    }
    assert len(non_exact["data"]) == 2
    assert non_exact["metadata"]["degraded"] is True
    assert non_exact["metadata"]["quality"]["state"] == "degraded"


def test_native_query_returns_current_rows_for_exact_invalid_data_through_failure(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    _insert_row(
        conn,
        provider="provider-a",
        row_key="invalid-time-current-row",
        payload={"symbol": "INVALID-TIME", "trade_date": "BAD-DATE", "big": 1},
        issues=("time_format_mismatch:trade_date:yyyymmdd",),
    )
    conn.commit()
    evidence = _failed_success_evidence(native_harness["dataset"].dataset_id)
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    response = _execute(
        native_harness,
        _request(
            fields=("symbol", "trade_date"),
            order=("symbol:asc",),
        ),
    )

    assert response["data"] == [{"symbol": "INVALID-TIME", "trade_date": "BAD-DATE"}]
    assert response["metadata"]["state"] == "failed"
    assert response["metadata"]["runtime_state"] == "failed"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["data_through"] is None
    assert response["metadata"]["receipt_id"] == "receipt-invalid-data-through"
    assert response["metadata"]["freshness"]["state"] == "failed"
    assert response["metadata"]["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": [
            "invalid_data_through",
            "provider_dataset_quality_degraded",
            "time_format_mismatch:trade_date:yyyymmdd",
        ],
    }
    assert response["metadata"]["lineage"]["complete"] is True
    assert response["metadata"]["lineage"]["providers"] == ["provider-a"]
    assert response["metadata"]["reasons"] == ["invalid_data_through"]


def test_failed_current_cohort_hides_prior_and_partial_facts(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    _insert_row(
        conn,
        provider="provider-a",
        row_key="prior-success-row",
        payload={"symbol": "PRIOR", "trade_date": "20260716", "big": 1},
    )
    _insert_row(
        conn,
        provider="provider-a",
        row_key="partial-current-row",
        payload={"symbol": "PARTIAL", "trade_date": "20260717", "big": 2},
    )
    conn.commit()
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=native_harness["dataset"].dataset_id,
            state="failed",
            degraded=True,
            data_through=None,
            observed_at="2026-07-17T03:00:00+00:00",
            receipt_id="receipt-current-failed",
            reasons=("variant_cohort_incomplete",),
        ),
        current_receipt_status="failed",
        current_providers=("provider-a",),
        last_success_receipt_id="receipt-prior-success",
        last_success_providers=("provider-a",),
        last_success_data_through="20260716",
        current_receipt_ids=("receipt-current-failed",),
        last_success_receipt_ids=("receipt-prior-success",),
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    response = _execute(native_harness, _request(fields=("symbol",)))

    assert response["data"] == []
    assert response["next_cursor"] is None
    assert response["metadata"]["state"] == "failed"
    assert response["metadata"]["runtime_state"] == "failed"
    assert response["metadata"]["degraded"] is True
    assert response["metadata"]["quality"]["valid"] is False
    assert response["metadata"]["reasons"] == ["variant_cohort_incomplete"]


def test_receipt_watermark_changes_when_cohort_membership_changes() -> None:
    dataset = _native_dataset()
    base = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=None,
            observed_at="2026-07-17T03:00:00+00:00",
            receipt_id="receipt-current-a",
            reasons=("variant_cohort_incomplete",),
        ),
        current_receipt_status="failed",
        current_providers=("provider-a",),
        last_success_receipt_id="receipt-prior-a",
        last_success_providers=("provider-a",),
        last_success_data_through="20260716",
        current_receipt_ids=("receipt-current-a",),
        last_success_receipt_ids=("receipt-prior-a",),
    )

    current_member_changed = replace(
        base,
        current_receipt_ids=("receipt-current-a", "receipt-current-b"),
    )
    last_success_member_changed = replace(
        base,
        last_success_receipt_ids=("receipt-prior-a", "receipt-prior-b"),
    )

    watermark = query_module._receipt_watermark(dataset, base)
    assert query_module._receipt_watermark(dataset, current_member_changed) != watermark
    assert query_module._receipt_watermark(dataset, last_success_member_changed) != watermark


@pytest.mark.parametrize(
    "evidence",
    [
        _failed_success_evidence(
            "cn.native.query",
            reasons=("invalid_data_through", "provider_error"),
        ),
        _failed_success_evidence(
            "cn.native.query",
            data_through="20260716",
        ),
        _failed_success_evidence(
            "cn.native.query",
            observed_at=None,
        ),
    ],
)
def test_native_query_rejects_nonexact_failed_success_receipt_combinations(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    evidence: DatasetRuntimeEvidence,
) -> None:
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(native_harness, _request(fields=("symbol",)))


def test_native_cursor_uses_provider_and_row_key_without_sqlite_rowid(
    native_harness: dict[str, object],
) -> None:
    first = _execute(native_harness, _request(fields=("symbol",), limit=1))
    second = _execute(
        native_harness,
        replace(_request(fields=("symbol",), limit=1), cursor=first["next_cursor"]),
    )
    third = _execute(
        native_harness,
        replace(_request(fields=("symbol",), limit=1), cursor=second["next_cursor"]),
    )
    assert [
        first["data"][0]["symbol"],
        second["data"][0]["symbol"],
        third["data"][0]["symbol"],
    ] == [
        "AAA",
        "BBB",
        "BBB",
    ]
    assert third["next_cursor"] is None


def test_native_default_order_matches_catalog_primary_key_and_keeps_stable_cursor(
    native_harness: dict[str, object],
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="000-physical-key",
        payload={"symbol": "ZZZ", "trade_date": "20260716", "big": 4},
    )
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="zzz-physical-key",
        payload={"symbol": "000", "trade_date": "20260716", "big": 5},
    )
    native_harness["conn"].commit()

    request = _request(fields=("symbol", "trade_date", "note"), order=None, limit=1)
    pages: list[dict[str, object]] = []
    while True:
        response = _execute(native_harness, request)
        pages.extend(response["data"])
        if response["next_cursor"] is None:
            break
        request = replace(request, cursor=response["next_cursor"])

    assert [row["symbol"] for row in pages] == ["000", "AAA", "BBB", "BBB", "ZZZ"]
    assert pages[2]["note"] is None
    assert pages[3]["note"] == "provider-b"


def test_catalog_only_append_only_query_uses_physical_cursor_without_guessed_key(
    native_harness: dict[str, object],
) -> None:
    source = native_harness["registry"]
    dataset = replace(
        native_harness["dataset"],
        primary_key=(),
        point_in_time="append_only",
        read_model_adapter=replace(
            native_harness["dataset"].read_model_adapter,
            row_key_strategy="payload_hash",
        ),
    )
    registry = DatasetRegistry((dataset,), query_defaults=source.query_defaults)
    native_harness["service"] = QueryService(
        db_path=Path("/tmp/provider-native-catalog-only.sqlite"),
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )

    request = _request(fields=(), order=None, limit=1)
    symbols: list[str] = []
    while True:
        response = _execute(native_harness, request)
        symbols.append(response["data"][0]["symbol"])
        if response["next_cursor"] is None:
            break
        request = replace(request, cursor=response["next_cursor"])

    assert symbols == ["AAA", "BBB", "BBB"]


def test_native_query_rejects_internal_storage_field_requests(
    native_harness: dict[str, object],
) -> None:
    with pytest.raises(Exception, match="not selectable"):
        _execute(native_harness, _request(fields=("payload_json",)))


def test_native_query_accepts_hashed_unknown_and_time_format_quality_codes(
    native_harness: dict[str, object],
) -> None:
    hashed_unknown = f"unknown_field_sha256:{'a' * 64}"
    time_mismatch = "time_format_mismatch:trade_date:rfc3339"
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="quality-code-valid",
        payload={"symbol": "QUALITY-CODE", "trade_date": "20260716", "big": 1},
        issues=(time_mismatch, hashed_unknown),
    )
    native_harness["conn"].commit()

    response = _execute(
        native_harness,
        _request(
            fields=("symbol",),
            filters={"symbol": {"eq": "QUALITY-CODE"}},
        ),
    )

    assert response["data"] == [{"symbol": "QUALITY-CODE"}]
    assert response["metadata"]["quality"]["evidence"] == [
        "provider_dataset_quality_degraded",
        time_mismatch,
        hashed_unknown,
    ]


def test_native_query_accepts_yyyymm_time_format_quality_code(
    native_harness: dict[str, object],
) -> None:
    month_mismatch = "time_format_mismatch:month:yyyymm"
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="quality-code-yyyymm",
        payload={"symbol": "QUALITY-MONTH", "trade_date": "20260716", "big": 1},
        issues=(month_mismatch,),
    )
    native_harness["conn"].commit()

    response = _execute(
        native_harness,
        _request(
            fields=("symbol",),
            filters={"symbol": {"eq": "QUALITY-MONTH"}},
        ),
    )

    assert response["data"] == [{"symbol": "QUALITY-MONTH"}]
    assert response["metadata"]["quality"]["evidence"] == [
        "provider_dataset_quality_degraded",
        month_mismatch,
    ]


def test_native_query_select_preserves_invalid_time_when_order_uses_safe_field(
    native_harness: dict[str, object],
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="invalid-declared-time-select",
        payload={"symbol": "BAD-LOW", "trade_date": "BAD-LOW", "big": 1},
        issues=("time_format_mismatch:trade_date:yyyymmdd",),
    )
    native_harness["conn"].commit()

    response = _execute(
        native_harness,
        _request(
            fields=("symbol", "trade_date"),
            order=("symbol:asc",),
        ),
    )

    assert {"symbol": "BAD-LOW", "trade_date": "BAD-LOW"} in response["data"]
    assert response["metadata"]["degraded"] is True
    assert (
        "time_format_mismatch:trade_date:yyyymmdd"
        in response["metadata"]["quality"]["evidence"]
    )


@pytest.mark.parametrize(
    ("query_request", "options"),
    [
        (
            _request(
                fields=("symbol", "trade_date"),
                filters={"trade_date": {"gte": "20260701"}},
            ),
            QueryExecutionOptions(),
        ),
        (
            _request(
                fields=("symbol", "trade_date"),
                order=("trade_date:asc",),
            ),
            QueryExecutionOptions(),
        ),
        (
            _request(
                fields=("symbol", "trade_date"),
                as_of="2026-07-16T23:59:59+08:00",
            ),
            QueryExecutionOptions(),
        ),
        (
            _request(fields=("symbol", "trade_date")),
            QueryExecutionOptions(latest_partition=True),
        ),
        (
            _request(fields=("symbol", "trade_date")),
            QueryExecutionOptions(any_of_eq_filters=(("trade_date", "20260716"),)),
        ),
    ],
)
def test_native_query_invalid_declared_time_operation_fails_closed(
    native_harness: dict[str, object],
    query_request: QueryRequest,
    options: QueryExecutionOptions,
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key="invalid-declared-time-operation",
        payload={"symbol": "BAD-HIGH", "trade_date": "BAD-HIGH", "big": 1},
        issues=("time_format_mismatch:trade_date:yyyymmdd",),
    )
    native_harness["conn"].commit()

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(native_harness, query_request, options=options)


@pytest.mark.parametrize(
    "issue",
    [
        f"unknown_field_sha256:{'a' * 63}",
        f"unknown_field_sha256:{'A' * 64}",
        "time_format_mismatch:trade-date:yyyymmdd",
        "time_format_mismatch:trade_date:iso8601",
    ],
)
def test_native_query_rejects_malformed_provider_quality_codes(
    native_harness: dict[str, object],
    issue: str,
) -> None:
    _insert_row(
        native_harness["conn"],
        provider="provider-a",
        row_key=f"quality-code-malformed-{len(issue)}-{issue[-1]}",
        payload={"symbol": "MALFORMED-CODE", "trade_date": "20260716", "big": 1},
        issues=(issue,),
    )
    native_harness["conn"].commit()

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(
            native_harness,
            _request(
                fields=("symbol",),
                filters={"symbol": {"eq": "MALFORMED-CODE"}},
            ),
        )


def test_native_query_25k_plus_degraded_uses_quality_index_within_vm_budget(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    page_receipts = [
        _insert_native_success_receipt(
            monkeypatch, conn, native_harness["dataset"],
            execution_id=f"bulk-fixture-{index}", call_index=0, page_offset=0,
            request_window={"trade_date": "20260716"}, data_through="20260716",
        ) for index in range(10)
    ]
    rows: list[tuple[object, ...]] = []
    for index in range(25_000):
        symbol = f"S{index:05d}"
        payload = json.dumps(
            {
                "big": index,
                "note": None,
                "symbol": symbol,
                "trade_date": "20260716",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(
            (
                "cn.native.query",
                "provider-a",
                1,
                "1.2.0",
                f"row-{index:05d}",
                "20260716",
                "20260716",
                payload,
                "a" * 64,
                "valid",
                "[]",
                "2026-07-17T03:00:00+00:00",
                page_receipts[index] if index < 10 else f"receipt:provider-a:{index:05d}",
                1,
            )
        )
    conn.executemany(
        "INSERT INTO provider_dataset_rows VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    _insert_row(
        conn,
        provider="provider-a",
        row_key="row-degraded-last",
        payload={
            "big": 25_000,
            "symbol": "ZZZZZ",
            "trade_date": "20260716",
        },
        issues=("missing_field:note",),
    )
    conn.commit()

    traced: list[str] = []
    conn.set_trace_callback(traced.append)
    try:
        response = _execute(
            native_harness,
            _request(fields=("symbol",), order=("symbol:asc",), limit=10),
        )
    finally:
        conn.set_trace_callback(None)

    assert [row["symbol"] for row in response["data"]] == [
        f"S{index:05d}" for index in range(10)
    ]
    assert response["metadata"]["state"] == "success"
    assert response["metadata"]["degraded"] is True
    degraded_checks = [
        statement
        for statement in traced
        if statement.startswith('SELECT 1 FROM main."provider_dataset_rows"')
        and "quality_state\" = 'degraded'" in statement
    ]
    assert len(degraded_checks) == 3
    assert all(
        'INDEXED BY "provider_dataset_rows_quality_idx"' in statement
        for statement in degraded_checks
    )
    for statement in degraded_checks:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {statement}").fetchall()
        assert any("provider_dataset_rows_quality_idx" in str(row[3]) for row in plan)


def test_native_query_missing_quality_index_fails_closed(
    native_harness: dict[str, object],
) -> None:
    native_harness["conn"].execute("DROP INDEX provider_dataset_rows_quality_idx")
    native_harness["conn"].commit()

    with pytest.raises(QueryServiceUnavailable, match="unavailable"):
        _execute(native_harness, _request(fields=("symbol",)))


def test_native_partition_filter_uses_partition_index_within_vm_budget(
    native_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    page_receipts = [
        _insert_native_success_receipt(
            monkeypatch, conn, native_harness["dataset"],
            execution_id=f"bulk-fixture-{index}", call_index=0, page_offset=0,
            request_window={"trade_date": "20260716"}, data_through="20260716",
        ) for index in range(10)
    ]
    rows: list[tuple[object, ...]] = []
    for index in range(25_000):
        trade_date = "20260716" if index < 10 else "20260715"
        payload = json.dumps(
            {
                "big": index,
                "note": None,
                "symbol": f"S{index:05d}",
                "trade_date": trade_date,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(
            (
                "cn.native.query",
                "provider-a",
                1,
                "1.2.0",
                f"partition-{index:05d}",
                trade_date,
                trade_date,
                payload,
                "a" * 64,
                "valid",
                "[]",
                "2026-07-17T03:00:00+00:00",
                page_receipts[index] if index < 10 else f"receipt:provider-a:partition-{index:05d}",
                1,
            )
        )
    conn.executemany(
        "INSERT INTO provider_dataset_rows VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    current_receipt_ids = tuple(sorted(page_receipts))
    original_project = query_module.project_dataset_runtime_evidence

    def current_partition_authority(
        *args: object, **kwargs: object
    ) -> DatasetRuntimeEvidence:
        evidence = original_project(*args, **kwargs)
        return replace(
            evidence,
            projection=replace(
                evidence.projection,
                receipt_id=current_receipt_ids[0],
            ),
            current_providers=("provider-a",),
            last_success_receipt_id=current_receipt_ids[0],
            last_success_providers=("provider-a",),
            current_receipt_ids=current_receipt_ids,
            last_success_receipt_ids=current_receipt_ids,
        )

    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        current_partition_authority,
    )

    dataset = native_harness["dataset"]
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(
            native_harness["registry"].query_defaults,
            sqlite_progress_steps=100_000,
        ),
    )
    service = QueryService(
        db_path=native_harness["service"]._db_path,  # noqa: SLF001
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    request = _request(
        fields=("symbol", "trade_date"),
        filters={"trade_date": {"eq": "20260716"}},
        order=("symbol:asc",),
        limit=10,
    )
    response = service.execute(
        request,
        access=native_harness["access"],
        now=NOW,
        request_id="request-native-partition",
    )

    assert [row["symbol"] for row in response["data"]] == [
        f"S{index:05d}" for index in range(10)
    ]
    assert all(row["trade_date"] == "20260716" for row in response["data"])
    assert query_module._field_expression(dataset, "trade_date") == '"partition_value"'

@pytest.mark.parametrize("include_proofs", [False, True])
@pytest.mark.parametrize("damage", ["missing", "malformed", "foreign_provider", "incomplete_execution"])
def test_query_rejects_broken_row_authority_even_with_healthy_latest_receipt(
    native_harness: dict[str, object], monkeypatch: pytest.MonkeyPatch,
    include_proofs: bool, damage: str,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    historical = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="historical-row",
        call_index=0, page_offset=0,
        provider="provider-b" if damage == "foreign_provider" else "provider-a",
    )
    latest = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="healthy-latest",
        call_index=0, page_offset=0,
    )
    if damage == "incomplete_execution":
        _insert_native_success_receipt(
            monkeypatch, conn, dataset, execution_id="missing-middle-call",
            call_index=0, page_offset=0,
        )
        historical = _insert_native_success_receipt(
            monkeypatch, conn, dataset, execution_id="missing-middle-call",
            call_index=2, page_offset=2,
        )
    _insert_row(conn, row_key="broken-history", payload={"symbol": "BROKEN", "trade_date": "20260715"}, receipt_id=historical)
    if damage == "missing":
        conn.execute("DELETE FROM market_ingest_runs WHERE run_id = ?", (historical,))
    elif damage == "malformed":
        conn.execute("UPDATE market_ingest_runs SET notes = '{' WHERE run_id = ?", (historical,))
    conn.commit()
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *a, **k: _proof_evidence((latest,)))
    with pytest.raises(QueryServiceUnavailable):
        _execute(native_harness, _request(filters={"symbol": {"eq": "BROKEN"}}, include_receipt_proofs=include_proofs))


def test_default_query_excludes_success_prefix_from_explicitly_failed_cohort(
    native_harness: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    valid = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="complete-independent",
        call_index=0, page_offset=0,
    )
    partial = _insert_native_success_receipt(
        monkeypatch, conn, dataset, execution_id="explicitly-failed",
        call_index=0, page_offset=0,
    )
    _insert_native_failed_receipt(
        monkeypatch, conn, dataset, execution_id="explicitly-failed", call_index=1,
    )
    _insert_row(
        conn, row_key="complete-independent", receipt_id=valid,
        payload={"symbol": "VALID", "trade_date": "20260715"},
    )
    _insert_row(
        conn, row_key="failed-prefix", receipt_id=partial,
        payload={"symbol": "PARTIAL", "trade_date": "20260715"},
    )
    conn.commit()
    evidence = _proof_evidence((valid,))
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: evidence,
    )

    response = _execute(
        native_harness,
        _request(filters={"symbol": {"in": ["PARTIAL", "VALID"]}}),
    )

    assert response["data"] == [{"symbol": "VALID", "trade_date": "20260715"}]


def test_default_query_keeps_successful_retry_after_failed_attempt(
    native_harness: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    _insert_native_failed_receipt(
        monkeypatch,
        conn,
        dataset,
        execution_id="retry-then-success",
        call_index=0,
        retry_index=0,
        finished_at="2026-07-17T03:01:00+00:00",
    )
    successful_retry = _insert_native_success_receipt(
        monkeypatch,
        conn,
        dataset,
        execution_id="retry-then-success",
        call_index=1,
        page_offset=0,
        retry_index=1,
        request_page_index=0,
        finished_at="2026-07-17T03:02:00+00:00",
    )
    _insert_row(
        conn,
        row_key="successful-retry",
        receipt_id=successful_retry,
        payload={"symbol": "RETRIED", "trade_date": "20260715"},
    )
    conn.commit()
    evidence = _proof_evidence((successful_retry,))
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: evidence,
    )

    response = _execute(
        native_harness,
        _request(filters={"symbol": {"eq": "RETRIED"}}),
    )

    assert response["data"] == [
        {"symbol": "RETRIED", "trade_date": "20260715"}
    ]


def test_default_query_keeps_valid_rows_from_independent_executions(
    native_harness: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = native_harness["conn"]
    dataset = native_harness["dataset"]
    ids = []
    for index in range(2):
        receipt = _insert_native_success_receipt(
            monkeypatch, conn, dataset, execution_id=f"separate-{index}", call_index=0, page_offset=0,
        )
        ids.append(receipt)
        _insert_row(conn, row_key=f"separate-{index}", payload={"symbol": f"SEPARATE_{index}", "trade_date": "20260715"}, receipt_id=receipt)
    conn.commit()
    monkeypatch.setattr(query_module, "project_dataset_runtime_evidence", lambda *a, **k: _proof_evidence(tuple(ids)))
    request = _request(filters={"symbol": {"in": ["SEPARATE_0", "SEPARATE_1"]}})
    result = _execute(native_harness, request)
    assert [row["symbol"] for row in result["data"]] == ["SEPARATE_0", "SEPARATE_1"]
    assert "row_receipt_proofs" not in result["metadata"]
    with pytest.raises(QueryServiceUnavailable):
        _execute(native_harness, replace(request, include_receipt_proofs=True))
