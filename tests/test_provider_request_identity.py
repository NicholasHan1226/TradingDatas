from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from collectors.tushare.provider_native_ingest import (
    ProviderCall,
    _provider_call_attempt_id,
)
from collectors.tushare.tushare_common import ProviderCallOutcome
from storage.ingest_receipts import (
    ProviderRequestIdentity,
    make_provider_call_attempt_id,
    parse_provider_call_attempt_id,
)


def test_provider_request_identity_is_typed_canonical_and_immutable() -> None:
    request_variant = {
        "listed": True,
        "limit": 100,
        "minimum": 1.25,
        "trade_date": "20260720",
    }
    fanout_values = ["SSE", 1, 2.5, False]

    identity = ProviderRequestIdentity(
        request_variant=request_variant,
        fanout_parameter="exchange",
        fanout_values=fanout_values,
        page_offset=200,
        page_index=2,
    )

    request_variant["limit"] = 999
    fanout_values.append("SZSE")
    assert dict(identity.request_variant) == {
        "limit": 100,
        "listed": True,
        "minimum": 1.25,
        "trade_date": "20260720",
    }
    assert identity.fanout_values == ("SSE", 1, 2.5, False)
    assert identity.canonical_payload() == {
        "fanout_parameter": "exchange",
        "fanout_values": ["SSE", 1, 2.5, False],
        "page_index": 2,
        "page_offset": 200,
        "request_variant": {
            "limit": 100,
            "listed": True,
            "minimum": 1.25,
            "trade_date": "20260720",
        },
    }
    with pytest.raises(TypeError):
        identity.request_variant["limit"] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        identity.page_index = 3  # type: ignore[misc]


def test_physical_call_attempt_ids_sort_by_numeric_call_order_after_nine() -> None:
    outcome = ProviderCallOutcome(
        state="empty",
        rows=(),
        provider_code=0,
        error_code=None,
        error_message=None,
    )
    identity = ProviderRequestIdentity.trivial()
    call_two = ProviderCall(identity, outcome, call_index=2, retry_index=0)
    call_ten = ProviderCall(identity, outcome, call_index=10, retry_index=0)

    id_two = _provider_call_attempt_id("root", call_two)
    id_ten = _provider_call_attempt_id("root", call_ten)

    assert id_two < id_ten
    assert "provider-call:000000000002" in id_two
    assert "provider-call:000000000010" in id_ten


def test_physical_call_attempt_identity_round_trips_numeric_ordinals() -> None:
    attempt_id = make_provider_call_attempt_id(
        "execution-root",
        call_index=10,
        retry_index=2,
    )

    parsed = parse_provider_call_attempt_id(attempt_id)

    assert parsed is not None
    assert parsed.root_attempt_id == "execution-root"
    assert parsed.call_index == 10
    assert parsed.retry_index == 2
    assert parse_provider_call_attempt_id("ordinary-attempt") is None


@pytest.mark.parametrize(
    "attempt_id",
    [
        "root:provider-call:2:retry:0",
        "root:provider-call:000000000002:retry:000000000003",
        "root:provider-call:000000000002:retry:00000000000x",
    ],
)
def test_physical_call_attempt_identity_rejects_noncanonical_values(
    attempt_id: str,
) -> None:
    with pytest.raises(ValueError):
        parse_provider_call_attempt_id(attempt_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_variant", {"filters": None}),
        ("request_variant", {"filters": []}),
        ("request_variant", {"filters": math.inf}),
        ("request_variant", {1: "value"}),
        ("fanout_values", (None,)),
        ("fanout_values", (["SSE"],)),
        ("fanout_values", (math.nan,)),
        ("page_offset", True),
        ("page_index", -1),
        ("page_index", True),
    ],
)
def test_provider_request_identity_rejects_non_contract_values(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "request_variant": {},
        "fanout_parameter": None,
        "fanout_values": (),
        "page_offset": None,
        "page_index": 0,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError), match=field):
        ProviderRequestIdentity(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "sensitive_key",
    ["apiToken", "authorization_header", "client-secret", "dbPath", "source_file"],
)
def test_provider_request_identity_rejects_secret_like_parameter_keys(
    sensitive_key: str,
) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        ProviderRequestIdentity(
            request_variant={sensitive_key: "redacted"},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        )
    with pytest.raises(ValueError, match="sensitive"):
        ProviderRequestIdentity(
            request_variant={},
            fanout_parameter=sensitive_key,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        )


def test_trivial_provider_request_identity_is_explicit_and_canonical() -> None:
    assert ProviderRequestIdentity.trivial().canonical_payload() == {
        "fanout_parameter": None,
        "fanout_values": [],
        "page_index": 0,
        "page_offset": None,
        "request_variant": {},
    }


def test_cursor_v2_identity_is_complete_and_canonical():
    identity = ProviderRequestIdentity(
        request_variant={"listed": True},
        fanout_parameter="ts_code",
        fanout_values=("000001.SZ",),
        page_offset=None,
        page_index=0,
        cursor_contract_version=2,
        frozen_universe_sha256="a" * 64,
        batch_index=1,
        batch_count=3,
        batch_values_sha256="b" * 64,
    )
    payload = identity.canonical_payload()
    assert payload["cursor_contract_version"] == 2
    assert payload["batch_index"] == 1
    assert payload["batch_count"] == 3
    assert ProviderRequestIdentity(**payload).canonical_payload() == payload


@pytest.mark.parametrize("kwargs", [
    {"cursor_contract_version": 2},
    {"cursor_contract_version": 1, "frozen_universe_sha256": "a" * 64, "batch_index": 0, "batch_count": 1, "batch_values_sha256": "b" * 64},
    {"cursor_contract_version": 2, "frozen_universe_sha256": "a" * 63, "batch_index": 0, "batch_count": 1, "batch_values_sha256": "b" * 64},
    {"cursor_contract_version": 2, "frozen_universe_sha256": "a" * 64, "batch_index": 2, "batch_count": 2, "batch_values_sha256": "b" * 64},
])
def test_cursor_v2_identity_rejects_incomplete_or_malformed(kwargs):
    values = {
        "request_variant": {}, "fanout_parameter": "ts_code",
        "fanout_values": ("000001.SZ",), "page_offset": None, "page_index": 0,
    }
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        ProviderRequestIdentity(**values)
