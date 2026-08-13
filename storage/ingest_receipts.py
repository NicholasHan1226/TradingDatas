"""Versioned, immutable SQLite ingest receipts.

The existing ``market_ingest_runs`` table is the physical envelope.  Its
``notes`` column stores the canonical provider-neutral receipt payload.  Data
writers retain transaction ownership: receipt insert helpers perform a plain
insert and never commit or roll back.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from storage.schema_contract import require_clean_sqlite_authority_schema
from storage.sqlite_authority_lock import sqlite_authority_lock


RECEIPT_SCHEMA_VERSION = "tradingdatas.ingest_receipt.v1"
UNMAPPED_TUSHARE_ADAPTER_VERSION = "unresolved.v1"
VALIDATION_FANOUT_COVERAGE_INCOMPLETE = "validation_fanout_coverage_incomplete"
VALIDATION_RESPONSE_FIELD_COVERAGE = "response_field_coverage"
VALIDATION_RESPONSE_COMPLETENESS = "response_completeness"

_RECEIPT_STATUSES = frozenset({"success", "empty", "failed"})
_TERMINAL_STATUSES = frozenset({"empty", "failed"})
_ERROR_CODES = frozenset(
    {
        "config_error",
        "permission_denied",
        "provider_error",
        "rate_limited",
        "resource_budget",
        "storage_failed",
        "unmapped_dataset",
        "validation_failed",
        VALIDATION_FANOUT_COVERAGE_INCOMPLETE,
        VALIDATION_RESPONSE_FIELD_COVERAGE,
        VALIDATION_RESPONSE_COMPLETENESS,
    }
)
_SENSITIVE_NAME_FRAGMENTS = (
    "apikey",
    "authorization",
    "credential",
    "dbpath",
    "filepath",
    "password",
    "path",
    "secret",
    "sourcefile",
    "stacktrace",
    "token",
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_TABLE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PROVIDER_CALL_ORDINAL_WIDTH = 12
_PROVIDER_CALL_ORDINAL_LIMIT = 10**_PROVIDER_CALL_ORDINAL_WIDTH
_PROVIDER_CALL_ATTEMPT_PATTERN = re.compile(
    rf"(?P<root>.+):provider-call:"
    rf"(?P<call>[0-9]{{{_PROVIDER_CALL_ORDINAL_WIDTH}}}):"
    rf"retry:(?P<retry>[0-9]{{{_PROVIDER_CALL_ORDINAL_WIDTH}}})"
)
_SCHEDULE_PLAN_ATTEMPT_PATTERN = re.compile(
    rf"(?P<root>.+):schedule-plan:"
    rf"(?P<plan>[0-9]{{{_PROVIDER_CALL_ORDINAL_WIDTH}}})"
)
_SECRET_MATERIAL_PATTERN = re.compile(
    r"(?:\bbearer\s+\S+|"
    r"\b(?:access|refresh)?[_-]?token\s*[:=]|"
    r"\bapi[_-]?key\s*[:=]|"
    r"\b(?:authorization|credential|password|secret)\s*[:=]|"
    r"\b(?:sk|pk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_STACKTRACE_PATTERN = re.compile(
    r"(?:\btraceback\b|\bstack\s*trace\b|"
    r"\bexception\s+in\s+thread\b|\bcaused\s+by\s*:|"
    r"\bat\s+[\w.$]+\.[\w$<>]+\([^)]*\.java:\d+\)|"
    r"\bfile\s+[\"']?[^,]+[\"']?,\s*line\s+\d+|"
    r"\b[\w.-]+\.py:\d+(?:\s+in\b)?|"
    r"\b[\w.$-]+\.java:\d+\b)",
    re.IGNORECASE,
)
_FILE_URI_PATTERN = re.compile(r"(?<![A-Za-z0-9])file:(?=\S)", re.IGNORECASE)
_WINDOWS_DRIVE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:(?=\S)", re.IGNORECASE
)
_SQLITE_HEADER = b"SQLite format 3\x00"

_FileIdentity = tuple[int, int, int]


@dataclass(frozen=True)
class _SqlitePathBinding:
    canonical_path: Path
    parent_identities: tuple[_FileIdentity, ...]
    database_identity: _FileIdentity


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(
            f"{field_name} must be non-empty without surrounding whitespace"
        )
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _reject_sensitive_material(value: str, field_name: str) -> None:
    if (
        "/" in value
        or "\\" in value
        or _FILE_URI_PATTERN.search(value)
        or _WINDOWS_DRIVE_PATH_PATTERN.search(value)
        or _SECRET_MATERIAL_PATTERN.search(value)
        or _STACKTRACE_PATTERN.search(value)
    ):
        raise ValueError(
            f"{field_name} must not contain secret, path, or stacktrace material"
        )


def _require_public_text(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    _reject_sensitive_material(text, field_name)
    return text


def make_unmapped_tushare_dataset_id(provider_api: object) -> str:
    """Return the reserved non-dataset identity for one unmapped Tushare API."""

    api_name = _require_public_text(provider_api, "provider_api")
    digest = hashlib.sha256(api_name.encode("utf-8")).hexdigest()[:16]
    return f"unmapped.tushare.{digest}"


def _require_hash(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if _HASH_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return text


def _require_timestamp(value: object, field_name: str) -> str:
    text = _require_public_text(value, field_name)
    candidate = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return text


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _require_optional_nonnegative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_nonnegative_int(value, field_name)


@dataclass(frozen=True)
class ProviderCallAttemptIdentity:
    """Parsed identity for one physical provider call inside one execution."""

    root_attempt_id: str
    call_index: int
    retry_index: int

    def __post_init__(self) -> None:
        _require_public_text(self.root_attempt_id, "root_attempt_id")
        call_index = _require_nonnegative_int(self.call_index, "call_index")
        retry_index = _require_nonnegative_int(self.retry_index, "retry_index")
        if (
            call_index >= _PROVIDER_CALL_ORDINAL_LIMIT
            or retry_index >= _PROVIDER_CALL_ORDINAL_LIMIT
        ):
            raise ValueError("provider call ordinal exceeds the deterministic bound")
        if retry_index > call_index:
            raise ValueError("retry_index cannot exceed call_index")


@dataclass(frozen=True)
class SchedulePlanAttemptIdentity:
    """One scheduler-owned plan identity derived from a shared run root."""

    run_attempt_id: str
    plan_index: int

    def __post_init__(self) -> None:
        root = _require_public_text(self.run_attempt_id, "run_attempt_id")
        if ":schedule-plan:" in root or ":provider-call:" in root:
            raise ValueError("run_attempt_id contains a reserved attempt marker")
        index = _require_nonnegative_int(self.plan_index, "plan_index")
        if index >= _PROVIDER_CALL_ORDINAL_LIMIT:
            raise ValueError("schedule plan ordinal exceeds the deterministic bound")


def make_schedule_plan_attempt_id(
    run_attempt_id: object,
    *,
    plan_index: object,
) -> str:
    """Return one canonical plan root for a scheduler run."""

    identity = SchedulePlanAttemptIdentity(
        run_attempt_id=_require_public_text(run_attempt_id, "run_attempt_id"),
        plan_index=_require_nonnegative_int(plan_index, "plan_index"),
    )
    return (
        f"{identity.run_attempt_id}:schedule-plan:"
        f"{identity.plan_index:0{_PROVIDER_CALL_ORDINAL_WIDTH}d}"
    )


def parse_schedule_plan_attempt_id(
    attempt_id: object,
) -> SchedulePlanAttemptIdentity | None:
    """Parse a scheduler plan root; ordinary one-shot roots return ``None``."""

    text = _require_public_text(attempt_id, "attempt_id")
    match = _SCHEDULE_PLAN_ATTEMPT_PATTERN.fullmatch(text)
    if match is None:
        if ":schedule-plan:" in text:
            raise ValueError("schedule plan attempt identity is not canonical")
        return None
    identity = SchedulePlanAttemptIdentity(
        run_attempt_id=match.group("root"),
        plan_index=int(match.group("plan")),
    )
    if (
        make_schedule_plan_attempt_id(
            identity.run_attempt_id,
            plan_index=identity.plan_index,
        )
        != text
    ):
        raise ValueError("schedule plan attempt identity is not canonical")
    return identity


def make_provider_call_attempt_id(
    root_attempt_id: object,
    *,
    call_index: object,
    retry_index: object,
) -> str:
    """Return the canonical fixed-width identity for one physical call."""

    identity = ProviderCallAttemptIdentity(
        root_attempt_id=_require_public_text(root_attempt_id, "root_attempt_id"),
        call_index=_require_nonnegative_int(call_index, "call_index"),
        retry_index=_require_nonnegative_int(retry_index, "retry_index"),
    )
    return (
        f"{identity.root_attempt_id}:provider-call:"
        f"{identity.call_index:0{_PROVIDER_CALL_ORDINAL_WIDTH}d}:"
        f"retry:{identity.retry_index:0{_PROVIDER_CALL_ORDINAL_WIDTH}d}"
    )


def parse_provider_call_attempt_id(
    attempt_id: object,
) -> ProviderCallAttemptIdentity | None:
    """Parse a canonical physical-call identity; ordinary attempts return ``None``."""

    text = _require_public_text(attempt_id, "attempt_id")
    match = _PROVIDER_CALL_ATTEMPT_PATTERN.fullmatch(text)
    if match is None:
        if ":provider-call:" in text:
            raise ValueError("provider call attempt identity is not canonical")
        return None
    identity = ProviderCallAttemptIdentity(
        root_attempt_id=match.group("root"),
        call_index=int(match.group("call")),
        retry_index=int(match.group("retry")),
    )
    if (
        make_provider_call_attempt_id(
            identity.root_attempt_id,
            call_index=identity.call_index,
            retry_index=identity.retry_index,
        )
        != text
    ):
        raise ValueError("provider call attempt identity is not canonical")
    return identity


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("canonical receipt JSON must not contain duplicate keys")
        value[key] = item
    return value


def _utc_now() -> str:
    """Return one canonical UTC timestamp for the receipt write."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


ProviderRequestScalar = str | int | float | bool


def _reject_sensitive_parameter_name(value: str, field_name: str) -> None:
    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    if any(fragment in compact for fragment in _SENSITIVE_NAME_FRAGMENTS):
        raise ValueError(f"{field_name} must not contain sensitive parameter keys")


def _require_request_scalar(
    value: object,
    field_name: str,
) -> ProviderRequestScalar:
    if type(value) not in (str, int, float, bool):
        raise TypeError(f"{field_name} must be a provider request scalar")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class ProviderRequestIdentity:
    """Canonical identity for exactly one real provider call."""

    request_variant: Mapping[str, ProviderRequestScalar]
    fanout_parameter: str | None
    fanout_values: tuple[ProviderRequestScalar, ...]
    page_offset: int | None
    page_index: int
    cursor_contract_version: int | None = None
    frozen_universe_sha256: str | None = None
    batch_index: int | None = None
    batch_count: int | None = None
    batch_values_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_variant, Mapping):
            raise TypeError("request_variant must be a mapping")
        normalized_variant: dict[str, ProviderRequestScalar] = {}
        for key, value in self.request_variant.items():
            normalized_key = _require_text(key, "request_variant key")
            _reject_sensitive_parameter_name(normalized_key, "request_variant")
            normalized_variant[normalized_key] = _require_request_scalar(
                value,
                f"request_variant[{normalized_key}]",
            )
        object.__setattr__(
            self,
            "request_variant",
            MappingProxyType(dict(sorted(normalized_variant.items()))),
        )

        if self.fanout_parameter is not None:
            normalized_parameter = _require_text(
                self.fanout_parameter,
                "fanout_parameter",
            )
            _reject_sensitive_parameter_name(
                normalized_parameter,
                "fanout_parameter",
            )
            object.__setattr__(self, "fanout_parameter", normalized_parameter)

        if isinstance(self.fanout_values, (str, bytes)) or not isinstance(
            self.fanout_values,
            Sequence,
        ):
            raise TypeError("fanout_values must be a non-string sequence")
        object.__setattr__(
            self,
            "fanout_values",
            tuple(
                _require_request_scalar(value, f"fanout_values[{index}]")
                for index, value in enumerate(self.fanout_values)
            ),
        )

        if self.page_offset is not None and (type(self.page_offset) is not int):
            raise TypeError("page_offset must be an integer or None")
        _require_nonnegative_int(self.page_index, "page_index")
        cursor_values = (
            self.cursor_contract_version,
            self.frozen_universe_sha256,
            self.batch_index,
            self.batch_count,
            self.batch_values_sha256,
        )
        if all(value is None for value in cursor_values):
            return
        if self.cursor_contract_version != 2:
            raise ValueError("cursor_contract_version must be 2")
        if (
            type(self.frozen_universe_sha256) is not str
            or _HASH_PATTERN.fullmatch(self.frozen_universe_sha256) is None
            or type(self.batch_values_sha256) is not str
            or _HASH_PATTERN.fullmatch(self.batch_values_sha256) is None
        ):
            raise ValueError("cursor hashes must be SHA-256")
        _require_nonnegative_int(self.batch_index, "batch_index")
        if type(self.batch_count) is not int or self.batch_count <= 0:
            raise ValueError("batch_count must be positive")
        if self.batch_index >= self.batch_count:
            raise ValueError("batch_index must be less than batch_count")
        if any(value is None for value in cursor_values):
            raise ValueError("cursor identity is incomplete")

    @classmethod
    def trivial(cls) -> ProviderRequestIdentity:
        """Return the explicit identity for one unvaried, unpaged call."""

        return cls(
            request_variant={},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=0,
        )

    def canonical_payload(self) -> dict[str, object]:
        """Return the JSON-compatible identity bound into receipt evidence."""

        payload = {
            "fanout_parameter": self.fanout_parameter,
            "fanout_values": list(self.fanout_values),
            "page_index": self.page_index,
            "page_offset": self.page_offset,
            "request_variant": dict(self.request_variant),
        }
        if self.cursor_contract_version is not None:
            payload.update(
                {
                    "batch_count": self.batch_count,
                    "batch_index": self.batch_index,
                    "batch_values_sha256": self.batch_values_sha256,
                    "cursor_contract_version": self.cursor_contract_version,
                    "frozen_universe_sha256": self.frozen_universe_sha256,
                }
            )
        return payload


@dataclass(frozen=True)
class IngestContext:
    attempt_id: str
    dataset_id: str
    provider: str
    provider_api: str
    request_window: Mapping[str, str]
    config_hash: str | None
    adapter_version: str
    started_at: str
    data_through: str | None
    request_identity: ProviderRequestIdentity = field(
        default_factory=ProviderRequestIdentity.trivial
    )

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "dataset_id",
            "provider",
            "provider_api",
            "adapter_version",
        ):
            _require_public_text(getattr(self, field_name), field_name)
        if self.config_hash is not None:
            _require_hash(self.config_hash, "config_hash")
        _require_timestamp(self.started_at, "started_at")
        if self.data_through is not None:
            _require_public_text(self.data_through, "data_through")
        if not isinstance(self.request_identity, ProviderRequestIdentity):
            raise TypeError("request_identity must be ProviderRequestIdentity")
        if not isinstance(self.request_window, Mapping):
            raise TypeError("request_window must be a mapping")

        copied_window: dict[str, str] = {}
        for key, value in self.request_window.items():
            normalized_key = _require_public_text(key, "request_window key")
            compact_key = re.sub(r"[^a-z0-9]", "", normalized_key.casefold())
            if any(fragment in compact_key for fragment in _SENSITIVE_NAME_FRAGMENTS):
                raise ValueError("request_window must not contain sensitive fields")
            normalized_value = _require_public_text(
                value, f"request_window[{normalized_key}]"
            )
            copied_window[normalized_key] = normalized_value
        object.__setattr__(
            self,
            "request_window",
            MappingProxyType(dict(sorted(copied_window.items()))),
        )


@dataclass(frozen=True)
class IngestCounts:
    returned: int
    validated: int
    inserted: int | None
    updated: int | None
    unchanged: int | None
    rejected: int
    committed: int
    count_semantics: str

    def __post_init__(self) -> None:
        for field_name in ("returned", "validated", "rejected", "committed"):
            _require_nonnegative_int(getattr(self, field_name), field_name)
        for field_name in ("inserted", "updated", "unchanged"):
            _require_optional_nonnegative_int(getattr(self, field_name), field_name)
        _require_public_text(self.count_semantics, "count_semantics")

        if self.returned != self.validated + self.rejected:
            raise ValueError(
                "count conservation requires returned = validated + rejected"
            )
        if self.committed > self.validated:
            raise ValueError("count conservation requires committed <= validated")

        outcomes = (self.inserted, self.updated, self.unchanged)
        known_outcomes = [value is not None for value in outcomes]
        if any(known_outcomes) and not all(known_outcomes):
            raise ValueError("count outcomes must be all known or all None")
        if all(known_outcomes):
            known_total = sum(value for value in outcomes if value is not None)
            if known_total != self.committed:
                raise ValueError(
                    "count conservation requires inserted + updated + unchanged = committed"
                )


@dataclass(frozen=True)
class ReceiptEvidence:
    """Immutable pre-insert evidence for one canonical receipt row."""

    receipt_id: str
    started_at: str
    finished_at: str
    status: str
    source: str
    rows_read: int
    rows_written: int
    canonical_notes: bytes
    schema_version: str
    request_identity: ProviderRequestIdentity
    target_table: str | None
    transaction_index: int

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "started_at",
            "finished_at",
            "status",
            "source",
            "schema_version",
        ):
            if type(getattr(self, field_name)) is not str:
                raise TypeError(f"{field_name} must be a string")
        _require_public_text(self.receipt_id, "receipt_id")
        _require_timestamp(self.started_at, "started_at")
        _require_timestamp(self.finished_at, "finished_at")
        _require_status(self.status)
        _require_public_text(self.source, "source")
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise ValueError("schema_version is not recognized")
        if not isinstance(self.request_identity, ProviderRequestIdentity):
            raise TypeError("request_identity must be ProviderRequestIdentity")
        if self.target_table is not None and type(self.target_table) is not str:
            raise TypeError("target_table must be a string or None")
        _validated_target_table(self.target_table)
        if type(self.transaction_index) is not int:
            raise TypeError("transaction_index must be an integer")
        _require_nonnegative_int(self.transaction_index, "transaction_index")
        for field_name in ("rows_read", "rows_written"):
            value = getattr(self, field_name)
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
            _require_nonnegative_int(value, field_name)
        if self.rows_written > self.rows_read:
            raise ValueError("rows_written must not exceed rows_read")
        if type(self.canonical_notes) is not bytes:
            raise TypeError("canonical_notes must be bytes")

        try:
            notes_text = self.canonical_notes.decode("utf-8")
            payload = json.loads(
                notes_text,
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("canonical_notes must contain valid UTF-8 JSON") from exc
        if type(payload) is not dict:
            raise ValueError("canonical_notes must contain one JSON object")
        if _canonical_json(payload).encode("utf-8") != self.canonical_notes:
            raise ValueError("canonical_notes must use canonical JSON encoding")

        expected_payload_fields: tuple[tuple[str, object], ...] = (
            ("receipt_id", self.receipt_id),
            ("started_at", self.started_at),
            ("finished_at", self.finished_at),
            ("status", self.status),
            ("dataset_id", self.source),
            ("schema_version", self.schema_version),
            ("request_identity", self.request_identity.canonical_payload()),
            ("target_table", self.target_table),
            ("transaction_index", self.transaction_index),
        )
        missing = object()
        for field_name, expected in expected_payload_fields:
            observed = payload.get(field_name, missing)
            if type(observed) is not type(expected) or observed != expected:
                raise ValueError(
                    f"canonical_notes field {field_name} does not match evidence"
                )
        count_payload = payload.get("counts")
        if type(count_payload) is not dict:
            raise ValueError("canonical_notes counts must be an object")
        for field_name, expected in (
            ("returned", self.rows_read),
            ("committed", self.rows_written),
        ):
            observed = count_payload.get(field_name, missing)
            if type(observed) is not int or observed != expected:
                raise ValueError(
                    f"canonical_notes count {field_name} does not match evidence"
                )

    @property
    def sqlite_row(self) -> tuple[object, ...]:
        """Exact SQLite ``typeof`` and value tuple expected on readback."""

        return (
            "text",
            self.receipt_id,
            "text",
            self.started_at,
            "text",
            self.finished_at,
            "text",
            self.status,
            "text",
            self.source,
            "integer",
            self.rows_read,
            "integer",
            self.rows_written,
            "text",
            self.canonical_notes,
        )


@dataclass(frozen=True)
class IngestResult:
    status: str
    counts: IngestCounts
    receipt_ids: tuple[str, ...]
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        status = _require_status(self.status)
        if not isinstance(self.counts, IngestCounts):
            raise TypeError("counts must be IngestCounts")
        receipt_ids = _validated_receipt_ids(self.receipt_ids)
        errors = _validated_errors(self.errors)
        _validate_status_errors(status, errors)
        _validate_result_status_counts(status, self.counts)
        if status == "success" and not receipt_ids:
            raise ValueError("success result requires at least one receipt_id")
        object.__setattr__(self, "receipt_ids", receipt_ids)
        object.__setattr__(self, "errors", errors)


def _require_status(status: object) -> str:
    value = _require_text(status, "status")
    if value not in _RECEIPT_STATUSES:
        raise ValueError(f"status must be one of {sorted(_RECEIPT_STATUSES)}")
    return value


def _validated_errors(errors: Sequence[str]) -> tuple[str, ...]:
    if isinstance(errors, (str, bytes)) or not isinstance(errors, Sequence):
        raise TypeError("errors must be a sequence of structured error codes")
    normalized = tuple(errors)
    for error in normalized:
        code = _require_text(error, "error code")
        if code not in _ERROR_CODES:
            raise ValueError("error code is not recognized")
    if len(normalized) != len(set(normalized)):
        raise ValueError("error codes must not contain duplicates")
    return normalized


def _validated_receipt_ids(receipt_ids: object) -> tuple[str, ...]:
    if isinstance(receipt_ids, (str, bytes)) or not isinstance(receipt_ids, Sequence):
        raise TypeError("receipt_ids must be a non-string sequence")
    normalized = tuple(receipt_ids)
    for receipt_id in normalized:
        _require_public_text(receipt_id, "receipt_id")
    return normalized


def _validate_status_errors(status: str, errors: tuple[str, ...]) -> None:
    if status == "failed" and not errors:
        raise ValueError("failed status requires at least one structured error code")
    if status != "failed" and errors:
        raise ValueError(f"{status} status must not contain errors")


def _validated_target_table(target_table: str | None) -> str | None:
    if target_table is None:
        return None
    value = _require_text(target_table, "target_table")
    if _TABLE_PATTERN.fullmatch(value) is None:
        raise ValueError("target_table must be a bare SQLite identifier")
    return value


def _validate_status_counts_and_target(
    status: str,
    counts: IngestCounts,
    target_table: str | None,
) -> None:
    _validate_status_counts(status, counts)
    if status == "success" and target_table is None:
        raise ValueError("success receipt requires target_table")
    if status in _TERMINAL_STATUSES and target_table is not None:
        raise ValueError(f"{status} receipt must not identify a target_table")


def _validate_status_counts(status: str, counts: IngestCounts) -> None:
    numeric_counts = (
        counts.returned,
        counts.validated,
        counts.inserted,
        counts.updated,
        counts.unchanged,
        counts.rejected,
        counts.committed,
    )
    if status == "success":
        if counts.committed == 0 or counts.committed != counts.validated:
            raise ValueError(
                "success receipt requires non-zero committed = validated counts"
            )
    elif status in _TERMINAL_STATUSES:
        if any(value != 0 for value in numeric_counts):
            raise ValueError(f"{status} receipt requires explicit integer zero counts")


def _validate_result_status_counts(status: str, counts: IngestCounts) -> None:
    """Validate an aggregate result without weakening singular receipts."""

    if (
        status == "failed"
        and counts.count_semantics == "aggregate_partial_physical_call_transactions"
    ):
        if counts.committed == 0 or counts.committed != counts.validated:
            raise ValueError(
                "partial aggregate failure requires non-zero committed = validated"
            )
        if any(
            value is None
            for value in (counts.inserted, counts.updated, counts.unchanged)
        ):
            raise ValueError("partial aggregate failure requires exact row outcomes")
        return
    _validate_status_counts(status, counts)


def _canonical_db_path(db_path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(db_path)))


def _file_identity(metadata: os.stat_result) -> _FileIdentity:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _validated_parent_chain(db_path: Path) -> tuple[_FileIdentity, ...]:
    identities: list[_FileIdentity] = []
    for parent in reversed(db_path.parents):
        try:
            metadata = parent.lstat()
        except FileNotFoundError:
            raise FileNotFoundError("db_path parent chain must already exist") from None
        except OSError:
            raise ValueError(
                "db_path parent chain must contain only directories"
            ) from None
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("db_path parent chain must not contain symbolic links")
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("db_path parent chain must contain only directories")
        identities.append(_file_identity(metadata))
    return tuple(identities)


def _validated_sqlite_file_identity(db_path: Path) -> _FileIdentity:
    try:
        metadata = db_path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError("db_path must already exist") from None
    except OSError:
        raise ValueError(
            "db_path must be an existing regular SQLite database"
        ) from None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(
            "db_path must be a regular SQLite database, not a symbolic link"
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("db_path must be a regular SQLite database")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError("platform cannot validate db_path without following links")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(db_path, flags)
    except FileNotFoundError:
        raise FileNotFoundError("db_path must already exist") from None
    except OSError:
        raise ValueError("db_path must be a readable regular SQLite database") from None
    try:
        opened_metadata = os.fstat(descriptor)
        opened_identity = _file_identity(opened_metadata)
        if opened_identity != _file_identity(metadata):
            raise ValueError("db_path changed while it was being validated")
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise ValueError("db_path must be a regular SQLite database")
        header = os.read(descriptor, len(_SQLITE_HEADER))
    finally:
        os.close(descriptor)
    if header != _SQLITE_HEADER:
        raise ValueError("db_path must be a regular SQLite database")
    return opened_identity


def validated_existing_sqlite_binding(db_path: Path) -> _SqlitePathBinding:
    canonical_path = _canonical_db_path(db_path)
    parent_identities = _validated_parent_chain(canonical_path)
    database_identity = _validated_sqlite_file_identity(canonical_path)

    if parent_identities != _validated_parent_chain(canonical_path):
        raise RuntimeError("db_path binding changed while it was being validated")
    if database_identity != _validated_sqlite_file_identity(canonical_path):
        raise RuntimeError("db_path binding changed while it was being validated")

    return _SqlitePathBinding(
        canonical_path=canonical_path,
        parent_identities=parent_identities,
        database_identity=database_identity,
    )


def require_unchanged_sqlite_binding(expected: _SqlitePathBinding) -> None:
    try:
        observed = validated_existing_sqlite_binding(expected.canonical_path)
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError(
            "db_path binding changed during terminal receipt write"
        ) from None
    if observed != expected:
        raise RuntimeError("db_path binding changed during terminal receipt write")


def make_receipt_id(
    context: IngestContext,
    target_table: str | None,
    transaction_index: int,
) -> str:
    """Derive a stable receipt ID from the attempt/transaction identity."""

    if not isinstance(context, IngestContext):
        raise TypeError("context must be IngestContext")
    table = _validated_target_table(target_table)
    index = _require_nonnegative_int(transaction_index, "transaction_index")
    identity = {
        "attempt_id": context.attempt_id,
        "request_identity": context.request_identity.canonical_payload(),
        "target_table": table,
        "transaction_index": index,
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"receipt:{digest}"


def _receipt_payload(
    *,
    receipt_id: str,
    context: IngestContext,
    target_table: str | None,
    transaction_index: int,
    status: str,
    counts: IngestCounts,
    errors: tuple[str, ...],
    payload_fingerprint: str,
    finished_at: str,
) -> dict[str, object]:
    return {
        "adapter_version": context.adapter_version,
        "attempt_id": context.attempt_id,
        "config_hash": context.config_hash,
        "counts": {
            field.name: getattr(counts, field.name) for field in fields(IngestCounts)
        },
        "data_through": context.data_through,
        "dataset_id": context.dataset_id,
        "errors": list(errors),
        "finished_at": finished_at,
        "payload_fingerprint": payload_fingerprint,
        "provider": context.provider,
        "provider_api": context.provider_api,
        "receipt_id": receipt_id,
        "request_identity": context.request_identity.canonical_payload(),
        "request_window": dict(context.request_window),
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "started_at": context.started_at,
        "status": status,
        "target_table": target_table,
        "transaction_index": transaction_index,
    }


def insert_ingest_receipt_with_evidence(
    conn: sqlite3.Connection,
    *,
    context: IngestContext,
    target_table: str | None,
    transaction_index: int,
    status: str,
    counts: IngestCounts,
    errors: Sequence[str],
    payload_fingerprint: str,
) -> ReceiptEvidence:
    """Prebuild immutable evidence, then insert without owning the transaction."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(context, IngestContext):
        raise TypeError("context must be IngestContext")
    if not isinstance(counts, IngestCounts):
        raise TypeError("counts must be IngestCounts")

    normalized_status = _require_status(status)
    normalized_errors = _validated_errors(errors)
    _validate_status_errors(normalized_status, normalized_errors)
    if context.config_hash is None:
        if normalized_status != "failed":
            raise ValueError("config_hash is required for success and empty receipts")
        if normalized_errors != ("config_error",):
            raise ValueError(
                "missing config_hash requires the config_error terminal code"
            )
    table = _validated_target_table(target_table)
    _validate_status_counts_and_target(normalized_status, counts, table)
    index = _require_nonnegative_int(transaction_index, "transaction_index")
    fingerprint = _require_hash(payload_fingerprint, "payload_fingerprint")
    receipt_id = make_receipt_id(context, table, index)
    finished_at = _require_timestamp(_utc_now(), "finished_at")
    payload = _receipt_payload(
        receipt_id=receipt_id,
        context=context,
        target_table=table,
        transaction_index=index,
        status=normalized_status,
        counts=counts,
        errors=normalized_errors,
        payload_fingerprint=fingerprint,
        finished_at=finished_at,
    )
    evidence = ReceiptEvidence(
        receipt_id=receipt_id,
        started_at=context.started_at,
        finished_at=finished_at,
        status=normalized_status,
        source=context.dataset_id,
        rows_read=counts.returned,
        rows_written=counts.committed,
        canonical_notes=_canonical_json(payload).encode("utf-8"),
        schema_version=RECEIPT_SCHEMA_VERSION,
        request_identity=context.request_identity,
        target_table=table,
        transaction_index=index,
    )

    cursor = conn.execute(
        """INSERT INTO market_ingest_runs
           (run_id, started_at, finished_at, status, source,
            rows_read, rows_written, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            receipt_id,
            context.started_at,
            finished_at,
            normalized_status,
            context.dataset_id,
            counts.returned,
            counts.committed,
            evidence.canonical_notes.decode("utf-8"),
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("ingest receipt insert did not affect exactly one row")
    return evidence


def require_receipt_evidence_readback(
    conn: sqlite3.Connection,
    evidence: ReceiptEvidence,
) -> None:
    """Require one inserted receipt to read back byte-for-byte in-transaction."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(evidence, ReceiptEvidence):
        raise TypeError("evidence must be ReceiptEvidence")
    row = conn.execute(
        """SELECT typeof(run_id), run_id,
                  typeof(started_at), started_at,
                  typeof(finished_at), finished_at,
                  typeof(status), status,
                  typeof(source), source,
                  typeof(rows_read), rows_read,
                  typeof(rows_written), rows_written,
                  typeof(notes), CAST(notes AS BLOB)
           FROM market_ingest_runs WHERE run_id = ?""",
        (evidence.receipt_id,),
    ).fetchone()
    if row is None or tuple(row) != evidence.sqlite_row:
        raise RuntimeError("ingest receipt transaction readback is inconsistent")


def insert_ingest_receipt(
    conn: sqlite3.Connection,
    *,
    context: IngestContext,
    target_table: str | None,
    transaction_index: int,
    status: str,
    counts: IngestCounts,
    errors: Sequence[str],
    payload_fingerprint: str,
) -> str:
    """Insert one receipt and return its canonical public identifier."""

    evidence = insert_ingest_receipt_with_evidence(
        conn,
        context=context,
        target_table=target_table,
        transaction_index=transaction_index,
        status=status,
        counts=counts,
        errors=errors,
        payload_fingerprint=payload_fingerprint,
    )
    return evidence.receipt_id


def write_terminal_receipt(
    db_path: Path,
    *,
    context: IngestContext,
    status: str,
    errors: Sequence[str],
) -> IngestResult:
    """Commit one ``empty`` or ``failed`` receipt-only transaction."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    normalized_status = _require_status(status)
    if normalized_status not in _TERMINAL_STATUSES:
        raise ValueError("terminal receipt status must be empty or failed")
    normalized_errors = _validated_errors(errors)
    _validate_status_errors(normalized_status, normalized_errors)
    counts = IngestCounts(
        returned=0,
        validated=0,
        inserted=0,
        updated=0,
        unchanged=0,
        rejected=0,
        committed=0,
        count_semantics="terminal_no_data_transaction",
    )
    empty_fingerprint = hashlib.sha256(b"").hexdigest()

    initial_db_binding = validated_existing_sqlite_binding(db_path)
    with sqlite_authority_lock(
        db_path,
        mode="exclusive",
        create=True,
        timeout=180.0,
    ) as authority_lease:
        db_binding = validated_existing_sqlite_binding(db_path)
        if db_binding != initial_db_binding:
            raise RuntimeError("db_path binding changed during terminal receipt write")
        conn = sqlite3.connect(
            f"{db_binding.canonical_path.as_uri()}?mode=rw",
            uri=True,
        )
        try:
            conn.execute("BEGIN IMMEDIATE")
            require_clean_sqlite_authority_schema(conn)
            require_unchanged_sqlite_binding(db_binding)
            evidence = insert_ingest_receipt_with_evidence(
                conn,
                context=context,
                target_table=None,
                transaction_index=0,
                status=normalized_status,
                counts=counts,
                errors=normalized_errors,
                payload_fingerprint=empty_fingerprint,
            )
            receipt_id = evidence.receipt_id
            require_receipt_evidence_readback(conn, evidence)
            require_unchanged_sqlite_binding(db_binding)
            authority_lease.validate()
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except BaseException:
                pass
            raise
        finally:
            conn.close()

    return IngestResult(
        status=normalized_status,
        counts=counts,
        receipt_ids=(receipt_id,),
        errors=normalized_errors,
    )
