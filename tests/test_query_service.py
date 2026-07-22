from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

import collectors.tushare.tushare_common as tushare_common
from catalog_service import DatasetQueryability, is_initial_release_eligible
from dataset_registry import DatasetRegistry, load_dataset_registry
from provider_ingest_contract import provider_ingest_config_hash
from provider_transport import provider_transport_profile
from query_contract import QueryAccessContext, QueryExecutionOptions, QueryRequest
from query_cursor import SignedCursorCodec
import query_service as query_module
from query_service import QueryDatasetNotFound, QueryService, QueryServiceUnavailable
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    DatasetRuntimeProjection,
)


SIGNING_KEY = b"query-service-test-signing-key-32-bytes"
NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("state", "providers", "expected_service"),
    (
        pytest.param("success", ("tushare",), "quicksync", id="trusted-tushare"),
        pytest.param("success", ("provider-a",), None, id="other-provider"),
        pytest.param("unobserved", (), None, id="incomplete-lineage"),
    ),
)
def test_runtime_lineage_binds_quicksync_transport_only_to_complete_tushare(
    state: str,
    providers: tuple[str, ...],
    expected_service: str | None,
) -> None:
    registry = load_dataset_registry()
    dataset = registry.resolve("cn.equity.daily")
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=dataset.default_projection,
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(  # noqa: SLF001
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=NOW,
    )
    complete = state == "success"
    provider_config_hashes = (
        (
            (
                "tushare",
                provider_ingest_config_hash(dataset, dataset.provider_bindings[0]),
            ),
        )
        if providers == ("tushare",)
        else ()
    )
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state=state,
            degraded=not complete,
            data_through="20260719" if complete else None,
            observed_at="2026-07-20T03:00:00+00:00" if complete else None,
            receipt_id="receipt-current" if complete else None,
            reasons=() if complete else ("no_recognized_receipt",),
        ),
        current_receipt_status="success" if complete else None,
        current_providers=providers,
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=provider_config_hashes,
    )

    metadata, _allow_rows = query_module._runtime_metadata(  # noqa: SLF001
        dataset,
        prepared,
        evidence,
        "watermark-test",
    )
    lineage = metadata["lineage"]
    assert lineage["transport_service"] == expected_service
    if expected_service is None:
        assert lineage["transport_profile_id"] is None
        assert lineage["transport_profile_sha256"] is None
    else:
        profile = provider_transport_profile("tushare")
        assert lineage["transport_profile_id"] == profile["profile_id"]
        assert lineage["transport_profile_sha256"] == profile["profile_sha256"]


def test_runtime_lineage_fails_closed_for_unbound_tushare_config_hash() -> None:
    registry = load_dataset_registry()
    dataset = registry.resolve("cn.equity.daily")
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=dataset.default_projection,
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(  # noqa: SLF001
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=NOW,
    )
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="success",
            degraded=False,
            data_through="20260719",
            observed_at="2026-07-20T03:00:00+00:00",
            receipt_id="receipt-old-transport",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("tushare",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=(("tushare", "a" * 64),),
    )

    metadata, allow_rows = query_module._runtime_metadata(  # noqa: SLF001
        dataset,
        prepared,
        evidence,
        "watermark-old-transport",
    )

    assert allow_rows is False
    assert metadata["state"] == "failed"
    assert metadata["degraded"] is True
    assert metadata["reasons"] == ["transport_profile_unverified"]
    assert metadata["lineage"]["complete"] is False
    assert metadata["lineage"]["transport_service"] is None


def test_success_without_response_completeness_is_partial_but_keeps_rows() -> None:
    source = load_dataset_registry()
    base = source.resolve("cn.equity.daily")
    binding = replace(base.provider_bindings[0], response_completeness=None)
    dataset = replace(base, provider_bindings=(binding,))
    registry = DatasetRegistry((dataset,), query_defaults=source.query_defaults)
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(  # noqa: SLF001
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=NOW,
    )
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="success",
            degraded=False,
            data_through="20260719",
            observed_at="2026-07-20T03:00:00+00:00",
            receipt_id="receipt-without-completeness-contract",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("tushare",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=(
            ("tushare", provider_ingest_config_hash(dataset, binding)),
        ),
    )

    metadata, allow_rows = query_module._runtime_metadata(  # noqa: SLF001
        dataset,
        prepared,
        evidence,
        "watermark-without-completeness-contract",
    )

    assert allow_rows is True
    assert metadata["state"] == "partial"
    assert metadata["runtime_state"] == "success"
    assert metadata["degraded"] is True
    assert metadata["freshness"] == {
        "state": "fresh",
        "stale": False,
        "sla_seconds": dataset.freshness_sla_seconds,
    }
    assert metadata["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": ["response_completeness_unverified"],
    }
    assert metadata["data_through"] == "2026-07-19T00:00:00+08:00"
    assert metadata["reasons"] == ["response_completeness_unverified"]
    assert metadata["lineage"]["complete"] is True
    assert metadata["lineage"]["transport_service"] == "quicksync"


def test_empty_without_response_completeness_is_partial_and_keeps_lineage() -> None:
    source = load_dataset_registry()
    base = source.resolve("cn.equity.daily")
    binding = replace(base.provider_bindings[0], response_completeness=None)
    assert binding.request_window_policy is not None
    dataset = replace(
        base,
        provider_bindings=(binding,),
        as_of_field=None,
        range_field=None,
        partition_field=None,
    )
    registry = DatasetRegistry((dataset,), query_defaults=source.query_defaults)
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(  # noqa: SLF001
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=NOW,
    )
    receipt_id = "receipt-empty-without-completeness-contract"
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="empty",
            degraded=False,
            data_through=None,
            observed_at="2026-07-20T03:00:00+00:00",
            receipt_id=receipt_id,
            reasons=(),
        ),
        current_receipt_status="empty",
        current_providers=("tushare",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=(
            ("tushare", provider_ingest_config_hash(dataset, binding)),
        ),
    )

    metadata, allow_rows = query_module._runtime_metadata(  # noqa: SLF001
        dataset,
        prepared,
        evidence,
        "watermark-empty-without-completeness-contract",
    )

    expected_reasons = [
        "freshness_watermark_unverified",
        "response_completeness_unverified",
    ]
    assert allow_rows is False
    assert metadata["state"] == "partial"
    assert metadata["runtime_state"] == "empty"
    assert metadata["degraded"] is True
    assert metadata["freshness"] == {
        "state": "unknown",
        "stale": False,
        "sla_seconds": dataset.freshness_sla_seconds,
    }
    assert metadata["quality"] == {
        "state": "degraded",
        "valid": False,
        "evidence": expected_reasons,
    }
    assert metadata["receipt_id"] == receipt_id
    assert metadata["observed_at"] == "2026-07-20T03:00:00+00:00"
    assert metadata["lineage"]["complete"] is True
    assert metadata["lineage"]["providers"] == ["tushare"]
    assert metadata["lineage"]["transport_service"] == "quicksync"
    assert metadata["reasons"] == expected_reasons


@pytest.mark.parametrize(
    "dataset_id",
    (
        "cn.dataset.index_classify",
        "cn.dataset.sw_daily",
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    ),
)
def test_reviewed_active_completeness_contracts_stay_ready_fresh_and_valid(
    dataset_id: str,
) -> None:
    registry = load_dataset_registry()
    dataset = registry.resolve(dataset_id)
    active_bindings = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )
    assert len(active_bindings) == 1
    binding = active_bindings[0]
    assert binding.response_completeness is not None
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(  # noqa: SLF001
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=NOW,
    )
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="success",
            degraded=False,
            data_through="20260719",
            observed_at="2026-07-20T03:00:00+00:00",
            receipt_id=f"receipt-reviewed-{dataset.dataset_id}",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("tushare",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=(
            ("tushare", provider_ingest_config_hash(dataset, binding)),
        ),
    )

    metadata, allow_rows = query_module._runtime_metadata(  # noqa: SLF001
        dataset,
        prepared,
        evidence,
        f"watermark-reviewed-{dataset.dataset_id}",
    )

    assert allow_rows is True
    assert metadata["state"] == "ready"
    assert metadata["runtime_state"] == "success"
    assert metadata["degraded"] is False
    assert metadata["freshness"]["state"] == "fresh"
    assert metadata["quality"] == {
        "state": "valid",
        "valid": True,
        "evidence": [],
    }
    assert metadata["reasons"] == []


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


@pytest.mark.parametrize(
    ("primary_states", "secondary_states", "market"),
    (
        pytest.param(("locked", "paused"), None, "CN", id="locked-paused"),
        pytest.param(("active", "paused"), None, "CN", id="active-paused"),
        pytest.param(("locked", "active"), None, "CN", id="locked-active"),
        pytest.param(
            ("active", "paused"),
            ("locked", "active"),
            "CN",
            id="multi-binding-cross-match",
        ),
        pytest.param(("active", "active"), None, "US", id="foreign"),
    ),
)
def test_ineligible_binding_combinations_fail_before_storage_or_provider(
    primary_states: tuple[str, str],
    secondary_states: tuple[str, str] | None,
    market: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = load_dataset_registry()
    base = source.resolve("cn.equity.daily")
    primary = replace(
        base.provider_bindings[0],
        entitlement_state=primary_states[0],
        activation_state=primary_states[1],
    )
    bindings = (primary,)
    if secondary_states is not None:
        bindings += (
            replace(
                primary,
                provider="cross_match_provider",
                api_name="cross_match_api",
                read_discriminator_value="cross_match_lane",
                entitlement_state=secondary_states[0],
                activation_state=secondary_states[1],
            ),
        )
    dataset = replace(base, market=market, provider_bindings=bindings)
    registry = DatasetRegistry((dataset,), query_defaults=source.query_defaults)
    db_path = (tmp_path / "must-not-open.sqlite").absolute()

    assert not is_initial_release_eligible(dataset)
    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "ineligible V1 query must not call the provider"
        ),
    )
    monkeypatch.setattr(
        query_module,
        "_query_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "ineligible V1 query must fail before opening SQLite"
        ),
    )
    service = QueryService(
        db_path=db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=dataset.schema_major,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    access = QueryAccessContext.from_grants(
        tenant_id="ineligible-binding-audit",
        scopes=(dataset.required_scope,),
        allowed_dataset_ids=(),
    )

    with pytest.raises(QueryDatasetNotFound, match="dataset is not available"):
        service.execute(
            request,
            access=access,
            now=NOW,
            request_id="ineligible-binding-combination",
        )
    assert not db_path.exists()


def test_all_181_non_active_target_datasets_fail_before_storage_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_dataset_registry()
    bindings = tuple(
        binding
        for dataset in registry.datasets
        for binding in dataset.provider_bindings
    )
    assert len(registry.datasets) == len(bindings) == 190
    assert {
        state: sum(binding.entitlement_state == state for binding in bindings)
        for state in ("active", "locked", "excluded", "unknown")
    } == {"active": 170, "locked": 14, "excluded": 5, "unknown": 1}
    assert {
        state: sum(binding.activation_state == state for binding in bindings)
        for state in ("active", "paused")
    } == {"active": 9, "paused": 181}

    active = tuple(
        dataset for dataset in registry.datasets if is_initial_release_eligible(dataset)
    )
    non_active = tuple(
        dataset
        for dataset in registry.datasets
        if not is_initial_release_eligible(dataset)
    )
    assert {dataset.dataset_id for dataset in active} == {
        "cn.dataset.adj_factor",
        "cn.dataset.index_classify",
        "cn.dataset.sw_daily",
        "cn.dataset.stk_auction",
        "cn.dataset.stk_limit",
        "cn.dataset.suspend_d",
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }
    assert len(non_active) == 181
    excluded = tuple(
        dataset
        for dataset in non_active
        if {binding.entitlement_state for binding in dataset.provider_bindings}
        == {"excluded"}
    )
    assert {dataset.dataset_id for dataset in excluded} == {
        "cn.dataset.etf_sh_cons",
        "cn.dataset.fut_trade_cal",
        "cn.dataset.monetary_policy",
        "cn.dataset.rt_etf_min",
        "cn.dataset.rt_etf_min_daily",
    }
    monkeypatch.setattr(
        tushare_common,
        "_provider_urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "non-active V1 query must not call the provider"
        ),
    )
    monkeypatch.setattr(
        query_module,
        "_query_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "non-active V1 query must fail before opening SQLite"
        ),
    )
    db_path = (tmp_path / "unopened.sqlite").absolute()
    service = QueryService(
        db_path=db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )

    for dataset in non_active:
        request = QueryRequest(
            dataset_id=dataset.dataset_id,
            schema_major=dataset.schema_major,
            fields=(),
            filters={},
            as_of=None,
            order=None,
            limit=1,
            cursor=None,
        )
        access = QueryAccessContext.from_grants(
            tenant_id="non-active-query-audit",
            scopes=(dataset.required_scope,),
            allowed_dataset_ids=(),
        )
        with pytest.raises(QueryDatasetNotFound, match="dataset is not available"):
            service.execute(
                request,
                access=access,
                now=NOW,
                request_id=f"non-active-{dataset.dataset_id}",
            )
    assert not db_path.exists()


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
