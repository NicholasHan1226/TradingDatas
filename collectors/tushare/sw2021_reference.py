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
from collections.abc import Mapping as MappingABC
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
TAXONOMY_PAGE_SIZE = 50
TAXONOMY_MAX_PAGES = 100
_ASHARE_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
_LEVELS = {"1": "L1", "2": "L2", "3": "L3", "L1": "L1", "L2": "L2", "L3": "L3"}

FetchRows = Callable[[str, dict[str, Any], str], Any]


class CandidateCollectionError(RuntimeError):
    """Fail-closed provider pagination error for an incomplete candidate."""

    def __init__(self, reason: str, **evidence: int) -> None:
        self.reason = reason
        self.evidence = dict(evidence)
        detail = (
            f":{json.dumps(self.evidence, sort_keys=True, separators=(',', ':'))}"
            if self.evidence
            else ""
        )
        super().__init__(f"{reason}{detail}")


@dataclass(frozen=True)
class IndustryCandidate:
    snapshot_id: str
    started_at: str
    source_run_id: str
    taxonomy_rows: tuple[Mapping[str, Any], ...]
    membership_rows: tuple[Mapping[str, Any], ...]
    # Raw row count returned by each provider request.  This must never be
    # reconstructed from row-declared l1_code values or post-deduplication rows.
    partition_counts: Mapping[str, int]
    deduplicated_partition_counts: Mapping[str, int]
    declared_partition_counts: Mapping[str, int]
    partition_scope_mismatches: tuple[tuple[str, str, str], ...]
    partition_failures: Mapping[str, str]


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
    row: Mapping[str, Any],
    *,
    snapshot_id: str,
    collected_at: str,
    requested_l1: str,
    source_partitions: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    symbol = _text(row.get("ts_code"))
    partitions = tuple(sorted(set(source_partitions or (requested_l1,))))
    evidence = {
        "provider_row": dict(row),
        "requested_l1": requested_l1,
        "source_partitions": list(partitions),
    }
    evidence["evidence_hash"] = _hash_key(
        f"{snapshot_id}|SW2021|{symbol}|{_raw_json(evidence)}"
    )
    raw_json = _raw_json(evidence)
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
        "raw_json": raw_json,
    }


def _membership_evidence(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, tuple[str, ...]]:
    evidence = json.loads(_text(row.get("raw_json")))
    if not isinstance(evidence, dict):
        raise ValueError("membership evidence must be an object")
    provider_row = evidence.get("provider_row")
    requested_l1 = evidence.get("requested_l1")
    source_partitions = evidence.get("source_partitions")
    evidence_hash = evidence.get("evidence_hash")
    if (
        set(evidence)
        != {"provider_row", "requested_l1", "source_partitions", "evidence_hash"}
        or not isinstance(provider_row, MappingABC)
        or not isinstance(requested_l1, str)
        or not requested_l1.strip()
        or not isinstance(source_partitions, list)
        or not source_partitions
        or any(not isinstance(value, str) or not value.strip() for value in source_partitions)
        or source_partitions != sorted(set(source_partitions))
        or requested_l1 != source_partitions[0]
        or not isinstance(evidence_hash, str)
    ):
        raise ValueError("invalid membership evidence")
    unsigned_evidence = dict(evidence)
    unsigned_evidence.pop("evidence_hash")
    expected_hash = _hash_key(
        f"{_text(row.get('snapshot_id'))}|SW2021|{_text(row.get('symbol'))}|"
        f"{_raw_json(unsigned_evidence)}"
    )
    if evidence_hash != expected_hash:
        raise ValueError("invalid membership evidence hash")
    return provider_row, requested_l1, tuple(source_partitions)


def _default_fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
    return tushare_rows(api_name, params, fields)


def _collect_taxonomy_pages(fetch: FetchRows) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_fingerprints: set[str] = set()

    for page_number in range(TAXONOMY_MAX_PAGES):
        offset = page_number * TAXONOMY_PAGE_SIZE
        try:
            page = fetch(
                "index_classify",
                {
                    "level": "",
                    "src": "SW2021",
                    "limit": TAXONOMY_PAGE_SIZE,
                    "offset": offset,
                },
                TAXONOMY_FIELDS,
            )
        except Exception as exc:
            raise CandidateCollectionError("taxonomy_fetch_failed") from exc

        if not isinstance(page, list) or any(
            not isinstance(row, MappingABC) for row in page
        ):
            raise CandidateCollectionError(
                "taxonomy_invalid_page", page=page_number, offset=offset
            )
        if len(page) > TAXONOMY_PAGE_SIZE:
            raise CandidateCollectionError("taxonomy_page_oversized")
        if not page:
            return rows

        fingerprint = _hash_key(_raw_json({"rows": page}))
        if fingerprint in page_fingerprints:
            raise CandidateCollectionError("taxonomy_repeated_page")
        page_fingerprints.add(fingerprint)
        rows.extend(page)

        if len(page) < TAXONOMY_PAGE_SIZE:
            return rows

    raise CandidateCollectionError("taxonomy_page_limit_exceeded")


def _validated_l1_codes(taxonomy_rows: list[dict[str, Any]]) -> list[str]:
    """Fail before fan-out unless the complete taxonomy is structurally sound."""

    by_level_and_index: dict[tuple[str, str], dict[str, Any]] = {}
    by_level_and_industry: dict[tuple[str, str], dict[str, Any]] = {}
    node_keys: set[str] = set()
    valid = True

    for row in taxonomy_rows:
        level = _text(row.get("level"))
        index_code = _text(row.get("index_code"))
        industry_code = _text(row.get("industry_code"))
        industry_name = _text(row.get("industry_name"))
        node_key = _text(row.get("taxonomy_node_key"))
        if (
            level not in {"L1", "L2", "L3"}
            or not index_code
            or not industry_code
            or not industry_name
            or not node_key
            or node_key in node_keys
            or (level, index_code) in by_level_and_index
            or (level, industry_code) in by_level_and_industry
        ):
            valid = False
        node_keys.add(node_key)
        by_level_and_index[(level, index_code)] = row
        by_level_and_industry[(level, industry_code)] = row

    for row in taxonomy_rows:
        level = _text(row.get("level"))
        parent = _text(row.get("parent_industry_code"))
        if level == "L1" and parent not in {"", "0"}:
            valid = False
        elif level == "L2" and (not parent or ("L1", parent) not in by_level_and_industry):
            valid = False
        elif level == "L3" and (not parent or ("L2", parent) not in by_level_and_industry):
            valid = False

    l1_codes = sorted(
        index_code
        for (level, index_code) in by_level_and_index
        if level == "L1" and index_code
    )
    levels = {level for level, _ in by_level_and_index}
    if not valid or levels != {"L1", "L2", "L3"} or len(l1_codes) != EXPECTED_PARTITION_COUNT:
        raise CandidateCollectionError("invalid_taxonomy_candidate")
    return l1_codes


def _deduplicate_memberships(
    rows: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    grouped: dict[
        tuple[str, str, str, str, str], list[tuple[str, dict[str, Any]]]
    ] = {}
    passthrough: list[tuple[str, dict[str, Any]]] = []
    for requested_partition, row in rows:
        identity = (
            _text(row.get("membership_key")),
            _text(row.get("symbol")),
            _text(row.get("l1_code")),
            _text(row.get("l2_code")),
            _text(row.get("l3_code")),
        )
        if all(identity):
            grouped.setdefault(identity, []).append((requested_partition, row))
        else:
            passthrough.append((requested_partition, row))

    deduplicated: list[tuple[str, dict[str, Any]]] = []
    for duplicates in grouped.values():
        evidence = [_membership_evidence(row) for _, row in duplicates]
        source_partitions = tuple(
            sorted({partition for _, _, partitions in evidence for partition in partitions})
        )
        provider_row = min(
            (provider_row for provider_row, _, _ in evidence), key=_raw_json
        )
        primary_partition = min(source_partitions)
        template = min(
            duplicates,
            key=lambda item: (_text(item[1].get("raw_json")), item[0]),
        )[1]
        merged = _normalize_membership_row(
            provider_row,
            snapshot_id=_text(template.get("snapshot_id")),
            collected_at=_text(template.get("collected_at")),
            requested_l1=primary_partition,
            source_partitions=source_partitions,
        )
        deduplicated.append((primary_partition, merged))
    return sorted(
        [*deduplicated, *passthrough],
        key=lambda item: (
            _text(item[1].get("symbol")),
            _text(item[1].get("l1_code")),
            _text(item[1].get("l2_code")),
            _text(item[1].get("l3_code")),
            _text(item[1].get("raw_json")),
            item[0],
        ),
    )


def collect_candidate(
    fetch: FetchRows = _default_fetch,
    *,
    snapshot_id: str,
    source_run_id: str,
) -> IndustryCandidate:
    """Collect one complete in-memory candidate without writing any database."""

    started_at = datetime.now(UTC).isoformat()
    taxonomy_raw = _collect_taxonomy_pages(fetch)
    normalized_taxonomy_rows = [
        _normalize_taxonomy_row(row, snapshot_id=snapshot_id, collected_at=started_at)
        for row in taxonomy_raw
    ]
    l1_codes = _validated_l1_codes(normalized_taxonomy_rows)
    taxonomy_rows = tuple(MappingProxyType(row) for row in normalized_taxonomy_rows)

    membership_entries: list[tuple[str, dict[str, Any]]] = []
    source_partition_counts: dict[str, int] = {}
    partition_failures: dict[str, str] = {}
    partition_scope_mismatches: list[tuple[str, str, str]] = []
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
            source_partition_counts[l1_code] = -1
            partition_failures[l1_code] = "membership_fetch_failed"
            continue
        if not isinstance(partition, list) or any(
            not isinstance(row, MappingABC) for row in partition
        ):
            source_partition_counts[l1_code] = -1
            partition_failures[l1_code] = "invalid_membership_response_shape"
            continue
        normalized_rows = [
            _normalize_membership_row(
                row,
                snapshot_id=snapshot_id,
                collected_at=started_at,
                requested_l1=l1_code,
            )
            for row in partition
        ]
        source_partition_counts[l1_code] = len(normalized_rows)
        for row in normalized_rows:
            declared_l1_code = _text(row.get("l1_code"))
            if declared_l1_code != l1_code:
                partition_scope_mismatches.append(
                    (l1_code, declared_l1_code, _text(row.get("symbol")))
                )
            membership_entries.append((l1_code, row))

    deduplicated_entries = _deduplicate_memberships(membership_entries)
    deduplicated_partition_counts = {code: 0 for code in l1_codes}
    declared_partition_counts = {code: 0 for code in l1_codes}
    membership_rows: list[dict[str, Any]] = []
    for requested_partition, row in deduplicated_entries:
        deduplicated_partition_counts[requested_partition] += 1
        declared_l1_code = _text(row.get("l1_code"))
        if declared_l1_code in declared_partition_counts:
            declared_partition_counts[declared_l1_code] += 1
        membership_rows.append(row)

    return IndustryCandidate(
        snapshot_id=snapshot_id,
        started_at=started_at,
        source_run_id=source_run_id,
        taxonomy_rows=taxonomy_rows,
        membership_rows=tuple(MappingProxyType(row) for row in membership_rows),
        partition_counts=MappingProxyType(source_partition_counts),
        deduplicated_partition_counts=MappingProxyType(deduplicated_partition_counts),
        declared_partition_counts=MappingProxyType(declared_partition_counts),
        partition_scope_mismatches=tuple(sorted(partition_scope_mismatches)),
        partition_failures=MappingProxyType(partition_failures),
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
        try:
            raw_row = json.loads(_text(row.get("raw_json")))
            expected_row = _normalize_taxonomy_row(
                raw_row,
                snapshot_id=candidate.snapshot_id,
                collected_at=candidate.started_at,
            )
            if dict(row) != expected_row:
                reject("invalid_taxonomy_lineage")
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            reject("invalid_taxonomy_lineage")
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

    if {level for level, _ in taxonomy_by_level_and_index} != {"L1", "L2", "L3"}:
        reject("incomplete_taxonomy_hierarchy")

    l1_codes = {
        index_code for (level, index_code) in taxonomy_by_level_and_index if level == "L1" and index_code
    }
    partition_codes = set(candidate.partition_counts)
    semantically_failed_partitions: set[str] = set()
    if len(l1_codes) != EXPECTED_PARTITION_COUNT or partition_codes != l1_codes:
        reject("partition_count")
    if set(candidate.deduplicated_partition_counts) != partition_codes:
        reject("deduplicated_partition_count_mismatch")
    if set(candidate.declared_partition_counts) != partition_codes:
        reject("declared_partition_count_mismatch")
    if candidate.partition_failures or any(
        count < 0 for count in candidate.partition_counts.values()
    ):
        reject("partition_fetch_failed")
        semantically_failed_partitions.update(candidate.partition_failures)
        semantically_failed_partitions.update(
            code for code, count in candidate.partition_counts.items() if count < 0
        )
    if any(count == 0 for count in candidate.partition_counts.values()):
        reject("empty_partition")
        semantically_failed_partitions.update(
            code for code, count in candidate.partition_counts.items() if count == 0
        )
    if any(count >= PROVIDER_PAGE_LIMIT for count in candidate.partition_counts.values()):
        reject("possible_provider_truncation")
        semantically_failed_partitions.update(
            code
            for code, count in candidate.partition_counts.items()
            if count >= PROVIDER_PAGE_LIMIT
        )
    if candidate.partition_scope_mismatches:
        reject("partition_scope_mismatch")
        semantically_failed_partitions.update(
            requested_partition
            for requested_partition, _, _ in candidate.partition_scope_mismatches
        )

    if any(
        source_count >= 0
        and candidate.deduplicated_partition_counts.get(code, -1) > source_count
        for code, source_count in candidate.partition_counts.items()
    ):
        reject("deduplicated_partition_count_mismatch")
        semantically_failed_partitions.update(
            code
            for code, source_count in candidate.partition_counts.items()
            if source_count >= 0
            and candidate.deduplicated_partition_counts.get(code, -1) > source_count
        )

    observed_partition_counts = {code: 0 for code in partition_codes}
    for row in candidate.membership_rows:
        code = _text(row.get("l1_code"))
        if code not in observed_partition_counts:
            reject("membership_outside_collected_partition")
            continue
        observed_partition_counts[code] += 1
    if any(
        observed_partition_counts.get(code) != count
        for code, count in candidate.declared_partition_counts.items()
    ):
        reject("declared_partition_count_mismatch")
        semantically_failed_partitions.update(
            code
            for code, count in candidate.declared_partition_counts.items()
            if observed_partition_counts.get(code) != count
        )

    membership_count = len(candidate.membership_rows)
    if sum(candidate.deduplicated_partition_counts.values()) != membership_count:
        reject("deduplicated_partition_count_mismatch")
    if sum(candidate.declared_partition_counts.values()) != membership_count:
        reject("declared_partition_count_mismatch")
    if not candidate.partition_scope_mismatches and (
        candidate.deduplicated_partition_counts != candidate.declared_partition_counts
    ):
        reject("partition_scope_mismatch")

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
    assignments: dict[str, tuple[tuple[str, str, str], set[str]]] = {}
    membership_keys: set[str] = set()
    unique_symbols: set[str] = set()
    scope_mismatch_partitions = {
        requested_partition
        for requested_partition, _, _ in candidate.partition_scope_mismatches
    }
    for row in candidate.membership_rows:
        row_failed = False
        row_partitions: set[str] = set()
        membership_key = _text(row.get("membership_key"))
        if membership_key in membership_keys:
            reject("duplicate_membership_key")
            row_failed = True
        membership_keys.add(membership_key)
        try:
            raw_row, requested_l1, source_partitions = _membership_evidence(row)
            row_partitions.update(
                code for code in source_partitions if code in partition_codes
            )
            expected_row = _normalize_membership_row(
                raw_row,
                snapshot_id=candidate.snapshot_id,
                collected_at=candidate.started_at,
                requested_l1=requested_l1,
                source_partitions=source_partitions,
            )
            if dict(row) != expected_row:
                reject("invalid_membership_lineage")
                row_failed = True
            declared_l1 = _text(expected_row.get("l1_code"))
            mismatched_partitions = {
                source_partition
                for source_partition in source_partitions
                if source_partition != declared_l1
            }
            if mismatched_partitions:
                scope_mismatch_partitions.update(mismatched_partitions)
                semantically_failed_partitions.update(mismatched_partitions)
                reject("partition_scope_mismatch")
                row_failed = True
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            reject("invalid_membership_lineage")
            row_failed = True
            try:
                evidence = json.loads(_text(row.get("raw_json")))
                if isinstance(evidence, dict):
                    requested_l1 = evidence.get("requested_l1")
                    source_partitions = evidence.get("source_partitions")
                    if isinstance(requested_l1, str) and requested_l1 in partition_codes:
                        row_partitions.add(requested_l1)
                    if isinstance(source_partitions, list):
                        row_partitions.update(
                            code
                            for code in source_partitions
                            if isinstance(code, str) and code in partition_codes
                        )
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if any(not _text(row.get(field)) for field in required_membership_fields):
            reject("missing_required_membership_field")
            row_failed = True
        symbol = _text(row.get("symbol"))
        if symbol and not _ASHARE_SYMBOL.fullmatch(symbol):
            reject("invalid_membership_symbol")
            row_failed = True
        if _text(row.get("is_current")).upper() != "Y" or _text(row.get("out_date")):
            reject("non_current_membership")
            row_failed = True

        assignment = tuple(_text(row.get(f"l{level}_code")) for level in (1, 2, 3))
        if symbol in assignments and assignments[symbol][0] != assignment:
            reject("conflicting_current_assignment")
            row_failed = True
            semantically_failed_partitions.update(assignments[symbol][1])
        elif symbol:
            assignments[symbol] = (assignment, set(row_partitions))
            unique_symbols.add(symbol)

        resolved_taxonomy: dict[int, Mapping[str, Any]] = {}
        for level in (1, 2, 3):
            code = _text(row.get(f"l{level}_code"))
            taxonomy = taxonomy_by_level_and_index.get((f"L{level}", code))
            if taxonomy is None:
                reject("unresolved_taxonomy_code")
                row_failed = True
            else:
                resolved_taxonomy[level] = taxonomy
                if _text(row.get(f"l{level}_name")) != _text(taxonomy.get("industry_name")):
                    reject("taxonomy_name_mismatch")
                    row_failed = True

        if len(resolved_taxonomy) == 3:
            if _text(resolved_taxonomy[2].get("parent_industry_code")) != _text(
                resolved_taxonomy[1].get("industry_code")
            ) or _text(resolved_taxonomy[3].get("parent_industry_code")) != _text(
                resolved_taxonomy[2].get("industry_code")
            ):
                reject("membership_hierarchy_mismatch")
                row_failed = True

        if not row_partitions:
            declared_l1 = _text(row.get("l1_code"))
            if declared_l1 in partition_codes:
                row_partitions.add(declared_l1)
        if row_failed:
            semantically_failed_partitions.update(row_partitions)

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

    successful_partitions = sum(
        code not in candidate.partition_failures
        and 0 < count < PROVIDER_PAGE_LIMIT
        and code not in scope_mismatch_partitions
        and code not in semantically_failed_partitions
        and 0 < candidate.deduplicated_partition_counts.get(code, 0) <= count
        and candidate.declared_partition_counts.get(code)
        == candidate.deduplicated_partition_counts.get(code)
        for code, count in candidate.partition_counts.items()
    )
    accepted = (
        not errors
        and EXPECTED_PARTITION_COUNT == 31
        and successful_partitions == EXPECTED_PARTITION_COUNT
    )
    return SnapshotValidation(
        accepted=accepted,
        errors=tuple(errors),
        expected_partition_count=EXPECTED_PARTITION_COUNT,
        successful_partition_count=successful_partitions,
        taxonomy_row_count=len(candidate.taxonomy_rows),
        membership_row_count=membership_count,
        unique_symbol_count=len(unique_symbols),
        active_universe_count=active_count,
        coverage_ratio=coverage_ratio,
    )
