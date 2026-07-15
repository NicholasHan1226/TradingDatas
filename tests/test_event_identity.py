from __future__ import annotations

import json

import pytest

from storage import event_identity as event_identity_contract
from storage.event_identity import event_content_fingerprint, stable_event_id


ROUTE_IDENTITY_ROWS = {
    "tushare_block_trade": {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
        "price": 10.0,
        "vol": 1000,
        "buyer": "buyer-a",
        "seller": "seller-b",
    },
    "tushare_limit_list": {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
    },
    "tushare_limit_list_d": {
        "ts_code": "600000.SH",
        "trade_date": "20260713",
    },
    "tushare_broker_recommend": {
        "month": "202607",
        "broker": "broker-a",
        "ts_code": "600000.SH",
    },
    "tushare_suspend_d": {
        "ts_code": "600000.SH",
        "suspend_date": "20260713",
    },
    "tushare_namechange": {
        "ts_code": "600000.SH",
        "start_date": "20260713",
        "name": "new-name",
    },
    "tushare_cb_issue": {"ts_code": "123456.SZ"},
    "tushare_news": {
        "datetime": "2026-07-13 09:00:00",
        "title": "headline",
    },
    "tushare_major_news": {
        "pub_time": "2026-07-13 09:00:00",
        "title": "major headline",
    },
    "tushare_cctv_news": {
        "date": "20260713",
        "broadcast_time": "19:00",
        "title": "broadcast headline",
    },
    "tushare_anns_d": {
        "ts_code": "600000.SH",
        "ann_date": "20260713",
        "title": "announcement",
    },
    "tushare_report_rc": {
        "ts_code": "600000.SH",
        "report_date": "20260713",
        "report_title": "research report",
    },
}

EXPECTED_TRUSTED_NATIVE_ID_FIELDS = {
    "tushare_block_trade": (),
    "tushare_limit_list": (),
    "tushare_limit_list_d": (),
    "tushare_broker_recommend": (),
    "tushare_suspend_d": (),
    "tushare_namechange": (),
    "tushare_cb_issue": (),
    "tushare_news": (),
    "tushare_major_news": (),
    "tushare_cctv_news": (),
    "tushare_anns_d": (),
    "tushare_report_rc": (),
}


def test_every_registry_event_route_declares_its_native_id_contract() -> None:
    assert (
        event_identity_contract.TRUSTED_NATIVE_ID_FIELDS
        == EXPECTED_TRUSTED_NATIVE_ID_FIELDS
    )


@pytest.mark.parametrize(
    ("provider", "row"),
    ROUTE_IDENTITY_ROWS.items(),
)
def test_every_registry_event_route_has_explicit_replayable_identity(
    provider: str,
    row: dict[str, object],
) -> None:
    event_type = provider.removeprefix("tushare_")

    first = stable_event_id(provider, event_type, row)
    replay = stable_event_id(
        provider,
        event_type,
        {**dict(reversed(list(row.items()))), "content": "corrected detail"},
    )

    assert first.startswith("evt:")
    assert replay == first


@pytest.mark.parametrize(
    ("provider", "row"),
    ROUTE_IDENTITY_ROWS.items(),
)
def test_registry_live_route_ignores_undeclared_top_level_native_ids(
    provider: str,
    row: dict[str, object],
) -> None:
    event_type = provider.removeprefix("tushare_")
    first = {**row, "id": "forged-top-a", "event_id": "forged-event-a"}
    replay = {**row, "id": "forged-top-b", "event_id": "forged-event-b"}

    assert stable_event_id(
        provider,
        event_type,
        first,
        allow_legacy_fallback=False,
    ) == stable_event_id(
        provider,
        event_type,
        replay,
        allow_legacy_fallback=False,
    )


@pytest.mark.parametrize(
    ("provider", "row"),
    ROUTE_IDENTITY_ROWS.items(),
)
def test_registry_live_route_ignores_nested_generic_ids(
    provider: str,
    row: dict[str, object],
) -> None:
    event_type = provider.removeprefix("tushare_")
    first = {
        **row,
        "raw_json": json.dumps({"id": "forged-raw-a"}),
        "content": json.dumps({"event_id": "forged-content-a"}),
    }
    replay = {
        **row,
        "raw_json": json.dumps({"id": "forged-raw-b"}),
        "content": json.dumps({"event_id": "forged-content-b"}),
    }

    assert stable_event_id(
        provider,
        event_type,
        first,
        allow_legacy_fallback=False,
    ) == stable_event_id(
        provider,
        event_type,
        replay,
        allow_legacy_fallback=False,
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("ts_code", "600001.SH"),
        ("trade_date", "20260714"),
        ("price", 10.1),
        ("vol", 1001),
        ("buyer", "buyer-c"),
        ("seller", "seller-d"),
    ],
)
def test_block_trade_without_native_id_uses_full_immutable_business_key(
    field: str,
    changed: object,
) -> None:
    row = ROUTE_IDENTITY_ROWS["tushare_block_trade"]

    assert stable_event_id(
        "tushare_block_trade", "block_trade", row
    ) != stable_event_id(
        "tushare_block_trade",
        "block_trade",
        {**row, field: changed},
    )


def test_block_trade_top_level_generic_id_never_overrides_full_key() -> None:
    row = {
        **ROUTE_IDENTITY_ROWS["tushare_block_trade"],
        "id": "block-42",
        "provider": "tushare_block_trade",
        "event_type": "block_trade",
    }
    changed = {**row, "price": 10.1}

    assert stable_event_id(
        "tushare_block_trade", "block_trade", row
    ) != stable_event_id("tushare_block_trade", "block_trade", changed)
    assert event_content_fingerprint(row) != event_content_fingerprint(changed)


def test_news_undeclared_top_level_event_id_is_not_identity() -> None:
    first = {
        "event_id": "provider-event-42",
        "provider": "tushare_news",
        "event_type": "news",
        "datetime": "2026-07-13 09:00:00",
        "title": "headline v1",
        "content": "body v1",
    }
    changed = {**first, "title": "headline v2", "content": "body v2"}

    assert stable_event_id(
        "tushare_news", "news", first
    ) != stable_event_id("tushare_news", "news", changed)
    assert event_content_fingerprint(first) != event_content_fingerprint(changed)


def test_block_trade_missing_full_business_key_fails_closed() -> None:
    row = dict(ROUTE_IDENTITY_ROWS["tushare_block_trade"])
    row.pop("seller")

    with pytest.raises(ValueError, match="missing required business key"):
        stable_event_id("tushare_block_trade", "block_trade", row)


@pytest.mark.parametrize("raw_payload", ["", "opaque"])
def test_cb_issue_opaque_raw_is_provenance_not_fingerprint_replacement(
    raw_payload: str,
) -> None:
    envelope = json.dumps(
        {
            "_sharedsignals_provenance": {
                "provider_claim": "spoof-source",
                "raw_payload_source": "raw_json",
                "schema": "provider-claim.v1",
            },
            "raw_payload": raw_payload,
        },
        sort_keys=True,
    )
    first = {
        "provider": "tushare_cb_issue",
        "event_type": "cb_issue",
        "ts_code": "123456.SZ",
        "issue_price": 100.0,
        "raw_json": envelope,
    }

    assert event_content_fingerprint(first) != event_content_fingerprint(
        {**first, "issue_price": 101.0}
    )


def test_cb_issue_current_business_fields_override_stale_nested_raw() -> None:
    stale_envelope = json.dumps(
        {
            "_sharedsignals_provenance": {
                "provider_claim": "nested-forged",
                "raw_payload_source": "row",
                "schema": "provider-claim.v1",
            },
            "raw_payload": {
                "ts_code": "123456.SZ",
                "issue_price": 100.0,
            },
        },
        sort_keys=True,
    )
    first = {
        "provider": "tushare_cb_issue",
        "event_type": "cb_issue",
        "ts_code": "123456.SZ",
        "issue_price": 100.0,
        "raw_json": stale_envelope,
    }

    assert event_content_fingerprint(first) != event_content_fingerprint(
        {**first, "issue_price": 101.0}
    )


def _provider_claim(payload: object) -> str:
    return json.dumps(
        {
            "_sharedsignals_provenance": {
                "provider_claim": "spoof-source",
                "raw_payload_source": "raw_json",
                "schema": "provider-claim.v1",
            },
            "raw_payload": payload,
        },
        sort_keys=True,
    )


def test_nested_news_business_content_is_normalized_across_raw_envelopes() -> None:
    base = {
        "provider": "tushare_news",
        "event_type": "news",
        "id": "news-42",
        "title": "headline",
        "event_time": "2026-07-13 09:00:00",
    }
    plain = {**base, "raw_json": json.dumps({"content": "v1"})}
    wrapped = {**base, "raw_json": _provider_claim({"content": "v1"})}
    changed = {**base, "raw_json": _provider_claim({"content": "v2"})}

    assert event_content_fingerprint(plain) == event_content_fingerprint(wrapped)
    assert event_content_fingerprint(wrapped) != event_content_fingerprint(changed)


def test_nested_context_spoof_does_not_change_business_fingerprint() -> None:
    base = {
        "provider": "tushare_news",
        "event_type": "news",
        "id": "news-42",
        "title": "headline",
        "raw_json": json.dumps({"content": "v1"}),
    }
    spoofed = {
        **base,
        "raw_json": json.dumps(
            {
                "content": "v1",
                "provider": "nested-forged",
                "event_type": "nested-forged",
            }
        ),
    }

    assert event_content_fingerprint(base) == event_content_fingerprint(spoofed)
