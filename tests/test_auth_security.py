from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

import auth

ROOT = Path(__file__).resolve().parents[1]


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _jwt(header: dict[str, Any], payload: dict[str, Any], key: str | None = None) -> str:
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    if key is None:
        signature = "forged"
    else:
        digest = hmac.new(key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        signature = _b64url(digest)
    return f"{signing_input}.{signature}"


def _reload_auth(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    for key in (
        "SHAREDSIGNALS_JWT_PUBLIC_KEY",
        "SHAREDSIGNALS_JWT_ISSUER",
        "SHAREDSIGNALS_TOKEN_HASHES_JSON",
        "SHAREDSIGNALS_LOCALHOST_BYPASS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(auth)


def test_forged_jwt_is_rejected_when_jwt_key_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")
    token = _jwt(
        {"alg": "none", "typ": "JWT"},
        {"sub": "attacker", "tier": "enterprise", "scopes": ["full"]},
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


def test_signed_jwt_without_scope_defaults_to_minimum_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY="test-secret",
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": "tenant-a", "iss": "sharedsignals-tests", "exp": int(time.time()) + 300},
        key="test-secret",
    )

    account = auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")

    assert account["auth_method"] == "jwt"
    assert account["tenant_id"] == "tenant-a"
    assert account["scopes"] == ["health"]
    assert not auth_module.check_endpoint_scope(account, "/market_data")


def test_pm_scope_covers_markets_and_prices() -> None:
    account = {"scopes": ["pm"]}

    assert auth.check_endpoint_scope(account, "/pm_markets")
    assert auth.check_endpoint_scope(account, "/pm_prices")
    assert not auth.check_endpoint_scope(account, "/market_data")


def test_industry_reference_scope_is_exact_and_least_privilege() -> None:
    expected = {
        "/industry/snapshot",
        "/industry/taxonomy",
        "/industry/memberships",
    }
    account = {"scopes": ["industry_reference"]}

    assert auth.SCOPE_ENDPOINTS["industry_reference"] == expected
    for path in expected:
        assert auth.check_endpoint_scope(account, path), path
    for path in (
        "/industry",
        "/fundamentals",
        "/events",
        "/health",
        "/cache/status",
        "/cache/invalidate",
    ):
        assert not auth.check_endpoint_scope(account, path), path


def test_industry_reference_routes_are_only_in_approved_composites() -> None:
    paths = {
        "/industry/snapshot",
        "/industry/taxonomy",
        "/industry/memberships",
    }

    for scope in ("fundamentals", "external_read", "read"):
        account = {"scopes": [scope]}
        for path in paths:
            assert auth.check_endpoint_scope(account, path), (scope, path)
    for scope in ("status", "health", "events"):
        account = {"scopes": [scope]}
        for path in paths:
            assert not auth.check_endpoint_scope(account, path), (scope, path)


def test_signed_jwt_wrong_issuer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY="test-secret",
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": "tenant-a", "iss": "other-issuer", "exp": int(time.time()) + 300, "scopes": ["full"]},
        key="test-secret",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


def test_signed_jwt_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY="test-secret",
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_LEEWAY_SECONDS="0",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": "tenant-a", "iss": "sharedsignals-tests", "exp": int(time.time()) - 1, "scopes": ["full"]},
        key="test-secret",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


def test_token_account_max_concurrent_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "tenant-token"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    {
                        "sha256": token_hash,
                        "tenant_id": "tenant-concurrent",
                        "tier": "pro",
                        "scopes": ["read"],
                        "max_concurrent": 1,
                    }
                ]
            }
        ),
    )

    account = auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")

    auth_module.claim_concurrency(account)
    with pytest.raises(auth_module.ConcurrencyLimitError):
        auth_module.claim_concurrency(account)
    auth_module.release_concurrency(account["tenant_id"])
    auth_module.claim_concurrency(account)
    auth_module.release_concurrency(account["tenant_id"])


def test_x_api_key_header_authenticates_token(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("x-api-key-token", "tenant-x-api-key", ["external_read"])]}
        ),
    )

    account = auth_module.authenticate({"X-API-Key": "x-api-key-token"}, "203.0.113.10")

    assert account["tenant_id"] == "tenant-x-api-key"
    assert auth_module.check_endpoint_scope(account, "/agent_config")


def test_external_read_scope_allows_full_data_surface_without_operator_control(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("external-token", "tenant-external", ["external_read"])]}
        ),
    )

    account = auth_module.authenticate(
        {"Authorization": "Bearer external-token"}, "203.0.113.10"
    )
    allowed_paths = [
        "/health",
        "/capabilities",
        "/agent_config",
        "/source_status",
        "/cache/status",
        "/market_data",
        "/realtime_5min",
        "/is_trading_day",
        "/fundamentals",
        "/reference",
        "/industry",
        "/industry/snapshot",
        "/industry/taxonomy",
        "/industry/memberships",
        "/macro",
        "/capital_flow",
        "/events",
        "/sentiment",
        "/crypto",
        "/pm_markets",
        "/pm_prices",
        "/associations",
        "/impacts",
        "/tushare",
    ]

    for path in allowed_paths:
        assert auth_module.check_endpoint_scope(account, path), path
    assert not auth_module.check_endpoint_scope(account, "/cache/invalidate")


def test_api_tokens_example_matches_loader_schema() -> None:
    payload = json.loads((ROOT / "config" / "api_tokens.example.json").read_text(encoding="utf-8"))
    tokens = payload.get("tokens")

    assert isinstance(tokens, list)
    assert tokens
    for item in tokens:
        token_hash = str(item.get("token_hash") or item.get("sha256") or "")
        assert len(token_hash) == 64
        assert "pbkdf2_sha256" not in item
        int(token_hash, 16)


def test_default_free_concurrency_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")
    account = {"tenant_id": "tenant-free", "tier": "free", "scopes": ["read"]}

    auth_module.claim_concurrency(account)
    auth_module.claim_concurrency(account)
    with pytest.raises(auth_module.ConcurrencyLimitError):
        auth_module.claim_concurrency(account)
    auth_module.release_concurrency(account["tenant_id"])
    auth_module.release_concurrency(account["tenant_id"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_config(token: str, tenant_id: str, scopes: list[str]) -> dict[str, Any]:
    return {
        "sha256": _token_hash(token),
        "tenant_id": tenant_id,
        "tier": "free",
        "scopes": scopes,
    }


def test_rate_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("rate-token", "tenant-rate", ["read"])]}
        ),
    )
    # Force a tiny limit so the test is deterministic and does not depend on time.
    auth_module.RATE_LIMITS["free"] = 1

    account = auth_module.authenticate(
        {"Authorization": "Bearer rate-token"}, "203.0.113.10"
    )
    auth_module.enforce_rate_limit(account["tenant_id"], account["tier"])
    with pytest.raises(auth_module.RateLimitError):
        auth_module.enforce_rate_limit(account["tenant_id"], account["tier"])


def test_rate_limit_isolated_by_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    _token_config("a-token", "tenant-a", ["read"]),
                    _token_config("b-token", "tenant-b", ["read"]),
                ]
            }
        ),
    )
    auth_module.RATE_LIMITS["free"] = 1

    account_a = auth_module.authenticate(
        {"Authorization": "Bearer a-token"}, "203.0.113.10"
    )
    account_b = auth_module.authenticate(
        {"Authorization": "Bearer b-token"}, "203.0.113.10"
    )

    auth_module.enforce_rate_limit(account_a["tenant_id"], account_a["tier"])
    # tenant-a second request is blocked.
    with pytest.raises(auth_module.RateLimitError):
        auth_module.enforce_rate_limit(account_a["tenant_id"], account_a["tier"])
    # tenant-b is unaffected by tenant-a's quota consumption.
    auth_module.enforce_rate_limit(account_b["tenant_id"], account_b["tier"])


def test_account_tiers_define_internal_and_future_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")

    assert auth_module.RATE_LIMITS["internal"] is None
    assert auth_module.CONCURRENCY_LIMITS["internal"] is None
    assert auth_module.RATE_LIMITS["starter"] == 60
    assert auth_module.CONCURRENCY_LIMITS["starter"] == 2
    assert auth_module.RATE_LIMITS["research"] == 300
    assert auth_module.CONCURRENCY_LIMITS["research"] == 4
    assert auth_module.RATE_LIMITS["pro"] == 600
    assert auth_module.CONCURRENCY_LIMITS["pro"] == 8
    # Backward-compatible alias for older configs.
    assert auth_module.RATE_LIMITS["free"] == auth_module.RATE_LIMITS["starter"]
    assert auth_module.CONCURRENCY_LIMITS["free"] == auth_module.CONCURRENCY_LIMITS["starter"]


def test_scope_isolation_limits_endpoint_access(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("health-token", "tenant-health", ["health"])]}
        ),
    )

    account = auth_module.authenticate(
        {"Authorization": "Bearer health-token"}, "203.0.113.10"
    )

    assert auth_module.check_endpoint_scope(account, "/health")
    assert not auth_module.check_endpoint_scope(account, "/market_data")
    assert not auth_module.check_endpoint_scope(account, "/tushare")


def test_localhost_bypass_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({}, "127.0.0.1")


def test_localhost_bypass_requires_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
        SHAREDSIGNALS_LOCALHOST_BYPASS="1",
    )

    account = auth_module.authenticate({}, "127.0.0.1")

    assert account["auth_method"] == "localhost"
    assert account["scopes"] == ["full"]


def test_localhost_request_with_token_does_not_use_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("local-token", "tenant-local-token", ["external_read"])]}
        ),
        SHAREDSIGNALS_LOCALHOST_BYPASS="1",
    )

    account = auth_module.authenticate(
        {"Authorization": "Bearer local-token"}, "127.0.0.1"
    )

    assert account["auth_method"] == "token_hash"
    assert account["tenant_id"] == "tenant-local-token"
    assert auth_module.check_endpoint_scope(account, "/tushare")
    assert not auth_module.check_endpoint_scope(account, "/cache/invalidate")


def test_forwarded_localhost_request_requires_real_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
        SHAREDSIGNALS_LOCALHOST_BYPASS="1",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"X-Forwarded-For": "203.0.113.20"}, "127.0.0.1")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"CF-Connecting-IP": "203.0.113.20"}, "127.0.0.1")
