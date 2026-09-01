from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import catalog_executor as executor
from catalog_service import CatalogFilters
from query_contract import QueryAccessContext, QueryBudgetError, QueryValidationError
from query_cursor import CursorMismatch, InvalidCursor
from query_service import QueryServiceUnavailable
from storage.receipt_projection import RuntimeProjectionError

NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


def arguments():
    return {
        "access": QueryAccessContext.from_grants(
            tenant_id="synthetic-tenant", scopes=("read",), allowed_dataset_ids=()
        ),
        "filters": CatalogFilters(),
        "limit": 1,
        "cursor": None,
        "now": NOW,
        "request_id": "test-request",
    }


@pytest.mark.parametrize("raw", ["", " 1", "1 ", "01", "+1", "-1", "3", "true", "1.0"])
def test_worker_configuration_rejects_noncanonical_values(monkeypatch, raw):
    monkeypatch.setenv("TRADINGDATAS_CATALOG_WORKERS", raw)
    with pytest.raises(QueryServiceUnavailable):
        executor.catalog_worker_count()


@pytest.mark.parametrize("raw,expected", [(None, 0), ("0", 0), ("1", 1), ("2", 2)])
def test_worker_configuration_default_and_supported_values(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("TRADINGDATAS_CATALOG_WORKERS", raising=False)
    else:
        monkeypatch.setenv("TRADINGDATAS_CATALOG_WORKERS", raw)
    assert executor.catalog_worker_count() == expected


def test_default_inline_does_not_initialize_pool_or_identity(monkeypatch):
    monkeypatch.delenv("TRADINGDATAS_CATALOG_WORKERS", raising=False)
    kwargs = arguments()
    response = {"sentinel": object()}
    calls = []
    catalog = SimpleNamespace(
        list_datasets=lambda **values: calls.append(values) or response
    )
    monkeypatch.setattr(
        executor, "_identity_for_catalog", lambda _: pytest.fail("identity")
    )
    assert executor.execute_catalog(catalog, **kwargs) is response
    assert calls == [kwargs]


def test_job_serializes_only_explicit_grants_and_filter_primitives():
    kwargs = arguments()
    payload = executor._pack_job(**kwargs)
    decoded = json.loads(payload)
    assert set(decoded) == {"access", "filters", "limit", "cursor", "now", "request_id"}
    assert set(decoded["access"]) == {
        "tenant_id",
        "scopes",
        "allowed_dataset_ids",
        "policy_id",
    }
    assert decoded["access"]["policy_id"] == kwargs["access"].policy_id
    assert b"signing_key" not in payload and b"credential" not in payload


class FakePool:
    def __init__(self):
        self.calls = []
        self.futures = []
        self.submitted = threading.Event()
        self.shutdown_calls = []

    def submit(self, function, payload):
        future = Future()
        self.calls.append((function, payload))
        self.futures.append(future)
        self.submitted.set()
        return future

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


def fake_state(monkeypatch, workers=1):
    pool = FakePool()
    catalog = SimpleNamespace(
        _registry=SimpleNamespace(
            query_defaults=SimpleNamespace(max_response_bytes=4096)
        )
    )
    monkeypatch.setattr(
        executor, "_identity_for_catalog", lambda _: {"synthetic": True}
    )
    monkeypatch.setattr(executor, "_new_pool", lambda count, identity: pool)
    state = executor._ExecutorState()
    state.initialize(catalog, workers)
    return state, pool, catalog, workers


def test_admission_has_no_backlog_and_retains_slot_until_future_finishes(monkeypatch):
    state, pool, catalog, workers = fake_state(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert pool.submitted.wait(5)
        with pytest.raises(QueryServiceUnavailable):
            state.execute(catalog, workers, arguments())
        assert len(pool.calls) == 1 and not result.done()
        pool.futures[0].set_result(("ok", b'{"data":[]}'))
        assert result.result(timeout=5) == {"data": []}
    state.shutdown()
    assert pool.shutdown_calls == [{"wait": True, "cancel_futures": False}]
    with pytest.raises(QueryServiceUnavailable):
        state.execute(catalog, workers, arguments())


@pytest.mark.parametrize(
    "code,error",
    [
        ("budget", QueryBudgetError),
        ("validation", QueryValidationError),
        ("cursor_mismatch", CursorMismatch),
        ("invalid_cursor", InvalidCursor),
        ("projection", RuntimeProjectionError),
        ("unavailable", QueryServiceUnavailable),
    ],
)
def test_worker_errors_return_only_fixed_public_error_classes(monkeypatch, code, error):
    state, pool, catalog, workers = fake_state(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert pool.submitted.wait(5)
        pool.futures[0].set_result((code, b""))
        with pytest.raises(error) as caught:
            result.result(timeout=5)
        assert "sensitive" not in str(caught.value)
    state.shutdown()


def test_ipc_failure_is_terminal_without_replay_or_inline_fallback(monkeypatch):
    state, pool, catalog, workers = fake_state(monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert pool.submitted.wait(5)
        pool.futures[0].set_exception(RuntimeError("sensitive transport details"))
        with pytest.raises(QueryServiceUnavailable) as caught:
            result.result(timeout=5)
        assert "sensitive" not in str(caught.value)
    with pytest.raises(QueryServiceUnavailable):
        state.execute(catalog, workers, arguments())
    assert len(pool.calls) == 1
    state.shutdown()


def test_opt_in_requires_prelisten_initialization(monkeypatch):
    state = executor._ExecutorState()
    monkeypatch.setattr(executor, "_new_pool", lambda *_: pytest.fail("lazy bootstrap"))
    with pytest.raises(QueryServiceUnavailable):
        state.execute(object(), 1, arguments())


def test_shutdown_blocks_new_work_and_waits_for_real_completion(monkeypatch):
    state, pool, catalog, workers = fake_state(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert pool.submitted.wait(5)
        shutdown = threads.submit(state.shutdown)
        deadline = time.monotonic() + 5
        while not state._closed and time.monotonic() < deadline:
            time.sleep(0.001)
        assert state._closed and not shutdown.done()
        with pytest.raises(QueryServiceUnavailable):
            state.execute(catalog, workers, arguments())
        pool.futures[0].set_result(("ok", b"{}"))
        assert result.result(timeout=5) == {}
        shutdown.result(timeout=5)
    assert pool.shutdown_calls == [{"wait": True, "cancel_futures": False}]


def test_interrupted_wait_keeps_admission_until_worker_done(monkeypatch):
    state, pool, catalog, workers = fake_state(monkeypatch)
    interrupted = threading.Event()

    class InterruptedFuture(Future):
        first = True

        def result(self, timeout=None):
            if self.first:
                self.first = False
                interrupted.set()
                raise KeyboardInterrupt()
            return super().result(timeout=timeout)

    future = InterruptedFuture()
    pool.submit = lambda *args: future
    with ThreadPoolExecutor(max_workers=1) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert interrupted.wait(5)
        with pytest.raises(QueryServiceUnavailable):
            state.execute(catalog, workers, arguments())
        assert not result.done()
        future.set_result(("ok", b"{}"))
        with pytest.raises(KeyboardInterrupt):
            result.result(timeout=5)
    state.shutdown()


@pytest.mark.parametrize(
    "reply",
    [
        ("ok", b"{"),
        ("ok", b"[]"),
        ("ok", b'{"a":NaN}'),
        ("ok", b"x" * 4097),
        ("unavailable", b"sensitive"),
        ("unknown", b""),
        ("ok", "not bytes"),
        {"data": []},
    ],
)
def test_invalid_or_oversized_ipc_reply_fails_closed(reply):
    with pytest.raises(QueryServiceUnavailable):
        executor._decode_reply(reply, 4096)


@pytest.mark.parametrize(
    "error,code",
    [
        (QueryBudgetError("sensitive"), "budget"),
        (QueryValidationError("sensitive"), "validation"),
        (CursorMismatch("sensitive"), "cursor_mismatch"),
        (InvalidCursor("sensitive"), "invalid_cursor"),
        (RuntimeProjectionError("sensitive"), "projection"),
        (ValueError("sensitive"), "unavailable"),
        (SystemExit("sensitive"), "unavailable"),
    ],
)
def test_worker_never_transmits_exception_message_or_traceback(
    monkeypatch, error, code
):
    def fail(**kwargs):
        raise error

    monkeypatch.setattr(
        executor, "_WORKER_CATALOG", SimpleNamespace(list_datasets=fail)
    )
    assert executor._worker_call(executor._pack_job(**arguments())) == (code, b"")


def test_response_budget_is_enforced_before_ipc(monkeypatch):
    catalog = SimpleNamespace(
        list_datasets=lambda **_: {"data": ["x" * 100]},
        _registry=SimpleNamespace(
            query_defaults=SimpleNamespace(max_response_bytes=20)
        ),
    )
    monkeypatch.setattr(executor, "_WORKER_CATALOG", catalog)
    assert executor._worker_call(executor._pack_job(**arguments())) == ("budget", b"")


def test_policy_identity_is_rebuilt_without_expanding_grants():
    kwargs = arguments()
    kwargs["access"] = QueryAccessContext.from_grants(
        tenant_id="restricted", scopes=(), allowed_dataset_ids=("cn.only.one",)
    )
    raw = executor._pack_job(**kwargs)
    unpacked = executor._unpack_job(raw)
    assert unpacked["access"] == kwargs["access"]
    job = json.loads(raw)
    job["access"]["allowed_dataset_ids"].append("cn.not.granted")
    with pytest.raises(QueryValidationError):
        executor._unpack_job(json.dumps(job).encode())


def test_failed_bootstrap_terminates_only_owned_pool_processes():
    events = []

    class Process:
        def __init__(self, name):
            self.name, self.alive = name, True

        def is_alive(self):
            return self.alive

        def terminate(self):
            events.append((self.name, "terminate"))

        def join(self, timeout):
            events.append((self.name, "join"))

        def kill(self):
            events.append((self.name, "kill"))
            self.alive = False

    owned = [Process("first"), Process("second")]
    pool = SimpleNamespace(
        _processes={1: owned[0], 2: owned[1]},
        shutdown=lambda **kwargs: events.append(("pool", kwargs)),
    )
    executor._discard_starting_pool(pool, 2)
    assert all(not process.is_alive() for process in owned)
    assert events[-1] == ("pool", {"wait": True, "cancel_futures": False})
    assert {name for name, _ in events} == {"first", "second", "pool"}


@pytest.fixture
def real_runtime(monkeypatch, tmp_path):
    import data_plane_runtime
    from storage.schema import SCHEMA_SQL
    from storage.sqlite_authority_lock import sqlite_authority_lock

    root = tmp_path.resolve() / "data"
    root.mkdir()
    database = root / "provider_native.sqlite"
    with (
        sqlite_authority_lock(database, mode="exclusive", create=True),
        sqlite3.connect(database) as conn,
    ):
        conn.executescript(SCHEMA_SQL)
    monkeypatch.setenv("TRADINGDATAS_DATA_MOUNT", str(tmp_path.resolve()))
    monkeypatch.setenv("TRADINGDATAS_DATA_ROOT", str(root))
    monkeypatch.setenv("TRADINGDATAS_DB_PATH", str(database))
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    monkeypatch.delenv("TRADINGDATAS_DATASET_REGISTRY_PATH", raising=False)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.setenv(
        "TRADINGDATAS_CURSOR_SIGNING_KEY", "synthetic-catalog-process-key-32-bytes"
    )
    data_plane_runtime._reset_data_plane_runtime_for_tests()
    runtime = data_plane_runtime.build_data_plane_runtime()
    try:
        yield runtime
    finally:
        data_plane_runtime._reset_data_plane_runtime_for_tests()


def test_real_spawn_catalog_matches_inline_and_reaps_children(real_runtime):
    catalog = real_runtime.catalog
    kwargs = arguments()
    kwargs["limit"] = 2
    expected = catalog.list_datasets(**kwargs)
    state = executor._ExecutorState()
    state.initialize(catalog, 2)
    children = tuple(state._pool._processes.values())
    assert len(children) == 2 and all(
        child.pid != os.getpid() and child.is_alive() for child in children
    )
    try:
        assert state.execute(catalog, 2, kwargs) == expected
        kwargs["cursor"] = expected["next_cursor"]
        assert state.execute(catalog, 2, kwargs) == catalog.list_datasets(**kwargs)
        restricted = dict(
            arguments(),
            access=QueryAccessContext.from_grants(
                tenant_id="restricted", scopes=(), allowed_dataset_ids=()
            ),
        )
        assert state.execute(catalog, 2, restricted)["data"] == []
    finally:
        state.shutdown()
    assert all(not child.is_alive() and child.exitcode == 0 for child in children)


@pytest.mark.parametrize(
    "field",
    [
        "root",
        "modules",
        "registry_sha256",
        "database_path",
        "cursor_signer_sha256",
        "uid",
    ],
)
def test_real_spawn_bootstrap_identity_mismatch_is_fail_closed(real_runtime, field):
    identity = executor._identity_for_catalog(real_runtime.catalog)
    identity[field] = "mismatch"
    with pytest.raises(QueryServiceUnavailable):
        executor._new_pool(1, identity)


def test_ipc_failure_holds_admission_until_executor_reaps_workers(monkeypatch):
    state, pool, catalog, workers = fake_state(monkeypatch)
    reaping = threading.Event()
    reaped = threading.Event()

    def shutdown(**kwargs):
        reaping.set()
        assert reaped.wait(5)
        pool.shutdown_calls.append(kwargs)

    pool.shutdown = shutdown
    with ThreadPoolExecutor(max_workers=1) as threads:
        result = threads.submit(state.execute, catalog, workers, arguments())
        assert pool.submitted.wait(5)
        pool.futures[0].set_exception(RuntimeError("synthetic broken worker"))
        assert reaping.wait(5)
        assert state._active == 1 and not result.done()
        with pytest.raises(QueryServiceUnavailable):
            state.execute(catalog, workers, arguments())
        reaped.set()
        with pytest.raises(QueryServiceUnavailable):
            result.result(timeout=5)
    assert state._active == 0 and pool.shutdown_calls == [
        {"wait": True, "cancel_futures": False}
    ]
    state.shutdown()


def test_real_worker_death_is_reaped_without_replay(real_runtime):
    state = executor._ExecutorState()
    state.initialize(real_runtime.catalog, 2)
    children = tuple(state._pool._processes.values())
    try:
        children[0].terminate()
        children[0].join(timeout=5)
        with pytest.raises(QueryServiceUnavailable):
            state.execute(real_runtime.catalog, 2, arguments())
        assert all(not child.is_alive() for child in children)
        with pytest.raises(QueryServiceUnavailable):
            state.execute(real_runtime.catalog, 2, arguments())
        assert state._pool is None
    finally:
        state.shutdown()


def test_parent_loaded_registry_must_match_frozen_raw_file(real_runtime):
    from dataset_registry import DatasetRegistry

    catalog = real_runtime.catalog
    original = catalog._registry
    catalog._registry = DatasetRegistry(
        original.datasets[:-1], query_defaults=original.query_defaults
    )
    try:
        with pytest.raises(QueryServiceUnavailable):
            executor._identity_for_catalog(catalog)
    finally:
        catalog._registry = original


def test_persistent_worker_opens_fresh_authority_snapshot_each_job(real_runtime):
    from storage.sqlite_authority_lock import sqlite_authority_lock

    catalog = real_runtime.catalog
    state = executor._ExecutorState()
    state.initialize(catalog, 1)
    children = tuple(state._pool._processes.values())
    try:
        first = state.execute(catalog, 1, arguments())
        assert len(first["data"]) == 1
        # Only this disposable test DB is changed: a cached response must not
        # hide a missing authority table on the next request to the same child.
        with (
            sqlite_authority_lock(catalog._db_path, mode="exclusive", create=False),
            sqlite3.connect(catalog._db_path) as conn,
        ):
            conn.execute("DROP TABLE market_ingest_runs")
        with pytest.raises(RuntimeProjectionError):
            state.execute(catalog, 1, arguments())
        assert all(child.is_alive() for child in children)
    finally:
        state.shutdown()
    assert all(not child.is_alive() for child in children)
