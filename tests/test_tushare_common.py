import json
import urllib.error

from collectors.tushare import tushare_common


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_tushare_data_retries_transient_http_error(monkeypatch):
    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append((request, timeout))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None)
        return _Response({"code": 0, "data": {"fields": ["value"], "items": [[1]]}})

    monkeypatch.setattr(tushare_common, "get_token", lambda: "test-token")
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(tushare_common.urllib.request, "urlopen", fake_urlopen)

    result = tushare_common.tushare_data("rt_min", retries=2)

    assert result == {"fields": ["value"], "items": [[1]]}
    assert len(attempts) == 2
