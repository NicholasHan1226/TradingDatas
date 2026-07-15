import json
import urllib.error
from dataclasses import FrozenInstanceError

import pytest

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


def _stub_outcome_response(monkeypatch, payload: dict) -> list[dict]:
    requests: list[dict] = []

    def fake_urlopen(request, timeout):
        requests.append(
            {
                "payload": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _Response(payload)

    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(tushare_common.urllib.request, "urlopen", fake_urlopen)
    return requests


def test_tushare_rows_outcome_preserves_success_rows_and_is_frozen(monkeypatch):
    requests = _stub_outcome_response(
        monkeypatch,
        {
            "code": 0,
            "msg": None,
            "data": {
                "fields": ["ts_code", "close"],
                "items": [["000001.SZ", 10.5]],
            },
        },
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "stub-token",
        params={"trade_date": "20260715"},
        fields="ts_code,close",
    )

    assert outcome == tushare_common.ProviderCallOutcome(
        state="success",
        rows=({"ts_code": "000001.SZ", "close": 10.5},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    assert requests == [
        {
            "payload": {
                "api_name": "daily",
                "token": "stub-token",
                "params": {"trade_date": "20260715"},
                "fields": "ts_code,close",
            },
            "timeout": 30,
        }
    ]
    with pytest.raises(FrozenInstanceError):
        outcome.state = "empty"


def test_tushare_rows_outcome_marks_valid_zero_rows_empty(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        {"code": 0, "msg": None, "data": {"fields": ["ts_code"], "items": []}},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome == tushare_common.ProviderCallOutcome(
        state="empty",
        rows=(),
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def test_tushare_rows_outcome_keeps_unknown_provider_error_failed(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        {
            "code": 70001,
            "msg": "upstream rejected request",
            "data": {"fields": ["value"], "items": [[1]]},
        },
    )

    outcome = tushare_common.tushare_rows_outcome("unknown_api", "stub-token")

    assert outcome == tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=70001,
        error_code="provider_error",
        error_message="upstream rejected request",
    )


def test_tushare_rows_outcome_classifies_entitlement_denial(monkeypatch):
    message = "抱歉，您没有访问该接口的权限"
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("income", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == "permission_denied"
    assert outcome.error_message == message


def test_tushare_rows_outcome_classifies_rate_limit(monkeypatch):
    message = "每分钟最多访问该接口200次"
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == "rate_limited"
    assert outcome.error_message == message


def test_tushare_rows_outcome_does_not_guess_unknown_error_class(monkeypatch):
    message = "upstream internal error"
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == message


def test_tushare_rows_outcome_rejects_malformed_success_data(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        {"code": 0, "msg": None, "data": []},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.provider_code == 0
    assert outcome.error_code == "provider_error"
    assert "mapping" in outcome.error_message


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"code": 0, "msg": None}, id="missing-data"),
        pytest.param({"code": 0, "msg": None, "data": None}, id="null-data"),
        pytest.param(
            {"code": 0, "msg": None, "data": {}}, id="missing-fields-and-items"
        ),
        pytest.param(
            {"code": 0, "msg": None, "data": {"items": [["000001.SZ"]]}},
            id="missing-fields",
        ),
        pytest.param(
            {"code": 0, "msg": None, "data": {"fields": ["ts_code"]}},
            id="missing-items",
        ),
        pytest.param(
            {"code": 0, "msg": None, "data": {"fields": [], "items": []}},
            id="empty-fields",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": "ts_code", "items": []},
            },
            id="fields-not-list",
        ),
        pytest.param(
            {"code": 0, "msg": None, "data": {"fields": [1], "items": []}},
            id="field-not-string",
        ),
        pytest.param(
            {"code": 0, "msg": None, "data": {"fields": [""], "items": []}},
            id="field-empty",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": [" ts_code"], "items": []},
            },
            id="field-invalid-whitespace",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["ts_code", "ts_code"], "items": []},
            },
            id="duplicate-fields",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["ts_code"], "items": None},
            },
            id="null-items",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["ts_code"], "items": {}},
            },
            id="items-not-list",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["ts_code"], "items": ["000001.SZ"]},
            },
            id="row-not-list",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": ["ts_code"],
                    "items": [{"ts_code": "000001.SZ"}],
                },
            },
            id="row-mapping",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": ["ts_code", "close"],
                    "items": [["000001.SZ"]],
                },
            },
            id="row-too-short",
        ),
        pytest.param(
            {
                "code": 0,
                "msg": None,
                "data": {
                    "fields": ["ts_code"],
                    "items": [["000001.SZ", 10.5]],
                },
            },
            id="row-too-long",
        ),
    ],
)
def test_tushare_rows_outcome_rejects_incomplete_or_lossy_success_schema(
    monkeypatch,
    payload,
):
    _stub_outcome_response(monkeypatch, payload)

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.provider_code == 0
    assert outcome.error_code == "provider_error"
    assert outcome.error_message


@pytest.mark.parametrize(
    "message",
    [
        "internal permission service error",
        "rate limiter internal service error",
        "throttling policy cache unavailable",
        "权限缓存服务异常",
        "访问频率配置服务异常",
        "权限不足检测服务异常",
        "请求频繁检测服务异常",
    ],
)
def test_tushare_rows_outcome_does_not_classify_internal_service_text(
    monkeypatch,
    message,
):
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == message


def test_tushare_rows_outcome_keeps_transport_exception_failed(monkeypatch):
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("offline")
        ),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.provider_code is None
    assert outcome.error_code == "provider_error"
    assert "offline" in outcome.error_message
