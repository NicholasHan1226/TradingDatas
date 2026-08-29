#!/usr/bin/env python3
"""Authentication, rate limiting, and request dedup for TradingDatas V1."""

from __future__ import annotations

import atexit
import base64
import binascii
import copy
import datetime
import functools
import hashlib
import hmac
import json
import os
import re
import stat
import threading
import tempfile
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

from env_bootstrap import env_int

ROOT = Path(__file__).resolve().parent
_UTC = datetime.timezone.utc
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
    # Commercial tiers use a sliding minute window below, never an hourly
    # fallback.
    "basic": None,
    "standard": None,
    "flagship": None,
    "enterprise": None,
    "internal": None,
}
COMMERCIAL_TIERS = frozenset({"basic", "standard", "flagship"})
MINUTE_RATE_LIMITS: dict[str, int] = {
    "basic": 200,
    "standard": 600,
    "flagship": 1000,
}
CONCURRENCY_LIMITS = {
    "free": 2,
    "starter": 2,
    "research": 4,
    "pro": 8,
    # Commercial plans are differentiated only by minute request frequency.
    "basic": None,
    "standard": None,
    "flagship": None,
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
ADMIN_ENDPOINTS = {"/admin/"}

SCOPE_ENDPOINTS: dict[str, set[str]] = {
    "catalog": {"/v1/catalog"},
    "query": {"/v1/query"},
    "read": V1_DATA_ENDPOINTS,
    "external_read": V1_DATA_ENDPOINTS,
    "internal": V1_DATA_ENDPOINTS,
    "full": V1_DATA_ENDPOINTS,
    "admin": ADMIN_ENDPOINTS,
}

# Stable product-facing entitlements. They intentionally do not expose
# provider names: registry market/domain metadata is mapped to these values at
# the API boundary. A missing ``data_categories`` field remains the legacy
# unrestricted mode so existing credentials keep their current access.
DATA_CATEGORIES = ("a_share", "crypto", "news")

_STATE_LOCK = threading.Lock()
_TOKEN_MUTATION_LOCK = threading.RLock()
_REQUEST_LOG: OrderedDict[str, deque[float]] = OrderedDict()
# Sliding per-minute store used by the three commercial tiers.
MINUTE_RATE_WINDOW_SECONDS = 60
_MINUTE_REQUEST_LOG: OrderedDict[str, deque[float]] = OrderedDict()
_DAILY_REQUEST_LOG: OrderedDict[str, dict[str, Any]] = OrderedDict()
_ACTIVE_REQUESTS: dict[str, int] = {}
# Cheap per-host pre-auth limiter: bounds PBKDF2 work spent on garbage bearer
# tokens before any expensive key derivation runs. Counts every authentication
# attempt (JWT-shaped or bearer) per client host inside a sliding window.
_PREAUTH_WINDOW_SECONDS = 60.0
# Independent per-IP abuse wall. It is not a commercial request quota and stays
# intentionally high enough for normal multi-agent traffic.
_PREAUTH_MAX_ATTEMPTS = max(
    1, int(os.environ.get("TRADINGDATAS_PREAUTH_RATE_LIMIT", "1200"))
)
_PREAUTH_LOG: OrderedDict[str, deque[float]] = OrderedDict()
_PREAUTH_MAX_HOSTS = 10000
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

    # Same housekeeping for any compatibility minute-window entries.
    empty_minute_tenants: list[str] = []
    for tenant_id, bucket in _MINUTE_REQUEST_LOG.items():
        while bucket and now - bucket[0] > MINUTE_RATE_WINDOW_SECONDS:
            bucket.popleft()
        if not bucket:
            empty_minute_tenants.append(tenant_id)
    for tenant_id in empty_minute_tenants:
        _MINUTE_REQUEST_LOG.pop(tenant_id, None)


def _enforce_preauth_limit(host: str) -> None:
    """Sliding-window per-host cap enforced before PBKDF2 key derivation.

    Every authentication attempt is recorded cheaply; once a host exceeds
    ``_PREAUTH_MAX_ATTEMPTS`` inside the window, further attempts are rejected
    before any expensive token hashing happens so garbage-token floods cannot
    burn CPU. Must not be called while _STATE_LOCK is held (authenticate
    performs file I/O afterwards).
    """
    now = _now()
    with _STATE_LOCK:
        bucket = _PREAUTH_LOG.get(host)
        if bucket is None:
            bucket = deque()
            _PREAUTH_LOG[host] = bucket
        while bucket and now - bucket[0] > _PREAUTH_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _PREAUTH_MAX_ATTEMPTS:
            raise RateLimitError(
                f"pre-auth rate limit exceeded for host={host}"
            )
        bucket.append(now)
        _PREAUTH_LOG.move_to_end(host)

        # Drop expired/empty buckets and evict oldest hosts when over capacity.
        expired_hosts = []
        for known_host, known_bucket in _PREAUTH_LOG.items():
            while (
                known_bucket and now - known_bucket[0] > _PREAUTH_WINDOW_SECONDS
            ):
                known_bucket.popleft()
            if not known_bucket:
                expired_hosts.append(known_host)
        for known_host in expired_hosts:
            _PREAUTH_LOG.pop(known_host, None)
        while len(_PREAUTH_LOG) > _PREAUTH_MAX_HOSTS:
            _PREAUTH_LOG.pop(next(iter(_PREAUTH_LOG)), None)

        # Evict oldest (LRU) tenants when over capacity
        while len(_REQUEST_LOG) > RATE_MAX_TENANTS:
            _REQUEST_LOG.popitem(last=False)
        while len(_MINUTE_REQUEST_LOG) > RATE_MAX_TENANTS:
            _MINUTE_REQUEST_LOG.popitem(last=False)


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


def _parse_expires_at(raw: Any) -> float | None:
    """Parse expires_at as RFC3339 string or Unix timestamp."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                from datetime import datetime as _dt
                dt = _dt.strptime(raw, fmt)
                if dt.tzinfo is None:
                    from datetime import timezone as _tz
                    dt = dt.replace(tzinfo=_tz.utc)
                return dt.timestamp()
            except ValueError:
                continue
    return None


def normalize_data_categories(raw: Any) -> list[str]:
    """Validate one explicit category allowlist in canonical product order."""

    if type(raw) is not list:
        raise AuthError("data_categories must be a list")
    if any(type(value) is not str for value in raw):
        raise AuthError("data_categories contains an invalid value")
    unknown = sorted(set(raw) - set(DATA_CATEGORIES))
    if unknown:
        raise AuthError("data_categories contains an unknown category")
    return [category for category in DATA_CATEGORIES if category in set(raw)]


def effective_data_categories(account: dict[str, Any]) -> list[str]:
    """Return effective categories without mutating the authenticated record."""

    if "data_categories" not in account:
        return list(DATA_CATEGORIES)
    return normalize_data_categories(account["data_categories"])


def _utc_today_key() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
        parsed: dict[str, Any] = {
            "tenant_id": tenant_id,
            "tier": tier,
            "scopes": scopes,
            "auth_method": "token_hash",
        }
        if "data_categories" in item:
            parsed["data_categories"] = normalize_data_categories(
                item["data_categories"]
            )
        if (
            tier not in COMMERCIAL_TIERS
            and max_concurrent is not None
            and max_concurrent >= 0
        ):
            parsed["max_concurrent"] = max_concurrent

        raw_enabled = item.get("enabled")
        if raw_enabled is not None:
            parsed["enabled"] = bool(raw_enabled)

        raw_daily_limit = item.get("daily_limit")
        if raw_daily_limit is not None and tier not in COMMERCIAL_TIERS:
            try:
                daily_limit = int(raw_daily_limit)
                if daily_limit > 0:
                    parsed["daily_limit"] = daily_limit
            except (TypeError, ValueError):
                pass

        raw_expires = item.get("expires_at")
        if raw_expires is not None:
            expires_ts = _parse_expires_at(raw_expires)
            if expires_ts is not None:
                parsed["expires_at"] = expires_ts

        items[token_hash] = parsed

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
    account = {
        "tenant_id": tenant_id,
        "tier": tier,
        "scopes": _normalize_jwt_scopes(payload),
        "auth_method": "jwt",
    }
    if "data_categories" in payload:
        account["data_categories"] = normalize_data_categories(
            payload["data_categories"]
        )
    return account


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
    host = str(client_host or "unknown")
    _enforce_preauth_limit(host)

    token = _extract_bearer_token(headers)
    jwt_claims = _parse_jwt(token)
    if jwt_claims is not None:
        return jwt_claims

    token_hash = _hash_token(token)
    token_hashes = _load_token_hashes()
    if token_hash in token_hashes:
        binding = token_hashes[token_hash]
        if binding.get("enabled") is False:
            raise AuthError("token is disabled")
        expires_at = binding.get("expires_at")
        if expires_at is not None and _now() >= float(expires_at):
            raise AuthError("token has expired")
        account = dict(binding)
        # Internal request context for tenant-scoped credential management.
        # Never project this value in a public response.
        account["_credential_hash"] = token_hash
        return account
    raise AuthError("invalid token")


def check_endpoint_scope(account: dict[str, Any], path: str) -> bool:
    """Check if the account's scopes allow access to the given endpoint path."""
    scopes: list[str] = account.get("scopes", ["health"])
    allowed: set[str] = set()
    for scope in scopes:
        normalized = "full" if scope == "*" else scope
        allowed.update(SCOPE_ENDPOINTS.get(normalized, set()))
    return path in allowed


def _enforce_window(
    buckets: dict,
    tenant_id: str,
    limit: int,
    window_seconds: float,
    message: str,
) -> None:
    """One sliding-window check inside ``_STATE_LOCK``; appends on success."""

    now = _now()
    if tenant_id not in buckets:
        buckets[tenant_id] = deque()
    bucket = buckets[tenant_id]

    # Remove expired timestamps from this tenant's bucket
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()

    if len(bucket) >= limit:
        raise RateLimitError(message)

    # Enforce per-tenant event cap
    while len(bucket) >= RATE_MAX_EVENTS_PER_TENANT:
        bucket.popleft()

    bucket.append(now)

    # LRU tracking: mark this tenant as recently used
    buckets.move_to_end(tenant_id)


def enforce_rate_limit(tenant_id: str, tier: str) -> None:
    normalized = (tier or "free").lower()

    minute_limit = MINUTE_RATE_LIMITS.get(normalized)
    if minute_limit is not None:
        with _STATE_LOCK:
            _enforce_window(
                _MINUTE_REQUEST_LOG,
                tenant_id,
                minute_limit,
                MINUTE_RATE_WINDOW_SECONDS,
                f"minute rate limit exceeded for tier={normalized}",
            )
            _cleanup_rate_log_locked(_now())

    hourly_limit = RATE_LIMITS.get(normalized, RATE_LIMITS["free"])
    if hourly_limit is None:
        # Enterprise/internal remain unmetered unless a per-token daily limit is
        # explicitly configured; current commercial tiers returned above.
        return

    with _STATE_LOCK:
        _enforce_window(
            _REQUEST_LOG,
            tenant_id,
            hourly_limit,
            RATE_WINDOW_SECONDS,
            f"rate limit exceeded for tier={normalized}",
        )
        _cleanup_rate_log_locked(_now())


_USAGE_HISTORY_FILE = os.environ.get(
    "TRADINGDATAS_USAGE_HISTORY",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config",
        "api_usage_history.json",
    ),
)
# date -> {tenant_id: request_count}; persisted for usage history queries.
_USAGE_HISTORY: dict[str, dict[str, int]] = {}
_USAGE_HISTORY_LOADED = False


def _load_usage_history_locked() -> dict[str, dict[str, int]]:
    global _USAGE_HISTORY_LOADED
    if _USAGE_HISTORY_LOADED:
        return _USAGE_HISTORY
    _USAGE_HISTORY_LOADED = True
    try:
        with open(_USAGE_HISTORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for date, tenants in data.items():
                if isinstance(tenants, dict):
                    _USAGE_HISTORY.setdefault(str(date), {
                        str(t): int(c) for t, c in tenants.items()
                        if isinstance(c, (int, float))
                    })
    except (OSError, ValueError):
        pass
    return _USAGE_HISTORY


def _flush_usage_history_locked() -> None:
    if not _USAGE_HISTORY:
        return
    tmp_path = _USAGE_HISTORY_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(_USAGE_HISTORY_FILE), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(_USAGE_HISTORY, fh, sort_keys=True)
        os.replace(tmp_path, _USAGE_HISTORY_FILE)
    except OSError:
        pass


def get_usage_history(days: int = 30) -> list[dict[str, Any]]:
    """Return daily usage history for the last N days (UTC), oldest first."""
    today = _utc_today_key()
    year, month, day = (int(x) for x in today.split("-"))
    start = datetime.datetime(year, month, day, tzinfo=_UTC) - datetime.timedelta(days=max(0, days - 1))
    out: list[dict[str, Any]] = []
    with _STATE_LOCK:
        _load_usage_history_locked()
        # Sync today's in-memory daily counters into history before reading.
        for tenant_id, entry in _DAILY_REQUEST_LOG.items():
            date_key = entry.get("date")
            if date_key == today and entry.get("count"):
                day_counts = _USAGE_HISTORY.setdefault(date_key, {})
                day_counts[tenant_id] = entry["count"]
        for offset in range(max(0, days)):
            date_key = (start + datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
            tenants = _USAGE_HISTORY.get(date_key, {})
            out.append({
                "date": date_key,
                "total": sum(tenants.values()),
                "by_tenant": dict(sorted(tenants.items())),
            })
        _flush_usage_history_locked()
    return out


def _flush_usage_history_on_exit() -> None:
    try:
        with _STATE_LOCK:
            _flush_usage_history_locked()
    except Exception:
        pass


atexit.register(_flush_usage_history_on_exit)


def enforce_daily_limit(account: dict[str, Any]) -> None:
    """Count every authenticated request and enforce legacy per-tenant limits."""
    tier = str(account.get("tier") or "free").lower()
    daily_limit = (
        None if tier in COMMERCIAL_TIERS else account.get("daily_limit")
    )
    tenant_id = str(account.get("tenant_id") or "").strip()
    if not tenant_id:
        return

    today = _utc_today_key()
    now = _now()
    with _STATE_LOCK:
        entry = _DAILY_REQUEST_LOG.get(tenant_id)
        if entry is None or entry.get("date") != today:
            _DAILY_REQUEST_LOG[tenant_id] = {"date": today, "count": 0, "reset_at": now}
            entry = _DAILY_REQUEST_LOG[tenant_id]
        if daily_limit is not None and entry["count"] >= int(daily_limit):
            raise RateLimitError(
                f"daily limit exceeded for tenant={tenant_id} "
                f"(limit={daily_limit}, used={entry['count']})"
            )
        entry["count"] += 1
        entry["daily_limit"] = daily_limit
        _DAILY_REQUEST_LOG.move_to_end(tenant_id)

        _load_usage_history_locked()
        day_counts = _USAGE_HISTORY.setdefault(today, {})
        day_counts[tenant_id] = entry["count"]

        # Cleanup stale entries
        stale = [k for k, v in _DAILY_REQUEST_LOG.items() if v.get("date") != today]
        for k in stale:
            _DAILY_REQUEST_LOG.pop(k, None)


def get_daily_usage() -> dict[str, dict[str, Any]]:
    """Return current daily usage for all tenants."""
    today = _utc_today_key()
    with _STATE_LOCK:
        result: dict[str, dict[str, Any]] = {}
        for tenant_id, entry in _DAILY_REQUEST_LOG.items():
            if entry.get("date") == today:
                result[tenant_id] = {
                    "date": today,
                    "count": entry["count"],
                    "daily_limit": entry.get("daily_limit"),
                }
        return result


def get_hourly_usage() -> dict[str, dict[str, Any]]:
    """Return current effective rate-window usage for all tenants.

    The public admin response keeps its legacy ``hourly`` key for compatibility,
    while every row carries its actual ``window_seconds``. Commercial plans use
    the minute bucket; legacy plans continue to use the hourly bucket.
    """
    now = _now()
    bindings = list(_load_token_hashes().values())
    hourly_limits: dict[str, list[int]] = {}
    minute_limits: dict[str, list[int]] = {}
    for binding in bindings:
        tenant_id = str(binding.get("tenant_id") or "").strip()
        tier = str(binding.get("tier") or "free").lower()
        if not tenant_id:
            continue
        hourly_limit = RATE_LIMITS.get(tier, RATE_LIMITS["free"])
        minute_limit = MINUTE_RATE_LIMITS.get(tier)
        if hourly_limit is not None:
            hourly_limits.setdefault(tenant_id, []).append(hourly_limit)
        if minute_limit is not None:
            minute_limits.setdefault(tenant_id, []).append(minute_limit)

    with _STATE_LOCK:
        result: dict[str, dict[str, Any]] = {}
        for tenant_id, bucket in _REQUEST_LOG.items():
            count = sum(1 for t in bucket if now - t <= RATE_WINDOW_SECONDS)
            if count > 0:
                limits = hourly_limits.get(tenant_id, [])
                result[tenant_id] = {
                    "count_in_window": count,
                    "window_seconds": RATE_WINDOW_SECONDS,
                    "tier_limit": min(limits) if limits else RATE_LIMITS["free"],
                }
        for tenant_id, bucket in _MINUTE_REQUEST_LOG.items():
            count = sum(1 for t in bucket if now - t <= MINUTE_RATE_WINDOW_SECONDS)
            if count > 0:
                limits = minute_limits.get(tenant_id, [])
                result[tenant_id] = {
                    "count_in_window": count,
                    "window_seconds": MINUTE_RATE_WINDOW_SECONDS,
                    "tier_limit": min(limits) if limits else None,
                }
        return result


def reload_token_hashes() -> None:
    """Force reload of token hashes from config file."""
    global _TOKEN_HASHES
    with _STATE_LOCK:
        _TOKEN_HASHES = None


def list_tokens() -> list[dict[str, Any]]:
    """List all configured tokens with masked hashes."""
    hashes = _load_token_hashes()
    result = []
    for token_hash, binding in hashes.items():
        masked = token_hash[:8] + "..." + token_hash[-4:]
        entry: dict[str, Any] = {
            "token_hash_masked": masked,
            "token_hash_full": token_hash,
            "tenant_id": binding.get("tenant_id", ""),
            "tier": binding.get("tier", "free"),
            "scopes": binding.get("scopes", []),
            "enabled": binding.get("enabled", True),
            "data_categories": effective_data_categories(binding),
            "data_category_mode": (
                "restricted" if "data_categories" in binding else "all"
            ),
            "max_concurrent": _account_concurrency_limit(binding),
            "minute_request_limit": effective_limits(binding)["minute_request_limit"],
        }
        if "daily_limit" in binding:
            entry["daily_limit"] = binding["daily_limit"]
        if "expires_at" in binding:
            from datetime import datetime, timezone
            ts = float(binding["expires_at"])
            entry["expires_at"] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            entry["expired"] = _now() >= ts
        result.append(entry)
    return result


def _read_token_file() -> dict[str, Any]:
    """Read the raw token config file."""
    if os.environ.get("TRADINGDATAS_TOKEN_HASHES_JSON", "").strip():
        raise AuthError("token management not supported with env-based config")
    if not os.path.lexists(TOKEN_HASH_FILE_RAW):
        return {"tokens": []}
    raw = _private_file_bytes(
        TOKEN_HASH_FILE_RAW, label="token hash", max_bytes=1024 * 1024
    )
    return json.loads(raw.decode("utf-8"))


def _write_token_file(payload: dict[str, Any]) -> None:
    """Atomically replace the existing private token config file."""
    if os.environ.get("TRADINGDATAS_TOKEN_HASHES_JSON", "").strip():
        raise AuthError("token management not supported with env-based config")
    path = Path(TOKEN_HASH_FILE_RAW)
    if not path.exists():
        raise AuthError("token config file does not exist; create it first")
    if path.is_symlink():
        raise AuthError("token config file must not be a symlink")
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    mode = stat.S_IMODE(path.stat().st_mode)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            os.chmod(temp_path, mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    reload_token_hashes()


def _serialized_token_mutation(function):
    @functools.wraps(function)
    def _wrapped(*args, **kwargs):
        with _TOKEN_MUTATION_LOCK:
            return function(*args, **kwargs)

    return _wrapped


@_serialized_token_mutation
def create_token(
    tenant_id: str,
    tier: str = "free",
    scopes: list[str] | None = None,
    max_concurrent: int | None = None,
    daily_limit: int | None = None,
    expires_at: str | None = None,
    data_categories: list[str] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Create a new API token and return it (only time the raw token is visible)."""
    import secrets
    normalized_tier = str(tier or "free").strip().lower() or "free"
    if normalized_tier in COMMERCIAL_TIERS and daily_limit is not None:
        raise AuthError(
            f"commercial tier={normalized_tier} does not support daily_limit"
        )
    if normalized_tier in COMMERCIAL_TIERS and max_concurrent is not None:
        raise AuthError(
            f"commercial tier={normalized_tier} does not support max_concurrent"
        )
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)

    payload = _read_token_file()
    tokens = payload.get("tokens", payload if isinstance(payload, list) else [])
    if isinstance(payload, dict) and "tokens" not in payload:
        tokens = list(payload.values()) if all(isinstance(v, dict) for v in payload.values()) else []

    entry: dict[str, Any] = {
        "tenant_id": tenant_id,
        "tier": normalized_tier,
        "scopes": scopes or ["read"],
        "token_hash": token_hash,
        "enabled": True,
        "created_at": datetime.datetime.now(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if label is not None:
        normalized_label = _normalize_token_label(label)
        entry["label"] = normalized_label
    if max_concurrent is not None:
        entry["max_concurrent"] = max_concurrent
    if daily_limit is not None:
        entry["daily_limit"] = daily_limit
    if expires_at is not None:
        entry["expires_at"] = expires_at
    if data_categories is not None:
        entry["data_categories"] = normalize_data_categories(data_categories)

    tokens.append(entry)
    payload = {"tokens": tokens}
    _write_token_file(payload)

    return {"token": raw_token, "token_hash": token_hash, "tenant_id": tenant_id}


def _normalize_token_label(raw: Any) -> str:
    if type(raw) is not str:
        raise AuthError("key label must be a string")
    label = " ".join(raw.strip().split())
    if not label or len(label) > 64:
        raise AuthError("key label must contain 1 to 64 characters")
    return label


def _customer_key_id(token_hash: str) -> str:
    return f"key_{token_hash[:16]}"


def _customer_credential_hash(account: dict[str, Any]) -> str:
    token_hash = str(account.get("_credential_hash") or "").lower()
    if len(token_hash) != 64:
        raise AuthError("API key management requires a token-hash credential")
    return token_hash


def _customer_key_projection(
    item: dict[str, Any], *, current_hash: str
) -> dict[str, Any]:
    token_hash = str(item.get("token_hash") or "").lower()
    return {
        "key_id": _customer_key_id(token_hash),
        "label": str(item.get("label") or "API key"),
        "enabled": item.get("enabled") is not False,
        "created_at": item.get("created_at"),
        "last_used_at": item.get("last_used_at"),
        "is_current": token_hash == current_hash,
        "fingerprint": f"{token_hash[:8]}...{token_hash[-4:]}",
    }


def list_customer_tokens(account: dict[str, Any]) -> list[dict[str, Any]]:
    """List only the authenticated tenant's keys without exposing hashes."""

    current_hash = _customer_credential_hash(account)
    tenant_id = str(account.get("tenant_id") or "").strip()
    payload = _read_token_file()
    tokens = payload.get("tokens", [])
    visible = [
        _customer_key_projection(item, current_hash=current_hash)
        for item in tokens
        if str(item.get("tenant_id") or item.get("tenant") or "").strip()
        == tenant_id
        and len(str(item.get("token_hash") or "")) == 64
    ]
    return sorted(
        visible,
        key=lambda item: (not item["is_current"], str(item.get("created_at") or "")),
    )


@_serialized_token_mutation
def create_customer_token(account: dict[str, Any], label: str) -> dict[str, Any]:
    """Create one same-tenant key that cannot exceed current effective access."""

    current_hash = _customer_credential_hash(account)
    normalized_label = _normalize_token_label(label)
    tenant_id = str(account.get("tenant_id") or "").strip()
    if not tenant_id:
        raise AuthError("missing tenant id")
    existing = list_customer_tokens(account)
    if len(existing) >= 10:
        raise AuthError("customer API key limit reached")
    inherited_scopes = [
        str(scope)
        for scope in account.get("scopes", [])
        if str(scope) not in {"admin", "*", "full"}
    ]
    if not inherited_scopes:
        raise AuthError("current credential has no delegable data scope")
    created = create_token(
        tenant_id=tenant_id,
        tier=str(account.get("tier") or "free"),
        scopes=inherited_scopes,
        max_concurrent=account.get("max_concurrent"),
        daily_limit=account.get("daily_limit"),
        expires_at=account.get("expires_at"),
        data_categories=(
            effective_data_categories(account)
            if "data_categories" in account
            else None
        ),
        label=normalized_label,
    )
    item = {
        "token_hash": created["token_hash"],
        "label": normalized_label,
        "enabled": True,
        "created_at": datetime.datetime.now(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {
        "key": created["token"],
        "api_key": _customer_key_projection(item, current_hash=current_hash),
    }


@_serialized_token_mutation
def disable_customer_token(
    account: dict[str, Any], key_id: str
) -> dict[str, Any]:
    """Disable a same-tenant non-current key; never permit self-lockout."""

    current_hash = _customer_credential_hash(account)
    tenant_id = str(account.get("tenant_id") or "").strip()
    if not re.fullmatch(r"key_[0-9a-f]{16}", str(key_id or "")):
        raise AuthError("invalid key id")
    payload = _read_token_file()
    tokens = payload.get("tokens", [])
    matches = [
        item
        for item in tokens
        if str(item.get("tenant_id") or item.get("tenant") or "").strip()
        == tenant_id
        and _customer_key_id(str(item.get("token_hash") or "").lower()) == key_id
    ]
    if len(matches) != 1:
        raise AuthError("API key not found")
    target = matches[0]
    token_hash = str(target.get("token_hash") or "").lower()
    if token_hash == current_hash:
        raise AuthError("current credential cannot be disabled")
    target["enabled"] = False
    _write_token_file({"tokens": tokens})
    return {
        "api_key": _customer_key_projection(target, current_hash=current_hash)
    }


@_serialized_token_mutation
def update_token(token_hash: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update an existing token's settings."""
    payload = _read_token_file()
    tokens = payload.get("tokens", [])
    found = False
    for item in tokens:
        if str(item.get("token_hash", "")).lower() == token_hash.lower():
            found = True
            target_tier = str(
                updates.get("tier", item.get("tier", "free")) or "free"
            ).strip().lower() or "free"
            if (
                target_tier in COMMERCIAL_TIERS
                and updates.get("daily_limit") is not None
            ):
                raise AuthError(
                    f"commercial tier={target_tier} does not support daily_limit"
                )
            if (
                target_tier in COMMERCIAL_TIERS
                and updates.get("max_concurrent") is not None
            ):
                raise AuthError(
                    f"commercial tier={target_tier} does not support max_concurrent"
                )
            for key in (
                "enabled",
                "daily_limit",
                "expires_at",
                "tier",
                "scopes",
                "max_concurrent",
                "data_categories",
            ):
                if key in updates:
                    if key == "data_categories":
                        item[key] = normalize_data_categories(updates[key])
                    elif updates[key] is None:
                        item.pop(key, None)
                    else:
                        item[key] = updates[key]
            item["tier"] = target_tier
            if target_tier in COMMERCIAL_TIERS:
                item.pop("daily_limit", None)
                item.pop("max_concurrent", None)
            break
    if not found:
        raise AuthError("token not found")
    payload = {"tokens": tokens}
    _write_token_file(payload)
    return {"token_hash": token_hash, "updated": True}


@_serialized_token_mutation
def delete_token(token_hash: str) -> dict[str, Any]:
    """Remove a token from the config."""
    payload = _read_token_file()
    tokens = payload.get("tokens", [])
    new_tokens = [
        t for t in tokens
        if str(t.get("token_hash", "")).lower() != token_hash.lower()
    ]
    if len(new_tokens) == len(tokens):
        raise AuthError("token not found")
    payload = {"tokens": new_tokens}
    _write_token_file(payload)
    return {"token_hash": token_hash, "deleted": True}
def _account_concurrency_limit(account: dict[str, Any]) -> int | None:
    tier = str(account.get("tier") or "free").lower()
    if tier in COMMERCIAL_TIERS:
        return None
    raw_limit = account.get("max_concurrent")
    if raw_limit is not None:
        try:
            value = int(raw_limit)
        except (TypeError, ValueError):
            value = 0
        return None if value <= 0 else value
    return CONCURRENCY_LIMITS.get(
        tier, CONCURRENCY_LIMITS["free"]
    )


def effective_limits(account: dict[str, Any]) -> dict[str, Any]:
    """Resolve the limits enforce_rate_limit/claim_concurrency would apply.

    Portal-facing helper: returns only what the caller's own account resolves
    to, never other tenants' state. ``None`` values mean unlimited.
    """

    tier = str(account.get("tier") or "free").lower()
    raw_daily = account.get("daily_limit")
    daily_limit = (
        int(raw_daily)
        if tier not in COMMERCIAL_TIERS
        and isinstance(raw_daily, int)
        and raw_daily > 0
        else None
    )
    hourly_limit = RATE_LIMITS.get(tier, RATE_LIMITS["free"])
    minute_limit = MINUTE_RATE_LIMITS.get(tier)
    return {
        "tier": tier,
        "hourly_request_limit": hourly_limit,
        "minute_request_limit": minute_limit,
        "concurrency_limit": _account_concurrency_limit(account),
        "daily_limit": daily_limit,
        "request_volume_unlimited": (
            hourly_limit is None and minute_limit is None and daily_limit is None
        ),
    }


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
            "request_log_tenants": len(set(_REQUEST_LOG) | set(_MINUTE_REQUEST_LOG)),
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
