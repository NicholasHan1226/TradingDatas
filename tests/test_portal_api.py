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
    ) -> tuple[int, dict[str, Any] | None, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            self._host, port=self._port, timeout=5
        )
        headers: list[tuple[str, str]] = []
        if token is not None:
            headers.append(("Authorization", f"Bearer {token}"))
        connection.request(method, target, body=None, headers=dict(headers))
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
            ),
            _token_record("admin-token", "tenant-admin", ["read"], tier="internal"),
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
        "enabled": True,
        "max_concurrent": 3,
        "hourly_request_limit": 60,
        "daily_limit": 5000,
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
        "concurrency_limit": None,
        "daily_limit": None,
    }
    free = auth.effective_limits({"tenant_id": "t"})
    assert free["tier"] == "free"
    assert free["hourly_request_limit"] == auth.RATE_LIMITS["free"]
    assert free["concurrency_limit"] == auth.CONCURRENCY_LIMITS["free"]
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
