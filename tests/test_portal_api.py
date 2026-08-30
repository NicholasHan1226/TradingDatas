"""Contract tests for the customer self-service portal endpoint.

Mirrors the in-process HTTP harness from test_v1_api.py, but scoped to
``/portal/api/*`` so it stays fast enough for the regular suite: no fake data
services, no runtime catalog, only auth-state fixtures.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from typing import Any

import pytest

import api_server
import auth


FUTURE_TS = time.time() + 90 * 24 * 3600
PAST_TS = time.time() - 3600
PORTAL_TEST_SALT = b"tradingdatas-portal-test-salt-32-bytes"


@pytest.fixture(autouse=True)
def _isolate_portal_auth_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep portal tests independent of auth-module reloads in other files.

    ``test_auth_security`` intentionally reloads :mod:`auth` with an invalid
    salt-file mode.  Environment restoration does not reset the module-level
    configuration captured by that reload, so a later portal fixture could
    inherit the rejected file path instead of its own deterministic test salt.
    The production 0600 validation remains covered by the security test; this
    fixture only establishes the portal suite's in-process test configuration.
    """
    monkeypatch.setattr(auth, "TOKEN_SALT_FILE_RAW", "")
    monkeypatch.setattr(auth, "TOKEN_SALT_RAW", PORTAL_TEST_SALT.decode("ascii"))
    monkeypatch.setattr(auth, "_TOKEN_SALT", None)


@pytest.mark.parametrize(
    ("raw_query", "expected"),
    [
        ("", 30),
        ("days=30", 30),
        ("days=0", 1),
        ("days=99999", 365),
        ("days=invalid", 30),
        ("unused=value&days=7", 7),
    ],
)
def test_usage_days_parser_is_lenient_and_bounded(raw_query: str, expected: int) -> None:
    assert api_server._parse_usage_days(raw_query) == expected  # noqa: SLF001 - public route contract


def _token_hash(token: str) -> str:
    return auth._hash_token(token)  # noqa: SLF001 - exercise real middleware token lookup


def _token_record(
    token: str, tenant_id: str, scopes: list[str], **extra: Any
) -> tuple[str, dict[str, Any]]:
    return (
        _token_hash(token),
        {
            "tenant_id": tenant_id,
            "tier": "starter",
            "scopes": scopes,
            "auth_method": "token_hash",
            **extra,
        },
    )


class _Harness:
    def __init__(self, base_url: str) -> None:
        host, _, port = base_url.removeprefix("http://").partition(":")
        self._host = host
        self._port = int(port)
        self.last_response_headers: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        target: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            self._host, port=self._port, timeout=5
        )
        headers: list[tuple[str, str]] = []
        if token is not None:
            headers.append(("Authorization", f"Bearer {token}"))
        raw_body = None if body is None else json.dumps(body).encode("utf-8")
        if raw_body is not None:
            headers.append(("Content-Type", "application/json"))
        connection.request(method, target, body=raw_body, headers=dict(headers))
        response = connection.getresponse()
        raw = response.read()
        self.last_response_headers = response.getheaders()
        response_headers = {
            name.lower(): value for name, value in self.last_response_headers
        }
        status = response.status
        connection.close()
        payload = None
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        return status, payload, response_headers, raw


@pytest.fixture
def portal_server(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    tokens = dict(
        [
            _token_record(
                "customer-token",
                "tenant-customer",
                ["read"],
                daily_limit=5000,
                max_concurrent=3,
                expires_at=FUTURE_TS,
                data_categories=["a_share", "news"],
            ),
            _token_record("admin-token", "tenant-admin", ["read"], tier="internal"),
            _token_record(
                "commercial-token",
                "tenant-commercial",
                ["read"],
                tier="standard",
                daily_limit=1,
            ),
            _token_record(
                "expired-token", "tenant-expired", ["read"], expires_at=PAST_TS
            ),
            _token_record(
                "disabled-token", "tenant-disabled", ["read"], enabled=False
            ),
        ]
    )
    monkeypatch.setattr(auth, "_TOKEN_HASHES", tokens)
    monkeypatch.setattr(auth, "LOCALHOST_BYPASS", False)
    monkeypatch.setattr(auth, "_REQUEST_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_DAILY_REQUEST_LOG", auth.OrderedDict())
    monkeypatch.setattr(auth, "_ACTIVE_REQUESTS", {})
    # Also reset the pre-auth limiter: a prior file in the same worker process
    # (e.g. test_auth_security's authenticate storm) otherwise leaves this host
    # rate-limited and every portal request 429s.
    monkeypatch.setattr(auth, "_PREAUTH_LOG", auth.OrderedDict())
    monkeypatch.setattr(api_server, "auth", auth)

    server = api_server.TradingDatasHTTPServer(
        ("127.0.0.1", 0),
        api_server.Handler,
        request_timeout=5,
        max_threads=8,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Harness(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _error_shape(payload: dict[str, Any], expected_code: str) -> None:
    assert payload["api_version"] == "v1"
    assert payload["request_id"]
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["retryable"] is (expected_code == "rate_limited")


def test_portal_me_requires_token(portal_server: _Harness) -> None:
    status, payload, headers, _ = portal_server.request("GET", "/portal/api/me")
    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")
    assert headers["access-control-allow-origin"] == "*"


def test_portal_me_returns_only_own_account(portal_server: _Harness) -> None:
    status, payload, _, raw = portal_server.request(
        "GET", "/portal/api/me", token="customer-token"
    )
    assert status == 200
    assert payload is not None
    assert raw.find(b"tenant-admin") == -1
    assert payload["api_version"] == "v1"
    assert payload["portal"] == {
        "tenant_id": "tenant-customer",
        "tier": "starter",
        "scopes": ["read"],
        "data_categories": ["a_share", "news"],
        "data_category_mode": "restricted",
        "enabled": True,
        "max_concurrent": 3,
        "hourly_request_limit": 60,
        "minute_request_limit": None,
        "daily_limit": 5000,
        "request_volume_unlimited": False,
        "expires_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(FUTURE_TS)
        ),
        "usage": {
            "today_date": None,
            "today_count": 0,
            "hourly_count": 1,
            "hourly_window_seconds": 3600,
        },
    }


def test_portal_me_disabled_token_rejected(portal_server: _Harness) -> None:
    status, payload, _, _ = portal_server.request(
        "GET", "/portal/api/me", token="disabled-token"
    )
    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")


def test_portal_me_projects_commercial_tier_as_unmetered(
    portal_server: _Harness,
) -> None:
    status, payload, _, _ = portal_server.request(
        "GET", "/portal/api/me", token="commercial-token"
    )
    assert status == 200
    assert payload is not None
    portal = payload["portal"]
    assert portal["tier"] == "standard"
    assert portal["max_concurrent"] is None
    assert portal["request_volume_unlimited"] is False
    assert portal["hourly_request_limit"] is None
    assert portal["minute_request_limit"] == 600
    assert portal["daily_limit"] is None


def test_portal_me_expired_token_rejected(portal_server: _Harness) -> None:
    status, payload, _, _ = portal_server.request(
        "GET", "/portal/api/me", token="expired-token"
    )
    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")


def test_portal_me_internal_tier_sees_unlimited_limits(
    portal_server: _Harness,
) -> None:
    status, payload, _, _ = portal_server.request(
        "GET", "/portal/api/me", token="admin-token"
    )
    assert status == 200
    assert payload is not None
    portal = payload["portal"]
    assert portal["tenant_id"] == "tenant-admin"
    assert portal["tier"] == "internal"
    assert portal["max_concurrent"] is None
    assert portal["daily_limit"] is None
    assert portal["hourly_request_limit"] is None
    assert portal["expires_at"] is None


def test_portal_me_unknown_portal_path_404(portal_server: _Harness) -> None:
    status, payload, _, _ = portal_server.request(
        "GET", "/portal/api/other", token="customer-token"
    )
    assert status == 404
    assert payload is not None
    _error_shape(payload, "not_found")


def test_portal_me_post_method_405(portal_server: _Harness) -> None:
    status, payload, headers, _ = portal_server.request(
        "POST", "/portal/api/me", token="customer-token"
    )
    assert status == 405
    assert headers["allow"] == "GET, OPTIONS"
    assert payload is not None
    _error_shape(payload, "method_not_allowed")


def test_portal_me_options_preflight_without_credentials(
    portal_server: _Harness,
) -> None:
    status, payload, headers, _ = portal_server.request(
        "OPTIONS", "/portal/api/me"
    )
    assert status == 204
    assert payload is None
    assert headers["access-control-allow-origin"] == "*"
    assert "authorization" in headers["access-control-allow-headers"].lower()


def test_portal_me_does_not_burn_daily_quota(portal_server: _Harness) -> None:
    for expected_hourly in (1, 2):
        status, payload, _, _ = portal_server.request(
            "GET", "/portal/api/me", token="customer-token"
        )
        assert status == 200
        usage = payload["portal"]["usage"]  # type: ignore[index]
        assert usage["today_count"] == 0
        assert usage["hourly_count"] == expected_hourly


def test_portal_me_usage_scoped_to_own_tenant(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "get_usage_history",
        lambda days=30: [
            {
                "date": "2026-08-22",
                "total": 90,
                "by_tenant": {"tenant-customer": 70, "tenant-admin": 20},
            },
            {
                "date": "2026-08-23",
                "total": 5,
                "by_tenant": {"tenant-customer": 5},
            },
        ],
    )
    status, payload, _, raw = portal_server.request(
        "GET", "/portal/api/me/usage?days=7", token="customer-token"
    )
    assert status == 200
    assert payload is not None
    assert raw.find(b"tenant-admin") == -1
    usage = payload["portal_usage"]
    assert usage["tenant_id"] == "tenant-customer"
    assert usage["daily_limit"] == 5000
    assert usage["history"] == [
        {"date": "2026-08-22", "total": 70},
        {"date": "2026-08-23", "total": 5},
    ]


def test_portal_me_usage_requires_token(portal_server: _Harness) -> None:
    status, payload, _, _ = portal_server.request("GET", "/portal/api/me/usage")
    assert status == 401
    assert payload is not None
    _error_shape(payload, "unauthenticated")


def test_portal_me_usage_days_out_of_range_clamped(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def _fake_history(days: int = 30) -> list[dict[str, Any]]:
        seen.append(days)
        return []

    monkeypatch.setattr(auth, "get_usage_history", _fake_history)
    for target in (
        "/portal/api/me/usage?days=0",
        "/portal/api/me/usage?days=99999",
        "/portal/api/me/usage?days=abc",
    ):
        status, _, _, _ = portal_server.request(
            "GET", target, token="customer-token"
        )
        assert status == 200
    assert sorted(seen) == [1, 30, 365]


def test_effective_limits_resolution() -> None:
    internal = auth.effective_limits({"tenant_id": "t", "tier": "internal"})
    assert internal == {
        "tier": "internal",
        "hourly_request_limit": None,
        "minute_request_limit": None,
        "concurrency_limit": None,
        "daily_limit": None,
        "request_volume_unlimited": True,
    }
    free = auth.effective_limits({"tenant_id": "t"})
    assert free["tier"] == "free"
    assert free["hourly_request_limit"] == auth.RATE_LIMITS["free"]
    assert free["minute_request_limit"] is None
    assert free["concurrency_limit"] == auth.CONCURRENCY_LIMITS["free"]
    assert free["request_volume_unlimited"] is False
    standard = auth.effective_limits({"tenant_id": "t", "tier": "standard"})
    assert standard["hourly_request_limit"] is None
    assert standard["minute_request_limit"] == 600
    assert standard["daily_limit"] is None
    assert standard["concurrency_limit"] is None
    assert standard["request_volume_unlimited"] is False
    override = auth.effective_limits(
        {"tenant_id": "t", "tier": "research", "max_concurrent": 9}
    )
    assert override["concurrency_limit"] == 9
    unlimited = auth.effective_limits(
        {"tenant_id": "t", "tier": "research", "max_concurrent": 0}
    )
    assert unlimited["concurrency_limit"] is None
    ignored_daily = auth.effective_limits(
        {"tenant_id": "t", "daily_limit": 0}
    )
    assert ignored_daily["daily_limit"] is None


def test_portal_keys_lists_only_current_tenant_and_masks_hashes(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth,
        "list_customer_tokens",
        lambda account: [
            {
                "key_id": "key_1234567890abcdef",
                "label": "Research laptop",
                "enabled": True,
                "created_at": None,
                "last_used_at": None,
                "is_current": True,
                "fingerprint": "12345678...cdef",
            }
        ],
    )
    status, payload, _, raw = portal_server.request(
        "GET", "/portal/api/me/keys", token="customer-token"
    )
    assert status == 200
    assert payload is not None
    assert payload["api_keys"][0]["is_current"] is True
    assert b"tenant-admin" not in raw
    assert b"token_hash" not in raw


def test_portal_keys_create_uses_customer_scoped_contract(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[dict[str, Any], str]] = []

    def _create(account: dict[str, Any], label: str) -> dict[str, Any]:
        seen.append((account, label))
        return {
            "key": "one-time-secret",
            "api_key": {
                "key_id": "key_feedfacecafebeef",
                "label": label,
                "enabled": True,
                "is_current": False,
                "fingerprint": "feedface...beef",
            },
        }

    monkeypatch.setattr(auth, "create_customer_token", _create)
    status, payload, _, _ = portal_server.request(
        "POST",
        "/portal/api/me/keys",
        token="customer-token",
        body={"label": "Codex on MacBook"},
    )
    assert status == 201
    assert payload == {
        "api_version": "v1",
        "api_key": {
            "key_id": "key_feedfacecafebeef",
            "label": "Codex on MacBook",
            "enabled": True,
            "is_current": False,
            "fingerprint": "feedface...beef",
        },
        "key": "one-time-secret",
    }
    assert seen[0][0]["tenant_id"] == "tenant-customer"
    assert seen[0][1] == "Codex on MacBook"


def test_portal_keys_disable_cannot_target_current_credential(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _disable(account: dict[str, Any], key_id: str) -> dict[str, Any]:
        raise auth.AuthError("current credential cannot be disabled")

    monkeypatch.setattr(auth, "disable_customer_token", _disable)
    status, payload, _, _ = portal_server.request(
        "PATCH",
        "/portal/api/me/keys/key_current000000",
        token="customer-token",
        body={"enabled": False},
    )
    assert status == 400
    assert payload == {"error": "current credential cannot be disabled"}


def test_portal_keys_rejects_privilege_mutation_fields(
    portal_server: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "disable_customer_token", lambda *_: {})
    status, payload, _, _ = portal_server.request(
        "PATCH",
        "/portal/api/me/keys/key_other00000000",
        token="customer-token",
        body={"tier": "internal", "enabled": False},
    )
    assert status == 400
    assert payload is not None
    _error_shape(payload, "invalid_request")
