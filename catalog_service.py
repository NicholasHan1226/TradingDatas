"""Provider-neutral catalog discovery over the canonical read model."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dataset_registry import DatasetDefinition, DatasetRegistry
from query_contract import (
    QueryAccessContext,
    QueryBudgetError,
    QueryValidationError,
    public_catalog_version,
)
from query_cursor import (
    CursorClaims,
    CursorConfigurationError,
    CursorExpectation,
    InvalidCursor,
    SignedCursorCodec,
)
from storage.receipt_projection import (
    RuntimeProjectionError,
    open_verified_read_model_snapshot,
    project_registry_runtime,
)

_RUNTIME_STATES = frozenset(
    {"success", "empty", "unobserved", "paused", "failed", "stale"}
)
_QUERYABILITY_REASONS = frozenset(
    {
        "json_functions_unavailable",
        "primary_table_unavailable",
        "query_columns_unavailable",
        "query_column_types_incompatible",
    }
)
_PROVIDER_NATIVE_STORAGE_KIND = "provider_native_rows"
_PROVIDER_NATIVE_TABLE = "provider_dataset_rows"
_PROVIDER_NATIVE_COLUMNS = {
    "dataset_id": "TEXT",
    "provider": "TEXT",
    "schema_major": "INTEGER",
    "ingested_schema_version": "TEXT",
    "row_key": "TEXT",
    "observed_at": "TEXT",
    "partition_value": "TEXT",
    "payload_json": "TEXT",
    "payload_hash": "TEXT",
    "quality_state": "TEXT",
    "quality_issues_json": "TEXT",
    "collected_at": "TEXT",
    "receipt_id": "TEXT",
    "revision": "INTEGER",
}
_AGGREGATE_SCOPES = frozenset({"external_read", "read", "full", "*"})
_RUNTIME_ROW_KEYS = frozenset(
    {
        "dataset_id",
        "state",
        "degraded",
        "data_through",
        "observed_at",
        "receipt_id",
        "reasons",
    }
)
_DATASET_ID_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z", re.ASCII)


def _canonical_public_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise QueryValidationError(f"{name} must be a canonical non-empty string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise QueryValidationError(f"{name} must be valid UTF-8 text") from None
    return value


def _canonical_filter(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _canonical_public_text(value, name)


@dataclass(frozen=True)
class CatalogFilters:
    market: str | None = None
    domain: str | None = None
    cadence: str | None = None
    state: str | None = None
    q: str | None = None

    def __post_init__(self) -> None:
        for name in ("market", "domain", "cadence", "state", "q"):
            object.__setattr__(self, name, _canonical_filter(getattr(self, name), name))
        if self.state is not None and self.state not in _RUNTIME_STATES:
            raise QueryValidationError(
                "state must be one of: empty, failed, paused, stale, success, "
                "unobserved"
            )


@dataclass(frozen=True)
class DatasetQueryability:
    queryable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.queryable) is not bool:
            raise TypeError("queryable must be a boolean")
        if type(self.reasons) is not tuple:
            raise TypeError("reasons must be a tuple")
        if any(type(reason) is not str for reason in self.reasons):
            raise TypeError("reasons must contain strings")
        if tuple(sorted(set(self.reasons))) != self.reasons or any(
            reason not in _QUERYABILITY_REASONS for reason in self.reasons
        ):
            raise ValueError("reasons must be sorted unique queryability enums")
        if self.queryable != (not self.reasons):
            raise ValueError("queryable must agree with reasons")


def is_initial_release_eligible(dataset: DatasetDefinition) -> bool:
    """Return the frozen structural discovery gate for the initial CN release."""

    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")
    return dataset.market == "CN" and any(
        binding.entitlement_state not in {"excluded", "retired"}
        for binding in dataset.provider_bindings
    )


def inspect_dataset_queryability(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
) -> DatasetQueryability:
    """Inspect the generic-query physical contract without changing SQLite."""

    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("conn must be sqlite3.Connection")
    if not isinstance(dataset, DatasetDefinition):
        raise TypeError("dataset must be DatasetDefinition")

    if (
        dataset.read_model_adapter.storage_kind != _PROVIDER_NATIVE_STORAGE_KIND
        or dataset.read_model_adapter.primary_table != _PROVIDER_NATIVE_TABLE
        or dataset.read_model_adapter.fixed_field_filters
        or any(
            binding.target_tables != (_PROVIDER_NATIVE_TABLE,)
            for binding in dataset.provider_bindings
        )
    ):
        return DatasetQueryability(False, ("primary_table_unavailable",))

    try:
        table_rows = conn.execute("PRAGMA main.table_list").fetchall()
        matching = [
            row
            for row in table_rows
            if len(row) >= 6 and row[0] == "main" and row[1] == _PROVIDER_NATIVE_TABLE
        ]
        if len(matching) != 1 or matching[0][2] != "table":
            return DatasetQueryability(False, ("primary_table_unavailable",))

        reasons: set[str] = set()

        column_rows = conn.execute(
            "SELECT name, type FROM pragma_table_xinfo(?, 'main')",
            (_PROVIDER_NATIVE_TABLE,),
        ).fetchall()
        columns = {
            name: declared_type
            for name, declared_type in column_rows
            if type(name) is str
        }
        if not set(_PROVIDER_NATIVE_COLUMNS).issubset(columns):
            reasons.add("query_columns_unavailable")
        for name, expected in _PROVIDER_NATIVE_COLUMNS.items():
            if name not in columns:
                continue
            actual = columns[name]
            if type(actual) is not str or actual.strip().upper() != expected:
                reasons.add("query_column_types_incompatible")
        try:
            json_probe = conn.execute(
                "SELECT json_valid('{}'), json_extract('{\"probe\":1}', '$.probe')"
            ).fetchone()
        except sqlite3.Error:
            reasons.add("json_functions_unavailable")
        else:
            if json_probe != (1, 1):
                reasons.add("json_functions_unavailable")
    except (KeyError, sqlite3.Error):
        raise RuntimeProjectionError(
            "catalog queryability inspection failed closed"
        ) from None

    normalized = tuple(sorted(reasons))
    return DatasetQueryability(not normalized, normalized)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _clock_seconds(now: datetime) -> int:
    if type(now) is not datetime or now.tzinfo is None:
        raise CursorConfigurationError("cursor validation clock is invalid")
    try:
        if now.utcoffset() is None:
            raise CursorConfigurationError("cursor validation clock is invalid")
        return math.floor(now.timestamp())
    except CursorConfigurationError:
        raise
    except (OverflowError, OSError, ValueError):
        raise CursorConfigurationError("cursor validation clock is invalid") from None


def _canonical_request_id(value: object) -> str:
    return _canonical_public_text(value, "request_id")


def _validated_limit(value: object, registry: DatasetRegistry) -> int:
    if type(value) is not int or value <= 0:
        raise QueryValidationError("limit must be a positive integer")
    if value > registry.query_defaults.max_page_size:
        raise QueryBudgetError(
            f"limit exceeds max_page_size={registry.query_defaults.max_page_size}"
        )
    return value


def _runtime_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise RuntimeProjectionError(f"catalog runtime {name} is invalid")
    return value


def _validated_runtime_row(
    runtime_rows: Mapping[str, object],
    dataset_id: str,
) -> dict[str, object]:
    row = runtime_rows.get(dataset_id)
    if type(row) is not dict or set(row) != _RUNTIME_ROW_KEYS:
        raise RuntimeProjectionError("catalog runtime row is unavailable")
    if row.get("dataset_id") != dataset_id:
        raise RuntimeProjectionError("catalog runtime row is invalid")
    state = row.get("state")
    if type(state) is not str or state not in _RUNTIME_STATES:
        raise RuntimeProjectionError("catalog runtime state is invalid")
    degraded = row.get("degraded")
    if type(degraded) is not bool:
        raise RuntimeProjectionError("catalog runtime degraded flag is invalid")
    raw_reasons = row.get("reasons")
    if type(raw_reasons) is not list:
        raise RuntimeProjectionError("catalog runtime reasons are invalid")
    reasons: list[str] = []
    for reason in raw_reasons:
        normalized = _runtime_text(reason, "reason")
        assert normalized is not None
        reasons.append(normalized)
    if len(reasons) != len(set(reasons)):
        raise RuntimeProjectionError("catalog runtime reasons are invalid")
    return {
        "state": state,
        "degraded": degraded,
        "data_through": _runtime_text(row.get("data_through"), "data_through"),
        "observed_at": _runtime_text(row.get("observed_at"), "observed_at"),
        "receipt_id": _runtime_text(row.get("receipt_id"), "receipt_id"),
        "reasons": reasons,
    }


def _has_catalog_scope(access: QueryAccessContext, dataset: DatasetDefinition) -> bool:
    grants = set(access.scopes)
    return dataset.required_scope in grants or bool(grants & _AGGREGATE_SCOPES)


def _matches_filters(
    dataset: DatasetDefinition,
    runtime: Mapping[str, object],
    filters: CatalogFilters,
) -> bool:
    if filters.market is not None and dataset.market != filters.market:
        return False
    if filters.domain is not None and dataset.domain != filters.domain:
        return False
    if filters.cadence is not None and dataset.cadence_class != filters.cadence:
        return False
    if filters.state is not None and runtime["state"] != filters.state:
        return False
    if filters.q is not None:
        needle = filters.q.casefold()
        searchable = (dataset.dataset_id, *dataset.aliases)
        if not any(needle in value.casefold() for value in searchable):
            return False
    return True


def _serialize_dataset(
    conn: sqlite3.Connection,
    dataset: DatasetDefinition,
    runtime: Mapping[str, object],
) -> dict[str, object]:
    queryability = inspect_dataset_queryability(conn, dataset)
    filter_operators = {
        field_name: list(operators)
        for field_name, operators in dataset.filter_operators.items()
    }
    return {
        "dataset_id": dataset.dataset_id,
        "aliases": list(dataset.aliases),
        "domain": dataset.domain,
        "market": dataset.market,
        "entity_type": dataset.entity_type,
        "data_classification": dataset.data_classification,
        "schema_version": dataset.schema_version,
        "schema_major": dataset.schema_major,
        "fields": [
            {
                "name": field.name,
                "logical_type": field.logical_type,
                "nullable": field.nullable,
                "selectable": field.selectable,
                "filterable": field.filterable,
                "sortable": field.sortable,
                "operators": list(filter_operators.get(field.name, ())),
            }
            for field in dataset.fields
        ],
        "default_fields": list(dataset.default_projection),
        "filter_operators": filter_operators,
        "sortable_fields": [field.name for field in dataset.fields if field.sortable],
        "default_order": [f"{field_name}:asc" for field_name in dataset.primary_key],
        "cadence": dataset.cadence_class,
        "timezone": dataset.timezone,
        "freshness_sla_seconds": dataset.freshness_sla_seconds,
        "limits": {
            "max_page_size": dataset.max_page_size,
            "max_lookback_days": dataset.max_lookback_days,
        },
        "point_in_time": dataset.point_in_time,
        "required_scope": dataset.required_scope,
        "quota_class": dataset.quota_class,
        "availability": {
            "entitlement_states": sorted(
                {binding.entitlement_state for binding in dataset.provider_bindings}
            ),
            "activation_states": sorted(
                {binding.activation_state for binding in dataset.provider_bindings}
            ),
        },
        "queryability": {
            "queryable": queryability.queryable,
            "reasons": list(queryability.reasons),
        },
        "runtime": {
            "state": runtime["state"],
            "degraded": runtime["degraded"],
            "data_through": runtime["data_through"],
            "observed_at": runtime["observed_at"],
            "receipt_id": runtime["receipt_id"],
            "reasons": list(runtime["reasons"]),
        },
    }


class CatalogService:
    """List access-visible registry datasets from one verified SQLite snapshot."""

    __slots__ = ("_registry", "_db_path", "_cursor_codec")

    def __init__(
        self,
        *,
        registry: DatasetRegistry,
        db_path: Path,
        cursor_codec: SignedCursorCodec,
    ) -> None:
        if not isinstance(registry, DatasetRegistry):
            raise TypeError("registry must be DatasetRegistry")
        if not isinstance(db_path, Path):
            raise TypeError("db_path must be pathlib.Path")
        canonical_path = Path(os.path.abspath(os.fspath(db_path)))
        if db_path != canonical_path:
            raise ValueError("db_path must be canonical")
        if not isinstance(cursor_codec, SignedCursorCodec):
            raise TypeError("cursor_codec must be SignedCursorCodec")
        self._registry = registry
        self._db_path = canonical_path
        self._cursor_codec = cursor_codec

    def list_datasets(
        self,
        *,
        access: QueryAccessContext,
        filters: CatalogFilters,
        limit: int,
        cursor: str | None,
        now: datetime,
        request_id: str,
    ) -> dict[str, object]:
        if not isinstance(access, QueryAccessContext):
            raise QueryValidationError("access must be QueryAccessContext")
        if not isinstance(filters, CatalogFilters):
            raise QueryValidationError("filters must be CatalogFilters")
        effective_limit = _validated_limit(limit, self._registry)
        canonical_request_id = _canonical_request_id(request_id)
        now_seconds = _clock_seconds(now)
        if (
            filters.q is not None
            and len(filters.q) > self._registry.query_defaults.max_catalog_search_chars
        ):
            raise QueryBudgetError(
                "q exceeds max_catalog_search_chars="
                f"{self._registry.query_defaults.max_catalog_search_chars}"
            )

        catalog_version = public_catalog_version(self._registry)
        normalized_query = {
            "market": filters.market,
            "domain": filters.domain,
            "cadence": filters.cadence,
            "state": filters.state,
            "q": None if filters.q is None else filters.q.casefold(),
            "limit": effective_limit,
        }
        query_hash = _digest(normalized_query)

        with open_verified_read_model_snapshot(self._db_path) as conn:
            try:
                report = project_registry_runtime(conn, self._registry, now=now)
            except RuntimeProjectionError:
                raise
            except (KeyError, TypeError, ValueError, sqlite3.Error):
                raise RuntimeProjectionError(
                    "catalog runtime projection failed closed"
                ) from None
            if type(report) is not dict or not isinstance(
                report.get("datasets"), Mapping
            ):
                raise RuntimeProjectionError("catalog runtime report is invalid")
            runtime_rows = report["datasets"]

            visible: list[tuple[DatasetDefinition, dict[str, object]]] = []
            for dataset in sorted(
                self._registry.datasets,
                key=lambda item: item.dataset_id,
            ):
                if not is_initial_release_eligible(dataset):
                    continue
                if not _has_catalog_scope(access, dataset):
                    continue
                visible.append(
                    (dataset, _validated_runtime_row(runtime_rows, dataset.dataset_id))
                )

            watermark = _digest(
                [
                    [
                        dataset.dataset_id,
                        runtime["state"],
                        runtime["receipt_id"],
                        runtime["data_through"],
                        runtime["observed_at"],
                    ]
                    for dataset, runtime in visible
                ]
            )
            expectation = CursorExpectation(
                kind="catalog",
                catalog_version=catalog_version,
                dataset_id=None,
                schema_major=None,
                query_hash=query_hash,
                policy_id=access.policy_id,
                receipt_watermark=watermark,
            )

            last_dataset_id: str | None = None
            if cursor is not None:
                claims = self._cursor_codec.decode(
                    cursor,
                    expected=expectation,
                    now=now,
                )
                if (
                    len(claims.sort_key) != 1
                    or type(claims.sort_key[0]) is not str
                    or _DATASET_ID_RE.fullmatch(claims.sort_key[0]) is None
                ):
                    raise InvalidCursor("cursor sort key is invalid")
                last_dataset_id = claims.sort_key[0]

            filtered = [
                (dataset, runtime)
                for dataset, runtime in visible
                if _matches_filters(dataset, runtime, filters)
                and (last_dataset_id is None or dataset.dataset_id > last_dataset_id)
            ]
            candidates = filtered[: effective_limit + 1]
            has_more = len(candidates) > effective_limit
            selected = candidates[:effective_limit]
            data = [
                _serialize_dataset(conn, dataset, runtime)
                for dataset, runtime in selected
            ]
            next_cursor = None
            if has_more:
                next_cursor = self._cursor_codec.encode(
                    CursorClaims(
                        kind="catalog",
                        catalog_version=catalog_version,
                        dataset_id=None,
                        schema_major=None,
                        query_hash=query_hash,
                        policy_id=access.policy_id,
                        receipt_watermark=watermark,
                        sort_key=(selected[-1][0].dataset_id,),
                        expires_at=(
                            now_seconds
                            + self._registry.query_defaults.cursor_ttl_seconds
                        ),
                    )
                )

            return {
                "api_version": "v1",
                "catalog_version": catalog_version,
                "request_id": canonical_request_id,
                "data": data,
                "next_cursor": next_cursor,
            }
