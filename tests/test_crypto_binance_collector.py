from __future__ import annotations

import requests

from collectors.crypto.binance import CryptoCollector


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


class _FlakySession:
    def __init__(self) -> None:
        self.calls = 0
        self.proxies = {}

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise requests.exceptions.SSLError("transient eof")
        return _Response()


def test_binance_health_check_retries_transient_requests_errors():
    collector = CryptoCollector(config={"retry": {"max_attempts": 1}})
    session = _FlakySession()
    collector._session = session
    collector.retry_base_delay = 0
    collector.retry_jitter = False

    result = collector.health_check()

    assert result["status"] == "available"
    assert session.calls == 2


def test_binance_get_falls_back_to_second_proxy():
    collector = CryptoCollector(config={"retry": {"max_attempts": 1}}, proxy="http://sg-relay:8080,http://127.0.0.1:7890")
    seen: list[dict] = []

    class Session:
        def get(self, *args, **kwargs):
            seen.append(kwargs.get("proxies") or {})
            if kwargs.get("proxies", {}).get("https") == "http://sg-relay:8080":
                raise requests.exceptions.ProxyError("sg relay unavailable")
            return _Response()

    collector._session = Session()

    response = collector._get("https://api.binance.com/api/v3/ping", timeout=10)

    assert response.status_code == 200
    assert seen == [
        {"http": "http://sg-relay:8080", "https": "http://sg-relay:8080"},
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    ]
