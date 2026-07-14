from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import sector_flow_v2
from storage.schema import SCHEMA_SQL


SNAPSHOT_COLUMNS = (
    "snapshot_id", "schema_version", "fact_kind", "market", "trade_date",
    "effective_at", "available_at", "collected_at", "provider", "source_run_id",
    "source_hash", "industry_snapshot_id", "status", "expected_industry_count",
    "observed_industry_count", "expected_constituent_count", "observed_constituent_count",
    "industry_coverage_ratio", "constituent_coverage_ratio", "runtime_status",
    "runtime_reason", "raw_json",
)
INDUSTRY_COLUMNS = (
    "snapshot_id", "industry_code", "industry_name", "industry_level", "effective_at",
    "available_at", "provider", "source_hash", "gross_inflow", "gross_outflow",
    "net_inflow", "turnover_amount", "constituent_count", "covered_constituent_count",
    "coverage_ratio", "raw_json",
)
CONSTITUENT_COLUMNS = (
    "snapshot_id", "industry_code", "symbol", "name", "effective_at", "available_at",
    "provider", "source_hash", "gross_inflow", "gross_outflow", "net_inflow",
    "turnover_amount", "raw_json",
)


def _insert_dict(conn: sqlite3.Connection, table: str, row: dict, columns: tuple[str, ...]) -> None:
    conn.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(row[column] for column in columns),
    )


def _snapshot(snapshot_id: str, fact_kind: str, runtime_status: str, *, status: str = "published") -> dict:
    is_eod = fact_kind == "official_eod"
    return {
        "snapshot_id": snapshot_id,
        "schema_version": "2",
        "fact_kind": fact_kind,
        "market": "Ashare",
        "trade_date": "20260713" if is_eod else "20260714",
        "effective_at": "2026-07-13T15:00:00+08:00" if is_eod else "2026-07-14T10:30:00+08:00",
        "available_at": "2026-07-13T18:00:00+08:00" if is_eod else "2026-07-14T10:31:00+08:00",
        "collected_at": "2026-07-13T18:01:00+08:00" if is_eod else "2026-07-14T10:31:30+08:00",
        "provider": "official_provider" if is_eod else "proxy_provider",
        "source_run_id": f"run-{snapshot_id}",
        "source_hash": "pending",
        "industry_snapshot_id": "sw-2021-a",
        "status": status,
        "expected_industry_count": 1,
        "observed_industry_count": 1,
        "expected_constituent_count": 1,
        "observed_constituent_count": 1,
        "industry_coverage_ratio": 1.0,
        "constituent_coverage_ratio": 1.0,
        "runtime_status": runtime_status,
        "runtime_reason": None if runtime_status == "success" else f"runtime {runtime_status}",
        "raw_json": "{}",
    }


def _facts(header: dict, industry_code: str, symbol: str) -> tuple[dict, dict]:
    industry = {
        "snapshot_id": header["snapshot_id"], "industry_code": industry_code,
        "industry_name": "电子" if industry_code == "801080" else "农林牧渔",
        "industry_level": "L1", "effective_at": header["effective_at"],
        "available_at": header["available_at"], "provider": header["provider"],
        "source_hash": "pending", "gross_inflow": 10.0, "gross_outflow": 4.0,
        "net_inflow": 6.0, "turnover_amount": 100.0, "constituent_count": 1,
        "covered_constituent_count": 1, "coverage_ratio": 1.0, "raw_json": "{}",
    }
    constituent = {
        "snapshot_id": header["snapshot_id"], "industry_code": industry_code,
        "symbol": symbol, "name": "测试股票", "effective_at": header["effective_at"],
        "available_at": header["available_at"], "provider": header["provider"],
        "source_hash": "pending", "gross_inflow": 4.0, "gross_outflow": 1.0,
        "net_inflow": 3.0, "turnover_amount": 20.0, "raw_json": "{}",
    }
    return industry, constituent


def _apply_hash(header: dict, industries: list[dict], constituents: list[dict]) -> None:
    source_hash = sector_flow_v2.compute_source_hash(header, industries, constituents)
    header["source_hash"] = source_hash
    for row in [*industries, *constituents]:
        row["source_hash"] = source_hash


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        """INSERT INTO market_industry_snapshots
        (snapshot_id,taxonomy_system,taxonomy_version,provider,started_at,completed_at,status,
         expected_partition_count,successful_partition_count,taxonomy_row_count,membership_row_count,
         unique_symbol_count,active_universe_count,coverage_ratio,validation_errors_json,source_run_id,promoted_at)
        VALUES ('sw-2021-a','SW','SW2021','tushare','2026-07-13T00:00:00+08:00',
        '2026-07-13T01:00:00+08:00','promoted',1,1,2,2,2,2,1.0,'[]','sw-run','2026-07-13T01:00:00+08:00')"""
    )
    for code, name, symbol, key in (
        ("801010", "农林牧渔", "000001.SZ", "a"),
        ("801080", "电子", "600000.SH", "b"),
    ):
        conn.execute(
            "INSERT INTO market_industry_taxonomy VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"node-{key}", "sw-2021-a", "SW", "SW2021", "L1", code, code, name, None, "1", "tushare", "2026-07-13T01:00:00+08:00", "{}"),
        )
        conn.execute(
            "INSERT INTO market_industry_memberships VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"member-{key}", "sw-2021-a", "Ashare", symbol, "测试股票", code, name, code, name, code, name, None, None, "1", "tushare", "2026-07-13T01:00:00+08:00", "{}"),
        )

    for header, industry_code, symbol in (
        (_snapshot("eod-1", "official_eod", "success"), "801010", "000001.SZ"),
        (_snapshot("proxy-1", "intraday_proxy", "unobserved"), "801080", "600000.SH"),
        (_snapshot("proxy-draft", "intraday_proxy", "unobserved", status="collecting"), "801080", "600000.SH"),
    ):
        industry, constituent = _facts(header, industry_code, symbol)
        _apply_hash(header, [industry], [constituent])
        _insert_dict(conn, "market_sector_flow_snapshots_v2", header, SNAPSHOT_COLUMNS)
        _insert_dict(conn, "market_sector_flow_industries_v2", industry, INDUSTRY_COLUMNS)
        _insert_dict(conn, "market_sector_flow_constituents_v2", constituent, CONSTITUENT_COLUMNS)
    conn.commit()
    conn.close()


def _rehash(path: Path, snapshot_id: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    header = dict(conn.execute("SELECT * FROM market_sector_flow_snapshots_v2 WHERE snapshot_id=?", (snapshot_id,)).fetchone())
    industries = [dict(row) for row in conn.execute("SELECT * FROM market_sector_flow_industries_v2 WHERE snapshot_id=?", (snapshot_id,))]
    constituents = [dict(row) for row in conn.execute("SELECT * FROM market_sector_flow_constituents_v2 WHERE snapshot_id=?", (snapshot_id,))]
    source_hash = sector_flow_v2.compute_source_hash(header, industries, constituents)
    conn.execute("UPDATE market_sector_flow_snapshots_v2 SET source_hash=? WHERE snapshot_id=?", (source_hash, snapshot_id))
    conn.execute("UPDATE market_sector_flow_industries_v2 SET source_hash=? WHERE snapshot_id=?", (source_hash, snapshot_id))
    conn.execute("UPDATE market_sector_flow_constituents_v2 SET source_hash=? WHERE snapshot_id=?", (source_hash, snapshot_id))
    conn.commit()
    conn.close()


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "sector-flow.sqlite"
    _seed_db(path)
    monkeypatch.setattr(sector_flow_v2, "SQLITE_PATH", path)
    return path


def _assert_invalid_snapshot(db: Path, expected_reason: str) -> None:
    rows = sector_flow_v2.get_snapshot(fact_kind="official_eod")
    assert rows[0]["degraded"] is True
    assert rows[0]["data"] == {}
    assert expected_reason in rows[0]["lineage"]["reason"]


def _read_entrypoint(entrypoint: str) -> list[dict]:
    if entrypoint == "latest":
        return sector_flow_v2.get_snapshot(fact_kind="official_eod")
    if entrypoint == "as_of":
        return sector_flow_v2.get_snapshot(
            fact_kind="official_eod", as_of="2026-07-13T20:00:00+08:00"
        )
    if entrypoint == "pinned":
        return sector_flow_v2.get_snapshot(snapshot_id="eod-1")
    raise AssertionError(f"unknown test entrypoint: {entrypoint}")


def test_latest_snapshot_is_fact_kind_isolated_and_reports_runtime_truth(db: Path) -> None:
    rows = sector_flow_v2.get_snapshot(fact_kind="intraday_proxy")
    assert rows[0]["data"]["snapshot_id"] == "proxy-1"
    assert rows[0]["data"]["runtime_status"] == "unobserved"
    assert rows[0]["degraded"] is True
    assert rows[0]["lineage"]["fact_kind"] == "intraday_proxy"
    assert rows[0]["lineage"]["source_hash"] == rows[0]["data"]["source_hash"]


@pytest.mark.parametrize("runtime_status", ["success", "empty", "unobserved", "paused", "failed"])
def test_runtime_five_state_contract(db: Path, runtime_status: str) -> None:
    conn = sqlite3.connect(db)
    reason = None if runtime_status == "success" else f"runtime {runtime_status}"
    conn.execute("UPDATE market_sector_flow_snapshots_v2 SET runtime_status=?,runtime_reason=? WHERE snapshot_id='eod-1'", (runtime_status, reason))
    if runtime_status == "empty":
        conn.execute("DELETE FROM market_sector_flow_industries_v2 WHERE snapshot_id='eod-1'")
        conn.execute("DELETE FROM market_sector_flow_constituents_v2 WHERE snapshot_id='eod-1'")
        conn.execute(
            """UPDATE market_sector_flow_snapshots_v2
            SET expected_industry_count=0,observed_industry_count=0,
                expected_constituent_count=0,observed_constituent_count=0,
                industry_coverage_ratio=0,constituent_coverage_ratio=0
            WHERE snapshot_id='eod-1'"""
        )
    conn.commit()
    conn.close()
    _rehash(db, "eod-1")
    rows = sector_flow_v2.get_snapshot(fact_kind="official_eod")
    assert rows[0]["data"]["runtime_status"] == runtime_status
    assert rows[0]["degraded"] is (runtime_status != "success")


def test_pit_as_of_uses_available_at_not_effective_at(db: Path) -> None:
    rows = sector_flow_v2.get_snapshot(fact_kind="official_eod", as_of="2026-07-13T17:59:59+08:00")
    assert rows[0]["degraded"] is True
    assert "no published" in rows[0]["lineage"]["reason"]


def test_explicit_unpublished_snapshot_is_fail_closed(db: Path) -> None:
    rows = sector_flow_v2.get_snapshot(snapshot_id="proxy-draft")
    assert rows[0]["degraded"] is True
    assert "not published" in rows[0]["lineage"]["reason"]


def test_industries_return_snapshot_pit_source_and_coverage(db: Path) -> None:
    rows = sector_flow_v2.get_industries(fact_kind="official_eod")
    assert rows[0]["data"]["industry_code"] == "801010"
    assert rows[0]["data"]["net_inflow"] == 6.0
    assert rows[0]["lineage"]["industry_coverage_ratio"] == 1.0
    assert rows[0]["lineage"]["available_at"] == "2026-07-13T18:00:00+08:00"


def test_constituents_are_filterable_without_cross_snapshot_fallback(db: Path) -> None:
    rows = sector_flow_v2.get_constituents(fact_kind="intraday_proxy", industry_code="801080", symbol="600000.SH")
    assert [row["data"]["symbol"] for row in rows] == ["600000.SH"]
    assert rows[0]["lineage"]["snapshot_id"] == "proxy-1"


def test_source_hash_rejects_header_tampering(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute("UPDATE market_sector_flow_snapshots_v2 SET provider='tampered' WHERE snapshot_id='eod-1'")
    conn.commit(); conn.close()
    _assert_invalid_snapshot(db, "source_hash mismatch")


def test_source_hash_rejects_child_content_tampering(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute("UPDATE market_sector_flow_industries_v2 SET net_inflow=999 WHERE snapshot_id='eod-1'")
    conn.commit(); conn.close()
    _assert_invalid_snapshot(db, "source_hash mismatch")


def test_success_with_rehashed_half_coverage_is_fail_closed(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """UPDATE market_sector_flow_snapshots_v2
        SET expected_industry_count=2, industry_coverage_ratio=0.5,
            expected_constituent_count=2, constituent_coverage_ratio=0.5
        WHERE snapshot_id='eod-1'"""
    )
    conn.commit(); conn.close()
    _rehash(db, "eod-1")
    _assert_invalid_snapshot(db, "runtime_status success requires full coverage")


def test_rehashed_constituent_without_snapshot_industry_row_is_fail_closed(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """UPDATE market_sector_flow_industries_v2
        SET covered_constituent_count=0, coverage_ratio=0
        WHERE snapshot_id='eod-1' AND industry_code='801010'"""
    )
    conn.execute(
        """UPDATE market_sector_flow_constituents_v2
        SET industry_code='801080', symbol='600000.SH'
        WHERE snapshot_id='eod-1'"""
    )
    conn.commit(); conn.close()
    _rehash(db, "eod-1")
    _assert_invalid_snapshot(db, "constituent industry_code absent from snapshot industry rows")


def test_future_sw2021_promotion_and_children_fail_closed_for_latest_and_as_of(db: Path) -> None:
    conn = sqlite3.connect(db)
    future = "2026-07-13T19:00:00+08:00"
    conn.execute(
        """UPDATE market_industry_snapshots
        SET completed_at=?, promoted_at=?
        WHERE snapshot_id='sw-2021-a'""",
        (future, future),
    )
    conn.execute(
        "UPDATE market_industry_taxonomy SET collected_at=? WHERE snapshot_id='sw-2021-a'",
        (future,),
    )
    conn.execute(
        "UPDATE market_industry_memberships SET collected_at=? WHERE snapshot_id='sw-2021-a'",
        (future,),
    )
    conn.commit(); conn.close()

    latest = sector_flow_v2.get_snapshot(fact_kind="official_eod")
    point_in_time = sector_flow_v2.get_snapshot(
        fact_kind="official_eod", as_of="2026-07-13T20:00:00+08:00"
    )
    for rows in (latest, point_in_time):
        assert rows[0]["degraded"] is True
        assert rows[0]["data"] == {}
        assert "cross-snapshot PIT" in rows[0]["lineage"]["reason"]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE market_industry_snapshots SET promoted_at=NULL "
        "WHERE snapshot_id='sw-2021-a'",
        "UPDATE market_industry_snapshots SET completed_at='2026-07-13T01:00:00' "
        "WHERE snapshot_id='sw-2021-a'",
        "UPDATE market_industry_taxonomy SET collected_at='2026-07-12T23:59:59+08:00' "
        "WHERE snapshot_id='sw-2021-a' AND taxonomy_node_key='node-a'",
    ],
)
def test_cross_snapshot_pit_missing_naive_and_conflict_remain_fail_closed(
    db: Path, sql: str
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(sql)
    conn.commit()
    conn.close()
    _rehash(db, "eod-1")
    _assert_invalid_snapshot(db, "cross-snapshot PIT")


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        (
            "UPDATE market_industry_taxonomy SET taxonomy_system='CITIC' "
            "WHERE snapshot_id='sw-2021-a' AND taxonomy_node_key='node-a'",
            "taxonomy child identity",
        ),
        (
            "UPDATE market_industry_taxonomy SET taxonomy_version='SW2024' "
            "WHERE snapshot_id='sw-2021-a' AND taxonomy_node_key='node-a'",
            "taxonomy child identity",
        ),
        (
            "UPDATE market_industry_memberships SET market='HK' "
            "WHERE snapshot_id='sw-2021-a' AND membership_key='member-a'",
            "membership child identity",
        ),
        (
            "UPDATE market_industry_snapshots SET taxonomy_row_count=1 "
            "WHERE snapshot_id='sw-2021-a'",
            "taxonomy_row_count",
        ),
        (
            "UPDATE market_industry_snapshots SET membership_row_count=1 "
            "WHERE snapshot_id='sw-2021-a'",
            "membership_row_count",
        ),
        (
            "UPDATE market_industry_snapshots SET unique_symbol_count=1 "
            "WHERE snapshot_id='sw-2021-a'",
            "unique_symbol_count",
        ),
    ],
)
def test_rehashed_sw2021_child_identity_and_header_counts_fail_closed(
    db: Path, sql: str, reason: str
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(sql)
    conn.commit()
    conn.close()
    _rehash(db, "eod-1")
    _assert_invalid_snapshot(db, reason)


@pytest.mark.parametrize(
    ("field", "value", "entrypoint", "reason"),
    [
        ("schema_version", "3", "latest", "schema_version"),
        ("market", "HK", "as_of", "market"),
        ("source_run_id", " ", "pinned", "source_run_id"),
    ],
)
def test_rehashed_v2_header_identity_fails_closed_across_all_entrypoints(
    db: Path, field: str, value: str, entrypoint: str, reason: str
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        f"UPDATE market_sector_flow_snapshots_v2 SET {field}=? WHERE snapshot_id='eod-1'",
        (value,),
    )
    conn.commit()
    conn.close()
    _rehash(db, "eod-1")

    rows = _read_entrypoint(entrypoint)
    assert rows[0]["degraded"] is True
    assert rows[0]["data"] == {}
    assert reason in rows[0]["lineage"]["reason"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_hash_normalizes_nonfinite_numbers_to_contract_error(value: float) -> None:
    header = _snapshot("finite-check", "official_eod", "success")
    industry, constituent = _facts(header, "801010", "000001.SZ")
    industry["gross_inflow"] = value

    with pytest.raises(sector_flow_v2.SnapshotContractError, match="non-finite"):
        sector_flow_v2.compute_source_hash(header, [industry], [constituent])


@pytest.mark.parametrize(
    ("table", "field", "value", "reader"),
    [
        (
            "market_sector_flow_industries_v2",
            "gross_inflow",
            float("nan"),
            sector_flow_v2.get_industries,
        ),
        (
            "market_sector_flow_industries_v2",
            "turnover_amount",
            float("inf"),
            sector_flow_v2.get_industries,
        ),
        (
            "market_sector_flow_constituents_v2",
            "net_inflow",
            float("-inf"),
            sector_flow_v2.get_constituents,
        ),
    ],
)
def test_nonfinite_industry_and_constituent_facts_return_degraded_empty(
    db: Path, table: str, field: str, value: object, reader: object
) -> None:
    conn = sqlite3.connect(db)
    conn.execute(f"UPDATE {table} SET {field}=? WHERE snapshot_id='eod-1'", (value,))
    conn.commit()
    conn.close()
    if isinstance(value, float) and value != value:
        _rehash(db, "eod-1")

    rows = reader(fact_kind="official_eod")
    assert rows[0]["degraded"] is True
    assert rows[0]["data"] == {}
    assert "finite numeric fact" in rows[0]["lineage"]["reason"]


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("UPDATE market_sector_flow_snapshots_v2 SET available_at='2026-07-13T14:59:00+08:00' WHERE snapshot_id='eod-1'", "PIT ordering"),
        ("UPDATE market_sector_flow_snapshots_v2 SET industry_coverage_ratio=2 WHERE snapshot_id='eod-1'", "coverage ratio"),
        ("UPDATE market_sector_flow_snapshots_v2 SET observed_industry_count=2 WHERE snapshot_id='eod-1'", "observed count exceeds expected"),
        ("UPDATE market_sector_flow_snapshots_v2 SET industry_snapshot_id='missing-sw' WHERE snapshot_id='eod-1'", "SW2021 lineage"),
        ("UPDATE market_sector_flow_snapshots_v2 SET runtime_status='active' WHERE snapshot_id='eod-1'", "runtime_status"),
    ],
)
def test_invalid_snapshot_contract_is_fail_closed_even_when_rehashed(db: Path, sql: str, reason: str) -> None:
    conn = sqlite3.connect(db); conn.execute(sql); conn.commit(); conn.close()
    _rehash(db, "eod-1")
    _assert_invalid_snapshot(db, reason)


def test_invalid_source_hash_format_is_fail_closed(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """UPDATE market_sector_flow_snapshots_v2
        SET source_hash='sha256:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz'
        WHERE snapshot_id='eod-1'"""
    )
    conn.commit(); conn.close()
    _assert_invalid_snapshot(db, "source_hash format")


def test_invalid_fact_kind_is_rejected(db: Path) -> None:
    with pytest.raises(ValueError, match="fact_kind"):
        sector_flow_v2.get_snapshot(fact_kind="blended")


def test_invalid_as_of_requires_timezone(db: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        sector_flow_v2.get_snapshot(fact_kind="official_eod", as_of="2026-07-13T18:00:00")


def test_missing_database_returns_degraded_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sector_flow_v2, "SQLITE_PATH", tmp_path / "missing.sqlite")
    rows = sector_flow_v2.get_industries(fact_kind="official_eod")
    assert rows[0]["degraded"] is True
    assert "database unavailable" in rows[0]["lineage"]["reason"]
