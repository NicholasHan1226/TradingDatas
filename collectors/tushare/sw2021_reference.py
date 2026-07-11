#!/usr/bin/env python3
"""Collect and validate an in-memory SW2021 reference snapshot candidate.

This module deliberately has no persistence or scheduling entry point.  A caller
must validate the complete candidate before the snapshot store introduced by the
next rollout task may write or promote it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Callable, Mapping

from collectors.tushare.tushare_common import tushare_rows


TAXONOMY_FIELDS = "index_code,industry_name,parent_code,level,industry_code,is_pub"
MEMBERSHIP_FIELDS = (
    "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,"
    "ts_code,name,in_date,out_date,is_new"
)
EXPECTED_PARTITION_COUNT = 31
PROVIDER_PAGE_LIMIT = 2_000
_ASHARE_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_LEVELS = {"1": "L1", "2": "L2", "3": "L3", "L1": "L1", "L2": "L2", "L3": "L3"}

FetchRows = Callable[[str, dict[str, Any], str], list[dict[str, Any]]]


@dataclass(frozen=True)
class IndustryCandidate:
    snapshot_id: str
    started_at: str
    source_run_id: str
    taxonomy_rows: tuple[Mapping[str, Any], ...]
    membership_rows: tuple[Mapping[str, Any], ...]
    partition_counts: Mapping[str, int]


@dataclass(frozen=True)
class SnapshotValidation:
    accepted: bool
    errors: tuple[str, ...]
    expected_partition_count: int
    successful_partition_count: int
    taxonomy_row_count: int
    membership_row_count: int
    unique_symbol_count: int
    active_universe_count: int
    coverage_ratio: float


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _raw_json(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _normalize_level(value: Any) -> str:
    return _LEVELS.get(_text(value).upper(), _text(value).upper())


def _normalize_taxonomy_row(
    row: Mapping[str, Any], *, snapshot_id: str, collected_at: str
) -> dict[str, Any]:
    level = _normalize_level(row.get("level"))
    index_code = _text(row.get("index_code"))
    return {
        "taxonomy_node_key": _hash_key(f"{snapshot_id}|SW2021|{level}|{index_code}"),
        "snapshot_id": snapshot_id,
        "taxonomy_system": "SW",
        "taxonomy_version": "SW2021",
        "level": level,
        "index_code": index_code,
        "industry_code": _text(row.get("industry_code")),
        "industry_name": _text(row.get("industry_name")),
        "parent_industry_code": _text(row.get("parent_code")),
        "is_published": _text(row.get("is_pub")),
        "provider": "tushare_index_classify",
        "collected_at": collected_at,
        "raw_json": _raw_json(row),
    }


def _normalize_membership_row(
    row: Mapping[str, Any], *, snapshot_id: str, collected_at: str
) -> dict[str, Any]:
    symbol = _text(row.get("ts_code"))
    return {
        "membership_key": _hash_key(f"{snapshot_id}|SW2021|{symbol}"),
        "snapshot_id": snapshot_id,
        "market": "Ashare",
        "symbol": symbol,
        "name": _text(row.get("name")),
        "l1_code": _text(row.get("l1_code")),
        "l1_name": _text(row.get("l1_name")),
        "l2_code": _text(row.get("l2_code")),
        "l2_name": _text(row.get("l2_name")),
        "l3_code": _text(row.get("l3_code")),
        "l3_name": _text(row.get("l3_name")),
        "in_date": _text(row.get("in_date")),
        "out_date": _text(row.get("out_date")),
        "is_current": _text(row.get("is_new")).upper(),
        "provider": "tushare_index_member_all",
        "collected_at": collected_at,
        "raw_json": _raw_json(row),
    }


def _default_fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
    return tushare_rows(api_name, params, fields)


def collect_candidate(
    fetch: FetchRows = _default_fetch,
    *,
    snapshot_id: str,
    source_run_id: str,
) -> IndustryCandidate:
    """Collect one complete in-memory candidate without writing any database."""

    started_at = datetime.now(UTC).isoformat()
    taxonomy_raw = fetch("index_classify", {"level": "", "src": "SW2021"}, TAXONOMY_FIELDS)
    taxonomy_rows = tuple(
        MappingProxyType(
            _normalize_taxonomy_row(row, snapshot_id=snapshot_id, collected_at=started_at)
        )
        for row in taxonomy_raw
    )
    l1_codes = sorted(
        {
            row["index_code"]
            for row in taxonomy_rows
            if row["level"] == "L1" and row["index_code"]
        }
    )

    membership_rows: list[dict[str, Any]] = []
    partition_counts: dict[str, int] = {}
    for l1_code in l1_codes:
        try:
            partition = fetch(
                "index_member_all",
                {"l1_code": l1_code, "is_new": "Y"},
                MEMBERSHIP_FIELDS,
            )
        except Exception:
            # Preserve the failed partition in the immutable candidate so the
            # validation result can be persisted as evidence in the next task.
            partition_counts[l1_code] = -1
            continue
        partition_counts[l1_code] = len(partition)
        membership_rows.extend(
            MappingProxyType(
                _normalize_membership_row(row, snapshot_id=snapshot_id, collected_at=started_at)
            )
            for row in partition
        )

    return IndustryCandidate(
        snapshot_id=snapshot_id,
        started_at=started_at,
        source_run_id=source_run_id,
        taxonomy_rows=taxonomy_rows,
        membership_rows=tuple(membership_rows),
        partition_counts=MappingProxyType(partition_counts),
    )


def eligible_ashare_universe(conn: sqlite3.Connection) -> set[str]:
    """Return the eligible stock universe from the authoritative asset master."""

    rows = conn.execute(
        """
        SELECT symbol FROM market_assets
        WHERE market='Ashare' AND provider='tushare_stock_basic' AND asset_type='stock'
          AND name IS NOT NULL AND TRIM(name) <> '' AND name NOT LIKE '%退%'
        """
    )
    return {str(symbol) for (symbol,) in rows if _ASHARE_SYMBOL.fullmatch(str(symbol))}


def validate_candidate(
    candidate: IndustryCandidate,
    active_symbols: set[str],
    *,
    min_rows: int,
    max_rows: int,
) -> SnapshotValidation:
    """Validate all completeness gates without mutating candidate or storage."""

    errors: list[str] = []

    def reject(reason: str) -> None:
        if reason not in errors:
            errors.append(reason)

    if not _text(candidate.snapshot_id) or not _text(candidate.source_run_id) or not _text(candidate.started_at):
        reject("missing_candidate_lineage")

    taxonomy_by_level_and_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    taxonomy_by_level_and_industry: dict[tuple[str, str], Mapping[str, Any]] = {}
    taxonomy_keys: set[str] = set()
    for row in candidate.taxonomy_rows:
        level = _text(row.get("level"))
        index_code = _text(row.get("index_code"))
        industry_code = _text(row.get("industry_code"))
        industry_name = _text(row.get("industry_name"))
        node_key = _text(row.get("taxonomy_node_key"))
        if level not in {"L1", "L2", "L3"}:
            reject("invalid_taxonomy_level")
        if not index_code or not industry_code or not industry_name:
            reject("missing_required_taxonomy_field")
        if (
            node_key in taxonomy_keys
            or (level, index_code) in taxonomy_by_level_and_index
            or (level, industry_code) in taxonomy_by_level_and_industry
        ):
            reject("duplicate_taxonomy_node")
        taxonomy_keys.add(node_key)
        taxonomy_by_level_and_index[(level, index_code)] = row
        taxonomy_by_level_and_industry[(level, industry_code)] = row

    for row in candidate.taxonomy_rows:
        level = _text(row.get("level"))
        parent = _text(row.get("parent_industry_code"))
        if level == "L1":
            if parent not in {"", "0"}:
                reject("invalid_taxonomy_parent")
        elif level == "L2":
            if not parent or ("L1", parent) not in taxonomy_by_level_and_industry:
                reject("invalid_taxonomy_parent")
        elif level == "L3":
            if not parent or ("L2", parent) not in taxonomy_by_level_and_industry:
                reject("invalid_taxonomy_parent")

    l1_codes = {
        index_code for (level, index_code) in taxonomy_by_level_and_index if level == "L1" and index_code
    }
    partition_codes = set(candidate.partition_counts)
    if len(l1_codes) != EXPECTED_PARTITION_COUNT or partition_codes != l1_codes:
        reject("partition_count")
    if any(count < 0 for count in candidate.partition_counts.values()):
        reject("partition_fetch_failed")
    if any(count == 0 for count in candidate.partition_counts.values()):
        reject("empty_partition")
    if any(count >= PROVIDER_PAGE_LIMIT for count in candidate.partition_counts.values()):
        reject("possible_provider_truncation")

    observed_partition_counts = {code: 0 for code in partition_codes}
    for row in candidate.membership_rows:
        code = _text(row.get("l1_code"))
        if code not in observed_partition_counts:
            reject("membership_outside_collected_partition")
            continue
        observed_partition_counts[code] += 1
    if any(
        count >= 0 and observed_partition_counts.get(code) != count
        for code, count in candidate.partition_counts.items()
    ):
        reject("partition_row_count_mismatch")

    required_membership_fields = (
        "symbol",
        "name",
        "l1_code",
        "l1_name",
        "l2_code",
        "l2_name",
        "l3_code",
        "l3_name",
    )
    assignments: dict[str, tuple[str, str, str]] = {}
    unique_symbols: set[str] = set()
    for row in candidate.membership_rows:
        if any(not _text(row.get(field)) for field in required_membership_fields):
            reject("missing_required_membership_field")
        symbol = _text(row.get("symbol"))
        if symbol and not _ASHARE_SYMBOL.fullmatch(symbol):
            reject("invalid_membership_symbol")
        if _text(row.get("is_current")).upper() != "Y" or _text(row.get("out_date")):
            reject("non_current_membership")

        assignment = tuple(_text(row.get(f"l{level}_code")) for level in (1, 2, 3))
        if symbol in assignments and assignments[symbol] != assignment:
            reject("conflicting_current_assignment")
        elif symbol:
            assignments[symbol] = assignment
            unique_symbols.add(symbol)

        for level in (1, 2, 3):
            code = _text(row.get(f"l{level}_code"))
            taxonomy = taxonomy_by_level_and_index.get((f"L{level}", code))
            if taxonomy is None:
                reject("unresolved_taxonomy_code")
            elif _text(row.get(f"l{level}_name")) != _text(taxonomy.get("industry_name")):
                reject("taxonomy_name_mismatch")

    membership_count = len(candidate.membership_rows)
    if membership_count < min_rows:
        reject("membership_rows_below_min")
    if membership_count > max_rows:
        reject("membership_rows_above_max")

    active_count = len(active_symbols)
    if active_count == 0:
        reject("empty_active_universe")
        coverage_ratio = 0.0
    else:
        coverage_ratio = len(unique_symbols & active_symbols) / active_count
        if coverage_ratio < 0.90:
            reject("coverage_below_0.90")

    successful_partitions = sum(count >= 0 for count in candidate.partition_counts.values())
    return SnapshotValidation(
        accepted=not errors,
        errors=tuple(errors),
        expected_partition_count=EXPECTED_PARTITION_COUNT,
        successful_partition_count=successful_partitions,
        taxonomy_row_count=len(candidate.taxonomy_rows),
        membership_row_count=membership_count,
        unique_symbol_count=len(unique_symbols),
        active_universe_count=active_count,
        coverage_ratio=coverage_ratio,
    )
