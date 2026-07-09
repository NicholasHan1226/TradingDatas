#!/usr/bin/env python3
"""Authentication, rate limiting, and request dedup for SharedSignals API."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import os
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

from env_bootstrap import env_bool, env_int

ROOT = Path(__file__).resolve().parent
TOKEN_HASH_FILE = Path(os.environ.get("SHAREDSIGNALS_TOKEN_HASH_FILE", ROOT / "config" / "api_tokens.json"))
RATE_LIMITS = {
    "free": 60,
    "starter": 60,
    "research": 300,
    "pro": 600,
    "enterprise": None,
    "internal": None,
}
CONCURRENCY_LIMITS = {
    "free": 2,
    "starter": 2,
    "research": 4,
    "pro": 8,
    "enterprise": None,
    "internal": None,
}
LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}
LOCALHOST_BYPASS = env_bool("SHAREDSIGNALS_LOCALHOST_BYPASS", False)
JWT_VERIFY_KEY = os.environ.get("SHAREDSIGNALS_JWT_PUBLIC_KEY", "").strip()
JWT_ISSUER = os.environ.get("SHAREDSIGNALS_JWT_ISSUER", "").strip()
JWT_LEEWAY_SECONDS = env_int("SHAREDSIGNALS_JWT_LEEWAY_SECONDS", 60, min_value=0, max_value=3600)
_SALT_RAW = os.environ.get("SHAREDSIGNALS_TOKEN_SALT", "")
if not _SALT_RAW:
    import warnings
    warnings.warn("SHAREDSIGNALS_TOKEN_SALT is empty — token hashing disabled; set SHAREDSIGNALS_TOKEN_SALT in environment", RuntimeWarning)
TOKEN_SALT = _SALT_RAW.encode("utf-8")
DEDUP_TTL_SECONDS = 60
RATE_WINDOW_SECONDS = 3600
DEDUP_MAX_ENTRIES = env_int("SHAREDSIGNALS_DEDUP_MAX_ENTRIES", 2048, min_value=1)
DEDUP_MAX_BYTES = env_int("SHAREDSIGNALS_DEDUP_MAX_BYTES", 10 * 1024 * 1024, min_value=0)
DEDUP_MAX_ENTRY_BYTES = env_int("SHAREDSIGNALS_DEDUP_MAX_ENTRY_BYTES", 1024 * 1024, min_value=1)
RATE_MAX_TENANTS = env_int("SHAREDSIGNALS_RATE_MAX_TENANTS", 1024, min_value=1)
RATE_MAX_EVENTS_PER_TENANT = env_int("SHAREDSIGNALS_RATE_MAX_EVENTS_PER_TENANT", 1000, min_value=1)

# Scope presets — which endpoints each scope grants access to
STATUS_ENDPOINTS = {"/health", "/capabilities", "/agent_config", "/source_status", "/cache/status"}

SCOPE_ENDPOINTS: dict[str, set[str]] = {
    "status": STATUS_ENDPOINTS,
    "health": {*STATUS_ENDPOINTS, "/cache/invalidate"},
    "market_data": {"/market_data", "/realtime_5min", "/is_trading_day"},
    "fundamentals": {"/fundamentals", "/reference", "/industry"},
    "macro": {"/macro", "/capital_flow"},
    "events": {"/events", "/sentiment"},
    "crypto": {"/crypto"},
    "pm": {"/pm_markets", "/pm_prices"},
    "associations": {"/associations", "/impacts"},
    "tushare": {"/tushare"},
    "full": {"*"},
}
SCOPE_ENDPOINTS["external_read"] = set().union(
    SCOPE_ENDPOINTS["status"],
    SCOPE_ENDPOINTS["market_data"],
    SCOPE_ENDPOINTS["fundamentals"],
    SCOPE_ENDPOINTS["macro"],
    SCOPE_ENDPOINTS["events"],
    SCOPE_ENDPOINTS["crypto"],
    SCOPE_ENDPOINTS["pm"],
    SCOPE_ENDPOINTS["associations"],
    SCOPE_ENDPOINTS["tushare"],
)
# "read" scope grants access to all read endpoints
SCOPE_ENDPOINTS["read"] = set().union(
    *(v for k, v in SCOPE_ENDPOINTS.items() if k not in ("full",))
)

_STATE_LOCK = threading.Lock()
_REQUEST_LOG: OrderedDict[str, deque[float]] = OrderedDict()
_ACTIVE_REQUESTS: dict[str, int] = {}
_DEDUP_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_DEDUP_CACHE_BYTES = 0
_TOKEN_HASHES: dict[str, dict[str, Any]] | None = None


class AuthError(Exception):
    """Raised when authentication fails."""


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""


class ConcurrencyLimitError(Exception):
    """Raised when per-tenant concurrency is exceeded."""



def _now() -> float:
    return time.time()


def _response_size_bytes(response: dict[str, Any]) -> int:
    try:
        return len(json.dumps(response, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    except Exception:
        return len(str(response).encode("utf-8", errors="replace"))


def _drop_dedup_locked(key: str) -> None:
    global _DEDUP_CACHE_BYTES
    item = _DEDUP_CACHE.pop(key, None)
    if item is not None:
        _DEDUP_CACHE_BYTES = max(0, _DEDUP_CACHE_BYTES - int(item.get("size_bytes", 0)))



def _cleanup_dedup_locked(now: float) -> None:
    """Remove expired dedup entries and evict oldest when over DEDUP_MAX_ENTRIES.

    Must be called while _STATE_LOCK is held.
    """
    # Remove expired entries
    expired = [
        key for key, item in _DEDUP_CACHE.items()
        if now - float(item.get("stored_at", 0.0)) > DEDUP_TTL_SECONDS
    ]
    for key in expired:
        _drop_dedup_locked(key)

    # Evict oldest (LRU) entries when over capacity
    while len(_DEDUP_CACHE) > DEDUP_MAX_ENTRIES:
        key, _ = next(iter(_DEDUP_CACHE.items()))
        _drop_dedup_locked(key)
    while DEDUP_MAX_BYTES > 0 and _DEDUP_CACHE_BYTES > DEDUP_MAX_BYTES and _DEDUP_CACHE:
        key, _ = next(iter(_DEDUP_CACHE.items()))
        _drop_dedup_locked(key)


def _cleanup_rate_log_locked(now: float) -> None:
    """Remove expired timestamps, empty tenant buckets, and evict oldest tenants.

    Must be called while _STATE_LOCK is held.
    """
    # Remove expired timestamps from each tenant bucket
    empty_tenants: list[str] = []
    for tenant_id, bucket in _REQUEST_LOG.items():
        while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
            bucket.popleft()
        if not bucket:
            empty_tenants.append(tenant_id)

    # Remove empty tenant buckets
    for tenant_id in empty_tenants:
        _REQUEST_LOG.pop(tenant_id, None)

    # Evict oldest (LRU) tenants when over capacity
    while len(_REQUEST_LOG) > RATE_MAX_TENANTS:
        _REQUEST_LOG.popitem(last=False)


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _parse_der_tlv(data: bytes, offset: int) -> tuple[int, bytes, int]:
    if offset >= len(data):
        raise ValueError("truncated DER")
    tag = data[offset]
    offset += 1
    if offset >= len(data):
        raise ValueError("truncated DER length")
    length_byte = data[offset]
    offset += 1
    if length_byte & 0x80:
        length_size = length_byte & 0x7F
        if length_size == 0 or offset + length_size > len(data):
            raise ValueError("invalid DER length")
        length = int.from_bytes(data[offset:offset + length_size], "big")
        offset += length_size
    else:
        length = length_byte
    end = offset + length
    if end > len(data):
        raise ValueError("truncated DER value")
    return tag, data[offset:end], end


def _der_int(value: bytes) -> int:
    while len(value) > 1 and value[0] == 0:
        value = value[1:]
    return int.from_bytes(value, "big")


def _pem_to_der(public_key: str) -> bytes:
    lines = [
        line.strip()
        for line in public_key.strip().splitlines()
        if line.strip() and not line.startswith("-----")
    ]
    if not lines:
        raise ValueError("empty key")
    return base64.b64decode("".join(lines))


def _rsa_public_numbers_from_der(der: bytes) -> tuple[int, int]:
    tag, content, end = _parse_der_tlv(der, 0)
    if tag != 0x30 or end != len(der):
        raise ValueError("expected public key sequence")

    first_tag, first_value, next_offset = _parse_der_tlv(content, 0)
    if first_tag == 0x02:
        second_tag, second_value, final_offset = _parse_der_tlv(content, next_offset)
        if second_tag != 0x02 or final_offset != len(content):
            raise ValueError("invalid RSA public key")
        return _der_int(first_value), _der_int(second_value)

    bit_tag, bit_value, final_offset = _parse_der_tlv(content, next_offset)
    if bit_tag != 0x03 or final_offset != len(content) or not bit_value or bit_value[0] != 0:
        raise ValueError("invalid SubjectPublicKeyInfo")
    rsa_der = bit_value[1:]
    rsa_tag, rsa_content, rsa_end = _parse_der_tlv(rsa_der, 0)
    if rsa_tag != 0x30 or rsa_end != len(rsa_der):
        raise ValueError("invalid RSA key sequence")
    n_tag, n_value, n_offset = _parse_der_tlv(rsa_content, 0)
    e_tag, e_value, e_offset = _parse_der_tlv(rsa_content, n_offset)
    if n_tag != 0x02 or e_tag != 0x02 or e_offset != len(rsa_content):
        raise ValueError("invalid RSA public numbers")
    return _der_int(n_value), _der_int(e_value)


def _verify_rs256(signing_input: bytes, signature: bytes, public_key: str) -> bool:
    try:
        n, e = _rsa_public_numbers_from_der(_pem_to_der(public_key))
    except Exception:
        return False
    key_bytes = (n.bit_length() + 7) // 8
    if len(signature) != key_bytes:
        return False
    encoded = pow(int.from_bytes(signature, "big"), e, n).to_bytes(key_bytes, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(signing_input).digest()
    if not encoded.startswith(b"\x00\x01"):
        return False
    try:
        separator = encoded.index(b"\x00", 2)
    except ValueError:
        return False
    padding = encoded[2:separator]
    return len(padding) >= 8 and all(byte == 0xFF for byte in padding) and encoded[separator + 1:] == digest_info


def _verify_jwt_signature(algorithm: str, signing_input: bytes, signature: bytes) -> bool:
    if algorithm == "HS256":
        expected = hmac.new(JWT_VERIFY_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)
    if algorithm == "RS256":
        return _verify_rs256(signing_input, signature, JWT_VERIFY_KEY)
    return False


def _hash_token(token: str) -> str:
    """Hash a bearer token for lookup. Uses HMAC-SHA256 when TOKEN_SALT is configured,
    falling back to plain SHA256 for backward compatibility."""
    if TOKEN_SALT:
        return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), TOKEN_SALT, 100000).hex().lower()
    return hashlib.sha256(token.encode("utf-8")).hexdigest().lower()



def _load_token_hashes() -> dict[str, dict[str, Any]]:
    global _TOKEN_HASHES
    if _TOKEN_HASHES is not None:
        return _TOKEN_HASHES

    items: dict[str, dict[str, Any]] = {}
    raw_json = os.environ.get("SHAREDSIGNALS_TOKEN_HASHES_JSON", "").strip()
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            payload = {}
    elif TOKEN_HASH_FILE.exists():
        try:
            payload = json.loads(TOKEN_HASH_FILE.read_text())
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}

    candidates = []
    if isinstance(payload, dict):
        if isinstance(payload.get("tokens"), list):
            candidates = payload["tokens"]
        elif all(isinstance(v, dict) for v in payload.values()):
            candidates = list(payload.values())
    elif isinstance(payload, list):
        candidates = payload

    for item in candidates:
        if not isinstance(item, dict):
            continue
        token_hash = str(item.get("sha256") or item.get("token_hash") or "").strip().lower()
        if len(token_hash) != 64:
            continue
        tenant_id = str(item.get("tenant_id") or item.get("tenant") or token_hash[:12]).strip() or token_hash[:12]
        tier = str(item.get("tier") or "free").strip().lower() or "free"
        scopes = item.get("scopes", ["read"])
        if isinstance(scopes, str):
            scopes = [s.strip() for s in scopes.split(",") if s.strip()]
        if not isinstance(scopes, list) or not scopes:
            scopes = ["read"]
        raw_max_concurrent = item.get("max_concurrent")
        try:
            max_concurrent = int(raw_max_concurrent) if raw_max_concurrent is not None else None
        except (TypeError, ValueError):
            max_concurrent = None
        items[token_hash] = {
            "tenant_id": tenant_id,
            "tier": tier,
            "scopes": scopes,
            "auth_method": "token_hash",
        }
        if max_concurrent is not None and max_concurrent >= 0:
            items[token_hash]["max_concurrent"] = max_concurrent

    _TOKEN_HASHES = items
    return _TOKEN_HASHES



def _normalize_jwt_scopes(payload: dict[str, Any]) -> list[str]:
    raw_scopes = payload.get("scopes", payload.get("scope"))
    if isinstance(raw_scopes, str):
        candidates = [part.strip() for part in raw_scopes.replace(",", " ").split() if part.strip()]
    elif isinstance(raw_scopes, list):
        candidates = [str(part).strip() for part in raw_scopes if str(part).strip()]
    else:
        candidates = []

    scopes: list[str] = []
    for scope in candidates:
        if scope in SCOPE_ENDPOINTS or scope in {"*", "full"}:
            scopes.append(scope)
    return scopes or ["health"]


def _parse_jwt(token: str) -> dict[str, Any] | None:
    if not JWT_VERIFY_KEY or not JWT_ISSUER:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        signature = _b64url_decode(parts[2])
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return None

    algorithm = str(header.get("alg") or "").strip()
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    if not _verify_jwt_signature(algorithm, signing_input, signature):
        return None

    if str(payload.get("iss") or "") != JWT_ISSUER:
        return None
    try:
        expires_at = float(payload["exp"])
    except (KeyError, TypeError, ValueError):
        return None
    if expires_at + JWT_LEEWAY_SECONDS < _now():
        return None

    tenant_id = str(payload.get("tenant_id") or payload.get("tid") or payload.get("sub") or "").strip()
    tier = str(payload.get("tier") or payload.get("plan") or payload.get("role") or "free").strip().lower() or "free"
    if not tenant_id:
        return None
    return {
        "tenant_id": tenant_id,
        "tier": tier,
        "scopes": _normalize_jwt_scopes(payload),
        "auth_method": "jwt",
    }



def _extract_bearer_token(headers: Any) -> str:
    header = headers.get("Authorization", "") if headers else ""
    if header.startswith("Bearer "):
        token = header.split(" ", 1)[1].strip()
        if not token:
            raise AuthError("empty bearer token")
    else:
        token = (headers.get("X-API-Key", "") if headers else "").strip()
        if not token:
            raise AuthError("missing bearer token")
    return token


def _has_external_auth_header(headers: Any) -> bool:
    if not headers:
        return False
    authorization = headers.get("Authorization", "")
    api_key = headers.get("X-API-Key", "")
    return bool(str(authorization).strip() or str(api_key).strip())


def _has_forwarded_client_header(headers: Any) -> bool:
    if not headers:
        return False
    forwarded_headers = (
        "Forwarded",
        "X-Forwarded-For",
        "X-Real-IP",
        "X-Client-IP",
    )
    return any(bool(str(headers.get(header, "")).strip()) for header in forwarded_headers)


def authenticate(headers: Any, client_host: str) -> dict[str, Any]:
    host = (client_host or "").strip()
    if (
        host in LOCALHOSTS
        and LOCALHOST_BYPASS
        and not _has_external_auth_header(headers)
        and not _has_forwarded_client_header(headers)
    ):
        return {
            "tenant_id": "internal",
            "tier": "internal",
            "scopes": ["full"],
            "auth_method": "localhost",
        }

    token = _extract_bearer_token(headers)
    jwt_claims = _parse_jwt(token)
    if jwt_claims is not None:
        return jwt_claims

    token_hash = _hash_token(token)
    token_hashes = _load_token_hashes()
    if token_hash in token_hashes:
        return token_hashes[token_hash]
    raise AuthError("invalid token")


def check_endpoint_scope(account: dict[str, Any], path: str) -> bool:
    """Check if the account's scopes allow access to the given endpoint path."""
    scopes: list[str] = account.get("scopes", ["health"])
    if "full" in scopes or "*" in scopes:
        return True

    allowed: set[str] = set()
    for scope in scopes:
        allowed.update(SCOPE_ENDPOINTS.get(scope, set()))

    if "*" in allowed:
        return True
    return path in allowed



def enforce_rate_limit(tenant_id: str, tier: str) -> None:
    limit = RATE_LIMITS.get((tier or "free").lower(), RATE_LIMITS["free"])
    if limit is None:
        return

    now = _now()
    with _STATE_LOCK:
        if tenant_id not in _REQUEST_LOG:
            _REQUEST_LOG[tenant_id] = deque()
        bucket = _REQUEST_LOG[tenant_id]

        # Remove expired timestamps from this tenant's bucket
        while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
            bucket.popleft()

        if len(bucket) >= limit:
            raise RateLimitError(f"rate limit exceeded for tier={tier}")

        # Enforce per-tenant event cap
        while len(bucket) >= RATE_MAX_EVENTS_PER_TENANT:
            bucket.popleft()

        bucket.append(now)

        # LRU tracking: mark this tenant as recently used
        _REQUEST_LOG.move_to_end(tenant_id)

        # Periodic cleanup
        _cleanup_rate_log_locked(now)


def _account_concurrency_limit(account: dict[str, Any]) -> int | None:
    raw_limit = account.get("max_concurrent")
    if raw_limit is not None:
        try:
            value = int(raw_limit)
        except (TypeError, ValueError):
            value = 0
        return None if value <= 0 else value
    return CONCURRENCY_LIMITS.get(str(account.get("tier") or "free").lower(), CONCURRENCY_LIMITS["free"])


def claim_concurrency(account: dict[str, Any]) -> None:
    tenant_id = str(account.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ConcurrencyLimitError("missing tenant id")
    limit = _account_concurrency_limit(account)
    if limit is None:
        return
    with _STATE_LOCK:
        active = int(_ACTIVE_REQUESTS.get(tenant_id, 0))
        if active >= limit:
            raise ConcurrencyLimitError(f"concurrency limit exceeded for tenant={tenant_id}")
        _ACTIVE_REQUESTS[tenant_id] = active + 1


def release_concurrency(tenant_id: str) -> None:
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        return
    with _STATE_LOCK:
        active = int(_ACTIVE_REQUESTS.get(tenant_id, 0))
        if active <= 1:
            _ACTIVE_REQUESTS.pop(tenant_id, None)
        else:
            _ACTIVE_REQUESTS[tenant_id] = active - 1



def request_fingerprint(path: str, params: dict[str, Any]) -> str:
    normalized = json.dumps({"path": path, "params": params}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()



def get_cached_response(fingerprint: str) -> dict[str, Any] | None:
    now = _now()
    with _STATE_LOCK:
        item = _DEDUP_CACHE.get(fingerprint)
        if not item:
            return None
        if now - float(item.get("stored_at", 0.0)) > DEDUP_TTL_SECONDS:
            _drop_dedup_locked(fingerprint)
            return None
        # LRU tracking: mark as recently accessed
        _DEDUP_CACHE.move_to_end(fingerprint)
        response = copy.deepcopy(item.get("response"))
    return response



def store_cached_response(fingerprint: str, response: dict[str, Any]) -> None:
    global _DEDUP_CACHE_BYTES
    now = _now()
    size_bytes = _response_size_bytes(response)
    if DEDUP_MAX_BYTES <= 0 or size_bytes > DEDUP_MAX_ENTRY_BYTES:
        with _STATE_LOCK:
            _drop_dedup_locked(fingerprint)
        return
    with _STATE_LOCK:
        _cleanup_dedup_locked(now)
        existing = _DEDUP_CACHE.pop(fingerprint, None)
        if existing is not None:
            _DEDUP_CACHE_BYTES = max(0, _DEDUP_CACHE_BYTES - int(existing.get("size_bytes", 0)))
        _DEDUP_CACHE[fingerprint] = {
            "stored_at": now,
            "response": copy.deepcopy(response),
            "size_bytes": size_bytes,
        }
        _DEDUP_CACHE_BYTES += size_bytes
        # LRU tracking: mark as most recently stored
        _DEDUP_CACHE.move_to_end(fingerprint)
        _cleanup_dedup_locked(now)



def cache_stats() -> dict[str, Any]:
    """Return cache and rate-limit statistics for monitoring."""
    with _STATE_LOCK:
        return {
            "dedup_entries": len(_DEDUP_CACHE),
            "dedup_bytes": _DEDUP_CACHE_BYTES,
            "request_log_tenants": len(_REQUEST_LOG),
            "active_request_tenants": len(_ACTIVE_REQUESTS),
            "active_requests": sum(_ACTIVE_REQUESTS.values()),
            "concurrency_limits": dict(CONCURRENCY_LIMITS),
            "dedup_max_entries": DEDUP_MAX_ENTRIES,
            "dedup_max_bytes": DEDUP_MAX_BYTES,
            "dedup_max_entry_bytes": DEDUP_MAX_ENTRY_BYTES,
            "rate_max_tenants": RATE_MAX_TENANTS,
            "rate_max_events_per_tenant": RATE_MAX_EVENTS_PER_TENANT,
            "dedup_ttl_seconds": DEDUP_TTL_SECONDS,
            "rate_window_seconds": RATE_WINDOW_SECONDS,
        }
