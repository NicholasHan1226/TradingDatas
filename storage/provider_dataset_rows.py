"""Lossless provider-native SQLite facts with atomic ingest receipts.

The canonical SQLite DDL lives in :mod:`storage.schema_contract`.  Runtime
writers still open an existing SQLite database in read/write mode and fail
closed when the generic table is absent; they never create or migrate schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from dataset_registry import DatasetDefinition, ProviderBinding
from storage.ingest_receipts import (
    IngestContext,
    IngestCounts,
    IngestResult,
    insert_ingest_receipt_with_evidence,
    make_receipt_id,
    require_receipt_evidence_readback,
    require_unchanged_sqlite_binding,
    validated_existing_sqlite_binding,
)
from storage.schema_contract import (
    PROVIDER_DATASET_ROWS_COLUMNS,
    PROVIDER_DATASET_ROWS_TABLE,
    get_table,
    require_clean_sqlite_authority_schema,
)
from storage.sqlite_authority_lock import sqlite_authority_lock


_EXPECTED_PROVIDER_TABLE_INFO = tuple(
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
_INGEST_RUN_CONTRACT = get_table("market_ingest_runs")
_INGEST_RUN_PRIMARY_KEY_POSITIONS = {
    name: index for index, name in enumerate(_INGEST_RUN_CONTRACT.primary_key, start=1)
}
_EXPECTED_INGEST_TABLE_INFO = tuple(
    (
        index,
        column.name,
        {"text": "TEXT", "integer": "INTEGER"}[column.logical_type],
        int(not column.nullable),
        None,
        _INGEST_RUN_PRIMARY_KEY_POSITIONS.get(column.name, 0),
        0,
    )
    for index, column in enumerate(_INGEST_RUN_CONTRACT.columns)
)
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_SAFE_PROVIDER_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_YYYYMMDD = re.compile(r"[0-9]{8}\Z")
_RFC3339 = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9])(?:\.(?P<fraction>[0-9]{1,6}))?"
    r"(?:(?P<zulu>Z)|(?P<offset_sign>[+-])"
    r"(?P<offset_hour>[01][0-9]|2[0-3]):"
    r"(?P<offset_minute>[0-5][0-9]))\Z"
)


class ProviderNativeAdmissionError(ValueError):
    """A provider batch cannot enter the generic authority unchanged."""

    def __init__(self, message: str, *, error_code: str = "validation_failed"):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class _PreparedProviderRow:
    row_key: str
    observed_at: str | None
    partition_value: str | None
    payload_json: str
    payload_hash: str
    quality_state: str
    quality_issues_json: str


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ProviderNativeAdmissionError(
            "provider row is not valid canonical JSON"
        ) from exc


def _validate_json_value(value: object, *, depth: int, max_depth: int) -> None:
    if depth > max_depth:
        raise ProviderNativeAdmissionError(
            "provider row exceeds max_nesting_depth",
            error_code="resource_budget",
        )
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProviderNativeAdmissionError("provider row contains NaN or Infinity")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProviderNativeAdmissionError(
                    "provider row object keys must be strings"
                )
            _validate_json_value(item, depth=depth + 1, max_depth=max_depth)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1, max_depth=max_depth)
        return
    raise ProviderNativeAdmissionError(
        f"provider row contains non-JSON value type {type(value).__name__}"
    )


def _matches_logical_type(value: object, logical_type: str) -> bool:
    if logical_type == "text":
        return isinstance(value, str)
    if logical_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if logical_type == "float":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
    return False


def matches_declared_provider_time(value: object, as_of_format: str) -> bool:
    """Return whether one raw provider value satisfies the registry time format."""

    if type(value) is not str:
        return False
    if as_of_format == "yyyymmdd":
        if _YYYYMMDD.fullmatch(value) is None:
            return False
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            return False
        return parsed.strftime("%Y%m%d") == value
    if as_of_format != "rfc3339":
        return False
    match = _RFC3339.fullmatch(value)
    if match is None:
        return False
    if (
        match.group("offset_sign") == "-"
        and match.group("offset_hour") == "00"
        and match.group("offset_minute") == "00"
    ):
        return False
    fraction = match.group("fraction") or ""
    microsecond = int(fraction.ljust(6, "0")) if fraction else 0
    try:
        datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
            microsecond,
        )
    except ValueError:
        return False
    return True


def _unknown_field_issue(field_name: str) -> str:
    if _SAFE_PROVIDER_FIELD.fullmatch(field_name) is not None:
        return f"unknown_field:{field_name}"
    digest = hashlib.sha256(field_name.encode("utf-8")).hexdigest()
    return f"unknown_field_sha256:{digest}"


def _quality_issues(
    dataset: DatasetDefinition,
    payload: Mapping[str, object],
) -> list[str]:
    fields = {field.name: field for field in dataset.fields}
    issues: set[str] = set()
    for field_name, field in fields.items():
        if field_name not in payload:
            issues.add(f"missing_field:{field_name}")
            continue
        value = payload[field_name]
        if value is None:
            if not field.nullable:
                issues.add(f"null_not_allowed:{field_name}")
            continue
        if not _matches_logical_type(value, field.logical_type):
            issues.add(f"type_mismatch:{field_name}:{field.logical_type}")
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and not (_INT64_MIN <= value <= _INT64_MAX)
        ):
            issues.add(f"integer_out_of_int64:{field_name}")
    for field_name in payload:
        if field_name not in fields:
            issues.add(_unknown_field_issue(field_name))
    if dataset.as_of_field is not None:
        value = payload.get(dataset.as_of_field)
        if value is not None and not matches_declared_provider_time(
            value,
            dataset.as_of_format or "",
        ):
            issues.add(
                f"time_format_mismatch:{dataset.as_of_field}:{dataset.as_of_format}"
            )
    return sorted(issues)


def _technical_text(
    payload: Mapping[str, object], field_name: str | None
) -> str | None:
    if field_name is None or field_name not in payload:
        return None
    value = payload[field_name]
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return _canonical_json(value)
    return None


def _snapshot_key(
    dataset: DatasetDefinition,
    payload: Mapping[str, object],
    payload_hash: str,
    issues: list[str],
) -> str:
    key_items: list[list[object]] = []
    fields = {field.name: field for field in dataset.fields}
    for field_name in dataset.primary_key:
        if field_name not in payload:
            issues.append(f"snapshot_key_fallback:missing:{field_name}")
            return f"payload:{payload_hash}"
        value = payload[field_name]
        if value is None:
            issues.append(f"snapshot_key_fallback:null:{field_name}")
            return f"payload:{payload_hash}"
        if isinstance(value, (dict, list, tuple)):
            issues.append(f"snapshot_key_fallback:non_scalar:{field_name}")
            return f"payload:{payload_hash}"
        field = fields[field_name]
        if field.logical_type == "text" and value == "":
            issues.append(f"snapshot_key_fallback:blank:{field_name}")
            return f"payload:{payload_hash}"
        if not _matches_logical_type(value, field.logical_type):
            issues.append(f"snapshot_key_fallback:type_mismatch:{field_name}")
            return f"payload:{payload_hash}"
        key_items.append([field_name, value])
    key_payload = _canonical_json(["provider-primary-key.v1", key_items])
    return f"primary:{hashlib.sha256(key_payload.encode('utf-8')).hexdigest()}"


def _prepare_rows(
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[_PreparedProviderRow, ...]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise TypeError("rows must be a non-string sequence")
    if not rows:
        raise ProviderNativeAdmissionError(
            "empty provider results require a terminal empty receipt"
        )
    budgets = (
        binding.max_rows_per_attempt,
        binding.max_payload_bytes_per_row,
        binding.max_batch_bytes,
        binding.max_nesting_depth,
    )
    if any(value is None for value in budgets):
        raise ProviderNativeAdmissionError("generic binding budgets are incomplete")
    max_rows, max_row_bytes, max_batch_bytes, max_depth = budgets
    assert max_rows is not None
    assert max_row_bytes is not None
    assert max_batch_bytes is not None
    assert max_depth is not None
    if (
        (binding.fanout is None or binding.fanout.strategy == "none")
        and len(rows) > max_rows
    ):
        raise ProviderNativeAdmissionError(
            "provider batch exceeds max_rows_per_attempt",
            error_code="resource_budget",
        )

    prepared: list[_PreparedProviderRow] = []
    # Exact canonical JSON array framing: opening/closing brackets and commas.
    batch_bytes = 2
    stable_payloads: dict[str, str] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise ProviderNativeAdmissionError("every provider row must be a mapping")
        payload = dict(raw_row)
        _validate_json_value(payload, depth=0, max_depth=max_depth)
        payload_json = _canonical_json(payload)
        payload_bytes = len(payload_json.encode("utf-8"))
        if payload_bytes > max_row_bytes:
            raise ProviderNativeAdmissionError(
                "provider row exceeds max_payload_bytes_per_row",
                error_code="resource_budget",
            )
        batch_bytes += payload_bytes + (1 if prepared else 0)
        if batch_bytes > max_batch_bytes:
            raise ProviderNativeAdmissionError(
                "provider batch exceeds max_batch_bytes",
                error_code="resource_budget",
            )
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        issues = _quality_issues(dataset, payload)
        if dataset.point_in_time == "append_only":
            row_key = f"payload:{payload_hash}"
        else:
            row_key = _snapshot_key(dataset, payload, payload_hash, issues)
            if row_key.startswith("primary:"):
                prior_hash = stable_payloads.setdefault(row_key, payload_hash)
                if prior_hash != payload_hash:
                    raise ProviderNativeAdmissionError(
                        "same attempt contains conflicting payloads for one stable key"
                    )
        issues = sorted(set(issues))
        prepared.append(
            _PreparedProviderRow(
                row_key=row_key,
                observed_at=_technical_text(payload, dataset.as_of_field),
                partition_value=_technical_text(payload, dataset.partition_field),
                payload_json=payload_json,
                payload_hash=payload_hash,
                quality_state="degraded" if issues else "valid",
                quality_issues_json=_canonical_json(issues),
            )
        )
    return tuple(prepared)


def _require_generic_contract(
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    context: IngestContext,
) -> None:
    adapter = dataset.read_model_adapter
    if adapter.storage_kind != "provider_native_rows":
        raise ValueError("dataset is not configured for provider_native_rows")
    if adapter.primary_table != PROVIDER_DATASET_ROWS_TABLE:
        raise ValueError("generic dataset primary table is invalid")
    if binding not in dataset.provider_bindings:
        raise ValueError("binding does not belong to dataset")
    expected_context = (
        dataset.dataset_id,
        binding.provider,
        binding.api_name,
        binding.adapter_version,
    )
    observed_context = (
        context.dataset_id,
        context.provider,
        context.provider_api,
        context.adapter_version,
    )
    if observed_context != expected_context:
        raise ValueError("ingest context does not match registry binding")


def _require_existing_table(conn: sqlite3.Connection) -> None:
    provider_rows = tuple(
        tuple(row)
        for row in conn.execute(
            "PRAGMA main.table_xinfo('provider_dataset_rows')"
        ).fetchall()
    )
    receipt_rows = tuple(
        tuple(row)
        for row in conn.execute(
            "PRAGMA main.table_xinfo('market_ingest_runs')"
        ).fetchall()
    )
    authority_tables = {
        str(row[1])
        for row in conn.execute("PRAGMA main.table_list").fetchall()
        if str(row[0]) == "main"
        and str(row[2]) == "table"
        and not str(row[1]).startswith("sqlite_")
    }
    if provider_rows != _EXPECTED_PROVIDER_TABLE_INFO:
        raise RuntimeError("provider_dataset_rows table is missing or incompatible")
    if receipt_rows != _EXPECTED_INGEST_TABLE_INFO:
        raise RuntimeError("market_ingest_runs table is missing or incompatible")
    if authority_tables != {PROVIDER_DATASET_ROWS_TABLE, "market_ingest_runs"}:
        raise RuntimeError("SQLite authority contains unsupported tables")
    require_clean_sqlite_authority_schema(conn)


def validate_provider_dataset_store(db_path: Path) -> None:
    """Read-only preflight for the already-migrated generic SQLite authority."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        _require_existing_table(conn)
    finally:
        conn.close()


def _write_prepared_rows(
    conn: sqlite3.Connection,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    rows: Sequence[_PreparedProviderRow],
    receipt_id: str,
    collected_at: str,
) -> tuple[IngestCounts, dict[tuple[str, str, int, str], tuple[object, ...]]]:
    inserted = 0
    updated = 0
    unchanged = 0
    schema_major = dataset.schema_major
    expected_rows: dict[
        tuple[str, str, int, str],
        tuple[object, ...],
    ] = {}
    for row in rows:
        existing = conn.execute(
            """SELECT dataset_id, provider, schema_major,
                      ingested_schema_version, row_key, observed_at,
                      partition_value, payload_json, payload_hash,
                      quality_state, quality_issues_json, collected_at,
                      receipt_id, revision
               FROM provider_dataset_rows
               WHERE dataset_id = ? AND provider = ?
                 AND schema_major = ? AND row_key = ?""",
            (dataset.dataset_id, binding.provider, schema_major, row.row_key),
        ).fetchone()
        identity = (
            dataset.dataset_id,
            binding.provider,
            schema_major,
            row.row_key,
        )
        desired_content = (
            dataset.dataset_id,
            binding.provider,
            schema_major,
            dataset.schema_version,
            row.row_key,
            row.observed_at,
            row.partition_value,
            row.payload_json,
            row.payload_hash,
            row.quality_state,
            row.quality_issues_json,
        )
        if existing is None:
            cursor = conn.execute(
                """INSERT INTO provider_dataset_rows
                   (dataset_id, provider, schema_major, ingested_schema_version,
                    row_key, observed_at, partition_value, payload_json,
                    payload_hash, quality_state, quality_issues_json,
                    collected_at, receipt_id, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    dataset.dataset_id,
                    binding.provider,
                    schema_major,
                    dataset.schema_version,
                    row.row_key,
                    row.observed_at,
                    row.partition_value,
                    row.payload_json,
                    row.payload_hash,
                    row.quality_state,
                    row.quality_issues_json,
                    collected_at,
                    receipt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "provider fact insert did not affect exactly one row"
                )
            expected_rows[identity] = (
                *desired_content,
                collected_at,
                receipt_id,
                1,
            )
            inserted += 1
            continue
        existing_tuple = tuple(existing)
        if existing_tuple[:11] == desired_content:
            if dataset.point_in_time == "append_only":
                # An append-only identity already proves this exact immutable
                # payload at its first successful observation.  Rebinding the
                # row to a later identical overlap receipt destroys that
                # earlier row-to-receipt authority and makes a bounded as-of
                # replay impossible without inventing historical PIT state.
                # Keep the first provenance while still recording this
                # transaction's exact ``unchanged`` outcome in its receipt.
                expected_rows[identity] = existing_tuple
                unchanged += 1
                continue
            # Re-observing an identical current-snapshot payload is still a
            # new, successful provider observation.  Bind the fact to this
            # transaction's receipt so a current registry contract cannot be
            # left with a success receipt but no authoritative facts merely
            # because SQLite avoided a payload rewrite.  ``revision`` tracks
            # payload changes, so it deliberately remains unchanged here.
            cursor = conn.execute(
                """UPDATE provider_dataset_rows
                   SET collected_at = ?, receipt_id = ?
                   WHERE dataset_id = ? AND provider = ?
                     AND schema_major = ? AND row_key = ?""",
                (
                    collected_at,
                    receipt_id,
                    dataset.dataset_id,
                    binding.provider,
                    schema_major,
                    row.row_key,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "provider fact provenance refresh did not affect exactly one row"
                )
            expected_rows[identity] = (
                *desired_content,
                collected_at,
                receipt_id,
                int(existing_tuple[13]),
            )
            unchanged += 1
            continue
        if dataset.point_in_time != "current_snapshot":
            if (
                existing_tuple[3] == desired_content[3]
                and existing_tuple[7] == desired_content[7]
            ):
                # Append-only rows are keyed by payload hash, so a matching
                # row_key already proves the payload bytes.  The remaining
                # content columns are registry-derived (observed_at,
                # partition_value, quality_state) and can drift when the
                # registry metadata changes (for example ``partition_field``);
                # keep the first provenance as long as schema version and
                # payload are unchanged, instead of failing an idempotent
                # re-collection.
                expected_rows[identity] = existing_tuple
                unchanged += 1
                continue
            raise RuntimeError("append_only provider identity must not update")
        cursor = conn.execute(
            """UPDATE provider_dataset_rows
               SET ingested_schema_version = ?, observed_at = ?,
                   partition_value = ?, payload_json = ?, payload_hash = ?,
                   quality_state = ?, quality_issues_json = ?, collected_at = ?,
                   receipt_id = ?, revision = ?
               WHERE dataset_id = ? AND provider = ?
                 AND schema_major = ? AND row_key = ?""",
            (
                dataset.schema_version,
                row.observed_at,
                row.partition_value,
                row.payload_json,
                row.payload_hash,
                row.quality_state,
                row.quality_issues_json,
                collected_at,
                receipt_id,
                int(existing_tuple[13]) + 1,
                dataset.dataset_id,
                binding.provider,
                schema_major,
                row.row_key,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("provider fact update did not affect exactly one row")
        expected_rows[identity] = (
            *desired_content,
            collected_at,
            receipt_id,
            int(existing_tuple[13]) + 1,
        )
        updated += 1
    counts = IngestCounts(
        returned=len(rows),
        validated=len(rows),
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        rejected=0,
        committed=len(rows),
        count_semantics="exact_row_outcomes",
    )
    return counts, expected_rows


def _require_provider_fact_readback(
    conn: sqlite3.Connection,
    expected_rows: Mapping[
        tuple[str, str, int, str],
        tuple[object, ...],
    ],
) -> None:
    for identity, expected in expected_rows.items():
        observed = conn.execute(
            """SELECT dataset_id, provider, schema_major,
                      ingested_schema_version, row_key, observed_at,
                      partition_value, payload_json, payload_hash,
                      quality_state, quality_issues_json, collected_at,
                      receipt_id, revision
               FROM provider_dataset_rows
               WHERE dataset_id = ? AND provider = ?
                 AND schema_major = ? AND row_key = ?""",
            identity,
        ).fetchone()
        if observed is None or tuple(observed) != expected:
            raise RuntimeError("provider fact transaction readback is inconsistent")


def ingest_provider_native_rows(
    db_path: Path,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    rows: Sequence[Mapping[str, Any]],
    context: IngestContext,
) -> IngestResult:
    """Write one prevalidated provider attempt and one atomic success receipt."""

    if not isinstance(db_path, Path):
        raise TypeError("db_path must be pathlib.Path")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    if not isinstance(binding, ProviderBinding):
        raise TypeError("binding must be ProviderBinding")
    if not isinstance(context, IngestContext):
        raise TypeError("context must be IngestContext")
    _require_generic_contract(dataset, binding, context)
    prepared = _prepare_rows(dataset=dataset, binding=binding, rows=rows)
    receipt_id = make_receipt_id(context, PROVIDER_DATASET_ROWS_TABLE, 0)
    payload_fingerprint = hashlib.sha256(
        ("[" + ",".join(row.payload_json for row in prepared) + "]").encode("utf-8")
    ).hexdigest()

    with sqlite_authority_lock(
        db_path,
        mode="exclusive",
        create=True,
        timeout=180.0,
    ) as authority_lease:
        db_binding = validated_existing_sqlite_binding(db_path)
        conn = sqlite3.connect(
            f"{db_binding.canonical_path.as_uri()}?mode=rw",
            uri=True,
        )
        try:
            conn.execute("BEGIN IMMEDIATE")
            _require_existing_table(conn)
            require_unchanged_sqlite_binding(db_binding)
            counts, expected_rows = _write_prepared_rows(
                conn,
                dataset=dataset,
                binding=binding,
                rows=prepared,
                receipt_id=receipt_id,
                collected_at=context.started_at,
            )
            evidence = insert_ingest_receipt_with_evidence(
                conn,
                context=context,
                target_table=PROVIDER_DATASET_ROWS_TABLE,
                transaction_index=0,
                status="success",
                counts=counts,
                errors=(),
                payload_fingerprint=payload_fingerprint,
            )
            if evidence.receipt_id != receipt_id:
                raise RuntimeError("receipt identity changed during generic write")
            _require_provider_fact_readback(conn, expected_rows)
            require_receipt_evidence_readback(conn, evidence)
            require_unchanged_sqlite_binding(db_binding)
            authority_lease.validate()
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    return IngestResult(
        status="success",
        counts=counts,
        receipt_ids=(receipt_id,),
        errors=(),
    )
