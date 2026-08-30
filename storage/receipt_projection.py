"""Project dataset runtime state from immutable SQLite ingest receipts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import struct
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dataset_registry import DatasetDefinition, DatasetRegistry, ProviderBinding
from provider_ingest_contract import provider_ingest_config_hash
from storage.ingest_receipts import (
    RECEIPT_SCHEMA_VERSION,
    UNMAPPED_TUSHARE_ADAPTER_VERSION,
    VALIDATION_FANOUT_COVERAGE_INCOMPLETE,
    VALIDATION_RESPONSE_FIELD_COVERAGE,
    VALIDATION_RESPONSE_COMPLETENESS,
    IngestContext,
    IngestCounts,
    ProviderRequestIdentity,
    make_unmapped_tushare_dataset_id,
    make_receipt_id,
    parse_provider_call_attempt_id,
    parse_schedule_plan_attempt_id,
)
from storage.schema_contract import (
    PROVIDER_DATASET_ROWS_COLUMNS,
    PROVIDER_DATASET_ROWS_INDEX_COLUMNS,
    PROVIDER_DATASET_ROWS_TABLE,
    TYPE_MAP,
    get_table,
)
from storage.sqlite_authority_lock import (
    SqliteAuthorityLockError,
    sqlite_authority_lock,
)


RuntimeState = Literal[
    "success",
    "empty",
    "unobserved",
    "paused",
    "failed",
    "stale",
]

_RECEIPT_PAYLOAD_KEYS = frozenset(
    {
        "adapter_version",
        "attempt_id",
        "config_hash",
        "counts",
        "data_through",
        "dataset_id",
        "errors",
        "finished_at",
        "payload_fingerprint",
        "provider",
        "provider_api",
        "receipt_id",
        "request_identity",
        "request_window",
        "schema_version",
        "started_at",
        "status",
        "target_table",
        "transaction_index",
    }
)
_RECEIPT_PAYLOAD_MARKERS = frozenset(
    {
        "adapter_version",
        "attempt_id",
        "counts",
        "data_through",
        "dataset_id",
        "payload_fingerprint",
        "provider_api",
        "receipt_id",
        "request_identity",
        "request_window",
        "schema_version",
        "target_table",
        "transaction_index",
    }
)
_COUNT_KEYS = frozenset(
    {
        "returned",
        "validated",
        "inserted",
        "updated",
        "unchanged",
        "rejected",
        "committed",
        "count_semantics",
    }
)
_ERROR_CODES = frozenset(
    {
        "config_error",
        "permission_denied",
        "provider_error",
        "rate_limited",
        "resource_budget",
        "storage_failed",
        "transport_error",
        "unmapped_dataset",
        "validation_failed",
        VALIDATION_FANOUT_COVERAGE_INCOMPLETE,
        VALIDATION_RESPONSE_FIELD_COVERAGE,
        VALIDATION_RESPONSE_COMPLETENESS,
    }
)
_MAX_INGEST_RUN_SCAN_ROWS = 400_000
# Catalog starts from 100 recent receipts per source, not the full append-only
# history. This is a seed window, not a complete-execution guarantee: full
# windows require sibling lookup for every recognizable selected execution,
# sharing the global raw-read budget (including duplicate reads).
_MAX_INGEST_RUN_SCAN_ROWS_PER_DATASET = 100
_RECEIPT_QUERY = """
SELECT typeof(run_id), run_id,
       typeof(started_at), started_at,
       typeof(finished_at), finished_at,
       typeof(status), status,
       typeof(source), source,
       typeof(rows_read), rows_read,
       typeof(rows_written), rows_written,
       typeof(notes), notes
FROM market_ingest_runs
LIMIT ?
"""
_RECEIPT_QUERY_BY_DATASET = _RECEIPT_QUERY.replace(
    "FROM market_ingest_runs\nLIMIT ?",
    "FROM market_ingest_runs\nWHERE source = ?\nLIMIT ?",
)
# The catalog projection scans the most recent ``_MAX_INGEST_RUN_SCAN_ROWS_PER_DATASET``
# receipts per ``source`` instead of the whole append-only table.  The column
# expressions stay identical to ``_RECEIPT_QUERY`` so ``_classify_ingest_run_row``
# keeps the same positional contract; only the row source changes.
_RECENT_INGEST_RUN_QUERY = _RECEIPT_QUERY.replace(
    "FROM market_ingest_runs\nLIMIT ?",
    """FROM (
    SELECT run_id, started_at, finished_at, status, source, rows_read,
           rows_written, notes,
           ROW_NUMBER() OVER (
               PARTITION BY source
               ORDER BY finished_at DESC, rowid DESC
           ) AS rn
    FROM market_ingest_runs
)
WHERE rn <= ?""",
)


def _receipt_query_by_run_ids(receipt_ids: tuple[str, ...]) -> str:
    if not receipt_ids:
        raise ValueError("receipt_ids must be non-empty")
    placeholders = ",".join("?" for _ in receipt_ids)
    return _RECEIPT_QUERY.replace(
        "FROM market_ingest_runs\nLIMIT ?",
        f"FROM market_ingest_runs\nWHERE run_id IN ({placeholders})",
    )


_INGEST_RUN_CONTRACT = get_table("market_ingest_runs")
_INGEST_RUN_PRIMARY_KEY_POSITIONS = {
    name: index for index, name in enumerate(_INGEST_RUN_CONTRACT.primary_key, start=1)
}
_EXPECTED_INGEST_RUN_TABLE_INFO = tuple(
    (
        index,
        column.name,
        TYPE_MAP["sqlite"][column.logical_type],
        int(not column.nullable),
        None,
        _INGEST_RUN_PRIMARY_KEY_POSITIONS.get(column.name, 0),
        0,
    )
    for index, column in enumerate(_INGEST_RUN_CONTRACT.columns)
)
_EXPECTED_PROVIDER_DATASET_ROWS_TABLE_INFO = tuple(
    (
        index,
        name,
        sqlite_type,
        int(not nullable),
        default,
        primary_key_position,
        0,
    )
    for index, (
        name,
        sqlite_type,
        nullable,
        default,
        primary_key_position,
    ) in enumerate(PROVIDER_DATASET_ROWS_COLUMNS)
)
_SQLITE_HEADER = b"SQLite format 3\x00"
_SNAPSHOT_READER_LOCK_TIMEOUT_SECONDS = 10.0
_SNAPSHOT_READER_MAX_ATTEMPTS = 5
_FileIdentity = tuple[int, int, int]
_IngestRunRow = tuple[object, ...]


class RuntimeProjectionError(RuntimeError):
    """The SQLite receipt authority could not be read safely."""


@dataclass(frozen=True)
class UnattributedReceiptAnomaly:
    """One receipt row that no registered dataset claims.

    Emitted by the global tripwire surface instead of failing every dataset's
    projection; ``reason`` uses the same vocabulary as per-dataset validation.
    """

    receipt_id: str | None
    source: str | None
    reason: str
    observed_at: str | None


@dataclass(frozen=True)
class UnattributedReceiptHealth:
    """Global tamper-tripwire health over rows outside the known dataset set."""

    scanned_at: str
    anomalies: tuple[UnattributedReceiptAnomaly, ...]
    benign_tombstones: int


@dataclass(frozen=True)
class DatasetRuntimeProjection:
    dataset_id: str
    state: RuntimeState
    degraded: bool
    data_through: str | None
    observed_at: str | None
    receipt_id: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DatasetRuntimeEvidence:
    projection: DatasetRuntimeProjection
    current_receipt_status: str | None
    current_providers: tuple[str, ...]
    last_success_receipt_id: str | None
    last_success_providers: tuple[str, ...]
    last_success_data_through: str | None
    current_provider_config_hashes: tuple[tuple[str, str], ...] = ()
    last_success_provider_config_hashes: tuple[tuple[str, str], ...] = ()
    current_receipt_ids: tuple[str, ...] = ()
    last_success_receipt_ids: tuple[str, ...] = ()
    as_of_success_receipt_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.projection, DatasetRuntimeProjection):
            raise TypeError("projection must be DatasetRuntimeProjection")
        if self.current_receipt_status not in {None, "success", "empty", "failed"}:
            raise ValueError("current_receipt_status is invalid")
        for name, providers in (
            ("current_providers", self.current_providers),
            ("last_success_providers", self.last_success_providers),
        ):
            if type(providers) is not tuple or any(
                type(provider) is not str or not provider for provider in providers
            ):
                raise TypeError(f"{name} must be a tuple of providers")
            if providers != tuple(sorted(set(providers))):
                raise ValueError(f"{name} must be sorted and unique")
        if self.current_receipt_status is None and self.current_providers:
            raise ValueError("untrusted current receipt cannot expose providers")
        if self.current_receipt_status is not None and not self.current_providers:
            raise ValueError("trusted current receipt requires providers")
        if self.last_success_receipt_id is None:
            if (
                self.last_success_providers
                or self.last_success_data_through is not None
            ):
                raise ValueError("last-success evidence is inconsistent")
        elif (
            type(self.last_success_receipt_id) is not str
            or not self.last_success_receipt_id
            or not self.last_success_providers
        ):
            raise ValueError("last-success evidence is inconsistent")
        if self.last_success_data_through is not None and (
            type(self.last_success_data_through) is not str
            or not self.last_success_data_through
        ):
            raise ValueError("last_success_data_through is invalid")
        for name, receipt_ids in (
            ("current_receipt_ids", self.current_receipt_ids),
            ("last_success_receipt_ids", self.last_success_receipt_ids),
            ("as_of_success_receipt_ids", self.as_of_success_receipt_ids),
        ):
            if type(receipt_ids) is not tuple or any(
                type(receipt_id) is not str or not receipt_id
                for receipt_id in receipt_ids
            ):
                raise TypeError(f"{name} must contain receipt IDs")
            if receipt_ids != tuple(sorted(set(receipt_ids))):
                raise ValueError(f"{name} must be sorted and unique")
        for name, pairs, providers in (
            (
                "current_provider_config_hashes",
                self.current_provider_config_hashes,
                self.current_providers,
            ),
            (
                "last_success_provider_config_hashes",
                self.last_success_provider_config_hashes,
                self.last_success_providers,
            ),
        ):
            if type(pairs) is not tuple or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or pair[0] not in providers
                or not _is_sha256(pair[1])
                for pair in pairs
            ):
                raise TypeError(f"{name} must contain provider/hash pairs")
            if pairs != tuple(sorted(set(pairs))):
                raise ValueError(f"{name} must be sorted and unique")


@dataclass(frozen=True)
class ValidatedReceiptHistoryEntry:
    """Minimal immutable receipt history exposed to read-only planners."""

    dataset_id: str
    provider: str
    receipt_id: str
    status: Literal["success", "empty", "failed"]
    cohort_status: Literal["success", "empty", "failed"]
    started_at: datetime
    finished_at: datetime
    request_window: Mapping[str, str]
    request_variant: Mapping[str, object]
    execution_id: str
    config_hash: str | None
    errors: tuple[str, ...] = ()
    cursor_contract_version: int | None = None
    frozen_universe_sha256: str | None = None
    batch_index: int | None = None
    batch_count: int | None = None
    batch_values_sha256: str | None = None
    physical_call_index: int | None = None
    retry_index: int | None = None
    data_through: str | None = None
    receipt_proof_sha256: str | None = None


@dataclass(frozen=True)
class ValidatedRowReceiptProof:
    """Secret-free immutable facts joined to one provider row receipt."""

    receipt_id: str
    dataset_id: str
    provider: str
    status: Literal["success"]
    execution_id: str
    config_hash: str | None
    request_window: Mapping[str, str]
    data_through: str | None
    finished_at: datetime
    receipt_proof_sha256: str


@dataclass(frozen=True)
class ReceiptJournalEntry:
    """Secret-free provenance for one persisted receipt row.

    Counts and error codes are taken only from a receipt that passed the
    existing authority validator.  Invalid rows expose their stable
    validation reason but never expose untrusted counts or payload fields.
    """

    receipt_id: str
    status: Literal["success", "empty", "failed", "invalid"]
    counts: IngestCounts | None
    error_layer: str | None
    error_codes: tuple[str, ...]
    validation_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedReceiptHistories:
    """Dataset-scoped planner authority derived from immutable receipts.

    A malformed receipt must make *its own* dataset unavailable.  It must not
    attest to, or prevent planning for, unrelated datasets sharing the same
    SQLite read model.
    """

    entries_by_dataset: Mapping[str, tuple[ValidatedReceiptHistoryEntry, ...]]
    failures_by_dataset: Mapping[str, tuple[str, ...]]


@dataclass
class _ReceiptReadBudget:
    """One catalog read budget, including repeated rows before deduplication."""

    remaining: int

    def consume(self, count: int) -> None:
        if count > self.remaining:
            raise RuntimeProjectionError("receipt execution scan row budget exceeded")
        self.remaining -= count


@dataclass(frozen=True)
class _Receipt:
    receipt_id: str
    attempt_id: str
    started_at: str
    finished_at: str
    status: str
    provider: str
    config_hash: str | None
    data_through: str | None
    request_window: Mapping[str, str]
    transaction_index: int
    counts: IngestCounts
    errors: tuple[str, ...]
    started_sort: datetime
    finished_sort: datetime
    attempt_context: str
    execution_id: str
    run_id: str
    schedule_plan_index: int | None
    physical_call_index: int | None
    retry_index: int | None
    request_variant: Mapping[str, object]
    request_identity_context: str
    execution_context: str
    cursor_contract_version: int | None
    frozen_universe_sha256: str | None
    batch_index: int | None
    batch_count: int | None
    batch_values_sha256: str | None


@dataclass(frozen=True)
class _CohortTerminal:
    status: Literal["success", "empty", "failed"]
    representative: _Receipt
    errors: tuple[str, ...]
    receipts: tuple[_Receipt, ...]


@dataclass(frozen=True)
class _InvalidReceipt:
    reason: str
    receipt_id: str | None
    observed_at: str | None


@dataclass(frozen=True)
class _ScannedIngestRunRow:
    raw: _IngestRunRow
    payload: dict[str, object] | None
    receipt_like: bool
    invalid: _InvalidReceipt | None


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True)
class _ReceiptDatabaseBinding:
    canonical_path: Path
    parent_identities: tuple[_FileIdentity, ...]
    database_identity: _FileIdentity
    wal_identity: _FileIdentity | None
    shm_identity: _FileIdentity | None


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey
        value[key] = item
    return value


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _receipt_proof_sha256(receipt: _Receipt, dataset_id: str) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "dataset_id": dataset_id,
                "provider": receipt.provider,
                "receipt_id": receipt.receipt_id,
                "execution_id": receipt.execution_id,
                "config_hash": receipt.config_hash,
                "data_through": receipt.data_through,
                "started_at": receipt.started_at,
                "finished_at": receipt.finished_at,
                "request_window": dict(receipt.request_window),
                "request_variant": dict(receipt.request_variant),
            }
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _parse_aware_datetime(value: object) -> datetime:
    if type(value) is not str or not value.strip():
        raise ValueError("timestamp must be a non-empty string")
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _active_bindings(dataset: DatasetDefinition) -> tuple[ProviderBinding, ...]:
    return tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.activation_state == "active"
    )


def _binding_for_payload(
    dataset: DatasetDefinition,
    provider: object,
    provider_api: object,
) -> ProviderBinding:
    if type(provider) is not str or type(provider_api) is not str:
        raise ValueError("provider_binding_mismatch")
    for binding in dataset.provider_bindings:
        if binding.provider == provider and binding.api_name == provider_api:
            return binding
    raise ValueError("provider_binding_mismatch")


def _validate_counts(payload: Mapping[str, object], status: str) -> IngestCounts:
    raw_counts = payload.get("counts")
    if type(raw_counts) is not dict or set(raw_counts) != _COUNT_KEYS:
        raise ValueError("receipt_counts_invalid")
    try:
        counts = IngestCounts(**raw_counts)
    except (TypeError, ValueError):
        raise ValueError("receipt_counts_invalid") from None

    numeric = (
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
            raise ValueError("receipt_counts_invalid")
        exact_semantics = {
            "exact_row_outcomes",
            "event_revision_outcomes_exact",
        }
        if counts.count_semantics in exact_semantics:
            if any(
                value is None
                for value in (counts.inserted, counts.updated, counts.unchanged)
            ):
                raise ValueError("receipt_counts_invalid")
        elif counts.count_semantics == "generic_upsert_outcomes_unavailable":
            if any(
                value is not None
                for value in (counts.inserted, counts.updated, counts.unchanged)
            ):
                raise ValueError("receipt_counts_invalid")
        else:
            raise ValueError("receipt_counts_invalid")
    elif status == "empty":
        if any(value != 0 for value in numeric):
            raise ValueError("receipt_counts_invalid")
        if counts.count_semantics != "terminal_no_data_transaction":
            raise ValueError("receipt_counts_invalid")
    elif status == "failed":
        if any(value != 0 for value in numeric):
            raise ValueError("receipt_counts_invalid")
        if counts.count_semantics not in {
            "storage_failure_before_commit",
            "terminal_no_data_transaction",
        }:
            raise ValueError("receipt_counts_invalid")
    else:
        raise ValueError("receipt_status_invalid")
    return counts


def _validate_errors(payload: Mapping[str, object], status: str) -> tuple[str, ...]:
    raw_errors = payload.get("errors")
    if type(raw_errors) is not list or any(
        type(item) is not str for item in raw_errors
    ):
        raise ValueError("receipt_errors_invalid")
    errors = tuple(raw_errors)
    if len(errors) != len(set(errors)) or any(
        code not in _ERROR_CODES for code in errors
    ):
        raise ValueError("receipt_errors_invalid")
    if status == "failed" and not errors:
        raise ValueError("receipt_errors_invalid")
    if status != "failed" and errors:
        raise ValueError("receipt_errors_invalid")
    return errors


def _validate_request_identity(
    payload: Mapping[str, object],
) -> ProviderRequestIdentity:
    raw_identity = payload.get("request_identity")
    expected_keys = {
        "fanout_parameter",
        "fanout_values",
        "page_index",
        "page_offset",
        "request_variant",
    }
    if type(raw_identity) is not dict or not expected_keys.issubset(raw_identity):
        raise ValueError("receipt_request_identity_invalid")
    cursor_keys = {
        "batch_count",
        "batch_index",
        "batch_values_sha256",
        "cursor_contract_version",
        "frozen_universe_sha256",
    }
    extra = set(raw_identity) - expected_keys
    if extra and extra != cursor_keys:
        raise ValueError("receipt_request_identity_invalid")
    cursor = {key: raw_identity.get(key) for key in cursor_keys} if extra else {}
    try:
        identity = ProviderRequestIdentity(
            request_variant=raw_identity["request_variant"],
            fanout_parameter=raw_identity["fanout_parameter"],
            fanout_values=raw_identity["fanout_values"],
            page_offset=raw_identity["page_offset"],
            page_index=raw_identity["page_index"],
            **cursor,
        )
    except (TypeError, ValueError):
        raise ValueError("receipt_request_identity_invalid") from None
    if _canonical_json(identity.canonical_payload()) != _canonical_json(raw_identity):
        raise ValueError("receipt_request_identity_invalid")
    return identity


def _related_to_dataset(
    payload: Mapping[str, object],
    envelope_source: object,
    dataset_id: str,
) -> bool:
    return envelope_source == dataset_id or payload.get("dataset_id") == dataset_id


def _payload_is_receipt_shaped(payload: Mapping[str, object]) -> bool:
    markers = set(payload).intersection(_RECEIPT_PAYLOAD_MARKERS)
    return bool(
        markers.intersection({"schema_version", "receipt_id", "payload_fingerprint"})
        or len(markers) >= 4
    )


def _classify_ingest_run_row(row: _IngestRunRow) -> _ScannedIngestRunRow:
    run_id = row[1]
    finished_at = row[5]
    notes_type = row[14]
    notes = row[15]
    envelope_receipt_like = type(run_id) is str and run_id.casefold().startswith(
        "receipt:"
    )
    receipt_id = run_id if type(run_id) is str else None
    observed_at = finished_at if type(finished_at) is str else None

    try:
        if notes_type != "text" or type(notes) is not str:
            raise ValueError
        decoded = json.loads(notes, object_pairs_hook=_object_without_duplicate_keys)
        if type(decoded) is not dict:
            raise ValueError
        payload: dict[str, object] = decoded
    except (json.JSONDecodeError, TypeError, ValueError, _DuplicateJsonKey):
        malformed_json_like = type(notes) is str and notes.lstrip().startswith(
            ("{", "[")
        )
        receipt_like = envelope_receipt_like or malformed_json_like
        invalid = (
            _InvalidReceipt("receipt_payload_invalid", receipt_id, observed_at)
            if receipt_like
            else None
        )
        return _ScannedIngestRunRow(row, None, receipt_like, invalid)

    receipt_like = envelope_receipt_like or _payload_is_receipt_shaped(payload)
    return _ScannedIngestRunRow(row, payload, receipt_like, None)


def _scan_ingest_run_rows(
    conn: sqlite3.Connection,
    *,
    dataset_id: str | None = None,
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read one bounded, unfiltered authority snapshot or fail closed."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    scan_limit = _MAX_INGEST_RUN_SCAN_ROWS + 1
    if dataset_id is None:
        cursor = conn.execute(_RECEIPT_QUERY, (scan_limit,))
    else:
        if type(dataset_id) is not str or not dataset_id:
            raise TypeError("dataset_id must be a non-empty string")
        cursor = conn.execute(
            _RECEIPT_QUERY_BY_DATASET,
            (dataset_id, scan_limit),
        )
    raw_rows = tuple(tuple(row) for row in cursor.fetchall())
    if len(raw_rows) == scan_limit:
        raise RuntimeProjectionError("receipt scan row budget exceeded")
    return tuple(_classify_ingest_run_row(row) for row in raw_rows)


def _scan_ingest_run_rows_for_dataset_authority(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    known_dataset_ids: frozenset[str],
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read one bounded per-dataset authority snapshot or fail closed.

    Materializes only the rows owned by ``dataset_id`` itself.  Rows owned by
    other known datasets always classify to inert rows and are excluded by the
    query; rows whose source is outside ``known_dataset_ids`` (tampered or
    unattributed rows) no longer poison this dataset's projection either —
    they are reported globally by ``project_unattributed_receipts`` instead,
    so one foreign row cannot fail every dataset at once.  The row budget
    therefore binds the dataset's own history rather than the whole
    append-only table.  ``known_dataset_ids`` remains part of the signature as
    the authority contract of the caller.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if type(dataset_id) is not str or not dataset_id:
        raise TypeError("dataset_id must be a non-empty string")
    if type(known_dataset_ids) is not frozenset:
        raise TypeError("known_dataset_ids must be frozenset")
    scan_limit = _MAX_INGEST_RUN_SCAN_ROWS + 1
    cursor = conn.execute(_RECEIPT_QUERY_BY_DATASET, (dataset_id, scan_limit))
    raw_rows = tuple(tuple(row) for row in cursor.fetchall())
    if len(raw_rows) == scan_limit:
        raise RuntimeProjectionError("receipt scan row budget exceeded")
    return tuple(_classify_ingest_run_row(row) for row in raw_rows)


def project_unattributed_receipts(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    registry: DatasetRegistry,
) -> UnattributedReceiptHealth:
    """Global tamper tripwire over rows no registered dataset claims.

    This is the narrowed blast radius of the former per-dataset contagion: a
    tampered or foreign receipt row used to fail *every* dataset's projection;
    it is now reported here (and via ``/admin/api/health/alerts``) while
    per-dataset projections stay accurate.  Tampering still cannot escape
    visibility — every receipt-like row whose envelope source is outside
    ``registry``'s known dataset ids is classified with the same reason
    vocabulary as per-dataset validation.  Historical unmapped-tushare
    tombstones that pass the deliberate-retirement marker are counted as
    benign and do not alert.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    _canonical_now(now)
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    other_known = sorted(known_dataset_ids)
    scan_limit = _MAX_INGEST_RUN_SCAN_ROWS + 1
    if not other_known:
        cursor = conn.execute(_RECEIPT_QUERY, (scan_limit,))
        params: tuple[object, ...] = (scan_limit,)
    else:
        placeholders = ", ".join("?" for _ in other_known)
        query = _RECEIPT_QUERY.replace(
            "FROM market_ingest_runs\nLIMIT ?",
            "FROM market_ingest_runs\n"
            f"WHERE source IS NULL OR source NOT IN ({placeholders})\n"
            "LIMIT ?",
        )
        params = (*other_known, scan_limit)
        cursor = conn.execute(query, params)
    raw_rows = tuple(tuple(row) for row in cursor.fetchall())
    if len(raw_rows) == scan_limit:
        raise RuntimeProjectionError("receipt scan row budget exceeded")

    anomalies: list[UnattributedReceiptAnomaly] = []
    benign = 0
    for scanned in (_classify_ingest_run_row(row) for row in raw_rows):
        source = scanned.raw[9]
        observed_at = (
            scanned.raw[5] if type(scanned.raw[5]) is str else None
        )
        receipt_id = scanned.raw[1] if type(scanned.raw[1]) is str else None
        if scanned.invalid is not None:
            anomalies.append(
                UnattributedReceiptAnomaly(
                    receipt_id=receipt_id,
                    source=source if type(source) is str else None,
                    reason=scanned.invalid.reason,
                    observed_at=observed_at,
                )
            )
            continue
        payload = scanned.payload
        assert payload is not None
        payload_dataset_id = payload.get("dataset_id")
        if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            anomalies.append(
                UnattributedReceiptAnomaly(
                    receipt_id=receipt_id,
                    source=source if type(source) is str else None,
                    reason="unknown_receipt_schema",
                    observed_at=observed_at,
                )
            )
            continue
        if type(source) is not str or type(payload_dataset_id) is not str:
            anomalies.append(
                UnattributedReceiptAnomaly(
                    receipt_id=receipt_id,
                    source=source if type(source) is str else None,
                    reason="receipt_envelope_invalid",
                    observed_at=observed_at,
                )
            )
            continue
        if source != payload_dataset_id:
            anomalies.append(
                UnattributedReceiptAnomaly(
                    receipt_id=receipt_id,
                    source=source,
                    reason="receipt_envelope_mismatch",
                    observed_at=observed_at,
                )
            )
            continue
        # source == payload.dataset_id and outside the known registry set.
        if _is_valid_unmapped_tushare_attempt(scanned, now=now):
            benign += 1
            continue
        anomalies.append(
            UnattributedReceiptAnomaly(
                receipt_id=receipt_id,
                source=source,
                reason="receipt_dataset_unknown",
                observed_at=observed_at,
            )
        )
    return UnattributedReceiptHealth(
        scanned_at=_canonical_now(now),
        anomalies=tuple(anomalies),
        benign_tombstones=benign,
    )


def _scan_recent_ingest_run_rows(
    conn: sqlite3.Connection,
    *,
    per_dataset_limit: int,
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read only the most recent ``per_dataset_limit`` receipts per dataset.

    This is the bounded replacement for the full ``market_ingest_runs`` scan on
    the catalog projection path.  The result is a union of per-source windows,
    so its size is independent of the table's total row count.  A global
    fail-closed budget still guards against a pathological number of distinct
    sources instead of silently truncating the authority snapshot.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if type(per_dataset_limit) is not int or per_dataset_limit <= 0:
        raise ValueError("per_dataset_limit must be a positive integer")
    raw_rows = tuple(
        tuple(row)
        for row in conn.execute(
            _RECENT_INGEST_RUN_QUERY,
            (per_dataset_limit,),
        ).fetchall()
    )
    if len(raw_rows) > _MAX_INGEST_RUN_SCAN_ROWS:
        raise RuntimeProjectionError("receipt scan row budget exceeded")
    return tuple(_classify_ingest_run_row(row) for row in raw_rows)


def _scan_ingest_run_rows_by_ids(
    conn: sqlite3.Connection,
    receipt_ids: tuple[str, ...],
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read only the bounded immutable receipt IDs requested by a row query."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not receipt_ids or len(receipt_ids) != len(set(receipt_ids)):
        raise ValueError("receipt_ids must be unique and non-empty")
    rows = tuple(
        tuple(row)
        for row in conn.execute(
            _receipt_query_by_run_ids(receipt_ids),
            receipt_ids,
        ).fetchall()
    )
    if {row[1] for row in rows} != set(receipt_ids) or len(rows) != len(receipt_ids):
        raise RuntimeProjectionError("row receipt authority is incomplete")
    return tuple(_classify_ingest_run_row(row) for row in rows)


def _scan_ingest_run_rows_by_execution_ids(
    conn: sqlite3.Connection,
    dataset_id: str,
    execution_ids: tuple[str, ...],
    *,
    read_budget: _ReceiptReadBudget | None = None,
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read only receipt rows belonging to selected validated executions.

    The first page lookup remains bounded by immutable receipt IDs.  This
    second-stage query retrieves only sibling physical calls needed to validate
    execution/variant cohort consistency for those selected receipts.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if type(dataset_id) is not str or not dataset_id:
        raise TypeError("dataset_id must be a non-empty string")
    if (
        type(execution_ids) is not tuple
        or not execution_ids
        or any(type(item) is not str or not item for item in execution_ids)
        or execution_ids != tuple(sorted(set(execution_ids)))
    ):
        raise ValueError("execution_ids must be a sorted unique non-empty tuple")

    fragments: list[str] = []
    for execution_id in execution_ids:
        ordinary = json.dumps(
            execution_id, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        physical_prefix = json.dumps(
            f"{execution_id}:provider-call:",
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )[:-1]
        fragments.extend(
            (f'"attempt_id":{ordinary}', f'"attempt_id":{physical_prefix}')
        )
    predicates = " OR ".join("instr(notes, ?) > 0" for _ in fragments)
    scan_limit = (
        _MAX_INGEST_RUN_SCAN_ROWS
        if read_budget is None
        else min(_MAX_INGEST_RUN_SCAN_ROWS, read_budget.remaining)
    ) + 1
    query = _RECEIPT_QUERY.replace(
        "FROM market_ingest_runs\nLIMIT ?",
        f"FROM market_ingest_runs\nWHERE source = ? AND ({predicates})\nLIMIT ?",
    )
    raw_rows = tuple(
        tuple(row)
        for row in conn.execute(
            query,
            (dataset_id, *fragments, scan_limit),
        ).fetchall()
    )
    if read_budget is not None:
        read_budget.consume(len(raw_rows))
    if len(raw_rows) == scan_limit:
        raise RuntimeProjectionError("receipt execution scan row budget exceeded")

    selected: list[_ScannedIngestRunRow] = []
    expected = frozenset(execution_ids)
    for row in raw_rows:
        scanned = _classify_ingest_run_row(row)
        if scanned.invalid is not None or scanned.payload is None:
            # The SQL fragment matched receipt-shaped material in this bounded
            # cohort. Preserve it so the ordinary validator can fail closed.
            selected.append(scanned)
            continue
        attempt_id = scanned.payload.get("attempt_id")
        try:
            physical = parse_provider_call_attempt_id(attempt_id)
            execution_id = (
                attempt_id if physical is None else physical.root_attempt_id
            )
        except (TypeError, ValueError):
            selected.append(scanned)
            continue
        if execution_id in expected:
            selected.append(scanned)
    return tuple(selected)


def _is_valid_unmapped_tushare_attempt(
    scanned: _ScannedIngestRunRow,
    *,
    now: datetime,
) -> bool:
    """Recognize one reserved collector-attempt tombstone, not a dataset row."""

    payload = scanned.payload
    if payload is None or scanned.invalid is not None:
        return False
    (
        run_id_type,
        run_id,
        started_at_type,
        started_at,
        finished_at_type,
        finished_at,
        status_type,
        envelope_status,
        source_type,
        source,
        rows_read_type,
        rows_read,
        rows_written_type,
        rows_written,
        notes_type,
        notes,
    ) = scanned.raw
    if (
        set(payload) != _RECEIPT_PAYLOAD_KEYS
        or type(notes) is not str
        or _canonical_json(payload) != notes
        or not _is_sha256(payload.get("payload_fingerprint"))
        or payload.get("payload_fingerprint") != hashlib.sha256(b"").hexdigest()
    ):
        return False
    if (
        run_id_type,
        started_at_type,
        finished_at_type,
        status_type,
        source_type,
        rows_read_type,
        rows_written_type,
        notes_type,
    ) != (
        "text",
        "text",
        "text",
        "text",
        "text",
        "integer",
        "integer",
        "text",
    ):
        return False
    if (
        payload.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or payload.get("receipt_id") != run_id
        or payload.get("started_at") != started_at
        or payload.get("finished_at") != finished_at
        or payload.get("status") != envelope_status
        or payload.get("dataset_id") != source
        or envelope_status != "failed"
        or payload.get("provider") != "tushare"
        or payload.get("adapter_version") != UNMAPPED_TUSHARE_ADAPTER_VERSION
        or payload.get("target_table") is not None
        or payload.get("transaction_index") != 0
        or payload.get("errors") != ["unmapped_dataset"]
        or not _is_sha256(payload.get("config_hash"))
    ):
        return False
    provider_api = payload.get("provider_api")
    try:
        expected_dataset_id = make_unmapped_tushare_dataset_id(provider_api)
    except (TypeError, ValueError):
        return False
    if source != expected_dataset_id:
        return False
    try:
        counts = _validate_counts(payload, "failed")
        errors = _validate_errors(payload, "failed")
        request_identity = _validate_request_identity(payload)
        request_window = payload.get("request_window")
        if type(request_window) is not dict or set(request_window) != {
            "end_date",
            "source_name",
            "start_date",
            "tier",
            "trade_date",
        }:
            return False
        start_date_text = request_window.get("start_date")
        end_date_text = request_window.get("end_date")
        trade_date_text = request_window.get("trade_date")
        source_name = request_window.get("source_name")
        tier = request_window.get("tier")
        if not all(
            type(value) is str and value
            for value in (
                start_date_text,
                end_date_text,
                trade_date_text,
                source_name,
                tier,
            )
        ):
            return False
        start_date = datetime.strptime(start_date_text, "%Y%m%d").date()
        end_date = datetime.strptime(end_date_text, "%Y%m%d").date()
        trade_date = datetime.strptime(trade_date_text, "%Y%m%d").date()
        if (
            start_date.strftime("%Y%m%d") != start_date_text
            or end_date.strftime("%Y%m%d") != end_date_text
            or trade_date.strftime("%Y%m%d") != trade_date_text
            or not start_date <= end_date <= trade_date
            or payload.get("data_through") != trade_date_text
            or not source_name.startswith(f"{provider_api}_")
        ):
            return False
        attempt_id = payload.get("attempt_id")
        if type(attempt_id) is not str:
            return False
        attempt_parts = attempt_id.split(":")
        if len(attempt_parts) != 2:
            return False
        attempt_uuids = tuple(uuid.UUID(part) for part in attempt_parts)
        if any(
            value.version != 4 or str(value) != part
            for value, part in zip(attempt_uuids, attempt_parts, strict=True)
        ):
            return False
        context = IngestContext(
            attempt_id=attempt_id,
            dataset_id=source,
            provider="tushare",
            provider_api=provider_api,
            request_window=request_window,
            config_hash=payload.get("config_hash"),
            adapter_version=UNMAPPED_TUSHARE_ADAPTER_VERSION,
            started_at=started_at,
            data_through=payload.get("data_through"),
            request_identity=request_identity,
        )
        expected_receipt_id = make_receipt_id(context, None, 0)
        started_sort = _parse_aware_datetime(started_at)
        finished_sort = _parse_aware_datetime(finished_at)
    except (TypeError, ValueError):
        return False
    now_utc = now.astimezone(timezone.utc)
    current_trade_date = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    return bool(
        errors == ("unmapped_dataset",)
        and counts.count_semantics == "terminal_no_data_transaction"
        and counts.returned == rows_read == 0
        and counts.committed == rows_written == 0
        and expected_receipt_id == run_id
        and finished_sort >= started_sort
        and started_sort <= now_utc
        and finished_sort <= now_utc
        and trade_date <= current_trade_date
    )


# Bounded per-process memo for receipt-row validation.  Receipts are immutable
# once committed, and validating a row against its *owning* dataset never
# consults ``now`` (only the unknown-source tombstone path does), so the result
# is a pure function of the row content and the dataset identity.  Long-lived
# API services pass one shared cache so each catalog request only validates
# receipts written since the previous request instead of the full append-only
# history; short-lived callers pass ``None`` and keep the direct path.  The
# cache is keyed by row content, not run_id, so a restored or rewritten row
# with a recycled run_id is always re-validated.
_RECEIPT_VALIDATION_CACHE_LIMIT = 250_000
_RECEIPT_VALIDATION_CACHE_LOCK = threading.Lock()


def _validate_receipt_row_memoized(
    scanned: _ScannedIngestRunRow,
    dataset: DatasetDefinition,
    known_dataset_ids: frozenset[str],
    now: datetime,
    expected_binding: ProviderBinding | None,
    cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"] | None,
) -> "_Receipt | _InvalidReceipt | None":
    if cache is None or expected_binding is not None:
        return _validate_receipt_row(
            scanned, dataset, known_dataset_ids, now, expected_binding
        )
    source = scanned.raw[9]
    if type(source) is not str or source != dataset.dataset_id:
        if type(source) is str and source in known_dataset_ids:
            # Rows owned by another known dataset always validate to ``None``
            # in both the invalid and the normal branch; skip the call.
            return None
        # Unknown-source rows take the ``now``-dependent tombstone path and
        # are never cached.
        return _validate_receipt_row(
            scanned, dataset, known_dataset_ids, now, expected_binding
        )
    key = (
        dataset.dataset_id,
        hashlib.sha256(repr(scanned.raw).encode("utf-8")).hexdigest(),
    )
    with _RECEIPT_VALIDATION_CACHE_LOCK:
        if key in cache:
            return cache[key]
    validated = _validate_receipt_row(
        scanned, dataset, known_dataset_ids, now, expected_binding
    )
    with _RECEIPT_VALIDATION_CACHE_LOCK:
        if len(cache) >= _RECEIPT_VALIDATION_CACHE_LIMIT:
            cache.clear()
        cache[key] = validated
    return validated


def _validate_receipt_row(
    scanned: _ScannedIngestRunRow,
    dataset: DatasetDefinition,
    known_dataset_ids: frozenset[str],
    now: datetime,
    expected_binding: ProviderBinding | None = None,
) -> _Receipt | _InvalidReceipt | None:
    if not scanned.receipt_like:
        return None
    if scanned.invalid is not None:
        source = scanned.raw[9]
        # Only a malformed receipt owned by this dataset poisons this dataset.
        # Foreign-source or unattributed malformed rows are inert here and are
        # surfaced globally by project_unattributed_receipts instead.
        if type(source) is str and source == dataset.dataset_id:
            return scanned.invalid
        return None
    payload = scanned.payload
    assert payload is not None
    (
        run_id_type,
        run_id,
        started_at_type,
        started_at,
        finished_at_type,
        finished_at,
        status_type,
        envelope_status,
        source_type,
        source,
        rows_read_type,
        rows_read,
        rows_written_type,
        rows_written,
        notes_type,
        notes,
    ) = scanned.raw
    receipt_id = run_id if type(run_id) is str else None
    observed_at = finished_at if type(finished_at) is str else None

    related = _related_to_dataset(payload, source, dataset.dataset_id)
    if not related:
        # Rows that do not claim this dataset are inert here.  The tamper
        # tripwire is preserved globally: project_unattributed_receipts
        # reports unknown-dataset/schema/malformed payloads so tampering can
        # still not escape visibility, without failing every dataset at once.
        return None
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return _InvalidReceipt("unknown_receipt_schema", receipt_id, observed_at)

    if set(payload) != _RECEIPT_PAYLOAD_KEYS or _canonical_json(payload) != notes:
        return _InvalidReceipt("receipt_payload_invalid", receipt_id, observed_at)
    if not _is_sha256(payload.get("payload_fingerprint")):
        return _InvalidReceipt("receipt_payload_invalid", receipt_id, observed_at)

    envelope_types = (
        run_id_type,
        started_at_type,
        finished_at_type,
        status_type,
        source_type,
        rows_read_type,
        rows_written_type,
    )
    if envelope_types != (
        "text",
        "text",
        "text",
        "text",
        "text",
        "integer",
        "integer",
    ):
        return _InvalidReceipt("receipt_envelope_invalid", receipt_id, observed_at)

    if payload.get("receipt_id") != run_id:
        return _InvalidReceipt("receipt_identity_mismatch", receipt_id, observed_at)
    if (
        payload.get("started_at") != started_at
        or payload.get("finished_at") != finished_at
        or payload.get("status") != envelope_status
        or payload.get("dataset_id") != source
        or source != dataset.dataset_id
    ):
        return _InvalidReceipt("receipt_envelope_mismatch", receipt_id, observed_at)

    status = payload.get("status")
    if type(status) is not str or status not in {"success", "empty", "failed"}:
        return _InvalidReceipt("receipt_status_invalid", receipt_id, observed_at)

    try:
        binding = _binding_for_payload(
            dataset,
            payload.get("provider"),
            payload.get("provider_api"),
        )
    except ValueError as exc:
        return _InvalidReceipt(str(exc), receipt_id, observed_at)
    if expected_binding is not None and binding != expected_binding:
        return None
    if payload.get("adapter_version") != binding.adapter_version:
        return _InvalidReceipt("adapter_version_mismatch", receipt_id, observed_at)

    target_table = payload.get("target_table")
    if binding.target_tables != (PROVIDER_DATASET_ROWS_TABLE,):
        return _InvalidReceipt("target_table_mismatch", receipt_id, observed_at)
    if status == "success":
        if target_table != PROVIDER_DATASET_ROWS_TABLE:
            return _InvalidReceipt("target_table_mismatch", receipt_id, observed_at)
    elif target_table is not None:
        return _InvalidReceipt("target_table_mismatch", receipt_id, observed_at)

    try:
        counts = _validate_counts(payload, status)
    except ValueError as exc:
        return _InvalidReceipt(str(exc), receipt_id, observed_at)
    if counts.returned != rows_read or counts.committed != rows_written:
        return _InvalidReceipt("receipt_envelope_mismatch", receipt_id, observed_at)
    try:
        errors = _validate_errors(payload, status)
    except ValueError as exc:
        return _InvalidReceipt(str(exc), receipt_id, observed_at)

    transaction_index = payload.get("transaction_index")
    request_window = payload.get("request_window")
    data_through = payload.get("data_through")
    if type(transaction_index) is not int or transaction_index < 0:
        return _InvalidReceipt("receipt_identity_mismatch", receipt_id, observed_at)
    if type(request_window) is not dict:
        return _InvalidReceipt("receipt_payload_invalid", receipt_id, observed_at)
    if data_through is not None and type(data_through) is not str:
        return _InvalidReceipt("invalid_data_through", receipt_id, observed_at)

    try:
        request_identity = _validate_request_identity(payload)
    except ValueError as exc:
        return _InvalidReceipt(str(exc), receipt_id, observed_at)

    try:
        context = IngestContext(
            attempt_id=payload.get("attempt_id"),
            dataset_id=payload.get("dataset_id"),
            provider=payload.get("provider"),
            provider_api=payload.get("provider_api"),
            request_window=request_window,
            config_hash=payload.get("config_hash"),
            adapter_version=payload.get("adapter_version"),
            started_at=payload.get("started_at"),
            data_through=data_through,
            request_identity=request_identity,
        )
        expected_receipt_id = make_receipt_id(
            context,
            target_table,
            transaction_index,
        )
        started_sort = _parse_aware_datetime(started_at)
        finished_sort = _parse_aware_datetime(finished_at)
    except (TypeError, ValueError):
        return _InvalidReceipt("receipt_identity_mismatch", receipt_id, observed_at)
    if expected_receipt_id != run_id:
        return _InvalidReceipt("receipt_identity_mismatch", receipt_id, observed_at)
    if finished_sort < started_sort:
        return _InvalidReceipt(
            "receipt_chronology_invalid",
            receipt_id,
            observed_at,
        )

    attempt_id = payload.get("attempt_id")
    assert type(attempt_id) is str
    assert type(run_id) is str
    assert type(started_at) is str
    assert type(finished_at) is str
    try:
        physical_attempt = parse_provider_call_attempt_id(attempt_id)
        execution_id = (
            attempt_id if physical_attempt is None else physical_attempt.root_attempt_id
        )
        schedule_attempt = parse_schedule_plan_attempt_id(execution_id)
    except (TypeError, ValueError):
        return _InvalidReceipt("receipt_identity_mismatch", receipt_id, observed_at)
    request_identity_context = _canonical_json(
        context.request_identity.canonical_payload()
    )
    execution_context = _canonical_json(
        {
            "adapter_version": context.adapter_version,
            "config_hash": context.config_hash,
            "dataset_id": context.dataset_id,
            "provider": context.provider,
            "provider_api": context.provider_api,
            "request_window": dict(context.request_window),
            "started_at": context.started_at,
        }
    )
    return _Receipt(
        receipt_id=run_id,
        attempt_id=attempt_id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        provider=binding.provider,
        config_hash=context.config_hash,
        data_through=data_through,
        request_window=MappingProxyType(dict(sorted(request_window.items()))),
        transaction_index=transaction_index,
        counts=counts,
        errors=errors,
        started_sort=started_sort,
        finished_sort=finished_sort,
        attempt_context=_canonical_json(
            {
                "adapter_version": context.adapter_version,
                "config_hash": context.config_hash,
                "dataset_id": context.dataset_id,
                "provider": context.provider,
                "provider_api": context.provider_api,
                "request_identity": context.request_identity.canonical_payload(),
                "request_window": dict(context.request_window),
                "started_at": context.started_at,
            }
        ),
        execution_id=execution_id,
        run_id=(
            execution_id
            if schedule_attempt is None
            else schedule_attempt.run_attempt_id
        ),
        schedule_plan_index=(
            None if schedule_attempt is None else schedule_attempt.plan_index
        ),
        physical_call_index=(
            None if physical_attempt is None else physical_attempt.call_index
        ),
        retry_index=(
            None if physical_attempt is None else physical_attempt.retry_index
        ),
        request_variant=MappingProxyType(
            dict(context.request_identity.request_variant)
        ),
        request_identity_context=request_identity_context,
        execution_context=execution_context,
        cursor_contract_version=context.request_identity.cursor_contract_version,
        frozen_universe_sha256=context.request_identity.frozen_universe_sha256,
        batch_index=context.request_identity.batch_index,
        batch_count=context.request_identity.batch_count,
        batch_values_sha256=context.request_identity.batch_values_sha256,
    )


def _invalid_receipt_sort_key(
    receipt: _InvalidReceipt,
) -> tuple[datetime, str, str, str]:
    try:
        observed_at = _parse_aware_datetime(receipt.observed_at)
    except (TypeError, ValueError):
        observed_at = datetime.min.replace(tzinfo=timezone.utc)
    return (
        observed_at,
        receipt.observed_at or "",
        receipt.receipt_id or "",
        receipt.reason,
    )


def _execution_sort_key(receipt: _Receipt) -> tuple[datetime, str]:
    return (receipt.started_sort, receipt.execution_id)


def _success_sort_key(
    receipt: _Receipt,
) -> tuple[datetime, str, int, int, int, datetime, str]:
    return (
        receipt.started_sort,
        receipt.execution_id,
        -1 if receipt.physical_call_index is None else receipt.physical_call_index,
        -1 if receipt.retry_index is None else receipt.retry_index,
        receipt.transaction_index,
        receipt.finished_sort,
        receipt.receipt_id,
    )


def _terminal_receipt_for_attempt(receipts: list[_Receipt]) -> _Receipt:
    terminal_receipts = [
        receipt for receipt in receipts if receipt.status in {"empty", "failed"}
    ]
    if terminal_receipts:
        return max(
            terminal_receipts,
            key=lambda receipt: (
                receipt.finished_sort,
                int(receipt.status == "failed"),
                receipt.receipt_id,
            ),
        )
    return max(
        receipts,
        key=lambda receipt: (
            receipt.transaction_index,
            receipt.finished_sort,
            receipt.receipt_id,
        ),
    )


def _physical_receipt_sort_key(
    receipt: _Receipt,
) -> tuple[int, int, int, datetime, str]:
    assert receipt.physical_call_index is not None
    assert receipt.retry_index is not None
    return (
        receipt.physical_call_index,
        receipt.retry_index,
        receipt.transaction_index,
        receipt.finished_sort,
        receipt.receipt_id,
    )


def _provider_execution_terminal(receipts: list[_Receipt]) -> _Receipt:
    logical_requests: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        logical_requests.setdefault(receipt.request_identity_context, []).append(
            receipt
        )

    request_terminals: list[_Receipt] = []
    for request_receipts in logical_requests.values():
        attempts: dict[str, list[_Receipt]] = {}
        for receipt in request_receipts:
            attempts.setdefault(receipt.attempt_id, []).append(receipt)
        latest_attempt = max(
            attempts.values(),
            key=lambda values: _physical_receipt_sort_key(values[0]),
        )
        request_terminals.append(_terminal_receipt_for_attempt(latest_attempt))

    for status in ("failed", "success", "empty"):
        matching = [
            receipt for receipt in request_terminals if receipt.status == status
        ]
        if matching:
            return max(matching, key=_physical_receipt_sort_key)
    raise ValueError("provider execution has no terminal receipt")


def _terminal_sort_key(receipt: _Receipt) -> tuple[datetime, int, int, str]:
    return (
        receipt.finished_sort,
        -1 if receipt.schedule_plan_index is None else receipt.schedule_plan_index,
        -1 if receipt.physical_call_index is None else receipt.physical_call_index,
        receipt.receipt_id,
    )


def _terminal_across_executions(receipts: list[_Receipt]) -> _Receipt:
    executions: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        executions.setdefault(receipt.execution_id, []).append(receipt)
    terminals: list[_Receipt] = []
    for execution_receipts in executions.values():
        physical = {
            receipt.physical_call_index is not None for receipt in execution_receipts
        }
        if physical == {True}:
            terminals.append(_provider_execution_terminal(execution_receipts))
        else:
            terminals.append(_terminal_receipt_for_attempt(execution_receipts))
    for status in ("failed", "success", "empty"):
        matching = [receipt for receipt in terminals if receipt.status == status]
        if matching:
            return max(matching, key=_terminal_sort_key)
    raise ValueError("receipt cohort has no terminal")


def _variant_key(variant: Mapping[str, object]) -> str:
    return _canonical_json({"request_variant": dict(variant)})


def _binding_for_provider(
    dataset: DatasetDefinition,
    provider: str,
) -> ProviderBinding:
    matches = tuple(
        binding
        for binding in dataset.provider_bindings
        if binding.provider == provider
    )
    if len(matches) != 1:
        raise ValueError("receipt provider binding is ambiguous")
    return matches[0]


def _variant_cohort_terminal(
    dataset: DatasetDefinition,
    receipts: list[_Receipt],
) -> _CohortTerminal:
    if not receipts:
        raise ValueError("variant cohort is empty")
    execution_ids = {receipt.execution_id for receipt in receipts}
    providers = {receipt.provider for receipt in receipts}
    windows = {
        _canonical_json(dict(receipt.request_window)) for receipt in receipts
    }
    if len(execution_ids) != 1 or len(providers) != 1 or len(windows) != 1:
        raise ValueError("variant cohort identity is inconsistent")
    binding = _binding_for_provider(dataset, receipts[0].provider)
    expected = {_variant_key(variant) for variant in binding.request_variants}
    by_variant: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        by_variant.setdefault(_variant_key(receipt.request_variant), []).append(receipt)
    representative = max(receipts, key=_terminal_sort_key)
    if set(by_variant) != expected:
        return _CohortTerminal(
            status="failed",
            representative=representative,
            errors=("variant_cohort_incomplete",),
            receipts=tuple(receipts),
        )

    terminals = [
        _terminal_across_executions(by_variant[variant])
        for variant in sorted(expected)
    ]
    failed = [receipt for receipt in terminals if receipt.status == "failed"]
    if failed:
        failure = max(failed, key=_terminal_sort_key)
        return _CohortTerminal(
            status="failed",
            representative=failure,
            errors=failure.errors,
            receipts=tuple(receipts),
        )
    if any(receipt.status == "success" for receipt in terminals):
        return _CohortTerminal(
            status="success",
            representative=representative,
            errors=(),
            receipts=tuple(receipts),
        )
    if dataset.empty_data_policy == "forbidden":
        return _CohortTerminal(
            status="failed",
            representative=representative,
            errors=("validation_failed",),
            receipts=tuple(receipts),
        )
    return _CohortTerminal(
        status="empty",
        representative=representative,
        errors=(),
        receipts=tuple(receipts),
    )


def _run_terminal(
    dataset: DatasetDefinition,
    receipts: list[_Receipt],
) -> _CohortTerminal:
    executions: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        executions.setdefault(receipt.execution_id, []).append(receipt)
    cohorts = [
        _variant_cohort_terminal(dataset, execution_receipts)
        for execution_receipts in executions.values()
    ]
    failed = [cohort for cohort in cohorts if cohort.status == "failed"]
    if failed:
        representative = max(
            failed,
            key=lambda cohort: _terminal_sort_key(cohort.representative),
        )
        return _CohortTerminal(
            status="failed",
            representative=representative.representative,
            errors=tuple(
                dict.fromkeys(error for cohort in failed for error in cohort.errors)
            ),
            receipts=tuple(receipts),
        )
    def target_key(cohort: _CohortTerminal) -> tuple[str, int, str]:
        receipt = cohort.representative
        binding = _binding_for_provider(dataset, receipt.provider)
        policy = binding.request_window_policy
        target = (
            ""
            if policy is None
            else receipt.request_window[policy.range_end_key]
        )
        return (
            target,
            -1
            if receipt.schedule_plan_index is None
            else receipt.schedule_plan_index,
            receipt.execution_id,
        )

    current = max(cohorts, key=target_key)
    return _CohortTerminal(
        status=current.status,
        representative=current.representative,
        errors=(),
        receipts=tuple(receipts),
    )


def _latest_run_terminal(
    dataset: DatasetDefinition,
    receipts: list[_Receipt],
) -> _CohortTerminal:
    runs: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        runs.setdefault(receipt.run_id, []).append(receipt)
    latest = max(
        runs.values(),
        key=lambda values: (
            max(receipt.started_sort for receipt in values),
            values[0].run_id,
        ),
    )
    return _run_terminal(dataset, latest)


def _effective_latest_terminal(
    dataset: DatasetDefinition,
    authority_receipts: list[_Receipt],
    last_success: _Receipt | None,
    now_utc: datetime,
) -> _CohortTerminal:
    """Return the current terminal, falling back to a fresh success history.

    An append-only dataset accumulates immutable rows; a transient
    ``provider_error`` on the *latest* incremental attempt does not invalidate
    a still-fresh successful watermark.  Without this fallback a daily-dump
    dataset would stay ``failed`` for hours after one transient failure until
    a new day publishes — hiding healthy history.  Structural failures
    (validation/config drift) and any snapshot dataset still fail closed.
    """

    latest = _latest_run_terminal(dataset, authority_receipts)
    if (
        latest.status == "failed"
        and dataset.point_in_time == "append_only"
        and latest.errors == ("provider_error",)
        and last_success is not None
        and last_success.data_through is not None
    ):
        try:
            success_utc = _freshness_reference_in_utc(
                last_success.data_through, dataset
            )
        except (ValueError, AttributeError):
            return latest
        if now_utc - success_utc <= timedelta(seconds=dataset.freshness_sla_seconds):
            execution = tuple(
                receipt
                for receipt in authority_receipts
                if receipt.execution_id == last_success.execution_id
            )
            return _CohortTerminal(
                status="success",
                representative=last_success,
                errors=(),
                receipts=execution,
            )
    return latest


def _complete_success_receipts(
    receipts: list[_Receipt],
    dataset: DatasetDefinition,
) -> tuple[_Receipt, ...]:
    executions: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        executions.setdefault(receipt.execution_id, []).append(receipt)
    return tuple(
        receipt
        for members in executions.values()
        if _variant_cohort_terminal(dataset, members).status == "success"
        for receipt in members
        if receipt.status == "success"
    )


def _success_watermark_receipt(
    receipts: list[_Receipt],
    dataset: DatasetDefinition,
) -> _Receipt | None:
    complete_successes = _complete_success_receipts(receipts, dataset)
    candidates: list[tuple[datetime, _Receipt]] = []
    for receipt in complete_successes:
        if receipt.data_through is None:
            continue
        try:
            watermark = _data_through_in_utc(receipt.data_through, dataset.timezone)
        except ValueError:
            continue
        candidates.append((watermark, receipt))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (item[0], _success_sort_key(item[1])),
    )[1]


def _ingest_config_hash_cached(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    config_hash_cache: dict[tuple[int, int], str],
) -> str:
    """Return the ingest config hash, computed at most once per projection."""
    key = (id(dataset), id(binding))
    config_hash = config_hash_cache.get(key)
    if config_hash is None:
        config_hash = provider_ingest_config_hash(dataset, binding)
        config_hash_cache[key] = config_hash
    return config_hash


def _partition_declaration_predecessor(
    dataset: DatasetDefinition,
) -> DatasetDefinition | None:
    """Return the preceding ``partition_field=None`` dataset, or ``None``.

    Declaring an append-only RFC3339 range field as ``partition_field`` changed
    the receipt config hash even though the provider request, payload, primary
    key, and row JSON stayed identical. Historical as-of reads may therefore
    retain the immediately preceding ``partition_field=None`` receipts. Current
    projection authority continues to require the active config hash.
    """

    if (
        dataset.point_in_time != "append_only"
        or dataset.as_of_format != "rfc3339"
        or dataset.range_field is None
        or dataset.partition_field != dataset.range_field
    ):
        return None
    return replace(dataset, partition_field=None)


def _receipt_matches_active_config(
    receipt: _Receipt,
    dataset: DatasetDefinition,
    expected_binding: ProviderBinding | None,
    config_hash_cache: dict[tuple[int, int], str],
) -> bool:
    """Return whether a valid receipt attests to the active ingest contract."""

    bindings = (
        (expected_binding,)
        if expected_binding is not None
        else dataset.provider_bindings
    )
    return any(
        receipt.config_hash
        == _ingest_config_hash_cached(dataset, binding, config_hash_cache)
        for binding in bindings
    )


def _receipt_matches_partition_declaration_predecessor(
    receipt: _Receipt,
    predecessor: DatasetDefinition | None,
    expected_binding: ProviderBinding | None,
    config_hash_cache: dict[tuple[int, int], str],
) -> bool:
    """Accept the pre-partition hash only for bounded historical row lineage."""

    if predecessor is None:
        return False
    bindings = (
        (expected_binding,)
        if expected_binding is not None
        else predecessor.provider_bindings
    )
    return any(
        receipt.config_hash
        == _ingest_config_hash_cached(predecessor, binding, config_hash_cache)
        for binding in bindings
    )


def _attempt_context_failures(
    receipts: list[_Receipt],
) -> tuple[_InvalidReceipt, ...]:
    attempts: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        attempts.setdefault(receipt.attempt_id, []).append(receipt)

    failures: list[_InvalidReceipt] = []
    for attempt_receipts in attempts.values():
        contexts = {receipt.attempt_context for receipt in attempt_receipts}
        if len(contexts) <= 1:
            continue
        representative = max(
            attempt_receipts,
            key=lambda receipt: (
                receipt.finished_sort,
                int(receipt.status == "failed"),
                receipt.receipt_id,
            ),
        )
        failures.append(
            _InvalidReceipt(
                "receipt_attempt_inconsistent",
                representative.receipt_id,
                representative.finished_at,
            )
        )
    return tuple(failures)


def _execution_context_failures(
    receipts: list[_Receipt],
    *,
    complete_execution_ids: frozenset[str] = frozenset(),
) -> tuple[_InvalidReceipt, ...]:
    executions: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        executions.setdefault(receipt.execution_id, []).append(receipt)

    failures: list[_InvalidReceipt] = []
    for execution_id, execution_receipts in executions.items():
        representative = max(
            execution_receipts,
            key=lambda receipt: (
                receipt.finished_sort,
                receipt.receipt_id,
            ),
        )
        physical_states = {
            receipt.physical_call_index is not None for receipt in execution_receipts
        }
        contexts = {receipt.execution_context for receipt in execution_receipts}
        if len(physical_states) != 1:
            failures.append(
                _InvalidReceipt(
                    "receipt_execution_inconsistent",
                    representative.receipt_id,
                    representative.finished_at,
                )
            )
            continue
        if physical_states == {False}:
            continue
        if len(contexts) != 1:
            failures.append(
                _InvalidReceipt(
                    "receipt_execution_inconsistent",
                    representative.receipt_id,
                    representative.finished_at,
                )
            )
            continue

        attempts: dict[str, list[_Receipt]] = {}
        for receipt in execution_receipts:
            attempts.setdefault(receipt.attempt_id, []).append(receipt)
        attempt_representatives = [values[0] for values in attempts.values()]
        call_indexes = sorted(
            receipt.physical_call_index for receipt in attempt_representatives
        )
        first_visible_call_index = call_indexes[0] if call_indexes else None
        # The bounded catalog scan can begin in the middle of a large
        # execution.  Its visible physical calls must still form one exact
        # contiguous suffix, but that suffix is not required to start at zero.
        if (
            any(call_index is None for call_index in call_indexes)
            or len(set(call_indexes)) != len(call_indexes)
            or first_visible_call_index is None
            or (execution_id in complete_execution_ids and first_visible_call_index != 0)
            or call_indexes
            != list(
                range(
                    first_visible_call_index,
                    first_visible_call_index + len(call_indexes),
                )
            )
        ):
            failures.append(
                _InvalidReceipt(
                    "receipt_execution_inconsistent",
                    representative.receipt_id,
                    representative.finished_at,
                )
            )
            continue

        logical_requests: dict[str, list[_Receipt]] = {}
        for receipt in attempt_representatives:
            logical_requests.setdefault(
                receipt.request_identity_context,
                [],
            ).append(receipt)
        inconsistent_retry_group = False
        for request_receipts in logical_requests.values():
            ordered = sorted(request_receipts, key=_physical_receipt_sort_key)
            first_call_index = ordered[0].physical_call_index
            assert first_call_index is not None
            actual = [
                (receipt.physical_call_index, receipt.retry_index)
                for receipt in ordered
            ]
            expected = [
                (first_call_index + retry_index, retry_index)
                for retry_index in range(len(ordered))
            ]
            if actual != expected:
                inconsistent_retry_group = True
                break
        if inconsistent_retry_group:
            failures.append(
                _InvalidReceipt(
                    "receipt_execution_inconsistent",
                    representative.receipt_id,
                    representative.finished_at,
                )
            )
    return tuple(failures)


def _data_through_in_utc(value: str, timezone_name: str) -> datetime:
    try:
        dataset_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError("dataset_timezone_invalid") from None

    candidate = value.strip()
    if len(candidate) == 6 and candidate.isdigit():
        parsed = datetime.strptime(candidate, "%Y%m")
    elif len(candidate) == 8 and candidate.isdigit():
        parsed = datetime.strptime(candidate, "%Y%m%d")
    else:
        try:
            parsed = datetime.fromisoformat(
                f"{candidate[:-1]}+00:00" if candidate.endswith("Z") else candidate
            )
        except ValueError:
            raise ValueError("invalid_data_through") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=dataset_timezone)
    return parsed.astimezone(timezone.utc)


def _freshness_reference_in_utc(value: str, dataset: DatasetDefinition) -> datetime:
    """Use the end of a date-only partition for freshness checks.

    A date-only success watermark means the data covers through that trade
    date. Measuring freshness from local midnight would make any daily
    dataset stale as soon as the next day begins, regardless of cadence
    class, so date-only watermarks always reference the end of their date.
    """

    data_through_utc = _data_through_in_utc(value, dataset.timezone)
    try:
        dataset_timezone = ZoneInfo(dataset.timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("dataset_timezone_invalid") from None
    local = data_through_utc.astimezone(dataset_timezone)
    if len(value.strip()) == 6 and value.strip().isdigit():
        # YYYYMM denotes the whole month, not its first calendar day.
        next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
        return (next_month - timedelta(microseconds=1)).astimezone(timezone.utc)
    if any((local.hour, local.minute, local.second, local.microsecond)):
        return data_through_utc
    return (local + timedelta(days=1) - timedelta(microseconds=1)).astimezone(
        timezone.utc
    )


def _freshness_clock_in_utc(dataset: DatasetDefinition, now_utc: datetime) -> datetime:
    """Freeze regular CN market cadence at Friday's close over the weekend.

    This is not a holiday calendar or an exemption for event/reference/crypto
    data. Missing Friday data must still fail the ordinary SLA comparison.
    """
    if (
        dataset.market != "CN"
        or dataset.timezone != "Asia/Shanghai"
        or dataset.cadence_class not in {"session_minute", "postclose_daily"}
    ):
        return now_utc
    local = now_utc.astimezone(ZoneInfo(dataset.timezone))
    if local.weekday() < 5:
        return now_utc
    friday = local - timedelta(days=local.weekday() - 4)
    if dataset.cadence_class == "session_minute":
        close = friday.replace(hour=15, minute=0, second=0, microsecond=0)
    else:
        close = (friday + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return close.astimezone(timezone.utc)


def _is_cn_session_minute_lunch_break(
    dataset: DatasetDefinition,
    *,
    now_utc: datetime,
    data_through_utc: datetime,
) -> bool:
    """Return whether a same-day A-share minute watermark is in the lunch break.

    ``session_minute`` describes a market-session cadence, not an unbroken
    wall-clock cadence. The current class is used only by China-market
    datasets, whose regular lunch break is 11:30--13:00 Asia/Shanghai. Keep
    the ordinary SLA strict at and after the afternoon open; only a watermark
    from the same local trading date is protected during the break.
    """

    if (
        dataset.cadence_class != "session_minute"
        or dataset.market != "CN"
        or dataset.timezone != "Asia/Shanghai"
    ):
        return False
    local_now = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    local_data_through = data_through_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    return (
        local_now.date() == local_data_through.date()
        and (local_now.hour == 11 and local_now.minute >= 30 or local_now.hour == 12)
    )


def _project_dataset_runtime(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    known_dataset_ids: frozenset[str],
    rows: tuple[_ScannedIngestRunRow, ...],
    expected_binding: ProviderBinding | None = None,
    validation_cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"]
    | None = None,
    complete_execution_ids: frozenset[str] = frozenset(),
) -> DatasetRuntimeProjection:
    """Derive one dataset's current state without consulting flat files."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")

    is_paused = (
        expected_binding.activation_state != "active"
        if expected_binding is not None
        else not _active_bindings(dataset)
    )

    receipts: list[_Receipt] = []
    invalid: list[_InvalidReceipt] = []
    for scanned_row in rows:
        validated = _validate_receipt_row_memoized(
            scanned_row,
            dataset,
            known_dataset_ids,
            now,
            expected_binding,
            validation_cache,
        )
        if isinstance(validated, _Receipt):
            receipts.append(validated)
        elif isinstance(validated, _InvalidReceipt):
            invalid.append(validated)

    now_utc = now.astimezone(timezone.utc)
    # Attempt/execution integrity must be asserted on the full validated set:
    # filtering future-dated receipts first would strip mid-execution calls and
    # cascade into bogus receipt_execution_inconsistent, masking the real
    # reason (receipt_timestamp_in_future / data_through_in_future).
    invalid.extend(_attempt_context_failures(receipts))
    invalid.extend(_execution_context_failures(
        receipts, complete_execution_ids=complete_execution_ids
    ))
    current_receipts: list[_Receipt] = []
    for receipt in receipts:
        if receipt.started_sort > now_utc or receipt.finished_sort > now_utc:
            invalid.append(
                _InvalidReceipt(
                    "receipt_timestamp_in_future",
                    receipt.receipt_id,
                    receipt.finished_at,
                )
            )
            continue
        if receipt.data_through is not None:
            try:
                data_through_utc = _data_through_in_utc(
                    receipt.data_through,
                    dataset.timezone,
                )
            except ValueError:
                data_through_utc = None
            if (
                data_through_utc is not None
                and data_through_utc > now_utc
                and dataset.entity_type != "trade_calendar"
            ):
                invalid.append(
                    _InvalidReceipt(
                        "data_through_in_future",
                        receipt.receipt_id,
                        receipt.finished_at,
                    )
                )
                continue
        current_receipts.append(receipt)
    receipts = current_receipts

    config_hash_cache: dict[tuple[int, int], str] = {}
    authority_receipts = [
        receipt
        for receipt in receipts
        if _receipt_matches_active_config(
            receipt,
            dataset,
            expected_binding,
            config_hash_cache,
        )
    ]
    has_superseded_contract_receipt = len(authority_receipts) != len(receipts)
    successful = list(_complete_success_receipts(authority_receipts, dataset))
    last_success = _success_watermark_receipt(authority_receipts, dataset) or max(
        successful,
        key=_success_sort_key,
        default=None,
    )
    public_success_watermark = (
        last_success.finished_at
        if dataset.entity_type == "trade_calendar" and last_success is not None
        else (last_success.data_through if last_success else None)
    )
    if invalid:
        failure = max(invalid, key=_invalid_receipt_sort_key)
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=public_success_watermark,
            observed_at=failure.observed_at,
            receipt_id=failure.receipt_id,
            reasons=(failure.reason,),
        )
    if is_paused:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="paused",
            degraded=True,
            data_through=None,
            observed_at=None,
            receipt_id=None,
            reasons=("registry_activation_paused",),
        )
    if not authority_receipts:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="unobserved",
            degraded=True,
            data_through=None,
            observed_at=None,
            receipt_id=None,
            reasons=(
                "active_config_receipt_mismatch"
                if has_superseded_contract_receipt
                else "no_recognized_receipt",
            ),
        )

    latest = _effective_latest_terminal(
        dataset, authority_receipts, last_success, now_utc
    )
    representative = latest.representative
    data_through = public_success_watermark
    if latest.status == "failed":
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=data_through,
            observed_at=representative.finished_at,
            receipt_id=representative.receipt_id,
            reasons=latest.errors,
        )
    # A terminal empty receipt is current evidence that the requested window
    # was checked and contained no rows.  Its freshness is the observation
    # time, not an older successful data watermark: otherwise a legitimate
    # empty current partition is incorrectly reported as stale forever.
    if latest.status == "empty":
        empty_is_stale = (
            dataset.cadence_class != "on_demand"
            and now_utc - representative.finished_sort
            > timedelta(seconds=dataset.freshness_sla_seconds)
        )
        if empty_is_stale:
            return DatasetRuntimeProjection(
                dataset_id=dataset.dataset_id,
                state="stale",
                degraded=True,
                data_through=data_through,
                observed_at=representative.finished_at,
                receipt_id=representative.receipt_id,
                reasons=("freshness_sla_exceeded", "latest_receipt_empty"),
            )
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="empty",
            degraded=False,
            data_through=data_through,
            observed_at=representative.finished_at,
            receipt_id=representative.receipt_id,
            reasons=("provider_returned_no_rows",),
        )
    if data_through is None:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=None,
            observed_at=representative.finished_at,
            receipt_id=representative.receipt_id,
            reasons=("invalid_data_through",),
        )
    try:
        data_through_utc = _freshness_reference_in_utc(data_through, dataset)
    except ValueError as exc:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=data_through,
            observed_at=representative.finished_at,
            receipt_id=representative.receipt_id,
            reasons=(str(exc),),
        )

    # on_demand datasets have no refresh expectation; freshness SLA must not
    # mark them stale (query-on-demand semantics per registry contract).
    is_stale = (
        dataset.cadence_class != "on_demand"
        and _freshness_clock_in_utc(dataset, now_utc) - data_through_utc
        > timedelta(seconds=dataset.freshness_sla_seconds)
        and not _is_cn_session_minute_lunch_break(
            dataset,
            now_utc=now_utc,
            data_through_utc=data_through_utc,
        )
    )
    if is_stale:
        reasons = ("freshness_sla_exceeded",)
        if latest.status == "empty":
            reasons += ("latest_receipt_empty",)
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="stale",
            degraded=True,
            data_through=data_through,
            observed_at=representative.finished_at,
            receipt_id=representative.receipt_id,
            reasons=reasons,
        )
    return DatasetRuntimeProjection(
        dataset_id=dataset.dataset_id,
        state="success",
        degraded=False,
        data_through=data_through,
        observed_at=representative.finished_at,
        receipt_id=representative.receipt_id,
        reasons=(),
    )


def project_dataset_runtime(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    registry: DatasetRegistry | None = None,
    provider_binding: ProviderBinding | None = None,
) -> DatasetRuntimeProjection:
    """Derive one dataset using a fail-closed single-dataset authority set."""

    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    if (
        provider_binding is not None
        and provider_binding not in dataset.provider_bindings
    ):
        raise ValueError("provider_binding must belong to dataset")
    known_dataset_ids = (
        frozenset(item.dataset_id for item in registry.datasets)
        if registry is not None
        else frozenset({dataset.dataset_id})
    )
    return _project_dataset_runtime(
        conn,
        dataset,
        now=now,
        known_dataset_ids=known_dataset_ids,
        rows=(
            _scan_ingest_run_rows_for_dataset_authority(
                conn,
                dataset_id=dataset.dataset_id,
                known_dataset_ids=known_dataset_ids,
            )
            if registry is not None
            else _scan_ingest_run_rows(conn)
        ),
        expected_binding=provider_binding,
    )


def _trusted_receipts_for_evidence(
    dataset: DatasetDefinition,
    *,
    now: datetime,
    known_dataset_ids: frozenset[str],
    rows: tuple[_ScannedIngestRunRow, ...],
    expected_binding: ProviderBinding | None,
    validation_cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"]
    | None = None,
) -> tuple[list[_Receipt], list[_InvalidReceipt]]:
    receipts: list[_Receipt] = []
    invalid: list[_InvalidReceipt] = []
    for scanned_row in rows:
        validated = _validate_receipt_row_memoized(
            scanned_row,
            dataset,
            known_dataset_ids,
            now,
            expected_binding,
            validation_cache,
        )
        if isinstance(validated, _Receipt):
            receipts.append(validated)
        elif isinstance(validated, _InvalidReceipt):
            invalid.append(validated)

    now_utc = now.astimezone(timezone.utc)
    # Same ordering rule as _project_dataset_runtime: integrity checks on the
    # full validated set, before future-dated receipts are filtered out.
    invalid.extend(_attempt_context_failures(receipts))
    invalid.extend(_execution_context_failures(receipts))
    current_receipts: list[_Receipt] = []
    for receipt in receipts:
        if receipt.started_sort > now_utc or receipt.finished_sort > now_utc:
            invalid.append(
                _InvalidReceipt(
                    "receipt_timestamp_in_future",
                    receipt.receipt_id,
                    receipt.finished_at,
                )
            )
            continue
        if receipt.data_through is not None:
            try:
                data_through_utc = _data_through_in_utc(
                    receipt.data_through,
                    dataset.timezone,
                )
            except ValueError:
                data_through_utc = None
            if (
                data_through_utc is not None
                and data_through_utc > now_utc
                and dataset.entity_type != "trade_calendar"
            ):
                invalid.append(
                    _InvalidReceipt(
                        "data_through_in_future",
                        receipt.receipt_id,
                        receipt.finished_at,
                    )
                )
                continue
        current_receipts.append(receipt)
    return current_receipts, invalid


def _validated_history_for_dataset_rows(
    dataset: DatasetDefinition,
    *,
    known_dataset_ids: frozenset[str],
    rows: tuple[_ScannedIngestRunRow, ...],
    now: datetime,
) -> tuple[tuple[ValidatedReceiptHistoryEntry, ...], tuple[str, ...]]:
    receipts, rejected = _trusted_receipts_for_evidence(
        dataset,
        now=now,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        expected_binding=None,
    )
    if rejected:
        return (), tuple(sorted({item.reason for item in rejected}))
    by_execution: dict[str, list[_Receipt]] = {}
    for receipt in receipts:
        by_execution.setdefault(receipt.execution_id, []).append(receipt)
    cohort_statuses = {
        execution_id: _variant_cohort_terminal(dataset, members).status
        for execution_id, members in by_execution.items()
    }
    entries = tuple(
        ValidatedReceiptHistoryEntry(
            dataset_id=dataset.dataset_id,
            provider=receipt.provider,
            receipt_id=receipt.receipt_id,
            status=receipt.status,  # type: ignore[arg-type]
            cohort_status=cohort_statuses[receipt.execution_id],
            started_at=receipt.started_sort,
            finished_at=receipt.finished_sort,
            request_window=receipt.request_window,
            request_variant=receipt.request_variant,
            execution_id=receipt.execution_id,
            config_hash=receipt.config_hash,
            errors=receipt.errors,
            cursor_contract_version=receipt.cursor_contract_version,
            frozen_universe_sha256=receipt.frozen_universe_sha256,
            batch_index=receipt.batch_index,
            batch_count=receipt.batch_count,
            batch_values_sha256=receipt.batch_values_sha256,
            physical_call_index=receipt.physical_call_index,
            retry_index=receipt.retry_index,
            data_through=receipt.data_through,
            receipt_proof_sha256=_receipt_proof_sha256(receipt, dataset.dataset_id),
        )
        for receipt in receipts
    )
    return tuple(sorted(entries, key=lambda entry: (entry.provider, entry.finished_at, entry.receipt_id))), ()


def validated_receipt_histories_by_dataset(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> ValidatedReceiptHistories:
    """Return immutable planner history and dataset-local authority failures."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    _canonical_now(now)
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    entries_by_dataset: dict[str, tuple[ValidatedReceiptHistoryEntry, ...]] = {}
    failures_by_dataset: dict[str, tuple[str, ...]] = {}
    for dataset in registry.datasets:
        entries, failures = _validated_history_for_dataset_rows(
            dataset,
            known_dataset_ids=known_dataset_ids,
            rows=_scan_ingest_run_rows_for_dataset_authority(
                conn,
                dataset_id=dataset.dataset_id,
                known_dataset_ids=known_dataset_ids,
            ),
            now=now,
        )
        if failures:
            failures_by_dataset[dataset.dataset_id] = failures
        else:
            entries_by_dataset[dataset.dataset_id] = entries
    return ValidatedReceiptHistories(
        entries_by_dataset=MappingProxyType(
            {
                dataset_id: tuple(
                    sorted(
                        entries,
                        key=lambda entry: (
                            entry.provider,
                            entry.finished_at,
                            entry.receipt_id,
                        ),
                    )
                )
                for dataset_id, entries in sorted(entries_by_dataset.items())
            }
        ),
        failures_by_dataset=MappingProxyType(
            dict(sorted(failures_by_dataset.items()))
        ),
    )


def validated_receipt_history_for_dataset(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    *,
    now: datetime,
) -> ValidatedReceiptHistories:
    """Validate one dataset without scanning unrelated receipt histories."""

    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    _canonical_now(now)
    validated_now = now
    try:
        registered_dataset = registry.resolve(dataset.dataset_id)
    except KeyError:
        raise RuntimeProjectionError("dataset is not registered") from None
    if registered_dataset != dataset:
        raise RuntimeProjectionError("dataset definition is not the registered authority")
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    rows = _scan_ingest_run_rows_for_dataset_authority(
        conn,
        dataset_id=dataset.dataset_id,
        known_dataset_ids=known_dataset_ids,
    )
    entries, failures = _validated_history_for_dataset_rows(
        dataset,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        now=validated_now,
    )
    if failures:
        return ValidatedReceiptHistories(
            entries_by_dataset=MappingProxyType({}),
            failures_by_dataset=MappingProxyType({dataset.dataset_id: failures}),
        )
    return ValidatedReceiptHistories(
        entries_by_dataset=MappingProxyType({dataset.dataset_id: entries}),
        failures_by_dataset=MappingProxyType({}),
    )


def _receipt_error_layer(
    error_codes: tuple[str, ...],
    validation_reasons: tuple[str, ...],
) -> str | None:
    if validation_reasons:
        return "receipt_validation"
    if "resource_budget" in error_codes:
        return "request_resource_budget"
    if "rate_limited" in error_codes:
        return "transport_retry"
    if "transport_error" in error_codes:
        return "transport"
    if "validation_failed" in error_codes:
        return "ingest_validation"
    if any(code in {"provider_error", "permission_denied"} for code in error_codes):
        return "provider_response"
    if "storage_failed" in error_codes:
        return "storage"
    if "config_error" in error_codes:
        return "configuration"
    return None


def _journal_entries_for_rows(
    registry: DatasetRegistry,
    dataset_id: str,
    receipt_ids: tuple[str, ...],
    *,
    now: datetime,
    rows: tuple[_ScannedIngestRunRow, ...],
) -> tuple[ReceiptJournalEntry, ...]:
    dataset = registry.resolve(dataset_id)
    wanted = frozenset(receipt_ids)
    receipts, rejected = _trusted_receipts_for_evidence(
        dataset,
        now=now,
        known_dataset_ids=frozenset(item.dataset_id for item in registry.datasets),
        rows=rows,
        expected_binding=None,
    )
    invalid_reasons: dict[str, set[str]] = {}
    for invalid in rejected:
        if invalid.receipt_id in wanted:
            invalid_reasons.setdefault(invalid.receipt_id, set()).add(
                invalid.reason  # type: ignore[arg-type]
            )
    entries: list[ReceiptJournalEntry] = []
    for receipt in receipts:
        if receipt.receipt_id not in wanted or receipt.receipt_id in invalid_reasons:
            continue
        entries.append(
            ReceiptJournalEntry(
                receipt_id=receipt.receipt_id,
                status=receipt.status,  # type: ignore[arg-type]
                counts=receipt.counts,
                error_layer=_receipt_error_layer(receipt.errors, ()),
                error_codes=receipt.errors,
                validation_reasons=(),
            )
        )
    for receipt_id, reason_set in invalid_reasons.items():
        reasons = tuple(sorted(reason_set))
        entries.append(
            ReceiptJournalEntry(
                receipt_id=receipt_id,
                status="invalid",
                counts=None,
                error_layer=_receipt_error_layer((), reasons),
                error_codes=(),
                validation_reasons=reasons,
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.receipt_id))


def validated_receipt_journal_entries_by_dataset(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    receipt_ids_by_dataset: Mapping[str, tuple[str, ...]],
    *,
    now: datetime,
) -> Mapping[str, tuple[ReceiptJournalEntry, ...]]:
    """Project selected receipt rows from one bounded authority snapshot."""

    if not isinstance(receipt_ids_by_dataset, Mapping):
        raise TypeError("receipt_ids_by_dataset must be a mapping")
    known_dataset_ids = {dataset.dataset_id for dataset in registry.datasets}
    if any(dataset_id not in known_dataset_ids for dataset_id in receipt_ids_by_dataset):
        raise ValueError("receipt_ids_by_dataset contains an undeclared dataset")
    if any(
        type(receipt_ids) is not tuple
        or any(type(receipt_id) is not str or not receipt_id for receipt_id in receipt_ids)
        for receipt_ids in receipt_ids_by_dataset.values()
    ):
        raise TypeError("receipt_ids_by_dataset values must be tuples of receipt IDs")
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    return MappingProxyType(
        {
            dataset_id: _journal_entries_for_rows(
                registry,
                dataset_id,
                receipt_ids,
                now=now,
                rows=_scan_ingest_run_rows_for_dataset_authority(
                    conn,
                    dataset_id=dataset_id,
                    known_dataset_ids=known_dataset_ids,
                ),
            )
            for dataset_id, receipt_ids in receipt_ids_by_dataset.items()
            if receipt_ids
        }
    )


def validated_receipt_journal_entries(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset_id: str,
    receipt_ids: tuple[str, ...],
    *,
    now: datetime,
) -> tuple[ReceiptJournalEntry, ...]:
    """Project selected receipt rows without exposing receipt payloads."""

    if type(dataset_id) is not str or not dataset_id:
        raise TypeError("dataset_id must be a non-empty string")
    return validated_receipt_journal_entries_by_dataset(
        conn,
        registry,
        {dataset_id: receipt_ids},
        now=now,
    ).get(dataset_id, ())


def validated_receipt_history(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> tuple[ValidatedReceiptHistoryEntry, ...]:
    """Return fully validated receipt history or fail closed on any invalid row."""

    histories = validated_receipt_histories_by_dataset(conn, registry, now=now)
    if histories.failures_by_dataset:
        raise RuntimeProjectionError("receipt history contains invalid authority")
    return tuple(
        entry
        for entries in histories.entries_by_dataset.values()
        for entry in entries
    )


def validated_success_receipt_ids(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    provider_binding: ProviderBinding,
    *,
    now: datetime,
) -> frozenset[str]:
    """Return success IDs only after the full projection receipt validator.

    Generic fanout uses this narrow surface rather than reimplementing a weaker
    receipt parser. Any malformed receipt related to the source dataset makes
    the complete source authority unavailable.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    if provider_binding not in dataset.provider_bindings:
        raise ValueError("provider_binding must belong to dataset")
    _canonical_now(now)
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    receipts, invalid = _trusted_receipts_for_evidence(
        dataset,
        now=now,
        known_dataset_ids=known_dataset_ids,
        rows=_scan_ingest_run_rows_for_dataset_authority(
            conn,
            dataset_id=dataset.dataset_id,
            known_dataset_ids=known_dataset_ids,
        ),
        expected_binding=provider_binding,
    )
    if invalid:
        raise RuntimeProjectionError("receipt authority contains invalid evidence")
    return frozenset(
        receipt.receipt_id
        for receipt in _complete_success_receipts(receipts, dataset)
    )


def validated_row_receipt_proofs(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    dataset: DatasetDefinition,
    receipt_ids: object,
    *,
    now: datetime,
) -> Mapping[str, ValidatedRowReceiptProof]:
    """Join bounded provider row receipt IDs to validated immutable facts.

    The helper never reads provider payloads and never selects a latest receipt
    as a substitute for a row's own receipt. Any missing, failed, or mismatched
    authority rejects the bounded join. ``receipt_proof_sha256`` is derived
    only from validated dataset/provider/receipt/execution/config/window,
    data-through, timestamps, and request-variant facts; credentials, raw
    provider values, and payloads are excluded.
    """

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    try:
        registered_dataset = registry.resolve(dataset.dataset_id)
    except KeyError:
        raise RuntimeProjectionError("dataset is not registered") from None
    if registered_dataset != dataset:
        raise RuntimeProjectionError("dataset definition is not the registered authority")
    if type(receipt_ids) not in {tuple, list, set, frozenset}:
        raise TypeError("receipt_ids must be a bounded collection")
    requested = tuple(receipt_ids)
    if not requested or len(requested) > registry.query_defaults.max_page_size:
        raise ValueError("receipt_ids exceeds bounded query page size")
    if any(type(receipt_id) is not str or not receipt_id for receipt_id in requested):
        raise ValueError("receipt_ids must contain non-empty strings")
    if len(set(requested)) != len(requested):
        raise ValueError("receipt_ids must be unique")
    _canonical_now(now)
    known_dataset_ids = frozenset(item.dataset_id for item in registry.datasets)
    selected_rows = _scan_ingest_run_rows_by_ids(conn, requested)
    selected_receipts: list[_Receipt] = []
    for scanned in selected_rows:
        validated = _validate_receipt_row(
            scanned, dataset, known_dataset_ids, now, None
        )
        if not isinstance(validated, _Receipt):
            raise RuntimeProjectionError("row receipt authority is invalid")
        selected_receipts.append(validated)
    execution_ids = tuple(
        sorted({receipt.execution_id for receipt in selected_receipts})
    )
    cohort_rows = _scan_ingest_run_rows_by_execution_ids(
        conn, dataset.dataset_id, execution_ids
    )
    entries, failures = _validated_history_for_dataset_rows(
        dataset,
        known_dataset_ids=known_dataset_ids,
        rows=cohort_rows,
        now=now,
    )
    if failures:
        raise RuntimeProjectionError("receipt authority contains invalid evidence")
    by_id = {
        entry.receipt_id: entry
        for entry in entries
    }
    result: dict[str, ValidatedRowReceiptProof] = {}
    for receipt_id in requested:
        entry = by_id.get(receipt_id)
        if (
            entry is None
            or entry.dataset_id != dataset.dataset_id
            or entry.status != "success"
            or entry.cohort_status != "success"
            or type(entry.receipt_proof_sha256) is not str
            or not _is_sha256(entry.receipt_proof_sha256)
            or type(entry.finished_at) is not datetime
        ):
            raise RuntimeProjectionError("row receipt proof is unavailable")
        result[receipt_id] = ValidatedRowReceiptProof(
            receipt_id=entry.receipt_id,
            dataset_id=entry.dataset_id,
            provider=entry.provider,
            status="success",
            execution_id=entry.execution_id,
            config_hash=entry.config_hash,
            request_window=MappingProxyType(dict(entry.request_window)),
            data_through=entry.data_through,
            finished_at=entry.finished_at,
            receipt_proof_sha256=entry.receipt_proof_sha256,
        )
    return MappingProxyType(dict(sorted(result.items())))


def project_dataset_runtime_evidence(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    registry: DatasetRegistry | None = None,
    provider_binding: ProviderBinding | None = None,
    evidence_as_of: datetime | None = None,
    data_through_as_of: datetime | None = None,
    receipt_collection_window: tuple[datetime, datetime] | None = None,
    request_partition: tuple[str, str] | None = None,
    validation_cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"]
    | None = None,
) -> DatasetRuntimeEvidence:
    """Return one projection and typed lineage evidence from one receipt scan.

    ``evidence_as_of`` is an observation cutoff, not a provider-row timestamp.
    When present, only complete receipt executions whose collection interval and
    data watermark are at or before their respective cutoffs can attest to
    returned rows. ``data_through_as_of`` defaults to ``evidence_as_of``. An
    optional ``receipt_collection_window`` bounds the success IDs exposed to
    an as-of row query to collection intervals overlapping that window.
    Omitting all cutoffs preserves the current read projection exactly. An exact
    ``request_partition`` narrows receipt authority to the matching immutable
    request window.  It is deliberately opt-in: unbounded/range queries keep
    the dataset-wide fail-closed projection.

    Long-lived API services should pass the same process-wide
    ``validation_cache`` they already hand to :func:`_project_dataset_runtime`;
    every receipt scan in this module re-validates the full append-only run
    history, so without the shared memo each row query pays the whole-history
    canonicalization cost again (issue #297).
    """

    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    if (
        provider_binding is not None
        and provider_binding not in dataset.provider_bindings
    ):
        raise ValueError("provider_binding must belong to dataset")
    if evidence_as_of is not None and (
        not isinstance(evidence_as_of, datetime)
        or evidence_as_of.tzinfo is None
        or evidence_as_of.utcoffset() is None
    ):
        raise ValueError("evidence_as_of must be a timezone-aware datetime")
    if data_through_as_of is not None and (
        evidence_as_of is None
        or not isinstance(data_through_as_of, datetime)
        or data_through_as_of.tzinfo is None
        or data_through_as_of.utcoffset() is None
    ):
        raise ValueError(
            "data_through_as_of requires a timezone-aware evidence_as_of"
        )
    if receipt_collection_window is not None:
        if (
            evidence_as_of is None
            or type(receipt_collection_window) is not tuple
            or len(receipt_collection_window) != 2
            or any(
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
                for value in receipt_collection_window
            )
        ):
            raise ValueError(
                "receipt_collection_window requires two aware datetimes and "
                "evidence_as_of"
            )
        receipt_window_start, receipt_window_end = (
            value.astimezone(timezone.utc) for value in receipt_collection_window
        )
        if (
            receipt_window_start > receipt_window_end
            or receipt_window_end > evidence_as_of.astimezone(timezone.utc)
        ):
            raise ValueError("receipt_collection_window is outside evidence_as_of")
    if request_partition is not None and (
        type(request_partition) is not tuple
        or len(request_partition) != 2
        or any(type(value) is not str or not value for value in request_partition)
    ):
        raise ValueError("request_partition must be a non-empty string pair")
    known_dataset_ids = (
        frozenset(item.dataset_id for item in registry.datasets)
        if registry is not None
        else frozenset({dataset.dataset_id})
    )
    if registry is not None:
        try:
            if registry.resolve(dataset.dataset_id) != dataset:
                raise RuntimeProjectionError("dataset definition is not the registered authority")
        except KeyError:
            raise RuntimeProjectionError("dataset is not registered") from None
        rows = _scan_ingest_run_rows_for_dataset_authority(
            conn,
            dataset_id=dataset.dataset_id,
            known_dataset_ids=known_dataset_ids,
        )
    else:
        rows = _scan_ingest_run_rows(conn)
    projection_now = now
    if evidence_as_of is not None:
        cutoff = evidence_as_of.astimezone(timezone.utc)
        data_cutoff = (
            cutoff
            if data_through_as_of is None
            else data_through_as_of.astimezone(timezone.utc)
        )
        receipts_at_read_time, invalid_at_read_time = _trusted_receipts_for_evidence(
            dataset,
            now=now,
            known_dataset_ids=known_dataset_ids,
            rows=rows,
            expected_binding=provider_binding,
            validation_cache=validation_cache,
        )
        if invalid_at_read_time:
            raise RuntimeProjectionError(
                "receipt authority contains invalid evidence"
            )
        receipts_by_execution: dict[str, list[_Receipt]] = {}
        for receipt in receipts_at_read_time:
            receipts_by_execution.setdefault(receipt.execution_id, []).append(receipt)
        eligible_receipt_ids: set[str] = set()
        for execution_receipts in receipts_by_execution.values():
            execution_is_eligible = True
            for receipt in execution_receipts:
                if receipt.started_sort > cutoff or receipt.finished_sort > cutoff:
                    execution_is_eligible = False
                    break
                if receipt.data_through is not None:
                    try:
                        data_through = _data_through_in_utc(
                            receipt.data_through,
                            dataset.timezone,
                        )
                    except ValueError:
                        execution_is_eligible = False
                        break
                    if data_through > data_cutoff:
                        execution_is_eligible = False
                        break
            if execution_is_eligible:
                eligible_receipt_ids.update(
                    receipt.receipt_id for receipt in execution_receipts
                )
        rows = tuple(
            row
            for row in rows
            if row.payload is not None
            and row.payload.get("receipt_id") in eligible_receipt_ids
        )
        projection_now = cutoff
    if request_partition is not None:
        request_partition_key, request_partition_value = request_partition
        scoped_rows: list[_ScannedIngestRunRow] = []
        for row in rows:
            validated = _validate_receipt_row_memoized(
                row,
                dataset,
                known_dataset_ids,
                projection_now,
                provider_binding,
                validation_cache,
            )
            # Invalid source evidence remains dataset-fatal.  Only a validated
            # receipt from another complete partition may be excluded.
            if not isinstance(validated, _Receipt) or (
                validated.request_window.get(request_partition_key)
                == request_partition_value
            ):
                scoped_rows.append(row)
        rows = tuple(scoped_rows)
    config_hash_cache: dict[tuple[int, int], str] = {}
    predecessor = _partition_declaration_predecessor(dataset)
    projection_dataset = dataset
    if receipt_collection_window is not None and (
        dataset.point_in_time == "append_only"
        and dataset.as_of_format == "rfc3339"
        and dataset.range_field is not None
        and dataset.partition_field == dataset.range_field
    ):
        projection_receipts, projection_invalid = _trusted_receipts_for_evidence(
            dataset,
            now=projection_now,
            known_dataset_ids=known_dataset_ids,
            rows=rows,
            expected_binding=provider_binding,
            validation_cache=validation_cache,
        )
        if projection_invalid:
            raise RuntimeProjectionError(
                "receipt authority contains invalid evidence"
            )
        active_receipts = [
            receipt
            for receipt in projection_receipts
            if _receipt_matches_active_config(
                receipt,
                dataset,
                provider_binding,
                config_hash_cache,
            )
        ]
        predecessor_receipts = [
            receipt
            for receipt in projection_receipts
            if _receipt_matches_partition_declaration_predecessor(
                receipt,
                predecessor,
                provider_binding,
                config_hash_cache,
            )
        ]
        active_watermark = _success_watermark_receipt(active_receipts, dataset)
        predecessor_watermark = _success_watermark_receipt(
            predecessor_receipts,
            dataset,
        )
        if predecessor_watermark is not None and (
            active_watermark is None
            or _data_through_in_utc(
                predecessor_watermark.data_through,
                dataset.timezone,
            )
            > _data_through_in_utc(
                active_watermark.data_through,
                dataset.timezone,
            )
        ):
            projection_dataset = predecessor

    projection = _project_dataset_runtime(
        conn,
        projection_dataset,
        now=projection_now,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        expected_binding=provider_binding,
        validation_cache=validation_cache,
    )
    receipts, invalid = _trusted_receipts_for_evidence(
        dataset,
        now=projection_now,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        expected_binding=provider_binding,
        validation_cache=validation_cache,
    )
    authority_receipts = [
        receipt
        for receipt in receipts
        if _receipt_matches_active_config(
            receipt,
            projection_dataset,
            provider_binding,
            config_hash_cache,
        )
    ]
    successful = list(_complete_success_receipts(authority_receipts, dataset))
    as_of_authority_receipts = authority_receipts
    if receipt_collection_window is not None:
        as_of_authority_receipts = [
            receipt
            for receipt in receipts
            if _receipt_matches_active_config(
                receipt,
                dataset,
                provider_binding,
                config_hash_cache,
            )
            or _receipt_matches_partition_declaration_predecessor(
                receipt,
                predecessor,
                provider_binding,
                config_hash_cache,
            )
        ]
    as_of_successful = list(
        _complete_success_receipts(as_of_authority_receipts, dataset)
    )
    if receipt_collection_window is not None:
        receipt_window_start, receipt_window_end = (
            value.astimezone(timezone.utc) for value in receipt_collection_window
        )
        assert evidence_as_of is not None
        cutoff = evidence_as_of.astimezone(timezone.utc)
        as_of_successful = [
            receipt
            for receipt in as_of_successful
            if receipt.started_sort <= receipt_window_end
            and receipt.finished_sort >= receipt_window_start
            and receipt.finished_sort <= cutoff
        ]
    last_success = _success_watermark_receipt(authority_receipts, dataset) or max(
        successful,
        key=_success_sort_key,
        default=None,
    )

    current_status: str | None = None
    current_providers: tuple[str, ...] = ()
    current_provider_config_hashes: tuple[tuple[str, str], ...] = ()
    current_receipt_ids: tuple[str, ...] = ()
    if (
        not invalid
        and projection.state not in {"paused", "unobserved"}
        and authority_receipts
    ):
        if evidence_as_of is None:
            latest = _effective_latest_terminal(
                dataset, authority_receipts, last_success, projection_now
            )
        else:
            # Historical as-of reads keep the strict latest-terminal semantics.
            latest = _latest_run_terminal(dataset, authority_receipts)
        current_status = latest.status
        current_execution = latest.receipts
        current_providers = tuple(sorted({receipt.provider for receipt in current_execution}))
        current_receipt_ids = tuple(
            sorted({receipt.receipt_id for receipt in current_execution})
        )
        if request_partition is not None and successful:
            # Exact-partition rows accumulate across repeated complete success
            # runs of the same partition (delta upserts keep their original
            # receipt binding).  Include every complete success receipt so the
            # partition-scoped read authority covers accumulated valid rows,
            # not only the latest run's terminal receipts.
            current_receipt_ids = tuple(
                sorted(
                    {
                        receipt.receipt_id
                        for receipt in current_execution
                    }
                    | {receipt.receipt_id for receipt in successful}
                )
            )
        current_provider_config_hashes = tuple(
            sorted(
                {
                    (receipt.provider, receipt.config_hash)
                    for receipt in current_execution
                    if type(receipt.config_hash) is str
                }
            )
        )

    last_success_providers: tuple[str, ...] = ()
    last_success_provider_config_hashes: tuple[tuple[str, str], ...] = ()
    last_success_receipt_ids: tuple[str, ...] = ()
    if last_success is not None:
        last_success_execution = tuple(
            receipt
            for receipt in authority_receipts
            if receipt.execution_id == last_success.execution_id
        )
        last_success_providers = tuple(
            sorted({receipt.provider for receipt in last_success_execution})
        )
        last_success_provider_config_hashes = tuple(
            sorted(
                {
                    (receipt.provider, receipt.config_hash)
                    for receipt in last_success_execution
                    if type(receipt.config_hash) is str
                }
            )
        )
        last_success_receipt_ids = tuple(
            sorted({receipt.receipt_id for receipt in last_success_execution})
        )
    return DatasetRuntimeEvidence(
        projection=projection,
        current_receipt_status=current_status,
        current_providers=current_providers,
        last_success_receipt_id=(
            None if last_success is None else last_success.receipt_id
        ),
        last_success_providers=last_success_providers,
        last_success_data_through=(
            None if last_success is None else last_success.data_through
        ),
        current_provider_config_hashes=current_provider_config_hashes,
        last_success_provider_config_hashes=last_success_provider_config_hashes,
        current_receipt_ids=current_receipt_ids,
        last_success_receipt_ids=last_success_receipt_ids,
        as_of_success_receipt_ids=(
            ()
            if evidence_as_of is None
            else tuple(sorted({receipt.receipt_id for receipt in as_of_successful}))
        ),
    )


def _projection_entry(projection: DatasetRuntimeProjection) -> dict[str, object]:
    return {
        "dataset_id": projection.dataset_id,
        "state": projection.state,
        "degraded": projection.degraded,
        "data_through": projection.data_through,
        "observed_at": projection.observed_at,
        "receipt_id": projection.receipt_id,
        "reasons": list(projection.reasons),
    }


def _canonical_now(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _project_registry_datasets(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
    validation_cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"]
    | None = None,
) -> tuple[
    tuple[DatasetRuntimeProjection, ...],
    frozenset[str],
    tuple[_ScannedIngestRunRow, ...],
    Mapping[str, frozenset[str]],
]:
    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    known_dataset_ids = frozenset(dataset.dataset_id for dataset in registry.datasets)
    rows = _scan_recent_ingest_run_rows(
        conn,
        per_dataset_limit=_MAX_INGEST_RUN_SCAN_ROWS_PER_DATASET,
    )
    seed_rows = rows
    expanded = list(seed_rows)
    seen_rows = {row.raw for row in seed_rows}
    read_budget = _ReceiptReadBudget(_MAX_INGEST_RUN_SCAN_ROWS - len(seed_rows))
    complete_execution_ids: dict[str, frozenset[str]] = {}
    # Any selected execution may have older siblings outside a full source
    # window. Do not trust unverified sibling chronology or text timestamp
    # ordering to guess that only the oldest visible execution was truncated.
    by_source: dict[str, list[_ScannedIngestRunRow]] = {}
    for row in seed_rows:
        source = row.raw[9]
        if type(source) is str and source in known_dataset_ids:
            by_source.setdefault(source, []).append(row)
    for dataset_id, source_rows in by_source.items():
        if len(source_rows) < _MAX_INGEST_RUN_SCAN_ROWS_PER_DATASET:
            continue
        dataset = registry.resolve(dataset_id)
        execution_ids = frozenset(
            validated.execution_id
            for row in source_rows
            if isinstance((validated := _validate_receipt_row_memoized(
                row, dataset, known_dataset_ids, now, None, validation_cache
            )), _Receipt)
        )
        if not execution_ids:
            continue
        siblings = _scan_ingest_run_rows_by_execution_ids(
            conn, dataset_id, tuple(sorted(execution_ids)), read_budget=read_budget
        )
        complete_execution_ids[dataset_id] = execution_ids
        for row in siblings:
            if row.raw not in seen_rows:
                expanded.append(row)
                seen_rows.add(row.raw)
    rows = tuple(expanded)
    related_rows: dict[str, list[_ScannedIngestRunRow]] = {
        dataset_id: [] for dataset_id in known_dataset_ids
    }
    for scanned in rows:
        # _validate_receipt_row only relates a row to its envelope source or
        # claimed payload dataset.  Index those two identities once instead of
        # presenting every recent receipt to every registry dataset.
        candidate_ids: set[str] = set()
        source = scanned.raw[9]
        if type(source) is str and source in known_dataset_ids:
            candidate_ids.add(source)
        if scanned.payload is not None:
            payload_dataset_id = scanned.payload.get("dataset_id")
            if (
                type(payload_dataset_id) is str
                and payload_dataset_id in known_dataset_ids
            ):
                candidate_ids.add(payload_dataset_id)
        for dataset_id in candidate_ids:
            related_rows[dataset_id].append(scanned)
    projections = tuple(
        _project_dataset_runtime(
            conn,
            dataset,
            now=now,
            known_dataset_ids=known_dataset_ids,
            rows=tuple(related_rows[dataset.dataset_id]),
            validation_cache=validation_cache,
            complete_execution_ids=complete_execution_ids.get(dataset.dataset_id, frozenset()),
        )
        for dataset in registry.datasets
    )
    return projections, known_dataset_ids, rows, MappingProxyType(complete_execution_ids)


def project_catalog_runtime(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
    validation_cache: dict[tuple[str, str], "_Receipt | _InvalidReceipt | None"]
    | None = None,
) -> dict[str, object]:
    """Project only the dataset runtime rows required by ``GET /v1/catalog``.

    Interface-level projections are for the broader runtime report and are not
    part of the catalog response.  Keeping them out of this path preserves the
    same dataset facts while avoiding a second receipt validation pass for each
    provider binding.
    """

    projections, _known_dataset_ids, _rows, _complete = _project_registry_datasets(
        conn, registry, now=now, validation_cache=validation_cache
    )
    return {
        "datasets": {
            projection.dataset_id: _projection_entry(projection)
            for projection in projections
        }
    }


def project_registry_runtime(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> dict[str, object]:
    """Project every declared dataset and derive all summary fields from it."""

    generated_at = _canonical_now(now)
    projections, known_dataset_ids, rows, complete_execution_ids = _project_registry_datasets(
        conn, registry, now=now
    )
    state_counts = {
        state: sum(projection.state == state for projection in projections)
        for state in (
            "success",
            "empty",
            "unobserved",
            "paused",
            "failed",
            "stale",
        )
    }
    summary = {
        "expected": len(projections),
        "observed": sum(
            projection.state not in {"unobserved", "paused"}
            for projection in projections
        ),
        "success": state_counts["success"],
        "empty": state_counts["empty"],
        "unobserved": state_counts["unobserved"],
        "paused": state_counts["paused"],
        "failed": state_counts["failed"],
        "stale": state_counts["stale"],
        "degraded": sum(projection.degraded for projection in projections),
    }
    if summary["failed"] or summary["stale"]:
        overall_status = "red"
    elif summary["empty"] or summary["unobserved"] or summary["paused"]:
        overall_status = "yellow"
    else:
        overall_status = "green"

    datasets = {
        projection.dataset_id: _projection_entry(projection)
        for projection in projections
    }
    interfaces: dict[str, dict[str, object]] = {}
    unobserved_api_names: list[str] = []
    paused_api_names: list[str] = []
    for dataset in registry.datasets:
        for binding in dataset.provider_bindings:
            projection = _project_dataset_runtime(
                conn,
                dataset,
                now=now,
                known_dataset_ids=known_dataset_ids,
                rows=rows,
                expected_binding=binding,
                complete_execution_ids=complete_execution_ids.get(dataset.dataset_id, frozenset()),
            )
            interface_name = (
                binding.api_name
                if binding.provider == "tushare"
                else f"{binding.provider}:{binding.api_name}"
            )
            entry = _projection_entry(projection)
            entry.update(
                {
                    "source": f"{binding.provider}:{binding.api_name}",
                    "provider": binding.provider,
                    "provider_api": binding.api_name,
                }
            )
            interfaces[interface_name] = entry
            if projection.state == "unobserved":
                unobserved_api_names.append(interface_name)
            elif projection.state == "paused":
                paused_api_names.append(interface_name)

    return {
        "report_version": "tradingdatas.interface_runtime.v1",
        "authority": "sqlite_ingest_receipts",
        "status": overall_status,
        "generated_at": generated_at,
        "summary": summary,
        "unobserved_api_names": sorted(unobserved_api_names),
        "paused_api_names": sorted(paused_api_names),
        "datasets": datasets,
        "interfaces": dict(sorted(interfaces.items())),
    }


def _file_identity(metadata: os.stat_result) -> _FileIdentity:
    return metadata.st_dev, metadata.st_ino, metadata.st_mode


def _validated_parent_chain(db_path: Path) -> tuple[_FileIdentity, ...]:
    identities: list[_FileIdentity] = []
    for parent in reversed(db_path.parents):
        try:
            metadata = parent.lstat()
        except OSError:
            raise RuntimeProjectionError(
                "receipt database parent chain is unavailable"
            ) from None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeProjectionError("receipt database parent chain is unavailable")
        identities.append(_file_identity(metadata))
    return tuple(identities)


def _validated_regular_file_prefix(
    path: Path,
    length: int,
    *,
    unavailable_message: str,
) -> tuple[_FileIdentity, os.stat_result, bytes]:
    try:
        metadata = path.lstat()
    except OSError:
        raise RuntimeProjectionError(unavailable_message) from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeProjectionError(unavailable_message)

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeProjectionError("receipt database binding is unavailable")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise RuntimeProjectionError(unavailable_message) from None
    try:
        opened_metadata = os.fstat(descriptor)
        opened_identity = _file_identity(opened_metadata)
        if opened_identity != _file_identity(metadata) or not stat.S_ISREG(
            opened_metadata.st_mode
        ):
            raise RuntimeProjectionError("receipt database binding changed")
        prefix = os.read(descriptor, length)
    finally:
        os.close(descriptor)
    return opened_identity, opened_metadata, prefix


def _validated_database_identity(
    db_path: Path,
) -> tuple[_FileIdentity, os.stat_result, bytes]:
    opened_identity, metadata, header = _validated_regular_file_prefix(
        db_path,
        100,
        unavailable_message="receipt database is unavailable",
    )
    if len(header) < 100 or not header.startswith(_SQLITE_HEADER):
        raise RuntimeProjectionError("receipt database is unreadable")
    return opened_identity, metadata, header


def _sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return (
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    )


def _validated_sidecar_binding(
    db_path: Path,
    *,
    main_metadata: os.stat_result,
    main_header: bytes,
) -> tuple[_FileIdentity | None, _FileIdentity | None]:
    wal_path, shm_path = _sidecar_paths(db_path)
    wal_exists = wal_path.exists() or wal_path.is_symlink()
    shm_exists = shm_path.exists() or shm_path.is_symlink()
    if wal_exists != shm_exists:
        raise RuntimeProjectionError("receipt database sidecar set is incomplete")
    if not wal_exists:
        return None, None

    wal_identity, wal_metadata, wal_header = _validated_regular_file_prefix(
        wal_path,
        32,
        unavailable_message="receipt database WAL is unavailable",
    )
    shm_identity, shm_metadata, shm_header = _validated_regular_file_prefix(
        shm_path,
        100,
        unavailable_message="receipt database SHM is unavailable",
    )
    if len(shm_header) != 100:
        raise RuntimeProjectionError("receipt database sidecars are unreadable")

    main_page_size = int.from_bytes(main_header[16:18], "big")
    if main_page_size == 1:
        main_page_size = 65_536
    byte_order = "<" if sys.byteorder == "little" else ">"
    shm_one = struct.unpack(f"{byte_order}III BB H II 2I 2I 2I", shm_header[:48])
    shm_two = struct.unpack(f"{byte_order}III BB H II 2I 2I 2I", shm_header[48:96])
    mx_frame = int(shm_one[6])
    n_backfill = int.from_bytes(shm_header[96:100], sys.byteorder)
    if len(wal_header) == 0:
        # SQLite keeps both sidecar names after a TRUNCATE checkpoint while
        # resetting WAL to zero bytes and the SHM index to its empty epoch.
        # No frame can be read from a zero-byte WAL, so accept only that exact
        # state; a truncated live WAL retains mx_frame/backfill evidence and
        # remains fail-closed below.
        if (
            main_header[18:20] != b"\x02\x02"
            or shm_one != shm_two
            or shm_one[0] != 3_007_000
            or shm_one[3] != 1
            or shm_one[5] != 0
            or mx_frame != 0
            or n_backfill != 0
        ):
            raise RuntimeProjectionError("receipt database sidecars are inconsistent")
        return wal_identity, shm_identity
    if len(wal_header) != 32:
        raise RuntimeProjectionError("receipt database sidecars are unreadable")

    wal_magic, wal_version, wal_page_size = struct.unpack(">III", wal_header[:12])
    committed_bytes = 32 + mx_frame * (24 + main_page_size)
    if (
        main_header[18:20] != b"\x02\x02"
        or wal_magic not in {0x377F0682, 0x377F0683}
        or wal_version != 3_007_000
        or wal_page_size != main_page_size
        or shm_one != shm_two
        or shm_one[0] != wal_version
        or shm_one[3] != 1
        or shm_one[5] != main_page_size
        or wal_header[16:24] != shm_header[32:40]
        or wal_metadata.st_size < committed_bytes
        or shm_metadata.st_size < 100
        or n_backfill > mx_frame
    ):
        raise RuntimeProjectionError("receipt database sidecars are inconsistent")
    if mx_frame > n_backfill and main_metadata.st_mtime_ns > wal_metadata.st_mtime_ns:
        raise RuntimeProjectionError("receipt database sidecars are stale")
    return wal_identity, shm_identity


def _validated_database_binding(db_path: Path) -> _ReceiptDatabaseBinding:
    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    candidate = Path(os.path.abspath(os.fspath(db_path)))
    parent_identities = _validated_parent_chain(candidate)
    database_identity, main_metadata, main_header = _validated_database_identity(
        candidate
    )
    wal_identity, shm_identity = _validated_sidecar_binding(
        candidate,
        main_metadata=main_metadata,
        main_header=main_header,
    )
    if parent_identities != _validated_parent_chain(candidate):
        raise RuntimeProjectionError("receipt database binding changed")
    observed_identity, observed_metadata, observed_header = (
        _validated_database_identity(candidate)
    )
    observed_wal, observed_shm = _validated_sidecar_binding(
        candidate,
        main_metadata=observed_metadata,
        main_header=observed_header,
    )
    if database_identity != observed_identity:
        raise RuntimeProjectionError("receipt database binding changed")
    if (wal_identity, shm_identity) != (observed_wal, observed_shm):
        raise RuntimeProjectionError("receipt database binding changed")
    return _ReceiptDatabaseBinding(
        canonical_path=candidate,
        parent_identities=parent_identities,
        database_identity=database_identity,
        wal_identity=wal_identity,
        shm_identity=shm_identity,
    )


def _require_unchanged_database_binding(
    expected: _ReceiptDatabaseBinding,
) -> None:
    try:
        observed = _validated_database_binding(expected.canonical_path)
    except (OSError, RuntimeProjectionError, TypeError, ValueError):
        raise RuntimeProjectionError("receipt database binding changed") from None
    if observed != expected:
        raise RuntimeProjectionError("receipt database binding changed")


def _current_regular_identity(path: Path) -> _FileIdentity:
    try:
        metadata = path.lstat()
    except OSError:
        raise RuntimeProjectionError("receipt database binding changed") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeProjectionError("receipt database binding changed")
    return _file_identity(metadata)


def _require_bound_path_identities(expected: _ReceiptDatabaseBinding) -> None:
    if _current_regular_identity(expected.canonical_path) != expected.database_identity:
        raise RuntimeProjectionError("receipt database binding changed")
    wal_path, shm_path = _sidecar_paths(expected.canonical_path)
    if expected.wal_identity is None and (
        wal_path.exists()
        or wal_path.is_symlink()
        or shm_path.exists()
        or shm_path.is_symlink()
    ):
        raise RuntimeProjectionError("receipt database binding changed")
    observed_wal = (
        _current_regular_identity(wal_path)
        if expected.wal_identity is not None
        else None
    )
    observed_shm = (
        _current_regular_identity(shm_path)
        if expected.shm_identity is not None
        else None
    )
    if (observed_wal, observed_shm) != (
        expected.wal_identity,
        expected.shm_identity,
    ):
        raise RuntimeProjectionError("receipt database binding changed")


def _expected_provider_indexes_snapshot(
    observed: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Expected provider-row index map, tolerating a missing coverage index.

    Stores created before ``provider_dataset_rows_coverage_idx`` keep passing
    the read-only snapshot validation; a present index must still match its
    declared column order exactly.
    """

    expected = dict(PROVIDER_DATASET_ROWS_INDEX_COLUMNS)
    if "provider_dataset_rows_coverage_idx" not in observed:
        expected.pop("provider_dataset_rows_coverage_idx", None)
    return expected


def _open_bound_receipt_database_ro(
    binding: _ReceiptDatabaseBinding,
) -> sqlite3.Connection:
    try:
        # ``immutable=1`` skips WAL and can serve a stale main-file snapshot.
        # Sidecar presence is the production signal to open ``mode=ro`` only.
        immutable = "" if binding.wal_identity is not None else "&immutable=1"
        conn = sqlite3.connect(
            f"{binding.canonical_path.as_uri()}?mode=ro{immutable}",
            uri=True,
            timeout=1.0,
        )
        _require_bound_path_identities(binding)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")
        conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        table_info = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute(
                "PRAGMA main.table_xinfo('market_ingest_runs')"
            ).fetchall()
        )
        table_entries = tuple(
            tuple(row)
            for row in conn.execute(
                "PRAGMA main.table_list('market_ingest_runs')"
            ).fetchall()
        )
        primary_indexes = [
            row
            for row in conn.execute("PRAGMA index_list(market_ingest_runs)").fetchall()
            if int(row[2]) == 1 and str(row[3]) == "pk"
        ]
        primary_columns = (
            tuple(
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                    (str(primary_indexes[0][1]),),
                ).fetchall()
            )
            if len(primary_indexes) == 1
            else ()
        )
        provider_table_info = tuple(
            tuple(row)
            for row in conn.execute(
                "PRAGMA main.table_xinfo('provider_dataset_rows')"
            ).fetchall()
        )
        provider_table_entries = tuple(
            tuple(row)
            for row in conn.execute(
                "PRAGMA main.table_list('provider_dataset_rows')"
            ).fetchall()
        )
        provider_indexes = {
            str(row[1]): tuple(
                str(column[0])
                for column in conn.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                    (str(row[1]),),
                ).fetchall()
            )
            for row in conn.execute(
                "PRAGMA main.index_list('provider_dataset_rows')"
            ).fetchall()
            if str(row[3]) == "c"
        }
        authority_tables = {
            str(row[1])
            for row in conn.execute("PRAGMA main.table_list").fetchall()
            if str(row[0]) == "main"
            and str(row[2]) == "table"
            and not str(row[1]).startswith("sqlite_")
        }
        if (
            table_info != _EXPECTED_INGEST_RUN_TABLE_INFO
            or primary_columns != _INGEST_RUN_CONTRACT.primary_key
            or len(table_entries) != 1
            or str(table_entries[0][0]) != "main"
            or str(table_entries[0][1]) != "market_ingest_runs"
            or str(table_entries[0][2]) != "table"
            or int(table_entries[0][3]) != len(_INGEST_RUN_CONTRACT.columns)
            or int(table_entries[0][4]) != 0
            or int(table_entries[0][5]) != 0
            or provider_table_info != _EXPECTED_PROVIDER_DATASET_ROWS_TABLE_INFO
            or len(provider_table_entries) != 1
            or str(provider_table_entries[0][0]) != "main"
            or str(provider_table_entries[0][1]) != PROVIDER_DATASET_ROWS_TABLE
            or str(provider_table_entries[0][2]) != "table"
            or int(provider_table_entries[0][3]) != len(PROVIDER_DATASET_ROWS_COLUMNS)
            or int(provider_table_entries[0][4]) != 0
            or int(provider_table_entries[0][5]) != 0
            or provider_indexes != _expected_provider_indexes_snapshot(
                provider_indexes
            )
            or authority_tables != {PROVIDER_DATASET_ROWS_TABLE, "market_ingest_runs"}
        ):
            raise RuntimeProjectionError("receipt database schema is unavailable")
        conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()
        _require_bound_path_identities(binding)
        return conn
    except RuntimeProjectionError:
        if "conn" in locals():
            conn.close()
        raise
    except sqlite3.Error:
        if "conn" in locals():
            conn.close()
        raise RuntimeProjectionError("receipt database is unreadable") from None


def _open_receipt_database_ro(
    db_path: Path,
) -> tuple[sqlite3.Connection, _ReceiptDatabaseBinding]:
    binding = _validated_database_binding(db_path)
    return _open_bound_receipt_database_ro(binding), binding


def _connection_epoch_evidence(conn: sqlite3.Connection) -> tuple[object, ...]:
    """Return bounded, stable evidence that two connections opened one DB epoch."""

    pragmas = tuple(
        int(conn.execute(f"PRAGMA {name}").fetchone()[0])
        for name in (
            "schema_version",
            "user_version",
            "application_id",
            "page_count",
            "freelist_count",
        )
    )
    receipt_summary = conn.execute(
        """
        SELECT COUNT(*),
               COALESCE(MIN(run_id), ''),
               COALESCE(MAX(run_id), ''),
               COALESCE(SUM(rows_read), 0),
               COALESCE(SUM(rows_written), 0),
               COALESCE(SUM(length(CAST(run_id AS BLOB))), 0),
               COALESCE(SUM(length(CAST(started_at AS BLOB))), 0),
               COALESCE(SUM(length(CAST(finished_at AS BLOB))), 0),
               COALESCE(SUM(length(CAST(status AS BLOB))), 0),
               COALESCE(SUM(length(CAST(source AS BLOB))), 0),
               COALESCE(SUM(length(CAST(notes AS BLOB))), 0)
        FROM market_ingest_runs
        """
    ).fetchone()
    if receipt_summary is None:
        raise RuntimeProjectionError("receipt database epoch is unavailable")
    return (*pragmas, *tuple(receipt_summary))


@contextmanager
def open_verified_read_model_snapshot(db_path: Path):
    """Yield one canonical read transaction under the clean-slate authority lock.

    Under WAL, two read connections opened back-to-back can observe different
    ``page_count``/``freelist_count``/receipt-summary evidence when a concurrent
    writer commits between them — a transient epoch skew, not a database swap.
    The bind-then-verify step is therefore retried a bounded number of times;
    the verified snapshot is still strictly required before any row is served.
    """

    last_error: RuntimeProjectionError | None = None
    try:
        for _ in range(_SNAPSHOT_READER_MAX_ATTEMPTS):
            try:
                with sqlite_authority_lock(
                    db_path,
                    mode="shared",
                    create=False,
                    timeout=_SNAPSHOT_READER_LOCK_TIMEOUT_SECONDS,
                ):
                    conn, binding = _open_receipt_database_ro(db_path)
                    try:
                        primary_evidence = _connection_epoch_evidence(conn)
                        verifier: sqlite3.Connection | None = None
                        try:
                            verifier = _open_bound_receipt_database_ro(binding)
                            if _connection_epoch_evidence(verifier) != primary_evidence:
                                raise RuntimeProjectionError(
                                    "receipt database connection target changed"
                                )
                            verifier.commit()
                        finally:
                            if verifier is not None:
                                verifier.close()
                        yield conn
                        conn.commit()
                    finally:
                        conn.close()
                return
            except RuntimeProjectionError as exc:
                # A concurrent writer (backfill) leaves the WAL/SHM sidecars in
                # transient mid-write states; any of those reads as a projection
                # error.  Retry a bounded number of times; a persistent error is
                # still raised fail-closed after the attempts are exhausted.
                last_error = exc
                time.sleep(0.05)
    except PermissionError:
        # QueryAccessDenied inherits PermissionError (an OSError subclass) and
        # must propagate as a 403, not be folded into a 503 projection error.
        raise
    except (
        OSError,
        SqliteAuthorityLockError,
        TimeoutError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ):
        raise RuntimeProjectionError("receipt projection failed closed") from None
    raise last_error  # type: ignore[misc]


def load_interface_runtime_report(
    db_path: Path,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> dict[str, object]:
    """Open SQLite in read-only mode and project the current registry."""

    with open_verified_read_model_snapshot(db_path) as conn:
        return project_registry_runtime(conn, registry, now=now)


def load_dataset_runtime_projection(
    db_path: Path,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    registry: DatasetRegistry | None = None,
    provider_binding: ProviderBinding | None = None,
) -> DatasetRuntimeProjection:
    """Load one current dataset projection from read-only SQLite authority."""

    with open_verified_read_model_snapshot(db_path) as conn:
        known_dataset_ids = (
            frozenset(item.dataset_id for item in registry.datasets)
            if registry is not None
            else frozenset({dataset.dataset_id})
        )
        return _project_dataset_runtime(
            conn,
            dataset,
            now=now,
            known_dataset_ids=known_dataset_ids,
            rows=(
                _scan_ingest_run_rows_for_dataset_authority(
                    conn,
                    dataset_id=dataset.dataset_id,
                    known_dataset_ids=known_dataset_ids,
                )
                if registry is not None
                else _scan_ingest_run_rows(conn)
            ),
            expected_binding=provider_binding,
        )


def write_interface_runtime_cache(
    report: Mapping[str, object],
    output_path: Path,
) -> None:
    """Atomically write one optional diagnostic projection cache."""

    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    if not isinstance(output_path, Path):
        raise TypeError("output_path must be pathlib.Path")
    payload = (
        json.dumps(
            dict(report),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(
        f"{output_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        descriptor = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temp_path, output_path)
        directory_descriptor = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def rebuild_interface_runtime_cache(
    db_path: Path,
    registry: DatasetRegistry,
    output_path: Path,
    *,
    now: datetime,
) -> None:
    """Rebuild the optional JSON cache exclusively from SQLite authority."""

    report = load_interface_runtime_report(db_path, registry, now=now)
    write_interface_runtime_cache(report, output_path)
