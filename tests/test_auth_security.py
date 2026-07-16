from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
from email.message import Message
import time
from pathlib import Path
from typing import Any

import pytest

import auth

ROOT = Path(__file__).resolve().parents[1]
HS256_TEST_SECRET = "sharedsignals-hs256-test-secret-at-least-32-bytes"
RS256_TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvLLh99yunJ6M04WFRJ5g
sZooFzw9vRwTlHZzCEBzx3h+3C2FcaHiYxt+UKA72GqKOCTcI5Wg83eAct/8S7K/
OtvgDLiDErZZ7BENO9FfM58hUcQkrEbO6h4bJovmoxDwgTFhOkUZ0Ga49vvwc3QP
4H/w0smZXJ1VdrZkuXJ5tctddqfvo0jY5ZQWU+NlwhWllieDhhsiaxNpEyaGFJrN
42jSvjpKnSaV0OZTR2+k+I5mtDncmm0QHWg/4RnnYVan8H5lo2bKYSSct6sgPYxm
h7wwwY2PUCwjPalUg+MkLbvV9zD7mhl+Mqs14BTigTWLdx7UsU2kTK3TeC55hCgF
MwIDAQAB
-----END PUBLIC KEY-----"""
RS256_TEST_TOKEN = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJ0ZW5hbnQtcnMiLCJpc3MiOiJzaGFyZWRzaWduYWxzLXRlc3RzIiwiZXhwIjo0MTAyNDQ0ODAwLCJzY29wZXMiOlsiZXh0ZXJuYWxfcmVhZCJdfQ."
    "GLRgLcwCj25RXSEWg7xqsjZeRwpAEB_h23a7apsiltuYDhZyJi8xRfRFfVXHZgkMNxL3_9tLb2GesXtxaRunBu74tai6VLyaw1scsOvGkdoxVLDwA7HlDJ7ZkHa4eYsocvCG0gdnmvD0arBzKaWlGCW-S17KtGMreLH3eCfvUR1biT74zuJRWclCWXVrC2beE3MyvzOgubCidHkSU91FVvOIxU4khOAssExWAStynRgH2KAX54Xg_zz6UAXEBSlT0GXY0G20DwLkcMRseySDHGyusUplFqBv_YXTa99OY1dHJpO1r1V6d_8vyOtEL2_91Vo4RqUs07YExL22dCpdsQ"
)


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _jwt(
    header: dict[str, Any], payload: dict[str, Any], key: str | None = None
) -> str:
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    if key is None:
        signature = "forged"
    else:
        digest = hmac.new(
            key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        signature = _b64url(digest)
    return f"{signing_input}.{signature}"


def _reload_auth(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    for key in (
        "SHAREDSIGNALS_JWT_PUBLIC_KEY",
        "SHAREDSIGNALS_JWT_ISSUER",
        "SHAREDSIGNALS_JWT_ALGORITHM",
        "SHAREDSIGNALS_JWT_LEEWAY_SECONDS",
        "SHAREDSIGNALS_TOKEN_HASH_FILE",
        "SHAREDSIGNALS_TOKEN_HASHES_JSON",
        "SHAREDSIGNALS_TOKEN_SALT",
        "SHAREDSIGNALS_LOCALHOST_BYPASS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(auth)


def test_forged_jwt_is_rejected_when_jwt_key_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")
    token = _jwt(
        {"alg": "none", "typ": "JWT"},
        {"sub": "attacker", "tier": "enterprise", "scopes": ["full"]},
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


def test_signed_jwt_without_scope_defaults_to_minimum_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="HS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "sharedsignals-tests",
            "exp": int(time.time()) + 300,
        },
        key=HS256_TEST_SECRET,
    )

    account = auth_module.authenticate(
        {"Authorization": f"Bearer {token}"}, "203.0.113.10"
    )

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
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="HS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "other-issuer",
            "exp": int(time.time()) + 300,
            "scopes": ["full"],
        },
        key=HS256_TEST_SECRET,
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


def test_signed_jwt_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="HS256",
        SHAREDSIGNALS_JWT_LEEWAY_SECONDS="0",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "sharedsignals-tests",
            "exp": int(time.time()) - 1,
            "scopes": ["full"],
        },
        key=HS256_TEST_SECRET,
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"Authorization": f"Bearer {token}"}, "203.0.113.10")


@pytest.mark.parametrize("token", ["W10.e30.AA", "e30.W10.AA"])
def test_jwt_header_and_payload_must_be_json_objects(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="HS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "203.0.113.10",
        )


@pytest.mark.parametrize("configured_algorithm", [None, "", "HS512", "hs256"])
def test_jwt_requires_explicit_supported_server_algorithm(
    monkeypatch: pytest.MonkeyPatch,
    configured_algorithm: str | None,
) -> None:
    env = {
        "SHAREDSIGNALS_JWT_PUBLIC_KEY": HS256_TEST_SECRET,
        "SHAREDSIGNALS_JWT_ISSUER": "sharedsignals-tests",
        "SHAREDSIGNALS_TOKEN_HASHES_JSON": "[]",
    }
    if configured_algorithm is not None:
        env["SHAREDSIGNALS_JWT_ALGORITHM"] = configured_algorithm
    auth_module = _reload_auth(monkeypatch, **env)
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "sharedsignals-tests",
            "exp": int(time.time()) + 300,
            "scopes": ["external_read"],
        },
        key=HS256_TEST_SECRET,
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "203.0.113.10",
        )


def test_jwt_header_algorithm_must_match_server_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="RS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "sharedsignals-tests",
            "exp": int(time.time()) + 300,
            "scopes": ["external_read"],
        },
        key=HS256_TEST_SECRET,
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "203.0.113.10",
        )


@pytest.mark.parametrize(
    "secret",
    [
        "too-short",
        "-----BEGIN PUBLIC KEY-----\nnot-a-real-key\n-----END PUBLIC KEY-----",
        "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----",
    ],
)
def test_hs256_rejects_weak_or_pem_shaped_server_key(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=secret,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="HS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "sharedsignals-tests",
            "exp": int(time.time()) + 300,
        },
        key=secret,
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "203.0.113.10",
        )


def test_rs256_accepts_only_the_configured_public_key_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=RS256_TEST_PUBLIC_KEY,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="RS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )

    account = auth_module.authenticate(
        {"Authorization": f"Bearer {RS256_TEST_TOKEN}"},
        "203.0.113.10",
    )

    assert account["tenant_id"] == "tenant-rs"
    assert account["scopes"] == ["external_read"]


def test_rs256_rejects_non_public_key_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        SHAREDSIGNALS_JWT_ISSUER="sharedsignals-tests",
        SHAREDSIGNALS_JWT_ALGORITHM="RS256",
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(
            {"Authorization": f"Bearer {RS256_TEST_TOKEN}"},
            "203.0.113.10",
        )


def test_token_account_max_concurrent_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    account = auth_module.authenticate(
        {"Authorization": f"Bearer {token}"}, "203.0.113.10"
    )

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
            {
                "tokens": [
                    _token_config(
                        "x-api-key-token", "tenant-x-api-key", ["external_read"]
                    )
                ]
            }
        ),
    )

    account = auth_module.authenticate({"X-API-Key": "x-api-key-token"}, "203.0.113.10")

    assert account["tenant_id"] == "tenant-x-api-key"
    assert auth_module.check_endpoint_scope(account, "/agent_config")


def test_external_read_scope_allows_full_data_surface_without_operator_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    _token_config(
                        "external-token", "tenant-external", ["external_read"]
                    )
                ]
            }
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


@pytest.mark.parametrize(
    "scope",
    ["market_data", "events", "external_read", "read", "full", "*"],
)
def test_v1_data_routes_use_only_the_frozen_endpoint_scopes(scope: str) -> None:
    account = {"scopes": [scope]}

    assert auth.check_endpoint_scope(account, "/v1/catalog")
    assert auth.check_endpoint_scope(account, "/v1/query")


@pytest.mark.parametrize(
    "scope", ["health", "status", "tushare", "fundamentals", "macro"]
)
def test_legacy_narrow_scopes_cannot_enter_v1(scope: str) -> None:
    account = {"scopes": [scope]}

    assert not auth.check_endpoint_scope(account, "/v1/catalog")
    assert not auth.check_endpoint_scope(account, "/v1/query")


@pytest.mark.parametrize(
    "headers",
    [
        [("Authorization", "Bearer first"), ("Authorization", "Bearer second")],
        [("X-API-Key", "first"), ("X-API-Key", "second")],
        [("Authorization", "Bearer first"), ("X-API-Key", "second")],
        [("Authorization", ""), ("X-API-Key", "second")],
    ],
)
def test_ambiguous_or_duplicate_credential_headers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    headers: list[tuple[str, str]],
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    _token_config("first", "tenant-first", ["external_read"]),
                    _token_config("second", "tenant-second", ["external_read"]),
                ]
            }
        ),
    )
    message = Message()
    for name, value in headers:
        message[name] = value

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate(message, "203.0.113.10")


def test_api_tokens_example_matches_loader_schema() -> None:
    payload = json.loads(
        (ROOT / "config" / "api_tokens.example.json").read_text(encoding="utf-8")
    )
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


def test_unlimited_concurrency_claim_does_not_release_same_tenant_finite_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")
    finite = {"tenant_id": "tenant-mixed", "tier": "free", "max_concurrent": 1}
    unlimited = {
        "tenant_id": "tenant-mixed",
        "tier": "internal",
        "max_concurrent": 0,
    }

    finite_claimed = auth_module.claim_concurrency(finite)
    unlimited_claimed = auth_module.claim_concurrency(unlimited)
    if unlimited_claimed:
        auth_module.release_concurrency(unlimited["tenant_id"])

    assert finite_claimed is True
    assert unlimited_claimed is False
    assert auth_module._ACTIVE_REQUESTS == {"tenant-mixed": 1}
    with pytest.raises(auth_module.ConcurrencyLimitError):
        auth_module.claim_concurrency(finite)
    auth_module.release_concurrency(finite["tenant_id"])
    assert auth_module._ACTIVE_REQUESTS == {}


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


def test_account_tiers_define_internal_and_future_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert (
        auth_module.CONCURRENCY_LIMITS["free"]
        == auth_module.CONCURRENCY_LIMITS["starter"]
    )


def test_scope_isolation_limits_endpoint_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_localhost_bypass_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(monkeypatch, SHAREDSIGNALS_TOKEN_HASHES_JSON="[]")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({}, "127.0.0.1")


def test_localhost_bypass_requires_explicit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
        SHAREDSIGNALS_LOCALHOST_BYPASS="1",
    )

    account = auth_module.authenticate({}, "127.0.0.1")

    assert account["auth_method"] == "localhost"
    assert account["scopes"] == ["full"]


def test_localhost_request_with_token_does_not_use_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    _token_config(
                        "local-token", "tenant-local-token", ["external_read"]
                    )
                ]
            }
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


def test_forwarded_localhost_request_requires_real_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        SHAREDSIGNALS_TOKEN_HASHES_JSON="[]",
        SHAREDSIGNALS_LOCALHOST_BYPASS="1",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"X-Forwarded-For": "203.0.113.20"}, "127.0.0.1")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"CF-Connecting-IP": "203.0.113.20"}, "127.0.0.1")
