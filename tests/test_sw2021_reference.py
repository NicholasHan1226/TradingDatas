from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest

from collectors.tushare.sw2021_reference import (
    MEMBERSHIP_FIELDS,
    TAXONOMY_FIELDS,
    TAXONOMY_PAGE_SIZE,
    CandidateCollectionError,
    IndustryCandidate,
    collect_candidate,
    eligible_ashare_universe,
    validate_candidate,
)
from storage.read_model_store import API_TO_TABLE_MAP


def _symbol(number: int) -> str:
    return f"{number:06d}.SZ"


def _raw_taxonomy() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number in range(1, 32):
        l1_industry = f"{number:02d}0000"
        l2_industry = f"{number:02d}1000"
        l3_industry = f"{number:02d}1100"
        rows.extend(
            [
                {
                    "index_code": f"L1-{number:02d}",
                    "industry_name": f"Level 1 {number}",
                    "parent_code": "",
                    "level": "L1",
                    "industry_code": l1_industry,
                    "is_pub": "1",
                },
                {
                    "index_code": f"L2-{number:02d}",
                    "industry_name": f"Level 2 {number}",
                    "parent_code": l1_industry,
                    "level": "L2",
                    "industry_code": l2_industry,
                    "is_pub": "1",
                },
                {
                    "index_code": f"L3-{number:02d}",
                    "industry_name": f"Level 3 {number}",
                    "parent_code": l2_industry,
                    "level": "L3",
                    "industry_code": l3_industry,
                    "is_pub": "0" if number == 31 else "1",
                },
            ]
        )
    return rows


def _raw_memberships() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number in range(1, 101):
        partition = ((number - 1) % 31) + 1
        rows.append(
            {
                "l1_code": f"L1-{partition:02d}",
                "l1_name": f"Level 1 {partition}",
                "l2_code": f"L2-{partition:02d}",
                "l2_name": f"Level 2 {partition}",
                "l3_code": f"L3-{partition:02d}",
                "l3_name": f"Level 3 {partition}",
                "ts_code": _symbol(number),
                "name": f"Stock {number}",
                "in_date": "20210101",
                "out_date": None,
                "is_new": "Y",
            }
        )
    return rows


def _collected_candidate() -> IndustryCandidate:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            offset = params["offset"]
            limit = params["limit"]
            return taxonomy[offset : offset + limit]
        assert fields == MEMBERSHIP_FIELDS
        return [row for row in memberships if row["l1_code"] == params["l1_code"]]

    return collect_candidate(fetch, snapshot_id="snapshot-1", source_run_id="run-1")


def candidate_fixture(mutation: str) -> tuple[IndustryCandidate, set[str]]:
    candidate = _collected_candidate()
    active = {_symbol(number) for number in range(1, 101)}

    if mutation == "missing_partition":
        counts = dict(candidate.partition_counts)
        counts.pop("L1-31")
        candidate = replace(candidate, partition_counts=counts)
    elif mutation == "partition_at_2000_rows":
        counts = dict(candidate.partition_counts)
        counts["L1-01"] = 2000
        candidate = replace(candidate, partition_counts=counts)
    elif mutation == "conflicting_symbol":
        conflict = dict(candidate.membership_rows[0])
        conflict["l3_code"] = "L3-02"
        conflict["l3_name"] = "Level 3 2"
        candidate = replace(candidate, membership_rows=(*candidate.membership_rows, conflict))
    elif mutation == "unresolved_l3":
        rows = [dict(row) for row in candidate.membership_rows]
        rows[0]["l3_code"] = "L3-MISSING"
        candidate = replace(candidate, membership_rows=tuple(rows))
    elif mutation == "missing_name":
        rows = [dict(row) for row in candidate.membership_rows]
        rows[0]["name"] = " "
        candidate = replace(candidate, membership_rows=tuple(rows))
    elif mutation == "out_date_present":
        rows = [dict(row) for row in candidate.membership_rows]
        rows[0]["out_date"] = "20260711"
        candidate = replace(candidate, membership_rows=tuple(rows))
    elif mutation == "coverage_89_percent":
        active = {_symbol(number) for number in range(1, 113)}
    elif mutation == "zero_universe":
        active = set()
    else:  # pragma: no cover - fixture misuse
        raise AssertionError(mutation)
    return candidate, active


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_partition", "partition_count"),
        ("partition_at_2000_rows", "possible_provider_truncation"),
        ("conflicting_symbol", "conflicting_current_assignment"),
        ("unresolved_l3", "unresolved_taxonomy_code"),
        ("missing_name", "missing_required_membership_field"),
        ("out_date_present", "non_current_membership"),
        ("coverage_89_percent", "coverage_below_0.90"),
        ("zero_universe", "empty_active_universe"),
    ],
)
def test_candidate_rejection_reasons(mutation: str, reason: str) -> None:
    candidate, active = candidate_fixture(mutation)
    result = validate_candidate(candidate, active, min_rows=1, max_rows=10_000)
    assert result.accepted is False
    assert reason in result.errors


def test_collects_full_hierarchy_and_exactly_31_bounded_partitions() -> None:
    calls: list[tuple[str, dict[str, Any], str]] = []
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        calls.append((api_name, params, fields))
        if api_name == "index_classify":
            offset = params["offset"]
            limit = params["limit"]
            return taxonomy[offset : offset + limit]
        return [row for row in memberships if row["l1_code"] == params["l1_code"]]

    candidate = collect_candidate(fetch, snapshot_id="snapshot-capture", source_run_id="run-capture")
    member_calls = [call for call in calls if call[0] == "index_member_all"]
    taxonomy_calls = [call for call in calls if call[0] == "index_classify"]

    assert taxonomy_calls == [
        (
            "index_classify",
            {"level": "", "src": "SW2021", "limit": TAXONOMY_PAGE_SIZE, "offset": offset},
            TAXONOMY_FIELDS,
        )
        for offset in range(0, len(taxonomy), TAXONOMY_PAGE_SIZE)
    ]
    assert len(member_calls) == 31
    assert [call[1] for call in member_calls] == [
        {"l1_code": f"L1-{number:02d}", "is_new": "Y"} for number in range(1, 32)
    ]
    assert {call[2] for call in member_calls} == {MEMBERSHIP_FIELDS}
    assert len(candidate.taxonomy_rows) == 93
    assert len(candidate.membership_rows) == 100
    assert set(candidate.partition_counts) == {f"L1-{number:02d}" for number in range(1, 32)}
    assert validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    ).accepted
    assert candidate.taxonomy_rows[0]["taxonomy_node_key"] == sha256(
        b"snapshot-capture|SW2021|L1|L1-01"
    ).hexdigest()
    assert candidate.membership_rows[0]["membership_key"] == sha256(
        b"snapshot-capture|SW2021|000001.SZ"
    ).hexdigest()
    assert candidate.taxonomy_rows[-1]["is_published"] == "0"
    assert '"index_code":"L1-01"' in candidate.taxonomy_rows[0]["raw_json"]


@pytest.mark.parametrize("mode", ["too_few", "too_many", "duplicate_l1", "broken_hierarchy"])
def test_invalid_taxonomy_fails_before_any_membership_call(mode: str) -> None:
    taxonomy = _raw_taxonomy()
    if mode == "too_few":
        taxonomy = [row for row in taxonomy if row["index_code"] != "L1-31"]
    elif mode == "too_many":
        taxonomy.extend(
            [
                {
                    "index_code": "L1-32",
                    "industry_name": "Level 1 32",
                    "parent_code": "",
                    "level": "L1",
                    "industry_code": "320000",
                    "is_pub": "1",
                },
                {
                    "index_code": "L2-32",
                    "industry_name": "Level 2 32",
                    "parent_code": "320000",
                    "level": "L2",
                    "industry_code": "321000",
                    "is_pub": "1",
                },
                {
                    "index_code": "L3-32",
                    "industry_name": "Level 3 32",
                    "parent_code": "321000",
                    "level": "L3",
                    "industry_code": "321100",
                    "is_pub": "1",
                },
            ]
        )
    elif mode == "duplicate_l1":
        taxonomy.append(dict(taxonomy[0]))
    else:
        taxonomy[-1] = dict(taxonomy[-1], parent_code="does-not-exist")

    membership_calls = 0

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        nonlocal membership_calls
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        membership_calls += 1
        return []

    with pytest.raises(CandidateCollectionError, match="invalid_taxonomy_candidate"):
        collect_candidate(fetch, snapshot_id=f"snapshot-{mode}", source_run_id="run")

    assert membership_calls == 0


def test_provider_partition_failure_is_preserved_and_rejected() -> None:
    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            taxonomy = _raw_taxonomy()
            offset = params["offset"]
            limit = params["limit"]
            return taxonomy[offset : offset + limit]
        if params["l1_code"] == "L1-12":
            raise RuntimeError("provider timeout")
        return [row for row in _raw_memberships() if row["l1_code"] == params["l1_code"]]

    candidate = collect_candidate(fetch, snapshot_id="snapshot-error", source_run_id="run-error")
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert candidate.partition_counts["L1-12"] == -1
    assert validation.accepted is False
    assert "partition_fetch_failed" in validation.errors


@pytest.mark.parametrize(
    "malformed_response",
    [
        {"l1_code": "L1-12"},
        "not-a-list-of-mappings",
        [{"l1_code": "L1-12"}, "not-a-mapping"],
    ],
)
def test_invalid_membership_response_shape_becomes_structured_partition_failure(
    malformed_response: object,
) -> None:
    taxonomy = _raw_taxonomy()

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> Any:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        if params["l1_code"] == "L1-12":
            return malformed_response
        return [
            row
            for row in _raw_memberships()
            if row["l1_code"] == params["l1_code"]
        ]

    candidate = collect_candidate(
        fetch, snapshot_id="snapshot-invalid-shape", source_run_id="run-invalid-shape"
    )
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert candidate.partition_counts["L1-12"] == -1
    assert candidate.partition_failures["L1-12"] == "invalid_membership_response_shape"
    assert validation.accepted is False
    assert "partition_fetch_failed" in validation.errors
    assert validation.successful_partition_count == 30


@pytest.mark.parametrize("raw_count", [-1, 0, 2_000])
def test_successful_partition_count_requires_nonempty_bounded_valid_response(
    raw_count: int,
) -> None:
    candidate = _collected_candidate()
    counts = dict(candidate.partition_counts)
    counts["L1-01"] = raw_count
    candidate = replace(candidate, partition_counts=counts)

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert validation.successful_partition_count == 30


def test_invalid_membership_row_fails_its_requested_partition_semantically() -> None:
    candidate, active = candidate_fixture("missing_name")

    validation = validate_candidate(candidate, active, min_rows=1, max_rows=10_000)

    assert validation.accepted is False
    assert "missing_required_membership_field" in validation.errors
    assert validation.successful_partition_count == 30


def test_empty_provider_partition_preserves_zero_source_count_and_is_rejected() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        if params["l1_code"] == "L1-02":
            return []
        return [row for row in memberships if row["l1_code"] == params["l1_code"]]

    candidate = collect_candidate(fetch, snapshot_id="snapshot-empty", source_run_id="run-empty")
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert candidate.partition_counts["L1-02"] == 0
    assert candidate.deduplicated_partition_counts["L1-02"] == 0
    assert candidate.declared_partition_counts["L1-02"] == 0
    assert validation.accepted is False
    assert "empty_partition" in validation.errors


def test_cross_partition_row_cannot_fill_an_empty_requested_partition() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    smuggled_l1_02 = next(row for row in memberships if row["l1_code"] == "L1-02")

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        if params["l1_code"] == "L1-02":
            return []
        rows = [row for row in memberships if row["l1_code"] == params["l1_code"]]
        return [*rows, smuggled_l1_02] if params["l1_code"] == "L1-01" else rows

    candidate = collect_candidate(
        fetch,
        snapshot_id="snapshot-partition-scope",
        source_run_id="run-partition-scope",
    )
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert candidate.partition_counts["L1-01"] == 5
    assert candidate.partition_counts["L1-02"] == 0
    assert candidate.deduplicated_partition_counts["L1-01"] == 5
    assert candidate.deduplicated_partition_counts["L1-02"] == 0
    assert candidate.declared_partition_counts["L1-02"] == 1
    assert candidate.partition_scope_mismatches == (
        ("L1-01", "L1-02", smuggled_l1_02["ts_code"]),
    )
    assert validation.accepted is False
    assert "empty_partition" in validation.errors
    assert "partition_scope_mismatch" in validation.errors


def test_per_row_partition_evidence_rebuilds_symmetric_scope_mismatch() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    first = next(row for row in memberships if row["l1_code"] == "L1-01")
    second = next(row for row in memberships if row["l1_code"] == "L1-02")

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        rows = [row for row in memberships if row["l1_code"] == params["l1_code"]]
        if params["l1_code"] == "L1-01":
            return [second if row is first else row for row in rows]
        if params["l1_code"] == "L1-02":
            return [first if row is second else row for row in rows]
        return rows

    candidate = collect_candidate(
        fetch, snapshot_id="snapshot-symmetric-scope", source_run_id="run-symmetric-scope"
    )
    candidate = replace(candidate, partition_scope_mismatches=())
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert validation.accepted is False
    assert "partition_scope_mismatch" in validation.errors
    assert validation.successful_partition_count == 29


@pytest.mark.parametrize("tamper", ["raw_lineage", "evidence_hash"])
def test_membership_partition_evidence_tampering_is_rejected(tamper: str) -> None:
    candidate = _collected_candidate()
    rows = [dict(row) for row in candidate.membership_rows]
    if tamper == "raw_lineage":
        evidence = json.loads(rows[0]["raw_json"])
        evidence["requested_l1"] = "L1-31"
    else:
        evidence = json.loads(rows[0]["raw_json"])
        evidence["evidence_hash"] = "tampered-hash"
    rows[0]["raw_json"] = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    candidate = replace(candidate, membership_rows=tuple(rows))

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert "invalid_membership_lineage" in validation.errors


@pytest.mark.parametrize(
    ("count_field", "reason"),
    [
        ("deduplicated_partition_counts", "deduplicated_partition_count_mismatch"),
        ("declared_partition_counts", "declared_partition_count_mismatch"),
    ],
)
def test_partition_count_totals_are_validated_defensively(
    count_field: str, reason: str
) -> None:
    candidate = _collected_candidate()
    counts = dict(getattr(candidate, count_field))
    counts["L1-01"] += 1
    candidate = replace(candidate, **{count_field: counts})

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert validation.accepted is False
    assert reason in validation.errors
    assert validation.successful_partition_count == 30


@pytest.mark.parametrize(
    ("invalid_row", "expected_page", "expected_offset"),
    [
        ("not-a-mapping", 0, 0),
        (42, 1, TAXONOMY_PAGE_SIZE),
    ],
)
def test_taxonomy_page_requires_only_mappings_with_structured_evidence(
    invalid_row: object,
    expected_page: int,
    expected_offset: int,
) -> None:
    taxonomy = _raw_taxonomy()

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[object]:
        assert api_name == "index_classify"
        page = list(taxonomy[params["offset"] : params["offset"] + params["limit"]])
        if params["offset"] == expected_offset:
            page[0] = invalid_row
        return page

    with pytest.raises(CandidateCollectionError) as exc_info:
        collect_candidate(
            fetch,
            snapshot_id=f"snapshot-invalid-taxonomy-page-{expected_page}",
            source_run_id="run-invalid-taxonomy-page",
        )

    assert exc_info.value.reason == "taxonomy_invalid_page"
    assert exc_info.value.evidence == {
        "page": expected_page,
        "offset": expected_offset,
    }


def test_taxonomy_pagination_continues_after_an_exact_full_page() -> None:
    taxonomy = _raw_taxonomy()
    exact_full_page = taxonomy[:TAXONOMY_PAGE_SIZE]
    calls: list[int] = []

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            calls.append(params["offset"])
            if params["offset"] == 0:
                return exact_full_page
            return []
        return []

    with pytest.raises(CandidateCollectionError, match="invalid_taxonomy_candidate"):
        collect_candidate(fetch, snapshot_id="snapshot-exact-page", source_run_id="run")

    assert calls == [0, TAXONOMY_PAGE_SIZE]


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("repeated", "taxonomy_repeated_page"),
        ("exception", "taxonomy_fetch_failed"),
        ("oversized", "taxonomy_page_oversized"),
    ],
)
def test_taxonomy_pagination_fails_closed(mode: str, reason: str) -> None:
    page = _raw_taxonomy()[:TAXONOMY_PAGE_SIZE]

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name != "index_classify":
            return []
        if mode == "exception" and params["offset"]:
            raise RuntimeError("provider timeout")
        if mode == "oversized":
            return [*page, dict(page[0])]
        return page

    with pytest.raises(CandidateCollectionError, match=reason):
        collect_candidate(fetch, snapshot_id=f"snapshot-{mode}", source_run_id="run")


def test_taxonomy_pagination_maximum_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import collectors.tushare.sw2021_reference as module

    monkeypatch.setattr(module, "TAXONOMY_MAX_PAGES", 2)
    page = _raw_taxonomy()[:TAXONOMY_PAGE_SIZE]

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        assert api_name == "index_classify"
        return [dict(row, index_code=f'{row["index_code"]}-{params["offset"]}') for row in page]

    with pytest.raises(CandidateCollectionError, match="taxonomy_page_limit_exceeded"):
        collect_candidate(fetch, snapshot_id="snapshot-max-pages", source_run_id="run")


def test_same_symbol_and_assignment_is_stably_deduplicated() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    duplicate = dict(memberships[0], name="A duplicate chosen deterministically")
    memberships.insert(0, duplicate)

    def collect(rows: list[dict[str, Any]]) -> IndustryCandidate:
        def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
            if api_name == "index_classify":
                offset = params["offset"]
                return taxonomy[offset : offset + params["limit"]]
            return [row for row in rows if row["l1_code"] == params["l1_code"]]

        return collect_candidate(fetch, snapshot_id="snapshot-dedupe", source_run_id="run")

    first = collect(memberships)
    second = collect(list(reversed(memberships)))

    assert len(first.membership_rows) == len(_raw_memberships())
    comparable_first = [
        {key: value for key, value in row.items() if key != "collected_at"}
        for row in first.membership_rows
    ]
    comparable_second = [
        {key: value for key, value in row.items() if key != "collected_at"}
        for row in second.membership_rows
    ]
    assert comparable_first == comparable_second
    keys = [row["membership_key"] for row in first.membership_rows]
    assert len(keys) == len(set(keys))


def test_same_partition_same_assignment_duplicate_remains_semantically_successful() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    memberships.append(dict(memberships[0]))

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        return [row for row in memberships if row["l1_code"] == params["l1_code"]]

    candidate = collect_candidate(
        fetch,
        snapshot_id="snapshot-valid-duplicate",
        source_run_id="run-valid-duplicate",
    )
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert sum(candidate.partition_counts.values()) == 101
    assert sum(candidate.deduplicated_partition_counts.values()) == 100
    assert validation.successful_partition_count == 31
    assert validation.accepted is True


def test_same_assignment_smuggled_across_partitions_is_deduplicated_but_rejected() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    smuggled = dict(memberships[0], name="Cross-partition duplicate")

    def collect(reverse: bool) -> IndustryCandidate:
        def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
            if api_name == "index_classify":
                return taxonomy[params["offset"] : params["offset"] + params["limit"]]
            rows = [row for row in memberships if row["l1_code"] == params["l1_code"]]
            if params["l1_code"] == "L1-02":
                rows.append(smuggled)
            return list(reversed(rows)) if reverse else rows

        return collect_candidate(fetch, snapshot_id="snapshot-global-dedupe", source_run_id="run")

    first = collect(False)
    second = collect(True)
    first_rows = [{k: v for k, v in row.items() if k != "collected_at"} for row in first.membership_rows]
    second_rows = [{k: v for k, v in row.items() if k != "collected_at"} for row in second.membership_rows]

    assert first_rows == second_rows
    assert len(first.membership_rows) == len(memberships)
    assert len({row["membership_key"] for row in first.membership_rows}) == len(
        first.membership_rows
    )
    validation = validate_candidate(
        first,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )
    assert validation.accepted is False
    assert "partition_scope_mismatch" in validation.errors
    assert first.partition_counts["L1-02"] == 5
    assert sum(first.partition_counts.values()) == 101
    assert sum(first.deduplicated_partition_counts.values()) == 100


def test_conflicting_assignment_smuggled_across_partitions_is_rejected() -> None:
    taxonomy = _raw_taxonomy()
    memberships = _raw_memberships()
    conflict = dict(
        memberships[0],
        l1_code="L1-02",
        l1_name="Level 1 2",
        l2_code="L2-02",
        l2_name="Level 2 2",
        l3_code="L3-02",
        l3_name="Level 3 2",
    )

    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return taxonomy[params["offset"] : params["offset"] + params["limit"]]
        rows = [row for row in memberships if row["l1_code"] == params["l1_code"]]
        return [*rows, conflict] if params["l1_code"] == "L1-02" else rows

    candidate = collect_candidate(fetch, snapshot_id="snapshot-global-conflict", source_run_id="run")
    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert len(candidate.membership_rows) == len(memberships) + 1
    assert "conflicting_current_assignment" in validation.errors
    assert "duplicate_membership_key" in validation.errors


def test_validate_candidate_rejects_duplicate_membership_key_defensively() -> None:
    candidate = _collected_candidate()
    duplicate = dict(candidate.membership_rows[0])
    candidate = replace(candidate, membership_rows=(*candidate.membership_rows, duplicate))

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert "duplicate_membership_key" in validation.errors


@pytest.mark.parametrize(("level", "parent_level"), [(2, 1), (3, 2)])
def test_membership_hierarchy_must_follow_the_rows_parent_chain(
    level: int, parent_level: int
) -> None:
    candidate = _collected_candidate()
    rows = [dict(row) for row in candidate.membership_rows]
    rows[0][f"l{level}_code"] = f"L{level}-02"
    rows[0][f"l{level}_name"] = f"Level {level} 2"
    assert rows[0][f"l{parent_level}_code"] != f"L{parent_level}-02"
    candidate = replace(candidate, membership_rows=tuple(rows))

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert "membership_hierarchy_mismatch" in validation.errors


@pytest.mark.parametrize(
    ("row_kind", "field", "value"),
    [
        ("taxonomy", "snapshot_id", "other-snapshot"),
        ("taxonomy", "taxonomy_system", "OTHER"),
        ("taxonomy", "taxonomy_version", "SW2021-tampered"),
        ("taxonomy", "provider", "other-provider"),
        ("taxonomy", "collected_at", "2020-01-01T00:00:00+00:00"),
        ("taxonomy", "raw_json", "{}"),
        ("taxonomy", "raw_json", "[]"),
        ("taxonomy", "taxonomy_node_key", "tampered-hash"),
        ("taxonomy", "industry_name", "tampered-name"),
        ("membership", "snapshot_id", "other-snapshot"),
        ("membership", "market", "HK"),
        ("membership", "provider", "other-provider"),
        ("membership", "collected_at", "2020-01-01T00:00:00+00:00"),
        ("membership", "raw_json", "{}"),
        ("membership", "raw_json", "[]"),
        ("membership", "membership_key", "tampered-hash"),
        ("membership", "name", "tampered-name"),
    ],
)
def test_row_lineage_and_content_tampering_is_rejected(
    row_kind: str, field: str, value: str
) -> None:
    candidate = _collected_candidate()
    if row_kind == "taxonomy":
        rows = [dict(row) for row in candidate.taxonomy_rows]
        rows[0][field] = value
        candidate = replace(candidate, taxonomy_rows=tuple(rows))
        reason = "invalid_taxonomy_lineage"
    else:
        rows = [dict(row) for row in candidate.membership_rows]
        rows[0][field] = value
        candidate = replace(candidate, membership_rows=tuple(rows))
        reason = "invalid_membership_lineage"

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )

    assert reason in validation.errors


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("level", "LEVEL1", "invalid_taxonomy_level"),
        ("industry_name", "", "missing_required_taxonomy_field"),
        ("parent_industry_code", "does-not-exist", "invalid_taxonomy_parent"),
    ],
)
def test_taxonomy_nodes_require_valid_levels_names_and_parents(field: str, value: str, reason: str) -> None:
    candidate = _collected_candidate()
    rows = [dict(row) for row in candidate.taxonomy_rows]
    rows[-1][field] = value
    candidate = replace(candidate, taxonomy_rows=tuple(rows))

    validation = validate_candidate(
        candidate,
        {_symbol(number) for number in range(1, 101)},
        min_rows=1,
        max_rows=10_000,
    )
    assert reason in validation.errors


def test_eligible_universe_uses_only_valid_named_non_delisted_tushare_stocks() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE market_assets (
            market TEXT, symbol TEXT, name TEXT, asset_type TEXT, provider TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO market_assets VALUES (?, ?, ?, ?, ?)",
        [
            ("Ashare", "000001.SZ", "平安银行", "stock", "tushare_stock_basic"),
            ("Ashare", "600000.SH", "浦发银行", "stock", "tushare_stock_basic"),
            ("Ashare", "430001.BJ", "北交样本", "stock", "tushare_stock_basic"),
            ("Ashare", "000002.SZ", "退市样本", "stock", "tushare_stock_basic"),
            ("Ashare", "000003.SZ", " ", "stock", "tushare_stock_basic"),
            ("Ashare", "bad", "无效代码", "stock", "tushare_stock_basic"),
            ("Ashare", "000004.SZ", "错误来源", "stock", "other"),
            ("HK", "000005.SZ", "错误市场", "stock", "tushare_stock_basic"),
            ("Ashare", "000006.SZ", "错误类型", "index", "tushare_stock_basic"),
        ],
    )

    assert eligible_ashare_universe(conn) == {"000001.SZ", "600000.SH", "430001.BJ"}


def test_dedicated_collector_does_not_change_generic_api_mappings() -> None:
    assert API_TO_TABLE_MAP["index_classify"] == "market_assets"
    assert API_TO_TABLE_MAP["index_member_all"] == "market_relationships"
