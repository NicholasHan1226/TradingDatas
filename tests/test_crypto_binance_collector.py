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
