from __future__ import annotations

import sqlite3
from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest

from collectors.tushare.sw2021_reference import (
    MEMBERSHIP_FIELDS,
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
            return taxonomy
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
            return taxonomy
        return [row for row in memberships if row["l1_code"] == params["l1_code"]]

    candidate = collect_candidate(fetch, snapshot_id="snapshot-capture", source_run_id="run-capture")
    member_calls = [call for call in calls if call[0] == "index_member_all"]
    taxonomy_calls = [call for call in calls if call[0] == "index_classify"]

    assert taxonomy_calls == [
        (
            "index_classify",
            {"level": "", "src": "SW2021"},
            "index_code,industry_name,parent_code,level,industry_code,is_pub",
        )
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


def test_provider_partition_failure_is_preserved_and_rejected() -> None:
    def fetch(api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        if api_name == "index_classify":
            return _raw_taxonomy()
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
