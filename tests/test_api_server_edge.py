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
from tools import health_check


class _FakeAuth:
    SCOPE_ENDPOINTS = {
        "health": {"/health", "/capabilities", "/cache/status", "/cache/invalidate"},
        "market_data": {"/market_data", "/realtime_5min", "/is_trading_day"},
        "full": {"*"},
    }

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

    def get_events(
        self,
        start: str | None = None,
        end: str | None = None,
        event_type: str | None = None,
        market: str | None = None,
        symbol: str | None = None,
        subject_code: str | None = None,
        subject_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.calls.append((
            "get_events",
            {
                "start": start,
                "end": end,
                "event_type": event_type,
                "market": market,
                "symbol": symbol,
                "subject_code": subject_code,
                "subject_type": subject_type,
                "limit": limit,
            },
        ))
        return []

    def get_sentiment(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("get_sentiment", {"start": start, "end": end}))
        return [
            {"data": {"signal_id": "s001"}, "degraded": False},
            {"data": {"signal_id": "s002"}, "degraded": False},
        ]

    def get_realtime_5min(self, ts_code: str = "", date: str | None = None, market: str = "Ashare") -> list[dict[str, Any]]:
        self.calls.append(("get_realtime_5min", {"ts_code": ts_code, "date": date, "market": market}))
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

    def get_pm_prices(self, market_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        self.calls.append(("get_pm_prices", {"market_id": market_id, "limit": limit}))
        return [
            {"data": {"market_id": market_id or "pm-1", "price": 0.42}, "degraded": False},
        ]

    def get_crypto_klines(self, symbol: str) -> list[dict[str, Any]]:
        self.calls.append(("get_crypto_klines", {"symbol": symbol}))
        return [
            {"data": {"symbol": symbol, "close": 100.0}, "degraded": False},
            {"data": {"symbol": symbol, "close": 101.0}, "degraded": False},
            {"data": {"symbol": symbol, "close": 102.0}, "degraded": False},
        ]

    def get_tushare(
        self,
        api_name: str,
        ts_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        **params: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append((
            "get_tushare",
            {
                "api_name": api_name,
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                **params,
            },
        ))
        return [
            {"data": {"title": "news-1"}, "degraded": False, "provenance": {"source_id": "tushare_news"}},
            {"data": {"title": "news-2"}, "degraded": False, "provenance": {"source_id": "tushare_news"}},
            {"data": {"title": "news-3"}, "degraded": False, "provenance": {"source_id": "tushare_news"}},
        ]

    def get_fundamentals(self, ts_code: str, limit: int = 200) -> list[dict[str, Any]]:
        self.calls.append(("get_fundamentals", {"ts_code": ts_code, "limit": limit}))
        return [{"data": {"symbol": ts_code, "factor_name": "unit"}, "degraded": False}]

    def get_macro_factors(self, start: str | None = None, end: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        self.calls.append(("get_macro_factors", {"start": start, "end": end, "limit": limit}))
        return [{"data": {"factor_name": "macro"}, "degraded": False}]

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
    return _request_json(base_url, path)


def _request_json(base_url: str, path: str, *, method: str = "GET") -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(base_url + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_api_request_with_no_query_params_does_not_crash(api_edge_server) -> None:
    base_url, _reader = api_edge_server

    status, payload = _get_json(base_url, "/events")

    assert status == 200
    assert payload["data"] == []


def test_api_events_passes_filter_params_to_reader(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(
        base_url,
        "/events?market=Ashare&symbol=600000.SH&subject_type=stock&event_type=policy&start=20260701&end=20260708&limit=5",
    )

    assert status == 200
    assert payload["data"] == []
    assert reader.calls[-1] == (
        "get_events",
        {
            "start": "20260701",
            "end": "20260708",
            "event_type": "policy",
            "market": "Ashare",
            "symbol": "600000.SH",
            "subject_code": "600000.SH",
            "subject_type": "stock",
            "limit": 5,
        },
    )


def test_api_tushare_applies_limit(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/tushare?api_name=news&limit=2")

    assert status == 200
    assert [row["title"] for row in payload["data"]] == ["news-1", "news-2"]
    assert payload["metadata"]["degraded"] is False
    assert reader.calls[-1][0] == "get_tushare"


def test_api_crypto_applies_limit(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/crypto?symbol=BTCUSDT&limit=2")

    assert status == 200
    assert [row["close"] for row in payload["data"]] == [100.0, 101.0]
    assert reader.calls[-1] == ("get_crypto_klines", {"symbol": "BTCUSDT"})


def test_api_fundamentals_passes_limit_to_reader(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/fundamentals?ts_code=000001.SZ&limit=7")

    assert status == 200
    assert payload["data"] == [{"symbol": "000001.SZ", "factor_name": "unit"}]
    assert reader.calls[-1] == ("get_fundamentals", {"ts_code": "000001.SZ", "limit": 7})


def test_api_macro_passes_limit_to_reader(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/macro?start=20260701&end=20260708&limit=9")

    assert status == 200
    assert payload["data"] == [{"factor_name": "macro"}]
    assert reader.calls[-1] == ("get_macro_factors", {"start": "20260701", "end": "20260708", "limit": 9})


def test_aggregate_metadata_drops_degraded_empty_data_rows() -> None:
    rows = [
        {
            "data": {},
            "degraded": True,
            "lineage": {"reason": "missing sqlite db"},
            "freshness": {"stale": True, "score": 0.0},
            "quality": {"score": 0.0},
            "provenance": {"source_id": "sqlite:market_events"},
        }
    ]

    payload, metadata, source = api_server.aggregate_metadata(rows)

    assert payload == []
    assert metadata["degraded"] is True
    assert metadata["degraded_reasons"] == ["missing sqlite db"]
    assert source == "sqlite:market_events"


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


def test_api_cache_invalidate_accepts_post(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _request_json(base_url, "/cache/invalidate", method="POST")

    assert status == 200
    assert payload["status"] == "ok"
    assert reader.clear_count == 1


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


def test_api_pm_prices_endpoint_uses_reader(api_edge_server) -> None:
    base_url, reader = api_edge_server

    status, payload = _get_json(base_url, "/pm_prices?market_id=pm-1&limit=5")

    assert status == 200
    assert payload["data"] == [{"market_id": "pm-1", "price": 0.42}]
    assert reader.calls[-1] == ("get_pm_prices", {"market_id": "pm-1", "limit": 5})


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
        ("get_realtime_5min", {"ts_code": "000001.SZ", "date": None, "market": "Ashare"}),
    ]

    status, payload = _get_json(base_url, "/realtime_5min?market=Futures&ts_code=RB2609.SHF&date=20260703&limit=1")
    assert status == 200
    assert payload["data"] == [{"bar_time": "09:30"}]
    assert reader.calls[-1] == (
        "get_realtime_5min",
        {"ts_code": "RB2609.SHF", "date": "20260703", "market": "Futures"},
    )

    status, payload = _get_json(base_url, "/realtime_5min?market=Futures&date=20260703&limit=1")
    assert status == 200
    assert payload["data"] == [{"bar_time": "09:30"}]
    assert reader.calls[-1] == (
        "get_realtime_5min",
        {"ts_code": "", "date": "20260703", "market": "Futures"},
    )


def test_capabilities_falls_back_when_registry_missing(api_edge_server, monkeypatch) -> None:
    base_url, _reader = api_edge_server
    monkeypatch.setattr(api_server, "CAPABILITY_PATH", api_server.ROOT / "tools" / "__missing_capability_registry__.json")

    status, payload = _get_json(base_url, "/capabilities")

    assert status == 200
    assert payload["source"] == "capability_fallback"
    assert payload["metadata"]["degraded"] is True
    assert payload["data"]["status"] == "degraded"
    assert any(item["path"] == "/market_data" for item in payload["data"]["endpoints"])


def test_api_health_defaults_to_lightweight_cached_checks(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_health_status(**kwargs):
        calls.append(dict(kwargs))
        return {"status": "ok", "checks": {"sla": {"status": "ok"}}, "timestamp": "2026-07-07T00:00:00"}

    monkeypatch.delenv(api_server.HEALTH_DEEP_CHECKS_ENV, raising=False)
    monkeypatch.setattr(health_check, "get_health_status", fake_get_health_status)
    monkeypatch.setattr(api_server, "_health_cache", None)
    monkeypatch.setattr(api_server, "_health_cache_time", 0.0)

    result = api_server._get_health()

    assert result["status"] == "ok"
    assert calls == [
        {
            "check_functions": False,
            "check_data_freshness": False,
            "check_cron": True,
            "check_arch": False,
            "check_compile": False,
        }
    ]


def test_api_health_deep_checks_are_explicit(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_health_status(**kwargs):
        calls.append(dict(kwargs))
        return {"status": "ok", "checks": {}, "timestamp": "2026-07-07T00:00:00"}

    monkeypatch.setenv(api_server.HEALTH_DEEP_CHECKS_ENV, "1")
    monkeypatch.setattr(health_check, "get_health_status", fake_get_health_status)
    monkeypatch.setattr(api_server, "_health_cache", None)
    monkeypatch.setattr(api_server, "_health_cache_time", 0.0)

    api_server._get_health()

    assert calls[0]["check_functions"] is True
    assert calls[0]["check_data_freshness"] is True


def test_sharedsignals_server_uses_large_accept_backlog() -> None:
    assert api_server.SharedSignalsHTTPServer.request_queue_size >= 256


def test_send_json_tolerates_client_disconnect() -> None:
    handler = api_server.Handler.__new__(api_server.Handler)
    calls: list[tuple[str, object]] = []

    handler.send_response = lambda status: calls.append(("status", status))  # type: ignore[method-assign]
    handler.send_header = lambda key, value: calls.append((key, value))  # type: ignore[method-assign]
    handler.end_headers = lambda: calls.append(("end_headers", True))  # type: ignore[method-assign]

    class DisconnectingWriter:
        def write(self, _body: bytes) -> None:
            raise BrokenPipeError("client closed")

    handler.wfile = DisconnectingWriter()

    handler._send_json({"status": "ok"})

    assert ("status", 200) in calls
