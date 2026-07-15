import json
import math
import re
import urllib.error
import urllib.parse
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
        assert outcome.error_message == "provider diagnostic [REDACTED]"


@pytest.mark.parametrize(
    ("message", "sensitive_fragments", "prefix", "suffix"),
    [
        pytest.param(
            "provider diagnostic-prefix | headers={'X-API-Key': "
            "'DUMMY-XAPI-LEAD tail+/=?&; DUMMY-XAPI-TRAIL'}; status=401",
            ("DUMMY-XAPI-LEAD", "DUMMY-XAPI-TRAIL"),
            "provider diagnostic-prefix | headers=",
            "; status=401",
            id="dict-x-api-key-quoted-specials",
        ),
        pytest.param(
            "provider bytes={b'X-Auth-Token': "
            "b'DUMMY-XAUTH-LEAD +/%=?& DUMMY-XAUTH-TRAIL', "
            "b'status': b'401'}",
            ("DUMMY-XAUTH-LEAD", "DUMMY-XAUTH-TRAIL"),
            "provider bytes=",
            ", b'status': b'401'}",
            id="bytes-repr-x-auth-token",
        ),
        pytest.param(
            'provider headers={"x Api Key" : '
            '"DUMMY-CASE-LEAD with spaces +/= DUMMY-CASE-TRAIL"} tail=kept',
            ("DUMMY-CASE-LEAD", "DUMMY-CASE-TRAIL"),
            "provider headers=",
            " tail=kept",
            id="mixed-case-space-separated-key",
        ),
        pytest.param(
            "provider diagnostic-prefix | X-API-Key = "
            "DUMMY-RAW-LEAD with spaces +/%=? DUMMY-RAW-TRAIL ; status=401",
            ("DUMMY-RAW-LEAD", "DUMMY-RAW-TRAIL"),
            "provider diagnostic-prefix | X-API-Key = ",
            "; status=401",
            id="unquoted-value-with-spaces-and-suffix",
        ),
        pytest.param(
            "provider%20headers%3D%7B%27X-Auth-Token%27%3A%20%27"
            "DUMMY-ENCODED-LEAD%2B%2F%3D%20DUMMY-ENCODED-TRAIL"
            "%27%7D%3B%20status%3D401",
            ("DUMMY-ENCODED-LEAD", "DUMMY-ENCODED-TRAIL"),
            "provider headers=",
            "; status=401",
            id="percent-encoded-x-auth-token",
        ),
        pytest.param(
            "provider diagnostic-prefix | X-API-Key="
            "DUMMY-BRACKET-LEAD]mid)DUMMY-BRACKET-TRAIL ; status=401",
            ("DUMMY-BRACKET-LEAD", "DUMMY-BRACKET-TRAIL"),
            "provider diagnostic-prefix | X-API-Key=",
            "; status=401",
            id="unquoted-value-with-bracket-specials",
        ),
        pytest.param(
            "provider headers={'X-Auth-Token': "
            "'[REDACTED]-DUMMY-MARKER-TRAIL'}; status=401",
            ("DUMMY-MARKER-TRAIL",),
            "provider headers=",
            "; status=401",
            id="literal-marker-prefix-is-still-untrusted",
        ),
    ],
)
def test_provider_call_outcome_redacts_normalized_header_credentials_completely(
    message,
    sensitive_fragments,
    prefix,
    suffix,
):
    del prefix, suffix
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    for fragment in sensitive_fragments:
        assert fragment not in outcome.error_message
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    for fragment in sensitive_fragments:
        assert fragment not in repr(log_fields)
    assert log_fields["error_message"] == outcome.error_message


def test_provider_call_outcome_does_not_redact_noncredential_key_prefixes():
    message = (
        "provider diagnostic-prefix=kept; x-api-key-count=3; "
        "x-auth-tokenizer=enabled; api-keyboard=visible"
    )

    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    assert outcome.error_message == message
    assert "[REDACTED]" not in outcome.error_message


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        pytest.param(
            "provider bytes={b'X-Auth-Token': "
            "b'DUMMY +/%=?& TRAIL', b'status': b'401'}",
            "provider diagnostic [REDACTED]",
            id="bytes-wrapper",
        ),
        pytest.param(
            r"provider headers={'X-API-Key': "
            r"'DUMMY \' embedded +/%=?& TRAIL', 'status': 401}",
            "provider diagnostic [REDACTED]",
            id="escaped-quote",
        ),
    ],
)
def test_normalized_header_redaction_preserves_value_wrappers_and_is_idempotent(
    message,
    expected,
):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    assert outcome.error_message == expected
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    assert log_fields["error_message"] == expected


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
    assert outcome.error_message == "provider diagnostic [REDACTED]"


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
    assert outcome.error_message == "provider transport unavailable"


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
    assert "S3CR3T-DO-NOT-LOG" not in outcome.error_message
    assert outcome.error_message == "provider transport unavailable"


@pytest.mark.parametrize(
    ("message", "sensitive_fragments"),
    [
        pytest.param(
            "Authorization: Bearer DUMMY-COMMA-LEAD,DUMMY-COMMA-TRAIL status=401",
            ("DUMMY-COMMA-LEAD", "DUMMY-COMMA-TRAIL"),
            id="authorization-comma",
        ),
        pytest.param(
            "Authorization: Bearer DUMMY-SEMI-LEAD;DUMMY-SEMI-TRAIL status=401",
            ("DUMMY-SEMI-LEAD", "DUMMY-SEMI-TRAIL"),
            id="authorization-semicolon",
        ),
        pytest.param(
            "Authorization: Bearer DUMMY-BRACKET-LEAD]DUMMY-BRACKET-TRAIL status=401",
            ("DUMMY-BRACKET-LEAD", "DUMMY-BRACKET-TRAIL"),
            id="authorization-right-bracket",
        ),
        pytest.param(
            "Authorization: Bearer DUMMY-NL-AUTH-LEAD\nDUMMY-NL-AUTH-TRAIL status=401",
            ("DUMMY-NL-AUTH-LEAD", "DUMMY-NL-AUTH-TRAIL"),
            id="authorization-newline",
        ),
        pytest.param(
            "X-API-Key: DUMMY-NL-KEY-LEAD\nDUMMY-NL-KEY-TRAIL status=401",
            ("DUMMY-NL-KEY-LEAD", "DUMMY-NL-KEY-TRAIL"),
            id="x-api-key-newline",
        ),
        pytest.param(
            "token=DUMMY-AMP-LEAD%26trail=DUMMY-AMP-TRAIL&status=401",
            ("DUMMY-AMP-LEAD", "DUMMY-AMP-TRAIL"),
            id="percent-encoded-ampersand",
        ),
        pytest.param(
            "token=DUMMY-NL-TOKEN-LEAD%0ADUMMY-NL-TOKEN-TRAIL status=401",
            ("DUMMY-NL-TOKEN-LEAD", "DUMMY-NL-TOKEN-TRAIL"),
            id="percent-encoded-newline",
        ),
        pytest.param(
            "https://api.example.test/v1?token=DUMMY-URL-LEAD%0ADUMMY-URL-TRAIL status=401",
            ("DUMMY-URL-LEAD", "DUMMY-URL-TRAIL"),
            id="url-percent-encoded-newline",
        ),
        pytest.param(
            "Cookie: session=DUMMY-COOKIE-LEAD\nDUMMY-COOKIE-TRAIL status=401",
            ("DUMMY-COOKIE-LEAD", "DUMMY-COOKIE-TRAIL"),
            id="cookie-newline",
        ),
        pytest.param(
            "Authorization: Bearer [REDACTED]DUMMY-MARKER-TRAIL status=401",
            ("DUMMY-MARKER-TRAIL",),
            id="literal-marker-prefix",
        ),
        pytest.param(
            "headers=[('X-API-Key', 'DUMMY-TUPLE-SECRET')]; status=401",
            ("DUMMY-TUPLE-SECRET",),
            id="tuple-header-repr",
        ),
        pytest.param(
            "headers=[(b'X-Auth-Token', b'DUMMY-TUPLE-BYTES')]; status=401",
            ("DUMMY-TUPLE-BYTES",),
            id="tuple-bytes-header-repr",
        ),
        pytest.param(
            '{"Authorization":"Bearer DUMMY-QUOTED-AUTH-LEAD,DUMMY-QUOTED-AUTH-TRAIL","status":401}',
            ("DUMMY-QUOTED-AUTH-LEAD", "DUMMY-QUOTED-AUTH-TRAIL"),
            id="quoted-authorization-comma",
        ),
        pytest.param(
            r'payload="{\"X-API-Key\":\"DUMMY-ESCAPED-JSON-SECRET\",\"status\":401}"',
            ("DUMMY-ESCAPED-JSON-SECRET",),
            id="escaped-json-string",
        ),
        pytest.param(
            "x+api+key=DUMMY-FORM-PLUS-SECRET&status=401",
            ("DUMMY-FORM-PLUS-SECRET",),
            id="form-percent-plus-encoding",
        ),
    ],
)
def test_fail_closed_outcome_redaction_covers_adversarial_boundaries(
    message,
    sensitive_fragments,
):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )
    log_fields = tushare_common.provider_outcome_log_fields(outcome)

    for fragment in sensitive_fragments:
        assert fragment not in (outcome.error_message or "")
        assert fragment not in repr(log_fields)
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert "401" not in outcome.error_message
    assert log_fields["error_message"] == outcome.error_message


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer DUMMY-IDEMPOTENT,DUMMY-TRAIL status=401",
        "Authorization: Bearer DUMMY-IDEMPOTENT;DUMMY-TRAIL status=401",
        "Authorization: Bearer DUMMY-IDEMPOTENT]DUMMY-TRAIL status=401",
        "Authorization: Bearer DUMMY-IDEMPOTENT\nDUMMY-TRAIL status=401",
    ],
)
def test_fail_closed_redaction_is_idempotent_at_log_boundary(message):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    assert (
        tushare_common.provider_outcome_log_fields(outcome)["error_message"]
        == outcome.error_message
    )


@pytest.mark.parametrize("field", ["provider_code", "error_code"])
def test_untrusted_outcome_codes_are_safe_in_return_and_receipt(field):
    secret = "DUMMY-CODE-SECRET"
    kwargs = {
        "state": "failed",
        "rows": (),
        "provider_code": -2001,
        "error_code": "provider_error",
        "error_message": "safe diagnostic",
    }
    kwargs[field] = f"token={secret}"

    outcome = tushare_common.ProviderCallOutcome(**kwargs)
    receipt = {"outcome": outcome}

    assert secret not in repr(outcome)
    assert secret not in repr(receipt)


@pytest.mark.parametrize("failure_mode", ["provider", "transport"])
def test_strict_provider_return_is_safe_for_delimited_secret(
    monkeypatch,
    failure_mode,
):
    secret = "DUMMY-STRICT-TRAIL"
    message = f"Authorization: Bearer DUMMY-STRICT-LEAD,{secret} status=401"
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    if failure_mode == "provider":
        monkeypatch.setattr(
            tushare_common.urllib.request,
            "urlopen",
            lambda *_args, **_kwargs: _Response(
                {"code": -2001, "msg": message, "data": None}
            ),
        )
    else:
        def raise_transport(*_args, **_kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(
            tushare_common.urllib.request,
            "urlopen",
            raise_transport,
        )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert secret not in (outcome.error_message or "")
    assert secret not in repr(outcome)


def test_provider_string_code_is_safe_in_return_and_receipt(monkeypatch):
    secret = "DUMMY-PROVIDER-CODE-SECRET"
    _stub_outcome_response(
        monkeypatch,
        {"code": f"token={secret}", "msg": "request rejected", "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")
    receipt = {"outcome": outcome}

    assert outcome.state == "failed"
    assert secret not in repr(outcome)
    assert secret not in repr(receipt)


_EXACT_TOKEN = "DUMMY token+/=\"'\nTAIL"


def _lower_percent_escapes(value: str) -> str:
    return re.sub(r"%[0-9A-F]{2}", lambda match: match.group(0).lower(), value)


@pytest.mark.parametrize(
    "echoed_token",
    [
        _EXACT_TOKEN,
        urllib.parse.quote(_EXACT_TOKEN, safe=""),
        urllib.parse.quote(_EXACT_TOKEN),
        _lower_percent_escapes(urllib.parse.quote(_EXACT_TOKEN, safe="")),
        urllib.parse.quote(_EXACT_TOKEN, safe="").replace("%2B", "%2b"),
        urllib.parse.quote_plus(_EXACT_TOKEN, safe=""),
        json.dumps(_EXACT_TOKEN)[1:-1],
        repr(_EXACT_TOKEN),
        repr(_EXACT_TOKEN.encode("utf-8")),
    ],
    ids=(
        "raw",
        "url-encoded",
        "url-encoded-default-safe",
        "url-encoded-lowercase",
        "url-encoded-mixed-case",
        "form-encoded",
        "json-escaped",
        "repr",
        "bytes-repr",
    ),
)
def test_provider_boundary_replaces_exact_token_equivalent_forms(
    monkeypatch,
    echoed_token,
):
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": f"provider echoed {echoed_token}; status=401", "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", _EXACT_TOKEN)
    fields = tushare_common.provider_outcome_log_fields(outcome)

    assert "DUMMY" not in (outcome.error_message or "")
    assert "TAIL" not in (outcome.error_message or "")
    assert fields["error_message"] == outcome.error_message


def test_provider_boundary_replaces_percent_decoded_token(monkeypatch):
    encoded_token = "DUMMY%2FDECODED%20TOKEN"
    decoded_token = urllib.parse.unquote(encoded_token)
    _stub_outcome_response(
        monkeypatch,
        {
            "code": -2001,
            "msg": f"provider echoed {decoded_token}; status=401",
            "data": None,
        },
    )

    outcome = tushare_common.tushare_rows_outcome("daily", encoded_token)

    assert "DUMMY" not in (outcome.error_message or "")
    assert "DECODED" not in (outcome.error_message or "")


def test_transport_summary_does_not_retain_arbitrary_exception_text(monkeypatch):
    secret = "innocent-looking-private-diagnostic"
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: "https://example.test")
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", "stub-token")

    assert outcome.state == "failed"
    assert secret not in (outcome.error_message or "")
    assert outcome.error_message == "provider transport failed"


def test_redacted_summary_does_not_misreport_three_digit_credential_as_status():
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message="Authorization: Bearer 401",
    )

    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert "401" not in outcome.error_message


_RECURSIVE_GUARD_TOKEN = "SYNTH-UNICODE-ARROW-9z"
_FULL_UNICODE_ESCAPE_TOKEN = "".join(
    f"\\u{ord(character):04x}" for character in _RECURSIVE_GUARD_TOKEN
)
_MIXED_UNICODE_ESCAPE_TOKEN = "".join(
    character if index % 2 else f"\\u{ord(character):04x}"
    for index, character in enumerate(_RECURSIVE_GUARD_TOKEN)
)


@pytest.mark.parametrize(
    "encoded_token",
    [_FULL_UNICODE_ESCAPE_TOKEN, _MIXED_UNICODE_ESCAPE_TOKEN],
    ids=("all-ascii-unicode-escapes", "mixed-raw-and-unicode-escapes"),
)
def test_provider_boundary_recursively_guards_unicode_escaped_request_token(
    monkeypatch,
    encoded_token,
):
    _stub_outcome_response(
        monkeypatch,
        {
            "code": -2001,
            "msg": f"Authorization -> {encoded_token}",
            "data": None,
        },
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        _RECURSIVE_GUARD_TOKEN,
    )
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert log_fields["error_message"] == outcome.error_message
    assert "Authorization" not in repr(receipt)
    assert "\\u0053" not in repr(receipt)


@pytest.mark.parametrize(
    "message",
    [
        "Authorization -> SYNTH-UNKNOWN-CREDENTIAL",
        "X-API-Key -> SYNTH-UNKNOWN-CREDENTIAL",
        "password=status=418",
    ],
)
def test_unparseable_credential_indicator_replaces_entire_diagnostic(message):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=message,
    )

    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert "418" not in outcome.error_message


@pytest.mark.parametrize("provider_code", [7314928, "7314928"])
def test_request_token_cannot_be_smuggled_as_numeric_provider_code(
    monkeypatch,
    provider_code,
):
    token = "7314928"
    _stub_outcome_response(
        monkeypatch,
        {"code": provider_code, "msg": "request rejected", "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", token)
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert outcome.state == "failed"
    assert outcome.provider_code == "<untrusted-provider-code>"
    assert token not in repr(outcome)
    assert token not in repr(log_fields)
    assert token not in repr(receipt)


@pytest.mark.parametrize(
    ("token", "data"),
    [
        pytest.param(
            "7314928",
            {"fields": ["value"], "items": [["7314928"]]},
            id="string-value",
        ),
        pytest.param(
            "7314928",
            {"fields": ["value"], "items": [[7314928]]},
            id="numeric-value",
        ),
        pytest.param(
            "SYNTH_NESTED_TOKEN",
            {
                "fields": ["value"],
                "items": [[{"SYNTH_NESTED_TOKEN": "safe"}]],
            },
            id="nested-container-key",
        ),
        pytest.param(
            "SYNTH_FIELD_TOKEN",
            {"fields": ["SYNTH_FIELD_TOKEN"], "items": [["safe"]]},
            id="row-key",
        ),
        pytest.param(
            "7314928",
            {
                "fields": ["value"],
                "items": [[r"\u0037\u0033\u0031\u0034\u0039\u0032\u0038"]],
            },
            id="unicode-escaped-value",
        ),
    ],
)
def test_success_payload_echoing_request_token_fails_closed(
    monkeypatch,
    token,
    data,
):
    _stub_outcome_response(
        monkeypatch,
        {"code": 0, "msg": None, "data": data},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", token)
    receipt = {"outcome": outcome}

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "Tushare response validation failed"
    assert token not in repr(receipt)


def test_outcome_defense_rejects_sensitive_bytes_in_success_rows():
    token = b"SYNTH-BYTES-TOKEN"

    with pytest.raises(ValueError, match="sensitive"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": token},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=(token,),
        )


def _nested_value(depth: int, leaf: object = "safe") -> object:
    value = leaf
    for index in range(depth):
        value = {f"level_{index}": value}
    return value


class _ExplodingItemsDict(dict):
    def items(self):
        raise RuntimeError("SYNTH-MAPPING-ITERATION-SECRET")


class _ExplodingIterable:
    def __iter__(self):
        yield "safe-prefix"
        raise RuntimeError("SYNTH-ITERATOR-SECRET")


def test_sensitive_guard_fails_closed_at_depth_limit_plus_one():
    budget = tushare_common.SensitiveScanBudget(max_depth=3)

    with pytest.raises(ValueError, match="sensitive or unscannable") as exc_info:
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": _nested_value(4)},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("SYNTH-DEPTH-TOKEN",),
            scan_budget=budget,
        )

    assert "SYNTH-DEPTH-TOKEN" not in str(exc_info.value)


def test_sensitive_guard_fails_closed_at_node_limit_plus_one():
    budget = tushare_common.SensitiveScanBudget(
        max_depth=16,
        max_nodes=4,
    )

    with pytest.raises(ValueError, match="sensitive or unscannable") as exc_info:
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": ["safe-one", "safe-two"]},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("SYNTH-NODE-TOKEN",),
            scan_budget=budget,
        )

    assert "SYNTH-NODE-TOKEN" not in str(exc_info.value)


def test_sensitive_guard_fails_closed_on_container_cycle():
    cycle = []
    cycle.append(cycle)

    with pytest.raises(ValueError, match="sensitive or unscannable") as exc_info:
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": cycle},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("SYNTH-CYCLE-TOKEN",),
        )

    assert "SYNTH-CYCLE-TOKEN" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("value", "secret"),
    [
        pytest.param(
            _ExplodingItemsDict({"safe": "value"}),
            "SYNTH-MAPPING-ITERATION-SECRET",
            id="mapping-items",
        ),
        pytest.param(
            _ExplodingIterable(),
            "SYNTH-ITERATOR-SECRET",
            id="custom-iterator",
        ),
    ],
)
def test_sensitive_guard_fails_closed_on_traversal_exception(value, secret):
    with pytest.raises(ValueError, match="sensitive or unscannable") as exc_info:
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": value},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("SYNTH-TRAVERSAL-TOKEN",),
        )

    assert secret not in str(exc_info.value)


def test_sensitive_guard_fails_closed_beyond_decode_round_budget():
    token = "SYNTH/DEEP?VALUE=9"
    encoded_token = token
    for _ in range(6):
        encoded_token = urllib.parse.quote(encoded_token, safe="")
    budget = tushare_common.SensitiveScanBudget(max_decode_rounds=4)

    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=f"provider echoed {encoded_token}",
        sensitive_values=(token,),
        scan_budget=budget,
    )

    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert encoded_token not in outcome.error_message


def test_sensitive_guard_fails_closed_beyond_representation_view_budget():
    token = "SYNTH/VIEW?VALUE=7"
    encoded_token = urllib.parse.quote(token, safe="")
    budget = tushare_common.SensitiveScanBudget(max_views=1)

    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="provider_error",
        error_message=f"provider echoed {encoded_token}",
        sensitive_values=(token,),
        scan_budget=budget,
    )

    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert encoded_token not in outcome.error_message


def test_provider_boundary_allows_explicit_budget_for_large_safe_response(
    monkeypatch,
):
    token = "SYNTH-LARGE-RESPONSE-TOKEN"
    large_safe_value = {
        "nested": _nested_value(10),
        "many": [f"safe-{index}" for index in range(40)],
    }
    _stub_outcome_response(
        monkeypatch,
        {
            "code": 0,
            "msg": None,
            "data": {"fields": ["value"], "items": [[large_safe_value]]},
        },
    )

    constrained = tushare_common.tushare_rows_outcome(
        "daily",
        token,
        scan_budget=tushare_common.SensitiveScanBudget(
            max_depth=4,
            max_nodes=10,
        ),
    )
    allowed = tushare_common.tushare_rows_outcome(
        "daily",
        token,
        scan_budget=tushare_common.SensitiveScanBudget(
            max_depth=32,
            max_nodes=1_000,
        ),
    )

    assert constrained.state == "failed"
    assert constrained.rows == ()
    assert constrained.error_message == "Tushare response validation failed"
    assert allowed.state == "success"
    assert allowed.rows == ({"value": large_safe_value},)
    assert token not in repr({"constrained": constrained, "allowed": allowed})

    _stub_outcome_response(
        monkeypatch,
        {
            "code": 0,
            "msg": None,
            "data": {
                "fields": ["value"],
                "items": [[{"deep": _nested_value(10, token)}]],
            },
        },
    )
    echoed = tushare_common.tushare_rows_outcome(
        "daily",
        token,
        scan_budget=tushare_common.SensitiveScanBudget(
            max_depth=32,
            max_nodes=1_000,
        ),
    )

    assert echoed.state == "failed"
    assert echoed.rows == ()
    assert echoed.error_message == "Tushare response validation failed"
    assert token not in repr(echoed)
