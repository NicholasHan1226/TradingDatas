"""Versioned signed keyset cursor contracts for the provider-neutral data plane."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import math
import os
import re


_CURSOR_VERSION = 1
_SIGNING_KEY_ENV = "SHAREDSIGNALS_CURSOR_SIGNING_KEY"
_MINIMUM_SIGNING_KEY_BYTES = 32
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z", re.ASCII)
_KINDS = frozenset({"catalog", "query"})
_WIRE_KEYS = frozenset(
    {
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
)


class InvalidCursor(ValueError):
    """A malformed, unverifiable, unsupported, or expired cursor (future HTTP 400)."""


class CursorMismatch(ValueError):
    """A valid cursor bound to a different request context (future HTTP 409)."""


class CursorConfigurationError(RuntimeError):
    """Signing-key or validation-clock configuration is unavailable (future 503)."""


def _canonical_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be a canonical non-empty string")
    return value


def _validate_dataset_id(value: object) -> str:
    dataset_id = _canonical_non_empty_string(value, "dataset_id")
    if _DATASET_ID_RE.fullmatch(dataset_id) is None:
        raise ValueError("dataset_id must be a canonical dataset identifier")
    return dataset_id


def _validate_bindings(
    *,
    kind: object,
    catalog_version: object,
    dataset_id: object,
    schema_major: object,
    query_hash: object,
    policy_id: object,
    receipt_watermark: object,
) -> None:
    if type(kind) is not str or kind not in _KINDS:
        raise ValueError("kind must be catalog or query")
    _canonical_non_empty_string(catalog_version, "catalog_version")
    _canonical_non_empty_string(query_hash, "query_hash")
    _canonical_non_empty_string(policy_id, "policy_id")
    _canonical_non_empty_string(receipt_watermark, "receipt_watermark")

    if kind == "catalog":
        if dataset_id is not None or schema_major is not None:
            raise ValueError("catalog cursor dataset and schema must be null")
        return

    _validate_dataset_id(dataset_id)
    if type(schema_major) is not int or schema_major <= 0:
        raise ValueError("schema_major must be a positive native integer")


def _validate_sort_key(sort_key: object) -> tuple[object, ...]:
    if type(sort_key) is not tuple:
        raise ValueError("sort_key must be a tuple")
    for value in sort_key:
        if value is None or type(value) in {str, int, bool}:
            continue
        if type(value) is float and math.isfinite(value):
            continue
        raise ValueError("sort_key values must be finite JSON scalars")
    return sort_key


@dataclass(frozen=True)
class CursorClaims:
    kind: str
    catalog_version: str
    dataset_id: str | None
    schema_major: int | None
    query_hash: str
    policy_id: str
    receipt_watermark: str
    sort_key: tuple[object, ...]
    expires_at: int

    def __post_init__(self) -> None:
        _validate_bindings(
            kind=self.kind,
            catalog_version=self.catalog_version,
            dataset_id=self.dataset_id,
            schema_major=self.schema_major,
            query_hash=self.query_hash,
            policy_id=self.policy_id,
            receipt_watermark=self.receipt_watermark,
        )
        _validate_sort_key(self.sort_key)
        if type(self.expires_at) is not int:
            raise ValueError("expires_at must be a native integer")


@dataclass(frozen=True)
class CursorExpectation:
    kind: str
    catalog_version: str
    dataset_id: str | None
    schema_major: int | None
    query_hash: str
    policy_id: str
    receipt_watermark: str

    def __post_init__(self) -> None:
        _validate_bindings(
            kind=self.kind,
            catalog_version=self.catalog_version,
            dataset_id=self.dataset_id,
            schema_major=self.schema_major,
            query_hash=self.query_hash,
            policy_id=self.policy_id,
            receipt_watermark=self.receipt_watermark,
        )


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_non_finite_constant(_value: str) -> None:
    raise ValueError


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode_strict(segment: str) -> bytes:
    if _SEGMENT_RE.fullmatch(segment) is None:
        raise InvalidCursor("cursor token is malformed")
    try:
        raw = base64.b64decode(
            segment + "=" * (-len(segment) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor("cursor token is malformed") from exc
    if _b64url_encode(raw) != segment:
        raise InvalidCursor("cursor token is malformed")
    return raw


def _validated_claims(claims: CursorClaims) -> CursorClaims:
    if type(claims) is not CursorClaims:
        raise TypeError("claims must be CursorClaims")
    return CursorClaims(
        kind=claims.kind,
        catalog_version=claims.catalog_version,
        dataset_id=claims.dataset_id,
        schema_major=claims.schema_major,
        query_hash=claims.query_hash,
        policy_id=claims.policy_id,
        receipt_watermark=claims.receipt_watermark,
        sort_key=claims.sort_key,
        expires_at=claims.expires_at,
    )


def _claims_payload(claims: CursorClaims) -> dict[str, object]:
    return {
        "v": _CURSOR_VERSION,
        "kind": claims.kind,
        "catalog_version": claims.catalog_version,
        "dataset_id": claims.dataset_id,
        "schema_major": claims.schema_major,
        "query_hash": claims.query_hash,
        "policy_id": claims.policy_id,
        "receipt_watermark": claims.receipt_watermark,
        "sort_key": list(claims.sort_key),
        "expires_at": claims.expires_at,
    }


def _parse_claims_payload(raw_payload: bytes) -> CursorClaims:
    try:
        text = raw_payload.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as exc:
        raise InvalidCursor("cursor payload is invalid") from exc
    if type(payload) is not dict:
        raise InvalidCursor("cursor payload is invalid")
    try:
        canonical = _canonical_json_bytes(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidCursor("cursor payload is invalid") from exc
    if canonical != raw_payload:
        raise InvalidCursor("cursor payload is not canonical")
    if set(payload) != _WIRE_KEYS:
        raise InvalidCursor("cursor payload schema is invalid")
    if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
        raise InvalidCursor("cursor version is unsupported")
    if type(payload["sort_key"]) is not list:
        raise InvalidCursor("cursor payload schema is invalid")
    try:
        return CursorClaims(
            kind=payload["kind"],
            catalog_version=payload["catalog_version"],
            dataset_id=payload["dataset_id"],
            schema_major=payload["schema_major"],
            query_hash=payload["query_hash"],
            policy_id=payload["policy_id"],
            receipt_watermark=payload["receipt_watermark"],
            sort_key=tuple(payload["sort_key"]),
            expires_at=payload["expires_at"],
        )
    except (TypeError, ValueError) as exc:
        raise InvalidCursor("cursor payload schema is invalid") from exc


def _floor_aware_timestamp(now: datetime) -> int:
    if type(now) is not datetime or now.tzinfo is None:
        raise CursorConfigurationError("cursor validation clock is invalid")
    try:
        if now.utcoffset() is None:
            raise CursorConfigurationError("cursor validation clock is invalid")
        return math.floor(now.timestamp())
    except CursorConfigurationError:
        raise
    except (OverflowError, OSError, ValueError) as exc:
        raise CursorConfigurationError("cursor validation clock is invalid") from exc


_MISMATCH_FIELDS = (
    ("kind", "cursor kind mismatch"),
    ("catalog_version", "cursor catalog version mismatch"),
    ("dataset_id", "cursor dataset mismatch"),
    ("schema_major", "cursor schema major mismatch"),
    ("query_hash", "cursor query mismatch"),
    ("policy_id", "cursor policy mismatch"),
    ("receipt_watermark", "cursor receipt watermark mismatch"),
)


class SignedCursorCodec:
    """Encode and validate one canonical HMAC-SHA256 cursor version."""

    __slots__ = ("_signing_key",)

    def __init__(self, signing_key: bytes) -> None:
        if (
            type(signing_key) is not bytes
            or len(signing_key) < _MINIMUM_SIGNING_KEY_BYTES
        ):
            raise CursorConfigurationError("cursor signing key is unavailable")
        self._signing_key = signing_key

    @classmethod
    def from_env(cls) -> SignedCursorCodec:
        value = os.environ.get(_SIGNING_KEY_ENV)
        if type(value) is not str or not value:
            raise CursorConfigurationError("cursor signing key is unavailable")
        try:
            signing_key = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CursorConfigurationError("cursor signing key is unavailable") from exc
        return cls(signing_key)

    def encode(self, claims: CursorClaims) -> str:
        validated = _validated_claims(claims)
        payload = _canonical_json_bytes(_claims_payload(validated))
        signature = hmac.new(
            self._signing_key,
            payload,
            hashlib.sha256,
        ).digest()
        return f"{_b64url_encode(payload)}.{_b64url_encode(signature)}"

    def decode(
        self,
        token: str,
        *,
        expected: CursorExpectation,
        now: datetime,
    ) -> CursorClaims:
        if type(token) is not str or token.count(".") != 1:
            raise InvalidCursor("cursor token is malformed")
        payload_segment, signature_segment = token.split(".")
        if not payload_segment or not signature_segment:
            raise InvalidCursor("cursor token is malformed")
        raw_payload = _b64url_decode_strict(payload_segment)
        signature = _b64url_decode_strict(signature_segment)
        if len(signature) != hashlib.sha256().digest_size:
            raise InvalidCursor("cursor token is malformed")

        expected_signature = hmac.new(
            self._signing_key,
            raw_payload,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidCursor("cursor signature is invalid")

        claims = _parse_claims_payload(raw_payload)
        if claims.expires_at <= _floor_aware_timestamp(now):
            raise InvalidCursor("cursor is expired")

        if type(expected) is not CursorExpectation:
            raise TypeError("expected must be CursorExpectation")
        for field, message in _MISMATCH_FIELDS:
            if getattr(claims, field) != getattr(expected, field):
                raise CursorMismatch(message)
        return claims
