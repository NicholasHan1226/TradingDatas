from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
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
    load_dataset_registry,
)
from query_contract import QueryAccessContext, QueryExecutionOptions, QueryRequest
from query_cursor import SignedCursorCodec
from query_service import QueryService, QueryServiceUnavailable
from storage.receipt_projection import DatasetRuntimeEvidence, DatasetRuntimeProjection


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
) -> None:
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

    def project(*_args: object, **kwargs: object) -> DatasetRuntimeEvidence:
        if kwargs.get("evidence_as_of") is None:
            return evidence
        return replace(
            evidence,
            as_of_success_receipt_ids=(
                "receipt-current",
                "receipt:provider-a:row-a",
                "receipt:provider-a:row-b",
                "receipt:provider-b:row-c",
            ),
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
        receipt_id="receipt-later",
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
        receipt_id="receipt-later",
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
    permitted = {
        "receipt-current",
        "receipt:provider-a:row-a",
        "receipt:provider-a:row-b",
        "receipt:provider-b:row-c",
    }
    for index, symbol in enumerate("CDEFGHIJKL", start=1):
        receipt_id = f"receipt:append-only-first:{index}"
        permitted.add(receipt_id)
        _insert_row(
            native_harness["conn"],
            provider="provider-a",
            row_key=f"append-only-first-{index}",
            payload={
                "symbol": symbol,
                "trade_date": "20260716",
                "note": "first append-only provenance",
                "big": index,
            },
            receipt_id=receipt_id,
        )
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
        receipt_id="receipt:append-only-later",
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
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
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
                f"receipt:provider-a:{index:05d}",
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
) -> None:
    conn = native_harness["conn"]
    conn.execute("DELETE FROM provider_dataset_rows")
    conn.execute(
        "CREATE INDEX provider_dataset_rows_partition_idx "
        "ON provider_dataset_rows(dataset_id, provider, schema_major, "
        "partition_value, row_key)"
    )
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
                f"receipt:provider-a:partition-{index:05d}",
                1,
            )
        )
    conn.executemany(
        "INSERT INTO provider_dataset_rows VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

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
