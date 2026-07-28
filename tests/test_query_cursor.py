from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

import query_cursor
from query_cursor import (
    CursorClaims,
    CursorConfigurationError,
    CursorExpectation,
    CursorMismatch,
    InvalidCursor,
    SignedCursorCodec,
)


NOW = datetime(2026, 7, 16, 8, 0, 0, 750_000, tzinfo=timezone.utc)
SECRET = b"phase2-primary-cursor-signing-key-0001"
WRONG_SECRET = b"phase2-secondary-cursor-signing-key-02"
WIRE_KEYS = {
    "v",
    "kind",
    "catalog_version",
    "dataset_id",
    "schema_major",
    "query_hash",
    "policy_id",
    "receipt_watermark",
    "sort_key",
    "expires_at",
}
BASE64URL_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


@pytest.fixture
def codec() -> SignedCursorCodec:
    return SignedCursorCodec(SECRET)


@pytest.fixture
def claims() -> CursorClaims:
    return CursorClaims(
        kind="query",
        catalog_version="v1-a1b2c3d4e5f60708",
        dataset_id="cn.equity.daily",
        schema_major=1,
        query_hash="query-hash-a",
        policy_id="policy-hash-a",
        receipt_watermark="receipt-watermark-a",
        sort_key=("20260716", "600519.SH", 42),
        expires_at=math.floor(NOW.timestamp()) + 900,
    )


@pytest.fixture
def expectation(claims: CursorClaims) -> CursorExpectation:
    return CursorExpectation(
        kind=claims.kind,
        catalog_version=claims.catalog_version,
        dataset_id=claims.dataset_id,
        schema_major=claims.schema_major,
        query_hash=claims.query_hash,
        policy_id=claims.policy_id,
        receipt_watermark=claims.receipt_watermark,
    )


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_segment(segment: str) -> bytes:
    return base64.b64decode(
        segment + "=" * (-len(segment) % 4),
        altchars=b"-_",
        validate=True,
    )


def _token_from_raw(raw: bytes, *, secret: bytes = SECRET) -> str:
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return f"{_b64url(raw)}.{_b64url(signature)}"


def _token_from_payload(payload: object, *, secret: bytes = SECRET) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _token_from_raw(raw, secret=secret)


def _noncanonical_trailing_bits(segment: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    remainder = len(segment) % 4
    assert remainder in {2, 3}
    unused_bits = 4 if remainder == 2 else 2
    current_index = alphabet.index(segment[-1])
    assert current_index % (1 << unused_bits) == 0
    replacement = alphabet[current_index + 1]
    candidate = segment[:-1] + replacement
    assert _decode_segment(candidate) == _decode_segment(segment)
    assert _b64url(_decode_segment(candidate)) == segment
    return candidate


def _standard_signature_token(character: str) -> str:
    assert character in {"+", "/"}
    for nonce in range(10_000):
        raw = f"signed-envelope-{nonce}".encode("ascii")
        signature = hmac.new(SECRET, raw, hashlib.sha256).digest()
        standard_signature = base64.b64encode(signature).decode("ascii").rstrip("=")
        if character in standard_signature:
            return f"{_b64url(raw)}.{standard_signature}"
    raise AssertionError(f"could not synthesize standard base64 {character!r}")


def _wire_payload(token: str) -> dict[str, object]:
    payload_segment, _ = token.split(".")
    payload = json.loads(_decode_segment(payload_segment))
    assert isinstance(payload, dict)
    return payload


def test_cursor_round_trip_is_canonical_versioned_and_unpadded(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    token = codec.encode(claims)

    assert token == codec.encode(claims)
    assert token.count(".") == 1
    payload_segment, signature_segment = token.split(".")
    assert BASE64URL_RE.fullmatch(payload_segment)
    assert BASE64URL_RE.fullmatch(signature_segment)
    assert "=" not in token

    raw_payload = _decode_segment(payload_segment)
    signature = _decode_segment(signature_segment)
    payload = json.loads(raw_payload)
    assert set(payload) == WIRE_KEYS
    assert payload["v"] == 1
    assert type(payload["v"]) is int
    assert payload["sort_key"] == list(claims.sort_key)
    assert len(signature) == hashlib.sha256().digest_size
    assert raw_payload == json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    decoded = codec.decode(token, expected=expectation, now=NOW)
    assert decoded == claims
    assert type(decoded.sort_key) is tuple


def test_cursor_payload_contains_only_bound_claims_not_secrets_or_internal_names(
    codec: SignedCursorCodec,
    claims: CursorClaims,
) -> None:
    token = codec.encode(claims)
    payload_segment, _ = token.split(".")
    raw_payload = _decode_segment(payload_segment)

    assert set(json.loads(raw_payload)) == WIRE_KEYS
    assert SECRET not in raw_payload
    assert SECRET.decode("ascii") not in token
    for forbidden in (
        b"__ss_rowid",
        b"primary_table",
        b"database_path",
        b"SELECT ",
        b"credential",
        b"provider_token",
    ):
        assert forbidden not in raw_payload


def test_catalog_cursor_round_trip_requires_null_dataset_and_schema(
    codec: SignedCursorCodec,
) -> None:
    claims = CursorClaims(
        kind="catalog",
        catalog_version="v1-a1b2c3d4e5f60708",
        dataset_id=None,
        schema_major=None,
        query_hash="catalog-filter-hash",
        policy_id="policy-hash-a",
        receipt_watermark="catalog-watermark-a",
        sort_key=("cn.equity.daily",),
        expires_at=math.floor(NOW.timestamp()) + 30,
    )
    expected = CursorExpectation(
        kind="catalog",
        catalog_version=claims.catalog_version,
        dataset_id=None,
        schema_major=None,
        query_hash=claims.query_hash,
        policy_id=claims.policy_id,
        receipt_watermark=claims.receipt_watermark,
    )

    assert codec.decode(codec.encode(claims), expected=expected, now=NOW) == claims


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "other"},
        {"kind": 1},
        {"catalog_version": ""},
        {"catalog_version": " v1-catalog"},
        {"dataset_id": None},
        {"dataset_id": "cn equity daily"},
        {"schema_major": None},
        {"schema_major": True},
        {"schema_major": 1.0},
        {"query_hash": 1},
        {"query_hash": ""},
        {"policy_id": " policy"},
        {"receipt_watermark": ""},
        {"sort_key": ["20260716"]},
        {"expires_at": True},
        {"expires_at": 1.0},
        {"expires_at": "1"},
    ],
)
def test_query_claims_reject_noncanonical_native_types(
    claims: CursorClaims,
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(claims, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_id": "cn.equity.daily"},
        {"schema_major": 1},
    ],
)
def test_catalog_claims_reject_non_null_dataset_or_schema(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "kind": "catalog",
        "catalog_version": "v1-catalog",
        "dataset_id": None,
        "schema_major": None,
        "query_hash": "catalog-query-hash",
        "policy_id": "policy-hash",
        "receipt_watermark": "catalog-watermark",
        "sort_key": ("cn.equity.daily",),
        "expires_at": math.floor(NOW.timestamp()) + 30,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        CursorClaims(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "sort_key",
    [
        (["nested"],),
        ({"hidden": "row"},),
        (("nested",),),
        (b"bytes",),
        (float("nan"),),
        (float("inf"),),
        (float("-inf"),),
    ],
)
def test_sort_key_rejects_mutable_nested_or_non_finite_values(
    claims: CursorClaims,
    sort_key: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError, match="sort_key"):
        replace(claims, sort_key=sort_key)


def test_sort_key_is_frozen_and_replace_revalidates(claims: CursorClaims) -> None:
    assert type(claims.sort_key) is tuple
    with pytest.raises(FrozenInstanceError):
        claims.sort_key = ("changed",)  # type: ignore[misc]
    with pytest.raises(ValueError, match="sort_key"):
        replace(claims, sort_key=("stable", ["mutable"]))


def test_sort_key_accepts_every_finite_json_scalar(claims: CursorClaims) -> None:
    replaced = replace(
        claims,
        sort_key=(None, "text", 0, True, 1.25, -2.5),
    )

    assert replaced.sort_key == (None, "text", 0, True, 1.25, -2.5)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "other"},
        {"kind": 1},
        {"dataset_id": None},
        {"schema_major": True},
        {"query_hash": " query"},
        {"policy_id": ""},
        {"receipt_watermark": 1},
    ],
)
def test_expectation_revalidates_native_binding_types(
    expectation: CursorExpectation,
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(expectation, **changes)


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda token: "",
        lambda token: token.split(".")[0],
        lambda token: "." + token.split(".")[1],
        lambda token: token.split(".")[0] + ".",
        lambda token: token + ".extra",
        lambda token: token + "=",
        lambda token: token.replace(".", "=.", 1),
        lambda token: "not+base64." + token.split(".")[1],
        lambda token: token[:-1],
    ],
)
def test_cursor_rejects_malformed_truncated_or_noncanonical_envelopes(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
    token_factory: object,
) -> None:
    token = codec.encode(claims)
    malformed = token_factory(token)  # type: ignore[operator]

    with pytest.raises(InvalidCursor, match="cursor token"):
        codec.decode(malformed, expected=expectation, now=NOW)


def test_cursor_strictly_rejects_illegal_characters_in_either_segment(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    token = codec.encode(claims)
    payload_segment, signature_segment = token.split(".")
    cases = [
        f" {payload_segment}.{signature_segment}",
        f"{payload_segment}\n.{signature_segment}",
        f"{payload_segment}$.{signature_segment}",
        f"{payload_segment}=.{signature_segment}",
        f"{payload_segment}==.{signature_segment}",
        f"{payload_segment}. {signature_segment}",
        f"{payload_segment}.{signature_segment}\n",
        f"{payload_segment}.{signature_segment}$",
        f"{payload_segment}.{signature_segment}=",
        f"{payload_segment}.{signature_segment}==",
        _token_from_raw(b"\xfb").replace("-w.", "+w.", 1),
        _token_from_raw(b"\xff").replace("_w.", "/w.", 1),
        _standard_signature_token("+"),
        _standard_signature_token("/"),
    ]
    assert all(candidate.count(".") == 1 for candidate in cases)

    for candidate in cases:
        with pytest.raises(InvalidCursor, match="cursor token"):
            codec.decode(candidate, expected=expectation, now=NOW)


def test_cursor_rejects_noncanonical_trailing_bits_in_either_segment(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    adjusted_claims = claims
    while True:
        token = codec.encode(adjusted_claims)
        payload_segment, signature_segment = token.split(".")
        if len(payload_segment) % 4 in {2, 3}:
            break
        adjusted_claims = replace(
            adjusted_claims,
            query_hash=adjusted_claims.query_hash + "x",
        )
    adjusted_expectation = replace(
        expectation,
        query_hash=adjusted_claims.query_hash,
    )
    cases = [
        f"{_noncanonical_trailing_bits(payload_segment)}.{signature_segment}",
        f"{payload_segment}.{_noncanonical_trailing_bits(signature_segment)}",
    ]

    for candidate in cases:
        with pytest.raises(InvalidCursor, match="cursor token"):
            codec.decode(candidate, expected=adjusted_expectation, now=NOW)


def test_cursor_rejects_payload_tampering_before_binding_comparison(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    token = codec.encode(claims)
    payload_segment, signature_segment = token.split(".")
    replacement = "A" if payload_segment[0] != "A" else "B"
    tampered = f"{replacement}{payload_segment[1:]}.{signature_segment}"
    mismatched = replace(expectation, query_hash="different-query")

    with pytest.raises(InvalidCursor, match="signature") as exc_info:
        codec.decode(tampered, expected=mismatched, now=NOW)
    assert tampered not in str(exc_info.value)
    assert "different-query" not in str(exc_info.value)


def test_cursor_rejects_signature_tampering(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    token = codec.encode(claims)
    payload_segment, signature_segment = token.split(".")
    replacement = "A" if signature_segment[0] != "A" else "B"
    tampered = f"{payload_segment}.{replacement}{signature_segment[1:]}"

    with pytest.raises(InvalidCursor, match="signature"):
        codec.decode(tampered, expected=expectation, now=NOW)


def test_cursor_rejects_wrong_signing_key(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    wrong_codec = SignedCursorCodec(WRONG_SECRET)

    with pytest.raises(InvalidCursor, match="signature"):
        wrong_codec.decode(codec.encode(claims), expected=expectation, now=NOW)


def test_signature_verification_uses_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real_compare_digest = hmac.compare_digest

    def recording_compare_digest(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return real_compare_digest(left, right)

    monkeypatch.setattr(query_cursor.hmac, "compare_digest", recording_compare_digest)

    assert codec.decode(codec.encode(claims), expected=expectation, now=NOW) == claims
    assert len(calls) == 1
    assert all(len(value) == hashlib.sha256().digest_size for value in calls[0])


def test_hmac_is_verified_before_payload_schema(
    codec: SignedCursorCodec,
    expectation: CursorExpectation,
) -> None:
    malformed_payload_with_wrong_signature = _token_from_raw(
        b"not-json",
        secret=WRONG_SECRET,
    )

    with pytest.raises(InvalidCursor, match="signature"):
        codec.decode(
            malformed_payload_with_wrong_signature,
            expected=expectation,
            now=NOW,
        )


def test_cursor_rejects_unsupported_or_non_native_version(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    payload = _wire_payload(codec.encode(claims))
    for version in (2, True, "1"):
        unsupported = dict(payload, v=version)
        with pytest.raises(InvalidCursor, match="version"):
            codec.decode(
                _token_from_payload(unsupported),
                expected=expectation,
                now=NOW,
            )


def test_cursor_rejects_missing_or_extra_claim_keys_without_leaking_values(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    payload = _wire_payload(codec.encode(claims))
    missing = dict(payload)
    missing.pop("query_hash")
    extra = dict(payload, sql="SELECT secret FROM /private/data.db")

    for candidate in (missing, extra):
        token = _token_from_payload(candidate)
        with pytest.raises(InvalidCursor, match="payload") as exc_info:
            codec.decode(token, expected=expectation, now=NOW)
        message = str(exc_info.value)
        assert token not in message
        assert "SELECT" not in message
        assert "/private/data.db" not in message


def test_cursor_rejects_duplicate_json_keys(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    payload_segment, _ = codec.encode(claims).split(".")
    raw = _decode_segment(payload_segment)
    duplicate = raw.replace(b'"v":1', b'"v":1,"v":1')
    assert duplicate != raw

    with pytest.raises(InvalidCursor, match="payload"):
        codec.decode(_token_from_raw(duplicate), expected=expectation, now=NOW)


def test_cursor_rejects_noncanonical_json_bytes(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    payload = _wire_payload(codec.encode(claims))
    noncanonical = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")

    with pytest.raises(InvalidCursor, match="canonical"):
        codec.decode(
            _token_from_raw(noncanonical),
            expected=expectation,
            now=NOW,
        )


def test_cursor_rejects_invalid_utf8_and_non_object_json(
    codec: SignedCursorCodec,
    expectation: CursorExpectation,
) -> None:
    for raw in (b"\xff", b"[]"):
        with pytest.raises(InvalidCursor, match="payload"):
            codec.decode(_token_from_raw(raw), expected=expectation, now=NOW)


@pytest.mark.parametrize(
    "raw_payload",
    [
        pytest.param(
            b"[" * 2_000 + b"0" + b"]" * 2_000,
            id="nested-arrays",
        ),
        pytest.param(
            b"[" + b'{"item":' * 2_000 + b"0" + b"}" * 2_000 + b"]",
            id="nested-objects",
        ),
    ],
)
def test_hmac_valid_deep_json_is_category_only_invalid_cursor(
    codec: SignedCursorCodec,
    expectation: CursorExpectation,
    raw_payload: bytes,
) -> None:
    token = _token_from_raw(raw_payload)

    with pytest.raises(InvalidCursor) as exc_info:
        codec.decode(token, expected=expectation, now=NOW)

    assert str(exc_info.value) == "cursor payload is invalid"
    assert token not in str(exc_info.value)


@pytest.mark.parametrize("stage", ["decode", "canonicalize"])
def test_payload_json_recursion_error_is_category_only_invalid_cursor(
    monkeypatch: pytest.MonkeyPatch,
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
    stage: str,
) -> None:
    token = codec.encode(claims)

    def raise_recursion_error(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("sensitive-nesting-marker")

    if stage == "decode":
        monkeypatch.setattr(query_cursor.json, "loads", raise_recursion_error)
    else:
        monkeypatch.setattr(
            query_cursor,
            "_canonical_json_bytes",
            raise_recursion_error,
        )

    with pytest.raises(InvalidCursor) as exc_info:
        codec.decode(token, expected=expectation, now=NOW)

    assert str(exc_info.value) == "cursor payload is invalid"
    assert "sensitive-nesting-marker" not in str(exc_info.value)
    assert token not in str(exc_info.value)


def test_cursor_rejects_signed_nan_payload(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    payload_segment, _ = codec.encode(claims).split(".")
    raw = _decode_segment(payload_segment)
    with_nan = re.sub(
        rb'"expires_at":[0-9]+',
        b'"expires_at":NaN',
        raw,
    )
    assert with_nan != raw

    with pytest.raises(InvalidCursor, match="payload"):
        codec.decode(_token_from_raw(with_nan), expected=expectation, now=NOW)


@pytest.mark.parametrize("expires_at", [True, 1.0, "1"])
def test_cursor_rejects_signed_non_native_expiry_claim(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
    expires_at: object,
) -> None:
    payload = dict(_wire_payload(codec.encode(claims)), expires_at=expires_at)

    with pytest.raises(InvalidCursor, match="payload"):
        codec.decode(_token_from_payload(payload), expected=expectation, now=NOW)


def test_cursor_expires_at_floor_of_aware_server_clock(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    floor_now = math.floor(NOW.timestamp())
    expired = replace(claims, expires_at=floor_now)
    still_valid = replace(claims, expires_at=floor_now + 1)

    with pytest.raises(InvalidCursor, match="expired"):
        codec.decode(codec.encode(expired), expected=expectation, now=NOW)
    assert (
        codec.decode(codec.encode(still_valid), expected=expectation, now=NOW)
        == still_valid
    )


def test_expiry_is_checked_before_expected_binding_mismatch(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    expired = replace(claims, expires_at=math.floor(NOW.timestamp()))
    mismatched = replace(expectation, query_hash="different-query")

    with pytest.raises(InvalidCursor, match="expired"):
        codec.decode(codec.encode(expired), expected=mismatched, now=NOW)


@pytest.mark.parametrize(
    "invalid_now",
    [datetime(2026, 7, 16, 8, 0, 0), True, "2026-07-16T08:00:00Z"],
)
def test_decode_rejects_invalid_or_naive_server_clock(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
    invalid_now: object,
) -> None:
    with pytest.raises(CursorConfigurationError, match="clock"):
        codec.decode(
            codec.encode(claims),
            expected=expectation,
            now=invalid_now,  # type: ignore[arg-type]
        )


def test_decode_accepts_equivalent_non_utc_aware_clock(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    shanghai_clock = NOW.astimezone(timezone(timedelta(hours=8)))

    assert (
        codec.decode(codec.encode(claims), expected=expectation, now=shanghai_clock)
        == claims
    )


@pytest.mark.parametrize(
    ("field", "new_value", "message"),
    [
        ("catalog_version", "v1-different", "catalog version"),
        ("dataset_id", "cn.equity.weekly", "dataset"),
        ("schema_major", 2, "schema major"),
        ("query_hash", "query-hash-b", "query"),
        ("policy_id", "policy-hash-b", "policy"),
        ("receipt_watermark", "receipt-watermark-b", "receipt watermark"),
    ],
)
def test_cursor_rejects_cross_binding_reuse_with_category_only_message(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
    field: str,
    new_value: object,
    message: str,
) -> None:
    mismatched = replace(expectation, **{field: new_value})
    token = codec.encode(claims)

    with pytest.raises(CursorMismatch, match=message) as exc_info:
        codec.decode(token, expected=mismatched, now=NOW)
    public_message = str(exc_info.value)
    assert token not in public_message
    assert str(new_value) not in public_message
    assert str(getattr(claims, field)) not in public_message


def test_cursor_rejects_cross_kind_reuse(
    codec: SignedCursorCodec,
    claims: CursorClaims,
) -> None:
    catalog_expectation = CursorExpectation(
        kind="catalog",
        catalog_version=claims.catalog_version,
        dataset_id=None,
        schema_major=None,
        query_hash=claims.query_hash,
        policy_id=claims.policy_id,
        receipt_watermark=claims.receipt_watermark,
    )

    with pytest.raises(CursorMismatch, match="kind"):
        codec.decode(
            codec.encode(claims),
            expected=catalog_expectation,
            now=NOW,
        )


def test_cursor_rejects_cross_snapshot_reuse(
    codec: SignedCursorCodec,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    token = codec.encode(claims)

    with pytest.raises(CursorMismatch, match="receipt watermark"):
        codec.decode(
            token,
            expected=replace(expectation, receipt_watermark="new"),
            now=NOW,
        )


@pytest.mark.parametrize("secret", [b"", b"x" * 31, "not-bytes", bytearray(b"x" * 32)])
def test_direct_codec_construction_rejects_missing_weak_or_non_bytes_key(
    secret: object,
) -> None:
    with pytest.raises(CursorConfigurationError, match="signing key"):
        SignedCursorCodec(secret)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["", "x" * 31, "é" * 15])
def test_from_env_rejects_missing_empty_or_short_utf8_key(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY", value)

    with pytest.raises(CursorConfigurationError, match="signing key") as exc_info:
        SignedCursorCodec.from_env()
    if value:
        assert value not in str(exc_info.value)


def test_from_env_rejects_missing_key_without_a_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", raising=False)

    with pytest.raises(CursorConfigurationError, match="signing key"):
        SignedCursorCodec.from_env()


def test_from_env_accepts_exactly_32_utf8_bytes(
    monkeypatch: pytest.MonkeyPatch,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY", "é" * 16)
    codec = SignedCursorCodec.from_env()

    assert codec.decode(codec.encode(claims), expected=expectation, now=NOW) == claims


def test_from_env_accepts_private_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    claims: CursorClaims,
    expectation: CursorExpectation,
) -> None:
    key_file = tmp_path / "cursor.key"
    key_file.write_bytes(SECRET + b"\n")
    key_file.chmod(0o600)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(key_file))

    codec = SignedCursorCodec.from_env()

    assert codec.decode(codec.encode(claims), expected=expectation, now=NOW) == claims


def test_from_env_rejects_ambiguous_plaintext_and_file_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "cursor.key"
    key_file.write_bytes(SECRET)
    key_file.chmod(0o600)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY", SECRET.decode("ascii"))
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(key_file))

    with pytest.raises(CursorConfigurationError, match="ambiguous"):
        SignedCursorCodec.from_env()


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644])
def test_from_env_rejects_unsafe_private_file_mode_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
) -> None:
    key_file = tmp_path / "cursor.key"
    key_file.write_bytes(SECRET)
    key_file.chmod(mode)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(key_file))

    with pytest.raises(CursorConfigurationError, match="unavailable") as exc_info:
        SignedCursorCodec.from_env()
    assert SECRET.decode("ascii") not in str(exc_info.value)


def test_from_env_rejects_symlink_private_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.key"
    target.write_bytes(SECRET)
    target.chmod(0o600)
    linked = tmp_path / "cursor.key"
    linked.symlink_to(target)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(linked))

    with pytest.raises(CursorConfigurationError, match="unavailable"):
        SignedCursorCodec.from_env()


def test_from_env_rejects_symlink_private_file_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    key_file = private_dir / "cursor.key"
    key_file.write_bytes(SECRET)
    key_file.chmod(0o600)
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(private_dir, target_is_directory=True)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv(
        "TRADINGDATAS_CURSOR_SIGNING_KEY_FILE",
        str(linked_dir / "cursor.key"),
    )

    with pytest.raises(CursorConfigurationError, match="unavailable"):
        SignedCursorCodec.from_env()


def test_from_env_rejects_private_file_not_owned_by_service_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key_file = tmp_path / "cursor.key"
    key_file.write_bytes(SECRET)
    key_file.chmod(0o600)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(key_file))
    monkeypatch.setattr(query_cursor.os, "geteuid", lambda: key_file.stat().st_uid + 1)

    with pytest.raises(CursorConfigurationError, match="unavailable"):
        SignedCursorCodec.from_env()


@pytest.mark.parametrize("content", [b"", b"x" * 31, b"x" * 4097])
def test_from_env_rejects_empty_short_or_oversized_private_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: bytes,
) -> None:
    key_file = tmp_path / "cursor.key"
    key_file.write_bytes(content)
    key_file.chmod(0o600)
    monkeypatch.delenv("TRADINGDATAS_CURSOR_SIGNING_KEY", raising=False)
    monkeypatch.setenv("TRADINGDATAS_CURSOR_SIGNING_KEY_FILE", str(key_file))

    with pytest.raises(CursorConfigurationError, match="signing key"):
        SignedCursorCodec.from_env()


def test_from_env_maps_utf8_encoding_failure_to_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_cursor.os,
        "environ",
        {"TRADINGDATAS_CURSOR_SIGNING_KEY": "\ud800" * 32},
    )

    with pytest.raises(CursorConfigurationError, match="signing key"):
        SignedCursorCodec.from_env()


def test_missing_environment_key_does_not_break_module_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = os.environ.copy()
    environment.pop("TRADINGDATAS_CURSOR_SIGNING_KEY", None)

    completed = subprocess.run(
        [sys.executable, "-c", "import query_cursor"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_signed_cursor_module_does_not_import_legacy_pagination() -> None:
    source = Path(query_cursor.__file__).read_text(encoding="utf-8")

    assert "pagination" not in source
