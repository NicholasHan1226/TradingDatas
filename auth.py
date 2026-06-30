#!/usr/bin/env python3
"""Authentication, rate limiting, and request dedup for SharedSignals API."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TOKEN_HASH_FILE = Path(os.environ.get("SHAREDSIGNALS_TOKEN_HASH_FILE", ROOT / "config" / "api_tokens.json"))
RATE_LIMITS = {
    "free": 60,
    "pro": 600,
    "enterprise": None,
    "internal": None,
}
LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}
DEDUP_TTL_SECONDS = 60
RATE_WINDOW_SECONDS = 3600

_STATE_LOCK = threading.Lock()
_REQUEST_LOG: dict[str, deque[float]] = defaultdict(deque)
_DEDUP_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_HASHES: dict[str, dict[str, str]] | None = None


class AuthError(Exception):
    """Raised when authentication fails."""


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""



def _now() -> float:
    return time.time()



def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)



def _load_token_hashes() -> dict[str, dict[str, str]]:
    global _TOKEN_HASHES
    if _TOKEN_HASHES is not None:
        return _TOKEN_HASHES

    items: dict[str, dict[str, str]] = {}
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
        items[token_hash] = {"tenant_id": tenant_id, "tier": tier, "auth_method": "token_hash"}

    _TOKEN_HASHES = items
    return _TOKEN_HASHES



def _parse_jwt(token: str) -> dict[str, str] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return None

    tenant_id = str(payload.get("tenant_id") or payload.get("tid") or payload.get("sub") or "").strip()
    tier = str(payload.get("tier") or payload.get("plan") or payload.get("role") or "free").strip().lower() or "free"
    if not tenant_id:
        return None
    return {"tenant_id": tenant_id, "tier": tier, "auth_method": "jwt"}



def _extract_bearer_token(headers: Any) -> str:
    header = headers.get("Authorization", "") if headers else ""
    if not header.startswith("Bearer "):
        raise AuthError("missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise AuthError("empty bearer token")
    return token



def authenticate(headers: Any, client_host: str) -> dict[str, str]:
    host = (client_host or "").strip()
    if host in LOCALHOSTS:
        return {"tenant_id": "internal", "tier": "internal", "auth_method": "localhost"}

    token = _extract_bearer_token(headers)
    jwt_claims = _parse_jwt(token)
    if jwt_claims is not None:
        return jwt_claims

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest().lower()
    token_hashes = _load_token_hashes()
    if token_hash in token_hashes:
        return token_hashes[token_hash]
    raise AuthError("invalid token")



def enforce_rate_limit(tenant_id: str, tier: str) -> None:
    limit = RATE_LIMITS.get((tier or "free").lower(), RATE_LIMITS["free"])
    if limit is None:
        return

    now = _now()
    with _STATE_LOCK:
        bucket = _REQUEST_LOG[tenant_id]
        while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            raise RateLimitError(f"rate limit exceeded for tier={tier}")
        bucket.append(now)



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
            _DEDUP_CACHE.pop(fingerprint, None)
            return None
        response = copy.deepcopy(item.get("response"))
    return response



def store_cached_response(fingerprint: str, response: dict[str, Any]) -> None:
    now = _now()
    with _STATE_LOCK:
        expired = [key for key, item in _DEDUP_CACHE.items() if now - float(item.get("stored_at", 0.0)) > DEDUP_TTL_SECONDS]
        for key in expired:
            _DEDUP_CACHE.pop(key, None)
        _DEDUP_CACHE[fingerprint] = {"stored_at": now, "response": copy.deepcopy(response)}
