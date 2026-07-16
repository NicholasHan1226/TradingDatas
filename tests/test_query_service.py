from __future__ import annotations

import base64
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

import storage.ingest_receipts as receipt_module
import storage.receipt_projection as projection_module
import query_contract as query_contract_module
from dataset_registry import (
    DatasetField,
    DatasetRegistry,
    FixedFieldFilter,
    ProviderBinding,
    ReadModelAdapter,
    load_dataset_registry,
)
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryExecutionOptions,
    QueryRequest,
    QueryValidationError,
)
from query_cursor import CursorClaims, CursorMismatch, InvalidCursor, SignedCursorCodec
import query_service as query_module
from query_service import (
    QueryAccessDenied,
    QueryDatasetNotFound,
    QueryService,
    QueryServiceUnavailable,
)
from storage.receipt_projection import (
    DatasetRuntimeEvidence,
    DatasetRuntimeProjection,
    RuntimeProjectionError,
)
from storage.ingest_receipts import IngestContext, IngestCounts, insert_ingest_receipt
from storage.schema import SCHEMA_SQL


SIGNING_KEY = b"query-service-test-signing-key-32-bytes"
NOW = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)


class _TrackingCursor(sqlite3.Cursor):
    def fetchmany(self, size: int | None = None, /):
        connection = self.connection
        assert isinstance(connection, _TrackingConnection)
        connection.fetchmany_sizes.append(size)
        return super().fetchmany(size)


class _TrackingConnection(sqlite3.Connection):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.progress_events: list[tuple[object, int]] = []
        self.fetchmany_sizes: list[int | None] = []
        self.sql_progress_states: list[bool] = []
        self.progress_active = False
        self.progress_callback_calls = 0

    def cursor(self, factory: type[sqlite3.Cursor] = _TrackingCursor):
        return super().cursor(factory)

    def execute(self, sql: str, parameters: object = (), /):
        self.sql_progress_states.append(self.progress_active)
        return self.cursor().execute(sql, parameters)

    def set_progress_handler(self, progress_handler: object, n: int) -> None:
        self.progress_events.append((progress_handler, n))
        self.progress_active = progress_handler is not None
        installed_handler = progress_handler
        if callable(progress_handler):

            def counted_handler() -> int:
                self.progress_callback_calls += 1
                return progress_handler()

            installed_handler = counted_handler
        super().set_progress_handler(installed_handler, n)


def _registry(*, eligible: bool = True, max_selected_fields: int = 100):
    source = load_dataset_registry()
    dataset = source.resolve("tushare.daily")
    if not eligible:
        dataset = replace(
            dataset,
            market="US",
            provider_bindings=(
                replace(dataset.provider_bindings[0], entitlement_state="excluded"),
            ),
        )
    defaults = replace(
        source.query_defaults,
        max_selected_fields=max_selected_fields,
    )
    return DatasetRegistry((dataset,), query_defaults=defaults)


def _request(
    *,
    dataset_id: str = "cn.equity.daily",
    schema_major: int = 1,
    fields: tuple[str, ...] = ("symbol",),
    filters: dict[str, object] | None = None,
    as_of: str | None = None,
    order: tuple[str, ...] | None = None,
    limit: int = 10,
) -> QueryRequest:
    return QueryRequest(
        dataset_id=dataset_id,
        schema_major=schema_major,
        fields=fields,
        filters={} if filters is None else filters,
        as_of=as_of,
        order=order,
        limit=limit,
        cursor=None,
    )


def _access(*, scopes: tuple[str, ...] = ("market_data",)) -> QueryAccessContext:
    return QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=scopes,
        allowed_dataset_ids=(),
    )


def _service(tmp_path: Path, registry: DatasetRegistry) -> QueryService:
    return QueryService(
        db_path=(tmp_path / "read-model.sqlite").absolute(),
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )


@pytest.fixture
def query_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = load_dataset_registry()
    base = source.resolve("tushare.daily")
    dataset = replace(
        base,
        dataset_id="cn.test.quotes",
        aliases=("tushare.test_quotes",),
        fields=(
            DatasetField("symbol", "text", False, True, True, True),
            DatasetField("trade_date", "text", False, True, True, True),
            DatasetField("score", "float", True, True, True, True),
            DatasetField("revision", "integer", False, True, True, True),
            DatasetField("note", "text", True, True, True, True),
        ),
        primary_key=("symbol", "trade_date", "revision"),
        default_projection=("symbol", "trade_date", "score", "revision", "note"),
        as_of_field="trade_date",
        as_of_format="yyyymmdd",
        range_field="trade_date",
        partition_field="trade_date",
        timezone="Asia/Shanghai",
        freshness_sla_seconds=86_400,
        max_page_size=3,
        max_lookback_days=10,
        provider_bindings=(
            ProviderBinding(
                provider="provider-a",
                api_name="quotes",
                adapter_version="writer.v1",
                read_discriminator_value="lane-a",
                entitlement_state="active",
                activation_state="active",
                target_tables=("facts_quotes",),
            ),
        ),
        read_model_adapter=ReadModelAdapter(
            adapter_version="reader.v1",
            primary_table="facts_quotes",
            fixed_field_filters=(FixedFieldFilter("lane_key", ("lane-a",)),),
        ),
    )
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(
            source.query_defaults,
            max_page_size=3,
            max_lookback_days=10,
            cursor_ttl_seconds=60,
            sqlite_progress_steps=100_000,
        ),
    )
    conn = sqlite3.connect(":memory:", factory=_TrackingConnection)
    conn.execute(
        'CREATE TABLE "facts_quotes" ('
        '"symbol" TEXT NOT NULL, "trade_date" TEXT NOT NULL, '
        '"score" REAL, "revision" INTEGER NOT NULL, "note" TEXT, '
        '"lane_key" TEXT NOT NULL)'
    )
    conn.executemany(
        'INSERT INTO "facts_quotes" '
        "(rowid, symbol, trade_date, score, revision, note, lane_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (-2, "AAA", "20260715", None, 1, None, "lane-a"),
            (0, "AAA", "20260716", 1.5, 2, "alpha", "lane-a"),
            (1, "BBB", "20260716", 2.5, 1, "beta", "lane-a"),
            (2, "CCC", "20260717", 3.5, 1, "gamma", "lane-a"),
            (3, "LEAK", "20260718", 99.0, 1, "secret", "lane-b"),
        ],
    )
    conn.commit()
    conn.progress_events.clear()
    conn.fetchmany_sizes.clear()
    conn.sql_progress_states.clear()
    calls = {"snapshot": 0, "evidence": 0, "connection": None}

    @contextmanager
    def snapshot(_path: Path):
        calls["snapshot"] += 1
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
            observed_at="2026-07-16T03:00:00+00:00",
            receipt_id="receipt-current",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("provider-a",),
        last_success_receipt_id="receipt-current",
        last_success_providers=("provider-a",),
        last_success_data_through="20260716",
    )
    evidence_box = {"value": evidence}

    def project_evidence(
        connection: sqlite3.Connection,
        projected_dataset: object,
        *,
        now: datetime,
        registry: DatasetRegistry,
    ) -> DatasetRuntimeEvidence:
        calls["evidence"] += 1
        calls["connection"] = connection
        assert connection is conn
        assert projected_dataset is dataset
        assert now == NOW
        assert registry is query_harness_registry
        return evidence_box["value"]

    query_harness_registry = registry
    monkeypatch.setattr(query_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        project_evidence,
        raising=False,
    )
    harness = {
        "dataset": dataset,
        "registry": registry,
        "conn": conn,
        "calls": calls,
        "evidence": evidence,
        "evidence_box": evidence_box,
        "service": _service(tmp_path, registry),
        "access": QueryAccessContext.from_grants(
            tenant_id="tenant-query",
            scopes=("market_data",),
            allowed_dataset_ids=(),
        ),
    }
    yield harness
    conn.close()


def _harness_request(
    *,
    fields: tuple[str, ...] = ("symbol", "trade_date", "score", "revision"),
    filters: dict[str, object] | None = None,
    as_of: str | None = None,
    order: tuple[str, ...] | None = None,
    limit: int = 3,
    cursor: str | None = None,
    dataset_id: str = "cn.test.quotes",
) -> QueryRequest:
    return QueryRequest(
        dataset_id=dataset_id,
        schema_major=1,
        fields=fields,
        filters={} if filters is None else filters,
        as_of=as_of,
        order=order,
        limit=limit,
        cursor=cursor,
    )


def _execute_harness(
    harness: dict[str, object],
    request: QueryRequest,
    *,
    options: QueryExecutionOptions = QueryExecutionOptions(),
) -> dict[str, object]:
    return harness["service"].execute(
        request,
        access=harness["access"],
        now=NOW,
        request_id="request-query",
        options=options,
    )


def _resign_cursor_sort_key(cursor: str, sort_key: tuple[object, ...]) -> str:
    payload_segment = cursor.split(".", 1)[0]
    payload = json.loads(
        base64.urlsafe_b64decode(payload_segment + "=" * (-len(payload_segment) % 4))
    )
    return SignedCursorCodec(SIGNING_KEY).encode(
        CursorClaims(
            kind=payload["kind"],
            catalog_version=payload["catalog_version"],
            dataset_id=payload["dataset_id"],
            schema_major=payload["schema_major"],
            query_hash=payload["query_hash"],
            policy_id=payload["policy_id"],
            receipt_watermark=payload["receipt_watermark"],
            sort_key=sort_key,
            expires_at=payload["expires_at"],
        )
    )


def _state_evidence(
    state: str,
    *,
    trusted_current: bool = True,
    prior_success: bool = True,
) -> DatasetRuntimeEvidence:
    degraded = state not in {"success", "empty"}
    reasons = {
        "success": (),
        "empty": ("provider_returned_no_rows",),
        "unobserved": ("no_recognized_receipt",),
        "paused": ("registry_activation_paused",),
        "failed": ("provider_error",),
        "stale": ("freshness_sla_exceeded",),
    }[state]
    has_current = state not in {"unobserved", "paused"}
    current_status = {
        "success": "success",
        "empty": "empty",
        "failed": "failed",
        "stale": "success",
    }.get(state)
    data_through = "20260715" if state in {"success", "failed", "stale"} else None
    return DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id="cn.test.quotes",
            state=state,
            degraded=degraded,
            data_through=data_through,
            observed_at=("2026-07-16T03:00:00+00:00" if has_current else None),
            receipt_id="receipt-current" if has_current else None,
            reasons=reasons,
        ),
        current_receipt_status=(
            current_status if trusted_current and has_current else None
        ),
        current_providers=(
            ("provider-current",) if trusted_current and has_current else ()
        ),
        last_success_receipt_id=(
            "receipt-prior"
            if prior_success and state in {"success", "failed", "stale"}
            else None
        ),
        last_success_providers=(
            ("provider-prior",)
            if prior_success and state in {"success", "failed", "stale"}
            else ()
        ),
        last_success_data_through=(
            "20260715"
            if prior_success and state in {"success", "failed", "stale"}
            else None
        ),
    )


def _insert_query_success_receipt(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    started_at: str,
    finished_at: str,
    data_through: str,
    dataset_id: str = "cn.test.quotes",
    provider: str = "provider-a",
    provider_api: str = "quotes",
    adapter_version: str = "writer.v1",
    target_table: str = "facts_quotes",
) -> str:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: finished_at)
    return insert_ingest_receipt(
        conn,
        context=IngestContext(
            attempt_id=attempt_id,
            dataset_id=dataset_id,
            provider=provider,
            provider_api=provider_api,
            request_window={"trade_date": data_through},
            config_hash="a" * 64,
            adapter_version=adapter_version,
            started_at=started_at,
            data_through=data_through,
        ),
        target_table=target_table,
        transaction_index=0,
        status="success",
        counts=IngestCounts(
            returned=1,
            validated=1,
            inserted=1,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1,
            count_semantics="exact_row_outcomes",
        ),
        errors=(),
        payload_fingerprint="b" * 64,
    )


def test_query_service_constructor_requires_only_frozen_injected_dependencies(
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

    assert not hasattr(service, "__dict__")
    with pytest.raises(TypeError, match="db_path"):
        QueryService(db_path=str(db_path), registry=registry, cursor_codec=codec)
    with pytest.raises(ValueError, match="canonical"):
        QueryService(
            db_path=Path("read-model.sqlite"),
            registry=registry,
            cursor_codec=codec,
        )
    with pytest.raises(TypeError, match="registry"):
        QueryService(db_path=db_path, registry=object(), cursor_codec=codec)
    with pytest.raises(TypeError, match="cursor_codec"):
        QueryService(db_path=db_path, registry=registry, cursor_codec=object())

    assert isinstance(registry, DatasetRegistry)


@pytest.mark.parametrize(
    ("registry", "dataset_id"),
    [
        (_registry(), "cn.unknown.dataset"),
        (_registry(eligible=False), "cn.equity.daily"),
    ],
)
def test_unknown_or_ineligible_dataset_is_404_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry: DatasetRegistry,
    dataset_id: str,
) -> None:
    opened = False

    def forbidden_snapshot(_path: Path):
        nonlocal opened
        opened = True
        raise AssertionError("snapshot must remain unopened")

    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        forbidden_snapshot,
    )

    with pytest.raises(QueryDatasetNotFound, match="dataset is not available"):
        _service(tmp_path, registry).execute(
            _request(dataset_id=dataset_id),
            access=_access(),
            now=NOW,
            request_id="request-1",
        )

    assert opened is False


def test_service_rechecks_injected_registry_budgets_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(max_selected_fields=1)
    opened = False

    def forbidden_snapshot(_path: Path):
        nonlocal opened
        opened = True
        raise AssertionError("snapshot must remain unopened")

    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        forbidden_snapshot,
    )

    with pytest.raises(QueryBudgetError, match="max_selected_fields=1"):
        _service(tmp_path, registry).execute(
            _request(fields=("symbol", "trade_date")),
            access=_access(),
            now=NOW,
            request_id="request-1",
        )

    assert opened is False


def test_service_uses_injected_budget_when_module_default_is_stricter(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _harness_request(fields=("symbol", "trade_date"), limit=2)
    base_registry = query_harness["registry"]
    registry = DatasetRegistry(
        (query_harness["dataset"],),
        query_defaults=replace(
            base_registry.query_defaults,
            max_selected_fields=2,
        ),
    )
    monkeypatch.setattr(
        query_contract_module,
        "_QUERY_DEFAULTS",
        replace(
            query_contract_module._QUERY_DEFAULTS,
            max_selected_fields=1,
        ),
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: query_harness["evidence"],
    )
    before = query_harness["calls"]["snapshot"]

    response = _service(tmp_path, registry).execute(
        request,
        access=query_harness["access"],
        now=NOW,
        request_id="request-injected-budget",
    )

    assert response["data"]
    assert query_harness["calls"]["snapshot"] == before + 1


@pytest.mark.parametrize(
    ("field", "tampered_value", "message"),
    [
        ("dataset_id", " tushare.daily", "dataset_id"),
        ("schema_major", True, "schema_major"),
        ("fields", ["symbol"], "fields"),
        ("filters", {}, "filters"),
        ("as_of", "2026-07-16T00:00:00Z", "as_of"),
        ("order", ["symbol:asc"], "order"),
        ("limit", True, "limit"),
        ("cursor", " cursor ", "cursor"),
    ],
)
def test_service_revalidates_every_request_field_at_entry_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered_value: object,
    message: str,
) -> None:
    request = _request()
    object.__setattr__(request, field, tampered_value)
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )

    with pytest.raises(QueryValidationError, match=message):
        _service(tmp_path, _registry()).execute(
            request,
            access=_access(),
            now=NOW,
            request_id="request-1",
        )


def test_structurally_nonqueryable_dataset_is_404_before_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    calls = 0

    @contextmanager
    def snapshot(_path: Path):
        nonlocal calls
        calls += 1
        yield conn

    monkeypatch.setattr(query_module, "open_verified_read_model_snapshot", snapshot)
    try:
        with pytest.raises(QueryDatasetNotFound, match="dataset is not available"):
            _service(tmp_path, _registry()).execute(
                _request(),
                access=_access(scopes=()),
                now=NOW,
                request_id="request-1",
            )
    finally:
        conn.close()

    assert calls == 1


def test_queryable_dataset_without_scope_is_403_after_structural_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)

    @contextmanager
    def snapshot(_path: Path):
        yield conn

    monkeypatch.setattr(query_module, "open_verified_read_model_snapshot", snapshot)
    try:
        with pytest.raises(QueryAccessDenied, match="query access is denied"):
            _service(tmp_path, _registry()).execute(
                _request(),
                access=_access(scopes=()),
                now=NOW,
                request_id="request-1",
            )
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("query_request", "message"),
    [
        (_request(schema_major=2), "schema_major"),
        (_request(fields=("raw_json",)), "selectable"),
        (_request(filters={"open": 1.0}), "filterable"),
        (_request(filters={"symbol": True}), "text"),
        (
            _request(filters={"trade_date": {"between": ("20260716", "20260701")}}),
            "between",
        ),
        (_request(order=("close:asc",)), "sortable"),
    ],
)
def test_contract_failures_are_rejected_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    query_request: QueryRequest,
    message: str,
) -> None:
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )

    with pytest.raises(QueryValidationError, match=message):
        _service(tmp_path, _registry()).execute(
            query_request,
            access=_access(),
            now=NOW,
            request_id="request-1",
        )


def test_dataset_page_budget_is_rejected_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_registry = _registry()
    dataset = replace(base_registry.datasets[0], max_page_size=2)
    registry = DatasetRegistry((dataset,), query_defaults=base_registry.query_defaults)
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )

    with pytest.raises(QueryBudgetError, match="max_page_size=2"):
        _service(tmp_path, registry).execute(
            _request(limit=3),
            access=_access(),
            now=NOW,
            request_id="request-1",
        )


def test_service_reconstructs_exact_access_context_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = _access()
    object.__setattr__(access, "policy_id", "forged-policy")
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )

    with pytest.raises(QueryValidationError, match="access"):
        _service(tmp_path, _registry()).execute(
            _request(),
            access=access,
            now=NOW,
            request_id="request-1",
        )


def test_query_uses_main_qualified_quoted_registry_sql_and_bound_filters(
    query_harness: dict[str, object],
) -> None:
    statements: list[str] = []
    query_harness["conn"].set_trace_callback(statements.append)

    response = _execute_harness(
        query_harness,
        _harness_request(
            filters={"symbol": "AAA"},
            order=("score:desc",),
        ),
    )

    assert [row["symbol"] for row in response["data"]] == ["AAA", "AAA"]
    assert all(row["symbol"] != "LEAK" for row in response["data"])
    selects = [statement for statement in statements if "facts_quotes" in statement]
    assert selects
    row_selects = [
        statement for statement in selects if 'FROM main."facts_quotes"' in statement
    ]
    assert row_selects
    assert all('"lane_key"' in statement for statement in row_selects)
    assert "__ss_rowid" not in json.dumps(response, sort_keys=True)


@pytest.mark.parametrize(
    ("filters", "symbols"),
    [
        ({"score": {"eq": None}}, ["AAA"]),
        ({"score": {"in": [None, 2.5]}}, ["AAA", "BBB"]),
        ({"score": {"between": [1.5, 2.5]}}, ["AAA", "BBB"]),
        ({"revision": {"between": [1, 2]}}, ["AAA", "AAA", "BBB"]),
    ],
)
def test_null_and_native_type_filter_grammar(
    query_harness: dict[str, object],
    filters: dict[str, object],
    symbols: list[str],
) -> None:
    response = _execute_harness(
        query_harness,
        _harness_request(filters=filters, order=("symbol:asc",)),
    )

    assert [row["symbol"] for row in response["data"]] == symbols


@pytest.mark.parametrize(
    "filters",
    [
        {"symbol": {"eq": None}},
        {"trade_date": {"gte": None}},
        {"score": True},
        {"revision": True},
    ],
)
def test_null_and_bool_type_confusion_fails_before_snapshot(
    query_harness: dict[str, object],
    filters: dict[str, object],
) -> None:
    before = query_harness["calls"]["snapshot"]
    with pytest.raises(QueryValidationError):
        _execute_harness(query_harness, _harness_request(filters=filters))
    assert query_harness["calls"]["snapshot"] == before


def test_latest_partition_and_any_of_share_one_connection_and_fixed_predicates(
    query_harness: dict[str, object],
) -> None:
    response = _execute_harness(
        query_harness,
        _harness_request(order=("symbol:asc",)),
        options=QueryExecutionOptions(
            latest_partition=True,
            any_of_eq_filters=(("symbol", "AAA"), ("symbol", "BBB")),
        ),
    )

    assert [(row["symbol"], row["trade_date"]) for row in response["data"]] == [
        ("AAA", "20260716"),
        ("BBB", "20260716"),
    ]
    assert query_harness["calls"] == {
        "snapshot": 1,
        "evidence": 1,
        "connection": query_harness["conn"],
    }


@pytest.mark.parametrize(
    "options",
    [
        QueryExecutionOptions(any_of_eq_filters=(("missing", "AAA"),)),
        QueryExecutionOptions(any_of_eq_filters=(("revision", True),)),
    ],
)
def test_any_of_contract_and_four_term_budget_fail_before_snapshot(
    query_harness: dict[str, object],
    options: QueryExecutionOptions,
) -> None:
    before = query_harness["calls"]["snapshot"]

    with pytest.raises((QueryValidationError, QueryBudgetError)):
        _execute_harness(
            query_harness,
            _harness_request(),
            options=options,
        )

    assert query_harness["calls"]["snapshot"] == before


def test_forged_any_of_over_four_terms_fails_before_snapshot(
    query_harness: dict[str, object],
) -> None:
    options = QueryExecutionOptions(
        any_of_eq_filters=(
            ("symbol", "A"),
            ("symbol", "B"),
            ("symbol", "C"),
            ("symbol", "D"),
        )
    )
    object.__setattr__(
        options,
        "any_of_eq_filters",
        (*options.any_of_eq_filters, ("symbol", "E")),
    )
    before = query_harness["calls"]["snapshot"]

    with pytest.raises(QueryBudgetError, match="at most 4"):
        _execute_harness(
            query_harness,
            _harness_request(),
            options=options,
        )

    assert query_harness["calls"]["snapshot"] == before


def test_latest_partition_any_of_and_as_of_are_cursor_query_bound(
    query_harness: dict[str, object],
) -> None:
    options = QueryExecutionOptions(
        latest_partition=True,
        any_of_eq_filters=(("symbol", "AAA"), ("symbol", "BBB")),
    )
    request = _harness_request(
        as_of="2026-07-16T00:00:00+00:00",
        order=("symbol:asc",),
        limit=1,
    )
    first = _execute_harness(query_harness, request, options=options)
    cursor = first["next_cursor"]
    assert cursor is not None

    with pytest.raises(CursorMismatch, match="query"):
        _execute_harness(
            query_harness,
            replace(request, cursor=cursor),
            options=QueryExecutionOptions(
                latest_partition=True,
                any_of_eq_filters=(("symbol", "AAA"),),
            ),
        )
    with pytest.raises(CursorMismatch, match="query"):
        _execute_harness(
            query_harness,
            replace(
                request,
                as_of="2026-07-15T00:00:00+00:00",
                cursor=cursor,
            ),
            options=options,
        )

    partition_request = replace(request, as_of=None, cursor=None)
    partition_first = _execute_harness(
        query_harness,
        partition_request,
        options=options,
    )
    partition_cursor = partition_first["next_cursor"]
    assert partition_cursor is not None

    conn = query_harness["conn"]
    conn.execute(
        'INSERT INTO "facts_quotes" '
        "(symbol, trade_date, score, revision, note, lane_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("BBB", "20260717", 4.5, 2, "new-partition", "lane-a"),
    )
    with pytest.raises(CursorMismatch, match="query"):
        _execute_harness(
            query_harness,
            replace(partition_request, cursor=partition_cursor),
            options=options,
        )


@pytest.mark.parametrize("value", ["20260229", "2026-07-16", 20260716])
def test_range_field_requires_strict_round_trip_yyyymmdd_before_snapshot(
    query_harness: dict[str, object],
    value: object,
) -> None:
    before = query_harness["calls"]["snapshot"]
    with pytest.raises(QueryValidationError, match="yyyymmdd|text"):
        _execute_harness(
            query_harness,
            _harness_request(filters={"trade_date": {"eq": value}}),
        )
    assert query_harness["calls"]["snapshot"] == before


def test_lookback_equal_to_max_passes_and_greater_fails_before_snapshot(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = _execute_harness(
        query_harness,
        _harness_request(filters={"trade_date": {"between": ["20260706", "20260716"]}}),
    )
    assert {row["trade_date"] for row in exact["data"]} == {"20260715", "20260716"}

    registry = query_harness["registry"]
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )
    with pytest.raises(QueryBudgetError, match="max_lookback_days=10"):
        _service(tmp_path, registry).execute(
            _harness_request(
                filters={"trade_date": {"between": ["20260705", "20260716"]}}
            ),
            access=query_harness["access"],
            now=NOW,
            request_id="request-query",
        )


def test_as_of_normalizes_in_dataset_timezone_and_is_inclusive(
    query_harness: dict[str, object],
) -> None:
    response = _execute_harness(
        query_harness,
        _harness_request(as_of="2026-07-16T00:00:00+00:00"),
    )

    assert {row["trade_date"] for row in response["data"]} == {"20260715", "20260716"}
    assert response["metadata"]["requested_as_of"] == "2026-07-16T00:00:00+00:00"
    assert response["metadata"]["resolved_as_of"] == "2026-07-16T00:00:00+08:00"


def test_rfc3339_as_of_cross_timezone_is_inclusive_and_upper_bound_wins(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = query_harness["conn"]
    conn.execute('ALTER TABLE "facts_quotes" ADD COLUMN "event_time" TEXT')
    conn.executemany(
        'UPDATE "facts_quotes" SET "event_time" = ? WHERE rowid = ?',
        [
            ("2026-07-16T07:59:59+08:00", -2),
            ("2026-07-16T09:00:00+08:00", 0),
            ("2026-07-16T10:00:00+08:00", 1),
            ("2026-07-17T10:00:00+08:00", 2),
            ("2026-07-18T10:00:00+08:00", 3),
        ],
    )
    conn.commit()
    base_dataset = query_harness["dataset"]
    dataset = replace(
        base_dataset,
        fields=(
            *base_dataset.fields,
            DatasetField("event_time", "text", False, True, True, True),
        ),
        as_of_field="event_time",
        as_of_format="rfc3339",
    )
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=query_harness["registry"].query_defaults,
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: query_harness["evidence"],
    )
    service = _service(tmp_path, registry)

    inclusive = service.execute(
        _harness_request(
            fields=("symbol", "event_time"),
            as_of="2026-07-16T02:00:00+00:00",
            order=("event_time:asc",),
        ),
        access=query_harness["access"],
        now=NOW,
        request_id="request-rfc3339-inclusive",
    )
    assert [row["event_time"] for row in inclusive["data"]] == [
        "2026-07-16T07:59:59+08:00",
        "2026-07-16T09:00:00+08:00",
        "2026-07-16T10:00:00+08:00",
    ]
    assert inclusive["metadata"]["requested_as_of"] == "2026-07-16T02:00:00+00:00"
    assert inclusive["metadata"]["resolved_as_of"] == "2026-07-16T10:00:00+08:00"

    stricter = service.execute(
        _harness_request(
            fields=("symbol", "event_time"),
            filters={"event_time": {"lte": "2026-07-16T09:00:00+08:00"}},
            as_of="2026-07-16T02:00:00+00:00",
            order=("event_time:asc",),
        ),
        access=query_harness["access"],
        now=NOW,
        request_id="request-rfc3339-upper-bound",
    )
    assert [row["event_time"] for row in stricter["data"]] == [
        "2026-07-16T07:59:59+08:00",
        "2026-07-16T09:00:00+08:00",
    ]
    assert stricter["metadata"]["resolved_as_of"] == "2026-07-16T09:00:00+08:00"


@pytest.mark.parametrize(
    ("runtime_state", "top_state", "degraded", "returns_rows", "lineage_complete"),
    [
        ("success", "ready", False, True, True),
        ("empty", "empty", False, False, True),
        ("unobserved", "unobserved", True, False, False),
        ("paused", "paused", True, False, False),
        ("failed", "failed", True, True, True),
        ("stale", "stale", True, True, True),
    ],
)
def test_query_runtime_state_and_metadata_truth_table(
    query_harness: dict[str, object],
    runtime_state: str,
    top_state: str,
    degraded: bool,
    returns_rows: bool,
    lineage_complete: bool,
) -> None:
    query_harness["evidence_box"]["value"] = _state_evidence(runtime_state)

    response = _execute_harness(query_harness, _harness_request(limit=2))
    metadata = response["metadata"]

    assert metadata["runtime_state"] == runtime_state
    assert metadata["state"] == top_state
    assert metadata["degraded"] is degraded
    assert bool(response["data"]) is returns_rows
    assert (response["next_cursor"] is not None) is returns_rows
    assert metadata["freshness"] == {
        "state": "fresh" if runtime_state == "success" else runtime_state,
        "stale": runtime_state == "stale",
        "sla_seconds": 86_400,
    }
    assert metadata["quality"] == {
        "state": "valid" if runtime_state in {"success", "empty"} else "degraded",
        "valid": runtime_state in {"success", "empty"},
        "evidence": sorted(_state_evidence(runtime_state).projection.reasons),
    }
    assert metadata["lineage"]["complete"] is lineage_complete
    assert metadata["lineage"]["state"] == (
        "complete" if lineage_complete else "incomplete"
    )
    if not returns_rows:
        assert response["next_cursor"] is None


def test_failed_rows_require_prior_success_but_trusted_failure_lineage_is_complete(
    query_harness: dict[str, object],
) -> None:
    query_harness["evidence_box"]["value"] = _state_evidence(
        "failed",
        prior_success=False,
    )

    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert response["data"] == []
    assert response["next_cursor"] is None
    assert response["metadata"]["lineage"]["complete"] is True
    assert response["metadata"]["lineage"]["providers"] == ["provider-current"]


@pytest.mark.parametrize(
    ("prior_success", "returns_rows", "complete", "providers"),
    [
        (True, True, True, ["provider-prior"]),
        (False, False, False, []),
    ],
)
def test_invalid_current_failed_receipt_uses_only_trusted_prior_lineage(
    query_harness: dict[str, object],
    prior_success: bool,
    returns_rows: bool,
    complete: bool,
    providers: list[str],
) -> None:
    query_harness["evidence_box"]["value"] = _state_evidence(
        "failed",
        trusted_current=False,
        prior_success=prior_success,
    )

    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert bool(response["data"]) is returns_rows
    assert response["metadata"]["lineage"]["complete"] is complete
    assert response["metadata"]["lineage"]["providers"] == providers


def test_healthy_state_with_incomplete_receipt_proof_is_503(
    query_harness: dict[str, object],
) -> None:
    query_harness["evidence_box"]["value"] = _state_evidence(
        "success",
        trusted_current=False,
    )

    with pytest.raises(query_module.QueryServiceUnavailable, match="unavailable"):
        _execute_harness(query_harness, _harness_request())


def test_response_metadata_and_lineage_have_recursive_exact_key_sets(
    query_harness: dict[str, object],
) -> None:
    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert set(response) == {
        "api_version",
        "catalog_version",
        "request_id",
        "dataset_id",
        "schema_version",
        "data",
        "next_cursor",
        "metadata",
    }
    assert set(response["metadata"]) == {
        "state",
        "runtime_state",
        "degraded",
        "freshness",
        "quality",
        "lineage",
        "receipt_id",
        "data_through",
        "observed_at",
        "requested_as_of",
        "resolved_as_of",
        "reasons",
    }
    assert set(response["metadata"]["freshness"]) == {
        "state",
        "stale",
        "sla_seconds",
    }
    assert set(response["metadata"]["quality"]) == {"state", "valid", "evidence"}
    assert set(response["metadata"]["lineage"]) == {
        "state",
        "complete",
        "provider_neutral",
        "authority",
        "dataset_id",
        "providers",
        "receipt_watermark",
    }
    serialized = json.dumps(response, sort_keys=True)
    for forbidden in (
        "facts_quotes",
        "lane_key",
        "primary_table",
        "provider_api",
        "adapter_version",
        "__ss_rowid",
    ):
        assert forbidden not in serialized


def test_canonical_alias_binds_response_and_exact_dataset_grant(
    query_harness: dict[str, object],
) -> None:
    access = QueryAccessContext.from_grants(
        tenant_id="tenant-compat",
        scopes=(),
        allowed_dataset_ids=("cn.test.quotes",),
    )

    response = query_harness["service"].execute(
        _harness_request(dataset_id="tushare.test_quotes", limit=2),
        access=access,
        now=NOW,
        request_id="request-alias",
    )

    assert response["dataset_id"] == "cn.test.quotes"
    assert response["metadata"]["lineage"]["dataset_id"] == "cn.test.quotes"


def test_nullable_mixed_direction_keyset_has_no_duplicates_or_gaps_and_signed_rowids(
    query_harness: dict[str, object],
) -> None:
    cursor = None
    rows: list[tuple[str, str, float | None, int]] = []
    cursors: list[str] = []
    while True:
        response = _execute_harness(
            query_harness,
            _harness_request(
                order=("score:desc", "symbol:asc"),
                limit=1,
                cursor=cursor,
            ),
        )
        rows.extend(
            (
                row["symbol"],
                row["trade_date"],
                row["score"],
                row["revision"],
            )
            for row in response["data"]
        )
        cursor = response["next_cursor"]
        if cursor is None:
            break
        cursors.append(cursor)

    assert rows == [
        ("CCC", "20260717", 3.5, 1),
        ("BBB", "20260716", 2.5, 1),
        ("AAA", "20260716", 1.5, 2),
        ("AAA", "20260715", None, 1),
    ]
    assert len(cursors) == 3
    assert len(rows) == len(set(rows))


def test_validly_signed_cursor_with_invalid_flat_sort_key_is_400(
    query_harness: dict[str, object],
) -> None:
    first = _execute_harness(
        query_harness,
        _harness_request(
            order=("score:desc", "symbol:asc"),
            limit=1,
        ),
    )
    cursor = first["next_cursor"]
    assert cursor is not None
    payload_segment = cursor.split(".", 1)[0]
    payload = json.loads(
        base64.urlsafe_b64decode(payload_segment + "=" * (-len(payload_segment) % 4))
    )
    valid_key = list(payload["sort_key"])
    assert len(valid_key) == 9

    malformed_keys: list[tuple[object, ...]] = []
    malformed_keys.append(tuple(valid_key[:-1]))
    for index, value in (
        (0, True),
        (0, 2),
        (1, "not-a-float"),
        (8, True),
        (8, 2**63),
    ):
        changed = valid_key.copy()
        changed[index] = value
        malformed_keys.append(tuple(changed))
    rank_value_mismatch = valid_key.copy()
    rank_value_mismatch[0:2] = [1, 3.5]
    malformed_keys.append(tuple(rank_value_mismatch))
    nonnullable_null = valid_key.copy()
    nonnullable_null[2:4] = [1, None]
    malformed_keys.append(tuple(nonnullable_null))

    for malformed_key in malformed_keys:
        malformed_cursor = _resign_cursor_sort_key(cursor, malformed_key)
        with pytest.raises(InvalidCursor, match="sort key"):
            _execute_harness(
                query_harness,
                _harness_request(
                    order=("score:desc", "symbol:asc"),
                    limit=1,
                    cursor=malformed_cursor,
                ),
            )


def test_cursor_query_policy_and_receipt_binding_mismatches(
    query_harness: dict[str, object],
) -> None:
    first = _execute_harness(
        query_harness,
        _harness_request(limit=1, order=("score:desc",)),
    )
    cursor = first["next_cursor"]
    assert cursor is not None

    with pytest.raises(CursorMismatch, match="query"):
        _execute_harness(
            query_harness,
            _harness_request(
                limit=1,
                order=("score:desc",),
                filters={"symbol": {"in": ["AAA", "BBB"]}},
                cursor=cursor,
            ),
        )

    other_access = QueryAccessContext.from_grants(
        tenant_id="tenant-other",
        scopes=("market_data",),
        allowed_dataset_ids=(),
    )
    with pytest.raises(CursorMismatch, match="policy"):
        query_harness["service"].execute(
            _harness_request(limit=1, order=("score:desc",), cursor=cursor),
            access=other_access,
            now=NOW,
            request_id="request-other-policy",
        )

    changed = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            receipt_id="receipt-changed",
        ),
    )
    query_harness["evidence_box"]["value"] = changed
    with pytest.raises(CursorMismatch, match="receipt watermark"):
        _execute_harness(
            query_harness,
            _harness_request(limit=1, order=("score:desc",), cursor=cursor),
        )


def test_private_fixed_routing_change_invalidates_cursor_without_catalog_drift(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _execute_harness(
        query_harness,
        _harness_request(limit=1, order=("symbol:asc",)),
    )
    cursor = first["next_cursor"]
    assert cursor is not None
    old_registry = query_harness["registry"]
    old_dataset = query_harness["dataset"]
    changed_dataset = replace(
        old_dataset,
        read_model_adapter=replace(
            old_dataset.read_model_adapter,
            fixed_field_filters=(FixedFieldFilter("lane_key", ("lane-b",)),),
        ),
    )
    changed_registry = DatasetRegistry(
        (changed_dataset,),
        query_defaults=old_registry.query_defaults,
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda _conn, _dataset, *, now, registry: query_harness["evidence"],
    )

    with pytest.raises(CursorMismatch, match="query"):
        _service(tmp_path, changed_registry).execute(
            _harness_request(limit=1, order=("symbol:asc",), cursor=cursor),
            access=query_harness["access"],
            now=NOW,
            request_id="request-routing-change",
        )


def test_progress_handler_spans_every_task4_sql_and_fetches_only_limit_plus_one(
    query_harness: dict[str, object],
) -> None:
    conn = query_harness["conn"]
    assert isinstance(conn, _TrackingConnection)

    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert len(response["data"]) == 2
    assert len(conn.progress_events) == 2
    installed_handler, quantum = conn.progress_events[0]
    assert callable(installed_handler)
    assert quantum == 1000
    assert conn.progress_events[1] == (None, 0)
    assert conn.progress_active is False
    assert conn.sql_progress_states
    assert all(conn.sql_progress_states)
    assert conn.fetchmany_sizes == [3]


@pytest.mark.parametrize(
    ("step_budget", "expected_callback_calls"),
    [(1, 1), (1000, 1), (1001, 2)],
)
def test_sqlite_progress_budget_interrupts_at_first_callback_reaching_budget(
    step_budget: int,
    expected_callback_calls: int,
) -> None:
    conn = sqlite3.connect(":memory:", factory=_TrackingConnection)
    assert isinstance(conn, _TrackingConnection)

    try:
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            with query_module._sqlite_progress_budget(conn, step_budget):
                conn.execute(
                    """
                    WITH RECURSIVE counter(value) AS (
                        VALUES(0)
                        UNION ALL
                        SELECT value + 1 FROM counter WHERE value < 1000000
                    )
                    SELECT sum(value) FROM counter
                    """
                ).fetchone()

        assert conn.progress_callback_calls == expected_callback_calls
        assert conn.progress_events[-1] == (None, 0)
        assert conn.progress_active is False
    finally:
        conn.close()


def test_sqlite_failure_is_sanitized_and_progress_handler_is_cleared(
    query_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = query_harness["conn"]
    assert isinstance(conn, _TrackingConnection)
    leaked_detail = "SELECT token FROM /private/read-model.sqlite"

    def fail_queryability(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.OperationalError(leaked_detail)

    monkeypatch.setattr(
        query_module,
        "inspect_dataset_queryability",
        fail_queryability,
    )

    with pytest.raises(QueryServiceUnavailable) as caught:
        _execute_harness(query_harness, _harness_request(limit=2))

    assert str(caught.value) == "query service is unavailable"
    assert leaked_detail not in str(caught.value)
    assert conn.progress_events[-1] == (None, 0)
    assert conn.progress_active is False


def test_snapshot_open_failure_is_translated_to_sanitized_503(
    query_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked_detail = "/private/read-model.sqlite receipt payload token"

    @contextmanager
    def broken_snapshot(_path: Path):
        raise RuntimeProjectionError(leaked_detail)
        yield

    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        broken_snapshot,
    )

    with pytest.raises(QueryServiceUnavailable) as caught:
        _execute_harness(query_harness, _harness_request(limit=2))

    assert str(caught.value) == "query service is unavailable"
    assert leaked_detail not in str(caught.value)


def test_response_serialization_failure_is_sanitized_and_clears_progress(
    query_harness: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_json_bytes = query_module._canonical_json_bytes
    calls = 0

    def fail_final_serialization(value: object) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("secret serialization detail")
        return canonical_json_bytes(value)

    monkeypatch.setattr(
        query_module,
        "_canonical_json_bytes",
        fail_final_serialization,
    )

    with pytest.raises(QueryServiceUnavailable) as caught:
        _execute_harness(query_harness, _harness_request(limit=2))

    assert str(caught.value) == "query service is unavailable"
    conn = query_harness["conn"]
    assert isinstance(conn, _TrackingConnection)
    assert conn.progress_events[-1] == (None, 0)
    assert conn.progress_active is False


def test_sqlite_vm_budget_interrupts_the_whole_request_as_sanitized_503(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = query_harness["dataset"]
    registry = query_harness["registry"]
    constrained_registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(registry.query_defaults, sqlite_progress_steps=1),
    )
    service = _service(tmp_path, constrained_registry)
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: query_harness["evidence"],
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        service.execute(
            _harness_request(limit=2),
            access=query_harness["access"],
            now=NOW,
            request_id="request-query",
        )

    conn = query_harness["conn"]
    assert isinstance(conn, _TrackingConnection)
    assert conn.progress_events[0][1] == 1
    assert conn.progress_events[-1] == (None, 0)
    assert conn.progress_active is False


def test_wal_query_returns_only_old_old_then_new_new_never_mixed(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = (tmp_path / "wal-read-model.sqlite").absolute()
    setup = sqlite3.connect(db_path)
    setup.executescript(SCHEMA_SQL)
    assert setup.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
    setup.execute(
        'CREATE TABLE "facts_quotes" ('
        '"symbol" TEXT NOT NULL, "trade_date" TEXT NOT NULL, '
        '"score" REAL, "revision" INTEGER NOT NULL, "note" TEXT, '
        '"lane_key" TEXT NOT NULL)'
    )
    setup.execute(
        'INSERT INTO "facts_quotes" '
        "(symbol, trade_date, score, revision, note, lane_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("OLD", "20260715", 1.0, 1, "old", "lane-a"),
    )
    old_receipt = _insert_query_success_receipt(
        monkeypatch,
        setup,
        attempt_id="attempt-old",
        started_at="2026-07-16T01:59:00+00:00",
        finished_at="2026-07-16T02:00:00+00:00",
        data_through="20260715",
    )
    setup.commit()

    target_dataset = query_harness["dataset"]
    target_binding = target_dataset.provider_bindings[0]
    unrelated_dataset = replace(
        target_dataset,
        dataset_id="cn.test.unrelated",
        aliases=("tushare.test_unrelated",),
        provider_bindings=(
            replace(
                target_binding,
                provider="provider-b",
                api_name="unrelated",
                adapter_version="writer.unrelated.v1",
                read_discriminator_value="lane-unrelated",
                target_tables=("facts_unrelated",),
            ),
        ),
        read_model_adapter=ReadModelAdapter(
            adapter_version="reader.unrelated.v1",
            primary_table="facts_unrelated",
            fixed_field_filters=(FixedFieldFilter("lane_key", ("lane-unrelated",)),),
        ),
    )
    registry = DatasetRegistry(
        (target_dataset, unrelated_dataset),
        query_defaults=query_harness["registry"].query_defaults,
    )
    service = QueryService(
        db_path=db_path,
        registry=registry,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    actual_projection = projection_module.project_dataset_runtime_evidence
    committed = False
    new_receipt: str | None = None

    def project_then_commit(
        conn: sqlite3.Connection,
        dataset: object,
        *,
        now: datetime,
        registry: DatasetRegistry,
    ) -> DatasetRuntimeEvidence:
        nonlocal committed, new_receipt
        evidence = actual_projection(conn, dataset, now=now, registry=registry)
        if not committed:
            writer = sqlite3.connect(db_path)
            try:
                writer.execute("BEGIN IMMEDIATE")
                writer.execute('DELETE FROM "facts_quotes"')
                writer.execute(
                    'INSERT INTO "facts_quotes" '
                    "(symbol, trade_date, score, revision, note, lane_key) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("NEW", "20260716", 2.0, 1, "new", "lane-a"),
                )
                new_receipt = _insert_query_success_receipt(
                    monkeypatch,
                    writer,
                    attempt_id="attempt-new",
                    started_at="2026-07-16T03:29:00+00:00",
                    finished_at="2026-07-16T03:30:00+00:00",
                    data_through="20260716",
                )
                writer.commit()
            finally:
                writer.close()
            committed = True
        return evidence

    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        projection_module.open_verified_read_model_snapshot,
    )
    monkeypatch.setattr(
        projection_module,
        "read_model_snapshot_lock",
        lambda _path: nullcontext(),
    )
    monkeypatch.setattr(
        projection_module,
        "read_model_snapshot_open_lock",
        lambda _path: nullcontext(),
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        project_then_commit,
    )

    old_response = service.execute(
        _harness_request(fields=("symbol", "trade_date"), order=("symbol:asc",)),
        access=query_harness["access"],
        now=NOW,
        request_id="request-old-snapshot",
    )
    assert [row["symbol"] for row in old_response["data"]] == ["OLD"]
    assert old_response["metadata"]["receipt_id"] == old_receipt
    assert old_response["metadata"]["data_through"] == "2026-07-15T00:00:00+08:00"

    new_response = service.execute(
        _harness_request(fields=("symbol", "trade_date"), order=("symbol:asc",)),
        access=query_harness["access"],
        now=NOW,
        request_id="request-new-snapshot",
    )
    assert [row["symbol"] for row in new_response["data"]] == ["NEW"]
    assert new_response["metadata"]["receipt_id"] == new_receipt
    assert new_response["metadata"]["data_through"] == "2026-07-16T00:00:00+08:00"

    _insert_query_success_receipt(
        monkeypatch,
        setup,
        attempt_id="attempt-unrelated",
        started_at="2026-07-16T03:39:00+00:00",
        finished_at="2026-07-16T03:40:00+00:00",
        data_through="20260716",
        dataset_id="cn.test.unrelated",
        provider="provider-b",
        provider_api="unrelated",
        adapter_version="writer.unrelated.v1",
        target_table="facts_unrelated",
    )
    setup.commit()
    after_unrelated = service.execute(
        _harness_request(fields=("symbol", "trade_date"), order=("symbol:asc",)),
        access=query_harness["access"],
        now=NOW,
        request_id="request-after-unrelated",
    )
    assert after_unrelated["metadata"]["receipt_id"] == new_receipt
    assert (
        after_unrelated["metadata"]["lineage"]["receipt_watermark"]
        == new_response["metadata"]["lineage"]["receipt_watermark"]
    )
    setup.close()


def test_full_utf8_response_budget_accepts_exact_bytes_and_rejects_one_less(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = query_harness["dataset"]
    base_registry = query_harness["registry"]
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: query_harness["evidence"],
    )

    baseline = _service(tmp_path, base_registry).execute(
        _harness_request(limit=3),
        access=query_harness["access"],
        now=NOW,
        request_id="请求-一",
    )
    compact_text = json.dumps(
        baseline,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded_size = len(compact_text.encode("utf-8"))
    assert encoded_size > len(compact_text)

    exact_registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(
            base_registry.query_defaults,
            max_response_bytes=encoded_size,
        ),
    )
    exact = _service(tmp_path, exact_registry).execute(
        _harness_request(limit=3),
        access=query_harness["access"],
        now=NOW,
        request_id="请求-一",
    )
    assert exact["request_id"] == "请求-一"

    too_small_registry = DatasetRegistry(
        (dataset,),
        query_defaults=replace(
            base_registry.query_defaults,
            max_response_bytes=encoded_size - 1,
        ),
    )
    with pytest.raises(QueryBudgetError, match="max_response_bytes"):
        _service(tmp_path, too_small_registry).execute(
            _harness_request(limit=3),
            access=query_harness["access"],
            now=NOW,
            request_id="请求-一",
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("revision", "not-an-integer"),
        ("score", float("inf")),
    ],
)
def test_wrong_or_nonfinite_stored_values_fail_closed_as_503(
    query_harness: dict[str, object],
    column: str,
    value: object,
) -> None:
    conn = query_harness["conn"]
    conn.execute(
        f'UPDATE "facts_quotes" SET "{column}" = ? WHERE symbol = ?', (value, "BBB")
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        _execute_harness(
            query_harness,
            _harness_request(
                fields=("symbol", "score", "revision"),
                order=("symbol:asc",),
            ),
        )


def test_extreme_rfc3339_timezone_conversion_is_400_before_snapshot(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = replace(query_harness["dataset"], as_of_format="rfc3339")
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=query_harness["registry"].query_defaults,
    )
    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        lambda _path: pytest.fail("snapshot must remain unopened"),
    )

    with pytest.raises(QueryValidationError, match="supported range"):
        _service(tmp_path, registry).execute(
            _harness_request(as_of="0001-01-01T00:00:00+23:59"),
            access=query_harness["access"],
            now=NOW,
            request_id="request-extreme-year",
        )


def test_invalid_injected_dataset_timezone_is_sanitized_503_before_snapshot(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = replace(query_harness["dataset"], timezone="Invalid/Timezone")
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=query_harness["registry"].query_defaults,
    )
    opened = False

    def forbidden_snapshot(_path: Path):
        nonlocal opened
        opened = True
        raise AssertionError("snapshot must remain unopened")

    monkeypatch.setattr(
        query_module,
        "open_verified_read_model_snapshot",
        forbidden_snapshot,
    )

    with pytest.raises(QueryServiceUnavailable) as caught:
        _service(tmp_path, registry).execute(
            _harness_request(as_of="2026-07-16T00:00:00+00:00"),
            access=query_harness["access"],
            now=NOW,
            request_id="request-invalid-timezone",
        )

    assert str(caught.value) == "query service is unavailable"
    assert "Invalid/Timezone" not in str(caught.value)
    assert opened is False


@pytest.mark.parametrize(
    ("raw_data_through", "normalized"),
    [
        ("20260715", "2026-07-15T00:00:00+08:00"),
        ("2026-07-15T12:34:56", "2026-07-15T12:34:56+08:00"),
    ],
)
def test_data_through_is_normalized_in_the_dataset_timezone(
    query_harness: dict[str, object],
    raw_data_through: str,
    normalized: str,
) -> None:
    evidence = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            data_through=raw_data_through,
            observed_at="2026-07-16T03:00:00Z",
        ),
        last_success_data_through=raw_data_through,
    )
    query_harness["evidence_box"]["value"] = evidence

    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert response["metadata"]["data_through"] == normalized
    assert response["metadata"]["observed_at"] == "2026-07-16T03:00:00+00:00"


@pytest.mark.parametrize(
    "raw_data_through",
    [
        "2026-03-08T02:30:00",
        "2026-11-01T01:30:00",
        "2026-07-15 12:00:00",
    ],
)
def test_nonexistent_ambiguous_or_nonstrict_local_data_through_is_503(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_data_through: str,
) -> None:
    dataset = replace(query_harness["dataset"], timezone="America/New_York")
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=query_harness["registry"].query_defaults,
    )
    evidence = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            data_through=raw_data_through,
        ),
        last_success_data_through=raw_data_through,
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        _service(tmp_path, registry).execute(
            _harness_request(limit=2),
            access=query_harness["access"],
            now=NOW,
            request_id="request-dst-boundary",
        )


def test_unambiguous_naive_local_data_through_uses_declared_dst_offset(
    query_harness: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = replace(query_harness["dataset"], timezone="America/New_York")
    registry = DatasetRegistry(
        (dataset,),
        query_defaults=query_harness["registry"].query_defaults,
    )
    evidence = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            data_through="2026-07-15T12:34:56",
        ),
        last_success_data_through="2026-07-15T12:34:56",
    )
    monkeypatch.setattr(
        query_module,
        "project_dataset_runtime_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    response = _service(tmp_path, registry).execute(
        _harness_request(limit=2),
        access=query_harness["access"],
        now=NOW,
        request_id="request-dst-normal",
    )

    assert response["metadata"]["data_through"] == "2026-07-15T12:34:56-04:00"


def test_naive_observed_at_is_never_localized_for_healthy_evidence(
    query_harness: dict[str, object],
) -> None:
    query_harness["evidence_box"]["value"] = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            observed_at="2026-07-16T03:00:00",
        ),
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        _execute_harness(query_harness, _harness_request(limit=2))


def test_invalid_degraded_evidence_is_null_with_only_a_sanitized_reason(
    query_harness: dict[str, object],
) -> None:
    evidence = _state_evidence("unobserved")
    query_harness["evidence_box"]["value"] = replace(
        evidence,
        projection=replace(
            evidence.projection,
            data_through="not-a-timestamp",
            observed_at="2026-07-16T03:00:00",
        ),
    )

    response = _execute_harness(query_harness, _harness_request(limit=2))

    assert response["data"] == []
    assert response["metadata"]["data_through"] is None
    assert response["metadata"]["observed_at"] is None
    assert response["metadata"]["reasons"] == [
        "invalid_data_through",
        "no_recognized_receipt",
    ]


def test_invalid_healthy_data_through_is_sanitized_503_not_public_400(
    query_harness: dict[str, object],
) -> None:
    query_harness["evidence_box"]["value"] = replace(
        query_harness["evidence"],
        projection=replace(
            query_harness["evidence"].projection,
            data_through="20260230",
        ),
        last_success_data_through="20260230",
    )

    with pytest.raises(QueryServiceUnavailable, match="query service is unavailable"):
        _execute_harness(query_harness, _harness_request(limit=2))
