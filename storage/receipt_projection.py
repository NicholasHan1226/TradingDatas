"""Project dataset runtime state from immutable SQLite ingest receipts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import struct
import sys
import uuid
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dataset_registry import DatasetDefinition, DatasetRegistry, ProviderBinding
from storage.ingest_receipts import (
    RECEIPT_SCHEMA_VERSION,
    UNMAPPED_TUSHARE_ADAPTER_VERSION,
    IngestContext,
    IngestCounts,
    make_unmapped_tushare_dataset_id,
    make_receipt_id,
)
from storage.read_model_store import (
    ReadModelLockError,
    read_model_snapshot_lock,
    read_model_snapshot_open_lock,
)
from storage.schema_contract import TYPE_MAP, get_table


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
        "unmapped_dataset",
        "validation_failed",
    }
)
_MAX_INGEST_RUN_SCAN_ROWS = 100_000
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
_SQLITE_HEADER = b"SQLite format 3\x00"
_FileIdentity = tuple[int, int, int]
_IngestRunRow = tuple[object, ...]


class RuntimeProjectionError(RuntimeError):
    """The SQLite receipt authority could not be read safely."""


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


@dataclass(frozen=True)
class _Receipt:
    receipt_id: str
    attempt_id: str
    started_at: str
    finished_at: str
    status: str
    provider: str
    data_through: str | None
    transaction_index: int
    errors: tuple[str, ...]
    started_sort: datetime
    finished_sort: datetime
    attempt_context: str


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
) -> tuple[_ScannedIngestRunRow, ...]:
    """Read one bounded, unfiltered authority snapshot or fail closed."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    scan_limit = _MAX_INGEST_RUN_SCAN_ROWS + 1
    raw_rows = tuple(
        tuple(row) for row in conn.execute(_RECEIPT_QUERY, (scan_limit,)).fetchall()
    )
    if len(raw_rows) == scan_limit:
        raise RuntimeProjectionError("receipt scan row budget exceeded")
    return tuple(_classify_ingest_run_row(row) for row in raw_rows)


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
        return scanned.invalid
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

    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return _InvalidReceipt("unknown_receipt_schema", receipt_id, observed_at)
    if not _related_to_dataset(payload, source, dataset.dataset_id):
        payload_dataset_id = payload.get("dataset_id")
        if type(source) is not str or type(payload_dataset_id) is not str:
            return _InvalidReceipt(
                "receipt_envelope_invalid",
                receipt_id,
                observed_at,
            )
        if source != payload_dataset_id:
            return _InvalidReceipt(
                "receipt_envelope_mismatch",
                receipt_id,
                observed_at,
            )
        if source not in known_dataset_ids:
            if _is_valid_unmapped_tushare_attempt(scanned, now=now):
                return None
            return _InvalidReceipt(
                "receipt_dataset_unknown",
                receipt_id,
                observed_at,
            )
        return None

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
    if status == "success":
        if type(target_table) is not str or target_table not in binding.target_tables:
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
    return _Receipt(
        receipt_id=run_id,
        attempt_id=attempt_id,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        provider=binding.provider,
        data_through=data_through,
        transaction_index=transaction_index,
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
                "request_window": dict(context.request_window),
                "started_at": context.started_at,
            }
        ),
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


def _attempt_sort_key(receipt: _Receipt) -> tuple[datetime, str]:
    return (receipt.started_sort, receipt.attempt_id)


def _success_sort_key(
    receipt: _Receipt,
) -> tuple[datetime, str, int, datetime, str]:
    return (
        receipt.started_sort,
        receipt.attempt_id,
        receipt.transaction_index,
        receipt.finished_sort,
        receipt.receipt_id,
    )


def _latest_attempt_receipt(receipts: list[_Receipt]) -> _Receipt:
    """Choose one attempt terminal before considering its chunk sequence."""

    latest_attempt = max(receipts, key=_attempt_sort_key)
    attempt_receipts = [
        receipt
        for receipt in receipts
        if receipt.attempt_id == latest_attempt.attempt_id
    ]
    terminal_receipts = [
        receipt for receipt in attempt_receipts if receipt.status in {"empty", "failed"}
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
        attempt_receipts,
        key=lambda receipt: (
            receipt.transaction_index,
            receipt.finished_sort,
            receipt.receipt_id,
        ),
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


def _data_through_in_utc(value: str, timezone_name: str) -> datetime:
    try:
        dataset_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise ValueError("dataset_timezone_invalid") from None

    candidate = value.strip()
    if len(candidate) == 8 and candidate.isdigit():
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


def _project_dataset_runtime(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    known_dataset_ids: frozenset[str],
    rows: tuple[_ScannedIngestRunRow, ...],
    expected_binding: ProviderBinding | None = None,
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
        validated = _validate_receipt_row(
            scanned_row,
            dataset,
            known_dataset_ids,
            now,
            expected_binding,
        )
        if isinstance(validated, _Receipt):
            receipts.append(validated)
        elif isinstance(validated, _InvalidReceipt):
            invalid.append(validated)

    now_utc = now.astimezone(timezone.utc)
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
            if data_through_utc is not None and data_through_utc > now_utc:
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

    invalid.extend(_attempt_context_failures(receipts))

    successful = [receipt for receipt in receipts if receipt.status == "success"]
    last_success = max(successful, key=_success_sort_key, default=None)
    if invalid:
        failure = max(invalid, key=_invalid_receipt_sort_key)
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=last_success.data_through if last_success else None,
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
    if not receipts:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="unobserved",
            degraded=True,
            data_through=None,
            observed_at=None,
            receipt_id=None,
            reasons=("no_recognized_receipt",),
        )

    latest = _latest_attempt_receipt(receipts)
    data_through = latest.data_through
    if data_through is None and last_success is not None:
        data_through = last_success.data_through
    if latest.status == "failed":
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=last_success.data_through if last_success else None,
            observed_at=latest.finished_at,
            receipt_id=latest.receipt_id,
            reasons=latest.errors,
        )
    if data_through is None:
        if latest.status == "empty":
            return DatasetRuntimeProjection(
                dataset_id=dataset.dataset_id,
                state="empty",
                degraded=False,
                data_through=None,
                observed_at=latest.finished_at,
                receipt_id=latest.receipt_id,
                reasons=("provider_returned_no_rows",),
            )
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=None,
            observed_at=latest.finished_at,
            receipt_id=latest.receipt_id,
            reasons=("invalid_data_through",),
        )
    try:
        data_through_utc = _data_through_in_utc(data_through, dataset.timezone)
    except ValueError as exc:
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="failed",
            degraded=True,
            data_through=data_through,
            observed_at=latest.finished_at,
            receipt_id=latest.receipt_id,
            reasons=(str(exc),),
        )

    is_stale = now_utc - data_through_utc > timedelta(
        seconds=dataset.freshness_sla_seconds
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
            observed_at=latest.finished_at,
            receipt_id=latest.receipt_id,
            reasons=reasons,
        )
    if latest.status == "empty":
        return DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="empty",
            degraded=False,
            data_through=data_through,
            observed_at=latest.finished_at,
            receipt_id=latest.receipt_id,
            reasons=("provider_returned_no_rows",),
        )
    return DatasetRuntimeProjection(
        dataset_id=dataset.dataset_id,
        state="success",
        degraded=False,
        data_through=data_through,
        observed_at=latest.finished_at,
        receipt_id=latest.receipt_id,
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
        rows=_scan_ingest_run_rows(conn),
        expected_binding=provider_binding,
    )


def _trusted_receipts_for_evidence(
    dataset: DatasetDefinition,
    *,
    now: datetime,
    known_dataset_ids: frozenset[str],
    rows: tuple[_ScannedIngestRunRow, ...],
    expected_binding: ProviderBinding | None,
) -> tuple[list[_Receipt], list[_InvalidReceipt]]:
    receipts: list[_Receipt] = []
    invalid: list[_InvalidReceipt] = []
    for scanned_row in rows:
        validated = _validate_receipt_row(
            scanned_row,
            dataset,
            known_dataset_ids,
            now,
            expected_binding,
        )
        if isinstance(validated, _Receipt):
            receipts.append(validated)
        elif isinstance(validated, _InvalidReceipt):
            invalid.append(validated)

    now_utc = now.astimezone(timezone.utc)
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
            if data_through_utc is not None and data_through_utc > now_utc:
                invalid.append(
                    _InvalidReceipt(
                        "data_through_in_future",
                        receipt.receipt_id,
                        receipt.finished_at,
                    )
                )
                continue
        current_receipts.append(receipt)
    invalid.extend(_attempt_context_failures(current_receipts))
    return current_receipts, invalid


def project_dataset_runtime_evidence(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    *,
    now: datetime,
    registry: DatasetRegistry | None = None,
    provider_binding: ProviderBinding | None = None,
) -> DatasetRuntimeEvidence:
    """Return one projection and typed lineage evidence from one receipt scan."""

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
    rows = _scan_ingest_run_rows(conn)
    projection = _project_dataset_runtime(
        conn,
        dataset,
        now=now,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        expected_binding=provider_binding,
    )
    receipts, invalid = _trusted_receipts_for_evidence(
        dataset,
        now=now,
        known_dataset_ids=known_dataset_ids,
        rows=rows,
        expected_binding=provider_binding,
    )
    successful = [receipt for receipt in receipts if receipt.status == "success"]
    last_success = max(successful, key=_success_sort_key, default=None)

    current_status: str | None = None
    current_providers: tuple[str, ...] = ()
    if not invalid and projection.state not in {"paused", "unobserved"} and receipts:
        latest = _latest_attempt_receipt(receipts)
        current_status = latest.status
        current_providers = tuple(
            sorted(
                {
                    receipt.provider
                    for receipt in receipts
                    if receipt.attempt_id == latest.attempt_id
                }
            )
        )

    last_success_providers: tuple[str, ...] = ()
    if last_success is not None:
        last_success_providers = tuple(
            sorted(
                {
                    receipt.provider
                    for receipt in successful
                    if receipt.attempt_id == last_success.attempt_id
                }
            )
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


def project_registry_runtime(
    conn: sqlite3.Connection,
    registry: DatasetRegistry,
    *,
    now: datetime,
) -> dict[str, object]:
    """Project every declared dataset and derive all summary fields from it."""

    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    generated_at = _canonical_now(now)
    known_dataset_ids = frozenset(dataset.dataset_id for dataset in registry.datasets)
    rows = _scan_ingest_run_rows(conn)
    projections = tuple(
        _project_dataset_runtime(
            conn,
            dataset,
            now=now,
            known_dataset_ids=known_dataset_ids,
            rows=rows,
        )
        for dataset in registry.datasets
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
        "report_version": "sharedsignals.interface_runtime.v2",
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
    if len(wal_header) != 32 or len(shm_header) != 100:
        raise RuntimeProjectionError("receipt database sidecars are unreadable")

    main_page_size = int.from_bytes(main_header[16:18], "big")
    if main_page_size == 1:
        main_page_size = 65_536
    wal_magic, wal_version, wal_page_size = struct.unpack(">III", wal_header[:12])
    byte_order = "<" if sys.byteorder == "little" else ">"
    shm_one = struct.unpack(f"{byte_order}III BB H II 2I 2I 2I", shm_header[:48])
    shm_two = struct.unpack(f"{byte_order}III BB H II 2I 2I 2I", shm_header[48:96])
    mx_frame = int(shm_one[6])
    n_backfill = int.from_bytes(shm_header[96:100], sys.byteorder)
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


def _open_bound_receipt_database_ro(
    binding: _ReceiptDatabaseBinding,
) -> sqlite3.Connection:
    try:
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
    """Yield one canonical read transaction under cooperative coordination locks."""

    try:
        with read_model_snapshot_lock(db_path):
            with ExitStack() as cleanup:
                with read_model_snapshot_open_lock(db_path):
                    conn, binding = _open_receipt_database_ro(db_path)
                    cleanup.callback(conn.close)
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
    except RuntimeProjectionError:
        raise
    except (
        OSError,
        ReadModelLockError,
        TimeoutError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ):
        raise RuntimeProjectionError("receipt projection failed closed") from None


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
            rows=_scan_ingest_run_rows(conn),
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
