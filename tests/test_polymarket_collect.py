import json
from typing import Any

from collectors import polymarket_collect as pm


def test_price_rows_use_outcome_prices():
    market = {
        "id": "m1",
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "outcomes": json.dumps(["Yes", "No"]),
    }

    rows = list(pm.price_rows(market, "2026-07-04T00:00:00+00:00"))

    assert len(rows) == 2
    assert rows[0][1] == "m1"
    assert rows[0][2] == "yes-token"
    assert rows[0][4] == 0.62
    assert json.loads(rows[0][8])["outcome"] == "Yes"


def test_price_rows_fallback_to_midpoint():
    market = {
        "id": "m2",
        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
        "bestBid": 0.51,
        "bestAsk": 0.53,
    }

    rows = list(pm.price_rows(market, "2026-07-04T00:00:00+00:00"))

    assert [row[4] for row in rows] == [0.52, 0.48]


class _Response:
    def __init__(self, payload: Any):
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_open_json_uses_proxy_without_direct_fallback_by_default(monkeypatch):
    routes: list[dict[str, str]] = []

    def fake_proxy_handler(proxies):
        return proxies

    class FakeOpener:
        def __init__(self, proxies):
            self.proxies = proxies

        def open(self, req, timeout=25):  # noqa: ANN001
            routes.append(self.proxies)
            return _Response([{"id": "m1"}])

    monkeypatch.setattr(pm.urllib.request, "ProxyHandler", fake_proxy_handler)
    monkeypatch.setattr(pm.urllib.request, "build_opener", lambda handler: FakeOpener(handler))

    payload = pm.open_json("https://example.test", proxy="http://127.0.0.1:7890", retries=1)

    assert payload == [{"id": "m1"}]
    assert routes == [{"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}]


def test_open_json_direct_fallback_requires_explicit_flag(monkeypatch):
    routes: list[dict[str, str]] = []

    def fake_proxy_handler(proxies):
        return proxies

    class FakeOpener:
        def __init__(self, proxies):
            self.proxies = proxies

        def open(self, req, timeout=25):  # noqa: ANN001
            routes.append(self.proxies)
            if self.proxies:
                raise OSError("proxy route unavailable")
            return _Response([{"id": "direct"}])

    monkeypatch.setattr(pm.urllib.request, "ProxyHandler", fake_proxy_handler)
    monkeypatch.setattr(pm.urllib.request, "build_opener", lambda handler: FakeOpener(handler))

    payload = pm.open_json(
        "https://example.test",
        proxy="http://127.0.0.1:7890",
        retries=1,
        direct_fallback=True,
    )

    assert payload == [{"id": "direct"}]
    assert routes == [
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        {},
    ]


def test_open_json_tries_proxy_list_before_fallback(monkeypatch):
    routes: list[dict[str, str]] = []

    def fake_proxy_handler(proxies):
        return proxies

    class FakeOpener:
        def __init__(self, proxies):
            self.proxies = proxies

        def open(self, req, timeout=25):  # noqa: ANN001
            routes.append(self.proxies)
            if self.proxies.get("https") == "http://sg-relay:8080":
                raise OSError("sg relay unavailable")
            return _Response([{"id": "local-clash"}])

    monkeypatch.setattr(pm.urllib.request, "ProxyHandler", fake_proxy_handler)
    monkeypatch.setattr(pm.urllib.request, "build_opener", lambda handler: FakeOpener(handler))

    payload = pm.open_json(
        "https://example.test",
        proxy="http://sg-relay:8080,http://127.0.0.1:7890",
        retries=1,
    )

    assert payload == [{"id": "local-clash"}]
    assert routes == [
        {"http": "http://sg-relay:8080", "https": "http://sg-relay:8080"},
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    ]
