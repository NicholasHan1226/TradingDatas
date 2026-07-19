#!/usr/bin/env python3
"""Authentication, rate limiting, and request dedup for TradingDatas V1."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import os
import stat
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

from env_bootstrap import env_int

ROOT = Path(__file__).resolve().parent
TOKEN_HASH_FILE_RAW = os.environ.get(
    "TRADINGDATAS_TOKEN_HASH_FILE",
    os.fspath(ROOT / "config" / "api_tokens.json"),
)
TOKEN_HASH_FILE = Path(TOKEN_HASH_FILE_RAW)
TOKEN_SALT_FILE_RAW = os.environ.get("TRADINGDATAS_TOKEN_SALT_FILE", "").strip()
TOKEN_SALT_RAW = os.environ.get("TRADINGDATAS_TOKEN_SALT", "")
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
# Retained only for existing in-process test harnesses. Authentication never
# consults this constant and no environment variable can enable a bypass.
LOCALHOST_BYPASS = False
JWT_VERIFY_KEY = os.environ.get("TRADINGDATAS_JWT_PUBLIC_KEY", "").strip()
JWT_ISSUER = os.environ.get("TRADINGDATAS_JWT_ISSUER", "").strip()
JWT_ALGORITHM = os.environ.get("TRADINGDATAS_JWT_ALGORITHM", "")
JWT_LEEWAY_SECONDS = env_int(
    "TRADINGDATAS_JWT_LEEWAY_SECONDS", 60, min_value=0, max_value=3600
)
DEDUP_TTL_SECONDS = 60
RATE_WINDOW_SECONDS = 3600
DEDUP_MAX_ENTRIES = env_int("TRADINGDATAS_DEDUP_MAX_ENTRIES", 2048, min_value=1)
DEDUP_MAX_BYTES = env_int("TRADINGDATAS_DEDUP_MAX_BYTES", 10 * 1024 * 1024, min_value=0)
DEDUP_MAX_ENTRY_BYTES = env_int(
    "TRADINGDATAS_DEDUP_MAX_ENTRY_BYTES", 1024 * 1024, min_value=1
)
RATE_MAX_TENANTS = env_int("TRADINGDATAS_RATE_MAX_TENANTS", 1024, min_value=1)
RATE_MAX_EVENTS_PER_TENANT = env_int(
    "TRADINGDATAS_RATE_MAX_EVENTS_PER_TENANT", 1000, min_value=1
)

V1_DATA_ENDPOINTS = {"/v1/catalog", "/v1/query"}

SCOPE_ENDPOINTS: dict[str, set[str]] = {
    "catalog": {"/v1/catalog"},
    "query": {"/v1/query"},
    "read": V1_DATA_ENDPOINTS,
    "external_read": V1_DATA_ENDPOINTS,
    "internal": V1_DATA_ENDPOINTS,
    "full": V1_DATA_ENDPOINTS,
}

_STATE_LOCK = threading.Lock()
_REQUEST_LOG: OrderedDict[str, deque[float]] = OrderedDict()
_ACTIVE_REQUESTS: dict[str, int] = {}
_DEDUP_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_DEDUP_CACHE_BYTES = 0
_TOKEN_HASHES: dict[str, dict[str, Any]] | None = None
_TOKEN_SALT: bytes | None = None
_EPHEMERAL_TOKEN_SALT = os.urandom(32)


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
        return len(
            json.dumps(
                response, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        )
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
        key
        for key, item in _DEDUP_CACHE.items()
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
        length = int.from_bytes(data[offset : offset + length_size], "big")
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
    if (
        bit_tag != 0x03
        or final_offset != len(content)
        or not bit_value
        or bit_value[0] != 0
    ):
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
    digest_info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256(signing_input).digest()
    )
    if not encoded.startswith(b"\x00\x01"):
        return False
    try:
        separator = encoded.index(b"\x00", 2)
    except ValueError:
        return False
    padding = encoded[2:separator]
    return (
        len(padding) >= 8
        and all(byte == 0xFF for byte in padding)
        and encoded[separator + 1 :] == digest_info
    )


def _verify_jwt_signature(
    algorithm: str, signing_input: bytes, signature: bytes
) -> bool:
    if JWT_ALGORITHM not in {"HS256", "RS256"} or algorithm != JWT_ALGORITHM:
        return False
    if JWT_ALGORITHM == "HS256":
        if "-----BEGIN " in JWT_VERIFY_KEY or "-----END " in JWT_VERIFY_KEY:
            return False
        try:
            key_bytes = JWT_VERIFY_KEY.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return False
        if len(key_bytes) < 32:
            return False
        expected = hmac.new(key_bytes, signing_input, hashlib.sha256).digest()
        return hmac.compare_digest(expected, signature)
    if JWT_ALGORITHM == "RS256":
        lines = JWT_VERIFY_KEY.splitlines()
        if len(lines) < 3 or (lines[0], lines[-1]) not in {
            ("-----BEGIN PUBLIC KEY-----", "-----END PUBLIC KEY-----"),
            (
                "-----BEGIN RSA PUBLIC KEY-----",
                "-----END RSA PUBLIC KEY-----",
            ),
        }:
            return False
        return _verify_rs256(signing_input, signature, JWT_VERIFY_KEY)
    return False


def _private_file_bytes(raw_path: str, *, label: str, max_bytes: int) -> bytes:
    if (
        not raw_path.startswith("/")
        or raw_path.startswith("//")
        or os.path.normpath(raw_path) != raw_path
    ):
        raise AuthError(f"{label} path must be absolute lexical canonical")
    path = Path(raw_path)
    components = path.parts[1:]
    if not components:
        raise AuthError(f"{label} file is unavailable")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    file_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_descriptors: list[int] = []
    directory_bindings: list[tuple[int, str, int]] = []
    descriptor: int | None = None
    primary_error: BaseException | None = None
    try:
        directory_descriptors.append(os.open(path.anchor, directory_flags))
        for component in components[:-1]:
            parent_descriptor = directory_descriptors[-1]
            try:
                named = os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                child_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_descriptor,
                )
            except OSError as exc:
                raise AuthError(f"{label} path is unavailable") from exc
            directory_descriptors.append(child_descriptor)
            opened = os.fstat(child_descriptor)
            if stat.S_ISLNK(named.st_mode):
                raise AuthError(f"{label} path may not contain a symlink")
            if not stat.S_ISDIR(named.st_mode) or not stat.S_ISDIR(opened.st_mode):
                raise AuthError(f"{label} path is unavailable")
            if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
                raise AuthError(f"{label} path binding changed while opening")
            directory_bindings.append((parent_descriptor, component, child_descriptor))

        parent_descriptor = directory_descriptors[-1]
        filename = components[-1]
        try:
            named_before = os.stat(
                filename,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            descriptor = os.open(filename, file_flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise AuthError(f"{label} file is unavailable") from exc
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AuthError(f"{label} must be one regular file")
        if before.st_uid != os.geteuid():
            raise AuthError(f"{label} owner is unsafe")
        if stat.S_IMODE(before.st_mode) != 0o600:
            raise AuthError(f"{label} mode must be 0600")
        binding_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_uid,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        named_binding_before = (
            named_before.st_dev,
            named_before.st_ino,
            named_before.st_mode,
            named_before.st_nlink,
            named_before.st_uid,
            named_before.st_size,
            named_before.st_mtime_ns,
            named_before.st_ctime_ns,
        )
        if named_binding_before != binding_before:
            raise AuthError(f"{label} binding changed while opening")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        try:
            named_after = os.stat(
                filename,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise AuthError(f"{label} binding changed while reading") from exc
        binding_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_uid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        named_binding_after = (
            named_after.st_dev,
            named_after.st_ino,
            named_after.st_mode,
            named_after.st_nlink,
            named_after.st_uid,
            named_after.st_size,
            named_after.st_mtime_ns,
            named_after.st_ctime_ns,
        )
        if binding_before != binding_after or binding_after != named_binding_after:
            raise AuthError(f"{label} binding changed while reading")
        for parent_fd, component, child_fd in directory_bindings:
            try:
                named_directory = os.stat(
                    component,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise AuthError(f"{label} path binding changed while reading") from exc
            opened_directory = os.fstat(child_fd)
            if (named_directory.st_dev, named_directory.st_ino) != (
                opened_directory.st_dev,
                opened_directory.st_ino,
            ):
                raise AuthError(f"{label} path binding changed while reading")
        if len(data) > max_bytes:
            raise AuthError(f"{label} file is too large")
        if len(data) != before.st_size:
            raise AuthError(f"{label} file changed while reading")
        return data
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error: OSError | None = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                cleanup_error = exc
        for directory_descriptor in reversed(directory_descriptors):
            try:
                os.close(directory_descriptor)
            except OSError as exc:
                cleanup_error = cleanup_error or exc
        if cleanup_error is not None and primary_error is None:
            raise AuthError(f"{label} descriptor cleanup failed") from cleanup_error


def _load_token_salt(*, required: bool) -> bytes:
    global _TOKEN_SALT
    if _TOKEN_SALT is not None:
        return _TOKEN_SALT
    if TOKEN_SALT_FILE_RAW and TOKEN_SALT_RAW:
        raise AuthError("token salt configuration is ambiguous")
    if TOKEN_SALT_FILE_RAW:
        raw = _private_file_bytes(
            TOKEN_SALT_FILE_RAW,
            label="token salt",
            max_bytes=4096,
        ).strip()
    elif TOKEN_SALT_RAW:
        raw = TOKEN_SALT_RAW.encode("utf-8")
    elif required:
        raise AuthError("token salt is required")
    else:
        return _EPHEMERAL_TOKEN_SALT
    if len(raw) < 16:
        raise AuthError("token salt must contain at least 16 bytes")
    _TOKEN_SALT = raw
    return raw


def _hash_token(token: str) -> str:
    """Hash a bearer token with PBKDF2; plain SHA compatibility is forbidden."""

    salt = _load_token_salt(required=False)
    return (
        hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 100000).hex().lower()
    )


def _load_token_hashes() -> dict[str, dict[str, Any]]:
    global _TOKEN_HASHES
    if _TOKEN_HASHES is not None:
        return _TOKEN_HASHES

    _load_token_salt(required=True)

    items: dict[str, dict[str, Any]] = {}
    raw_json = os.environ.get("TRADINGDATAS_TOKEN_HASHES_JSON", "").strip()
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise AuthError("token hash configuration is invalid") from exc
    elif os.path.lexists(TOKEN_HASH_FILE_RAW):
        try:
            payload = json.loads(
                _private_file_bytes(
                    TOKEN_HASH_FILE_RAW,
                    label="token hash",
                    max_bytes=1024 * 1024,
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthError("token hash configuration is invalid") from exc
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
        token_hash = str(item.get("token_hash") or "").strip().lower()
        if len(token_hash) != 64:
            continue
        tenant_id = (
            str(item.get("tenant_id") or item.get("tenant") or token_hash[:12]).strip()
            or token_hash[:12]
        )
        tier = str(item.get("tier") or "free").strip().lower() or "free"
        scopes = item.get("scopes", ["read"])
        if isinstance(scopes, str):
            scopes = [s.strip() for s in scopes.split(",") if s.strip()]
        if not isinstance(scopes, list) or not scopes:
            scopes = ["read"]
        raw_max_concurrent = item.get("max_concurrent")
        try:
            max_concurrent = (
                int(raw_max_concurrent) if raw_max_concurrent is not None else None
            )
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
        candidates = [
            part.strip()
            for part in raw_scopes.replace(",", " ").split()
            if part.strip()
        ]
    elif isinstance(raw_scopes, list):
        candidates = [str(part).strip() for part in raw_scopes if str(part).strip()]
    else:
        candidates = []

    scopes: list[str] = []
    for scope in candidates:
        if scope in SCOPE_ENDPOINTS or scope in {"*", "full"}:
            scopes.append(scope)
    return scopes or ["catalog"]


def _parse_jwt(token: str) -> dict[str, Any] | None:
    if not JWT_VERIFY_KEY or not JWT_ISSUER or JWT_ALGORITHM not in {"HS256", "RS256"}:
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
    if type(header) is not dict or type(payload) is not dict:
        return None

    raw_algorithm = header.get("alg")
    if type(raw_algorithm) is not str:
        return None
    algorithm = raw_algorithm
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

    tenant_id = str(
        payload.get("tenant_id") or payload.get("tid") or payload.get("sub") or ""
    ).strip()
    tier = (
        str(payload.get("tier") or payload.get("plan") or payload.get("role") or "free")
        .strip()
        .lower()
        or "free"
    )
    if not tenant_id:
        return None
    return {
        "tenant_id": tenant_id,
        "tier": tier,
        "scopes": _normalize_jwt_scopes(payload),
        "auth_method": "jwt",
    }


def _header_values(headers: Any, name: str) -> tuple[str, ...]:
    """Return every physical header value without last-value-wins behavior."""

    if not headers:
        return ()
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all(name, [])
        return tuple(str(value) for value in values)
    value = headers.get(name) if hasattr(headers, "get") else None
    return () if value is None else (str(value),)


def _extract_bearer_token(headers: Any) -> str:
    authorization_values = _header_values(headers, "Authorization")
    api_key_values = _header_values(headers, "X-API-Key")
    if (
        len(authorization_values) > 1
        or len(api_key_values) > 1
        or (authorization_values and api_key_values)
    ):
        raise AuthError("ambiguous credential")
    if authorization_values:
        header = authorization_values[0]
        if not header.startswith("Bearer "):
            raise AuthError("invalid bearer token")
        token = header.split(" ", 1)[1].strip()
        if not token:
            raise AuthError("empty bearer token")
        return token
    if api_key_values:
        token = api_key_values[0].strip()
        if not token:
            raise AuthError("empty api key")
        return token
    raise AuthError("missing bearer token")


def authenticate(headers: Any, client_host: str) -> dict[str, Any]:
    del client_host

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
    allowed: set[str] = set()
    for scope in scopes:
        normalized = "full" if scope == "*" else scope
        allowed.update(SCOPE_ENDPOINTS.get(normalized, set()))
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
    return CONCURRENCY_LIMITS.get(
        str(account.get("tier") or "free").lower(), CONCURRENCY_LIMITS["free"]
    )


def claim_concurrency(account: dict[str, Any]) -> bool:
    """Claim one counted tenant slot and report whether release is required."""

    tenant_id = str(account.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ConcurrencyLimitError("missing tenant id")
    limit = _account_concurrency_limit(account)
    if limit is None:
        return False
    with _STATE_LOCK:
        active = int(_ACTIVE_REQUESTS.get(tenant_id, 0))
        if active >= limit:
            raise ConcurrencyLimitError(
                f"concurrency limit exceeded for tenant={tenant_id}"
            )
        _ACTIVE_REQUESTS[tenant_id] = active + 1
    return True


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
    normalized = json.dumps(
        {"path": path, "params": params},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
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
            _DEDUP_CACHE_BYTES = max(
                0, _DEDUP_CACHE_BYTES - int(existing.get("size_bytes", 0))
            )
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
