import json
import math
import urllib.error
from dataclasses import FrozenInstanceError

import pytest

from collectors.tushare import tushare_common


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _RawResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")


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


@pytest.mark.parametrize(
    ("raw_payload", "constant"),
    [
        pytest.param(
            '{"code": NaN, "msg": null, "data": {"fields": ["value"], "items": []}}',
            "NaN",
            id="top-level-nan",
        ),
        pytest.param(
            '{"code": 0, "msg": null, "data": {"fields": ["value"], "items": [[Infinity]]}}',
            "Infinity",
            id="row-infinity",
        ),
        pytest.param(
            '{"code": 0, "msg": null, "data": {"fields": ["value"], "items": [[1]]}, "meta": {"sentinel": -Infinity}}',
            "-Infinity",
            id="nested-negative-infinity",
        ),
    ],
)
def test_tushare_rows_outcome_rejects_non_finite_raw_json_constants(
    monkeypatch,
    raw_payload,
    constant,
):
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _RawResponse(raw_payload),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_code == "provider_error"
    assert "non-finite JSON constant" in outcome.error_message
    assert constant in outcome.error_message


@pytest.mark.parametrize(
    "raw_payload",
    [
        pytest.param(
            '{"code": -2001, "code": 0, "msg": null, "data": {"fields": ["value"], "items": [[1]]}}',
            id="top-level-code-last-wins",
        ),
        pytest.param(
            '{"code": 0, "msg": null, "data": {"fields": ["value"], "items": [[{"nested": 1, "nested": 2}]]}}',
            id="nested-row-object",
        ),
    ],
)
def test_tushare_rows_outcome_rejects_duplicate_json_keys_at_any_depth(
    monkeypatch,
    raw_payload,
):
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _RawResponse(raw_payload),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.provider_code is None
    assert outcome.error_code == "provider_error"
    assert "duplicate JSON object key" in outcome.error_message


def test_tushare_rows_outcome_rejects_finite_overflow_outside_data(monkeypatch):
    raw_payload = (
        '{"code": 0, "msg": null, "data": '
        '{"fields": ["value"], "items": [[1]]}, "meta": {"sentinel": 1e400}}'
    )
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _RawResponse(raw_payload),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_code == "provider_error"
    assert "non-finite number" in outcome.error_message


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
        pytest.param({"nested": [math.nan]}, id="nested-nan"),
    ],
)
def test_strict_provider_rows_rejects_non_finite_float_values(value):
    with pytest.raises(ValueError, match="finite"):
        tushare_common._strict_provider_rows({"fields": ["value"], "items": [[value]]})


@pytest.mark.parametrize(
    ("state", "rows"),
    [
        pytest.param("failed", ({"value": 1},), id="failed-with-rows"),
        pytest.param("empty", ({"value": 1},), id="empty-with-rows"),
        pytest.param("success", (), id="success-without-rows"),
        pytest.param("unknown", (), id="unknown-state"),
    ],
)
def test_provider_call_outcome_rejects_invalid_state_row_combinations(state, rows):
    with pytest.raises(ValueError, match="outcome"):
        tushare_common.ProviderCallOutcome(
            state=state,
            rows=rows,
            provider_code=-1,
            error_code="provider_error",
            error_message="failed",
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


@pytest.mark.parametrize(
    ("message", "expected_error_code"),
    [
        pytest.param(
            "抱歉，您没有权限访问该接口",
            "permission_denied",
            id="chinese-permission-before-action",
        ),
        pytest.param(
            "you are not allowed to access this endpoint",
            "permission_denied",
            id="english-not-allowed",
        ),
        pytest.param(
            "请求频率太高，请稍后再试",
            "rate_limited",
            id="chinese-frequency-too-high",
        ),
        pytest.param(
            "访问次数超出限制",
            "rate_limited",
            id="chinese-access-count-over-limit",
        ),
    ],
)
def test_tushare_rows_outcome_classifies_explicit_provider_denials(
    monkeypatch,
    message,
    expected_error_code,
):
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == expected_error_code
    assert outcome.error_message == message


@pytest.mark.parametrize(
    ("message", "expected_error_code"),
    [
        pytest.param("permission denied.", "permission_denied", id="permission-period"),
        pytest.param("access denied!", "permission_denied", id="access-exclamation"),
        pytest.param(
            "rate limit has been exceeded.",
            "rate_limited",
            id="rate-limit-period",
        ),
        pytest.param(
            "permission denied, please try again later.",
            "permission_denied",
            id="permission-retry-period",
        ),
        pytest.param(
            "access denied: retry later!",
            "permission_denied",
            id="access-retry-exclamation",
        ),
        pytest.param(
            "rate limit has been exceeded, please try again later.",
            "rate_limited",
            id="rate-limit-retry-period",
        ),
        pytest.param(
            "too many requests; retry later.",
            "rate_limited",
            id="too-many-retry-period",
        ),
    ],
)
def test_tushare_rows_outcome_accepts_natural_terminal_punctuation(
    monkeypatch,
    message,
    expected_error_code,
):
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == expected_error_code
    assert outcome.error_message == message


@pytest.mark.parametrize(
    "message",
    [
        "permission denied, please try again later.",
        "too many requests; retry later.",
    ],
)
def test_retry_suffix_classification_remains_fullmatch_and_code_gated(message):
    assert tushare_common._provider_error_code(70001, message) == "provider_error"
    assert (
        tushare_common._provider_error_code(-2001, f"{message} unrelated")
        == "provider_error"
    )


def test_tushare_rows_outcome_requires_reliable_code_for_specialized_classification(
    monkeypatch,
):
    message = "you are not allowed to access this endpoint"
    _stub_outcome_response(
        monkeypatch,
        {"code": 70001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == 70001
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
        "internal service failure: access denied classifier unavailable",
        "internal service failure: rate limit has been exceeded classifier unavailable",
        "permission config unavailable: access denied",
        "rate classifier failure: too many requests",
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


@pytest.mark.parametrize(
    "message",
    [
        "provider rejected token=S3CR3T-DO-NOT-LOG",
        "provider rejected api_key: S3CR3T-DO-NOT-LOG",
        "provider rejected password=S3CR3T-DO-NOT-LOG",
        "provider rejected Authorization: Bearer S3CR3T-DO-NOT-LOG",
        "provider rejected Bearer S3CR3T-DO-NOT-LOG",
        'provider rejected {"api-key":"S3CR3T-DO-NOT-LOG"}',
    ],
)
def test_provider_call_outcome_redacts_credential_styles(message):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    assert "S3CR3T-DO-NOT-LOG" not in outcome.error_message
    assert "[REDACTED]" in outcome.error_message
    assert outcome.provider_code == -2001


@pytest.mark.parametrize(
    ("message", "secrets"),
    [
        pytest.param(
            "provider rejected Cookie: session=DUMMY-COOKIE-SECRET; theme=dark",
            ("DUMMY-COOKIE-SECRET",),
            id="cookie-header",
        ),
        pytest.param(
            "provider rejected Set-Cookie: session=DUMMY-SET-COOKIE; Path=/; HttpOnly",
            ("DUMMY-SET-COOKIE",),
            id="set-cookie-header",
        ),
        pytest.param(
            "provider URL https://example.test/path?token=DUMMY-URL-SECRET#DUMMY-FRAGMENT-SECRET",
            ("DUMMY-URL-SECRET", "DUMMY-FRAGMENT-SECRET"),
            id="url-query-and-fragment",
        ),
        pytest.param(
            "provider rejected credential=DUMMY-CREDENTIAL-SECRET",
            ("DUMMY-CREDENTIAL-SECRET",),
            id="credential-field",
        ),
        pytest.param(
            'provider rejected {"client_secret":"DUMMY-CLIENT-SECRET"}',
            ("DUMMY-CLIENT-SECRET",),
            id="client-secret-field",
        ),
        pytest.param(
            'provider params={"api_key":DUMMY-UNQUOTED-SECRET}',
            ("DUMMY-UNQUOTED-SECRET",),
            id="unquoted-json-credential",
        ),
        pytest.param(
            "provider url=https%3A%2F%2Fexample.test%2F%3Ftoken%3DDUMMY-ENCODED-URL-SECRET",
            ("DUMMY-ENCODED-URL-SECRET",),
            id="percent-encoded-url",
        ),
    ],
)
def test_provider_call_outcome_redacts_extended_credential_surfaces(
    message,
    secrets,
):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    for secret in secrets:
        assert secret not in outcome.error_message
    assert "[REDACTED]" in outcome.error_message
    assert outcome.error_message.startswith("provider ")
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    for secret in secrets:
        assert secret not in repr(log_fields)
    assert log_fields["error_message"] == outcome.error_message
    if "https://" in message:
        assert "?[REDACTED]#[REDACTED]" in outcome.error_message


def test_tushare_rows_outcome_redacts_provider_error_before_return(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        {
            "code": -2001,
            "msg": "upstream rejected request token=S3CR3T-DO-NOT-LOG",
            "data": None,
        },
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code == -2001
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "upstream rejected request token=[REDACTED]"


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


def test_tushare_rows_outcome_redacts_transport_error_before_return(monkeypatch):
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("offline token=S3CR3T-DO-NOT-LOG")
        ),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert outcome.provider_code is None
    assert outcome.error_code == "provider_error"
    assert "offline" in outcome.error_message
    assert "S3CR3T-DO-NOT-LOG" not in outcome.error_message
    assert "token=[REDACTED]" in outcome.error_message
