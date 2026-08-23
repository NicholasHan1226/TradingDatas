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
import query_cursor

ROOT = Path(__file__).resolve().parents[1]
HS256_TEST_SECRET = "tradingdatas-hs256-test-secret-at-least-32-bytes"
TOKEN_TEST_SALT = "tradingdatas-test-token-salt-32-bytes"
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
        "TRADINGDATAS_JWT_PUBLIC_KEY",
        "TRADINGDATAS_JWT_ISSUER",
        "TRADINGDATAS_JWT_ALGORITHM",
        "TRADINGDATAS_JWT_LEEWAY_SECONDS",
        "TRADINGDATAS_TOKEN_HASH_FILE",
        "TRADINGDATAS_TOKEN_HASHES_JSON",
        "TRADINGDATAS_TOKEN_SALT",
        "TRADINGDATAS_TOKEN_SALT_FILE",
        "TRADINGDATAS_LOCALHOST_BYPASS",
    ):
        monkeypatch.delenv(key, raising=False)
    if (
        "TRADINGDATAS_TOKEN_SALT" not in env
        and "TRADINGDATAS_TOKEN_SALT_FILE" not in env
    ):
        monkeypatch.setenv("TRADINGDATAS_TOKEN_SALT", TOKEN_TEST_SALT)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(auth)


@pytest.fixture(autouse=True)
def _realign_query_cursor_auth_references() -> None:
    """importlib.reload(auth) rebinds auth.AuthError and auth._private_file_bytes
    in place; query_cursor holds from-import references that must be realigned
    so its AuthError translation keeps working for the rest of the session."""
    yield
    query_cursor.AuthError = auth.AuthError
    query_cursor._private_file_bytes = auth._private_file_bytes


def test_forged_jwt_is_rejected_when_jwt_key_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_HASHES_JSON="[]")
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
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="HS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "tradingdatas-tests",
            "exp": int(time.time()) + 300,
        },
        key=HS256_TEST_SECRET,
    )

    account = auth_module.authenticate(
        {"Authorization": f"Bearer {token}"}, "203.0.113.10"
    )

    assert account["auth_method"] == "jwt"
    assert account["tenant_id"] == "tenant-a"
    assert account["scopes"] == ["catalog"]
    assert auth_module.check_endpoint_scope(account, "/v1/catalog")
    assert not auth_module.check_endpoint_scope(account, "/v1/query")


def test_signed_jwt_wrong_issuer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="HS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
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
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="HS256",
        TRADINGDATAS_JWT_LEEWAY_SECONDS="0",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "tradingdatas-tests",
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
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="HS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
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
        "TRADINGDATAS_JWT_PUBLIC_KEY": HS256_TEST_SECRET,
        "TRADINGDATAS_JWT_ISSUER": "tradingdatas-tests",
        "TRADINGDATAS_TOKEN_HASHES_JSON": "[]",
    }
    if configured_algorithm is not None:
        env["TRADINGDATAS_JWT_ALGORITHM"] = configured_algorithm
    auth_module = _reload_auth(monkeypatch, **env)
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "tradingdatas-tests",
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
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="RS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "tradingdatas-tests",
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
        TRADINGDATAS_JWT_PUBLIC_KEY=secret,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="HS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
    )
    token = _jwt(
        {"alg": "HS256", "typ": "JWT"},
        {
            "sub": "tenant-a",
            "iss": "tradingdatas-tests",
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
    payload_segment = RS256_TEST_TOKEN.split(".")[1]
    signed_issuer = json.loads(
        base64.urlsafe_b64decode(payload_segment + "=" * (-len(payload_segment) % 4))
    )["iss"]
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_JWT_PUBLIC_KEY=RS256_TEST_PUBLIC_KEY,
        TRADINGDATAS_JWT_ISSUER=signed_issuer,
        TRADINGDATAS_JWT_ALGORITHM="RS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
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
        TRADINGDATAS_JWT_PUBLIC_KEY=HS256_TEST_SECRET,
        TRADINGDATAS_JWT_ISSUER="tradingdatas-tests",
        TRADINGDATAS_JWT_ALGORITHM="RS256",
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
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
    token_hash = _token_hash(token)
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": token_hash,
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
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
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
    assert auth_module.check_endpoint_scope(account, "/v1/catalog")
    assert auth_module.check_endpoint_scope(account, "/v1/query")


def test_external_read_scope_allows_only_the_fixed_data_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
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
    allowed_paths = ["/v1/catalog", "/v1/query"]

    for path in allowed_paths:
        assert auth_module.check_endpoint_scope(account, path), path
    for retired in ("/health", "/tushare", "/source_status", "/opening_gate"):
        assert not auth_module.check_endpoint_scope(account, retired)


@pytest.mark.parametrize(
    "scope",
    ["external_read", "read", "internal", "full", "*"],
)
def test_v1_data_routes_use_only_the_frozen_endpoint_scopes(scope: str) -> None:
    account = {"scopes": [scope]}

    assert auth.check_endpoint_scope(account, "/v1/catalog")
    assert auth.check_endpoint_scope(account, "/v1/query")


@pytest.mark.parametrize(
    "scope", ["health", "status", "tushare", "fundamentals", "macro", "events"]
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
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
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
    auth_module = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_HASHES_JSON="[]")
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
    auth_module = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_HASHES_JSON="[]")
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
    return hashlib.pbkdf2_hmac(
        "sha256",
        token.encode("utf-8"),
        TOKEN_TEST_SALT.encode("utf-8"),
        100000,
    ).hex()


def _token_config(token: str, tenant_id: str, scopes: list[str]) -> dict[str, Any]:
    return {
        "token_hash": _token_hash(token),
        "tenant_id": tenant_id,
        "tier": "free",
        "scopes": scopes,
    }


def test_rate_limit_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
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
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
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
    auth_module = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_HASHES_JSON="[]")

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


def test_unknown_scope_is_denied_every_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("old-token", "tenant-old", ["health"])]}
        ),
    )

    account = auth_module.authenticate(
        {"Authorization": "Bearer old-token"}, "203.0.113.10"
    )

    assert not auth_module.check_endpoint_scope(account, "/v1/catalog")
    assert not auth_module.check_endpoint_scope(account, "/v1/query")
    assert not auth_module.check_endpoint_scope(account, "/health")


def test_localhost_bypass_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(monkeypatch, TRADINGDATAS_TOKEN_HASHES_JSON="[]")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({}, "127.0.0.1")


def test_localhost_never_bypasses_explicit_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
        TRADINGDATAS_LOCALHOST_BYPASS="1",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({}, "127.0.0.1")


def test_localhost_request_with_token_does_not_use_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    _token_config(
                        "local-token", "tenant-local-token", ["external_read"]
                    )
                ]
            }
        ),
        TRADINGDATAS_LOCALHOST_BYPASS="1",
    )

    account = auth_module.authenticate(
        {"Authorization": "Bearer local-token"}, "127.0.0.1"
    )

    assert account["auth_method"] == "token_hash"
    assert account["tenant_id"] == "tenant-local-token"
    assert auth_module.check_endpoint_scope(account, "/v1/catalog")
    assert auth_module.check_endpoint_scope(account, "/v1/query")
    assert not auth_module.check_endpoint_scope(account, "/tushare")


def test_forwarded_localhost_request_requires_real_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON="[]",
        TRADINGDATAS_LOCALHOST_BYPASS="1",
    )

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"X-Forwarded-For": "203.0.113.20"}, "127.0.0.1")

    with pytest.raises(auth_module.AuthError):
        auth_module.authenticate({"CF-Connecting-IP": "203.0.113.20"}, "127.0.0.1")


def test_unsalted_plain_sha_token_config_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "unsalted-token"
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT="",
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                        "tenant_id": "tenant-unsalted",
                        "tier": "internal",
                        "scopes": ["read"],
                    }
                ]
            }
        ),
    )

    with pytest.raises(auth_module.AuthError, match="salt"):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "127.0.0.1",
        )


def test_token_hash_file_requires_private_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "file-token"
    token_file = tmp_path / "api_tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": _token_hash(token),
                        "tenant_id": "tenant-file",
                        "tier": "internal",
                        "scopes": ["read"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    token_file.chmod(0o644)
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASH_FILE=str(token_file),
    )

    with pytest.raises(auth_module.AuthError, match="mode"):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "127.0.0.1",
        )


def test_token_salt_file_requires_private_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    salt_file = tmp_path / "token_salt"
    salt_file.write_text(TOKEN_TEST_SALT, encoding="utf-8")
    salt_file.chmod(0o644)
    token = "salt-file-token"
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_SALT_FILE=str(salt_file),
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                        "tenant_id": "tenant-salt-file",
                        "tier": "internal",
                        "scopes": ["read"],
                    }
                ]
            }
        ),
    )

    with pytest.raises(auth_module.AuthError, match="mode"):
        auth_module.authenticate(
            {"Authorization": f"Bearer {token}"},
            "127.0.0.1",
        )


def test_private_token_and_salt_files_authenticate_explicit_loopback_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    salt_file = tmp_path / "token_salt"
    salt_file.write_text(TOKEN_TEST_SALT, encoding="utf-8")
    salt_file.chmod(0o600)
    token = "private-file-token"
    token_file = tmp_path / "api_tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": _token_hash(token),
                        "tenant_id": "tenant-private-file",
                        "tier": "internal",
                        "scopes": ["read"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    token_file.chmod(0o600)
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASH_FILE=str(token_file),
        TRADINGDATAS_TOKEN_SALT_FILE=str(salt_file),
    )

    account = auth_module.authenticate(
        {"Authorization": f"Bearer {token}"},
        "127.0.0.1",
    )

    assert account["tenant_id"] == "tenant-private-file"
    assert account["auth_method"] == "token_hash"
    assert auth_module.check_endpoint_scope(account, "/v1/catalog")
    assert auth_module.check_endpoint_scope(account, "/v1/query")


@pytest.mark.parametrize("label", ["token hash", "token salt"])
def test_private_auth_file_rejects_replacement_between_name_check_and_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    target = tmp_path / label.replace(" ", "_")
    target.write_bytes(b"trusted-auth-material")
    target.chmod(0o600)
    replacement = tmp_path / f".{target.name}.replacement"
    replacement.write_bytes(b"attacker-auth-material")
    replacement.chmod(0o600)
    real_open = auth.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and Path(path).name == target.name
            and not flags & getattr(auth.os, "O_DIRECTORY", 0)
        ):
            replacement.replace(target)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(auth.os, "open", racing_open)

    with pytest.raises(auth.AuthError, match="binding changed"):
        auth._private_file_bytes(str(target), label=label, max_bytes=4096)

    assert swapped


def test_private_auth_file_closes_all_descriptors_on_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "token_salt"
    target.write_bytes(b"trusted-auth-material")
    target.chmod(0o600)
    real_open = auth.os.open
    real_close = auth.os.close
    opened: set[int] = set()
    closed: set[int] = set()

    class FatalRead(BaseException):
        pass

    def tracking_open(path, flags, *args, **kwargs):
        descriptor = real_open(path, flags, *args, **kwargs)
        opened.add(descriptor)
        return descriptor

    def tracking_close(descriptor: int) -> None:
        closed.add(descriptor)
        real_close(descriptor)

    def fatal_read(descriptor: int, size: int) -> bytes:
        raise FatalRead

    monkeypatch.setattr(auth.os, "open", tracking_open)
    monkeypatch.setattr(auth.os, "close", tracking_close)
    monkeypatch.setattr(auth.os, "read", fatal_read)

    with pytest.raises(FatalRead):
        auth._private_file_bytes(str(target), label="token salt", max_bytes=4096)

    assert opened
    assert opened <= closed


def test_preauth_rate_limit_rejects_before_pbkdf2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garbage-token floods from one host must be capped before key derivation."""
    auth_module = _reload_auth(monkeypatch)
    auth_module._PREAUTH_MAX_ATTEMPTS = 5

    hash_calls = {"count": 0}
    real_hash_token = auth_module._hash_token

    def counting_hash(token: str) -> str:
        hash_calls["count"] += 1
        return real_hash_token(token)

    monkeypatch.setattr(auth_module, "_hash_token", counting_hash)

    # The first five garbage tokens reach PBKDF2 and fail as invalid.
    for _ in range(5):
        with pytest.raises(auth_module.AuthError):
            auth_module.authenticate(
                {"Authorization": "Bearer garbage-token"}, "203.0.113.10"
            )
    assert hash_calls["count"] == 5

    # The sixth attempt is rejected by the pre-auth limiter without hashing.
    with pytest.raises(auth_module.RateLimitError):
        auth_module.authenticate(
            {"Authorization": "Bearer garbage-token"}, "203.0.113.10"
        )
    assert hash_calls["count"] == 5


def test_preauth_rate_limit_isolated_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch,
        TRADINGDATAS_TOKEN_HASHES_JSON=json.dumps(
            {"tokens": [_token_config("iso-token", "tenant-iso", ["read"])]}
        ),
    )
    auth_module._PREAUTH_MAX_ATTEMPTS = 2

    for _ in range(2):
        with pytest.raises(auth_module.AuthError):
            auth_module.authenticate(
                {"Authorization": "Bearer garbage-a"}, "203.0.113.10"
            )
    with pytest.raises(auth_module.RateLimitError):
        auth_module.authenticate(
            {"Authorization": "Bearer iso-token"}, "203.0.113.10"
        )

    # A different host is unaffected and authenticates normally.
    account = auth_module.authenticate(
        {"Authorization": "Bearer iso-token"}, "198.51.100.77"
    )
    assert account["tenant_id"] == "tenant-iso"


def test_preauth_rate_limit_env_override_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_module = _reload_auth(
        monkeypatch, TRADINGDATAS_PREAUTH_RATE_LIMIT="7"
    )
    assert auth_module._PREAUTH_MAX_ATTEMPTS == 7


def test_preauth_limiter_bounds_and_recovers():
    """Anonymous PBKDF2 spray is capped per source; window expiry restores."""
    import api_server

    monkey = {"t": 1000.0}
    real_mono = api_server.time.monotonic
    api_server.time.monotonic = lambda: monkey["t"]
    try:
        with api_server._AUTH_LIMITER_LOCK:
            api_server._AUTH_ATTEMPT_TIMES.clear()
        for _ in range(api_server._AUTH_ATTEMPTS_PER_WINDOW):
            assert api_server._auth_attempt_allowed("10.9.9.9")
        assert not api_server._auth_attempt_allowed("10.9.9.9")
        assert api_server._auth_attempt_allowed("10.9.9.8")  # other sources unaffected

        monkey["t"] += api_server._AUTH_ATTEMPT_WINDOW_SECONDS + 1
        assert api_server._auth_attempt_allowed("10.9.9.9")  # expired window recovers
    finally:
        api_server.time.monotonic = real_mono
        with api_server._AUTH_LIMITER_LOCK:
            api_server._AUTH_ATTEMPT_TIMES.clear()


def test_preauth_limiter_tracks_bounded_sources():
    import api_server

    real_mono = api_server.time.monotonic
    api_server.time.monotonic = lambda: 5000.0
    try:
        with api_server._AUTH_LIMITER_LOCK:
            api_server._AUTH_ATTEMPT_TIMES.clear()
        cap = api_server._AUTH_ATTEMPT_TRACK_CAP
        for i in range(cap + 5):
            api_server._auth_attempt_allowed(f"10.1.{i // 256}.{i % 256}")
        assert len(api_server._AUTH_ATTEMPT_TIMES) <= cap
    finally:
        api_server.time.monotonic = real_mono
        with api_server._AUTH_LIMITER_LOCK:
            api_server._AUTH_ATTEMPT_TIMES.clear()
