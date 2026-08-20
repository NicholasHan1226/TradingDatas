#!/usr/bin/env python3
"""Provider-neutral TradingDatas V1 catalog/query HTTP API."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import socket
import threading
import uuid
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

from catalog_service import CatalogFilters
from dataset_registry import load_runtime_dataset_registry
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryValidationError,
    parse_query_request,
)
from query_cursor import CursorConfigurationError, CursorMismatch, InvalidCursor
from query_service import (
    QueryAccessDenied,
    QueryDatasetNotFound,
    QueryServiceUnavailable,
)
from storage.receipt_projection import RuntimeProjectionError


ROOT = Path(__file__).resolve().parent
V1_CATALOG_PATH = "/v1/catalog"
V1_QUERY_PATH = "/v1/query"
V1_CATALOG_PARAMS = frozenset(
    {"market", "domain", "cadence", "state", "q", "cursor", "limit"}
)
V1_QUERY_DEFAULTS = load_runtime_dataset_registry().query_defaults


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


HOST = os.environ.get("TRADINGDATAS_API_HOST", "127.0.0.1")
PORT = _env_int("TRADINGDATAS_API_PORT", 18082, minimum=1, maximum=65535)
VERSION = os.environ.get("TRADINGDATAS_API_VERSION", "1.0.0")
REQUEST_TIMEOUT = _env_float(
    "TRADINGDATAS_HTTP_TIMEOUT_SECONDS",
    30.0,
    minimum=1.0,
    maximum=300.0,
)
MAX_THREADS = _env_int(
    "TRADINGDATAS_API_MAX_THREADS",
    20,
    minimum=1,
    maximum=512,
)

auth: Any | None = None
_auth_load_lock = threading.Lock()
_process_config_load_lock = threading.Lock()
_process_config_loaded = False
_CANONICAL_CONTENT_LENGTH_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
_CANONICAL_POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*\Z", re.ASCII)
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_V1_ERROR_DETAILS: dict[str, tuple[str, bool]] = {
    "invalid_request": ("request is invalid", False),
    "unauthenticated": ("authentication required", False),
    "forbidden": ("request is forbidden", False),
    "not_found": ("resource not found", False),
    "method_not_allowed": ("method is not allowed", False),
    "cursor_mismatch": ("cursor does not match request", False),
    "budget_exceeded": ("request exceeds allowed budget", False),
    "unsupported_media_type": ("unsupported media type", False),
    "rate_limited": ("rate limit exceeded", True),
    "service_unavailable": ("service temporarily unavailable", True),
    "internal_error": ("internal error", False),
}


class _V1ProtocolError(Exception):
    """One bounded HTTP-layer contract failure for the V1 data plane."""

    def __init__(
        self,
        status: int,
        code: str,
        *,
        close_connection: bool = False,
        allow: str | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.close_connection = close_connection
        self.allow = allow


def _ensure_process_config_loaded() -> None:
    """Load TradingDatas server settings without constructing the data plane."""

    global HOST, PORT, VERSION, REQUEST_TIMEOUT, MAX_THREADS, _process_config_loaded
    if _process_config_loaded:
        return
    with _process_config_load_lock:
        if _process_config_loaded:
            return
        HOST = os.environ.get("TRADINGDATAS_API_HOST", HOST)
        PORT = _env_int("TRADINGDATAS_API_PORT", PORT, minimum=1, maximum=65535)
        VERSION = os.environ.get("TRADINGDATAS_API_VERSION", VERSION)
        REQUEST_TIMEOUT = _env_float(
            "TRADINGDATAS_HTTP_TIMEOUT_SECONDS",
            REQUEST_TIMEOUT,
            minimum=1.0,
            maximum=300.0,
        )
        MAX_THREADS = _env_int(
            "TRADINGDATAS_API_MAX_THREADS",
            MAX_THREADS,
            minimum=1,
            maximum=512,
        )
        Handler.server_version = f"TradingDatasAPI/{VERSION}"
        _process_config_loaded = True


def _ensure_auth_loaded() -> None:
    """Load authentication only when a valid V1 endpoint is requested."""

    global auth
    if auth is not None:
        return
    with _auth_load_lock:
        if auth is not None:
            return
        import auth as auth_module  # noqa: WPS433

        auth = auth_module


def _build_v1_services() -> tuple[Any, Any]:
    """Construct the catalog/query services lazily."""

    from data_plane_runtime import build_data_plane_services

    return build_data_plane_services()


def _reject_json_constant(_value: str) -> object:
    raise QueryValidationError("request is invalid")


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise QueryValidationError("request is invalid")
        result[key] = value
    return result


def _validate_json_tree(value: object) -> None:
    """Reject non-finite floats and non-Unicode scalar strings iteratively."""

    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is float and not math.isfinite(item):
            raise QueryValidationError("request is invalid")
        if type(item) is str:
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise QueryValidationError("request is invalid") from None
            continue
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def parse_json_body(raw: bytes, *, max_bytes: int) -> object:
    """Parse one bounded canonical UTF-8 JSON document for the query route."""

    if type(raw) is not bytes or type(max_bytes) is not int or max_bytes <= 0:
        raise QueryValidationError("request is invalid")
    if len(raw) > max_bytes:
        raise QueryBudgetError("request exceeds allowed budget")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise QueryValidationError("request is invalid")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
        _validate_json_tree(payload)
    except QueryValidationError:
        raise
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise QueryValidationError("request is invalid") from None
    return payload


def _split_target(target: str) -> tuple[str, str]:
    if "?" not in target:
        return target, ""
    path, query = target.split("?", 1)
    return path, query


def _strict_percent_decode(value: str) -> str:
    if _INVALID_PERCENT_ESCAPE_RE.search(value):
        raise QueryValidationError("request is invalid")
    try:
        return unquote_to_bytes(value).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise QueryValidationError("request is invalid") from None


def _parse_catalog_query(raw_query: str) -> dict[str, str]:
    if not raw_query:
        return {}
    result: dict[str, str] = {}
    for component in raw_query.split("&"):
        if "=" not in component:
            raise QueryValidationError("request is invalid")
        raw_key, raw_value = component.split("=", 1)
        key = _strict_percent_decode(raw_key)
        value = _strict_percent_decode(raw_value)
        if not key or key not in V1_CATALOG_PARAMS or key in result:
            raise QueryValidationError("request is invalid")
        result[key] = value
    return result


def _header_values(headers: Any, name: str) -> list[str]:
    getter = getattr(headers, "get_all", None)
    if callable(getter):
        values = getter(name, [])
        return [str(value) for value in values]
    if headers is None or name not in headers:
        return []
    return [str(headers[name])]


def _validated_query_framing(headers: Any) -> int:
    """Validate query body framing before authentication or JSON decoding."""

    if _header_values(headers, "Transfer-Encoding"):
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)

    content_lengths = _header_values(headers, "Content-Length")
    if len(content_lengths) != 1:
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    raw_length = content_lengths[0]
    if (
        _CANONICAL_CONTENT_LENGTH_RE.fullmatch(raw_length) is None
        or len(raw_length) > 19
    ):
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    length = int(raw_length)
    if length > V1_QUERY_DEFAULTS.max_request_bytes:
        raise _V1ProtocolError(413, "budget_exceeded", close_connection=True)

    if _header_values(headers, "Content-Encoding"):
        raise _V1ProtocolError(415, "unsupported_media_type", close_connection=True)

    content_types = _header_values(headers, "Content-Type")
    if not content_types:
        raise _V1ProtocolError(415, "unsupported_media_type", close_connection=True)
    if len(content_types) != 1:
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    _validate_json_content_type(content_types[0])
    return length


def _validate_json_content_type(raw_value: str) -> None:
    parts = raw_value.split(";")
    media_type = parts[0].strip().casefold()
    if media_type != "application/json":
        raise _V1ProtocolError(415, "unsupported_media_type", close_connection=True)
    if len(parts) == 1:
        return
    if len(parts) != 2 or not parts[1].strip():
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    parameter = parts[1].strip()
    if parameter.count("=") != 1:
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    name, value = (item.strip() for item in parameter.split("=", 1))
    if name.casefold() != "charset":
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    elif '"' in value:
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    if value.casefold() != "utf-8":
        raise _V1ProtocolError(415, "unsupported_media_type", close_connection=True)


def _validate_catalog_framing(headers: Any) -> None:
    if _header_values(headers, "Transfer-Encoding"):
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)
    content_lengths = _header_values(headers, "Content-Length")
    if not content_lengths:
        return
    if (
        len(content_lengths) != 1
        or _CANONICAL_CONTENT_LENGTH_RE.fullmatch(content_lengths[0]) is None
        or content_lengths[0] != "0"
    ):
        raise _V1ProtocolError(400, "invalid_request", close_connection=True)


def _access_context_from_account(account: object) -> QueryAccessContext:
    if type(account) is not dict:
        raise RuntimeError("authenticated account is invalid")
    tenant_id = account.get("tenant_id")
    raw_scopes = account.get("scopes")
    if type(tenant_id) is not str or type(raw_scopes) not in {list, tuple}:
        raise RuntimeError("authenticated account is invalid")
    if any(type(scope) is not str for scope in raw_scopes):
        raise RuntimeError("authenticated account is invalid")
    return QueryAccessContext.from_grants(
        tenant_id=tenant_id,
        scopes=tuple(raw_scopes),
        allowed_dataset_ids=(),
    )


class Handler(BaseHTTPRequestHandler):
    """Serve exactly the two provider-neutral V1 routes."""

    server_version = f"TradingDatasAPI/{VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.getLogger("tradingdatas.api").info(fmt, *args)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        raw_path = str(getattr(self, "path", "")).split("?", 1)[0]
        safe_path = (
            raw_path if raw_path in {V1_CATALOG_PATH, V1_QUERY_PATH} else "unknown"
        )
        logging.getLogger("tradingdatas.api").info(
            "V1 request path=%s status=%s request_id=%s category=%s",
            safe_path,
            code,
            getattr(self, "_v1_request_id", "unavailable"),
            getattr(self, "_v1_log_category", "request"),
        )

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        if code == 501:
            return self._handle_v1(str(getattr(self, "command", "")))
        return super().send_error(code, message, explain)

    def do_GET(self) -> None:  # noqa: N802
        self._handle_v1("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle_v1("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle_v1("OPTIONS")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_v1("HEAD")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_v1("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle_v1("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_v1("DELETE")

    def _write_v1_json(
        self,
        payload: dict[str, object],
        *,
        status: int,
        suppress_body: bool = False,
        allow: str | None = None,
        max_response_bytes: int | None = None,
    ) -> None:
        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
            raise RuntimeError("V1 response is not serializable") from None
        if max_response_bytes is not None and len(body) > max_response_bytes:
            raise QueryBudgetError("response exceeds allowed budget")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Origin", "*")
        if allow is not None:
            self.send_header("Allow", allow)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if suppress_body:
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _write_v1_error(
        self,
        request_id: str,
        *,
        status: int,
        code: str,
        suppress_body: bool = False,
        allow: str | None = None,
    ) -> None:
        self._v1_log_category = code
        message, retryable = _V1_ERROR_DETAILS[code]
        self._write_v1_json(
            {
                "api_version": "v1",
                "request_id": request_id,
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                },
            },
            status=status,
            suppress_body=suppress_body,
            allow=allow,
        )

    def _write_v1_options(self, allow: str) -> None:
        self._v1_log_category = "preflight"
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", allow)
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-API-Key",
        )
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    @staticmethod
    def _service_query_defaults(service: object) -> object:
        registry = getattr(service, "_registry", None)
        defaults = getattr(registry, "query_defaults", None)
        if defaults is None:
            raise QueryServiceUnavailable("query service is unavailable")
        return defaults

    @staticmethod
    def _build_services_fail_closed() -> tuple[Any, Any]:
        try:
            services = _build_v1_services()
        except (
            CursorConfigurationError,
            QueryServiceUnavailable,
            RuntimeProjectionError,
        ):
            raise
        except Exception:
            raise QueryServiceUnavailable("query service is unavailable") from None
        if type(services) is not tuple or len(services) != 2:
            raise QueryServiceUnavailable("query service is unavailable")
        return services

    def _read_v1_body(self, length: int) -> bytes:
        try:
            raw = self.rfile.read(length)
        except (OSError, TimeoutError, socket.timeout):
            self.close_connection = True
            raise QueryValidationError("request is invalid") from None
        if len(raw) != length:
            self.close_connection = True
            raise QueryValidationError("request is invalid")
        return raw

    def _dispatch_v1_catalog(
        self,
        *,
        access: QueryAccessContext,
        request_id: str,
        now: datetime,
    ) -> tuple[dict[str, object], int]:
        raw_path, raw_query = _split_target(self.path)
        if raw_path != V1_CATALOG_PATH:
            raise QueryValidationError("request is invalid")
        params = _parse_catalog_query(raw_query)
        raw_limit = params.pop("limit", None)
        if raw_limit is None:
            limit = V1_QUERY_DEFAULTS.max_page_size
        else:
            if _CANONICAL_POSITIVE_INTEGER_RE.fullmatch(raw_limit) is None:
                raise QueryValidationError("request is invalid")
            maximum = str(V1_QUERY_DEFAULTS.max_page_size)
            if len(raw_limit) > len(maximum) or (
                len(raw_limit) == len(maximum) and raw_limit > maximum
            ):
                raise QueryBudgetError("request exceeds allowed budget")
            limit = int(raw_limit)
        filters = CatalogFilters(
            market=params.pop("market", None),
            domain=params.pop("domain", None),
            cadence=params.pop("cadence", None),
            state=params.pop("state", None),
            q=params.pop("q", None),
        )
        if (
            filters.q is not None
            and len(filters.q) > V1_QUERY_DEFAULTS.max_catalog_search_chars
        ):
            raise QueryBudgetError("request exceeds allowed budget")
        cursor = params.pop("cursor", None)
        if cursor is not None and (not cursor or cursor != cursor.strip()):
            raise QueryValidationError("request is invalid")
        if params:
            raise QueryValidationError("request is invalid")
        catalog, _query = self._build_services_fail_closed()
        defaults = self._service_query_defaults(catalog)
        response = catalog.list_datasets(
            access=access,
            filters=filters,
            limit=limit,
            cursor=cursor,
            now=now,
            request_id=request_id,
        )
        return response, defaults.max_response_bytes

    def _dispatch_v1_query(
        self,
        *,
        access: QueryAccessContext,
        request_id: str,
        now: datetime,
        content_length: int,
    ) -> tuple[dict[str, object], int]:
        raw = self._read_v1_body(content_length)
        payload = parse_json_body(raw, max_bytes=V1_QUERY_DEFAULTS.max_request_bytes)
        request = parse_query_request(payload)
        _catalog, query = self._build_services_fail_closed()
        defaults = self._service_query_defaults(query)
        response = query.execute(
            request,
            access=access,
            now=now,
            request_id=request_id,
        )
        return response, defaults.max_response_bytes

    def _handle_admin(
        self, method: str, path: str, raw_query: str, request_id: str
    ) -> None:
        """Handle admin console and admin API routes."""
        try:
            _ensure_auth_loaded()
        except Exception:
            return self._write_v1_error(
                request_id, status=503, code="service_unavailable"
            )

        # Serve admin console HTML without authentication (page loads, API calls need auth)
        if path in ("/admin", "/admin/") and method == "GET":
            return self._serve_admin_console()

        # Admin API routes require authentication
        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError:
            return self._write_v1_error(
                request_id, status=401, code="unauthenticated"
            )

        if "admin" not in account.get("scopes", []) and account.get("tier") != "internal":
            return self._write_v1_error(
                request_id, status=403, code="forbidden"
            )

        # Admin API routes
        if path == "/admin/api/tokens" and method == "GET":
            tokens = auth.list_tokens()
            daily = auth.get_daily_usage()
            for t in tokens:
                tid = t.get("tenant_id", "")
                t["daily_usage"] = daily.get(tid, {}).get("count", 0)
            return self._write_v1_json(
                {"tokens": tokens, "count": len(tokens)}, status=200
            )

        if path == "/admin/api/tokens" and method == "POST":
            body = self._read_admin_body()
            if body is None:
                return self._write_v1_error(
                    request_id, status=400, code="invalid_request"
                )
            try:
                result = auth.create_token(
                    tenant_id=body.get("tenant_id", ""),
                    tier=body.get("tier", "free"),
                    scopes=body.get("scopes"),
                    max_concurrent=body.get("max_concurrent"),
                    daily_limit=body.get("daily_limit"),
                    expires_at=body.get("expires_at"),
                )
                return self._write_v1_json(result, status=201)
            except auth.AuthError as exc:
                return self._write_v1_json(
                    {"error": str(exc)}, status=400
                )

        if path.startswith("/admin/api/tokens/") and method in ("PATCH", "DELETE"):
            token_hash = path[len("/admin/api/tokens/"):]
            if not token_hash or len(token_hash) != 64:
                return self._write_v1_error(
                    request_id, status=400, code="invalid_request"
                )
            if method == "DELETE":
                try:
                    result = auth.delete_token(token_hash)
                    return self._write_v1_json(result, status=200)
                except auth.AuthError as exc:
                    return self._write_v1_json(
                        {"error": str(exc)}, status=404
                    )
            # PATCH
            body = self._read_admin_body()
            if body is None:
                return self._write_v1_error(
                    request_id, status=400, code="invalid_request"
                )
            try:
                result = auth.update_token(token_hash, body)
                return self._write_v1_json(result, status=200)
            except auth.AuthError as exc:
                return self._write_v1_json(
                    {"error": str(exc)}, status=404
                )

        if path == "/admin/api/usage" and method == "GET":
            return self._write_v1_json({
                "daily": auth.get_daily_usage(),
                "hourly": auth.get_hourly_usage(),
                "cache": auth.cache_stats(),
            }, status=200)

        if path == "/admin/api/usage/history" and method == "GET":
            try:
                days = int(query_params.get("days", ["30"])[0])
            except (ValueError, TypeError):
                days = 30
            days = max(1, min(days, 365))
            return self._write_v1_json({
                "history": auth.get_usage_history(days=days),
            }, status=200)

        if path == "/admin/api/health/alerts" and method == "GET":
            return self._serve_health_alerts(request_id, account)

        if path == "/admin/api/collection/status" and method == "GET":
            return self._serve_collection_status(request_id, account)

        if path == "/admin/api/data/overview" and method == "GET":
            return self._serve_data_overview(request_id, account)

        return self._write_v1_error(
            request_id, status=404, code="not_found"
        )

    def _read_admin_body(self) -> dict | None:
        """Read and parse JSON body for admin API."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            return None
        if length <= 0 or length > 1024 * 1024:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _serve_admin_console(self) -> None:
        """Serve the admin console HTML page from static/index.html."""
        static_path = Path(__file__).resolve().parent / "static" / "index.html"
        try:
            html = static_path.read_bytes()
        except OSError:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"admin console asset missing: static/index.html")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html)

    def _admin_catalog_rows(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        """Aggregate access-visible catalog rows via the fixed V1 catalog API."""
        from data_plane_runtime import build_data_plane_runtime

        runtime = build_data_plane_runtime()
        provider_map = {
            dataset.dataset_id: sorted(
                {binding.provider for binding in dataset.provider_bindings}
            )
            for dataset in runtime.registry.datasets
        }
        access = _access_context_from_account(account)
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):
            response: dict[str, object] = runtime.catalog.list_datasets(
                access=access,
                filters=CatalogFilters(),
                limit=200,
                cursor=cursor,
                now=datetime.now(timezone.utc),
                request_id="admin",
            )
            for item in response.get("data", []):
                dataset_id = item.get("dataset_id", "")
                availability = item.get("availability", {})
                runtime_info = item.get("runtime", {})
                state = runtime_info.get("state", "")
                degraded = bool(runtime_info.get("degraded"))
                rows.append({
                    "dataset_id": dataset_id,
                    "provider": "|".join(provider_map.get(dataset_id, ["-"])),
                    "market": item.get("market", ""),
                    "domain": item.get("domain", ""),
                    "cadence": item.get("cadence", ""),
                    "activation": "|".join(availability.get("activation_states") or ["-"]),
                    "entitlement": "|".join(availability.get("entitlement_states") or ["-"]),
                    "runtime_state": state,
                    "degraded": degraded,
                    "freshness_state": "degraded" if degraded else state,
                    "data_through": runtime_info.get("data_through"),
                    "observed_at": runtime_info.get("observed_at"),
                    "reasons": list(runtime_info.get("reasons", [])),
                })
            cursor = response.get("next_cursor")
            if not cursor:
                break
        return rows

    def _serve_collection_status(
        self, request_id: str, account: dict[str, Any]
    ) -> None:
        """Return collection status for all access-visible datasets."""
        try:
            datasets = self._admin_catalog_rows(account)
            self._write_v1_json({
                "datasets": datasets,
                "total": len(datasets),
                "active": sum(1 for d in datasets if d["activation"] == "active"),
                "paused": sum(1 for d in datasets if d["activation"] == "paused"),
            }, status=200)
        except Exception as exc:
            self._write_v1_json(
                {"error": str(exc), "datasets": [], "total": 0}, status=503
            )

    def _serve_health_alerts(
        self, request_id: str, account: dict[str, Any]
    ) -> None:
        """Return current collection health alerts (failed, stale, degraded)."""
        try:
            datasets = self._admin_catalog_rows(account)
            alerts: list[dict[str, Any]] = []
            for d in datasets:
                state = d["runtime_state"]
                if state == "failed":
                    alerts.append({
                        "severity": "critical",
                        "title": f"{d['dataset_id']}: collection failed",
                        "detail": (
                            f"provider={d['provider']} cadence={d['cadence']} "
                            f"reasons={','.join(d['reasons']) or '-'} "
                            f"observed_at={d['observed_at'] or '-'}"
                        ),
                    })
                elif state == "stale" or d["degraded"]:
                    alerts.append({
                        "severity": "warning",
                        "title": f"{d['dataset_id']}: {d['freshness_state']}",
                        "detail": (
                            f"provider={d['provider']} cadence={d['cadence']} "
                            f"data_through={d['data_through'] or '-'} "
                            f"observed_at={d['observed_at'] or '-'}"
                        ),
                    })
                elif d["activation"] == "active" and state in ("empty", "unobserved"):
                    alerts.append({
                        "severity": "info",
                        "title": f"{d['dataset_id']}: {state}",
                        "detail": (
                            f"provider={d['provider']} active but runtime state is "
                            f"{state}"
                        ),
                    })
            return self._write_v1_json({
                "alert_count": len(alerts),
                "alerts": alerts,
            }, status=200)
        except Exception as exc:
            return self._write_v1_json(
                {"error": "health_alerts_failed", "detail": str(exc)}, status=500)

    def _serve_data_overview(
        self, request_id: str, account: dict[str, Any]
    ) -> None:
        """Return data overview (dataset counts by market/provider/cadence)."""
        try:
            datasets = self._admin_catalog_rows(account)

            def _counts(key: str) -> dict[str, int]:
                out: dict[str, int] = {}
                for d in datasets:
                    value = d.get(key) or "unknown"
                    out[value] = out.get(value, 0) + 1
                return dict(sorted(out.items(), key=lambda kv: -kv[1]))

            self._write_v1_json({
                "total_datasets": len(datasets),
                "by_market": _counts("market"),
                "by_provider": _counts("provider"),
                "by_cadence": _counts("cadence"),
                "by_runtime_state": _counts("runtime_state"),
            }, status=200)
        except Exception as exc:
            self._write_v1_json(
                {"error": str(exc)}, status=503
            )

    def _handle_v1(self, method: str) -> None:
        request_id = str(uuid.uuid4())
        self._v1_request_id = request_id
        self._v1_log_category = "request"
        suppress_body = method == "HEAD"
        path, raw_query = _split_target(self.path)

        if path == "/admin" or path.startswith("/admin/"):
            return self._handle_admin(method, path, raw_query, request_id)

        # Redirect root path to admin console
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/admin/")
            self.end_headers()
            return

        if path not in {V1_CATALOG_PATH, V1_QUERY_PATH}:
            return self._write_v1_error(
                request_id,
                status=404,
                code="not_found",
                suppress_body=suppress_body,
            )

        expected_method = "GET" if path == V1_CATALOG_PATH else "POST"
        allow = f"{expected_method}, OPTIONS"
        if method == "OPTIONS":
            return self._write_v1_options(allow)
        if method != expected_method:
            return self._write_v1_error(
                request_id,
                status=405,
                code="method_not_allowed",
                suppress_body=suppress_body,
                allow=allow,
            )
        if path == V1_QUERY_PATH and raw_query:
            self.close_connection = True
            return self._write_v1_error(
                request_id,
                status=400,
                code="invalid_request",
            )

        try:
            content_length = 0
            if path == V1_CATALOG_PATH:
                _validate_catalog_framing(self.headers)
            else:
                content_length = _validated_query_framing(self.headers)
        except _V1ProtocolError as exc:
            if exc.close_connection:
                self.close_connection = True
            return self._write_v1_error(
                request_id,
                status=exc.status,
                code=exc.code,
                suppress_body=suppress_body,
                allow=exc.allow,
            )

        try:
            _ensure_auth_loaded()
        except Exception:
            return self._write_v1_error(
                request_id,
                status=503,
                code="service_unavailable",
                suppress_body=suppress_body,
            )

        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError:
            return self._write_v1_error(
                request_id,
                status=401,
                code="unauthenticated",
                suppress_body=suppress_body,
            )
        if not auth.check_endpoint_scope(account, path):
            return self._write_v1_error(
                request_id,
                status=403,
                code="forbidden",
                suppress_body=suppress_body,
            )
        try:
            auth.enforce_rate_limit(account["tenant_id"], account["tier"])
        except auth.RateLimitError:
            return self._write_v1_error(
                request_id,
                status=429,
                code="rate_limited",
                suppress_body=suppress_body,
            )
        try:
            auth.enforce_daily_limit(account)
        except auth.RateLimitError:
            return self._write_v1_error(
                request_id,
                status=429,
                code="daily_limit_exceeded",
                suppress_body=suppress_body,
            )

        concurrency_claimed = False
        try:
            concurrency_claimed = auth.claim_concurrency(account)
        except auth.ConcurrencyLimitError:
            return self._write_v1_error(
                request_id,
                status=429,
                code="rate_limited",
                suppress_body=suppress_body,
            )

        try:
            access = _access_context_from_account(account)
            now = datetime.now(timezone.utc)
            if path == V1_CATALOG_PATH:
                response, max_response_bytes = self._dispatch_v1_catalog(
                    access=access,
                    request_id=request_id,
                    now=now,
                )
            else:
                response, max_response_bytes = self._dispatch_v1_query(
                    access=access,
                    request_id=request_id,
                    now=now,
                    content_length=content_length,
                )
            self._v1_log_category = "success"
            self._write_v1_json(
                response,
                status=200,
                max_response_bytes=max_response_bytes,
            )
        except QueryBudgetError:
            self._write_v1_error(
                request_id,
                status=413,
                code="budget_exceeded",
                suppress_body=suppress_body,
            )
        except CursorMismatch:
            self._write_v1_error(
                request_id,
                status=409,
                code="cursor_mismatch",
                suppress_body=suppress_body,
            )
        except (InvalidCursor, QueryValidationError):
            self._write_v1_error(
                request_id,
                status=400,
                code="invalid_request",
                suppress_body=suppress_body,
            )
        except QueryAccessDenied:
            self._write_v1_error(
                request_id,
                status=403,
                code="forbidden",
                suppress_body=suppress_body,
            )
        except QueryDatasetNotFound:
            self._write_v1_error(
                request_id,
                status=404,
                code="not_found",
                suppress_body=suppress_body,
            )
        except (
            CursorConfigurationError,
            QueryServiceUnavailable,
            RuntimeProjectionError,
        ):
            self._write_v1_error(
                request_id,
                status=503,
                code="service_unavailable",
                suppress_body=suppress_body,
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("tradingdatas.api").error(
                "V1 request failed request_id=%s category=internal_error exception_type=%s",
                request_id,
                type(exc).__name__,
            )
            self._write_v1_error(
                request_id,
                status=500,
                code="internal_error",
                suppress_body=suppress_body,
            )
        finally:
            if concurrency_claimed:
                auth.release_concurrency(account["tenant_id"])


class TradingDatasHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        *,
        request_timeout: float = 30.0,
        max_threads: int = 20,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.request_timeout = max(float(request_timeout), 1.0)
        self.max_threads = max(int(max_threads), 1)
        self._thread_limiter = threading.BoundedSemaphore(self.max_threads)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._thread_limiter.acquire(blocking=False):
            self._send_capacity_response(request)
            return
        request.settimeout(self.request_timeout)
        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._thread_limiter.release()

    def _send_capacity_response(self, request: Any) -> None:
        request_id = str(uuid.uuid4())
        payload = json.dumps(
            {
                "api_version": "v1",
                "request_id": request_id,
                "error": {
                    "code": "service_unavailable",
                    "message": "service temporarily unavailable",
                    "retryable": True,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            + f"Content-Length: {len(payload)}\r\n".encode("ascii")
            + b"Cache-Control: no-store\r\n"
            + b"Connection: close\r\n"
            + f"Date: {formatdate(usegmt=True)}\r\n\r\n".encode("ascii")
            + payload
        )
        try:
            request.sendall(response)
        finally:
            request.close()




def main() -> None:
    _ensure_process_config_loaded()
    httpd = TradingDatasHTTPServer(
        (HOST, PORT),
        Handler,
        request_timeout=REQUEST_TIMEOUT,
        max_threads=MAX_THREADS,
    )
    print(f"TradingDatas API listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
