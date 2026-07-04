from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

import api_server


class _FakeAuth:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def authenticate(self, headers: Any, client_host: str) -> dict[str, Any]:
        return {"tenant_id": "test", "tier": "internal", "scopes": ["full"]}

    def check_endpoint_scope(self, account: dict[str, Any], path: str) -> bool:
        return True

    def request_fingerprint(self, path: str, params: dict[str, Any]) -> str:
        return json.dumps({"path": path, "params": params}, sort_keys=True)

    def get_cached_response(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            cached = self._cache.get(fingerprint)
            return json.loads(json.dumps(cached)) if cached is not None else None

    def store_cached_response(self, fingerprint: str, response: dict[str, Any]) -> None:
        with self._lock:
            self._cache[fingerprint] = json.loads(json.dumps(response))

    def enforce_rate_limit(self, tenant_id: str, tier: str) -> None:
        return None

    def cache_stats(self) -> dict[str, Any]:
        with self._lock:
            return {"dedup_entries": len(self._cache)}


class _FakeReader:
    CACHE_TTL_SECONDS = 300
    _CACHE_GENERATION = 0
    _CACHED_FUNCTIONS = ("get_events",)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.clear_count = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_events(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        return []

    def get_sentiment(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("get_sentiment", {"start": start, "end": end}))
        return [
            {"data": {"signal_id": "s001"}, "degraded": False},
            {"data": {"signal_id": "s002"}, "degraded": False},
        ]

    def get_realtime_5min(self, ts_code: str, date: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("get_realtime_5min", {"ts_code": ts_code, "date": date}))
        return [
            {"data": {"bar_time": "09:30"}, "degraded": False},
            {"data": {"bar_time": "09:35"}, "degraded": False},
        ]

    def get_market_data(
        self,
        ts_code: str,
        start: str | None = None,
        end: str | None = None,
        freq: str = "daily",
    ) -> list[dict[str, Any]]:
        self.calls.append(("get_market_data", {"ts_code": ts_code, "start": start, "end": end, "freq": freq}))
        return []

    def get_capital_flow(
        self,
        date: str | None = None,
        ts_code: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append(("get_capital_flow", {"date": date, "ts_code": ts_code, **kwargs}))
        return []

    def clear_caches(self) -> None:
        with self._lock:
            self.clear_count += 1
            self._CACHE_GENERATION += 1


@pytest.fixture
def api_edge_server(monkeypatch):
    fake_auth = _FakeAuth()
    fake_reader = _FakeReader()
    monkeypatch.setattr(api_server, "auth", fake_auth)
    monkeypatch.setattr(api_server, "reader", fake_reader)

    server = api_server.SharedSignalsHTTPServer(
        ("127.0.0.1", 0),
        api_server.Handler,
        request_timeout=5,
        max_threads=8,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url, fake_reader
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get_json(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(base_url + path, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_api_request_with_no_query_params_does_not_crash(api_edge_server) -> None:
    base_url, _reader = api_edge_server

    status, payload = _get_json(base_url, "/events")

    assert status == 200
    assert payload["data"] == []


def test_api_malformed_json_query_param_returns_400(api_edge_server) -> None:
    base_url, _reader = api_edge_server
    bad_json = urllib.parse.quote("{broken", safe="")

    status, payload = _get_json(base_url, f"/events?filters={bad_json}")

    assert status == 400
    assert "malformed JSON" in payload["error"]


def test_api_unknown_endpoint_returns_404(api_edge_server) -> None:
    base_url, _reader = api_edge_server

    status, payload = _get_json(base_url, "/unknown-endpoint")

    assert status == 404
    assert "unknown endpoint" in payload["error"]


def test_api_concurrent_cache_invalidate_calls_do_not_corrupt_state(api_edge_server) -> None:
    base_url, reader = api_edge_server

    def call_invalidate(_: int) -> int:
        status, payload = _get_json(base_url, "/cache/invalidate")
        assert payload["status"] == "ok"
        return status

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(call_invalidate, range(32)))

    status, payload = _get_json(base_url, "/cache/status")

    assert statuses == [200] * 32
    assert status == 200
    assert payload["generation"] >= 1
    assert reader.clear_count >= 1


def test_api_oversize_query_is_handled_gracefully(api_edge_server) -> None:
    base_url, _reader = api_edge_server
    oversized = "x" * 12_000

    status, payload = _get_json(base_url, f"/events?padding={oversized}")

    assert status == 200
    assert payload["data"] == []


def test_api_passes_market_data_freq_and_capital_flow_range_params(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/market_data?ts_code=000001.SZ&start=20260701&end=20260702&freq=5m")
    assert status == 200
    assert payload["data"] == []

    status, payload = _get_json(base_url, "/capital_flow?ts_code=000001.SZ&start=20260701&end=20260702")
    assert status == 200
    assert payload["data"] == []

    assert reader.calls == [
        ("get_market_data", {"ts_code": "000001.SZ", "start": "20260701", "end": "20260702", "freq": "5m"}),
        (
            "get_capital_flow",
            {
                "date": "20260701",
                "ts_code": "000001.SZ",
                "start_date": "20260701",
                "end_date": "20260702",
            },
        ),
    ]


def test_api_limit_applies_to_sentiment_and_realtime(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/sentiment?limit=1")
    assert status == 200
    assert payload["data"] == [{"signal_id": "s001"}]

    status, payload = _get_json(base_url, "/realtime_5min?ts_code=000001.SZ&limit=1")
    assert status == 200
    assert payload["data"] == [{"bar_time": "09:30"}]

    assert reader.calls[-2:] == [
        ("get_sentiment", {"start": None, "end": None}),
        ("get_realtime_5min", {"ts_code": "000001.SZ", "date": None}),
    ]
