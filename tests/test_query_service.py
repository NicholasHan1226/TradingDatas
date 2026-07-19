from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from catalog_service import DatasetQueryability
from dataset_registry import DatasetRegistry, load_dataset_registry
from query_contract import QueryAccessContext, QueryRequest
from query_cursor import SignedCursorCodec
import query_service as query_module
from query_service import QueryService, QueryServiceUnavailable
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    DatasetRuntimeProjection,
)


SIGNING_KEY = b"query-service-test-signing-key-32-bytes"
NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


def test_query_service_constructor_keeps_only_frozen_injected_dependencies(
    tmp_path: Path,
) -> None:
    registry = load_dataset_registry()
    codec = SignedCursorCodec(SIGNING_KEY)
    db_path = (tmp_path / "read-model.sqlite").absolute()

    service = QueryService(
        db_path=db_path,
        registry=registry,
        cursor_codec=codec,
    )

    assert service._db_path == db_path
    assert service._registry is registry
    assert service._cursor_codec is codec


def test_query_service_rejects_arbitrary_table_before_any_sql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = load_dataset_registry()
    base = source.resolve("cn.equity.daily")
    binding = replace(
        base.provider_bindings[0],
        target_tables=("facts_quotes",),
    )
    dataset = replace(
        base,
        provider_bindings=(binding,),
        read_model_adapter=replace(
            base.read_model_adapter,
            storage_kind="typed_columns",
            primary_table="facts_quotes",
        ),
    )
    registry = DatasetRegistry((dataset,), query_defaults=source.query_defaults)
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "facts_quotes" ("payload_json" TEXT)')
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    @contextmanager
    def snapshot(_path: Path):
        yield conn

    monkeypatch.setattr(query_module, "_query_snapshot", snapshot)
    monkeypatch.setattr(
        query_module,
        "inspect_dataset_queryability",
        lambda _conn, _dataset: DatasetQueryability(True, ()),
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: DatasetRuntimeEvidence(
            projection=DatasetRuntimeProjection(
                dataset_id=dataset.dataset_id,
                state="unobserved",
                degraded=True,
                data_through=None,
                observed_at=None,
                receipt_id=None,
                reasons=("no_recognized_receipt",),
            ),
            current_receipt_status=None,
            current_providers=(),
            last_success_receipt_id=None,
            last_success_providers=(),
            last_success_data_through=None,
        ),
    )
    service = QueryService(
        db_path=(tmp_path / "read-model.sqlite").absolute(),
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=(dataset.default_projection[0],),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    access = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=(dataset.required_scope,),
        allowed_dataset_ids=(),
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        service.execute(
            request,
            access=access,
            now=NOW,
            request_id="request-arbitrary-table",
        )

    assert statements == ["BEGIN"]
    assert all("facts_quotes" not in statement for statement in statements)
    conn.close()
