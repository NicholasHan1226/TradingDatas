"""Opt-in, bounded process isolation for authenticated catalog work only.

The caller retains authentication, quotas and tenant admission. Workers receive
only explicit grants and request primitives and execute the unchanged catalog
service against a new verified SQLite snapshot for each job.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

from catalog_service import CatalogFilters, CatalogService
from query_contract import QueryAccessContext, QueryBudgetError, QueryValidationError
from query_cursor import CursorMismatch, InvalidCursor
from query_service import QueryServiceUnavailable
from storage.receipt_projection import RuntimeProjectionError

_ROOT = Path(__file__).resolve().parent
_RUNTIME_MODULES = (
    "catalog_service",
    "storage.receipt_projection",
    "data_plane_runtime",
    "dataset_registry",
    "query_contract",
    "query_cursor",
    "query_service",
    "auth",
)
_MAX_JOB_BYTES = 1024 * 1024
_FILTER_FIELDS = ("market", "domain", "cadence", "state", "q")
_ERROR_TYPES = {
    "budget": QueryBudgetError,
    "validation": QueryValidationError,
    "cursor_mismatch": CursorMismatch,
    "invalid_cursor": InvalidCursor,
    "projection": RuntimeProjectionError,
    "unavailable": QueryServiceUnavailable,
}
_WORKER_CATALOG: CatalogService | None = None


def _unavailable() -> QueryServiceUnavailable:
    return QueryServiceUnavailable("catalog executor is unavailable")


def catalog_worker_count() -> int:
    raw = os.environ.get("TRADINGDATAS_CATALOG_WORKERS", "0")
    if raw not in {"0", "1", "2"}:
        raise _unavailable()
    return int(raw)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity_for_catalog(catalog: CatalogService) -> dict[str, object]:
    from dataset_registry import (
        load_runtime_dataset_registry,
        runtime_dataset_registry_path,
    )
    from runtime_paths import marketdata_sqlite_path

    if type(catalog) is not CatalogService or Path(__file__).parent != _ROOT:
        raise _unavailable()
    modules = []
    for name in (*_RUNTIME_MODULES, "catalog_executor"):
        module = importlib.import_module(name)
        path = Path(module.__file__)
        expected = _ROOT / (name.replace(".", "/") + ".py")
        if path != expected or path.resolve(strict=True) != expected:
            raise _unavailable()
        modules.append((name, str(path), _file_hash(path)))
    registry_path = runtime_dataset_registry_path()
    before = _file_hash(registry_path)
    loaded = load_runtime_dataset_registry()
    if (
        catalog._registry.datasets != loaded.datasets
        or catalog._registry.query_defaults != loaded.query_defaults
        or before != _file_hash(registry_path)
    ):
        raise _unavailable()
    db_path = catalog._db_path
    if db_path != marketdata_sqlite_path() or db_path.resolve(strict=True) != db_path:
        raise _unavailable()
    return {
        "root": str(_ROOT),
        "modules": tuple(modules),
        "registry_path": str(registry_path),
        "registry_sha256": before,
        "database_path": str(db_path),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cursor_signer_sha256": hashlib.sha256(
            catalog._cursor_codec._signing_key
        ).hexdigest(),
    }


def _initialize_worker(identity: dict[str, object], barrier=None) -> None:
    global _WORKER_CATALOG
    _WORKER_CATALOG = None
    try:
        from data_plane_runtime import build_data_plane_runtime

        catalog = build_data_plane_runtime().catalog
        if _identity_for_catalog(catalog) != identity:
            raise _unavailable()
        if barrier is not None:
            barrier.wait()
        _WORKER_CATALOG = catalog
    except BaseException:  # noqa: BLE001 - bootstrap failures must not cross IPC.
        # Never transmit or log bootstrap exception text or a traceback.
        if barrier is not None:
            try:
                barrier.abort()
            except Exception:  # noqa: BLE001, S110 - never log bootstrap secrets.
                pass


def _worker_ready() -> bool:
    return _WORKER_CATALOG is not None


def _new_pool(workers: int, identity: dict[str, object]) -> ProcessPoolExecutor:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(workers, timeout=20)
    pool = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(identity, barrier),
    )
    deadline = time.monotonic() + 40
    try:
        probes = [pool.submit(_worker_ready) for _ in range(workers)]
        if not all(
            probe.result(timeout=max(0, deadline - time.monotonic())) is True
            for probe in probes
        ):
            raise _unavailable()
    except BaseException:  # noqa: BLE001 - reap unpublished children on interruption.
        _discard_starting_pool(pool, workers)
        raise _unavailable() from None
    return pool


def _discard_starting_pool(pool, workers: int) -> None:
    """Reap only this not-yet-published pool; never called for customer jobs.

    Python 3.12 has no public executor terminate_workers API. Its _processes
    mapping is used solely to retrieve the owned multiprocessing.Process
    objects; no PID search or signaling unrelated services is permitted.
    """
    processes = tuple((pool._processes or {}).values())
    if len(processes) > workers:
        raise _unavailable()
    for process in processes:
        if process.is_alive():
            process.terminate()
    deadline = time.monotonic() + 2
    for process in processes:
        process.join(timeout=max(0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.kill()
    deadline = time.monotonic() + 2
    for process in processes:
        process.join(timeout=max(0, deadline - time.monotonic()))
    pool.shutdown(wait=True, cancel_futures=False)


def _pack_job(*, access, filters, limit, cursor, now, request_id) -> bytes:
    if not isinstance(access, QueryAccessContext) or not isinstance(
        filters, CatalogFilters
    ):
        raise QueryValidationError("catalog request is invalid")
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise QueryValidationError("catalog clock is invalid")
    value = {
        "access": {
            "tenant_id": access.tenant_id,
            "scopes": list(access.scopes),
            "allowed_dataset_ids": list(access.allowed_dataset_ids),
            "policy_id": access.policy_id,
        },
        "filters": {name: getattr(filters, name) for name in _FILTER_FIELDS},
        "limit": limit,
        "cursor": cursor,
        "now": now.isoformat(),
        "request_id": request_id,
    }
    try:
        raw = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise QueryValidationError("catalog request is invalid") from None
    if len(raw) > _MAX_JOB_BYTES:
        raise QueryBudgetError("catalog request exceeds executor budget")
    return raw


def _unpack_job(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > _MAX_JOB_BYTES:
        raise QueryBudgetError("catalog request exceeds executor budget")
    job = json.loads(raw)
    if type(job) is not dict or set(job) != {
        "access",
        "filters",
        "limit",
        "cursor",
        "now",
        "request_id",
    }:
        raise QueryValidationError("catalog request is invalid")
    grants = job["access"]
    if type(grants) is not dict or set(grants) != {
        "tenant_id",
        "scopes",
        "allowed_dataset_ids",
        "policy_id",
    }:
        raise QueryValidationError("catalog grants are invalid")
    if (
        type(grants["scopes"]) is not list
        or type(grants["allowed_dataset_ids"]) is not list
    ):
        raise QueryValidationError("catalog grants are invalid")
    access = QueryAccessContext.from_grants(
        tenant_id=grants["tenant_id"],
        scopes=tuple(grants["scopes"]),
        allowed_dataset_ids=tuple(grants["allowed_dataset_ids"]),
    )
    if access.policy_id != grants["policy_id"]:
        raise QueryValidationError("catalog policy is invalid")
    filters = job["filters"]
    if type(filters) is not dict or set(filters) != set(_FILTER_FIELDS):
        raise QueryValidationError("catalog filters are invalid")
    return {
        "access": access,
        "filters": CatalogFilters(**filters),
        "limit": job["limit"],
        "cursor": job["cursor"],
        "now": datetime.fromisoformat(job["now"]),
        "request_id": job["request_id"],
    }


def _worker_call(raw: bytes) -> tuple[str, bytes]:
    try:
        if _WORKER_CATALOG is None:
            return "unavailable", b""
        response = _WORKER_CATALOG.list_datasets(**_unpack_job(raw))
        encoded = json.dumps(
            response, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > _WORKER_CATALOG._registry.query_defaults.max_response_bytes:
            return "budget", b""
        return "ok", encoded
    except BaseException as exc:  # noqa: BLE001 - only a fixed error enum may cross IPC.
        for code, error_type in _ERROR_TYPES.items():
            if isinstance(exc, error_type):
                return code, b""
        return "unavailable", b""


def _decode_reply(reply, byte_limit: int) -> dict[str, object]:
    if type(reply) is not tuple or len(reply) != 2:
        raise _unavailable()
    code, raw = reply
    if type(code) is not str or type(raw) is not bytes:
        raise _unavailable()
    if code in _ERROR_TYPES and raw == b"":
        raise _ERROR_TYPES[code]("catalog request failed")
    if code != "ok" or len(raw) > byte_limit:
        raise _unavailable()
    try:
        payload = json.loads(raw, parse_constant=_reject_json_constant)
    except (UnicodeError, ValueError):
        raise _unavailable() from None
    if type(payload) is not dict:
        raise _unavailable()
    return payload


def _reject_json_constant(_value: str):
    raise ValueError("non-finite JSON")


class _ExecutorState:
    def __init__(self):
        self._condition = threading.Condition()
        self._pool_lock = threading.Lock()
        self._pool = None
        self._catalog = None
        self._workers = None
        self._active = 0
        self._closed = False
        self._broken = False

    def _bind(self, catalog, workers):
        if self._closed or self._broken:
            raise _unavailable()
        if self._catalog is None:
            self._catalog, self._workers = catalog, workers
        if self._catalog is not catalog or self._workers != workers:
            raise _unavailable()

    def _get_pool(self, catalog, workers):
        with self._pool_lock:
            with self._condition:
                if self._closed or self._broken:
                    raise _unavailable()
            if self._pool is None:
                try:
                    self._pool = _new_pool(workers, _identity_for_catalog(catalog))
                except Exception:  # noqa: BLE001 - no bootstrap detail reaches HTTP.
                    with self._condition:
                        self._broken = True
                    raise _unavailable() from None
            return self._pool

    def initialize(self, catalog, workers):
        with self._condition:
            self._bind(catalog, workers)
        self._get_pool(catalog, workers)

    def _fail_pool(self, pool):
        with self._condition:
            self._broken = True
        # A failed future may become done before the executor manager reaps
        # sibling processes. Retain all caller admission until that completes.
        with self._pool_lock:
            if self._pool is pool:
                pool.shutdown(wait=True, cancel_futures=False)
                self._pool = None

    def execute(self, catalog, workers, kwargs):
        with self._condition:
            self._bind(catalog, workers)
            if self._pool is None or self._active >= workers:
                raise _unavailable()
            self._active += 1
            pool = self._pool
        future = None
        try:
            payload = _pack_job(**kwargs)
            try:
                future = pool.submit(_worker_call, payload)
                reply = future.result()  # No deadline, replay or inline fallback.
            except Exception:  # noqa: BLE001 - IPC failure is a fixed 503.
                self._fail_pool(pool)
                raise _unavailable() from None
            return _decode_reply(
                reply, catalog._registry.query_defaults.max_response_bytes
            )
        finally:
            # An interrupted caller still owns its admission until work finishes.
            while future is not None and not future.done():
                try:
                    future.result()
                except BaseException:  # noqa: BLE001, S112 - hold admission until completion.
                    continue
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def shutdown(self):
        with self._condition:
            self._closed = True
            while self._active:
                self._condition.wait()
        with self._pool_lock:
            if self._pool is not None:
                self._pool.shutdown(wait=True, cancel_futures=False)
                self._pool = None


_STATE = _ExecutorState()


def initialize_catalog_executor(catalog: CatalogService) -> None:
    workers = catalog_worker_count()
    if workers:
        _STATE.initialize(catalog, workers)


def execute_catalog(
    catalog: CatalogService,
    *,
    access: QueryAccessContext,
    filters: CatalogFilters,
    limit: int,
    cursor: str | None,
    now: datetime,
    request_id: str,
) -> dict[str, object]:
    workers = catalog_worker_count()
    kwargs = {
        "access": access,
        "filters": filters,
        "limit": limit,
        "cursor": cursor,
        "now": now,
        "request_id": request_id,
    }
    if workers == 0:
        return catalog.list_datasets(**kwargs)
    return _STATE.execute(catalog, workers, kwargs)


def shutdown_catalog_executor() -> None:
    _STATE.shutdown()
