from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import catalog_service as catalog_module
import storage.ingest_receipts as receipt_module
import storage.receipt_projection as receipt_projection_module
from catalog_service import (
    CatalogService,
    CatalogFilters,
    DatasetQueryability,
    inspect_dataset_queryability,
    is_catalog_discoverable,
    is_initial_release_eligible,
)
from dataset_registry import (
    DatasetDefinition,
    DatasetField,
    DatasetRegistry,
    ProviderBinding,
    ReadModelAdapter,
    load_dataset_registry,
)
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryValidationError,
    public_catalog_version,
)
from query_cursor import (
    CursorConfigurationError,
    CursorExpectation,
    CursorMismatch,
    InvalidCursor,
    SignedCursorCodec,
)
from storage.ingest_receipts import IngestContext, IngestCounts, insert_ingest_receipt
from storage.receipt_projection import RuntimeProjectionError
from storage.schema import SCHEMA_SQL


def _dataset(**changes: object):
    base = load_dataset_registry().resolve("tushare.daily")
    return replace(base, **changes)


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
SIGNING_KEY = b"catalog-service-test-signing-key-32-bytes"
ROW_KEYS = {
    "dataset_id",
    "aliases",
    "domain",
    "market",
    "entity_type",
    "data_classification",
    "schema_version",
    "schema_major",
    "fields",
    "default_fields",
    "filter_operators",
    "sortable_fields",
    "default_order",
    "identity_fields",
    "cadence",
    "timezone",
    "freshness_sla_seconds",
    "limits",
    "point_in_time",
    "required_scope",
    "quota_class",
    "availability",
    "queryability",
    "runtime",
}


def _catalog_dataset(
    dataset_id: str,
    *,
    aliases: tuple[str, ...] = (),
    market: str = "CN",
    required_scope: str = "market_data",
    entitlement_state: str = "active",
    activation_state: str = "active",
    second_binding: bool = False,
) -> DatasetDefinition:
    base = _dataset()
    slug = dataset_id.replace(".", "_").replace("-", "_")
    primary = ProviderBinding(
        provider=f"source_{slug}",
        api_name=f"api_{slug}",
        adapter_version=f"write_{slug}.v1",
        read_discriminator_value=f"lane_{slug}",
        entitlement_state=entitlement_state,
        activation_state=activation_state,
        target_tables=("provider_dataset_rows",),
    )
    bindings = (primary,)
    if second_binding:
        bindings += (
            replace(
                primary,
                provider=f"mirror_{slug}",
                api_name=f"mirror_api_{slug}",
                read_discriminator_value=f"mirror_lane_{slug}",
                entitlement_state="unknown",
                activation_state="paused",
            ),
        )
    return replace(
        base,
        dataset_id=dataset_id,
        aliases=aliases,
        schema_version="1.2.0",
        domain="market_data",
        market=market,
        entity_type="quote",
        fields=(
            DatasetField("symbol", "text", False, True, True, True),
            DatasetField("value", "float", True, True, False, False),
            DatasetField("revision", "integer", False, True, True, True),
        ),
        primary_key=("symbol",),
        default_projection=("symbol", "value"),
        as_of_field=None,
        as_of_format=None,
        range_field=None,
        partition_field=None,
        cadence_class="postclose_daily",
        freshness_sla_seconds=3_600,
        max_page_size=2,
        max_lookback_days=365,
        required_scope=required_scope,
        provider_bindings=bindings,
        read_model_adapter=ReadModelAdapter(
            adapter_version=f"read_{slug}.v1",
            primary_table="provider_dataset_rows",
            fixed_field_filters=(),
            storage_kind="provider_native_rows",
            row_key_strategy="primary_key",
        ),
    )


def _queryable_table(conn: sqlite3.Connection, dataset: DatasetDefinition) -> None:
    del dataset
    conn.executescript(SCHEMA_SQL)


def _receipt_dataset(dataset: DatasetDefinition) -> DatasetDefinition:
    return replace(
        dataset,
        provider_bindings=tuple(
            replace(binding, target_tables=("provider_dataset_rows",))
            for binding in dataset.provider_bindings
        ),
        read_model_adapter=ReadModelAdapter(
            adapter_version="provider-native-json.v1",
            primary_table="provider_dataset_rows",
            fixed_field_filters=(),
            storage_kind="provider_native_rows",
            row_key_strategy="primary_key",
        ),
    )


def _runtime(
    dataset_id: str,
    state: str,
    *,
    receipt_id: str | None = None,
) -> dict[str, object]:
    degraded = state not in {"success", "empty"}
    observed = (
        None if state in {"unobserved", "paused"} else "2026-07-16T03:00:00+00:00"
    )
    through = "2026-07-16T03:00:00+00:00" if state in {"success", "stale"} else None
    reasons = {
        "success": [],
        "empty": ["provider_returned_no_rows"],
        "unobserved": ["no_recognized_receipt"],
        "paused": ["registry_activation_paused"],
        "failed": ["provider_error"],
        "stale": ["freshness_sla_exceeded"],
    }[state]
    return {
        "dataset_id": dataset_id,
        "state": state,
        "degraded": degraded,
        "data_through": through,
        "observed_at": observed,
        "receipt_id": receipt_id,
        "reasons": reasons,
    }


@pytest.fixture
def catalog_harness(tmp_path: Path):
    alpha = _catalog_dataset(
        "cn.catalog.alpha",
        aliases=("tushare.daily", "StraßeAlpha"),
        entitlement_state="locked",
        second_binding=True,
    )
    beta = _catalog_dataset(
        "cn.catalog.beta",
        aliases=("STRASSEBeta",),
        entitlement_state="unknown",
        activation_state="paused",
    )
    gamma = _catalog_dataset("cn.catalog.gamma", aliases=("PagedGamma",))
    hidden_scope = _catalog_dataset(
        "cn.catalog.hidden_scope",
        required_scope="fundamentals",
    )
    hidden_market = _catalog_dataset("us.catalog.hidden_market", market="US")
    excluded = _catalog_dataset(
        "cn.catalog.excluded",
        entitlement_state="excluded",
    )
    defaults = replace(
        load_dataset_registry().query_defaults,
        max_page_size=2,
        max_catalog_search_chars=12,
        cursor_ttl_seconds=60,
    )
    registry = DatasetRegistry(
        (alpha, beta, gamma, hidden_scope, hidden_market, excluded),
        query_defaults=defaults,
    )
    conn = sqlite3.connect(":memory:")
    for dataset in (alpha, gamma, hidden_scope, hidden_market, excluded):
        _queryable_table(conn, dataset)
    runtime = {
        alpha.dataset_id: _runtime(
            alpha.dataset_id, "success", receipt_id="receipt:alpha"
        ),
        beta.dataset_id: _runtime(beta.dataset_id, "paused"),
        gamma.dataset_id: _runtime(
            gamma.dataset_id, "empty", receipt_id="receipt:gamma"
        ),
        hidden_scope.dataset_id: _runtime(hidden_scope.dataset_id, "unobserved"),
        hidden_market.dataset_id: _runtime(
            hidden_market.dataset_id, "failed", receipt_id="receipt:us"
        ),
        excluded.dataset_id: _runtime(
            excluded.dataset_id, "stale", receipt_id="receipt:excluded"
        ),
    }
    harness = {
        "registry": registry,
        "datasets": {
            item.dataset_id: item
            for item in (alpha, beta, gamma, hidden_scope, hidden_market, excluded)
        },
        "conn": conn,
        "runtime": runtime,
        "db_path": (tmp_path / "read-model.sqlite").absolute(),
        "codec": SignedCursorCodec(SIGNING_KEY),
        "now": NOW,
        "access": QueryAccessContext.from_grants(
            tenant_id="tenant-a",
            scopes=("market_data",),
            allowed_dataset_ids=(hidden_scope.dataset_id,),
        ),
    }
    yield harness
    conn.close()


def _install_fake_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    harness: dict[str, object],
) -> dict[str, object]:
    calls: dict[str, object] = {"snapshot": 0, "projection": 0, "now": None}

    @contextmanager
    def snapshot(db_path: Path):
        calls["snapshot"] = int(calls["snapshot"]) + 1
        assert db_path == harness["db_path"]
        yield harness["conn"]

    def project(conn: sqlite3.Connection, registry: DatasetRegistry, *, now: datetime):
        calls["projection"] = int(calls["projection"]) + 1
        calls["now"] = now
        assert conn is harness["conn"]
        assert registry is harness["registry"]
        return {
            "datasets": harness["runtime"],
            "interfaces": {"must_not_leak": {"provider": "secret-source"}},
        }

    monkeypatch.setattr(catalog_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(catalog_module, "project_catalog_runtime", project)
    return calls


def _service(harness: dict[str, object]) -> CatalogService:
    return CatalogService(
        registry=harness["registry"],
        db_path=harness["db_path"],
        cursor_codec=harness["codec"],
    )


def _list(
    service: CatalogService,
    harness: dict[str, object],
    *,
    access: QueryAccessContext | None = None,
    filters: CatalogFilters | None = None,
    limit: int = 2,
    cursor: str | None = None,
    now: datetime | None = None,
    request_id: str = "request-1",
) -> dict[str, object]:
    return service.list_datasets(
        access=harness["access"] if access is None else access,
        filters=CatalogFilters() if filters is None else filters,
        limit=limit,
        cursor=cursor,
        now=harness["now"] if now is None else now,
        request_id=request_id,
    )


def _insert_runtime_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    status: str,
    suffix: str,
    started_at: str,
    finished_at: str,
    data_through: str | None,
) -> str:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    binding = dataset.provider_bindings[0]
    context = IngestContext(
        attempt_id=f"attempt-{suffix}",
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window={"window": suffix},
        config_hash="a" * 64,
        adapter_version=binding.adapter_version,
        started_at=started_at,
        data_through=data_through,
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
        target_table = binding.target_tables[0]
        errors: tuple[str, ...] = ()
    else:
        counts = IngestCounts(
            returned=0,
            validated=0,
            inserted=0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=0,
            count_semantics=(
                "terminal_no_data_transaction"
                if status == "empty"
                else "storage_failure_before_commit"
            ),
        )
        target_table = None
        errors = () if status == "empty" else ("provider_error",)
    receipt_id = insert_ingest_receipt(
        conn,
        context=context,
        target_table=target_table,
        transaction_index=0,
        status=status,
        counts=counts,
        errors=errors,
        payload_fingerprint="b" * 64,
    )
    conn.commit()
    return receipt_id


@pytest.fixture
def real_catalog_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        receipt_projection_module,
        "provider_ingest_config_hash",
        lambda _dataset, _binding: "a" * 64,
    )
    success = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.a_success",
            aliases=("tushare.daily",),
            entitlement_state="locked",
        )
    )
    empty = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.b_empty",
            entitlement_state="unknown",
        )
    )
    unobserved = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.c_unobserved",
            entitlement_state="unknown",
        )
    )
    paused = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.d_paused",
            entitlement_state="locked",
            activation_state="paused",
        )
    )
    failed = _receipt_dataset(_catalog_dataset("cn.runtime.e_failed"))
    stale = _receipt_dataset(_catalog_dataset("cn.runtime.f_stale"))
    excluded = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.g_excluded",
            entitlement_state="excluded",
            activation_state="paused",
        )
    )
    retired = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.h_retired",
            entitlement_state="retired",
            activation_state="paused",
        )
    )
    foreign = _receipt_dataset(_catalog_dataset("us.runtime.i_foreign", market="US"))
    other_scope = _receipt_dataset(
        _catalog_dataset(
            "cn.runtime.j_other_scope",
            required_scope="fundamentals",
        )
    )
    datasets = (
        success,
        empty,
        unobserved,
        paused,
        failed,
        stale,
        excluded,
        retired,
        foreign,
        other_scope,
    )
    registry = DatasetRegistry(
        datasets,
        query_defaults=replace(
            load_dataset_registry().query_defaults,
            max_page_size=20,
            max_catalog_search_chars=32,
            cursor_ttl_seconds=60,
        ),
    )
    db_path = (tmp_path / "catalog-receipts.sqlite").absolute()
    (tmp_path / f".{db_path.name}.tradingdatas.lock").touch(mode=0o600)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    monkeypatch.setattr(
        catalog_module,
        "inspect_dataset_queryability",
        lambda _conn, dataset: DatasetQueryability(
            queryable=dataset is not stale,
            reasons=() if dataset is not stale else ("primary_table_unavailable",),
        ),
    )
    boundary = (NOW - timedelta(seconds=3_600)).isoformat()
    stale_through = (NOW - timedelta(seconds=3_601)).isoformat()
    _insert_runtime_receipt(
        monkeypatch,
        conn,
        success,
        status="success",
        suffix="success",
        started_at="2026-07-16T03:49:00+00:00",
        finished_at="2026-07-16T03:50:00+00:00",
        data_through=boundary,
    )
    _insert_runtime_receipt(
        monkeypatch,
        conn,
        empty,
        status="empty",
        suffix="empty",
        started_at="2026-07-16T03:49:00+00:00",
        finished_at="2026-07-16T03:50:00+00:00",
        data_through=None,
    )
    _insert_runtime_receipt(
        monkeypatch,
        conn,
        failed,
        status="failed",
        suffix="failed",
        started_at="2026-07-16T03:49:00+00:00",
        finished_at="2026-07-16T03:50:00+00:00",
        data_through=None,
    )
    _insert_runtime_receipt(
        monkeypatch,
        conn,
        stale,
        status="success",
        suffix="stale",
        started_at="2026-07-16T03:49:00+00:00",
        finished_at="2026-07-16T03:50:00+00:00",
        data_through=stale_through,
    )
    conn.close()
    return {
        "registry": registry,
        "db_path": db_path,
        "codec": SignedCursorCodec(SIGNING_KEY),
        "now": NOW,
        "access": QueryAccessContext.from_grants(
            tenant_id="tenant-real",
            scopes=("market_data",),
            allowed_dataset_ids=(other_scope.dataset_id,),
        ),
    }


def test_catalog_filters_freeze_only_the_five_public_filters() -> None:
    filters = CatalogFilters(
        market="CN",
        domain="equity",
        cadence="daily",
        state="success",
        q="daily",
    )

    assert tuple(field.name for field in fields(CatalogFilters)) == (
        "market",
        "domain",
        "cadence",
        "state",
        "q",
    )
    assert filters.q == "daily"
    with pytest.raises(FrozenInstanceError):
        filters.q = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"market": " CN"}, "market"),
        ({"domain": ""}, "domain"),
        ({"cadence": "daily "}, "cadence"),
        ({"state": "healthy"}, "state"),
        ({"q": ""}, "q"),
    ],
)
def test_catalog_filters_reject_noncanonical_values(
    changes: dict[str, str],
    message: str,
) -> None:
    values: dict[str, str | None] = {
        "market": None,
        "domain": None,
        "cadence": None,
        "state": None,
        "q": None,
    }
    values.update(changes)

    with pytest.raises(QueryValidationError, match=message):
        CatalogFilters(**values)


@pytest.mark.parametrize("field_name", ["market", "domain", "cadence", "state", "q"])
@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_catalog_filters_reject_lone_utf16_surrogates(
    field_name: str,
    surrogate: str,
) -> None:
    values: dict[str, str | None] = {
        "market": None,
        "domain": None,
        "cadence": None,
        "state": None,
        "q": None,
    }
    values[field_name] = surrogate

    with pytest.raises(QueryValidationError, match=field_name):
        CatalogFilters(**values)


def test_catalog_filters_accept_valid_unicode_without_normalizing() -> None:
    filters = CatalogFilters(
        market="中国",
        domain="Straße",
        cadence="每😀日",
        q="Straße😀",
    )

    assert filters.market == "中国"
    assert filters.domain == "Straße"
    assert filters.cadence == "每😀日"
    assert filters.q == "Straße😀"


def test_catalog_discoverability_is_separate_from_query_runtime_eligibility() -> None:
    base = _dataset()
    active = base.provider_bindings[0]
    locked_paused = replace(
        active,
        entitlement_state="locked",
        activation_state="paused",
    )
    active_paused = replace(
        active,
        entitlement_state="active",
        activation_state="paused",
    )
    locked_active = replace(
        active,
        entitlement_state="locked",
        activation_state="active",
    )
    cross_match_active = replace(
        locked_active,
        provider="cross_match_provider",
        api_name="cross_match_api",
        read_discriminator_value="cross_match_lane",
    )

    active_dataset = replace(base, provider_bindings=(active,))
    locked_paused_dataset = replace(base, provider_bindings=(locked_paused,))
    active_paused_dataset = replace(base, provider_bindings=(active_paused,))
    locked_active_dataset = replace(base, provider_bindings=(locked_active,))
    cross_match_dataset = replace(
        base,
        provider_bindings=(active_paused, cross_match_active),
    )
    foreign_dataset = replace(base, market="US", provider_bindings=(active,))

    for dataset in (
        active_dataset,
        locked_paused_dataset,
        active_paused_dataset,
        locked_active_dataset,
        cross_match_dataset,
    ):
        assert is_catalog_discoverable(dataset)
    assert not is_catalog_discoverable(foreign_dataset)

    assert is_initial_release_eligible(active_dataset)
    for dataset in (
        locked_paused_dataset,
        active_paused_dataset,
        locked_active_dataset,
        cross_match_dataset,
        foreign_dataset,
    ):
        assert not is_initial_release_eligible(dataset)


def test_target_registry_catalog_cursor_discovers_all_190_with_honest_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_dataset_registry()
    assert len(registry.datasets) == 190
    excluded_ids = {
        dataset.dataset_id
        for dataset in registry.datasets
        if {binding.entitlement_state for binding in dataset.provider_bindings}
        == {"excluded"}
    }
    assert excluded_ids == {
        "cn.dataset.etf_sh_cons",
        "cn.dataset.fut_trade_cal",
        "cn.dataset.monetary_policy",
        "cn.dataset.rt_etf_min",
        "cn.dataset.rt_etf_min_daily",
    }

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    db_path = (tmp_path / "target-registry-catalog.sqlite").absolute()
    runtime = {
        dataset.dataset_id: _runtime(
            dataset.dataset_id,
            (
                "paused"
                if all(
                    binding.activation_state == "paused"
                    for binding in dataset.provider_bindings
                )
                else "unobserved"
            ),
        )
        for dataset in registry.datasets
    }

    @contextmanager
    def snapshot(path: Path):
        assert path == db_path
        yield conn

    def project(
        snapshot_conn: sqlite3.Connection,
        projected_registry: DatasetRegistry,
        *,
        now: datetime,
    ) -> dict[str, object]:
        assert snapshot_conn is conn
        assert projected_registry is registry
        assert now == NOW
        return {"datasets": runtime}

    monkeypatch.setattr(catalog_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(catalog_module, "project_catalog_runtime", project)
    service = CatalogService(
        registry=registry,
        db_path=db_path,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    access = QueryAccessContext.from_grants(
        tenant_id="target-registry-audit",
        scopes=("*",),
        allowed_dataset_ids=(),
    )

    rows: list[dict[str, object]] = []
    cursor: str | None = None
    for page_number in range(1, 20):
        response = service.list_datasets(
            access=access,
            filters=CatalogFilters(),
            limit=37,
            cursor=cursor,
            now=NOW,
            request_id=f"target-registry-page-{page_number}",
        )
        rows.extend(response["data"])
        cursor = response["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("catalog pagination did not terminate")
    conn.close()

    ids = [row["dataset_id"] for row in rows]
    assert len(ids) == 190
    assert len(set(ids)) == 190
    assert ids == sorted(ids)
    excluded_rows = {
        row["dataset_id"]: row for row in rows if row["dataset_id"] in excluded_ids
    }
    assert set(excluded_rows) == excluded_ids
    for row in excluded_rows.values():
        assert row["availability"] == {
            "entitlement_states": ["excluded"],
            "activation_states": ["paused"],
        }
        assert row["runtime"]["state"] == "paused"


def test_queryability_rejects_arbitrary_table_without_inspecting_it() -> None:
    dataset = _catalog_dataset("cn.queryability.arbitrary")
    dataset = replace(
        dataset,
        provider_bindings=(
            replace(dataset.provider_bindings[0], target_tables=("facts_quotes",)),
        ),
        read_model_adapter=replace(
            dataset.read_model_adapter,
            primary_table="facts_quotes",
        ),
    )
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "facts_quotes" ("payload_json" TEXT)')
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    result = inspect_dataset_queryability(conn, dataset)

    assert result == DatasetQueryability(
        queryable=False,
        reasons=("primary_table_unavailable",),
    )
    assert statements == []
    assert conn.total_changes == 0


def test_queryability_keeps_missing_table_as_nonleaking_row_reason() -> None:
    result = inspect_dataset_queryability(sqlite3.connect(":memory:"), _dataset())

    assert result == DatasetQueryability(
        queryable=False,
        reasons=("primary_table_unavailable",),
    )


def test_catalog_service_uses_one_snapshot_projection_and_same_connection(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    original_inspect = catalog_module.inspect_dataset_queryability
    inspected_connections: list[sqlite3.Connection] = []

    def inspect(conn: sqlite3.Connection, dataset: DatasetDefinition):
        inspected_connections.append(conn)
        return original_inspect(conn, dataset)

    monkeypatch.setattr(catalog_module, "inspect_dataset_queryability", inspect)

    response = _list(_service(catalog_harness), catalog_harness)

    assert calls == {"snapshot": 1, "projection": 1, "now": NOW}
    assert len(inspected_connections) == len(response["data"])
    assert all(conn is catalog_harness["conn"] for conn in inspected_connections)


def test_catalog_rows_are_exact_provider_neutral_whitelists(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)

    response = _list(_service(catalog_harness), catalog_harness, limit=1)
    row = response["data"][0]

    assert set(response) == {
        "api_version",
        "catalog_version",
        "request_id",
        "data",
        "next_cursor",
    }
    assert response["api_version"] == "v1"
    assert response["catalog_version"] == public_catalog_version(
        catalog_harness["registry"]
    )
    assert response["request_id"] == "request-1"
    assert set(row) == ROW_KEYS
    assert row["aliases"] == ["tushare.daily", "StraßeAlpha"]
    assert row["schema_major"] == 1
    assert row["default_fields"] == ["symbol", "value"]
    assert row["identity_fields"] == ["symbol"]
    assert row["sortable_fields"] == ["symbol", "revision"]
    assert row["default_order"] == ["symbol:asc"]
    assert set(row["fields"][0]) == {
        "name",
        "logical_type",
        "nullable",
        "selectable",
        "filterable",
        "sortable",
        "operators",
    }
    assert set(row["limits"]) == {"max_page_size", "max_lookback_days"}
    assert set(row["availability"]) == {
        "entitlement_states",
        "activation_states",
    }
    assert row["availability"] == {
        "entitlement_states": ["locked", "unknown"],
        "activation_states": ["active", "paused"],
    }
    assert set(row["queryability"]) == {"queryable", "reasons"}
    assert set(row["runtime"]) == {
        "state",
        "degraded",
        "data_through",
        "observed_at",
        "receipt_id",
        "reasons",
    }

    wire = json.dumps(response, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        '"provider":',
        "api_cn_catalog_alpha",
        "facts_cn_catalog_alpha",
        "adapter_version",
        "primary_table",
        "target_tables",
        "fixed_field_filters",
        "must_not_leak",
        "secret-source",
        str(catalog_harness["db_path"]),
        "SELECT ",
        "token",
        "raw receipt",
    ):
        assert forbidden not in wire


def test_catalog_contract_fingerprint_golden_vector_is_cross_repository_stable() -> (
    None
):
    """Keep the public contract material aligned with TradingAgent's reader."""

    row = {
        "dataset_id": "cn.equity.daily",
        "schema_major": 2,
        "default_fields": ["ts_code", "trade_date", "close"],
        "filter_operators": {
            "trade_date": ["between", "eq"],
            "ts_code": ["in", "eq"],
        },
        "default_order": ["ts_code:asc", "trade_date:asc"],
        "limits": {"max_page_size": 500, "max_lookback_days": 36500},
        "identity_fields": ["ts_code", "trade_date"],
    }
    material = {
        **row,
        "filter_operators": {
            field: sorted(operators)
            for field, operators in sorted(row["filter_operators"].items())
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    assert fingerprint == (
        "2a64eade6402119d492ae339213af96865ad5125358ac45de576b5a71f1d9e07"
    )


def test_visibility_requires_scope_but_ignores_allowed_dataset_grants(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)

    first = _list(service, catalog_harness)
    second = _list(
        service,
        catalog_harness,
        cursor=first["next_cursor"],
        request_id="request-2",
    )
    ids = [row["dataset_id"] for row in first["data"] + second["data"]]

    assert ids == [
        "cn.catalog.alpha",
        "cn.catalog.beta",
        "cn.catalog.excluded",
        "cn.catalog.gamma",
    ]
    assert first["data"][1]["runtime"]["state"] == "paused"
    assert first["data"][1]["availability"] == {
        "entitlement_states": ["unknown"],
        "activation_states": ["paused"],
    }
    assert first["data"][1]["queryability"] == {
        "queryable": True,
        "reasons": [],
    }
    excluded_row = next(
        row
        for row in first["data"] + second["data"]
        if row["dataset_id"] == "cn.catalog.excluded"
    )
    assert excluded_row["availability"] == {
        "entitlement_states": ["excluded"],
        "activation_states": ["active"],
    }
    assert excluded_row["runtime"]["state"] == "stale"

    allowed_only = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=(),
        allowed_dataset_ids=("cn.catalog.hidden_scope",),
    )
    assert _list(service, catalog_harness, access=allowed_only)["data"] == []

    aggregate = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("external_read",),
        allowed_dataset_ids=(),
    )
    aggregate_first = _list(service, catalog_harness, access=aggregate)
    aggregate_second = _list(
        service,
        catalog_harness,
        access=aggregate,
        cursor=aggregate_first["next_cursor"],
    )
    aggregate_third = _list(
        service,
        catalog_harness,
        access=aggregate,
        cursor=aggregate_second["next_cursor"],
    )
    aggregate_ids = [
        row["dataset_id"]
        for row in (
            aggregate_first["data"] + aggregate_second["data"] + aggregate_third["data"]
        )
    ]
    assert aggregate_ids == [
        "cn.catalog.alpha",
        "cn.catalog.beta",
        "cn.catalog.excluded",
        "cn.catalog.gamma",
        "cn.catalog.hidden_scope",
    ]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_pagination_has_no_gaps_and_binds_exact_query_policy_and_watermark(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(service, catalog_harness, limit=2)
    assert first["next_cursor"] is not None

    visible_ids = [
        "cn.catalog.alpha",
        "cn.catalog.beta",
        "cn.catalog.excluded",
        "cn.catalog.gamma",
    ]
    watermark_rows = [
        [
            dataset_id,
            catalog_harness["runtime"][dataset_id]["state"],
            catalog_harness["runtime"][dataset_id]["receipt_id"],
            catalog_harness["runtime"][dataset_id]["data_through"],
            catalog_harness["runtime"][dataset_id]["observed_at"],
        ]
        for dataset_id in visible_ids
    ]
    watermark = hashlib.sha256(_canonical_json(watermark_rows)).hexdigest()
    query_hash = hashlib.sha256(
        _canonical_json(
            {
                "market": None,
                "domain": None,
                "cadence": None,
                "state": None,
                "q": None,
                "limit": 2,
            }
        )
    ).hexdigest()
    expectation = CursorExpectation(
        kind="catalog",
        catalog_version=public_catalog_version(catalog_harness["registry"]),
        dataset_id=None,
        schema_major=None,
        query_hash=query_hash,
        policy_id=catalog_harness["access"].policy_id,
        receipt_watermark=watermark,
    )
    claims = catalog_harness["codec"].decode(
        first["next_cursor"],
        expected=expectation,
        now=NOW,
    )
    assert claims.sort_key == ("cn.catalog.beta",)
    assert claims.expires_at == int(NOW.timestamp()) + 60

    second = _list(
        service,
        catalog_harness,
        limit=2,
        cursor=first["next_cursor"],
        request_id="request-2",
    )
    ids = [row["dataset_id"] for row in first["data"] + second["data"]]
    assert ids == visible_ids
    assert len(ids) == len(set(ids))
    assert second["next_cursor"] is None


def test_catalog_filters_are_exact_and_q_casefolds_only_id_and_aliases(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)

    first = _list(
        service,
        catalog_harness,
        filters=CatalogFilters(q="straße"),
        limit=1,
    )
    assert [row["dataset_id"] for row in first["data"]] == ["cn.catalog.alpha"]
    second = _list(
        service,
        catalog_harness,
        filters=CatalogFilters(q="STRASSE"),
        limit=1,
        cursor=first["next_cursor"],
    )
    assert [row["dataset_id"] for row in second["data"]] == ["cn.catalog.beta"]

    assert (
        _list(
            service,
            catalog_harness,
            filters=CatalogFilters(q="quote"),
        )["data"]
        == []
    )
    assert (
        _list(
            service,
            catalog_harness,
            filters=CatalogFilters(state="empty"),
        )["data"][0]["dataset_id"]
        == "cn.catalog.gamma"
    )
    assert (
        _list(
            service,
            catalog_harness,
            filters=CatalogFilters(market="cn"),
        )["data"]
        == []
    )
    assert _list(
        service,
        catalog_harness,
        filters=CatalogFilters(domain="market_data", cadence="postclose_daily"),
    )["data"]


@pytest.mark.parametrize("limit", [True, 1.0, "1", 0, -1])
def test_catalog_rejects_invalid_limit_shapes(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    limit: object,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    with pytest.raises(QueryValidationError, match="limit"):
        _list(_service(catalog_harness), catalog_harness, limit=limit)  # type: ignore[arg-type]
    assert calls["snapshot"] == 0


def test_catalog_rejects_filter_and_limit_budget_overflow_before_snapshot(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)

    with pytest.raises(QueryBudgetError, match="q"):
        _list(service, catalog_harness, filters=CatalogFilters(q="x" * 13))
    with pytest.raises(QueryBudgetError, match="limit"):
        _list(service, catalog_harness, limit=3)
    assert calls["snapshot"] == 0


def test_catalog_q_budget_counts_unicode_code_points(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)

    response = _list(
        service,
        catalog_harness,
        filters=CatalogFilters(q="😀" * 12),
        request_id="请求-Straße-😀",
    )
    assert response["request_id"] == "请求-Straße-😀"
    assert calls["snapshot"] == 1

    with pytest.raises(QueryBudgetError, match="q"):
        _list(service, catalog_harness, filters=CatalogFilters(q="😀" * 13))
    assert calls["snapshot"] == 1


@pytest.mark.parametrize("request_id", ["", " request", "request ", 1])
def test_catalog_rejects_noncanonical_request_id(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    request_id: object,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    with pytest.raises(QueryValidationError, match="request_id"):
        _list(
            _service(catalog_harness),
            catalog_harness,
            request_id=request_id,  # type: ignore[arg-type]
        )
    assert calls["snapshot"] == 0


@pytest.mark.parametrize("request_id", ["\ud800", "\udfff"])
def test_catalog_rejects_lone_utf16_surrogate_request_id_before_snapshot(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    request_id: str,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)

    with pytest.raises(QueryValidationError, match="request_id"):
        _list(
            _service(catalog_harness),
            catalog_harness,
            request_id=request_id,
        )
    assert calls["snapshot"] == 0


def test_catalog_fails_closed_for_missing_or_invalid_visible_runtime(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    runtime = catalog_harness["runtime"]

    saved = runtime.pop("cn.catalog.alpha")
    with pytest.raises(RuntimeProjectionError):
        _list(service, catalog_harness)
    runtime["cn.catalog.alpha"] = {**saved, "state": "healthy"}
    with pytest.raises(RuntimeProjectionError):
        _list(service, catalog_harness)


def test_pre_filter_visible_runtime_change_invalidates_cursor(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(
        service,
        catalog_harness,
        filters=CatalogFilters(q="strasse"),
        limit=1,
    )
    gamma = catalog_harness["runtime"]["cn.catalog.gamma"]
    gamma["receipt_id"] = "receipt:gamma-new"
    gamma["observed_at"] = "2026-07-16T03:30:00+00:00"

    with pytest.raises(CursorMismatch, match="watermark"):
        _list(
            service,
            catalog_harness,
            filters=CatalogFilters(q="STRASSE"),
            limit=1,
            cursor=first["next_cursor"],
        )


def test_hidden_runtime_change_does_not_enter_visible_watermark(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(service, catalog_harness, limit=1)
    hidden = catalog_harness["runtime"]["cn.catalog.hidden_scope"]
    hidden["state"] = "failed"
    hidden["degraded"] = True
    hidden["receipt_id"] = "receipt:hidden-new"
    hidden["observed_at"] = "2026-07-16T03:30:00+00:00"
    hidden["reasons"] = ["provider_error"]

    second = _list(
        service,
        catalog_harness,
        limit=1,
        cursor=first["next_cursor"],
    )
    assert second["data"][0]["dataset_id"] == "cn.catalog.beta"


def test_cursor_filter_limit_and_policy_drift_are_mismatches(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(service, catalog_harness, limit=1)
    cursor = first["next_cursor"]

    with pytest.raises(CursorMismatch, match="query"):
        _list(
            service,
            catalog_harness,
            filters=CatalogFilters(market="CN"),
            limit=1,
            cursor=cursor,
        )
    with pytest.raises(CursorMismatch, match="query"):
        _list(service, catalog_harness, limit=2, cursor=cursor)
    changed_policy = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("market_data",),
        allowed_dataset_ids=("some.other.dataset",),
    )
    with pytest.raises(CursorMismatch, match="policy"):
        _list(
            service,
            catalog_harness,
            access=changed_policy,
            limit=1,
            cursor=cursor,
        )


def test_malformed_tampered_expired_and_bad_shape_cursors_are_invalid(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(service, catalog_harness, limit=1)
    cursor = first["next_cursor"]

    with pytest.raises(InvalidCursor):
        _list(service, catalog_harness, limit=1, cursor="not-a-token")
    with pytest.raises(InvalidCursor):
        _list(service, catalog_harness, limit=1, cursor=f"{cursor[:-1]}A")
    with pytest.raises(InvalidCursor, match="expired"):
        _list(
            service,
            catalog_harness,
            limit=1,
            cursor=cursor,
            now=NOW + timedelta(seconds=61),
        )

    filters = CatalogFilters()
    visible = [
        "cn.catalog.alpha",
        "cn.catalog.beta",
        "cn.catalog.excluded",
        "cn.catalog.gamma",
    ]
    watermark = hashlib.sha256(
        _canonical_json(
            [
                [
                    dataset_id,
                    catalog_harness["runtime"][dataset_id]["state"],
                    catalog_harness["runtime"][dataset_id]["receipt_id"],
                    catalog_harness["runtime"][dataset_id]["data_through"],
                    catalog_harness["runtime"][dataset_id]["observed_at"],
                ]
                for dataset_id in visible
            ]
        )
    ).hexdigest()
    query_hash = hashlib.sha256(
        _canonical_json(
            {
                "market": filters.market,
                "domain": filters.domain,
                "cadence": filters.cadence,
                "state": filters.state,
                "q": filters.q,
                "limit": 1,
            }
        )
    ).hexdigest()
    expectation = CursorExpectation(
        kind="catalog",
        catalog_version=public_catalog_version(catalog_harness["registry"]),
        dataset_id=None,
        schema_major=None,
        query_hash=query_hash,
        policy_id=catalog_harness["access"].policy_id,
        receipt_watermark=watermark,
    )
    claims = catalog_harness["codec"].decode(
        cursor,
        expected=expectation,
        now=NOW,
    )
    bad_shape = catalog_harness["codec"].encode(
        replace(claims, sort_key=("cn.catalog.alpha", "extra"))
    )
    with pytest.raises(InvalidCursor, match="sort"):
        _list(service, catalog_harness, limit=1, cursor=bad_shape)


def test_naive_cursor_clock_is_a_configuration_error_before_snapshot(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fake_snapshot(monkeypatch, catalog_harness)
    with pytest.raises(CursorConfigurationError, match="clock"):
        _list(
            _service(catalog_harness),
            catalog_harness,
            now=datetime(2026, 7, 16, 4, 0),
        )
    assert calls["snapshot"] == 0


def test_real_receipt_snapshot_preserves_all_six_projected_states(
    real_catalog_harness: dict[str, object],
) -> None:
    response = _list(
        _service(real_catalog_harness),
        real_catalog_harness,
        limit=20,
        request_id="real-snapshot",
    )
    rows = {row["dataset_id"]: row for row in response["data"]}

    assert set(rows) == {
        "cn.runtime.a_success",
        "cn.runtime.b_empty",
        "cn.runtime.c_unobserved",
        "cn.runtime.d_paused",
        "cn.runtime.e_failed",
        "cn.runtime.f_stale",
        "cn.runtime.g_excluded",
        "cn.runtime.h_retired",
    }
    assert {
        dataset_id: row["runtime"]["state"] for dataset_id, row in rows.items()
    } == {
        "cn.runtime.a_success": "success",
        "cn.runtime.b_empty": "empty",
        "cn.runtime.c_unobserved": "unobserved",
        "cn.runtime.d_paused": "paused",
        "cn.runtime.e_failed": "failed",
        "cn.runtime.f_stale": "stale",
        "cn.runtime.g_excluded": "paused",
        "cn.runtime.h_retired": "paused",
    }
    assert rows["cn.runtime.a_success"]["availability"] == {
        "entitlement_states": ["locked"],
        "activation_states": ["active"],
    }
    assert rows["cn.runtime.c_unobserved"]["availability"] == {
        "entitlement_states": ["unknown"],
        "activation_states": ["active"],
    }
    assert rows["cn.runtime.g_excluded"]["availability"] == {
        "entitlement_states": ["excluded"],
        "activation_states": ["paused"],
    }
    assert rows["cn.runtime.h_retired"]["availability"] == {
        "entitlement_states": ["retired"],
        "activation_states": ["paused"],
    }
    assert rows["cn.runtime.f_stale"]["queryability"] == {
        "queryable": False,
        "reasons": ["primary_table_unavailable"],
    }
    assert response["next_cursor"] is None


def test_queryability_reports_only_frozen_physical_reason_enums() -> None:
    dataset = _catalog_dataset("cn.physical.contract")
    table = "provider_dataset_rows"

    canonical = sqlite3.connect(":memory:")
    canonical.executescript(SCHEMA_SQL)
    assert inspect_dataset_queryability(canonical, dataset) == DatasetQueryability(
        True,
        (),
    )

    missing = sqlite3.connect(":memory:")
    missing.execute(f'CREATE TABLE "{table}" ("dataset_id" TEXT)')
    assert inspect_dataset_queryability(missing, dataset) == DatasetQueryability(
        False,
        ("query_columns_unavailable",),
    )

    incompatible = sqlite3.connect(":memory:")
    incompatible.execute(
        f'CREATE TABLE "{table}" ('
        '"dataset_id" INTEGER, "provider" TEXT, "schema_major" INTEGER, '
        '"ingested_schema_version" TEXT, "row_key" TEXT, "observed_at" TEXT, '
        '"partition_value" TEXT, "payload_json" TEXT, "payload_hash" TEXT, '
        '"quality_state" TEXT, "quality_issues_json" TEXT, "collected_at" TEXT, '
        '"receipt_id" TEXT, "revision" INTEGER)'
    )
    assert inspect_dataset_queryability(incompatible, dataset) == DatasetQueryability(
        False,
        ("query_column_types_incompatible",),
    )

    view = sqlite3.connect(":memory:")
    view.execute(f'CREATE VIEW "{table}" AS SELECT 1 AS symbol')
    assert inspect_dataset_queryability(view, dataset) == DatasetQueryability(
        False,
        ("primary_table_unavailable",),
    )


def test_queryability_sqlite_failure_is_not_downgraded_to_a_row_reason() -> None:
    conn = sqlite3.connect(":memory:")
    conn.close()

    with pytest.raises(RuntimeProjectionError, match="failed closed"):
        inspect_dataset_queryability(conn, _catalog_dataset("cn.physical.closed"))


def test_missing_database_is_a_whole_request_projection_failure(
    tmp_path: Path,
) -> None:
    dataset = _catalog_dataset("cn.missing.database")
    registry = DatasetRegistry((dataset,))
    service = CatalogService(
        registry=registry,
        db_path=(tmp_path / "missing.sqlite").absolute(),
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    access = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("market_data",),
        allowed_dataset_ids=(),
    )

    with pytest.raises(RuntimeProjectionError):
        service.list_datasets(
            access=access,
            filters=CatalogFilters(),
            limit=1,
            cursor=None,
            now=NOW,
            request_id="missing-db",
        )


def test_public_catalog_version_drift_invalidates_existing_cursor(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    first = _list(_service(catalog_harness), catalog_harness, limit=1)
    changed = tuple(
        replace(dataset, aliases=(*dataset.aliases, "new-public-alias"))
        if dataset.dataset_id == "cn.catalog.alpha"
        else dataset
        for dataset in catalog_harness["registry"].datasets
    )
    catalog_harness["registry"] = DatasetRegistry(
        changed,
        query_defaults=catalog_harness["registry"].query_defaults,
    )

    with pytest.raises(CursorMismatch, match="catalog version"):
        _list(
            _service(catalog_harness),
            catalog_harness,
            limit=1,
            cursor=first["next_cursor"],
        )


def test_out_of_product_scope_runtime_rows_are_not_required_or_watermarked(
    catalog_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_snapshot(monkeypatch, catalog_harness)
    service = _service(catalog_harness)
    first = _list(service, catalog_harness, limit=1)
    catalog_harness["runtime"].pop("us.catalog.hidden_market")

    second = _list(
        service,
        catalog_harness,
        limit=1,
        cursor=first["next_cursor"],
    )
    assert second["data"][0]["dataset_id"] == "cn.catalog.beta"
