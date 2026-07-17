#!/usr/bin/env python3

"""http.server based REST API for SharedSignals."""

from __future__ import annotations

import json
import math
import os
import re
import socket
import sys
import threading
import uuid
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote_to_bytes, urlparse

import api_control_plane
from api_response import (
    add_page_metadata,
    aggregate_metadata,
    apply_row_limit,
    to_int,
    utc_now_iso,
    validate_json_query_params,
    wrap_response,
)
from catalog_service import CatalogFilters
from dataset_registry import TUSHARE_ALLOWED_API_NAMES, load_dataset_registry
from env_bootstrap import env_float, env_int
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryValidationError,
    parse_query_request,
)
from query_cursor import (
    CursorConfigurationError,
    CursorMismatch,
    InvalidCursor,
)
from query_service import (
    QueryAccessDenied,
    QueryDatasetNotFound,
    QueryServiceUnavailable,
)
from storage.receipt_projection import RuntimeProjectionError

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

auth: Any | None = None
reader: Any | None = None
sector_flow_v2: Any | None = None
_runtime_load_lock = threading.Lock()
_auth_load_lock = threading.Lock()
_process_config_load_lock = threading.Lock()
_process_config_loaded = False
HOST = os.environ.get("SHAREDSIGNALS_API_HOST", "127.0.0.1")
PORT = env_int("SHAREDSIGNALS_API_PORT", 8082, min_value=1, max_value=65535)
VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", "1.0.0")
REQUEST_TIMEOUT = env_float(
    "SHAREDSIGNALS_REQUEST_TIMEOUT", 30.0, min_value=1.0, max_value=300.0
)
MAX_THREADS = env_int("SHAREDSIGNALS_MAX_THREADS", 20, min_value=1, max_value=512)
CAPABILITY_PATH = ROOT / "tools" / "capability_registry.json"
AGENT_CONFIG_PATH = ROOT / "config" / "external_agent_api_config.json"
HEALTH_CACHE_SECONDS = 60
HEALTH_DEEP_CHECKS_ENV = "SHAREDSIGNALS_HEALTH_DEEP_CHECKS"
LIVE_CONTROL_PLANE_ENDPOINTS = {
    "/capabilities",
    "/agent_config",
    "/source_status",
    "/opening_gate",
    "/cache/status",
    "/tushare",
}
V1_CATALOG_PATH = "/v1/catalog"
V1_QUERY_PATH = "/v1/query"
V1_CATALOG_PARAMS = frozenset(
    {"market", "domain", "cadence", "state", "q", "cursor", "limit"}
)
V1_QUERY_DEFAULTS = load_dataset_registry().query_defaults
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
    """Bootstrap process/server configuration without legacy data readers."""

    global HOST, PORT, VERSION, REQUEST_TIMEOUT, MAX_THREADS, _process_config_loaded
    if _process_config_loaded:
        return
    with _process_config_load_lock:
        if _process_config_loaded:
            return
        from env_bootstrap import bootstrap_sharedsignals_env

        bootstrap_sharedsignals_env()
        HOST = os.environ.get("SHAREDSIGNALS_API_HOST", HOST)
        PORT = env_int("SHAREDSIGNALS_API_PORT", PORT, min_value=1, max_value=65535)
        VERSION = os.environ.get("SHAREDSIGNALS_API_VERSION", VERSION)
        REQUEST_TIMEOUT = env_float(
            "SHAREDSIGNALS_REQUEST_TIMEOUT",
            REQUEST_TIMEOUT,
            min_value=1.0,
            max_value=300.0,
        )
        MAX_THREADS = env_int(
            "SHAREDSIGNALS_MAX_THREADS", MAX_THREADS, min_value=1, max_value=512
        )
        Handler.server_version = f"SharedSignalsAPI/{VERSION}"
        _process_config_loaded = True


def _ensure_auth_loaded() -> None:
    """Load only authentication dependencies for the isolated V1 data plane."""

    global auth
    if auth is not None:
        return
    _ensure_process_config_loaded()
    with _auth_load_lock:
        if auth is not None:
            return
        import auth as auth_module  # noqa: WPS433

        auth = auth_module


def _build_v1_services() -> tuple[Any, Any]:
    """Construct V1 services lazily so unrelated process health can start."""

    return _build_data_plane_runtime().services


def _build_data_plane_runtime() -> Any:
    """Return the one immutable runtime shared by V1 and migrated legacy reads."""

    reader_builder = getattr(reader, "_build_data_plane_runtime", None)
    if callable(reader_builder):
        return reader_builder()

    from data_plane_runtime import build_data_plane_runtime

    return build_data_plane_runtime()


def _normalize_stock_master_table(value: object) -> str | None:
    from legacy_query_compat import normalize_stock_master_table

    return normalize_stock_master_table(value)


def _bypasses_legacy_response_cache(
    path: str,
    params: dict[str, str],
) -> bool:
    return path == "/tushare" or (
        path == "/reference"
        and _normalize_stock_master_table(params.get("table")) is not None
    )


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
    """Parse one bounded canonical UTF-8 JSON document for ``POST /v1/query``."""

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


def _is_v1_namespace(target: str) -> bool:
    raw_path = target.split("?", 1)[0]
    folded = raw_path.casefold()
    return folded == "/v1" or folded.startswith("/v1/")


def _split_v1_target(target: str) -> tuple[str, str]:
    if "?" not in target:
        return target, ""
    return tuple(target.split("?", 1))  # type: ignore[return-value]


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
    """Validate V1 query body framing before authentication or JSON decoding."""

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


def _legacy_request_access_context(
    account: object | None,
    dataset_id: str,
) -> QueryAccessContext:
    """Bind one authenticated legacy request to only its resolved dataset."""

    if account is None:
        tenant_id = "legacy-dispatch"
        scopes: tuple[str, ...] = ()
    else:
        base = _access_context_from_account(account)
        tenant_id = base.tenant_id
        scopes = base.scopes
    return QueryAccessContext.from_grants(
        tenant_id=tenant_id,
        scopes=scopes,
        allowed_dataset_ids=(dataset_id,),
    )


def _ensure_runtime_loaded() -> None:
    """Load legacy reader modules only when a legacy route needs them."""

    global reader, sector_flow_v2
    _ensure_process_config_loaded()
    _ensure_auth_loaded()
    if reader is not None and sector_flow_v2 is not None:
        return

    with _runtime_load_lock:
        if reader is not None and sector_flow_v2 is not None:
            return
        reader_module = reader
        sector_flow_v2_module = sector_flow_v2
        if reader_module is None:
            import reader as reader_module  # noqa: WPS433
        if sector_flow_v2_module is None:
            import sector_flow_v2 as sector_flow_v2_module  # noqa: WPS433
        reader = reader_module
        sector_flow_v2 = sector_flow_v2_module


# ---- Health check (lazy import to avoid pulling in health_check at startup) ----
_health_cache: dict[str, Any] | None = None
_health_cache_time: float = 0.0
_health_cache_lock = threading.Lock()


def _health_deep_checks_enabled() -> bool:
    return str(os.environ.get(HEALTH_DEEP_CHECKS_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_health() -> dict[str, Any]:
    """Return cached health status, refreshing if older than HEALTH_CACHE_SECONDS."""
    global _health_cache, _health_cache_time
    now = datetime.now(timezone.utc).timestamp()
    with _health_cache_lock:
        if (
            _health_cache is not None
            and (now - _health_cache_time) < HEALTH_CACHE_SECONDS
        ):
            return _health_cache

    try:
        from tools.health_check import get_health_status

        deep_checks = _health_deep_checks_enabled()
        result = get_health_status(
            check_functions=deep_checks,
            check_data_freshness=deep_checks,
            check_cron=True,
            check_arch=False,
            check_compile=False,
        )
    except Exception:
        result = {
            "status": "error",
            "message": "health check failed",
            "timestamp": utc_now_iso(),
        }

    result.setdefault("version", VERSION)
    with _health_cache_lock:
        _health_cache = result
        _health_cache_time = now
        return _health_cache


class NotFoundError(ValueError):
    """Raised when an endpoint or resource is not found (maps to 404)."""

    pass


ALLOWED_TUSHARE_APIS = TUSHARE_ALLOWED_API_NAMES


class Handler(BaseHTTPRequestHandler):
    server_version = f"SharedSignalsAPI/{VERSION}"

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Date", formatdate(usegmt=True))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            import logging

            logging.getLogger("sharedsignals.api").debug(
                "client disconnected before response body was written"
            )

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message, "timestamp": utc_now_iso()}, status)

    def log_message(self, fmt: str, *args: Any) -> None:
        import logging

        logger = logging.getLogger("sharedsignals.api")
        logger.info(fmt % args)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Keep V1 access logs useful without recording raw query material."""

        if _is_v1_namespace(getattr(self, "path", "")):
            import logging

            raw_path = str(getattr(self, "path", "")).split("?", 1)[0]
            safe_path = (
                raw_path
                if raw_path in {V1_CATALOG_PATH, V1_QUERY_PATH}
                else "/v1/<unknown>"
            )
            logging.getLogger("sharedsignals.api").info(
                "V1 request path=%s status=%s request_id=%s category=%s",
                safe_path,
                code,
                getattr(self, "_v1_request_id", "unavailable"),
                getattr(self, "_v1_log_category", "request"),
            )
            return
        super().log_request(code, size)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """Route unknown V1 methods into the bounded V1 error contract only."""

        if code == 501 and _is_v1_namespace(getattr(self, "path", "")):
            return self._handle_v1(str(getattr(self, "command", "")))
        return super().send_error(code, message, explain)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        if _is_v1_namespace(self.path):
            return self._handle_v1("OPTIONS")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key"
        )
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def _discard_request_body(self) -> None:
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(min(length, 1_000_000))

    def _cache_invalidate_response(self) -> dict[str, Any]:
        reader.clear_caches()
        return {
            "status": "ok",
            "message": "all caches cleared",
            "timestamp": utc_now_iso(),
        }

    def do_POST(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("POST")
        _ensure_runtime_loaded()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {
            key: values[-1]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        self._discard_request_body()
        try:
            validate_json_query_params(params)
        except ValueError as exc:
            return self._error(400, str(exc))
        if path != "/cache/invalidate":
            return self._error(404, f"unknown endpoint: {path}")
        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError as exc:
            return self._error(401, str(exc))
        if not auth.check_endpoint_scope(account, path):
            return self._error(403, f"scope does not grant access to {path}")
        try:
            auth.enforce_rate_limit(account["tenant_id"], account["tier"])
        except auth.RateLimitError as exc:
            return self._error(429, str(exc))
        return self._send_json(self._cache_invalidate_response())

    def do_GET(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("GET")
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/health":
            _ensure_auth_loaded()
        else:
            _ensure_runtime_loaded()
        params = {
            key: values[-1]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        try:
            validate_json_query_params(params)
        except ValueError as exc:
            return self._error(400, str(exc))

        if path == "/health":
            try:
                account = auth.authenticate(self.headers, self.client_address[0])
                if not auth.check_endpoint_scope(account, path):
                    return self._error(403, "scope does not grant access to /health")
            except auth.AuthError:
                return self._error(401, "authentication required")
            return self._send_json(_get_health())

        try:
            account = auth.authenticate(self.headers, self.client_address[0])
        except auth.AuthError as exc:
            return self._error(401, str(exc))

        if not auth.check_endpoint_scope(account, path):
            return self._error(403, f"scope does not grant access to {path}")

        fingerprint = None
        if (
            path not in LIVE_CONTROL_PLANE_ENDPOINTS
            and not _bypasses_legacy_response_cache(path, params)
        ):
            fingerprint = auth.request_fingerprint(path, params)
        if fingerprint is not None:
            cached = auth.get_cached_response(fingerprint)
            if cached is not None:
                return self._send_json(cached)

        try:
            auth.enforce_rate_limit(account["tenant_id"], account["tier"])
        except auth.RateLimitError as exc:
            return self._error(429, str(exc))

        claim_concurrency = getattr(auth, "claim_concurrency", None)
        release_concurrency = getattr(auth, "release_concurrency", None)
        concurrency_error = getattr(auth, "ConcurrencyLimitError", Exception)
        concurrency_claimed = False
        if claim_concurrency is not None:
            try:
                concurrency_claimed = bool(claim_concurrency(account))
            except concurrency_error as exc:
                return self._error(429, str(exc))

        try:
            try:
                response = self._dispatch(path, params, account=account)
            except NotFoundError as exc:
                return self._error(404, str(exc))
            except QueryBudgetError as exc:
                return self._error(413, str(exc))
            except CursorMismatch as exc:
                return self._error(409, str(exc))
            except InvalidCursor as exc:
                return self._error(400, str(exc))
            except QueryAccessDenied as exc:
                return self._error(403, str(exc))
            except QueryDatasetNotFound as exc:
                return self._error(404, str(exc))
            except (
                CursorConfigurationError,
                QueryServiceUnavailable,
                RuntimeProjectionError,
            ) as exc:
                return self._error(503, str(exc))
            except QueryValidationError as exc:
                return self._error(400, str(exc))
            except ValueError as exc:
                return self._error(400, str(exc))
            except FileNotFoundError as exc:
                return self._error(404, str(exc))
            except Exception as exc:  # noqa: BLE001
                import logging

                logger = logging.getLogger("sharedsignals.api")
                logger.error("Unhandled error on %s: %s", path, exc, exc_info=True)
                return self._error(500, "internal error")
        finally:
            if concurrency_claimed and release_concurrency is not None:
                release_concurrency(account["tenant_id"])

        if fingerprint is not None:
            auth.store_cached_response(fingerprint, response)
        self._send_json(response)

    def do_HEAD(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("HEAD")
        return self.send_error(501, "Unsupported method")

    def do_PUT(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("PUT")
        return self.send_error(501, "Unsupported method")

    def do_PATCH(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("PATCH")
        return self.send_error(501, "Unsupported method")

    def do_DELETE(self) -> None:
        if _is_v1_namespace(self.path):
            return self._handle_v1("DELETE")
        return self.send_error(501, "Unsupported method")

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
        self.send_header("Date", formatdate(usegmt=True))
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
        raw_path, raw_query = _split_v1_target(self.path)
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

    def _handle_v1(self, method: str) -> None:
        request_id = str(uuid.uuid4())
        self._v1_request_id = request_id
        self._v1_log_category = "request"
        suppress_body = method == "HEAD"
        path, raw_query = _split_v1_target(self.path)

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
            import logging

            logging.getLogger("sharedsignals.api").error(
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

    def _dispatch(
        self,
        path: str,
        params: dict[str, str],
        *,
        account: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path == "/capabilities":
            scope_map = getattr(auth, "SCOPE_ENDPOINTS", {}) if auth is not None else {}
            payload, metadata, source = api_control_plane.capabilities_payload(
                capability_path=CAPABILITY_PATH,
                scope_map=scope_map,
            )
            return wrap_response(payload, metadata, source)

        if path == "/agent_config":
            payload, metadata, source = api_control_plane.agent_config_payload(
                AGENT_CONFIG_PATH
            )
            return wrap_response(payload, metadata, source)

        if path == "/source_status":
            payload, metadata, source = api_control_plane.source_status_payload()
            return wrap_response(payload, metadata, source)

        if path == "/opening_gate":
            payload, metadata, source = api_control_plane.opening_gate_payload()
            return wrap_response(payload, metadata, source)

        if path == "/market_data":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_market_data(
                ts_code=ts_code,
                start=params.get("start"),
                end=params.get("end"),
                freq=params.get("freq") or "daily",
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/events":
            symbol = (
                params.get("symbol", "").strip()
                or params.get("ts_code", "").strip()
                or params.get("subject_code", "").strip()
            )
            page = reader.get_events_page(
                start=params.get("start"),
                end=params.get("end"),
                event_type=params.get("event_type", "").strip() or None,
                market=params.get("market", "").strip() or None,
                symbol=symbol or None,
                subject_code=params.get("subject_code", "").strip() or symbol or None,
                subject_type=params.get("subject_type", "").strip() or None,
                limit=to_int(params.get("limit"), 500),
                cursor=params.get("cursor"),
            )
            payload, metadata, source = aggregate_metadata(page["rows"])
            metadata = add_page_metadata(
                metadata,
                next_cursor=page["next_cursor"],
                row_count=page["row_count"],
            )
            return wrap_response(payload, metadata, source)

        if path == "/sentiment":
            rows = reader.get_sentiment(
                start=params.get("start"), end=params.get("end")
            )
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/fundamentals":
            ts_code = (params.get("ts_code", "") or params.get("symbol", "")).strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_fundamentals(
                ts_code=ts_code, limit=to_int(params.get("limit"), 200)
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/capital_flow":
            date = params.get("date", "").strip()
            start = params.get("start", "").strip()
            end = params.get("end", "").strip()
            ts_code = params.get("ts_code", "").strip() or None
            if not date and not start and not ts_code:
                raise ValueError("date, start, or ts_code is required")
            call_kwargs: dict[str, Any] = {}
            if start:
                call_kwargs["start_date"] = start
            if end:
                call_kwargs["end_date"] = end
            rows = reader.get_capital_flow(
                date=date or start or None, ts_code=ts_code, **call_kwargs
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/macro":
            rows = reader.get_macro_factors(
                start=params.get("start"),
                end=params.get("end"),
                limit=to_int(params.get("limit"), 500),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/crypto":
            symbol = params.get("symbol", "").strip()
            if not symbol:
                raise ValueError("symbol is required")
            rows = reader.get_crypto_klines(
                symbol=symbol,
                limit=to_int(params.get("limit"), 50),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/pm_markets":
            rows = reader.get_pm_markets(limit=to_int(params.get("limit"), 100))
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/pm_prices":
            market_id = params.get("market_id", "").strip() or None
            rows = reader.get_pm_prices(
                market_id=market_id,
                limit=to_int(params.get("limit"), 200),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/reference":
            raw_table = params.get("table", "")
            table = raw_table.strip()
            if not table:
                raise ValueError("table is required")
            if _normalize_stock_master_table(raw_table) is not None:
                runtime = _build_data_plane_runtime()
                invocation = runtime.legacy.stock_master_request(params)
                access = _legacy_request_access_context(
                    account,
                    invocation.request.dataset_id,
                )
                query_envelope = runtime.legacy_query.execute(
                    invocation.request,
                    access=access,
                    now=datetime.now(timezone.utc),
                    request_id=str(uuid.uuid4()),
                    options=invocation.options,
                )
                return runtime.legacy.legacy_envelope(query_envelope)
            rows = reader.get_reference(
                table=table,
                limit=to_int(params.get("limit"), 6000, max_val=10000),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/industry/snapshot":
            rows = reader.get_industry_snapshot()
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/industry/taxonomy":
            page = reader.get_industry_taxonomy(
                snapshot_id=params.get("snapshot_id", "").strip() or None,
                level=params.get("level", "").strip() or None,
                parent_industry_code=params.get("parent_industry_code", "").strip()
                or None,
                index_code=params.get("index_code", "").strip() or None,
                limit=to_int(params.get("limit"), 500, max_val=1000),
                cursor=params.get("cursor", "").strip() or None,
            )
            payload, metadata, source = aggregate_metadata(page["rows"])
            metadata = add_page_metadata(
                metadata,
                next_cursor=page["next_cursor"],
                row_count=page["row_count"],
                total_rows=page["total_rows"],
                page_metadata=page.get("metadata"),
            )
            return wrap_response(payload, metadata, source)

        if path == "/industry/memberships":
            page = reader.get_industry_memberships(
                snapshot_id=params.get("snapshot_id", "").strip() or None,
                symbol=params.get("symbol", "").strip() or None,
                l1_code=params.get("l1_code", "").strip() or None,
                l2_code=params.get("l2_code", "").strip() or None,
                l3_code=params.get("l3_code", "").strip() or None,
                limit=to_int(params.get("limit"), 500, max_val=1000),
                cursor=params.get("cursor", "").strip() or None,
            )
            payload, metadata, source = aggregate_metadata(page["rows"])
            metadata = add_page_metadata(
                metadata,
                next_cursor=page["next_cursor"],
                row_count=page["row_count"],
                total_rows=page["total_rows"],
                page_metadata=page.get("metadata"),
            )
            return wrap_response(payload, metadata, source)

        if path == "/v2/sector-flow/snapshot":
            rows = sector_flow_v2.get_snapshot(
                fact_kind=params.get("fact_kind", "").strip() or None,
                snapshot_id=params.get("snapshot_id", "").strip() or None,
                as_of=params.get("as_of", "").strip() or None,
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/v2/sector-flow/industries":
            rows = sector_flow_v2.get_industries(
                fact_kind=params.get("fact_kind", "").strip() or None,
                snapshot_id=params.get("snapshot_id", "").strip() or None,
                as_of=params.get("as_of", "").strip() or None,
                industry_code=params.get("industry_code", "").strip() or None,
                limit=to_int(params.get("limit"), 500, max_val=1000),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/v2/sector-flow/constituents":
            industry_code = params.get("industry_code", "").strip() or None
            symbol = params.get("symbol", "").strip() or None
            if not industry_code and not symbol:
                raise ValueError("industry_code or symbol is required")
            rows = sector_flow_v2.get_constituents(
                fact_kind=params.get("fact_kind", "").strip() or None,
                snapshot_id=params.get("snapshot_id", "").strip() or None,
                as_of=params.get("as_of", "").strip() or None,
                industry_code=industry_code,
                symbol=symbol,
                limit=to_int(params.get("limit"), 500, max_val=1000),
            )
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/industry":
            ts_code = params.get("ts_code", "").strip()
            if not ts_code:
                raise ValueError("ts_code is required")
            rows = reader.get_industry(ts_code=ts_code)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/associations":
            ts_code = params.get("ts_code", "").strip() or None
            event_id = params.get("event_id", "").strip() or None
            if not ts_code and not event_id:
                raise ValueError("ts_code or event_id is required")
            rows = reader.get_associations(ts_code=ts_code, event_id=event_id)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/impacts":
            event_type = params.get("event_type", "").strip() or None
            target = params.get("target", "").strip() or None
            rows = reader.get_impacts(event_type=event_type, target=target)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/tushare":
            api_name = params.get("api_name", "").strip()
            if not api_name:
                raise ValueError("api_name is required")
            runtime = _build_data_plane_runtime()
            invocation = runtime.legacy.tushare_request(params)
            access = _legacy_request_access_context(
                account,
                invocation.request.dataset_id,
            )
            query_envelope = runtime.legacy_query.execute(
                invocation.request,
                access=access,
                now=datetime.now(timezone.utc),
                request_id=str(uuid.uuid4()),
                options=invocation.options,
            )
            return runtime.legacy.legacy_envelope(query_envelope)

        if path == "/is_trading_day":
            date = params.get("date", "").strip()
            if not date:
                raise ValueError("date is required")
            rows = reader.is_trading_day(date)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/realtime_5min":
            ts_code = params.get("ts_code", "").strip()
            date = params.get("date", "").strip() or None
            market = params.get("market", "").strip() or "Ashare"
            if not ts_code and not market:
                raise ValueError("ts_code or market is required")
            rows = reader.get_realtime_5min(ts_code=ts_code, date=date, market=market)
            rows = apply_row_limit(rows, params)
            payload, metadata, source = aggregate_metadata(rows)
            return wrap_response(payload, metadata, source)

        if path == "/cache/invalidate":
            return self._cache_invalidate_response()

        if path == "/cache/status":
            return {
                "generation": getattr(reader, "_CACHE_GENERATION", 0),
                "ttl_seconds": getattr(reader, "CACHE_TTL_SECONDS", None),
                "estimated_bytes": reader.cache_byte_estimate()
                if hasattr(reader, "cache_byte_estimate")
                else 0,
                "max_bytes": getattr(reader, "CACHE_MAX_BYTES", None),
                "entry_count": reader._cache_entry_count()
                if hasattr(reader, "_cache_entry_count")
                else 0,
                "functions_registered": len(getattr(reader, "_CACHED_FUNCTIONS", ())),
                "auth": auth.cache_stats(),
                "timestamp": utc_now_iso(),
            }

        raise NotFoundError(f"unknown endpoint: {path}")


class SharedSignalsHTTPServer(ThreadingHTTPServer):
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
        payload = json.dumps(
            {"error": "server at capacity", "timestamp": utc_now_iso()},
            ensure_ascii=False,
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
    httpd = SharedSignalsHTTPServer(
        (HOST, PORT),
        Handler,
        request_timeout=REQUEST_TIMEOUT,
        max_threads=MAX_THREADS,
    )
    print(f"SharedSignals API listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
