"""DB-first read contract for versioned sector capital-flow facts.

This module never calls a provider and never falls back to files or another
table.  It exposes provider facts only; ranking, scoring, signals, and trading
decisions remain downstream responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import string
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime_paths import marketdata_sqlite_path


SQLITE_PATH: Path = marketdata_sqlite_path()
SQLITE_BUSY_TIMEOUT_MS = 250
FACT_KINDS = frozenset({"official_eod", "intraday_proxy"})
RUNTIME_STATUSES = frozenset({"success", "empty", "unobserved", "paused", "failed"})
PUBLISHED_STATUS = "published"
SNAPSHOT_TABLE = "market_sector_flow_snapshots_v2"
INDUSTRY_TABLE = "market_sector_flow_industries_v2"
CONSTITUENT_TABLE = "market_sector_flow_constituents_v2"
MONEY_FIELDS = ("gross_inflow", "gross_outflow", "net_inflow", "turnover_amount")


class SnapshotContractError(ValueError):
    """Raised when persisted sector-flow facts violate the v2 contract."""


def _without_source_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items() if key != "source_hash"}


def compute_source_hash(
    snapshot: dict[str, Any],
    industries: list[dict[str, Any]],
    constituents: list[dict[str, Any]],
) -> str:
    """Return the canonical SHA-256 binding for a complete v2 snapshot."""
    document = {
        "snapshot": _without_source_hash(dict(snapshot)),
        "industries": sorted(
            (_without_source_hash(dict(row)) for row in industries),
            key=lambda row: (str(row.get("industry_code") or ""),),
        ),
        "constituents": sorted(
            (_without_source_hash(dict(row)) for row in constituents),
            key=lambda row: (
                str(row.get("industry_code") or ""),
                str(row.get("symbol") or ""),
            ),
        ),
    }
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SnapshotContractError(
            "invalid canonical source content: non-finite or unsupported value"
        ) from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _aware_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotContractError(f"invalid PIT timestamp: {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotContractError(f"invalid PIT timezone: {field}")
    return parsed


def _nonnegative_count(snapshot: dict[str, Any], field: str) -> int:
    value = snapshot.get(field)
    if isinstance(value, bool):
        raise SnapshotContractError(f"invalid count: {field}")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SnapshotContractError(f"invalid count: {field}") from exc
    if parsed < 0 or parsed != value:
        raise SnapshotContractError(f"invalid count: {field}")
    return parsed


def _coverage_ratio(value: Any, *, field: str, observed: int, expected: int) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotContractError(f"invalid coverage ratio: {field}") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise SnapshotContractError(f"invalid coverage ratio: {field}")
    expected_ratio = (observed / expected) if expected else 0.0
    if not math.isclose(parsed, expected_ratio, rel_tol=0.0, abs_tol=1e-12):
        raise SnapshotContractError(f"coverage ratio does not match counts: {field}")
    return parsed


def _finite_numeric_fact(row: dict[str, Any], field: str) -> float:
    value = row.get(field)
    if isinstance(value, bool):
        raise SnapshotContractError(f"invalid finite numeric fact: {field}")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SnapshotContractError(f"invalid finite numeric fact: {field}") from exc
    if not math.isfinite(parsed):
        raise SnapshotContractError(f"invalid finite numeric fact: {field}")
    return parsed


def _validate_snapshot_contract(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> None:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    industries = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {INDUSTRY_TABLE} WHERE snapshot_id=? ORDER BY industry_code",
            (snapshot_id,),
        )
    ]
    constituents = [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {CONSTITUENT_TABLE} WHERE snapshot_id=? ORDER BY industry_code,symbol",
            (snapshot_id,),
        )
    ]

    if not snapshot_id:
        raise SnapshotContractError("invalid snapshot_id: non-empty identity required")
    if str(snapshot.get("schema_version") or "").strip() != "2":
        raise SnapshotContractError("invalid schema_version: expected 2")
    if snapshot.get("market") != "Ashare":
        raise SnapshotContractError("invalid market: expected Ashare")
    if not str(snapshot.get("source_run_id") or "").strip():
        raise SnapshotContractError("invalid source_run_id: non-empty identity required")
    try:
        _validate_fact_kind(str(snapshot.get("fact_kind") or ""))
    except ValueError as exc:
        raise SnapshotContractError(f"invalid persisted fact_kind: {exc}") from exc
    effective_at = _aware_datetime(snapshot.get("effective_at"), "effective_at")
    available_at = _aware_datetime(snapshot.get("available_at"), "available_at")
    collected_at = _aware_datetime(snapshot.get("collected_at"), "collected_at")
    if not effective_at <= available_at <= collected_at:
        raise SnapshotContractError("invalid PIT ordering: effective_at <= available_at <= collected_at required")
    trade_date = str(snapshot.get("trade_date") or "")
    if len(trade_date) != 8 or not trade_date.isdigit() or trade_date != effective_at.strftime("%Y%m%d"):
        raise SnapshotContractError("invalid PIT trade_date/effective_at binding")

    runtime_status = str(snapshot.get("runtime_status") or "")
    if runtime_status not in RUNTIME_STATUSES:
        raise SnapshotContractError("invalid runtime_status; expected success/empty/unobserved/paused/failed")
    runtime_reason = str(snapshot.get("runtime_reason") or "").strip()
    if runtime_status == "success" and runtime_reason:
        raise SnapshotContractError("runtime_reason must be empty for success")
    if runtime_status != "success" and not runtime_reason:
        raise SnapshotContractError(f"runtime_reason is required for {runtime_status}")

    expected_industries = _nonnegative_count(snapshot, "expected_industry_count")
    observed_industries = _nonnegative_count(snapshot, "observed_industry_count")
    expected_constituents = _nonnegative_count(snapshot, "expected_constituent_count")
    observed_constituents = _nonnegative_count(snapshot, "observed_constituent_count")
    if observed_industries > expected_industries or observed_constituents > expected_constituents:
        raise SnapshotContractError("observed count exceeds expected count")
    if observed_industries != len(industries) or observed_constituents != len(constituents):
        raise SnapshotContractError("observed count does not match persisted child rows")
    industry_coverage_ratio = _coverage_ratio(
        snapshot.get("industry_coverage_ratio"),
        field="industry_coverage_ratio",
        observed=observed_industries,
        expected=expected_industries,
    )
    constituent_coverage_ratio = _coverage_ratio(
        snapshot.get("constituent_coverage_ratio"),
        field="constituent_coverage_ratio",
        observed=observed_constituents,
        expected=expected_constituents,
    )
    if runtime_status == "empty" and (observed_industries or observed_constituents):
        raise SnapshotContractError("runtime_status empty requires zero observed rows")
    if runtime_status == "success" and (
        industry_coverage_ratio != 1.0 or constituent_coverage_ratio != 1.0
    ):
        raise SnapshotContractError(
            "runtime_status success requires full coverage for industries and constituents"
        )

    for row in [*industries, *constituents]:
        for field in MONEY_FIELDS:
            _finite_numeric_fact(row, field)

    industry_snapshot_id = str(snapshot.get("industry_snapshot_id") or "")
    sw_snapshot_row = conn.execute(
        """SELECT started_at, completed_at, status, promoted_at,
                  taxonomy_row_count, membership_row_count, unique_symbol_count
        FROM market_industry_snapshots
        WHERE snapshot_id=? AND taxonomy_system='SW' AND taxonomy_version='SW2021'
          AND status IN ('promoted','superseded') LIMIT 1""",
        (industry_snapshot_id,),
    ).fetchone()
    if sw_snapshot_row is None:
        raise SnapshotContractError("invalid SW2021 lineage: industry_snapshot_id is not published")
    sw_snapshot = dict(sw_snapshot_row)
    try:
        sw_started_at = _aware_datetime(sw_snapshot.get("started_at"), "SW2021 started_at")
        sw_completed_at = _aware_datetime(sw_snapshot.get("completed_at"), "SW2021 completed_at")
        sw_promoted_at = _aware_datetime(sw_snapshot.get("promoted_at"), "SW2021 promoted_at")
    except SnapshotContractError as exc:
        raise SnapshotContractError(f"cross-snapshot PIT: {exc}") from exc
    if not sw_started_at <= sw_completed_at <= sw_promoted_at <= available_at:
        raise SnapshotContractError(
            "cross-snapshot PIT conflict: SW2021 requires "
            "started_at <= completed_at <= promoted_at <= sector available_at"
        )

    taxonomy_rows = [
        dict(row)
        for row in conn.execute(
            """SELECT taxonomy_system, taxonomy_version, industry_code, collected_at
            FROM market_industry_taxonomy WHERE snapshot_id=?""",
            (industry_snapshot_id,),
        )
    ]
    membership_rows = [
        dict(row)
        for row in conn.execute(
            """SELECT market, symbol, l1_code, l2_code, l3_code, collected_at
            FROM market_industry_memberships WHERE snapshot_id=?""",
            (industry_snapshot_id,),
        )
    ]
    if not taxonomy_rows:
        raise SnapshotContractError(
            "cross-snapshot PIT: market_industry_taxonomy has no rows for pinned SW2021 snapshot"
        )
    if not membership_rows:
        raise SnapshotContractError(
            "cross-snapshot PIT: market_industry_memberships has no rows for pinned SW2021 snapshot"
        )

    for row in taxonomy_rows:
        if row.get("taxonomy_system") != "SW" or row.get("taxonomy_version") != "SW2021":
            raise SnapshotContractError(
                "invalid SW2021 taxonomy child identity: expected SW/SW2021"
            )
    for row in membership_rows:
        if row.get("market") != "Ashare":
            raise SnapshotContractError(
                "invalid SW2021 membership child identity: expected Ashare"
            )

    taxonomy_row_count = _nonnegative_count(sw_snapshot, "taxonomy_row_count")
    membership_row_count = _nonnegative_count(sw_snapshot, "membership_row_count")
    unique_symbol_count = _nonnegative_count(sw_snapshot, "unique_symbol_count")
    if taxonomy_row_count != len(taxonomy_rows):
        raise SnapshotContractError("SW2021 taxonomy_row_count does not match child rows")
    if membership_row_count != len(membership_rows):
        raise SnapshotContractError("SW2021 membership_row_count does not match child rows")
    if unique_symbol_count != len({row.get("symbol") for row in membership_rows}):
        raise SnapshotContractError(
            "SW2021 unique_symbol_count does not match distinct membership symbols"
        )

    for table, child_rows in (
        ("market_industry_taxonomy", taxonomy_rows),
        ("market_industry_memberships", membership_rows),
    ):
        for child_row in child_rows:
            try:
                child_collected_at = _aware_datetime(
                    child_row.get("collected_at"), f"{table} collected_at"
                )
            except SnapshotContractError as exc:
                raise SnapshotContractError(f"cross-snapshot PIT: {exc}") from exc
            if not sw_started_at <= child_collected_at <= sw_completed_at:
                raise SnapshotContractError(
                    f"cross-snapshot PIT conflict: {table} collected_at must be "
                    "between SW2021 started_at and completed_at"
                )

    snapshot_hash = str(snapshot.get("source_hash") or "")
    if (
        not snapshot_hash.startswith("sha256:")
        or len(snapshot_hash) != 71
        or snapshot_hash[7:] != snapshot_hash[7:].lower()
        or any(character not in string.hexdigits.lower() for character in snapshot_hash[7:].lower())
    ):
        raise SnapshotContractError("invalid source_hash format")
    for row in [*industries, *constituents]:
        if str(row.get("source_hash") or "") != snapshot_hash:
            raise SnapshotContractError("source_hash mismatch across snapshot tables")
    if compute_source_hash(snapshot, industries, constituents) != snapshot_hash:
        raise SnapshotContractError("source_hash mismatch with canonical snapshot content")
    for row in [*industries, *constituents]:
        for field in ("effective_at", "available_at", "provider"):
            if row.get(field) != snapshot.get(field):
                raise SnapshotContractError(f"source lineage mismatch: {field}")

    taxonomy_codes = {str(row.get("industry_code")) for row in taxonomy_rows}
    for row in industries:
        if str(row.get("industry_code") or "") not in taxonomy_codes:
            raise SnapshotContractError("invalid SW2021 lineage: industry code absent from taxonomy")
        count = _nonnegative_count(row, "constituent_count")
        covered = _nonnegative_count(row, "covered_constituent_count")
        if covered > count:
            raise SnapshotContractError("observed count exceeds expected count: industry constituents")
        _coverage_ratio(row.get("coverage_ratio"), field="industry coverage_ratio", observed=covered, expected=count)
        actual = sum(1 for item in constituents if item.get("industry_code") == row.get("industry_code"))
        if actual != covered:
            raise SnapshotContractError("industry covered constituent count does not match child rows")

    snapshot_industry_codes = {
        str(row.get("industry_code") or "") for row in industries
    }
    for row in constituents:
        if str(row.get("industry_code") or "") not in snapshot_industry_codes:
            raise SnapshotContractError(
                "constituent industry_code absent from snapshot industry rows"
            )
        membership = any(
            item.get("symbol") == row.get("symbol")
            and row.get("industry_code")
            in (item.get("l1_code"), item.get("l2_code"), item.get("l3_code"))
            for item in membership_rows
        )
        if not membership:
            raise SnapshotContractError("invalid SW2021 lineage: constituent membership absent")



def _validate_fact_kind(value: str | None, *, required: bool = True) -> str:
    normalized = str(value or "").strip()
    if not normalized and not required:
        return ""
    if normalized not in FACT_KINDS:
        raise ValueError("fact_kind must be official_eod or intraday_proxy")
    return normalized


def _validate_as_of(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of must include a timezone offset")
    return normalized


def _bounded_limit(value: Any, default: int = 500) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 1000))


def _connect() -> sqlite3.Connection:
    path = Path(SQLITE_PATH)
    conn = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0,
    )
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn


def _degraded(reason: str, *, reader: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "data": {},
            "provenance": {
                "source_id": f"sqlite:{SNAPSHOT_TABLE}",
                "source_tier": "unavailable",
                "collected_at": "",
            },
            "freshness": None,
            "quality": None,
            "degraded": True,
            "degraded_reasons": [reason],
            "lineage": {
                "reader": reader,
                "table": SNAPSHOT_TABLE,
                "filters": filters,
                "reason": reason,
                "fallback": "none",
            },
        }
    ]


def _resolve_snapshot(
    conn: sqlite3.Connection,
    *,
    reader: str,
    fact_kind: str,
    snapshot_id: str,
    as_of: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    filters = {
        "snapshot_id": snapshot_id or None,
        "fact_kind": fact_kind or None,
        "as_of": as_of or None,
    }
    where = ["status = ?"]
    params: list[Any] = [PUBLISHED_STATUS]
    if snapshot_id:
        where.append("snapshot_id = ?")
        params.append(snapshot_id)
    if fact_kind:
        where.append("fact_kind = ?")
        params.append(fact_kind)
    if as_of:
        where.append("julianday(available_at) <= julianday(?)")
        params.append(as_of)
    row = conn.execute(
        f"SELECT * FROM {SNAPSHOT_TABLE} WHERE {' AND '.join(where)} "
        "ORDER BY julianday(effective_at) DESC, julianday(available_at) DESC, snapshot_id DESC LIMIT 1",
        tuple(params),
    ).fetchone()
    if row is None:
        reason = (
            f"snapshot is not published: {snapshot_id}"
            if snapshot_id
            else f"no published {fact_kind} snapshot available at requested PIT"
        )
        return None, _degraded(reason, reader=reader, filters=filters)
    snapshot = dict(row)
    try:
        _validate_snapshot_contract(conn, snapshot)
    except SnapshotContractError as exc:
        return None, _degraded(
            f"invalid published snapshot contract: {exc}",
            reader=reader,
            filters=filters,
        )
    return snapshot, None


def _lineage(reader: str, table: str, snapshot: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "reader": reader,
        "table": table,
        "schema_version": snapshot["schema_version"],
        "snapshot_id": snapshot["snapshot_id"],
        "fact_kind": snapshot["fact_kind"],
        "industry_snapshot_id": snapshot["industry_snapshot_id"],
        "provider": snapshot["provider"],
        "source_run_id": snapshot["source_run_id"],
        "source_hash": snapshot["source_hash"],
        "effective_at": snapshot["effective_at"],
        "available_at": snapshot["available_at"],
        "collected_at": snapshot["collected_at"],
        "expected_industry_count": snapshot["expected_industry_count"],
        "observed_industry_count": snapshot["observed_industry_count"],
        "expected_constituent_count": snapshot["expected_constituent_count"],
        "observed_constituent_count": snapshot["observed_constituent_count"],
        "industry_coverage_ratio": snapshot["industry_coverage_ratio"],
        "constituent_coverage_ratio": snapshot["constituent_coverage_ratio"],
        "runtime_status": snapshot["runtime_status"],
        "runtime_reason": snapshot["runtime_reason"],
        "filters": filters,
        "fallback": "none",
    }


def _wrap(row: dict[str, Any], *, table: str, snapshot: dict[str, Any], reader: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": row,
        "provenance": {
            "source_id": f"sqlite:{table}",
            "source_tier": "fact",
            "collected_at": snapshot["collected_at"],
        },
        "freshness": {
            "effective_at": snapshot["effective_at"],
            "available_at": snapshot["available_at"],
            "collected_at": snapshot["collected_at"],
        },
        "quality": {
            "industry_coverage_ratio": snapshot["industry_coverage_ratio"],
            "constituent_coverage_ratio": snapshot["constituent_coverage_ratio"],
        },
        "degraded": snapshot["runtime_status"] != "success",
        "degraded_reasons": [snapshot["runtime_reason"]]
        if snapshot["runtime_status"] != "success" and snapshot.get("runtime_reason")
        else [],
        "lineage": _lineage(reader, table, snapshot, filters),
    }


def _read(
    *,
    reader: str,
    table: str,
    fact_kind: str | None,
    snapshot_id: str | None,
    as_of: str | None,
    industry_code: str = "",
    symbol: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    snapshot_key = str(snapshot_id or "").strip()
    kind = _validate_fact_kind(fact_kind, required=not bool(snapshot_key))
    pit = _validate_as_of(as_of)
    filters = {
        "snapshot_id": snapshot_key or None,
        "fact_kind": kind or None,
        "as_of": pit or None,
        "industry_code": industry_code or None,
        "symbol": symbol or None,
    }
    try:
        with _connect() as conn:
            snapshot, degraded = _resolve_snapshot(
                conn,
                reader=reader,
                fact_kind=kind,
                snapshot_id=snapshot_key,
                as_of=pit,
            )
            if degraded is not None:
                return degraded
            assert snapshot is not None
            if table == SNAPSHOT_TABLE:
                return [_wrap(snapshot, table=table, snapshot=snapshot, reader=reader, filters=filters)]
            where = ["snapshot_id = ?"]
            params: list[Any] = [snapshot["snapshot_id"]]
            if industry_code:
                where.append("industry_code = ?")
                params.append(industry_code)
            if symbol and table == CONSTITUENT_TABLE:
                where.append("symbol = ?")
                params.append(symbol)
            order = "industry_level, industry_code" if table == INDUSTRY_TABLE else "industry_code, symbol"
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
                (*params, _bounded_limit(limit)),
            ).fetchall()
            if not rows:
                return _degraded(
                    f"no rows in published snapshot {snapshot['snapshot_id']} matched filters",
                    reader=reader,
                    filters=filters,
                )
            return [
                _wrap(dict(row), table=table, snapshot=snapshot, reader=reader, filters=filters)
                for row in rows
            ]
    except sqlite3.Error as exc:
        return _degraded(
            f"database unavailable: {exc}", reader=reader, filters=filters
        )


def get_snapshot(*, fact_kind: str | None = None, snapshot_id: str | None = None, as_of: str | None = None) -> list[dict[str, Any]]:
    return _read(
        reader="get_sector_flow_snapshot_v2",
        table=SNAPSHOT_TABLE,
        fact_kind=fact_kind,
        snapshot_id=snapshot_id,
        as_of=as_of,
    )


def get_industries(
    *,
    fact_kind: str | None = None,
    snapshot_id: str | None = None,
    as_of: str | None = None,
    industry_code: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return _read(
        reader="get_sector_flow_industries_v2",
        table=INDUSTRY_TABLE,
        fact_kind=fact_kind,
        snapshot_id=snapshot_id,
        as_of=as_of,
        industry_code=str(industry_code or "").strip(),
        limit=limit,
    )


def get_constituents(
    *,
    fact_kind: str | None = None,
    snapshot_id: str | None = None,
    as_of: str | None = None,
    industry_code: str | None = None,
    symbol: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return _read(
        reader="get_sector_flow_constituents_v2",
        table=CONSTITUENT_TABLE,
        fact_kind=fact_kind,
        snapshot_id=snapshot_id,
        as_of=as_of,
        industry_code=str(industry_code or "").strip(),
        symbol=str(symbol or "").strip(),
        limit=limit,
    )
