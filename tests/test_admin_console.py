"""Tests for admin console features: token expiry, daily limits, admin API."""

from __future__ import annotations

import importlib
import json
import time
from email.message import Message
from pathlib import Path

import pytest

import auth

TOKEN_TEST_SALT = "tradingdatas-test-token-salt-32-bytes"


def _reload_auth(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key in (
        "TRADINGDATAS_JWT_PUBLIC_KEY",
        "TRADINGDATAS_JWT_ISSUER",
        "TRADINGDATAS_JWT_ALGORITHM",
        "TRADINGDATAS_JWT_LEEWAY_SECONDS",
        "TRADINGDATAS_TOKEN_HASH_FILE",
        "TRADINGDATAS_TOKEN_HASHES_JSON",
        "TRADINGDATAS_TOKEN_SALT",
        "TRADINGDATAS_TOKEN_SALT_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    if "TRADINGDATAS_TOKEN_SALT" not in env and "TRADINGDATAS_TOKEN_SALT_FILE" not in env:
        monkeypatch.setenv("TRADINGDATAS_TOKEN_SALT", TOKEN_TEST_SALT)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(auth)


def _headers(token: str) -> Message:
    h = Message()
    h["Authorization"] = f"Bearer {token}"
    return h


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token-for-expiry"
    token_hash = auth._hash_token.__wrapped__(token) if hasattr(auth._hash_token, '__wrapped__') else None
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    th = auth_mod._hash_token(token)
    past_ts = time.time() - 86400
    tokens_json = json.dumps({
        "tokens": [{
            "tenant_id": "expired-tenant",
            "tier": "free",
            "scopes": ["read"],
            "token_hash": th,
            "expires_at": past_ts,
        }]
    })
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )
    with pytest.raises(auth_mod.AuthError, match="expired"):
        auth_mod.authenticate(_headers(token), "127.0.0.1")


def test_future_token_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token-future-expiry"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    th = auth_mod._hash_token(token)
    future_ts = time.time() + 86400 * 365
    tokens_json = json.dumps({
        "tokens": [{
            "tenant_id": "future-tenant",
            "tier": "free",
            "scopes": ["read"],
            "token_hash": th,
            "expires_at": future_ts,
        }]
    })
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )
    account = auth_mod.authenticate(_headers(token), "127.0.0.1")
    assert account["tenant_id"] == "future-tenant"


def test_disabled_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token-disabled"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    th = auth_mod._hash_token(token)
    tokens_json = json.dumps({
        "tokens": [{
            "tenant_id": "disabled-tenant",
            "tier": "free",
            "scopes": ["read"],
            "token_hash": th,
            "enabled": False,
        }]
    })
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )
    with pytest.raises(auth_mod.AuthError, match="disabled"):
        auth_mod.authenticate(_headers(token), "127.0.0.1")


def test_daily_limit_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-token-daily-limit"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    th = auth_mod._hash_token(token)
    tokens_json = json.dumps({
        "tokens": [{
            "tenant_id": "daily-tenant",
            "tier": "free",
            "scopes": ["read"],
            "token_hash": th,
            "daily_limit": 3,
        }]
    })
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )
    account = auth_mod.authenticate(_headers(token), "127.0.0.1")
    for _ in range(3):
        auth_mod.enforce_daily_limit(account)
    with pytest.raises(auth_mod.RateLimitError, match="daily limit exceeded"):
        auth_mod.enforce_daily_limit(account)


def test_daily_limit_unlimited_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    account = {"tenant_id": "unlimited", "tier": "internal", "scopes": ["read"]}
    for _ in range(100):
        auth_mod.enforce_daily_limit(account)


def test_parse_expires_at_formats() -> None:
    assert auth._parse_expires_at("2027-01-01T00:00:00Z") is not None
    assert auth._parse_expires_at(1893456000) == 1893456000.0
    assert auth._parse_expires_at("1893456000") == 1893456000.0
    assert auth._parse_expires_at("2027-06-15") is not None
    assert auth._parse_expires_at("") is None
    assert auth._parse_expires_at(None) is None


def test_get_daily_usage_returns_empty_initially(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    auth_mod._DAILY_REQUEST_LOG.clear()
    usage = auth_mod.get_daily_usage()
    assert isinstance(usage, dict)


def test_get_hourly_usage_returns_empty_initially(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    auth_mod._REQUEST_LOG.clear()
    usage = auth_mod.get_hourly_usage()
    assert isinstance(usage, dict)


def test_admin_scope_in_scope_endpoints() -> None:
    assert "admin" in auth.SCOPE_ENDPOINTS
    assert "/admin/" in auth.SCOPE_ENDPOINTS["admin"]


def test_data_categories_preserve_legacy_all_and_validate_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "test-category-token"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    token_hash = auth_mod._hash_token(token)
    tokens_json = json.dumps(
        {
            "tokens": [
                {
                    "tenant_id": "category-tenant",
                    "tier": "standard",
                    "scopes": ["read"],
                    "token_hash": token_hash,
                    "data_categories": ["news", "a_share", "news"],
                }
            ]
        }
    )
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )

    account = auth_mod.authenticate(_headers(token), "127.0.0.1")
    assert account["data_categories"] == ["a_share", "news"]
    listed = auth_mod.list_tokens()[0]
    assert listed["data_categories"] == ["a_share", "news"]
    assert listed["data_category_mode"] == "restricted"
    assert auth_mod.effective_data_categories({"scopes": ["read"]}) == [
        "a_share",
        "crypto",
        "news",
    ]


def test_unknown_data_category_fails_closed_during_token_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "test-unknown-category-token"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    token_hash = auth_mod._hash_token(token)
    tokens_json = json.dumps(
        {
            "tokens": [
                {
                    "tenant_id": "category-tenant",
                    "tier": "standard",
                    "scopes": ["read"],
                    "token_hash": token_hash,
                    "data_categories": ["provider-secret-category"],
                }
            ]
        }
    )
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )

    with pytest.raises(auth_mod.AuthError, match="unknown category"):
        auth_mod.authenticate(_headers(token), "127.0.0.1")


def test_token_mutations_persist_only_valid_category_allowlists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "api_tokens.json"
    token_file.write_text('{"tokens": []}', encoding="utf-8")
    token_file.chmod(0o600)
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASH_FILE=str(token_file),
    )

    created = auth_mod.create_token(
        "category-customer",
        tier="standard",
        scopes=["read"],
        data_categories=["news", "a_share"],
    )
    payload = json.loads(token_file.read_text(encoding="utf-8"))
    assert payload["tokens"][0]["data_categories"] == ["a_share", "news"]

    before_invalid_update = token_file.read_bytes()
    with pytest.raises(auth_mod.AuthError, match="unknown category"):
        auth_mod.update_token(
            created["token_hash"],
            {"data_categories": ["unknown"]},
        )
    assert token_file.read_bytes() == before_invalid_update

    auth_mod.update_token(created["token_hash"], {"data_categories": []})
    payload = json.loads(token_file.read_text(encoding="utf-8"))
    assert payload["tokens"][0]["data_categories"] == []

    with pytest.raises(auth_mod.AuthError, match="must be a list"):
        auth_mod.update_token(created["token_hash"], {"data_categories": None})


def test_rfc3339_expires_at_in_token_config(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-rfc3339-token"
    auth_mod = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT)
    th = auth_mod._hash_token(token)
    tokens_json = json.dumps({
        "tokens": [{
            "tenant_id": "rfc3339-tenant",
            "tier": "research",
            "scopes": ["read"],
            "token_hash": th,
            "expires_at": "2099-12-31T23:59:59Z",
            "daily_limit": 10000,
            "enabled": True,
        }]
    })
    auth_mod = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT=TOKEN_TEST_SALT,
        TRADINGDATAS_TOKEN_HASHES_JSON=tokens_json,
    )
    account = auth_mod.authenticate(_headers(token), "127.0.0.1")
    assert account["tenant_id"] == "rfc3339-tenant"
    assert account.get("daily_limit") == 10000
    assert account.get("expires_at") is not None
    assert account.get("enabled") is True
