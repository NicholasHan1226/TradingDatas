from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import importlib
import importlib.util
from pathlib import Path

import pytest

import api_server
import legacy_query_compat
from dataset_registry import load_dataset_registry
from query_contract import QueryBudgetError, QueryValidationError
from query_cursor import CursorMismatch
from query_service import QueryAccessDenied
from test_query_service import (  # noqa: F401 - imported fixture is consumed by pytest
    NOW as QUERY_SERVICE_NOW,
    _harness_request,
    query_harness,
)


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
SIGNING_KEY = b"legacy-compat-test-signing-key-32-bytes"


def _compat():
    from legacy_query_compat import LegacyQueryCompat

    return LegacyQueryCompat(load_dataset_registry())


def _filters(request: object) -> dict[str, dict[str, object]]:
    raw = getattr(request, "filters")
    return {field: dict(clause) for field, clause in raw.items()}


def test_legacy_compat_module_is_present_before_behavior_checks() -> None:
    assert importlib.util.find_spec("legacy_query_compat") is not None


def test_tushare_daily_translates_only_into_registry_query_contract() -> None:
    invocation = _compat().tushare_request(
        {
            "api_name": "daily",
            "ts_code": "600000.SH",
            "start_date": "2026-07-01",
            "end_date": "20260716",
            "limit": "17",
            "cursor": "signed-cursor",
        }
    )

    assert invocation.request.dataset_id == "cn.equity.daily"
    assert invocation.request.schema_major == 1
    assert invocation.request.fields == ()
    assert _filters(invocation.request) == {
        "symbol": {"eq": "600000.SH"},
        "trade_date": {"between": ("20260701", "20260716")},
    }
    assert invocation.request.order == ("trade_date:desc",)
    assert invocation.request.limit == 17
    assert invocation.request.cursor == "signed-cursor"
    assert invocation.options.latest_partition is False
    assert invocation.options.any_of_eq_filters == ()


def test_partitioned_legacy_query_without_dates_requests_internal_latest_partition() -> None:
    invocation = _compat().tushare_request(
        {"api_name": "daily", "limit": "500"}
    )

    assert invocation.options.latest_partition is True
    assert "trade_date" not in invocation.request.filters


@pytest.mark.parametrize(
    ("api_name", "dataset_id", "symbol_field", "date_field"),
    [
        ("daily", "cn.equity.daily", "symbol", "trade_date"),
        ("weekly", "cn.equity.weekly", "symbol", "trade_date"),
        ("stock_basic", "cn.equity.security_master", "symbol", "updated_at"),
        ("daily_basic", "cn.equity.daily_metrics", "symbol", "event_time"),
        ("broker_recommend", "cn.equity.broker_research", "symbol", "trade_date"),
        ("news", "cn.event.news", "symbol", "trade_date"),
        (
            "fund_portfolio",
            "cn.fund.portfolio",
            "symbol",
            "ann_date",
        ),
    ],
)
def test_schema_profiles_use_declared_symbol_date_and_default_projection(
    api_name: str,
    dataset_id: str,
    symbol_field: str,
    date_field: str,
) -> None:
    invocation = _compat().tushare_request(
        {
            "api_name": api_name,
            "ts_code": "000001.SZ",
            "start_date": "20260701",
            "end_date": "20260716",
        }
    )

    assert invocation.request.dataset_id == dataset_id
    assert invocation.request.fields == ()
    assert _filters(invocation.request)[symbol_field] == {"eq": "000001.SZ"}
    assert _filters(invocation.request)[date_field] == {
        "between": ("20260701", "20260716")
    }
    declared = {field.name for field in load_dataset_registry().resolve(dataset_id).fields}
    assert set(invocation.request.filters) <= declared


def test_relationship_symbol_filter_preserves_subject_object_or_semantics() -> None:
    invocation = _compat().tushare_request(
        {"api_name": "concept_detail", "ts_code": "600000.SH"}
    )

    assert invocation.request.dataset_id == "cn.equity.concept_membership"
    assert invocation.request.filters == {}
    assert invocation.options.any_of_eq_filters == (
        ("child_symbol", "600000.SH"),
        ("parent_symbol", "600000.SH"),
    )


def test_stock_basic_and_stock_company_are_not_mixed() -> None:
    registry = load_dataset_registry()
    compat = _compat()

    stock_basic = compat.tushare_request({"api_name": "stock_basic"})
    stock_company = compat.tushare_request({"api_name": "stock_company"})
    stock_master = compat.stock_master_request({"table": "stock_master"})

    assert stock_basic.request.dataset_id == "cn.equity.security_master"
    assert stock_master.request.dataset_id == stock_basic.request.dataset_id
    assert stock_company.request.dataset_id == "cn.company.profile"
    assert stock_basic.request.filters == {}
    assert stock_company.request.filters == {}
    assert registry.resolve(stock_basic.request.dataset_id).read_model_adapter.fixed_field_filters[0].allowed_values == (
        "tushare_stock_basic",
    )
    assert registry.resolve(stock_company.request.dataset_id).read_model_adapter.fixed_field_filters[0].allowed_values == (
        "tushare_stock_company",
    )


def test_every_imported_tushare_alias_resolves_exactly_one_registry_definition() -> None:
    registry = load_dataset_registry()
    compat = _compat()
    api_names = registry.compatibility_api_names("tushare")

    assert len(api_names) == 114
    for api_name in sorted(api_names):
        invocation = compat.tushare_request({"api_name": api_name})
        expected = registry.resolve(f"tushare.{api_name}")
        assert invocation.request.dataset_id == expected.dataset_id
        assert invocation.request.fields == ()
        declared_fields = {field.name for field in expected.fields}
        assert set(invocation.request.filters) <= declared_fields
        assert {
            field for field, _value in invocation.options.any_of_eq_filters
        } <= declared_fields
        assert not invocation.options.latest_partition or expected.partition_field is not None


def test_stock_master_is_the_only_reference_translation_and_is_cursor_bounded() -> None:
    compat = _compat()
    invocation = compat.stock_master_request(
        {"table": "stock_master", "limit": "500", "cursor": "signed-cursor"}
    )

    assert invocation.request.dataset_id == "cn.equity.security_master"
    assert invocation.request.fields == ()
    assert invocation.request.filters == {}
    assert invocation.request.order == ("symbol:asc",)
    assert invocation.request.limit == 500
    assert invocation.request.cursor == "signed-cursor"
    assert invocation.options.latest_partition is False
    with pytest.raises(QueryValidationError, match="stock_master"):
        compat.stock_master_request({"table": "legacy_csv"})


@pytest.mark.parametrize(
    "raw",
    ["stock_master", "STOCK_MASTER", " Stock_Master ", "\tstock_master\n"],
)
def test_stock_master_table_normalizer_accepts_one_shared_canonical_family(
    raw: str,
) -> None:
    assert legacy_query_compat.normalize_stock_master_table(raw) == "stock_master"


@pytest.mark.parametrize("raw", ["", "stock-master", "stock_master_extra", None, 1])
def test_stock_master_table_normalizer_rejects_non_family_values(raw: object) -> None:
    assert legacy_query_compat.normalize_stock_master_table(raw) is None


@pytest.mark.parametrize("raw", ["0", "+1", "01", " 1", "1.0", ""])
def test_legacy_limit_requires_a_canonical_positive_integer(raw: str) -> None:
    with pytest.raises(QueryValidationError, match="limit"):
        _compat().tushare_request({"api_name": "daily", "limit": raw})


@pytest.mark.parametrize("raw", ["501", "6000", "10000"])
def test_legacy_limit_above_500_is_a_budget_error(raw: str) -> None:
    with pytest.raises(QueryBudgetError, match="500"):
        _compat().stock_master_request({"table": "stock_master", "limit": raw})


def test_legacy_envelope_retains_query_metadata_and_signed_cursor() -> None:
    query_envelope = {
        "api_version": "v1",
        "catalog_version": "catalog-v1",
        "request_id": "request-1",
        "dataset_id": "cn.equity.daily",
        "schema_version": "1.0.0",
        "data": [{"symbol": "000001.SZ"}, {"symbol": "600000.SH"}],
        "next_cursor": "signed-next-page",
        "metadata": {
            "state": "failed",
            "runtime_state": "failed",
            "degraded": True,
            "freshness": {"state": "failed", "stale": False, "sla_seconds": 1},
            "quality": {"state": "degraded", "valid": False, "evidence": ["provider_error"]},
            "lineage": {
                "authority": "sqlite_ingest_receipts",
                "providers": ["tushare"],
                "receipt_watermark": "watermark-1",
            },
            "receipt_id": "receipt-1",
            "data_through": "20260716",
            "observed_at": "2026-07-16T03:00:00+00:00",
            "reasons": ["provider_error"],
        },
    }

    legacy = _compat().legacy_envelope(query_envelope)

    assert legacy["data"] == query_envelope["data"]
    assert legacy["source"] == "tushare"
    assert legacy["metadata"]["runtime_state"] == "failed"
    assert legacy["metadata"]["data_through"] == "20260716"
    assert legacy["metadata"]["observed_at"] == "2026-07-16T03:00:00+00:00"
    assert legacy["metadata"]["quality"]["evidence"] == ["provider_error"]
    assert legacy["metadata"]["lineage"]["receipt_watermark"] == "watermark-1"
    assert legacy["metadata"]["next_cursor"] == "signed-next-page"
    assert legacy["metadata"]["row_count"] == 2
    assert legacy["metadata"]["degraded_reasons"] == ["provider_error"]


@pytest.mark.parametrize("surface", ["tushare", "stock_master"])
@pytest.mark.parametrize(
    ("runtime_state", "degraded", "has_rows"),
    [
        ("success", False, True),
        ("empty", False, False),
        ("unobserved", True, False),
        ("paused", True, False),
        ("failed", True, True),
        ("stale", True, True),
    ],
)
def test_both_legacy_surfaces_preserve_every_query_service_receipt_state(
    surface: str,
    runtime_state: str,
    degraded: bool,
    has_rows: bool,
) -> None:
    compat = _compat()
    invocation = (
        compat.tushare_request({"api_name": "daily"})
        if surface == "tushare"
        else compat.stock_master_request({"table": "stock_master"})
    )
    rows = [{"symbol": "000001.SZ"}] if has_rows else []
    reasons = [] if runtime_state == "success" else [f"{runtime_state}_evidence"]
    query_envelope = {
        "api_version": "v1",
        "catalog_version": "catalog-v1",
        "request_id": f"request-{surface}-{runtime_state}",
        "dataset_id": invocation.request.dataset_id,
        "schema_version": "1.0.0",
        "data": rows,
        "next_cursor": "signed-next-page" if has_rows else None,
        "metadata": {
            "state": "ready" if runtime_state == "success" else runtime_state,
            "runtime_state": runtime_state,
            "degraded": degraded,
            "freshness": {
                "state": "fresh" if runtime_state == "success" else runtime_state,
                "stale": runtime_state == "stale",
                "sla_seconds": 86_400,
            },
            "quality": {
                "state": "valid" if not degraded else "degraded",
                "valid": not degraded,
                "evidence": reasons,
            },
            "lineage": {
                "authority": "sqlite_ingest_receipts",
                "providers": ["tushare"],
                "receipt_watermark": f"watermark-{runtime_state}",
            },
            "receipt_id": f"receipt-{runtime_state}",
            "data_through": "20260716" if has_rows else None,
            "observed_at": "2026-07-16T03:00:00+00:00" if has_rows else None,
            "reasons": reasons,
        },
    }

    legacy = compat.legacy_envelope(query_envelope)

    assert legacy["data"] == rows
    assert legacy["metadata"]["runtime_state"] == runtime_state
    assert legacy["metadata"]["degraded"] is degraded
    assert legacy["metadata"]["next_cursor"] == (
        "signed-next-page" if has_rows else None
    )
    assert legacy["metadata"]["receipt_id"] == f"receipt-{runtime_state}"
    assert legacy["metadata"]["lineage"]["receipt_watermark"] == (
        f"watermark-{runtime_state}"
    )


def test_api_v1_and_reader_dependency_hooks_share_the_exact_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server
    import data_plane_runtime
    import reader

    monkeypatch.setenv(
        "SHAREDSIGNALS_CURSOR_SIGNING_KEY",
        "phase2-test-signing-key-32-bytes-minimum",
    )
    data_plane_runtime._reset_data_plane_runtime_for_tests()
    try:
        runtime = data_plane_runtime.build_data_plane_runtime()

        assert api_server._build_data_plane_runtime() is runtime
        assert reader._build_data_plane_runtime() is runtime
        assert api_server._build_v1_services() is runtime.services
    finally:
        data_plane_runtime._reset_data_plane_runtime_for_tests()


def test_legacy_http_request_access_uses_only_resolved_dataset_and_ignores_forged_policy() -> None:
    access = api_server._legacy_request_access_context(
        {
            "tenant_id": "tenant-narrow",
            "tier": "research",
            "scopes": ["tushare", "tushare"],
            "allowed_dataset_ids": ["cn.secret.dataset"],
            "policy_id": "attacker-policy",
        },
        "cn.event.news",
    )

    assert access.tenant_id == "tenant-narrow"
    assert access.scopes == ("tushare",)
    assert access.allowed_dataset_ids == ("cn.event.news",)
    assert access.policy_id != "attacker-policy"


def test_request_local_grant_cannot_query_another_dataset_and_cursor_is_policy_bound(
    query_harness: dict[str, object],  # noqa: F811 - pytest imported fixture
) -> None:
    access = api_server._legacy_request_access_context(
        {
            "tenant_id": "tenant-a",
            "tier": "research",
            "scopes": ["tushare"],
        },
        "cn.test.quotes",
    )
    first = query_harness["service"].execute(
        _harness_request(limit=1, order=("score:desc",)),
        access=access,
        now=QUERY_SERVICE_NOW,
        request_id="request-local-first",
    )
    cursor = first["next_cursor"]
    assert cursor is not None

    wrong_dataset = api_server._legacy_request_access_context(
        {
            "tenant_id": "tenant-a",
            "tier": "research",
            "scopes": ["tushare"],
        },
        "cn.other.dataset",
    )
    with pytest.raises(QueryAccessDenied, match="query access is denied"):
        query_harness["service"].execute(
            _harness_request(limit=1),
            access=wrong_dataset,
            now=QUERY_SERVICE_NOW,
            request_id="request-local-other-dataset",
        )

    other_tenant = api_server._legacy_request_access_context(
        {
            "tenant_id": "tenant-b",
            "tier": "research",
            "scopes": ["tushare"],
        },
        "cn.test.quotes",
    )
    with pytest.raises(CursorMismatch, match="policy"):
        query_harness["service"].execute(
            _harness_request(
                limit=1,
                order=("score:desc",),
                cursor=cursor,
            ),
            access=other_tenant,
            now=QUERY_SERVICE_NOW,
            request_id="request-local-other-policy",
        )


def test_data_plane_runtime_is_one_immutable_lazily_published_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_plane_runtime
    import catalog_service  # noqa: F401 - settle import-time contract defaults
    import dataset_registry
    import legacy_query_compat  # noqa: F401 - settle import-time contract defaults
    import query_cursor
    import query_service  # noqa: F401 - settle import-time contract defaults
    import runtime_paths

    registry = load_dataset_registry()
    calls = {"registry": 0, "cursor": 0}

    def registry_once():
        calls["registry"] += 1
        return registry

    def cursor_once(_cls: object):
        calls["cursor"] += 1
        return query_cursor.SignedCursorCodec(SIGNING_KEY)

    monkeypatch.setattr(dataset_registry, "load_dataset_registry", registry_once)
    monkeypatch.setattr(
        query_cursor.SignedCursorCodec,
        "from_env",
        classmethod(cursor_once),
    )
    monkeypatch.setattr(
        runtime_paths,
        "marketdata_sqlite_path",
        lambda: tmp_path / "read-model.sqlite",
    )
    reloaded = importlib.reload(data_plane_runtime)
    reloaded._reset_data_plane_runtime_for_tests()

    try:
        first = reloaded.build_data_plane_runtime()
        second = reloaded.build_data_plane_runtime()

        assert first is second
        assert first.registry is registry
        assert first.services is reloaded.build_data_plane_services()
        assert first.services is reloaded.build_data_plane_services()
        assert first.services == (first.catalog, first.query)
        assert calls == {"registry": 1, "cursor": 1}
        with pytest.raises(FrozenInstanceError):
            first.query = object()  # type: ignore[misc]
        reloaded._reset_data_plane_runtime_for_tests()
        assert reloaded.build_data_plane_runtime() is not first
    finally:
        reloaded._reset_data_plane_runtime_for_tests()


def test_data_plane_runtime_does_not_publish_a_partial_failed_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_plane_runtime
    import query_cursor
    import runtime_paths

    def fail_cursor(_cls: object):
        raise RuntimeError("construction failed")

    monkeypatch.setattr(
        runtime_paths,
        "marketdata_sqlite_path",
        lambda: tmp_path / "read-model.sqlite",
    )
    monkeypatch.setattr(
        query_cursor.SignedCursorCodec,
        "from_env",
        classmethod(fail_cursor),
    )
    data_plane_runtime._reset_data_plane_runtime_for_tests()
    try:
        with pytest.raises(RuntimeError, match="construction failed"):
            data_plane_runtime.build_data_plane_runtime()

        assert data_plane_runtime._RUNTIME is None
        assert data_plane_runtime._SERVICES is None

        monkeypatch.setattr(
            query_cursor.SignedCursorCodec,
            "from_env",
            classmethod(lambda _cls: query_cursor.SignedCursorCodec(SIGNING_KEY)),
        )
        runtime = data_plane_runtime.build_data_plane_runtime()
        assert runtime.services == (runtime.catalog, runtime.query)
    finally:
        data_plane_runtime._reset_data_plane_runtime_for_tests()
