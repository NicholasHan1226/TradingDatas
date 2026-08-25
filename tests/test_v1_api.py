from __future__ import annotations

import base64
import builtins
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import importlib
import importlib.util
import json
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable
import uuid

import pytest

import api_server
import auth
from catalog_service import CatalogFilters
from dataset_registry import DatasetRegistry, load_dataset_registry
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryValidationError,
)
from query_cursor import (
    CursorClaims,
    CursorConfigurationError,
    CursorExpectation,
    CursorMismatch,
    InvalidCursor,
    SignedCursorCodec,
)
from query_service import (
    QueryAccessDenied,
    QueryDatasetNotFound,
    QueryServiceUnavailable,
)
from storage.receipt_projection import RuntimeProjectionError


# This module runs an in-process HTTP server, raw sockets, timeout paths, and
# polling loops. Keep its contract coverage in the nightly full suite: xdist
# workers otherwise contend for process-global auth/runtime state.
pytestmark = pytest.mark.slow


SIGNING_KEY = b"phase2-test-signing-key-32-bytes-minimum"
JWT_HS256_SECRET = "tradingdatas-hs256-test-secret-at-least-32-bytes"
GOOD_QUERY = {"dataset_id": "cn.equity.daily", "schema_major": 1}
V1_SCOPES = ("external_read", "read", "internal", "full", "*")


def _token_hash(token: str) -> str:
    return auth._hash_token(token)  # noqa: SLF001 - exercise real middleware token lookup


def _hs256_jwt(*, secret: str = JWT_HS256_SECRET) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "tenant-jwt",
        "iss": "tradingdatas-tests",
        "exp": int(time.time()) + 300,
        "scopes": ["external_read"],
    }
    segments = [
        base64.urlsafe_b64encode(
            json.dumps(item, separators=(",", ":")).encode("utf-8")
        )
        .rstrip(b"=")
        .decode("ascii")
        for item in (header, payload)
    ]
    signing_input = ".".join(segments)
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    segments.append(base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"))
    return ".".join(segments)


def _token_record(
    token: str, tenant_id: str, scopes: list[str], **extra: Any
) -> tuple[str, dict[str, Any]]:
    return (
        _token_hash(token),
        {
            "tenant_id": tenant_id,
            "tier": "internal",
            "scopes": scopes,
            "auth_method": "token_hash",
            **extra,
        },
    )


def _registry_with_limits(
    *,
    max_request_bytes: int | None = None,
    max_response_bytes: int | None = None,
    max_page_size: int | None = None,
) -> DatasetRegistry:
    registry = load_dataset_registry()
    overrides: dict[str, int] = {}
    if max_request_bytes is not None:
        overrides["max_request_bytes"] = max_request_bytes
    if max_response_bytes is not None:
        overrides["max_response_bytes"] = max_response_bytes
    if max_page_size is not None:
        overrides["max_page_size"] = max_page_size
    defaults = replace(registry.query_defaults, **overrides)
    return DatasetRegistry(registry.datasets, query_defaults=defaults)


def test_account_category_allowlist_maps_only_server_owned_registry_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_server, "auth", auth)
    registry = load_dataset_registry()
    legacy = api_server._access_context_from_account(  # noqa: SLF001
        {"tenant_id": "legacy", "scopes": ["read"]},
        registry,
    )
    assert legacy.scopes == ("read",)
    assert legacy.allowed_dataset_ids == ()

    a_share = api_server._access_context_from_account(  # noqa: SLF001
        {
            "tenant_id": "a-share-only",
            "scopes": ["read", "market_data"],
            "data_categories": ["a_share"],
        },
        registry,
    )
    assert a_share.scopes == ()
    assert a_share.allowed_dataset_ids
    assert all(dataset_id.startswith("cn.") for dataset_id in a_share.allowed_dataset_ids)
    assert "global.news.flash" not in a_share.allowed_dataset_ids

    news = api_server._access_context_from_account(  # noqa: SLF001
        {
            "tenant_id": "news-only",
            "scopes": ["read"],
            "data_categories": ["news"],
        },
        registry,
    )
    assert news.allowed_dataset_ids == (
        "cn.dataset.news",
        "cn.news.flash",
        "global.news.flash",
    )

    crypto_registry = load_dataset_registry(
        Path("config/crypto_binance_canary_registry.v1.yaml").absolute()
    )
    crypto = api_server._access_context_from_account(  # noqa: SLF001
        {
            "tenant_id": "crypto-only",
            "scopes": ["read"],
            "data_categories": ["crypto"],
        },
        crypto_registry,
    )
    assert crypto.allowed_dataset_ids
    assert all(dataset_id.startswith("crypto.") for dataset_id in crypto.allowed_dataset_ids)

    empty = api_server._access_context_from_account(  # noqa: SLF001
        {
            "tenant_id": "no-data",
            "scopes": ["read"],
            "data_categories": [],
        },
        registry,
    )
    assert empty.scopes == ()
    assert empty.allowed_dataset_ids == ()


def test_news_category_takes_precedence_over_market() -> None:
    class _Dataset:
        dataset_id = "cn.news.flash"
        market = "CN"
        domain = "provider_data"

    assert api_server._dataset_data_category(_Dataset()) == "news"  # noqa: SLF001


def _success_query_response(
    request_id: str, *, state: str = "success"
) -> dict[str, object]:
    degraded = state not in {"success", "empty"}
    return {
        "api_version": "v1",
        "catalog_version": "v1-test-contract",
        "request_id": request_id,
        "dataset_id": "cn.equity.daily",
        "schema_version": "1.0.0",
        "data": [] if state != "success" else [{"symbol": "600000.SH"}],
        "next_cursor": None,
        "metadata": {
            "state": "ready" if state == "success" else state,
            "runtime_state": state,
            "degraded": degraded,
            "freshness": {
                "state": "fresh" if state == "success" else state,
                "stale": state == "stale",
                "sla_seconds": 1,
            },
            "quality": {
                "state": "valid" if not degraded else "degraded",
                "valid": not degraded,
                "evidence": [],
            },
            "lineage": {
                "state": "complete",
                "complete": True,
                "provider_neutral": True,
                "authority": "sqlite_ingest_receipts",
                "dataset_id": "cn.equity.daily",
                "providers": ["tushare"],
            },
            "receipt_id": "receipt-1",
            "data_through": "2026-07-16T00:00:00+08:00",
            "observed_at": "2026-07-16T00:00:00+08:00",
            "requested_as_of": None,
            "resolved_as_of": None,
            "reasons": [],
        },
    }


class _FakeCatalogService:
    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self.calls: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.decoder: Callable[[str, datetime], None] | None = None

    def list_datasets(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        cursor = kwargs.get("cursor")
        now = kwargs.get("now")
        if cursor is not None and self.decoder is not None:
            assert isinstance(cursor, str)
            assert isinstance(now, datetime)
            self.decoder(cursor, now)
        request_id = kwargs["request_id"]
        assert isinstance(request_id, str)
        return {
            "api_version": "v1",
            "catalog_version": "v1-test-contract",
            "request_id": request_id,
            "data": [{"dataset_id": "cn.equity.daily"}],
            "next_cursor": None,
        }


class _FakeQueryService:
    def __init__(self, registry: DatasetRegistry) -> None:
        self._registry = registry
        self.calls: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.decoder: Callable[[str, datetime], None] | None = None
        self.state = "success"
        self.response_override: dict[str, object] | None = None
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def execute(self, request: object, **kwargs: object) -> dict[str, object]:
        self.calls.append({"request": request, **kwargs})
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        if self.error is not None:
            raise self.error
        cursor = getattr(request, "cursor", None)
        now = kwargs.get("now")
        if cursor is not None and self.decoder is not None:
            assert isinstance(cursor, str)
            assert isinstance(now, datetime)
            self.decoder(cursor, now)
        request_id = kwargs["request_id"]
        assert isinstance(request_id, str)
        if self.response_override is not None:
            response = dict(self.response_override)
            response["request_id"] = request_id
            return response
        return _success_query_response(request_id, state=self.state)


class _Harness:
    def __init__(
        self, base_url: str, catalog: _FakeCatalogService, query: _FakeQueryService
    ) -> None:
        self.base_url = base_url
        self.host = "127.0.0.1"
        self.port = int(base_url.rsplit(":", 1)[1])
        self.catalog = catalog
        self.query = query
        self.last_response_headers: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        target: str,
        *,
        body: bytes = b"",
        token: str | None = "full-token",
        headers: list[tuple[str, str]] | None = None,
    ) -> tuple[int, dict[str, Any] | None, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        connection.putrequest(method, target)
        supplied = list(headers or [])
        if token is not None and not any(
            name.casefold() in {"authorization", "x-api-key"} for name, _ in supplied
        ):
            supplied.append(("Authorization", f"Bearer {token}"))
        for name, value in supplied:
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        raw = response.read()
        self.last_response_headers = response.getheaders()
        response_headers = {
            name.lower(): value for name, value in self.last_response_headers
        }
        status = response.status
        connection.close()
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        else:
            payload = None
        return status, payload, response_headers, raw


@pytest.fixture
def v1_server(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    registry = _registry_with_limits()
    catalog = _FakeCatalogService(registry)
    query = _FakeQueryService(registry)
    tokens = dict(
        [
            _token_record("full-token", "tenant-full", ["full"]),
            _token_record("market-token", "tenant-market", ["market_data"]),
            _token_record("events-token", "tenant-events", ["events"]),
            _token_record("external-token", "tenant-external", ["external_read"]),
            _token_record("read-token", "tenant-read", ["read"]),
            _token_record("star-token", "tenant-star", ["*"]),
            _token_record("health-token", "tenant-health", ["health"]),
            _token_record("status-token", "tenant-status", ["status"]),
            _token_record("tushare-token", "tenant-tushare", ["tushare"]),
            _token_record(
                "fundamentals-token", "tenant-fundamentals", ["fundamentals"]
            ),
            _token_record("tenant-a-token", "tenant-a", ["external_read"]),
            _token_record("tenant-b-token", "tenant-b", ["external_read"]),
            _token_record(
                "mixed-finite-token",
                "tenant-mixed",
                ["external_read"],
                max_concurrent=1,
            ),
            _token_record(
                "mixed-unlimited-token",
                "tenant-mixed",
                ["external_read"],
                max_concurrent=0,
            ),
        ]
    )
    monkeypatch.setattr(auth, "_TOKEN_HASHES", tokens)
    monkeypatch.setattr(auth, "LOCALHOST_BYPASS", False)
    monkeypatch.setattr(auth, "RATE_LIMITS", {**auth.RATE_LIMITS, "internal": None})
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": None}
    )
    monkeypatch.setattr(auth, "_REQUEST_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_DAILY_REQUEST_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_ACTIVE_REQUESTS", {})
    # Reset the pre-auth limiter too: a prior file in the same worker process
    # (e.g. test_auth_security's authenticate storm) otherwise leaves this host
    # rate-limited before any handler logic runs.
    monkeypatch.setattr(auth, "_PREAUTH_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_DEDUP_CACHE", auth.OrderedDict())
    monkeypatch.setattr(api_server, "auth", auth)
    monkeypatch.setattr(
        api_server, "_build_v1_services", lambda: (catalog, query), raising=False
    )

    server = api_server.TradingDatasHTTPServer(
        ("127.0.0.1", 0),
        api_server.Handler,
        request_timeout=5,
        max_threads=8,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield _Harness(base_url, catalog, query)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _json_body(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _post_headers(
    body: bytes, *, content_type: str = "application/json"
) -> list[tuple[str, str]]:
    return [("Content-Type", content_type), ("Content-Length", str(len(body)))]


def _error_shape(payload: dict[str, Any], expected_code: str) -> None:
    uuid.UUID(payload["request_id"], version=4)
    assert payload == {
        "api_version": "v1",
        "request_id": payload["request_id"],
        "error": {
            "code": expected_code,
            "message": {
                "invalid_request": "request is invalid",
                "unauthenticated": "authentication required",
                "forbidden": "request is forbidden",
                "not_found": "resource not found",
                "method_not_allowed": "method is not allowed",
                "cursor_mismatch": "cursor does not match request",
                "budget_exceeded": "request exceeds allowed budget",
                "unsupported_media_type": "unsupported media type",
                "rate_limited": "rate limit exceeded",
                "service_unavailable": "service temporarily unavailable",
                "internal_error": "internal error",
            }[expected_code],
            "retryable": expected_code in {"rate_limited", "service_unavailable"},
        },
    }


def _signed_deep_token(raw_payload: bytes) -> str:
    payload_segment = base64.urlsafe_b64encode(raw_payload).decode("ascii").rstrip("=")
    signature = hmac.new(SIGNING_KEY, raw_payload, hashlib.sha256).digest()
    signature_segment = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload_segment}.{signature_segment}"


def _deep_decoder(token: str, now: datetime) -> None:
    SignedCursorCodec(SIGNING_KEY).decode(
        token,
        expected=CursorExpectation(
            kind="catalog",
            catalog_version="v1-test-contract",
            dataset_id=None,
            schema_major=None,
            query_hash="query",
            policy_id="policy",
            receipt_watermark="receipt",
        ),
        now=now,
    )


def _raw_http_request(
    harness: _Harness,
    request: bytes,
    *,
    shutdown_write: bool = True,
) -> tuple[int, bytes]:
    with socket.create_connection((harness.host, harness.port), timeout=5) as client:
        client.settimeout(5)
        client.sendall(request)
        if shutdown_write:
            client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65_536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    status_line = raw.split(b"\r\n", 1)[0]
    return int(status_line.split(b" ", 2)[1]), raw


def test_v1_group_01_fixed_route_set(v1_server: _Harness) -> None:
    status, payload, _headers, _raw = v1_server.request("GET", "/v1/catalog")
    assert status == 200
    assert payload is not None and payload["api_version"] == "v1"

    body = _json_body(GOOD_QUERY)
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=_post_headers(body)
    )
    assert status == 200
    assert payload is not None and payload["dataset_id"] == "cn.equity.daily"

    for provider_path in ("/v1/tushare", "/v1/provider/tushare", "/v1/cn.equity.daily"):
        status, payload, _headers, _raw = v1_server.request("GET", provider_path)
        assert status == 404
        assert payload is not None
        _error_shape(payload, "not_found")


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "allow"),
    [
        ("GET", "/v1/catalog/", 404, None),
        ("GET", "/V1/catalog", 404, None),
        ("POST", "/v1/catalog", 405, "GET, OPTIONS"),
        ("HEAD", "/v1/catalog", 405, "GET, OPTIONS"),
        ("GET", "/v1/query", 405, "POST, OPTIONS"),
        ("PUT", "/v1/query", 405, "POST, OPTIONS"),
        ("OPTIONS", "/v1/catalog", 204, None),
        ("OPTIONS", "/v1/query", 204, None),
        ("OPTIONS", "/v1/unknown", 404, None),
    ],
)
def test_v1_group_02_exact_path_method_and_options(
    v1_server: _Harness,
    method: str,
    path: str,
    expected_status: int,
    allow: str | None,
) -> None:
    status, payload, headers, raw = v1_server.request(method, path)
    assert status == expected_status
    if expected_status == 204 or method == "HEAD":
        assert raw == b""
    else:
        assert payload is not None
    if allow is not None:
        assert headers["allow"] == allow


def test_admin_api_options_preflight_does_not_require_credentials(
    v1_server: _Harness,
) -> None:
    status, payload, headers, raw = v1_server.request(
        "OPTIONS",
        "/admin/api/tokens",
        token=None,
        headers=[
            ("Origin", "https://tradingdatas-admin.pages.dev"),
            ("Access-Control-Request-Method", "GET"),
            ("Access-Control-Request-Headers", "authorization"),
        ],
    )

    assert status == 204
    assert payload is None
    assert raw == b""
    assert headers["access-control-allow-origin"] == "*"
    assert headers["access-control-allow-methods"] == "GET, POST, PATCH, DELETE, OPTIONS"
    assert headers["access-control-allow-headers"] == "Authorization, Content-Type, X-API-Key"


def test_admin_api_unauthenticated_response_has_one_cors_origin_header(
    v1_server: _Harness,
) -> None:
    status, payload, headers, _raw = v1_server.request(
        "GET", "/admin/api/tokens", token=None
    )

    assert status == 401
    assert payload is not None
    assert headers["access-control-allow-origin"] == "*"
    assert [
        value
        for name, value in v1_server.last_response_headers
        if name.casefold() == "access-control-allow-origin"
    ] == ["*"]


@pytest.mark.parametrize(
    ("method", "path", "allow"),
    [
        ("TRACE", "/v1/catalog", "GET, OPTIONS"),
        ("CONNECT", "/v1/query", "POST, OPTIONS"),
        ("BREW", "/v1/catalog", "GET, OPTIONS"),
    ],
)
def test_v1_group_02_any_unsupported_method_is_bounded_405(
    v1_server: _Harness,
    method: str,
    path: str,
    allow: str,
) -> None:
    status, payload, headers, _raw = v1_server.request(method, path)
    assert status == 405
    assert headers["allow"] == allow
    assert payload is not None
    _error_shape(payload, "method_not_allowed")


def test_v1_group_02_unknown_path_precedes_arbitrary_method(
    v1_server: _Harness,
) -> None:
    status, payload, _headers, _raw = v1_server.request("BREW", "/v1/unknown")
    assert status == 404
    assert payload is not None
    _error_shape(payload, "not_found")


@pytest.mark.parametrize("method", ["HEAD", "PUT", "PATCH", "DELETE", "BREW"])
def test_v1_group_02_retired_routes_are_bounded_404(
    v1_server: _Harness,
    method: str,
) -> None:
    status, payload, _headers, _raw = v1_server.request(method, "/legacy-unknown")
    assert status == 404
    if method == "HEAD":
        assert payload is None
    else:
        assert payload is not None
        _error_shape(payload, "not_found")


@pytest.mark.parametrize(
    "headers",
    [
        [("Transfer-Encoding", "chunked")],
        [("Content-Length", "1")],
    ],
)
def test_v1_group_03_catalog_rejects_body_framing_and_closes(
    v1_server: _Harness,
    headers: list[tuple[str, str]],
) -> None:
    status, payload, response_headers, _raw = v1_server.request(
        "GET", "/v1/catalog", body=b"x", headers=headers
    )
    assert status == 400
    assert response_headers.get("connection", "").casefold() == "close"
    assert payload is not None
    _error_shape(payload, "invalid_request")


def test_v1_group_03_catalog_rejection_does_not_parse_pipelined_request(
    v1_server: _Harness,
) -> None:
    status, raw = _raw_http_request(
        v1_server,
        b"GET /v1/catalog HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer full-token\r\n"
        b"Content-Length: 1\r\n\r\n"
        b"x"
        b"GET /v1/catalog HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer full-token\r\n\r\n",
    )
    assert status == 400
    assert raw.count(b"HTTP/1.") == 1
    assert b"Connection: close" in raw


@pytest.mark.parametrize(
    "query",
    [
        "unknown=x",
        "market=CN&market=US",
        "=x",
        "%ZZ=x",
        "%FF=x",
    ],
)
def test_v1_group_04_catalog_query_parser_is_strict(
    v1_server: _Harness, query: str
) -> None:
    status, payload, _headers, _raw = v1_server.request("GET", f"/v1/catalog?{query}")
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        ("1", 200),
        ("500", 200),
        ("0", 400),
        ("+1", 400),
        ("-1", 400),
        ("01", 400),
        ("%201", 400),
        ("1.0", 400),
        ("1e0", 400),
        ("%D9%A1", 400),
        ("true", 400),
        ("501", 413),
    ],
)
def test_v1_group_05_catalog_canonical_limit(
    v1_server: _Harness, limit: str, expected: int
) -> None:
    status, payload, _headers, _raw = v1_server.request(
        "GET", f"/v1/catalog?limit={limit}&market=CN"
    )
    assert status == expected
    assert payload is not None
    if status == 200:
        call = v1_server.catalog.calls[-1]
        assert call["limit"] == int(limit)
        assert call["filters"] == CatalogFilters(market="CN")
    else:
        _error_shape(payload, "budget_exceeded" if status == 413 else "invalid_request")


@pytest.mark.parametrize("target", ["/v1/query?x=1", "/v1/query/"])
def test_v1_group_06_query_target_and_body_are_exact(
    v1_server: _Harness, target: str
) -> None:
    body = _json_body(GOOD_QUERY)
    status, payload, _headers, _raw = v1_server.request(
        "POST", target, body=body, headers=_post_headers(body)
    )
    assert status in {400, 404}
    assert payload is not None
    _error_shape(payload, "invalid_request" if "?" in target else "not_found")
    assert v1_server.query.calls == []


@pytest.mark.parametrize(
    ("content_type", "content_encoding", "extra", "expected"),
    [
        (None, None, [], 415),
        ("text/plain", None, [], 415),
        ("application/json; charset=latin1", None, [], 415),
        ("application/json; charset=utf-8; version=1", None, [], 400),
        ("application/json; charset=utf-8; charset=utf-8", None, [], 400),
        ("application/json", "gzip", [], 415),
        ("application/json", None, [("Content-Type", "application/json")], 400),
        ('APPLICATION/JSON; CHARSET="UTF-8"', None, [], 200),
    ],
)
def test_v1_group_07_media_type_is_strict(
    v1_server: _Harness,
    content_type: str | None,
    content_encoding: str | None,
    extra: list[tuple[str, str]],
    expected: int,
) -> None:
    body = _json_body(GOOD_QUERY)
    headers: list[tuple[str, str]] = [("Content-Length", str(len(body)))]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    headers.extend(extra)
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=headers
    )
    assert status == expected
    assert payload is not None
    if expected != 200:
        _error_shape(
            payload, "unsupported_media_type" if expected == 415 else "invalid_request"
        )


@pytest.mark.parametrize(
    ("raw_length", "transfer", "expected"),
    [
        (None, None, 400),
        ("", None, 400),
        ("+2", None, 400),
        ("-1", None, 400),
        ("01", None, 400),
        (" 1", None, 400),
        ("1.0", None, 400),
        ("184467440737095516160", None, 400),
        ("2", "chunked", 400),
    ],
)
def test_v1_group_08_framing_is_canonical(
    v1_server: _Harness,
    raw_length: str | None,
    transfer: str | None,
    expected: int,
) -> None:
    headers: list[tuple[str, str]] = [("Content-Type", "application/json")]
    if raw_length is not None:
        headers.append(("Content-Length", raw_length))
    if transfer is not None:
        headers.append(("Transfer-Encoding", transfer))
    status, payload, response_headers, _raw = v1_server.request(
        "POST", "/v1/query", body=b"{}", headers=headers
    )
    assert status == expected
    assert response_headers.get("connection", "").casefold() == "close"
    assert payload is not None
    _error_shape(payload, "invalid_request")


@pytest.mark.parametrize(
    "raw", [b"\xef\xbb\xbf{}", b"{\xff}", b'{"dataset_id":"\\ud800","schema_major":1}']
)
def test_v1_group_09_strict_utf8(v1_server: _Harness, raw: bytes) -> None:
    status, payload, _headers, response_raw = v1_server.request(
        "POST", "/v1/query", body=raw, headers=_post_headers(raw)
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")
    assert raw not in response_raw


@pytest.mark.parametrize(
    "raw",
    [
        b'{"dataset_id":"cn.equity.daily","dataset_id":"cn.equity.daily","schema_major":1}',
        b'{"dataset_id":"cn.equity.daily","schema_major":1,"filters":{"symbol":{"eq":"A","eq":"B"}}}',
    ],
)
def test_v1_group_10_recursive_duplicate_keys(v1_server: _Harness, raw: bytes) -> None:
    status, payload, _headers, _response_raw = v1_server.request(
        "POST", "/v1/query", body=raw, headers=_post_headers(raw)
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_v1_group_11_non_finite_json(v1_server: _Harness, constant: str) -> None:
    raw = f'{{"dataset_id":"cn.equity.daily","schema_major":1,"filters":{{"close":{constant}}}}}'.encode()
    status, payload, _headers, _response_raw = v1_server.request(
        "POST", "/v1/query", body=raw, headers=_post_headers(raw)
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")


def test_v1_group_11_valid_unicode_distinct_keys_and_finite_boundary(
    v1_server: _Harness,
) -> None:
    raw = (
        b'{"dataset_id":"cn.equity.daily","schema_major":1,"filters":'
        b'{"company":{"eq":"\xe6\xb5\xa6\xe5\x8f\x91\xe9\x93\xb6\xe8\xa1\x8c"},'
        b'"close":{"eq":1.7976931348623157e308}}}'
    )
    status, payload, _headers, _response_raw = v1_server.request(
        "POST",
        "/v1/query",
        body=raw,
        headers=_post_headers(raw),
    )
    assert status == 200
    assert payload is not None
    request = v1_server.query.calls[-1]["request"]
    assert request.filters["company"]["eq"] == "浦发银行"
    assert request.filters["close"]["eq"] == 1.7976931348623157e308


@pytest.mark.parametrize(
    "payload",
    [
        None,
        True,
        1,
        "x",
        [],
        {"schema_major": 1},
        {"dataset_id": "cn.equity.daily"},
        {"dataset_id": "cn.equity.daily", "schema_major": True},
        {"dataset_id": "cn.equity.daily", "schema_major": "1"},
        {"dataset_id": "cn.equity.daily", "schema_major": 1, "latest_partition": True},
        {"dataset_id": "cn.equity.daily", "schema_major": 1, "sql": "select 1"},
        {
            "dataset_id": "cn.equity.daily",
            "schema_major": 1,
            "provider_token": "secret",
        },
    ],
)
def test_v1_group_12_root_schema_and_types(
    v1_server: _Harness, payload: object
) -> None:
    body = _json_body(payload)
    status, response, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=_post_headers(body)
    )
    assert status == 400
    assert response is not None
    _error_shape(response, "invalid_request")


@pytest.mark.parametrize(
    "raw",
    [b"[" * 2_000 + b"0" + b"]" * 2_000, b'{"x":' * 2_000 + b"0" + b"}" * 2_000],
)
def test_v1_group_13_deep_json_is_bounded_and_server_survives(
    v1_server: _Harness, raw: bytes
) -> None:
    status, payload, _headers, _response_raw = v1_server.request(
        "POST", "/v1/query", body=raw, headers=_post_headers(raw)
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")
    follow_status, _follow_payload, _follow_headers, _follow_raw = v1_server.request(
        "GET", "/v1/catalog"
    )
    assert follow_status == 200


@pytest.mark.parametrize(
    "raw_payload",
    [
        b"[" * 2_000 + b"0" + b"]" * 2_000,
        b"[" + b'{"item":' * 2_000 + b"0" + b"}" * 2_000 + b"]",
    ],
)
def test_v1_group_14_deep_signed_cursor_maps_to_400(
    v1_server: _Harness, raw_payload: bytes
) -> None:
    token = _signed_deep_token(raw_payload)
    v1_server.catalog.decoder = _deep_decoder
    status, payload, _headers, raw = v1_server.request(
        "GET", f"/v1/catalog?cursor={token}"
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")
    assert token.encode() not in raw

    v1_server.query.decoder = _deep_decoder
    body = _json_body({**GOOD_QUERY, "cursor": token})
    status, payload, _headers, raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=_post_headers(body)
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")
    assert token.encode() not in raw


@pytest.mark.parametrize(
    ("error", "expected_status", "code"),
    [
        (QueryValidationError("raw-secret"), 400, "invalid_request"),
        (QueryBudgetError("raw-secret"), 413, "budget_exceeded"),
        (InvalidCursor("raw-secret"), 400, "invalid_request"),
        (CursorMismatch("raw-secret"), 409, "cursor_mismatch"),
        (QueryAccessDenied("raw-secret"), 403, "forbidden"),
        (QueryDatasetNotFound("raw-secret"), 404, "not_found"),
        (QueryServiceUnavailable("raw-secret"), 503, "service_unavailable"),
        (RuntimeProjectionError("raw-secret"), 503, "service_unavailable"),
        (CursorConfigurationError("raw-secret"), 503, "service_unavailable"),
        (RuntimeError("raw-secret"), 500, "internal_error"),
    ],
)
def test_v1_group_15_request_id_error_envelope_and_privacy(
    v1_server: _Harness,
    error: BaseException,
    expected_status: int,
    code: str,
) -> None:
    v1_server.query.error = error
    body = _json_body(GOOD_QUERY)
    status, payload, _headers, raw = v1_server.request(
        "POST",
        "/v1/query",
        body=body,
        headers=[*_post_headers(body), ("X-Request-ID", "attacker-controlled")],
    )
    assert status == expected_status
    assert payload is not None
    _error_shape(payload, code)
    assert payload["request_id"] != "attacker-controlled"
    assert b"raw-secret" not in raw


def test_v1_group_15_success_request_ids_are_unique_forwarded_and_logs_are_safe(
    v1_server: _Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_cursor = "cursor-secret-must-not-appear"
    caplog.set_level("INFO", logger="tradingdatas.api")

    first_status, first, _headers, _raw = v1_server.request(
        "GET",
        f"/v1/catalog?cursor={secret_cursor}&market=CN",
    )
    second_status, second, _headers, _raw = v1_server.request(
        "GET",
        "/v1/catalog?market=CN",
    )

    assert first_status == second_status == 200
    assert first is not None and second is not None
    uuid.UUID(first["request_id"], version=4)
    uuid.UUID(second["request_id"], version=4)
    assert first["request_id"] != second["request_id"]
    assert v1_server.catalog.calls[-2]["request_id"] == first["request_id"]
    assert v1_server.catalog.calls[-1]["request_id"] == second["request_id"]
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_cursor not in rendered_logs
    assert "cursor=" not in rendered_logs


@pytest.mark.parametrize(
    ("token", "headers"),
    [
        (None, []),
        ("invalid", []),
        (None, [("Authorization", "Malformed")]),
        (None, [("Authorization", "Bearer full-token"), ("X-API-Key", "full-token")]),
        (
            None,
            [
                ("Authorization", "Bearer full-token"),
                ("Authorization", "Bearer full-token"),
            ],
        ),
        (None, [("Authorization", ""), ("X-Forwarded-For", "203.0.113.9")]),
    ],
)
def test_v1_group_16_real_auth_rejects_missing_invalid_and_ambiguous(
    v1_server: _Harness,
    token: str | None,
    headers: list[tuple[str, str]],
) -> None:
    status, payload, _response_headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token=token, headers=headers
    )
    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")


@pytest.mark.parametrize("token", ["W10.e30.AA", "e30.W10.AA"])
def test_v1_group_16_malformed_jwt_object_shape_is_bounded_401(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    monkeypatch.setattr(auth, "JWT_VERIFY_KEY", JWT_HS256_SECRET)
    monkeypatch.setattr(auth, "JWT_ISSUER", "tradingdatas-tests")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256", raising=False)

    status, payload, _headers, raw = v1_server.request(
        "GET",
        "/v1/catalog",
        token=token,
    )

    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")
    assert token.encode("ascii") not in raw


@pytest.mark.parametrize(
    ("configured_algorithm", "expected_status"),
    [("", 401), ("RS256", 401), ("HS256", 200)],
)
def test_v1_group_16_jwt_algorithm_is_bound_by_server_policy(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    configured_algorithm: str,
    expected_status: int,
) -> None:
    token = _hs256_jwt()
    monkeypatch.setattr(auth, "JWT_VERIFY_KEY", JWT_HS256_SECRET)
    monkeypatch.setattr(auth, "JWT_ISSUER", "tradingdatas-tests")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", configured_algorithm, raising=False)

    status, payload, _headers, raw = v1_server.request(
        "GET",
        "/v1/catalog",
        token=token,
    )

    assert status == expected_status
    assert payload is not None
    if expected_status == 401:
        _error_shape(payload, "unauthenticated")
    else:
        assert payload["api_version"] == "v1"
    assert token.encode("ascii") not in raw
    assert JWT_HS256_SECRET.encode("ascii") not in raw


@pytest.mark.parametrize(
    "token",
    [
        "external-token",
        "read-token",
        "full-token",
        "star-token",
    ],
)
def test_v1_group_17_endpoint_scope_positive_matrix(
    v1_server: _Harness, token: str
) -> None:
    status, payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token=token
    )
    assert status == 200
    assert payload is not None


@pytest.mark.parametrize(
    "token",
    [
        "health-token",
        "status-token",
        "tushare-token",
        "fundamentals-token",
        "market-token",
        "events-token",
    ],
)
def test_v1_group_17_endpoint_scope_negative_matrix(
    v1_server: _Harness, token: str
) -> None:
    status, payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token=token
    )
    assert status == 403
    assert payload is not None
    _error_shape(payload, "forbidden")


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (QueryDatasetNotFound("table/column/rowid unavailable"), 404),
        (QueryServiceUnavailable("inspection failed"), 503),
        (RuntimeProjectionError("projection failed"), 503),
    ],
)
def test_v1_group_18_resource_404_503_boundary(
    v1_server: _Harness, error: BaseException, expected_status: int
) -> None:
    v1_server.query.error = error
    body = _json_body(GOOD_QUERY)
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=_post_headers(body)
    )
    assert status == expected_status
    assert payload is not None
    _error_shape(
        payload, "not_found" if expected_status == 404 else "service_unavailable"
    )


def test_v1_group_19_tenant_context_ignores_account_policy_and_grants(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_authenticate = auth.authenticate

    def inject_untrusted_fields(headers: Any, client_host: str) -> dict[str, Any]:
        account = dict(real_authenticate(headers, client_host))
        account["policy_id"] = "attacker-policy"
        account["allowed_dataset_ids"] = ["cn.secret.dataset"]
        return account

    monkeypatch.setattr(auth, "authenticate", inject_untrusted_fields)
    status, _payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token="tenant-a-token"
    )
    assert status == 200
    access = v1_server.catalog.calls[-1]["access"]
    assert isinstance(access, QueryAccessContext)
    assert access.tenant_id == "tenant-a"
    assert access.allowed_dataset_ids == ()
    assert access.policy_id != "attacker-policy"


def test_v1_group_19_cross_tenant_cursor_mismatch_is_category_only(
    v1_server: _Harness,
) -> None:
    v1_server.query.error = CursorMismatch("expected=tenant-a actual=tenant-b")
    body = _json_body({**GOOD_QUERY, "cursor": "opaque.valid.cursor"})
    status, payload, _headers, raw = v1_server.request(
        "POST",
        "/v1/query",
        body=body,
        token="tenant-b-token",
        headers=_post_headers(body),
    )
    assert status == 409
    assert payload is not None
    _error_shape(payload, "cursor_mismatch")
    assert b"tenant-a" not in raw and b"tenant-b" not in raw


def test_v1_group_20_v1_bypasses_legacy_cache_and_dedup(
    v1_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy cache/dedup must not be used")

    monkeypatch.setattr(auth, "request_fingerprint", forbidden)
    monkeypatch.setattr(auth, "get_cached_response", forbidden)
    monkeypatch.setattr(auth, "store_cached_response", forbidden)
    for token in ("tenant-a-token", "tenant-a-token", "tenant-b-token"):
        status, _payload, _headers, _raw = v1_server.request(
            "GET", "/v1/catalog", token=token
        )
        assert status == 200
    assert len(v1_server.catalog.calls) == 3


def test_v1_group_21_rate_limit_is_per_tenant(
    v1_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "RATE_LIMITS", {**auth.RATE_LIMITS, "internal": 1})
    first, _payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token="tenant-a-token"
    )
    second, payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token="tenant-a-token"
    )
    other, _payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token="tenant-b-token"
    )
    assert first == 200
    assert second == 429
    assert payload is not None
    _error_shape(payload, "rate_limited")
    assert other == 200


def test_v1_group_21_concurrency_claim_is_released_on_service_error(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    v1_server.query.error = QueryValidationError("bad")
    body = _json_body(GOOD_QUERY)
    for _ in range(2):
        status, _payload, _headers, _raw = v1_server.request(
            "POST",
            "/v1/query",
            body=body,
            token="tenant-a-token",
            headers=_post_headers(body),
        )
        assert status == 400
    deadline = time.monotonic() + 5
    while auth._ACTIVE_REQUESTS and time.monotonic() < deadline:
        time.sleep(0.01)
    assert auth._ACTIVE_REQUESTS == {}


def test_v1_group_21_unlimited_request_does_not_release_finite_same_tenant_claim(
    v1_server: _Harness,
) -> None:
    finite_account = {
        "tenant_id": "tenant-mixed",
        "tier": "internal",
        "max_concurrent": 1,
    }
    assert auth.claim_concurrency(finite_account) is True
    try:
        status, payload, _headers, _raw = v1_server.request(
            "GET",
            "/v1/catalog",
            token="mixed-unlimited-token",
        )
        assert status == 200
        assert payload is not None
        assert auth._ACTIVE_REQUESTS == {"tenant-mixed": 1}

        status, payload, _headers, _raw = v1_server.request(
            "GET",
            "/v1/catalog",
            token="mixed-finite-token",
        )
        assert status == 429
        assert payload is not None
        _error_shape(payload, "rate_limited")
        assert auth._ACTIVE_REQUESTS == {"tenant-mixed": 1}
    finally:
        auth.release_concurrency("tenant-mixed")
    assert auth._ACTIVE_REQUESTS == {}


@pytest.mark.parametrize(
    "state", ["success", "empty", "unobserved", "paused", "failed", "stale"]
)
def test_v1_group_21_runtime_states_remain_honest_200(
    v1_server: _Harness, state: str
) -> None:
    v1_server.query.state = state
    body = _json_body(GOOD_QUERY)
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=body, headers=_post_headers(body)
    )
    assert status == 200
    assert payload is not None
    assert payload["metadata"]["runtime_state"] == state
    assert payload["metadata"]["degraded"] is (state not in {"success", "empty"})


def test_v1_group_21_response_budget_is_checked_before_headers_and_releases_claim(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_registry = _registry_with_limits(max_response_bytes=256)
    v1_server.catalog._registry = small_registry
    v1_server.query._registry = small_registry
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    v1_server.query.response_override = {
        **_success_query_response("placeholder"),
        "data": [{"blob": "x" * 1024}],
    }
    body = _json_body(GOOD_QUERY)
    for _ in range(2):
        status, payload, _headers, raw = v1_server.request(
            "POST", "/v1/query", body=body, headers=_post_headers(body)
        )
        assert status == 413
        assert payload is not None
        _error_shape(payload, "budget_exceeded")
        assert b"blob" not in raw
    assert auth._ACTIVE_REQUESTS == {}


def test_v1_group_22_lazy_services_do_not_import_product_or_trading_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert importlib.util.find_spec("data_plane_runtime") is not None
    source = (api_server.ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "TradingAgent" not in source
    assert "MarketGraph" not in source
    assert re.search(r"(?:from|import)\s+(?:TradingAgent|MarketGraph)", source) is None
    for forbidden in (
        "opening_gate",
        "candidate_pool",
        "portfolio_position",
        "trading_order",
        "trade_fill",
    ):
        assert forbidden not in source


def test_v1_group_22_main_bootstrap_does_not_import_legacy_runtime(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__
    imported_legacy: list[str] = []
    forbidden_modules = {
        "api_control_plane",
        "api_response",
        "legacy_query_compat",
        "reader",
        "sector_flow_v2",
    }

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name in forbidden_modules:
            imported_legacy.append(name)
            raise AssertionError("process bootstrap must not import legacy runtime")
        return real_import(name, *args, **kwargs)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    real_server_class = api_server.TradingDatasHTTPServer
    server_started = threading.Event()
    servers: list[api_server.TradingDatasHTTPServer] = []

    def build_server(*args: object, **kwargs: object) -> object:
        server = real_server_class(*args, **kwargs)
        servers.append(server)
        server_started.set()
        return server

    monkeypatch.setenv("TRADINGDATAS_API_HOST", "127.0.0.1")
    monkeypatch.setenv("TRADINGDATAS_API_PORT", str(port))
    monkeypatch.setenv("TRADINGDATAS_API_VERSION", "clean-slate-test")
    monkeypatch.setenv("TRADINGDATAS_HTTP_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("TRADINGDATAS_API_MAX_THREADS", "20")
    monkeypatch.setattr(api_server, "HOST", api_server.HOST)
    monkeypatch.setattr(api_server, "PORT", api_server.PORT)
    monkeypatch.setattr(api_server, "VERSION", api_server.VERSION)
    monkeypatch.setattr(api_server, "REQUEST_TIMEOUT", api_server.REQUEST_TIMEOUT)
    monkeypatch.setattr(api_server, "MAX_THREADS", api_server.MAX_THREADS)
    monkeypatch.setattr(
        api_server.Handler, "server_version", api_server.Handler.server_version
    )
    monkeypatch.setattr(api_server, "_process_config_loaded", False, raising=False)
    monkeypatch.setattr(api_server, "TradingDatasHTTPServer", build_server)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    main_errors: list[BaseException] = []

    def run_main() -> None:
        try:
            api_server.main()
        except BaseException as exc:  # noqa: BLE001 - assert bootstrap containment
            main_errors.append(exc)
            server_started.set()

    thread = threading.Thread(target=run_main, daemon=True)
    thread.start()
    assert server_started.wait(timeout=5)
    try:
        assert main_errors == []
        assert len(servers) == 1
        main_harness = _Harness(
            f"http://127.0.0.1:{port}", v1_server.catalog, v1_server.query
        )
        v1_status, v1_payload, _headers, _raw = main_harness.request(
            "GET", "/v1/catalog"
        )
        retired_status, retired_payload, _headers, _raw = main_harness.request(
            "GET", "/health"
        )
    finally:
        if servers:
            servers[0].shutdown()
            servers[0].server_close()
        thread.join(timeout=5)

    assert imported_legacy == []
    assert not thread.is_alive()
    assert v1_status == 200
    assert v1_payload is not None and v1_payload["api_version"] == "v1"
    assert retired_status == 404
    assert retired_payload is not None
    _error_shape(retired_payload, "not_found")


def test_v1_group_22_retired_routes_do_not_import_legacy_runtime(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__
    imported_legacy: list[str] = []
    forbidden_modules = {
        "api_control_plane",
        "api_response",
        "legacy_query_compat",
        "reader",
        "sector_flow_v2",
    }

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name in forbidden_modules:
            imported_legacy.append(name)
            raise AssertionError("V1 server must not import legacy runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    v1_status, v1_payload, _headers, _raw = v1_server.request("GET", "/v1/catalog")
    assert v1_status == 200
    assert v1_payload is not None and v1_payload["api_version"] == "v1"
    for retired_route in (
        "/health",
        "/cache/status",
        "/tushare",
        "/source_status",
        "/opening_gate",
        "/crypto",
        "/pm_markets",
        "/v2/sector-flow/snapshot",
    ):
        status, payload, _headers, _raw = v1_server.request("GET", retired_route)
        assert status == 404
        assert payload is not None
        _error_shape(payload, "not_found")
    assert imported_legacy == []


def test_v1_group_01_unknown_provider_route_never_builds_services(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = v1_server.catalog._registry
    source = registry.datasets[0]
    fake_binding = replace(
        source.provider_bindings[0],
        provider="future_news_provider",
        api_name="future_news_stream",
        read_discriminator_value="future_news_stream",
        target_tables=("future_news_facts",),
    )
    fake_dataset = replace(
        source,
        dataset_id="cn.news.future",
        aliases=("future.news",),
        provider_bindings=(fake_binding,),
        read_model_adapter=replace(
            source.read_model_adapter,
            primary_table="future_news_facts",
        ),
    )
    expanded = DatasetRegistry(
        (*registry.datasets, fake_dataset),
        query_defaults=registry.query_defaults,
    )
    v1_server.catalog._registry = expanded
    v1_server.query._registry = expanded

    def forbidden() -> tuple[object, object]:
        raise AssertionError(
            "unknown provider routes must not reach a provider or service"
        )

    monkeypatch.setattr(api_server, "_build_v1_services", forbidden)
    status, payload, _headers, _raw = v1_server.request(
        "GET",
        "/v1/provider/fake-provider",
        token="invalid",
    )
    assert status == 404
    assert payload is not None
    _error_shape(payload, "not_found")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("unknown=x", 400),
        ("state=not-a-runtime-state", 400),
        ("cursor=", 400),
        ("cursor=%20opaque", 400),
        (
            "q=" + "x" * (api_server.V1_QUERY_DEFAULTS.max_catalog_search_chars + 1),
            413,
        ),
    ],
)
def test_v1_group_04_catalog_rejects_invalid_request_before_service_build(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected: int,
) -> None:
    def forbidden() -> tuple[object, object]:
        raise AssertionError("invalid catalog requests must not build services")

    monkeypatch.setattr(api_server, "_build_v1_services", forbidden)
    status, payload, _headers, _raw = v1_server.request(
        "GET",
        f"/v1/catalog?{query}",
    )
    assert status == expected
    assert payload is not None
    _error_shape(
        payload,
        "budget_exceeded" if expected == 413 else "invalid_request",
    )


def test_v1_group_05_catalog_default_limit_all_filters_and_cursor(
    v1_server: _Harness,
) -> None:
    status, payload, _headers, _raw = v1_server.request(
        "GET",
        "/v1/catalog?market=CN&domain=equity&cadence=postclose_daily"
        "&state=success&q=%E6%B5%A6%E5%8F%91&cursor=opaque-cursor",
    )
    assert status == 200
    assert payload is not None
    call = v1_server.catalog.calls[-1]
    assert call["limit"] == api_server.V1_QUERY_DEFAULTS.max_page_size
    assert call["cursor"] == "opaque-cursor"
    assert call["filters"] == CatalogFilters(
        market="CN",
        domain="equity",
        cadence="postclose_daily",
        state="success",
        q="浦发",
    )


def test_v1_group_05_oversized_canonical_limit_is_413_not_500(
    v1_server: _Harness,
) -> None:
    status, payload, _headers, _raw = v1_server.request(
        "GET",
        "/v1/catalog?limit=" + "9" * 5_000,
    )
    assert status == 413
    assert payload is not None
    _error_shape(payload, "budget_exceeded")


@pytest.mark.parametrize(
    ("method", "target", "body", "headers", "token", "expected", "code"),
    [
        ("POST", "/v1/catalog", b"{broken", [], "invalid", 405, "method_not_allowed"),
        (
            "POST",
            "/v1/query",
            b"{broken",
            [("Content-Length", "+7"), ("Content-Type", "application/json")],
            "invalid",
            400,
            "invalid_request",
        ),
        (
            "POST",
            "/v1/query",
            b"{broken",
            [("Content-Length", "7"), ("Content-Type", "application/json")],
            "invalid",
            401,
            "unauthenticated",
        ),
        (
            "POST",
            "/v1/query",
            b"x",
            [
                (
                    "Content-Length",
                    str(api_server.V1_QUERY_DEFAULTS.max_request_bytes + 1),
                ),
                ("Content-Type", "application/json"),
            ],
            "invalid",
            413,
            "budget_exceeded",
        ),
    ],
)
def test_v1_fixed_failure_priority(
    v1_server: _Harness,
    method: str,
    target: str,
    body: bytes,
    headers: list[tuple[str, str]],
    token: str,
    expected: int,
    code: str,
) -> None:
    status, payload, _response_headers, _raw = v1_server.request(
        method,
        target,
        body=body,
        token=token,
        headers=headers,
    )
    assert status == expected
    assert payload is not None
    _error_shape(payload, code)


def test_v1_rate_and_concurrency_gates_run_before_json_decode(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_body = b"{broken"
    headers = _post_headers(bad_body)
    monkeypatch.setattr(auth, "RATE_LIMITS", {**auth.RATE_LIMITS, "internal": 0})
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=bad_body, headers=headers
    )
    assert status == 429
    assert payload is not None
    _error_shape(payload, "rate_limited")

    monkeypatch.setattr(auth, "RATE_LIMITS", {**auth.RATE_LIMITS, "internal": None})
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    auth.claim_concurrency({"tenant_id": "tenant-full", "tier": "internal"})
    try:
        status, payload, _headers, _raw = v1_server.request(
            "POST", "/v1/query", body=bad_body, headers=headers
        )
    finally:
        auth.release_concurrency("tenant-full")
    assert status == 429
    assert payload is not None
    _error_shape(payload, "rate_limited")


@pytest.mark.parametrize(
    ("raw_request", "expected"),
    [
        (b"GET /v1/" + b"x" * 70_000 + b" HTTP/1.1\r\nHost: x\r\n\r\n", 414),
        (
            b"GET /v1/catalog HTTP/1.1\r\nHost: x\r\nX-Large: "
            + b"x" * 70_000
            + b"\r\n\r\n",
            431,
        ),
    ],
)
def test_v1_group_02_transport_limits_are_fail_closed_without_v1_envelope(
    v1_server: _Harness,
    raw_request: bytes,
    expected: int,
) -> None:
    status, raw = _raw_http_request(v1_server, raw_request)
    assert status == expected
    assert b'"request_id"' not in raw


def test_v1_group_08_duplicate_content_length_is_rejected(v1_server: _Harness) -> None:
    status, payload, headers, _raw = v1_server.request(
        "POST",
        "/v1/query",
        body=b"{}",
        headers=[
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
            ("Content-Length", "2"),
        ],
    )
    assert status == 400
    assert headers.get("connection", "").casefold() == "close"
    assert payload is not None
    _error_shape(payload, "invalid_request")


def test_v1_group_08_exact_request_budget_and_one_byte_over(
    v1_server: _Harness,
) -> None:
    encoded = _json_body(GOOD_QUERY)
    exact = encoded + b" " * (
        api_server.V1_QUERY_DEFAULTS.max_request_bytes - len(encoded)
    )
    status, payload, _headers, _raw = v1_server.request(
        "POST", "/v1/query", body=exact, headers=_post_headers(exact)
    )
    assert status == 200
    assert payload is not None

    status, payload, response_headers, _raw = v1_server.request(
        "POST",
        "/v1/query",
        body=b"x",
        headers=[
            ("Content-Type", "application/json"),
            ("Content-Length", str(api_server.V1_QUERY_DEFAULTS.max_request_bytes + 1)),
        ],
    )
    assert status == 413
    assert response_headers.get("connection", "").casefold() == "close"
    assert payload is not None
    _error_shape(payload, "budget_exceeded")


def test_v1_group_08_over_budget_never_decodes_body(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("over-budget body must not be decoded")

    monkeypatch.setattr(api_server, "parse_json_body", forbidden)
    status, payload, _headers, _raw = v1_server.request(
        "POST",
        "/v1/query",
        body=b"x",
        headers=[
            ("Content-Type", "application/json"),
            ("Content-Length", str(api_server.V1_QUERY_DEFAULTS.max_request_bytes + 1)),
        ],
    )
    assert status == 413
    assert payload is not None
    _error_shape(payload, "budget_exceeded")


def test_v1_group_08_short_read_is_bounded_400_and_close(v1_server: _Harness) -> None:
    request = (
        b"POST /v1/query HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer full-token\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 100\r\n\r\n{}"
    )
    status, raw = _raw_http_request(v1_server, request)
    assert status == 400
    assert b"Connection: close" in raw
    assert b'"code":"invalid_request"' in raw


def test_v1_group_19_http_context_normalizes_scopes_and_recomputes_policy(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_authenticate = auth.authenticate

    def reordered(headers: Any, client_host: str) -> dict[str, Any]:
        account = dict(real_authenticate(headers, client_host))
        account["scopes"] = ["read", "external_read", "read"]
        account["policy_id"] = "untrusted"
        account["allowed_dataset_ids"] = ["cn.secret.dataset"]
        return account

    monkeypatch.setattr(auth, "authenticate", reordered)
    status, _payload, _headers, _raw = v1_server.request(
        "GET", "/v1/catalog", token="tenant-a-token"
    )
    assert status == 200
    access = v1_server.catalog.calls[-1]["access"]
    expected = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("external_read", "read"),
        allowed_dataset_ids=(),
    )
    assert access == expected


def test_v1_group_19_real_signed_cursor_is_bound_to_tenant_policy(
    v1_server: _Harness,
) -> None:
    now = datetime.now(timezone.utc)
    codec = SignedCursorCodec(SIGNING_KEY)
    access_a = QueryAccessContext.from_grants(
        tenant_id="tenant-a",
        scopes=("external_read",),
        allowed_dataset_ids=(),
    )
    access_b = QueryAccessContext.from_grants(
        tenant_id="tenant-b",
        scopes=("external_read",),
        allowed_dataset_ids=(),
    )
    token = codec.encode(
        CursorClaims(
            kind="query",
            catalog_version="v1-test-contract",
            dataset_id="cn.equity.daily",
            schema_major=1,
            query_hash="query-hash",
            policy_id=access_a.policy_id,
            receipt_watermark="receipt",
            sort_key=("600000.SH",),
            expires_at=int(now.timestamp()) + 600,
        )
    )

    def decode_for_b(raw: str, request_now: datetime) -> None:
        codec.decode(
            raw,
            expected=CursorExpectation(
                kind="query",
                catalog_version="v1-test-contract",
                dataset_id="cn.equity.daily",
                schema_major=1,
                query_hash="query-hash",
                policy_id=access_b.policy_id,
                receipt_watermark="receipt",
            ),
            now=request_now,
        )

    v1_server.query.decoder = decode_for_b
    body = _json_body({**GOOD_QUERY, "cursor": token})
    status, payload, _headers, raw = v1_server.request(
        "POST",
        "/v1/query",
        token="tenant-b-token",
        body=body,
        headers=_post_headers(body),
    )
    assert status == 409
    assert payload is not None
    _error_shape(payload, "cursor_mismatch")
    assert token.encode() not in raw
    assert access_a.policy_id.encode() not in raw
    assert access_b.policy_id.encode() not in raw


def test_v1_group_20_query_always_dispatches_and_never_touches_legacy_cache(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy cache/dedup must not be used")

    monkeypatch.setattr(auth, "request_fingerprint", forbidden)
    monkeypatch.setattr(auth, "get_cached_response", forbidden)
    monkeypatch.setattr(auth, "store_cached_response", forbidden)
    body = _json_body(GOOD_QUERY)
    for token in ("tenant-a-token", "tenant-a-token", "tenant-b-token"):
        status, _payload, _headers, _raw = v1_server.request(
            "POST", "/v1/query", token=token, body=body, headers=_post_headers(body)
        )
        assert status == 200
    assert len(v1_server.query.calls) == 3


def test_v1_group_21_concurrency_is_per_tenant_and_released(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    entered = threading.Event()
    release = threading.Event()
    v1_server.query.entered = entered
    v1_server.query.release = release
    body = _json_body(GOOD_QUERY)
    results: dict[str, tuple[int, dict[str, Any] | None, dict[str, str], bytes]] = {}

    def query_as(name: str, token: str) -> None:
        results[name] = v1_server.request(
            "POST",
            "/v1/query",
            token=token,
            body=body,
            headers=_post_headers(body),
        )

    tenant_a = threading.Thread(target=query_as, args=("a", "tenant-a-token"))
    tenant_a.start()
    assert entered.wait(timeout=5)

    tenant_b = threading.Thread(target=query_as, args=("b", "tenant-b-token"))
    tenant_b.start()
    deadline = time.monotonic() + 5
    while auth._ACTIVE_REQUESTS.get("tenant-b") != 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert auth._ACTIVE_REQUESTS == {"tenant-a": 1, "tenant-b": 1}

    same_status, same_payload, _headers, _raw = v1_server.request(
        "POST",
        "/v1/query",
        token="tenant-a-token",
        body=body,
        headers=_post_headers(body),
    )
    assert same_status == 429
    assert same_payload is not None
    _error_shape(same_payload, "rate_limited")

    release.set()
    tenant_a.join(timeout=5)
    tenant_b.join(timeout=5)
    assert results["a"][0] == 200
    assert results["b"][0] == 200
    deadline = time.monotonic() + 5
    while auth._ACTIVE_REQUESTS and time.monotonic() < deadline:
        time.sleep(0.01)
    assert auth._ACTIVE_REQUESTS == {}


def test_v1_group_21_serialization_failure_releases_concurrency_claim(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    v1_server.query.response_override = {
        **_success_query_response("placeholder"),
        "data": [{"invalid": float("nan")}],
    }
    body = _json_body(GOOD_QUERY)
    for _ in range(2):
        status, payload, _headers, raw = v1_server.request(
            "POST", "/v1/query", body=body, headers=_post_headers(body)
        )
        assert status == 500
        assert payload is not None
        _error_shape(payload, "internal_error")
        assert b"NaN" not in raw
    assert auth._ACTIVE_REQUESTS == {}


def test_v1_group_21_client_disconnect_releases_concurrency_claim(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth, "CONCURRENCY_LIMITS", {**auth.CONCURRENCY_LIMITS, "internal": 1}
    )
    entered = threading.Event()
    release = threading.Event()
    v1_server.query.entered = entered
    v1_server.query.release = release
    body = _json_body(GOOD_QUERY)
    request = (
        b"POST /v1/query HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer tenant-a-token\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )
    client = socket.create_connection((v1_server.host, v1_server.port), timeout=5)
    client.sendall(request)
    assert entered.wait(timeout=5)
    client.close()
    release.set()
    deadline = time.monotonic() + 5
    while auth._ACTIVE_REQUESTS and time.monotonic() < deadline:
        time.sleep(0.01)
    assert auth._ACTIVE_REQUESTS == {}


def test_v1_group_22_data_plane_constructor_is_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_plane_runtime
    import query_cursor

    calls = 0

    def fake_from_env(_cls: type[SignedCursorCodec]) -> SignedCursorCodec:
        nonlocal calls
        calls += 1
        return SignedCursorCodec(SIGNING_KEY)

    monkeypatch.setattr(
        query_cursor.SignedCursorCodec,
        "from_env",
        classmethod(fake_from_env),
    )
    reloaded = importlib.reload(data_plane_runtime)
    assert calls == 0
    try:
        first = reloaded.build_data_plane_services()
        second = reloaded.build_data_plane_services()
        assert first is second
        assert calls == 1
    finally:
        reloaded._reset_data_plane_runtime_for_tests()


@pytest.mark.parametrize("signing_key", [None, "short"])
def test_v1_group_22_missing_or_short_key_only_degrades_v1(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    signing_key: str | None,
) -> None:
    import data_plane_runtime

    data_plane_runtime._reset_data_plane_runtime_for_tests()
    if signing_key is None:
        monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    else:
        monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY", signing_key)
    monkeypatch.setattr(
        api_server,
        "_build_v1_services",
        data_plane_runtime.build_data_plane_services,
    )
    status, payload, _headers, _raw = v1_server.request("GET", "/v1/catalog")
    assert status == 503
    assert payload is not None
    _error_shape(payload, "service_unavailable")

    retired_status, retired, _headers, _raw = v1_server.request("GET", "/health")
    assert retired_status == 404
    assert retired is not None
    _error_shape(retired, "not_found")
    data_plane_runtime._reset_data_plane_runtime_for_tests()


def test_v1_group_22_missing_read_model_is_503_without_file_fallback(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    import data_plane_runtime
    import runtime_paths

    missing = tmp_path / "missing" / "marketdata.sqlite"
    monkeypatch.setenv(
        "TRADINGDATAS_CURSOR_SIGNING_KEY",
        SIGNING_KEY.decode("ascii"),
    )
    monkeypatch.setattr(runtime_paths, "marketdata_sqlite_path", lambda: missing)
    data_plane_runtime._reset_data_plane_runtime_for_tests()
    monkeypatch.setattr(
        api_server,
        "_build_v1_services",
        data_plane_runtime.build_data_plane_services,
    )
    status, payload, _headers, _raw = v1_server.request("GET", "/v1/catalog")
    assert status == 503
    assert payload is not None
    _error_shape(payload, "service_unavailable")
    assert not missing.exists()
    data_plane_runtime._reset_data_plane_runtime_for_tests()


def test_v1_group_22_invalid_server_clock_is_503(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    import data_plane_runtime
    import runtime_paths

    class NaiveClock:
        @classmethod
        def now(cls, _tz: object = None) -> datetime:
            return datetime(2026, 7, 16, 0, 0, 0)

    monkeypatch.setenv(
        "TRADINGDATAS_CURSOR_SIGNING_KEY",
        SIGNING_KEY.decode("ascii"),
    )
    monkeypatch.setattr(
        runtime_paths,
        "marketdata_sqlite_path",
        lambda: tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(api_server, "datetime", NaiveClock)
    data_plane_runtime._reset_data_plane_runtime_for_tests()
    monkeypatch.setattr(
        api_server,
        "_build_v1_services",
        data_plane_runtime.build_data_plane_services,
    )
    status, payload, _headers, _raw = v1_server.request("GET", "/v1/catalog")
    assert status == 503
    assert payload is not None
    _error_shape(payload, "service_unavailable")
    data_plane_runtime._reset_data_plane_runtime_for_tests()


def test_admin_data_endpoints_serve_real_catalog_runtime(
    v1_server: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Admin collection/status, health/alerts and data/overview must run
    against the real catalog service surface instead of assuming methods
    that only exist on test doubles."""
    import sqlite3
    from contextlib import contextmanager
    from pathlib import Path
    from types import SimpleNamespace

    import catalog_service as catalog_module
    import data_plane_runtime
    from catalog_service import CatalogService
    from query_cursor import SignedCursorCodec
    from storage.schema import SCHEMA_SQL

    registry = load_dataset_registry()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(SCHEMA_SQL)
    db_path = (tmp_path / "admin-endpoints.sqlite").absolute()

    def _runtime_row(dataset_id: str, state: str) -> dict[str, Any]:
        return {
            "dataset_id": dataset_id,
            "state": state,
            "degraded": state not in {"success", "empty"},
            "data_through": (
                "2026-07-16T03:00:00+00:00"
                if state in {"success", "stale"}
                else None
            ),
            "observed_at": (
                None if state in {"unobserved", "paused"}
                else "2026-07-16T03:00:00+00:00"
            ),
            "receipt_id": None,
            "reasons": {
                "success": [],
                "empty": ["provider_returned_no_rows"],
                "unobserved": ["no_recognized_receipt"],
                "paused": ["registry_activation_paused"],
                "failed": ["provider_error"],
                "stale": ["freshness_sla_exceeded"],
            }[state],
        }

    failed_id = registry.datasets[0].dataset_id
    stale_id = registry.datasets[1].dataset_id
    states = {
        dataset.dataset_id: _runtime_row(
            dataset.dataset_id,
            "failed" if dataset.dataset_id == failed_id
            else "stale" if dataset.dataset_id == stale_id
            else "success",
        )
        for dataset in registry.datasets
    }
    project_calls = 0

    @contextmanager
    def snapshot(path: Any):
        assert Path(path) == db_path
        yield conn

    def project(
        snapshot_conn: sqlite3.Connection,
        projected_registry: DatasetRegistry,
        *,
        now: datetime,
        validation_cache: dict | None = None,
    ) -> dict[str, Any]:
        nonlocal project_calls
        project_calls += 1
        return {"datasets": states}

    monkeypatch.setattr(catalog_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(catalog_module, "project_catalog_runtime", project)
    catalog = CatalogService(
        registry=registry,
        db_path=db_path,
        cursor_codec=SignedCursorCodec(SIGNING_KEY),
    )
    monkeypatch.setattr(
        data_plane_runtime,
        "build_data_plane_runtime",
        lambda: SimpleNamespace(registry=registry, catalog=catalog),
    )
    try:
        status, payload, _headers, _raw = v1_server.request(
            "GET", "/admin/api/collection/status", token="full-token"
        )
        assert status == 200, payload
        assert payload is not None
        ids = {row["dataset_id"] for row in payload["datasets"]}
        assert ids == {dataset.dataset_id for dataset in registry.datasets}
        failed_row = next(
            row for row in payload["datasets"] if row["dataset_id"] == failed_id
        )
        assert failed_row["runtime_state"] == "failed"
        assert failed_row["provider"]
        assert failed_row["cadence"]

        status, alerts, _headers, _raw = v1_server.request(
            "GET", "/admin/api/health/alerts", token="full-token"
        )
        assert status == 200
        assert alerts is not None
        by_severity = {}
        for alert in alerts["alerts"]:
            by_severity.setdefault(alert["severity"], []).append(alert)
        assert {a["title"].split(":")[0] for a in by_severity["critical"]} == {failed_id}
        assert {a["title"].split(":")[0] for a in by_severity["warning"]} == {stale_id}
        failed_alert = by_severity["critical"][0]
        assert failed_alert["dataset_id"] == failed_id
        assert failed_alert["runtime_state"] == "failed"
        assert failed_alert["reason_codes"] == ["provider_error"]
        assert failed_alert["suggested_action"]

        status, overview, _headers, _raw = v1_server.request(
            "GET", "/admin/api/data/overview", token="full-token"
        )
        assert status == 200
        assert overview is not None
        assert overview["total_datasets"] == len(registry.datasets)
        assert sum(overview["by_runtime_state"].values()) == len(registry.datasets)
        assert overview["by_runtime_state"]["failed"] == 1
        assert overview["by_runtime_state"]["stale"] == 1
        assert project_calls == 1
        assert sum(overview["by_market"].values()) == len(registry.datasets)
    finally:
        conn.close()


def test_admin_usage_history_accepts_dashboard_days_parameter(
    v1_server: _Harness,
) -> None:
    """The admin dashboard's history query is not a catalog-filter query."""

    status, payload, _headers, _raw = v1_server.request(
        "GET", "/admin/api/usage/history?days=7", token="full-token"
    )
    assert status == 200
    assert payload is not None
    assert len(payload["history"]) == 7
