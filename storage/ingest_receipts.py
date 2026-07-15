"""Versioned, immutable SQLite ingest receipts.

The existing ``market_ingest_runs`` table is the physical envelope.  Its
``notes`` column stores the canonical provider-neutral receipt payload.  Data
writers retain transaction ownership: :func:`insert_ingest_receipt` performs a
plain insert and never commits or rolls back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType


RECEIPT_SCHEMA_VERSION = "sharedsignals.ingest_receipt.v1"

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


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _utc_now() -> str:
    """Return one canonical UTC timestamp for the receipt write."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class IngestContext:
    attempt_id: str
    dataset_id: str
    provider: str
    provider_api: str
    request_window: Mapping[str, str]
    config_hash: str
    adapter_version: str
    started_at: str
    data_through: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "attempt_id",
            "dataset_id",
            "provider",
            "provider_api",
            "adapter_version",
        ):
            _require_public_text(getattr(self, field_name), field_name)
        _require_hash(self.config_hash, "config_hash")
        _require_timestamp(self.started_at, "started_at")
        if self.data_through is not None:
            _require_public_text(self.data_through, "data_through")
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
        _validate_status_counts(status, self.counts)
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


def _validated_existing_sqlite_binding(db_path: Path) -> _SqlitePathBinding:
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


def _require_unchanged_sqlite_binding(expected: _SqlitePathBinding) -> None:
    try:
        observed = _validated_existing_sqlite_binding(expected.canonical_path)
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
        "request_window": dict(context.request_window),
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "started_at": context.started_at,
        "status": status,
        "target_table": target_table,
        "transaction_index": transaction_index,
    }


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
    """Insert one receipt without committing or rolling back its transaction."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(context, IngestContext):
        raise TypeError("context must be IngestContext")
    if not isinstance(counts, IngestCounts):
        raise TypeError("counts must be IngestCounts")

    normalized_status = _require_status(status)
    normalized_errors = _validated_errors(errors)
    _validate_status_errors(normalized_status, normalized_errors)
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

    conn.execute(
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
            _canonical_json(payload),
        ),
    )
    return receipt_id


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

    db_binding = _validated_existing_sqlite_binding(db_path)
    conn = sqlite3.connect(f"{db_binding.canonical_path.as_uri()}?mode=rw", uri=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _require_unchanged_sqlite_binding(db_binding)
        receipt_id = insert_ingest_receipt(
            conn,
            context=context,
            target_table=None,
            transaction_index=0,
            status=normalized_status,
            counts=counts,
            errors=normalized_errors,
            payload_fingerprint=empty_fingerprint,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return IngestResult(
        status=normalized_status,
        counts=counts,
        receipt_ids=(receipt_id,),
        errors=normalized_errors,
    )
