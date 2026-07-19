import json
import math
import re
import ssl
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


def test_quicksync_transport_requires_verified_tls13(monkeypatch):
    observed: dict[str, object] = {}

    def fake_urlopen(request, timeout, *, context):
        observed.update(
            {
                "context": context,
                "timeout": timeout,
                "url": request.full_url,
            }
        )
        return _Response(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["value"], "items": [[1]]},
            }
        )

    monkeypatch.setattr(
        tushare_common,
        "get_api_url",
        lambda: tushare_common.QUICKSYNC_API_URL,
    )
    monkeypatch.setattr(tushare_common.urllib.request, "urlopen", fake_urlopen)

    outcome = tushare_common.tushare_rows_outcome("trade_cal", "stub-token")

    context = observed["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.minimum_version is ssl.TLSVersion.TLSv1_3
    assert context.maximum_version is ssl.TLSVersion.TLSv1_3
    assert observed["timeout"] == 30
    assert observed["url"] == tushare_common.QUICKSYNC_API_URL
    assert outcome.state == "success"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.quicksync.cn",
        "https://api.quicksync.cn:444",
        "https://api.quicksync.cn/provider",
    ],
)
def test_quicksync_transport_rejects_unverified_routes_before_token_send(
    monkeypatch,
    url,
):
    monkeypatch.setattr(tushare_common, "get_api_url", lambda: url)
    monkeypatch.setattr(
        tushare_common.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail(
            "unverified QuickSync route must fail before network access"
        ),
    )

    outcome = tushare_common.tushare_rows_outcome("trade_cal", "stub-token")

    assert outcome.state == "failed"
    assert outcome.error_code == "provider_error"


def test_non_quicksync_transport_keeps_default_verified_urlopen(monkeypatch):
    observed: dict[str, object] = {}

    def fake_urlopen(request, timeout, **kwargs):
        observed.update(
            {
                "kwargs": kwargs,
                "timeout": timeout,
                "url": request.full_url,
            }
        )
        return _Response(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": ["value"], "items": [[1]]},
            }
        )

    monkeypatch.setattr(
        tushare_common,
        "get_api_url",
        lambda: "https://api.tushare.pro",
    )
    monkeypatch.setattr(tushare_common.urllib.request, "urlopen", fake_urlopen)

    outcome = tushare_common.tushare_rows_outcome("trade_cal", "stub-token")

    assert observed == {
        "kwargs": {},
        "timeout": 30,
        "url": "https://api.tushare.pro",
    }
    assert outcome.state == "success"


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


@pytest.mark.parametrize(
    ("fields", "expected_fields"),
    [
        pytest.param(None, None, id="none-omits-wire-field"),
        pytest.param("", None, id="empty-omits-wire-field"),
        pytest.param("ts_code,close", "ts_code,close", id="projection-is-exact"),
    ],
)
def test_tushare_rows_outcome_omits_empty_fields_from_wire_request(
    monkeypatch,
    fields: str | None,
    expected_fields: str | None,
) -> None:
    requests = _stub_outcome_response(
        monkeypatch,
        {"code": 0, "msg": None, "data": {"fields": ["ts_code"], "items": []}},
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "stub-token",
        params={"trade_date": "20260717"},
        fields=fields,
    )

    assert outcome.state == "empty"
    payload = requests[0]["payload"]
    if expected_fields is None:
        assert "fields" not in payload
    else:
        assert payload["fields"] == expected_fields


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
    assert outcome.error_message == "provider diagnostic [REDACTED]"
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
    assert constrained.error_message == "provider diagnostic [REDACTED]"
    assert allowed.state == "success"
    assert allowed.mutable_rows() == [{"value": large_safe_value}]
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
    assert echoed.error_message == "provider diagnostic [REDACTED]"
    assert token not in repr(echoed)


_CLASSIFIABLE_DIAGNOSTIC = "too many requests"
_PERCENT_CLASSIFIER_TOKEN = urllib.parse.quote(
    _CLASSIFIABLE_DIAGNOSTIC,
    safe="",
)
_UNICODE_CLASSIFIER_TOKEN = "".join(
    f"\\u{ord(character):04x}" for character in _CLASSIFIABLE_DIAGNOSTIC
)
_REPR_CLASSIFIER_TOKEN = repr(_CLASSIFIABLE_DIAGNOSTIC)
_MULTI_PERCENT_CLASSIFIER_TOKEN = _CLASSIFIABLE_DIAGNOSTIC
for _ in range(4):
    _MULTI_PERCENT_CLASSIFIER_TOKEN = urllib.parse.quote(
        _MULTI_PERCENT_CLASSIFIER_TOKEN,
        safe="",
    )
_BUDGET_CLASSIFIER_TOKEN = "SYNTH/BUDGET?VALUE=5"
_BUDGET_EXHAUSTING_MESSAGE = _BUDGET_CLASSIFIER_TOKEN
for _ in range(5):
    _BUDGET_EXHAUSTING_MESSAGE = urllib.parse.quote(
        _BUDGET_EXHAUSTING_MESSAGE,
        safe="",
    )


@pytest.mark.parametrize(
    ("token", "message", "scan_budget"),
    [
        pytest.param(
            "7314928",
            "每分钟最多访问7314928次",
            None,
            id="long-numeric",
        ),
        pytest.param(
            "7",
            "每分钟最多访问7次",
            None,
            id="short-numeric",
        ),
        pytest.param(
            _PERCENT_CLASSIFIER_TOKEN,
            _CLASSIFIABLE_DIAGNOSTIC,
            None,
            id="percent-equivalent",
        ),
        pytest.param(
            _UNICODE_CLASSIFIER_TOKEN,
            _CLASSIFIABLE_DIAGNOSTIC,
            None,
            id="unicode-equivalent",
        ),
        pytest.param(
            _REPR_CLASSIFIER_TOKEN,
            _CLASSIFIABLE_DIAGNOSTIC,
            None,
            id="repr-equivalent",
        ),
        pytest.param(
            _MULTI_PERCENT_CLASSIFIER_TOKEN,
            _CLASSIFIABLE_DIAGNOSTIC,
            None,
            id="multi-percent-equivalent",
        ),
        pytest.param(
            "SYNTH-NESTED-DIAGNOSTIC",
            {"detail": [{"echo": "SYNTH-NESTED-DIAGNOSTIC"}]},
            None,
            id="nested-diagnostic",
        ),
        pytest.param(
            "SYNTH-UNRELATED-TOKEN",
            "Authorization -> SYNTH-OPAQUE-CREDENTIAL",
            None,
            id="credential-indicator",
        ),
        pytest.param(
            _BUDGET_CLASSIFIER_TOKEN,
            _BUDGET_EXHAUSTING_MESSAGE,
            tushare_common.SensitiveScanBudget(max_decode_rounds=2),
            id="decode-budget-exhausted",
        ),
    ],
)
def test_untrusted_provider_diagnostic_never_reaches_classifier(
    monkeypatch,
    token,
    message,
    scan_budget,
):
    classifier_inputs = []

    def record_classifier(provider_code, diagnostic):
        classifier_inputs.append((provider_code, diagnostic))
        return "rate_limited"

    monkeypatch.setattr(
        tushare_common,
        "_provider_error_code",
        record_classifier,
    )
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        token,
        scan_budget=scan_budget,
    )
    log_fields = tushare_common.provider_outcome_log_fields(
        outcome,
        sensitive_values=(token,),
        scan_budget=scan_budget,
    )
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert classifier_inputs == []
    assert outcome.state == "failed"
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert log_fields["error_code"] == "provider_error"
    assert log_fields["error_message"] == outcome.error_message
    assert token not in repr(receipt)
    assert str(message) not in repr(receipt)


def test_sensitive_provider_code_never_enables_specialized_classification(
    monkeypatch,
):
    token = "-2001"
    classifier_inputs = []

    def record_classifier(provider_code, diagnostic):
        classifier_inputs.append((provider_code, diagnostic))
        return "rate_limited"

    monkeypatch.setattr(
        tushare_common,
        "_provider_error_code",
        record_classifier,
    )
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": _CLASSIFIABLE_DIAGNOSTIC, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", token)
    log_fields = tushare_common.provider_outcome_log_fields(
        outcome,
        sensitive_values=(token,),
    )

    assert classifier_inputs == []
    assert outcome.provider_code == "<untrusted-provider-code>"
    assert outcome.error_code == "provider_error"
    assert token not in repr({"outcome": outcome, "log_fields": log_fields})


@pytest.mark.parametrize(
    ("token", "message", "derived_error_code"),
    [
        ("7314928", "每分钟最多访问7314928次", "rate_limited"),
        (
            "permission denied",
            "permission denied",
            "permission_denied",
        ),
    ],
)
def test_outcome_defense_downgrades_code_derived_from_untrusted_diagnostic(
    token,
    message,
    derived_error_code,
):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code=derived_error_code,
        error_message=message,
        sensitive_values=(token,),
    )

    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert token not in repr(outcome)


def test_log_defense_downgrades_code_derived_from_untrusted_diagnostic():
    token = "7314928"
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="rate_limited",
        error_message=f"每分钟最多访问{token}次",
    )

    log_fields = tushare_common.provider_outcome_log_fields(
        outcome,
        sensitive_values=(token,),
    )

    assert log_fields["error_code"] == "provider_error"
    assert log_fields["error_message"] == "provider diagnostic [REDACTED]"
    assert token not in repr(log_fields)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(
            {"detail": ["too many requests"]},
            id="mapping",
        ),
        pytest.param(["too many requests"], id="list"),
        pytest.param(429, id="integer"),
        pytest.param(True, id="boolean"),
        pytest.param(429.5, id="float"),
        pytest.param(None, id="null"),
    ],
)
def test_non_string_provider_diagnostic_never_reaches_classifier(
    monkeypatch,
    message,
):
    classifier_inputs = []

    def record_classifier(provider_code, diagnostic):
        classifier_inputs.append((provider_code, diagnostic))
        return "rate_limited"

    monkeypatch.setattr(
        tushare_common,
        "_provider_error_code",
        record_classifier,
    )
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-NONSTRING-TOKEN",
    )
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert classifier_inputs == []
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert log_fields["error_code"] == "provider_error"
    assert log_fields["error_message"] == outcome.error_message
    assert str(message) not in repr(receipt)


class _DiagnosticStringSubclass(str):
    pass


class _DiagnosticConversionTrap:
    def __init__(self) -> None:
        self.conversions = []

    def __str__(self):
        self.conversions.append("str")
        return "too many requests"

    def __repr__(self):
        self.conversions.append("repr")
        return "too many requests"


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(b"too many requests", id="bytes"),
        pytest.param(bytearray(b"too many requests"), id="bytearray"),
        pytest.param(
            _DiagnosticStringSubclass("too many requests"),
            id="string-subclass",
        ),
    ],
)
def test_outcome_accepts_only_exact_string_diagnostic_type(message):
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="rate_limited",
        error_message=message,
    )

    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"


def test_outcome_non_string_diagnostic_does_not_call_str_or_repr():
    message = _DiagnosticConversionTrap()

    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="rate_limited",
        error_message=message,
    )

    assert message.conversions == []
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"


def test_log_non_string_diagnostic_does_not_call_str_or_repr():
    message = _DiagnosticConversionTrap()
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=-2001,
        error_code="rate_limited",
        error_message="too many requests",
    )
    object.__setattr__(outcome, "error_message", message)

    log_fields = tushare_common.provider_outcome_log_fields(outcome)

    assert message.conversions == []
    assert log_fields["error_code"] == "provider_error"
    assert log_fields["error_message"] == "provider diagnostic [REDACTED]"


_NON_BMP_TOKEN = "🔑S3CRET"
_LOWER_SURROGATE_PAIR = r"\ud83d\udd11S3CRET"
_UPPER_HEX_SURROGATE_PAIR = r"\uD83D\uDD11S3CRET"
_UPPER_U_NON_BMP_ESCAPE = r"\U0001F511S3CRET"
_DOUBLE_ESCAPED_SURROGATE_PAIR = _LOWER_SURROGATE_PAIR.replace("\\", "\\\\")
_MULTI_ENCODED_SURROGATE_PAIR = _LOWER_SURROGATE_PAIR
for _ in range(3):
    _MULTI_ENCODED_SURROGATE_PAIR = urllib.parse.quote(
        _MULTI_ENCODED_SURROGATE_PAIR,
        safe="",
    )


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_LOWER_SURROGATE_PAIR, id="lower-u-pair"),
        pytest.param(_UPPER_HEX_SURROGATE_PAIR, id="upper-hex-pair"),
        pytest.param(_UPPER_U_NON_BMP_ESCAPE, id="upper-U-scalar"),
        pytest.param(
            _DOUBLE_ESCAPED_SURROGATE_PAIR,
            id="double-escaped-pair",
        ),
        pytest.param(
            _MULTI_ENCODED_SURROGATE_PAIR,
            id="multi-percent-encoded-pair",
        ),
    ],
)
def test_non_bmp_token_equivalent_diagnostic_fails_closed(
    monkeypatch,
    message,
):
    classifier_inputs = []

    def record_classifier(provider_code, diagnostic):
        classifier_inputs.append((provider_code, diagnostic))
        return "rate_limited"

    monkeypatch.setattr(
        tushare_common,
        "_provider_error_code",
        record_classifier,
    )
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome("daily", _NON_BMP_TOKEN)
    log_fields = tushare_common.provider_outcome_log_fields(
        outcome,
        sensitive_values=(_NON_BMP_TOKEN,),
    )
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert classifier_inputs == []
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert _NON_BMP_TOKEN not in repr(receipt)
    assert "S3CRET" not in repr(receipt)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(r"\ud83dSYNTH-LONE-HIGH", id="lone-high"),
        pytest.param(r"\udd11SYNTH-LONE-LOW", id="lone-low"),
        pytest.param(r"\ud83d\u0041SYNTH-BAD-PAIR", id="high-non-low"),
        pytest.param(r"\udd11\ud83dSYNTH-REVERSED", id="reversed-pair"),
        pytest.param(r"\ud83d\ud83dSYNTH-TWO-HIGH", id="two-high"),
        pytest.param(r"\U0000D83DSYNTH-UPPER-U-HIGH", id="upper-U-high"),
    ],
)
def test_invalid_surrogate_diagnostic_fails_closed_without_classification(
    monkeypatch,
    message,
):
    classifier_inputs = []

    def record_classifier(provider_code, diagnostic):
        classifier_inputs.append((provider_code, diagnostic))
        return "permission_denied"

    monkeypatch.setattr(
        tushare_common,
        "_provider_error_code",
        record_classifier,
    )
    _stub_outcome_response(
        monkeypatch,
        {"code": -2001, "msg": message, "data": None},
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-UNRELATED-TOKEN",
    )
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert classifier_inputs == []
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert "SYNTH" not in repr(receipt)
    assert "d83d" not in repr(receipt).casefold()
    assert "dd11" not in repr(receipt).casefold()


def _provider_success_payload(
    data,
    **extra,
):
    return {"code": 0, "msg": None, "data": data, **extra}


def _provider_success_payload_with_metadata_value(value):
    return _provider_success_payload(
        {"fields": ["value"], "items": [["safe"]]},
        metadata={"note": value},
    )


_NEUTRAL_SCHEME_REFERENCE = "SYNTH-CTX-AUTH-9xQ7"
_NEUTRAL_CONTEXTUAL_AUTH_TEXT_VALUES = (
    pytest.param(
        f"upstream debug Bearer {_NEUTRAL_SCHEME_REFERENCE}",
        _NEUTRAL_SCHEME_REFERENCE,
        id="bearer-prefix",
    ),
    pytest.param(
        f"Bearer {_NEUTRAL_SCHEME_REFERENCE} status=401",
        _NEUTRAL_SCHEME_REFERENCE,
        id="bearer-suffix",
    ),
    pytest.param(
        f"upstream debug Basic {_NEUTRAL_SCHEME_REFERENCE}",
        _NEUTRAL_SCHEME_REFERENCE,
        id="basic-prefix",
    ),
    pytest.param(
        f"Basic {_NEUTRAL_SCHEME_REFERENCE} status=401",
        _NEUTRAL_SCHEME_REFERENCE,
        id="basic-suffix",
    ),
    pytest.param(
        f"upstream%20Bearer%20{_NEUTRAL_SCHEME_REFERENCE}",
        _NEUTRAL_SCHEME_REFERENCE,
        id="percent-encoded",
    ),
    pytest.param(
        repr(f"upstream Bearer {_NEUTRAL_SCHEME_REFERENCE}"),
        _NEUTRAL_SCHEME_REFERENCE,
        id="repr-wrapped",
    ),
    pytest.param(
        f"u'Bearer {_NEUTRAL_SCHEME_REFERENCE}'",
        _NEUTRAL_SCHEME_REFERENCE,
        id="python2-repr",
    ),
    pytest.param(
        f"('Bearer {_NEUTRAL_SCHEME_REFERENCE}',)",
        _NEUTRAL_SCHEME_REFERENCE,
        id="tuple-repr",
    ),
    pytest.param(
        f"upstream Bear\u200ber {_NEUTRAL_SCHEME_REFERENCE}",
        _NEUTRAL_SCHEME_REFERENCE,
        id="format-control",
    ),
    pytest.param(
        "prefix Bearer abcdefghijklmnop",
        "abcdefghijklmnop",
        id="lowercase-opaque",
    ),
    pytest.param(
        "prefix Basic dXNlcjpwYXNz",
        "dXNlcjpwYXNz",
        id="mixed-case-base64",
    ),
)

_TWO_WORD_AUTH_PROSE_VALUES = (
    pytest.param("Bearer bonds", id="lower-bearer-bonds"),
    pytest.param("Bearer Securities", id="title-bearer-securities"),
    pytest.param("Basic materials", id="lower-basic-materials"),
    pytest.param("Basic Materials", id="title-basic-materials"),
)

_NEUTRAL_BUSINESS_TEXT_VALUES = (
    pytest.param("Bearer abcdefgh", id="bearer-eight-lowercase"),
    pytest.param("Basic abcdefgh", id="basic-eight-lowercase"),
    pytest.param("Bearer abcdefghijklmno", id="bearer-fifteen-lowercase"),
    pytest.param("Basic abcdefghijklmno", id="basic-fifteen-lowercase"),
    pytest.param("Bearer abcdefghijklmnop", id="bearer-sixteen-lowercase"),
    pytest.param("Basic telecommunications", id="basic-long-business-word"),
    pytest.param(
        "Basic telecommunications services expanded",
        id="basic-long-business-sentence",
    ),
    pytest.param(
        "Bearer responsibilities transferred",
        id="bearer-long-business-sentence",
    ),
    pytest.param("Bearer counterparty", id="bearer-business-control"),
    pytest.param(
        "token=SYNTH-NEUTRAL-REFERENCE",
        id="neutral-token-assignment-text",
    ),
    pytest.param(
        "Authorization: Bearer SYNTH-NEUTRAL-REFERENCE",
        id="neutral-authorization-reference-text",
    ),
)

_STRICT_METADATA_SOURCE_VALUES = (
    pytest.param(
        "metadata",
        "Bearer abcdefgh",
        "abcdefgh",
        id="raw-bearer",
    ),
    pytest.param(
        "provenance",
        urllib.parse.quote("Basic abcdefgh"),
        "abcdefgh",
        id="url-encoded-basic",
    ),
    pytest.param(
        "debug",
        repr("Bearer abcdefghijklmno"),
        "abcdefghijklmno",
        id="repr-bearer",
    ),
    pytest.param(
        "note",
        "Bear\u200ber abcdefgh",
        "abcdefgh",
        id="format-control-bearer",
    ),
)

_KNOWN_SHORT_SECRET = "abcdefgh"
_KNOWN_SECRET_FORMAT_CONTROL_VALUES = (
    pytest.param(
        "Bearer abcd\u200befgh",
        id="raw-single-format-control",
    ),
    pytest.param(
        "Bearer a\u200bb\u2060c\u200dd\ufeffefgh",
        id="raw-multiple-format-controls",
    ),
    pytest.param(
        urllib.parse.quote("Bearer abcd\u200befgh"),
        id="percent-encoded-format-control",
    ),
    pytest.param(
        repr("Bearer abcd\u200befgh"),
        id="repr-wrapped-format-control",
    ),
    pytest.param(
        urllib.parse.quote(repr("Bearer abcd\u200befgh")),
        id="percent-encoded-repr-format-control",
    ),
)


@pytest.mark.parametrize(
    ("value", "secret_fragment"),
    _NEUTRAL_CONTEXTUAL_AUTH_TEXT_VALUES,
)
def test_success_payload_accepts_neutral_contextual_auth_scheme_text(
    monkeypatch,
    value,
    secret_fragment,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {
                "fields": ["value"],
                "items": [[{"note": {"items": [value]}}]],
            }
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )
    assert outcome.state == "success"
    assert outcome.mutable_rows() == [{"value": {"note": {"items": [value]}}}]
    assert secret_fragment in outcome.rows[0]["value"]["note"]["items"][0]


@pytest.mark.parametrize(
    ("value", "secret_fragment"),
    _NEUTRAL_CONTEXTUAL_AUTH_TEXT_VALUES,
)
def test_direct_outcome_accepts_neutral_contextual_auth_scheme_text(
    value,
    secret_fragment,
):
    outcome = tushare_common.ProviderCallOutcome(
        state="success",
        rows=({"note": {"items": [value]}},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    assert outcome.mutable_rows() == [{"note": {"items": [value]}}]
    assert secret_fragment in outcome.rows[0]["note"]["items"][0]


@pytest.mark.parametrize(
    ("value", "secret_fragment"),
    _NEUTRAL_CONTEXTUAL_AUTH_TEXT_VALUES,
)
def test_auth_scheme_text_in_provider_metadata_fails_closed(
    monkeypatch,
    value,
    secret_fragment,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload_with_metadata_value(value),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )
    receipt = {
        "outcome": outcome,
        "log_fields": tushare_common.provider_outcome_log_fields(outcome),
    }

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert secret_fragment not in repr(receipt)


@pytest.mark.parametrize("value", _NEUTRAL_BUSINESS_TEXT_VALUES)
def test_neutral_row_text_is_strictly_redacted_when_sourced_from_metadata(
    monkeypatch,
    value,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload_with_metadata_value(value),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"


def test_noncredential_provider_metadata_preserves_success_rows(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["value"], "items": [["safe"]]},
            metadata={"note": "ordinary provider provenance"},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "success"
    assert outcome.mutable_rows() == [{"value": "safe"}]


@pytest.mark.parametrize(
    ("extra_key", "value", "secret_fragment"),
    _STRICT_METADATA_SOURCE_VALUES,
)
def test_extra_data_envelope_metadata_fails_closed(
    monkeypatch,
    extra_key,
    value,
    secret_fragment,
):
    data = {
        "fields": ["value"],
        "items": [["safe"]],
        extra_key: {"note": value},
    }
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(data),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )
    receipt = {
        "outcome": outcome,
        "log_fields": tushare_common.provider_outcome_log_fields(outcome),
    }

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert secret_fragment not in repr(receipt)


@pytest.mark.parametrize(
    ("extra_key", "value", "secret_fragment"),
    _STRICT_METADATA_SOURCE_VALUES,
)
def test_top_level_metadata_uses_same_strict_source_contract(
    monkeypatch,
    extra_key,
    value,
    secret_fragment,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["value"], "items": [["safe"]]},
            **{extra_key: {"note": value}},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )
    receipt = {
        "outcome": outcome,
        "log_fields": tushare_common.provider_outcome_log_fields(outcome),
    }

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert secret_fragment not in repr(receipt)


def test_benign_extra_data_envelope_metadata_preserves_success_rows(monkeypatch):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {
                "fields": ["value"],
                "items": [["safe"]],
                "provenance": {"note": "ordinary provider provenance"},
            },
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "success"
    assert outcome.mutable_rows() == [{"value": "safe"}]


def test_nested_list_in_extra_data_envelope_metadata_fails_closed(monkeypatch):
    secret_fragment = "abcdefghijklmno"
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {
                "fields": ["value"],
                "items": [["safe"]],
                "provider_context": [
                    "ordinary",
                    {"notes": [f"Bearer {secret_fragment}"]},
                ],
            },
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert secret_fragment not in repr(outcome)


@pytest.mark.parametrize("value", _NEUTRAL_BUSINESS_TEXT_VALUES)
def test_direct_outcome_accepts_neutral_business_text_without_source_contract(
    value,
):
    source = {"description": value}
    outcome = tushare_common.ProviderCallOutcome(
        state="success",
        rows=(source,),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    source["description"] = "mutated"
    mutable_rows = outcome.mutable_rows()
    mutable_rows[0]["description"] = "consumer mutation"

    assert outcome.rows == ({"description": value},)
    assert outcome.mutable_rows() == [{"description": value}]


@pytest.mark.parametrize("value", _NEUTRAL_BUSINESS_TEXT_VALUES)
def test_success_payload_accepts_neutral_business_text_without_source_contract(
    monkeypatch,
    value,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["description"], "items": [[value]]},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "success"
    assert outcome.mutable_rows() == [{"description": value}]


@pytest.mark.parametrize("token", ["abcdefgh", "abcdefghijklmno"])
def test_direct_outcome_rejects_caller_known_short_auth_value(token):
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"description": f"Bearer {token}"},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=(token,),
        )


@pytest.mark.parametrize("token", ["abcdefgh", "abcdefghijklmno"])
def test_success_payload_rejects_caller_known_short_auth_value(
    monkeypatch,
    token,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["description"], "items": [[f"Bearer {token}"]]},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", token)
    receipt = {
        "outcome": outcome,
        "log_fields": tushare_common.provider_outcome_log_fields(outcome),
    }

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert token not in repr(receipt)


@pytest.mark.parametrize("value", _KNOWN_SECRET_FORMAT_CONTROL_VALUES)
def test_direct_outcome_rejects_format_control_variant_of_known_value(value):
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"description": value},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=(_KNOWN_SHORT_SECRET,),
        )


@pytest.mark.parametrize("value", _KNOWN_SECRET_FORMAT_CONTROL_VALUES)
def test_success_payload_rejects_format_control_variant_of_known_value(
    monkeypatch,
    value,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["description"], "items": [[value]]},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        _KNOWN_SHORT_SECRET,
    )
    receipt = {
        "outcome": outcome,
        "log_fields": tushare_common.provider_outcome_log_fields(outcome),
    }

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert value not in repr(receipt)


def test_known_value_with_format_control_matches_plain_candidate():
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"description": f"Bearer {_KNOWN_SHORT_SECRET}"},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("abcd\u200befgh",),
        )


def test_format_control_only_known_value_fails_closed():
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"description": "ordinary business text"},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("\u200b\u2060",),
        )


def test_format_control_only_known_value_cannot_mark_outcome_empty():
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=("\u200b\u2060",),
        )


def test_failed_outcome_can_redact_unscannable_known_value():
    outcome = tushare_common.ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=0,
        error_code="provider_error",
        error_message="ordinary provider failure",
        sensitive_values=("\u200b\u2060",),
    )

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.provider_code == "<untrusted-provider-code>"
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"


@pytest.mark.parametrize(
    ("token", "value"),
    [
        pytest.param(
            "abcd\u200befgh",
            f"Bearer {_KNOWN_SHORT_SECRET}",
            id="known-value-contains-format-control",
        ),
        pytest.param(
            "\u200b\u2060",
            "ordinary business text",
            id="known-value-normalizes-empty",
        ),
    ],
)
def test_success_payload_fails_closed_for_format_control_in_known_value(
    monkeypatch,
    token,
    value,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["description"], "items": [[value]]},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome("daily", token)

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_message == "provider diagnostic [REDACTED]"


@pytest.mark.parametrize(
    ("value", "scan_budget"),
    [
        pytest.param(
            "Bearer abcd\u200befgh",
            tushare_common.SensitiveScanBudget(max_views=1),
            id="view-budget",
        ),
        pytest.param(
            urllib.parse.quote("Bearer abcd\u200befgh"),
            tushare_common.SensitiveScanBudget(max_decode_rounds=1),
            id="decode-round-budget",
        ),
    ],
)
def test_known_value_format_control_normalization_budget_fails_closed(
    value,
    scan_budget,
):
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"description": value},),
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=(_KNOWN_SHORT_SECRET,),
            scan_budget=scan_budget,
        )


@pytest.mark.parametrize("value", _KNOWN_SECRET_FORMAT_CONTROL_VALUES)
def test_format_control_text_without_known_value_remains_neutral_business_data(
    monkeypatch,
    value,
):
    direct = tushare_common.ProviderCallOutcome(
        state="success",
        rows=({"description": value},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": ["description"], "items": [[value]]},
        ),
    )

    public = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-UNRELATED-TOKEN",
    )

    assert direct.mutable_rows() == [{"description": value}]
    assert public.state == "success"
    assert public.mutable_rows() == [{"description": value}]


@pytest.mark.parametrize("value", _TWO_WORD_AUTH_PROSE_VALUES)
def test_direct_outcome_accepts_two_word_auth_prose(value):
    outcome = tushare_common.ProviderCallOutcome(
        state="success",
        rows=({"description": value},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    assert outcome.state == "success"
    assert outcome.mutable_rows() == [{"description": value}]


@pytest.mark.parametrize(
    ("payload", "secret_fragment"),
    [
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["Authorization"],
                    "items": [["Bearer SYNTH-FOREIGN-AUTH-SECRET"]],
                }
            ),
            "SYNTH-FOREIGN-AUTH-SECRET",
            id="foreign-authorization-row",
        ),
        pytest.param(
            _provider_success_payload(
                {"fields": ["Authorization"], "items": []}
            ),
            "Authorization",
            id="credential-field-with-empty-items",
        ),
        pytest.param(
            _provider_success_payload(
                {"fields": ["token"], "items": [["SYNTH-FOREIGN-TOKEN"]]}
            ),
            "SYNTH-FOREIGN-TOKEN",
            id="token-field",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["access_token"],
                    "items": [["SYNTH-FOREIGN-ACCESS-TOKEN"]],
                }
            ),
            "SYNTH-FOREIGN-ACCESS-TOKEN",
            id="access-token-field",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["password"],
                    "items": [["SYNTH-FOREIGN-PASSWORD"]],
                }
            ),
            "SYNTH-FOREIGN-PASSWORD",
            id="password-field",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["clientSecret"],
                    "items": [["SYNTH-FOREIGN-CLIENT-SECRET"]],
                }
            ),
            "SYNTH-FOREIGN-CLIENT-SECRET",
            id="client-secret-field",
        ),
        pytest.param(
            _provider_success_payload(
                {"fields": ["Cookie"], "items": [["sid=SYNTH-FOREIGN-COOKIE"]]}
            ),
            "SYNTH-FOREIGN-COOKIE",
            id="cookie-field",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [
                        [
                            {
                                "proxy-authorization": (
                                    "Bearer SYNTH-FOREIGN-PROXY-AUTH"
                                )
                            }
                        ]
                    ],
                }
            ),
            "SYNTH-FOREIGN-PROXY-AUTH",
            id="nested-proxy-authorization",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[{"X-API-Key": "SYNTH-FOREIGN-API-KEY"}]],
                }
            ),
            "SYNTH-FOREIGN-API-KEY",
            id="nested-x-api-key",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[[{"Set-Cookie": "sid=SYNTH-FOREIGN-SET-COOKIE"}]]],
                }
            ),
            "SYNTH-FOREIGN-SET-COOKIE",
            id="nested-list-set-cookie",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[{"Author%69zation": "SYNTH-FOREIGN-PERCENT-KEY"}]],
                }
            ),
            "SYNTH-FOREIGN-PERCENT-KEY",
            id="percent-encoded-key",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[{"Author%2569zation": "SYNTH-FOREIGN-DEEP-KEY"}]],
                }
            ),
            "SYNTH-FOREIGN-DEEP-KEY",
            id="multi-percent-encoded-key",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[{r"\u0041uthorization": "SYNTH-FOREIGN-UNICODE-KEY"}]],
                }
            ),
            "SYNTH-FOREIGN-UNICODE-KEY",
            id="unicode-escaped-key",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [[{"'Authorization'": "SYNTH-FOREIGN-REPR-KEY"}]],
                }
            ),
            "SYNTH-FOREIGN-REPR-KEY",
            id="repr-wrapped-key",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "Authorization: Bearer SYNTH-FOREIGN-AUTH-VALUE"
            ),
            "SYNTH-FOREIGN-AUTH-VALUE",
            id="metadata-authorization-header-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "token=SYNTH-FOREIGN-ASSIGNMENT"
            ),
            "SYNTH-FOREIGN-ASSIGNMENT",
            id="metadata-token-assignment-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "password -> SYNTH-FOREIGN-ARROW"
            ),
            "SYNTH-FOREIGN-ARROW",
            id="metadata-password-arrow-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "Cookie: sid=SYNTH-FOREIGN-COOKIE-VALUE"
            ),
            "SYNTH-FOREIGN-COOKIE-VALUE",
            id="metadata-cookie-header-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "Bearer SYNTH-FOREIGN-BEARER"
            ),
            "SYNTH-FOREIGN-BEARER",
            id="metadata-standalone-bearer-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "Basic U1lOVEg6Rk9SRUlHTg=="
            ),
            "U1lOVEg6Rk9SRUlHTg==",
            id="metadata-standalone-basic-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                "Bearer%20SYNTH-FOREIGN-PERCENT-VALUE"
            ),
            "SYNTH-FOREIGN-PERCENT-VALUE",
            id="metadata-percent-encoded-bearer-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                r"Bearer\u0020SYNTH-FOREIGN-UNICODE-VALUE"
            ),
            "SYNTH-FOREIGN-UNICODE-VALUE",
            id="metadata-unicode-escaped-bearer-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                urllib.parse.quote(
                    urllib.parse.quote(
                        '{"Authorization":"Bearer '
                        'SYNTH-FOREIGN-ENCODED-JSON"}',
                        safe="",
                    ),
                    safe="",
                )
            ),
            "SYNTH-FOREIGN-ENCODED-JSON",
            id="metadata-multi-percent-encoded-json-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                r"{\u0022Authorization\u0022:"
                r"\u0022Bearer\u0020SYNTH-FOREIGN-ESCAPED-JSON\u0022}"
            ),
            "SYNTH-FOREIGN-ESCAPED-JSON",
            id="metadata-unicode-escaped-json-value",
        ),
        pytest.param(
            _provider_success_payload_with_metadata_value(
                repr(
                    '{"Authorization":"Bearer '
                    'SYNTH-FOREIGN-REPR-JSON"}'
                )
            ),
            "SYNTH-FOREIGN-REPR-JSON",
            id="metadata-repr-wrapped-json-value",
        ),
        pytest.param(
            _provider_success_payload(
                {
                    "fields": ["value"],
                    "items": [
                        [{"Author\u200bization": "SYNTH-FOREIGN-ZERO-WIDTH-KEY"}]
                    ],
                }
            ),
            "SYNTH-FOREIGN-ZERO-WIDTH-KEY",
            id="zero-width-credential-key",
        ),
        pytest.param(
            _provider_success_payload(
                {"fields": ["value"], "items": [["safe"]]},
                metadata={
                    "Authorization": "Bearer SYNTH-FOREIGN-METADATA-AUTH"
                },
            ),
            "SYNTH-FOREIGN-METADATA-AUTH",
            id="top-level-metadata-authorization",
        ),
        pytest.param(
            _provider_success_payload(
                {"fields": ["value"], "items": [["safe"]]},
                metadata={"token": "SYNTH-FOREIGN-METADATA-TOKEN"},
            ),
            "SYNTH-FOREIGN-METADATA-TOKEN",
            id="top-level-metadata-token",
        ),
    ],
)
def test_foreign_credential_in_success_payload_fails_closed(
    monkeypatch,
    payload,
    secret_fragment,
):
    request_token = "SYNTH-REQUEST-TOKEN"
    _stub_outcome_response(
        monkeypatch,
        payload,
    )

    outcome = tushare_common.tushare_rows_outcome("daily", request_token)
    log_fields = tushare_common.provider_outcome_log_fields(outcome)
    receipt = {"outcome": outcome, "log_fields": log_fields}

    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_code == "provider_error"
    assert outcome.error_message == "provider diagnostic [REDACTED]"
    assert secret_fragment not in repr(receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("token_count", 12, id="token-count"),
        pytest.param("tokenized_value", "ordinary", id="tokenized-value"),
        pytest.param("authorization_status", "approved", id="authorization-status"),
        pytest.param(
            "basic_materials",
            "Basic materials sector rose",
            id="basic-materials",
        ),
        pytest.param("cookie_sales", 42, id="cookie-sales"),
        pytest.param("api_keyboard", "ordinary", id="api-keyboard"),
        pytest.param(
            "password_policy",
            "password policy was updated",
            id="password-policy",
        ),
        pytest.param(
            "description",
            "token economy adoption rose",
            id="token-prose",
        ),
        pytest.param(
            "description",
            "Bearer bonds gained today",
            id="bearer-prose",
        ),
        pytest.param(
            "description",
            "authorization reform passed",
            id="authorization-reform-prose",
        ),
        pytest.param(
            "description",
            "Basic Materials sector rose today",
            id="title-case-basic-materials",
        ),
        pytest.param(
            "description",
            "Bearer Securities gained today",
            id="title-case-bearer-securities",
        ),
        pytest.param(
            "description",
            "Bearer bonds",
            id="two-word-lower-bearer-bonds",
        ),
        pytest.param(
            "description",
            "Bearer Securities",
            id="two-word-title-bearer-securities",
        ),
        pytest.param(
            "description",
            "Basic materials",
            id="two-word-lower-basic-materials",
        ),
        pytest.param(
            "description",
            "Basic Materials",
            id="two-word-title-basic-materials",
        ),
    ],
)
def test_normal_business_token_words_remain_valid_success_rows(
    monkeypatch,
    field,
    value,
):
    _stub_outcome_response(
        monkeypatch,
        _provider_success_payload(
            {"fields": [field], "items": [[value]]},
        ),
    )

    outcome = tushare_common.tushare_rows_outcome(
        "daily",
        "SYNTH-REQUEST-TOKEN",
    )

    assert outcome.state == "success"
    assert outcome.rows == ({field: value},)
    assert outcome.error_code is None
    assert outcome.error_message is None


class _SuccessRowConversionTrap:
    def __init__(self):
        self.conversions = []

    def __str__(self):
        self.conversions.append("str")
        return "Authorization: Bearer SYNTH-CONVERSION-TRAP"

    def __repr__(self):
        self.conversions.append("repr")
        return "Authorization: Bearer SYNTH-CONVERSION-TRAP"


def test_outcome_rejects_unscannable_success_row_without_conversion():
    trap = _SuccessRowConversionTrap()

    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": trap},),
            provider_code=0,
            error_code=None,
            error_message=None,
        )

    assert trap.conversions == []


@pytest.mark.parametrize(
    ("rows", "secret"),
    [
        pytest.param(
            ({"Authorization": "Bearer SYNTH-DIRECT-AUTH"},),
            "SYNTH-DIRECT-AUTH",
            id="authorization-key",
        ),
        pytest.param(
            ({"value": "token=SYNTH-DIRECT-TOKEN"},),
            "SYNTH-DIRECT-TOKEN",
            id="token-assignment",
        ),
        pytest.param(
            ({"value": [{"Set-Cookie": "sid=SYNTH-DIRECT-COOKIE"}]},),
            "SYNTH-DIRECT-COOKIE",
            id="nested-set-cookie",
        ),
        pytest.param(
            ({"value": "Bearer SYNTH-DIRECT-BEARER"},),
            "SYNTH-DIRECT-BEARER",
            id="bearer-value",
        ),
    ],
)
def test_direct_outcome_rejects_caller_known_or_structured_credential_rows(
    rows,
    secret,
):
    with pytest.raises(
        ValueError,
        match="sensitive or unscannable",
    ) as exc_info:
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=rows,
            provider_code=0,
            error_code=None,
            error_message=None,
            sensitive_values=(secret,),
        )

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(
            ({"Authorization": "Bearer abcdefgh"},),
            id="authorization-key",
        ),
        pytest.param(
            ({"value": [{"Set-Cookie": "sid=abcdefgh"}]},),
            id="nested-set-cookie-key",
        ),
    ],
)
def test_direct_outcome_rejects_structured_credential_without_known_value(rows):
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=rows,
            provider_code=0,
            error_code=None,
            error_message=None,
        )


class _SuccessStringSubclass(str):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.repr_calls = 0
        return instance

    def __repr__(self):
        self.repr_calls += 1
        return "Bearer SYNTH-STRING-SUBCLASS-SECRET"


def test_outcome_rejects_string_subclass_without_repr_conversion():
    value = _SuccessStringSubclass("ordinary visible text")

    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": value},),
            provider_code=0,
            error_code=None,
            error_message=None,
        )

    assert value.repr_calls == 0


class _SuccessMappingSubclass(dict):
    pass


class _SuccessListSubclass(list):
    pass


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(_SuccessMappingSubclass({"value": "safe"}), id="mapping"),
        pytest.param(_SuccessListSubclass(["safe"]), id="list"),
    ],
)
def test_outcome_rejects_success_container_subclasses(value):
    with pytest.raises(ValueError, match="sensitive or unscannable"):
        tushare_common.ProviderCallOutcome(
            state="success",
            rows=({"value": value},),
            provider_code=0,
            error_code=None,
            error_message=None,
        )


def test_outcome_rows_are_defensive_deep_immutable_snapshots():
    foreign_secret = "SYNTH-POST-CONSTRUCTION-SECRET"
    source_nested = {"items": ["safe"]}
    source_row = {"value": source_nested}
    outcome = tushare_common.ProviderCallOutcome(
        state="success",
        rows=(source_row,),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    source_row["Authorization"] = f"Bearer {foreign_secret}"
    source_nested["Authorization"] = f"Bearer {foreign_secret}"
    source_nested["items"].append(f"Bearer {foreign_secret}")

    assert foreign_secret not in repr(outcome)
    assert outcome.rows == ({"value": {"items": ("safe",)}},)
    with pytest.raises(TypeError):
        outcome.rows[0]["Authorization"] = f"Bearer {foreign_secret}"
    with pytest.raises(TypeError):
        outcome.rows[0]["value"]["Authorization"] = f"Bearer {foreign_secret}"
    with pytest.raises(AttributeError):
        outcome.rows[0]["value"]["items"].append(foreign_secret)


def test_outcome_mutable_rows_are_independent_plain_json_copies():
    outcome = tushare_common.ProviderCallOutcome(
        state="success",
        rows=({"value": {"items": ["safe"]}},),
        provider_code=0,
        error_code=None,
        error_message=None,
    )

    rows = outcome.mutable_rows()
    rows[0]["value"]["items"].append("consumer mutation")

    assert type(rows[0]) is dict
    assert type(rows[0]["value"]) is dict
    assert type(rows[0]["value"]["items"]) is list
    assert outcome.rows == ({"value": {"items": ("safe",)}},)
