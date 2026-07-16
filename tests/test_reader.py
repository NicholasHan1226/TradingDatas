"""test_reader.py — mock storage, test each function return format + metadata + error handling.

Tests read-side functions from storage/schema.py, bridge/ modules,
and reference/market_calendar.py.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from pagination import encode_cursor  # noqa: E402


class _LegacyQueryRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, request, *, access, now, request_id, options):
        self.calls.append(
            {
                "request": request,
                "access": access,
                "now": now,
                "request_id": request_id,
                "options": options,
            }
        )
        return {
            "api_version": "v1",
            "catalog_version": "catalog-test",
            "request_id": request_id,
            "dataset_id": request.dataset_id,
            "schema_version": "1.0.0",
            "data": [{"symbol": "000001.SZ", "market": "Ashare"}],
            "next_cursor": "signed-next-page",
            "metadata": {
                "state": "ready",
                "runtime_state": "success",
                "degraded": False,
                "freshness": {
                    "state": "fresh",
                    "stale": False,
                    "sla_seconds": 3600,
                },
                "quality": {"state": "valid", "valid": True, "evidence": []},
                "lineage": {
                    "authority": "sqlite_ingest_receipts",
                    "providers": ["tushare"],
                    "receipt_watermark": "watermark-test",
                },
                "receipt_id": "receipt-test",
                "data_through": "20260716",
                "observed_at": "2026-07-16T03:00:00+00:00",
                "reasons": [],
            },
        }


def _legacy_runtime_recorder(monkeypatch: pytest.MonkeyPatch):
    import reader
    from dataset_registry import load_dataset_registry
    from legacy_query_compat import LegacyQueryCompat

    registry = load_dataset_registry()
    query = _LegacyQueryRecorder()
    runtime = SimpleNamespace(
        registry=registry,
        query=query,
        legacy=LegacyQueryCompat(registry),
    )
    monkeypatch.setattr(
        reader,
        "_build_data_plane_runtime",
        lambda: runtime,
        raising=False,
    )
    return reader, query


def _forbid_migrated_independent_readers(
    reader: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("migrated route touched an independent legacy reader")

    for name in ("_query_tushare_rows", "_sqlite_rows", "_connect_sqlite_ro"):
        monkeypatch.setattr(reader, name, forbidden, raising=False)


def test_migrated_reader_entrypoints_share_query_service_without_legacy_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, query = _legacy_runtime_recorder(monkeypatch)
    _forbid_migrated_independent_readers(reader, monkeypatch)

    tushare_rows = reader.get_tushare("daily", limit=1)
    stock_rows = reader.get_reference("stock_master", limit=1)

    assert [row["data"]["symbol"] for row in tushare_rows] == ["000001.SZ"]
    assert [row["data"]["symbol"] for row in stock_rows] == ["000001.SZ"]
    assert tushare_rows[0]["lineage"]["next_cursor"] == "signed-next-page"
    assert stock_rows[0]["lineage"]["next_cursor"] == "signed-next-page"
    assert [call["request"].dataset_id for call in query.calls] == [
        "cn.equity.daily",
        "cn.equity.security_master",
    ]
    assert query.calls[0]["options"].latest_partition is True
    assert query.calls[0]["access"].tenant_id == "legacy-reader"
    assert query.calls[1]["access"].policy_id == query.calls[0]["access"].policy_id


@pytest.mark.parametrize("table", ["stock_master", "STOCK_MASTER", " Stock_Master "])
def test_reader_stock_master_spellings_share_the_canonical_migrated_branch(
    monkeypatch: pytest.MonkeyPatch,
    table: str,
) -> None:
    reader, query = _legacy_runtime_recorder(monkeypatch)
    _forbid_migrated_independent_readers(reader, monkeypatch)

    rows = reader.get_reference(table, limit=1)

    assert [row["data"]["symbol"] for row in rows] == ["000001.SZ"]
    assert query.calls[-1]["request"].dataset_id == "cn.equity.security_master"


def test_non_stock_reference_keeps_the_existing_legacy_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, query = _legacy_runtime_recorder(monkeypatch)

    rows = reader.get_reference("legacy_csv_table")

    assert rows[0]["degraded"] is True
    assert "reference CSV endpoints are retired" in rows[0]["lineage"]["reason"]
    assert query.calls == []


# ============================================================================
# storage/schema.py tests
# ============================================================================

class TestSchemaSQL:
    """Validate the SCHEMA_SQL definition."""

    def test_schema_is_nonempty_string(self):
        from storage.schema import SCHEMA_SQL
        assert isinstance(SCHEMA_SQL, str)
        assert len(SCHEMA_SQL) > 100

    def test_schema_contains_all_expected_tables(self):
        from storage.schema import SCHEMA_SQL
        required_tables = [
            "market_assets", "market_bars_daily", "market_bars_intraday",
            "market_events", "market_pm_markets", "market_pm_prices",
            "market_factors", "market_ingest_runs", "market_coverage_status",
            "market_backfill_status", "provider_interface_matrix",
            "market_relationships", "market_fund_portfolio",
        ]
        for table in required_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL, \
                f"Missing table: {table}"

    def test_schema_executes_without_error(self, tmp_db: sqlite3.Connection):
        """Schema should execute cleanly."""
        from storage.schema import SCHEMA_SQL
        tmp_db.executescript(SCHEMA_SQL)
        tables = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "market_assets" in table_names
        assert "market_bars_daily" in table_names
        assert "market_events" in table_names

    def test_schema_is_idempotent(self, tmp_db: sqlite3.Connection):
        """Running schema twice should not error."""
        from storage.schema import SCHEMA_SQL
        tmp_db.executescript(SCHEMA_SQL)
        tmp_db.executescript(SCHEMA_SQL)  # second run — no error


# ============================================================================
# bridge/marketgraph_marketdata_db.py tests
# ============================================================================

class TestMarketdataDB:
    """Test the marketdata database bridge functions."""

    def test_connect_returns_connection(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_connect_sets_row_factory(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        assert conn.row_factory is not None
        conn.close()

    def test_connect_creates_schema(self, tmp_db_path: str):
        from bridge.marketgraph_marketdata_db import connect
        conn = connect(Path(tmp_db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) >= 11
        conn.close()

    def test_query_market_assets_returns_rows(self, tmp_db_with_data: sqlite3.Connection):
        conn = tmp_db_with_data
        rows = conn.execute(
            "SELECT * FROM market_assets WHERE market = ?", ("Ashare",)
        ).fetchall()
        assert len(rows) >= 1
        row = rows[0]
        assert row["symbol"] is not None
        assert row["market"] == "Ashare"
        assert isinstance(row["symbol"], str)

    def test_query_bars_daily_has_ohlcv(self, tmp_db_with_data: sqlite3.Connection):
        conn = tmp_db_with_data
        rows = conn.execute(
            "SELECT * FROM market_bars_daily WHERE symbol = ?", ("000001.SZ",)
        ).fetchall()
        assert len(rows) >= 1
        row = rows[0]
        for field in ("open", "high", "low", "close", "volume"):
            assert field in row.keys()
            assert row[field] is not None


# ============================================================================
# reader event tests
# ============================================================================

class TestReaderEvents:
    def test_event_cursor_is_opaque_endpoint_bound_and_snapshot_checked(self):
        from pagination import decode_cursor, encode_cursor

        cursor = encode_cursor(
            "events",
            "snap-1",
            ("2026-07-11T09:30:00Z", "event-1", 2, "hash-1"),
        )

        assert "event-1" not in cursor
        assert decode_cursor(cursor, scope="events", snapshot_id="snap-1") == (
            "2026-07-11T09:30:00Z",
            "event-1",
            2,
            "hash-1",
        )
        with pytest.raises(ValueError, match="^invalid cursor$"):
            decode_cursor(cursor, scope="industry_taxonomy")
        with pytest.raises(ValueError, match="^cursor snapshot mismatch$"):
            decode_cursor(cursor, scope="events", snapshot_id="snap-2")

    def test_event_cursor_rejects_legacy_three_part_sort_key(self):
        import reader
        from pagination import encode_cursor

        legacy_cursor = encode_cursor(
            "events", "", ("2026-07-11T09:30:00Z", "event-1", 2)
        )

        with pytest.raises(ValueError, match="^invalid cursor$"):
            reader.get_events_page(limit=2, cursor=legacy_cursor)

    @pytest.mark.parametrize("cursor", ["", "not-base64!", "e30"])
    def test_event_cursor_rejects_malformed_payloads(self, cursor: str):
        from pagination import decode_cursor

        with pytest.raises(ValueError, match="^invalid cursor$"):
            decode_cursor(cursor, scope="events")

    def test_events_cursor_has_no_duplicates_across_equal_timestamps(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"h{idx}",
                        1,
                        "unit",
                        "news",
                        "2026-07-11T09:30:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T09:31:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 5)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=2)
        second = reader.get_events_page(limit=2, cursor=first["next_cursor"])
        legacy_first = reader.get_events(limit=2)

        ids = [row["data"]["event_hash"] for row in first["rows"] + second["rows"]]
        assert ids == ["h4", "h3", "h2", "h1"]
        assert len(ids) == len(set(ids))
        assert legacy_first == first["rows"]
        assert first["row_count"] == 2
        assert second == {"rows": second["rows"], "next_cursor": None, "row_count": 2}

    def test_events_cursor_traverses_identical_logical_keys_by_physical_hash(
        self, tmp_path: Path, monkeypatch
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, 'same-event', 1, 'unit', 'news',
                          '2026-07-11T09:30:00+00:00', '20260711', 'Ashare',
                          '000001.SZ', ?, '', '', 'unit', 'unit',
                          '2026-07-11T09:31:00+00:00', '{}')
                """,
                [(f"physical-hash-{idx}", f"event {idx}") for idx in range(1, 5)],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=2)
        second = reader.get_events_page(limit=2, cursor=first["next_cursor"])

        hashes = [row["data"]["event_hash"] for row in first["rows"] + second["rows"]]
        assert hashes == [
            "physical-hash-4",
            "physical-hash-3",
            "physical-hash-2",
            "physical-hash-1",
        ]
        assert len(hashes) == len(set(hashes))
        assert second["next_cursor"] is None

    @pytest.mark.parametrize(
        ("bad_field", "bad_value"),
        [("__cursor_time", ""), ("__cursor_revision", "not-an-integer")],
    )
    def test_events_page_fails_closed_for_bad_non_boundary_lookahead_row(
        self, monkeypatch, bad_field: str, bad_value: object
    ):
        import reader

        rows = [
            {
                "event_hash": "h3",
                "event_id": "event-3",
                "revision": 1,
                "collected_at": "2026-07-11T10:00:00+00:00",
                "__cursor_time": "2026-07-11T09:33:00+00:00",
                "__cursor_event_key": "event-3",
                "__cursor_revision": 1,
                "__cursor_event_hash": "h3",
            },
            {
                "event_hash": "h2",
                "event_id": "event-2",
                "revision": 1,
                "collected_at": "2026-07-11T10:00:00+00:00",
                "__cursor_time": "2026-07-11T09:32:00+00:00",
                "__cursor_event_key": "event-2",
                "__cursor_revision": 1,
                "__cursor_event_hash": "h2",
            },
            {
                "event_hash": "h1",
                "event_id": "event-1",
                "revision": 1,
                "collected_at": "2026-07-11T10:00:00+00:00",
                "__cursor_time": "2026-07-11T09:31:00+00:00",
                "__cursor_event_key": "event-1",
                "__cursor_revision": 1,
                "__cursor_event_hash": "h1",
            },
        ]
        rows[2][bad_field] = bad_value
        monkeypatch.setattr(reader, "_sqlite_rows", lambda *args, **kwargs: (rows, None))
        reader.clear_caches()

        page = reader.get_events_page(limit=2)

        assert page["row_count"] == 0
        assert page["next_cursor"] is None
        assert page["rows"][0]["degraded"] is True
        assert "stable event cursor" in page["rows"][0]["lineage"]["reason"]

    @pytest.mark.parametrize(
        ("legacy_event_id", "legacy_revision"),
        [
            (None, 1),
            ("", 1),
            ("legacy-event-4", None),
        ],
    )
    def test_events_cursor_traverses_legacy_nullable_identity_boundary(
        self,
        tmp_path: Path,
        monkeypatch,
        legacy_event_id: str | None,
        legacy_revision: int | None,
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"legacy-h{idx}",
                        legacy_event_id if idx == 4 else f"event-{idx}",
                        legacy_revision if idx == 4 else 1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{6 - idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 6)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=4)
        assert first["next_cursor"] is not None
        from pagination import decode_cursor

        assert decode_cursor(first["next_cursor"], scope="events") == (
            "2026-07-11T09:32:00+00:00",
            legacy_event_id or "legacy-h4",
            legacy_revision if legacy_revision is not None else 0,
            "legacy-h4",
        )
        second = reader.get_events_page(limit=4, cursor=first["next_cursor"])

        event_hashes = [
            row["data"]["event_hash"]
            for row in first["rows"] + second["rows"]
        ]
        assert event_hashes == [f"legacy-h{idx}" for idx in range(1, 6)]
        assert len(event_hashes) == len(set(event_hashes))
        assert second["next_cursor"] is None

    @pytest.mark.parametrize("bad_event_hash", [None, ""])
    def test_events_page_fails_closed_when_cursor_boundary_has_no_stable_identity(
        self, tmp_path: Path, monkeypatch, bad_event_hash: str | None
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        bad_event_hash if idx == 4 else f"stable-h{idx}",
                        None if idx == 4 else f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        "2026-07-11T09:30:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        "{}",
                    )
                    for idx in range(1, 6)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        page = reader.get_events_page(limit=4)

        assert page["row_count"] == 0
        assert page["next_cursor"] is None
        assert page["rows"][0]["degraded"] is True
        assert "stable event cursor" in page["rows"][0]["lineage"]["reason"]

    def test_events_page_preserves_degraded_shape(self, tmp_path: Path, monkeypatch):
        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", tmp_path / "missing_marketdata.sqlite")
        reader.clear_caches()

        page = reader.get_events_page(limit=2)

        assert page["rows"][0]["degraded"] is True
        assert page["rows"][0]["data"] == {}
        assert page["next_cursor"] is None
        assert page["row_count"] == 0

    def test_events_subject_type_filters_before_page_limit_and_allows_missing_type(
        self, tmp_path: Path, monkeypatch
    ):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        json.dumps({"subject_type": subject_type}) if subject_type else "{}",
                    )
                    for idx, subject_type in ((1, None), (2, "stock"), (3, "bond"), (4, "bond"))
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        page = reader.get_events_page(limit=2, subject_type="stock")

        assert [row["data"]["event_hash"] for row in page["rows"]] == ["h2", "h1"]
        assert page["row_count"] == 2
        assert page["next_cursor"] is None

    def test_events_subject_type_cursor_does_not_skip_matching_rows(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, event_id, revision, provider, event_type,
                    event_time, trade_date, market, symbol, title, content,
                    url, source, source_file, collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"h{idx}",
                        f"event-{idx}",
                        1,
                        "unit",
                        "news",
                        f"2026-07-11T09:3{idx}:00+00:00",
                        "20260711",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "unit",
                        "unit",
                        "2026-07-11T10:00:00+00:00",
                        json.dumps({"subject_type": subject_type}),
                    )
                    for idx, subject_type in (
                        (1, "stock"),
                        (2, "bond"),
                        (3, "stock"),
                        (4, "bond"),
                        (5, "bond"),
                        (6, "stock"),
                    )
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        first = reader.get_events_page(limit=2, subject_type="stock")
        second = reader.get_events_page(
            limit=2,
            subject_type="stock",
            cursor=first["next_cursor"],
        )

        assert [row["data"]["event_hash"] for row in first["rows"]] == ["h6", "h3"]
        assert [row["data"]["event_hash"] for row in second["rows"]] == ["h1"]
        assert first["row_count"] == 2
        assert first["next_cursor"] is not None
        assert second["row_count"] == 1
        assert second["next_cursor"] is None

    @pytest.mark.parametrize(
        "cursor",
        ["not-a-cursor", pytest.param(None, id="cross-scope")],
    )
    def test_events_page_rejects_invalid_cursor_before_reader_degradation(self, cursor, monkeypatch):
        import reader
        from pagination import encode_cursor

        if cursor is None:
            cursor = encode_cursor("industry_taxonomy", "", ("L1", "801010.SI", "n1"))

        with pytest.raises(ValueError, match="^invalid cursor$"):
            reader.get_events_page(limit=2, cursor=cursor)

    # The migrated Tushare matrix is covered by the shared-runtime tests above.
    def test_get_events_filters_market_and_code_variants(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        collected_at = datetime.now(timezone.utc).isoformat()
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "evt-1",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "Ashare",
                        "SH600276",
                        "matched",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-2",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "US",
                        "AAPL.US",
                        "other",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-3",
                        "tushare_policy",
                        "policy",
                        "20260708",
                        "20260708",
                        "Futures",
                        "RB2609.SHF",
                        "futures matched",
                        "",
                        "",
                        "tushare_policy",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                    (
                        "evt-4",
                        "polymarket_news",
                        "policy",
                        "20260708",
                        "20260708",
                        "PredictionMarkets",
                        "pm-1",
                        "pm matched",
                        "",
                        "",
                        "polymarket_news",
                        "policy_20260708.csv",
                        collected_at,
                        "{}",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="Ashare",
            subject_code="600276.SH",
            subject_type="stock",
        )

        assert [row["data"]["event_hash"] for row in rows] == ["evt-1"]

        futures_rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="CNFutures",
        )
        pm_rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="policy",
            market="PM",
        )

        assert [row["data"]["event_hash"] for row in futures_rows] == ["evt-3"]
        assert [row["data"]["event_hash"] for row in pm_rows] == ["evt-4"]

    def test_get_events_reads_sqlite_market_events_only(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "event-1",
                    "tushare_anns_d",
                    "anns_d",
                    "20260708",
                    "20260708",
                    "Ashare",
                    "600276.SH",
                    "董事会公告",
                    "公告内容",
                    "https://example.com/ann",
                    "tushare_anns_d",
                    "anns_d_20260708.csv",
                    datetime.now(timezone.utc).isoformat(),
                    "{}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            event_type="anns_d",
            market="Ashare",
            subject_code="600276.SH",
        )

        assert len(rows) == 1
        assert rows[0]["data"]["title"] == "董事会公告"
        assert rows[0]["provenance"]["source_id"] == "tushare_anns_d"
        assert rows[0]["lineage"]["source"] == "sqlite:market_events"

    def test_get_events_honors_reader_limit(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"event-{idx}",
                        "tushare_news",
                        "news",
                        f"2026070{idx}",
                        f"2026070{idx}",
                        "Ashare",
                        "000001.SZ",
                        f"event {idx}",
                        "",
                        "",
                        "tushare_news",
                        "unit.csv",
                        datetime.now(timezone.utc).isoformat(),
                        "{}",
                    )
                    for idx in range(1, 4)
                ],
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        rows = reader.get_events(limit=2)

        assert len(rows) == 2
        assert [row["data"]["title"] for row in rows] == ["event 3", "event 2"]

    def test_get_events_pushes_symbol_filter_before_limit(self, tmp_path: Path, monkeypatch):
        import reader
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(SCHEMA_SQL)
            rows = []
            for idx in range(10):
                rows.append(
                    (
                        f"newer-{idx}",
                        "sec_edgar",
                        "sec_edgar:4",
                        f"2026-07-{20 + idx:02d}T00:00:00+00:00",
                        f"202607{20 + idx:02d}",
                        "US",
                        "CIK9999999999",
                        f"newer {idx}",
                        "",
                        "",
                        "SEC EDGAR submissions",
                        "sec_edgar_filings",
                        datetime.now(timezone.utc).isoformat(),
                        "{}",
                    )
                )
            rows.append(
                (
                    "target-old",
                    "sec_edgar",
                    "sec_edgar:4",
                    "2026-07-01T00:00:00+00:00",
                    "20260701",
                    "US",
                    "CIK0000320193",
                    "Apple Form 4",
                    "",
                    "",
                    "SEC EDGAR submissions",
                    "sec_edgar_filings",
                    datetime.now(timezone.utc).isoformat(),
                    "{}",
                )
            )
            conn.executemany(
                """
                INSERT INTO market_events (
                    event_hash, provider, event_type, event_time, trade_date,
                    market, symbol, title, content, url, source, source_file,
                    collected_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()

        result = reader.get_events(
            market="US",
            subject_code="CIK0000320193",
            event_type="sec_edgar:4",
            limit=2,
        )

        assert [row["data"]["event_hash"] for row in result] == ["target-old"]

    def test_degraded_empty_is_stale_and_unfresh(self):
        import reader

        rows = reader._degraded_empty("sqlite:market_events", "missing sqlite db")

        assert rows[0]["degraded"] is True
        assert rows[0]["data"] == {}
        assert rows[0]["freshness"]["stale"] is True
        assert rows[0]["freshness"]["score"] == 0.0

    def test_get_events_preserves_degraded_empty_when_filters_are_present(self, tmp_path: Path, monkeypatch):
        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", tmp_path / "missing_marketdata.sqlite")
        reader.clear_caches()

        rows = reader.get_events(
            start="20260708",
            end="20260708",
            market="Ashare",
            subject_code="600276.SH",
        )

        assert rows[0]["degraded"] is True
        assert rows[0]["data"] == {}
        assert "missing sqlite db" in rows[0]["lineage"]["reason"]

# ============================================================================
# canonical stock-master reference tests
# ============================================================================


# Stock-master compatibility now uses the shared runtime and is covered above.

# ============================================================================
# reference/market_calendar.py tests
# ============================================================================

class TestMarketCalendar:
    """Test market calendar functions with a SharedSignals read-model cache."""

    @pytest.fixture(autouse=True)
    def calendar_db(self, tmp_path, monkeypatch):
        """Clear cache before each test."""
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE market_bars_daily (
                market TEXT,
                symbol TEXT,
                trade_date TEXT,
                close REAL
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_bars_daily VALUES (?, ?, ?, ?)",
            [
                ("Ashare", "000001.SZ", "20260629", 10.0),
                ("Ashare", "000001.SZ", "20260630", 10.1),
                ("Ashare", "000001.SZ", "20260701", 10.2),
            ],
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("SHARED_SIGNALS_DB", str(db_path))
        from reference.market_calendar import clear_cache
        clear_cache()
        yield
        clear_cache()

    def test_is_trading_day_true_for_cached_day(self):
        """Cached A-share daily bar date should return True."""
        from reference.market_calendar import is_trading_day

        result = is_trading_day(date(2026, 6, 29))
        assert result is True

    def test_is_trading_day_false_for_weekend(self):
        """Weekend without cached rows should return False."""
        from reference.market_calendar import is_trading_day

        result = is_trading_day(date(2026, 6, 28))
        assert result is False

    def test_get_trading_days_returns_list(self):
        """Should return sorted list of date objects."""
        from reference.market_calendar import get_trading_days

        result = get_trading_days(date(2026, 6, 29), date(2026, 7, 1))
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(d, date) for d in result)

    def test_get_trading_days_swaps_reversed_range(self):
        """Start > end should be swapped."""
        from reference.market_calendar import get_trading_days

        result = get_trading_days(date(2026, 6, 30), date(2026, 6, 29))
        assert len(result) == 2

    def test_get_next_trading_day_returns_date_or_none(self):
        """Should return next trading day or None."""
        from reference.market_calendar import get_next_trading_day

        result = get_next_trading_day(date(2026, 6, 29))
        assert result == date(2026, 6, 30)

    def test_get_next_trading_day_include_today(self):
        """include_today=True on trading day should return today."""
        from reference.market_calendar import get_next_trading_day

        result = get_next_trading_day(date(2026, 6, 29), include_today=True)
        assert result == date(2026, 6, 29)

    def test_to_date_parses_string_formats(self):
        from reference.market_calendar import _to_date
        d1 = _to_date("2026-06-29")
        d2 = _to_date("2026/06/29")
        d3 = _to_date("20260629")
        assert d1 == d2 == d3 == date(2026, 6, 29)

    def test_to_date_raises_on_invalid(self):
        from reference.market_calendar import _to_date
        with pytest.raises(ValueError):
            _to_date("not a date")
        with pytest.raises(ValueError):
            _to_date("2026-13-01")

    def test_raises_on_uncached_weekday_range(self):
        """Empty cache for a weekday range should raise instead of calling providers."""
        from reference.market_calendar import (
            TradingCalendarUnavailableError, get_trading_days, clear_cache,
        )
        clear_cache()
        with pytest.raises(TradingCalendarUnavailableError):
            get_trading_days(date(2026, 7, 2), date(2026, 7, 3))


class TestPMPriceReader:
    def test_get_pm_prices_reads_market_pm_prices(self, tmp_path, monkeypatch):
        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE market_pm_prices (
                price_hash TEXT PRIMARY KEY,
                market_id TEXT,
                token_id TEXT,
                price_time TEXT,
                price REAL,
                provider TEXT,
                source_file TEXT,
                collected_at TEXT,
                raw_json TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO market_pm_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("h1", "pm-1", "yes", "2026-07-07T00:00:00Z", 0.41, "polymarket", "unit", "2026-07-07T00:00:01Z", "{}"),
                ("h2", "pm-1", "yes", "2026-07-07T00:05:00Z", 0.43, "polymarket", "unit", "2026-07-07T00:05:01Z", "{}"),
                ("h3", "pm-2", "yes", "2026-07-07T00:04:00Z", 0.52, "polymarket", "unit", "2026-07-07T00:04:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("MARKETDATA_SQLITE", str(db_path))

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_pm_prices(market_id="pm-1", limit=1)

        assert len(rows) == 1
        assert rows[0]["data"]["market_id"] == "pm-1"
        assert rows[0]["data"]["price"] == 0.43
        assert rows[0]["provenance"]["source_tier"] == "polymarket"
        assert rows[0]["lineage"]["table"] == "market_pm_prices"


class TestMarketDataReader:
    def test_get_market_data_supports_intraday_freq(self, tmp_path, monkeypatch):
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO market_bars_intraday (
                market, symbol, bar_time, trade_date, interval,
                open, high, low, close, volume, amount,
                provider, source_file, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Ashare", "000001.SZ", "2026-07-08 09:35:00", "20260708", "5min", 10, 10.2, 9.9, 10.1, 1000, 10100, "tushare_rt_min", "unit.csv", "2026-07-08T09:35:01Z", "{}"),
                ("Ashare", "000001.SZ", "2026-07-08 09:40:00", "20260708", "5min", 10.1, 10.3, 10.0, 10.2, 1100, 11220, "tushare_rt_min", "unit.csv", "2026-07-08T09:40:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_market_data("000001.SZ", "20260708", "20260708", freq="5m")

        assert [row["data"]["bar_time"] for row in rows] == [
            "2026-07-08 09:35:00",
            "2026-07-08 09:40:00",
        ]
        assert rows[0]["provenance"]["source_id"] == "tushare_rt_min"
        assert rows[0]["lineage"]["filters"]["freq"] == "5min"

    def test_get_market_data_intraday_without_dates_uses_latest_trade_date(self, tmp_path, monkeypatch):
        from storage.schema import SCHEMA_SQL

        db_path = tmp_path / "marketdata.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO market_bars_intraday (
                market, symbol, bar_time, trade_date, interval,
                open, high, low, close, volume, amount,
                provider, source_file, collected_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("Ashare", "000001.SZ", "2026-07-07 15:00:00", "20260707", "5min", 9, 9, 9, 9, 100, 900, "tushare_rt_min", "unit.csv", "2026-07-07T15:00:01Z", "{}"),
                ("Ashare", "000001.SZ", "2026-07-08 09:35:00", "20260708", "5min", 10, 10.2, 9.9, 10.1, 1000, 10100, "tushare_rt_min", "unit.csv", "2026-07-08T09:35:01Z", "{}"),
            ],
        )
        conn.commit()
        conn.close()

        import reader

        monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
        reader.clear_caches()
        rows = reader.get_market_data("000001.SZ", None, None, freq="5m")

        assert len(rows) == 1
        assert rows[0]["data"]["trade_date"] == "20260708"


# ============================================================================
# Pinned SW2021 industry reference reader tests
# ============================================================================


@pytest.fixture
def industry_db(tmp_path: Path) -> Path:
    """Create one promoted and one superseded SW2021 snapshot."""
    from storage.schema import SCHEMA_SQL

    db_path = tmp_path / "industry.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        """
        INSERT INTO market_industry_snapshots (
            snapshot_id, taxonomy_system, taxonomy_version, provider,
            started_at, completed_at, status, expected_partition_count,
            successful_partition_count, taxonomy_row_count,
            membership_row_count, unique_symbol_count, active_universe_count,
            coverage_ratio, validation_errors_json, source_run_id, promoted_at
        ) VALUES (?, 'SW', 'SW2021', 'tushare', ?, ?, ?, 31, 31, ?, ?, ?, ?, ?,
                  '[]', ?, ?)
        """,
        [
            (
                "snap-old",
                "2026-07-01T00:00:00+00:00",
                "2026-07-01T00:30:00+00:00",
                "superseded",
                1,
                1,
                1,
                1,
                1.0,
                "run-old",
                "2026-07-01T00:30:00+00:00",
            ),
            (
                "snap-a",
                "2026-07-11T00:00:00+00:00",
                "2026-07-11T00:30:00+00:00",
                "promoted",
                4,
                3,
                3,
                4,
                0.75,
                "run-a",
                "2026-07-11T00:30:00+00:00",
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO market_industry_taxonomy (
            taxonomy_node_key, snapshot_id, taxonomy_system, taxonomy_version,
            level, index_code, industry_code, industry_name,
            parent_industry_code, is_published, provider, collected_at, raw_json
        ) VALUES (?, ?, 'SW', 'SW2021', ?, ?, ?, ?, ?, '1',
                  'tushare_index_classify', ?, '{}')
        """,
        [
            (
                "old-tax-1", "snap-old", "L1", "700001.SI", "OLD-L1",
                "Old Industry", "", "2026-07-01T00:20:00+00:00",
            ),
            (
                "tax-1", "snap-a", "L1", "801010.SI", "L1-01",
                "Agriculture", "", "2026-07-11T00:20:00+00:00",
            ),
            (
                "tax-2", "snap-a", "L2", "801011.SI", "L2-01",
                "Seeds", "L1-01", "2026-07-11T00:21:00+00:00",
            ),
            (
                "tax-3", "snap-a", "L2", "801012.SI", "L2-02",
                "Farming", "L1-01", "2026-07-11T00:22:00+00:00",
            ),
            (
                "tax-4", "snap-a", "L3", "801013.SI", "L3-01",
                "Hybrid Seeds", "L2-01", "2026-07-11T00:23:00+00:00",
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO market_industry_memberships (
            membership_key, snapshot_id, market, symbol, name,
            l1_code, l1_name, l2_code, l2_name, l3_code, l3_name,
            in_date, out_date, is_current, provider, collected_at, raw_json
        ) VALUES (?, ?, 'Ashare', ?, ?, ?, ?, ?, ?, ?, ?, '20210101', '', 'Y',
                  'tushare_index_member_all', ?, '{}')
        """,
        [
            (
                "old-member-1", "snap-old", "000099.SZ", "Old Stock",
                "OLD-L1", "Old Industry", "OLD-L2", "Old L2", "OLD-L3",
                "Old L3", "2026-07-01T00:25:00+00:00",
            ),
            (
                "member-1", "snap-a", "000001.SZ", "Ping An Bank",
                "L1-01", "Agriculture", "L2-01", "Seeds", "L3-01",
                "Hybrid Seeds", "2026-07-11T00:25:00+00:00",
            ),
            (
                "member-2", "snap-a", "000002.SZ", "Vanke",
                "L1-01", "Agriculture", "L2-01", "Seeds", "L3-01",
                "Hybrid Seeds", "2026-07-11T00:26:00+00:00",
            ),
            (
                "member-3", "snap-a", "600000.SH", "SPDB",
                "L1-02", "Banks", "L2-03", "Joint-stock Banks", "L3-03",
                "Banks", "2026-07-11T00:27:00+00:00",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


def _use_industry_db(monkeypatch: pytest.MonkeyPatch, db_path: Path):
    import reader

    monkeypatch.setattr(reader, "SQLITE_PATH", db_path)
    reader.clear_caches()
    return reader


def test_get_industry_snapshot_returns_promoted_snapshot_with_exact_lineage(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)

    rows = reader.get_industry_snapshot()

    assert len(rows) == 1
    assert rows[0]["data"]["snapshot_id"] == "snap-a"
    assert rows[0]["data"]["status"] == "promoted"
    assert rows[0]["data"]["taxonomy_system"] == "SW"
    assert rows[0]["data"]["taxonomy_version"] == "SW2021"
    assert rows[0]["lineage"] == {
        "reader": "get_industry_snapshot",
        "table": "market_industry_snapshots",
        "snapshot_id": "snap-a",
        "provider": "tushare",
        "source_run_id": "run-a",
        "coverage_numerator": 3,
        "coverage_denominator": 4,
        "coverage_missing_count": 1,
    }
    assert rows[0]["provenance"]["source_id"] == "sqlite:market_industry_snapshots"
    assert rows[0]["freshness"]["age_hours"] is not None


def test_industry_taxonomy_uses_stable_pinned_keyset_and_exact_metadata(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)

    first = reader.get_industry_taxonomy(limit=2)
    second = reader.get_industry_taxonomy(limit=2, cursor=first["next_cursor"])

    assert [row["data"]["taxonomy_node_key"] for row in first["rows"]] == [
        "tax-1",
        "tax-2",
    ]
    assert [row["data"]["taxonomy_node_key"] for row in second["rows"]] == [
        "tax-3",
        "tax-4",
    ]
    assert second["next_cursor"] is None
    assert first["row_count"] == 2
    assert first["total_rows"] == 4
    expected_metadata = {
        "snapshot_id": "snap-a",
        "provider": "tushare",
        "source_run_id": "run-a",
        "coverage_numerator": 3,
        "coverage_denominator": 4,
        "coverage_missing_count": 1,
        "coverage_ratio": 0.75,
        "freshness_at": "2026-07-11T00:30:00+00:00",
    }
    assert {
        key: first["metadata"][key] for key in expected_metadata
    } == expected_metadata
    assert first["metadata"]["lineage"]["snapshot_id"] == "snap-a"
    assert first["rows"][0]["lineage"]["snapshot_id"] == "snap-a"
    assert first["rows"][0]["lineage"]["source_run_id"] == "run-a"


def test_industry_page_past_last_key_preserves_exact_filtered_total(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)
    cursor = encode_cursor(
        "industry_taxonomy", "snap-a", ("L3", "801013.SI", "tax-4")
    )

    page = reader.get_industry_taxonomy(snapshot_id="snap-a", cursor=cursor)

    assert page["row_count"] == 0
    assert page["total_rows"] == 4
    assert page["next_cursor"] is None
    assert page["rows"][0]["degraded"] is True


def test_industry_taxonomy_filters_and_can_read_pinned_superseded_snapshot(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)

    filtered = reader.get_industry_taxonomy(
        level="L2", parent_industry_code="L1-01", index_code="801012.SI"
    )
    historical = reader.get_industry_taxonomy(snapshot_id="snap-old")

    assert filtered["total_rows"] == 1
    assert filtered["rows"][0]["data"]["taxonomy_node_key"] == "tax-3"
    assert historical["metadata"]["snapshot_id"] == "snap-old"
    assert historical["rows"][0]["data"]["taxonomy_node_key"] == "old-tax-1"


def test_taxonomy_cursor_is_endpoint_and_snapshot_bound(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)
    page = reader.get_industry_taxonomy(snapshot_id="snap-a", limit=1)
    assert page["next_cursor"]

    with pytest.raises(ValueError, match="cursor snapshot mismatch"):
        reader.get_industry_taxonomy(
            snapshot_id="snap-old", cursor=page["next_cursor"]
        )
    with pytest.raises(ValueError, match="cursor snapshot mismatch"):
        reader.get_industry_taxonomy(
            snapshot_id="snap-does-not-exist", cursor=page["next_cursor"]
        )
    with pytest.raises(ValueError, match="^invalid cursor$"):
        reader.get_industry_memberships(cursor=page["next_cursor"])


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param(
            encode_cursor("industry_taxonomy", "snap-a", ("L1",)),
            id="short-key",
        ),
        pytest.param(
            encode_cursor("industry_taxonomy", "snap-a", ("L1", 1, "tax-1")),
            id="non-string-key",
        ),
    ],
)
def test_taxonomy_rejects_invalid_cursor_sort_key_shape(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch, cursor: str
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)

    with pytest.raises(ValueError, match="^invalid cursor$"):
        reader.get_industry_taxonomy(snapshot_id="snap-a", cursor=cursor)


@pytest.mark.parametrize("hidden_status", ["collecting", "rejected"])
def test_explicit_unpromoted_industry_snapshot_is_not_visible(
    industry_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    hidden_status: str,
) -> None:
    conn = sqlite3.connect(industry_db)
    conn.execute(
        "UPDATE market_industry_snapshots SET status = ? WHERE snapshot_id = 'snap-old'",
        (hidden_status,),
    )
    conn.commit()
    conn.close()
    reader = _use_industry_db(monkeypatch, industry_db)

    page = reader.get_industry_memberships(snapshot_id="snap-old")

    assert page["row_count"] == 0
    assert page["total_rows"] == 0
    assert page["rows"][0]["degraded"] is True
    assert page["rows"][0]["data"] == {}


def test_industry_memberships_filters_paginates_and_reports_exact_total(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)

    first = reader.get_industry_memberships(l1_code="L1-01", limit=1)
    second = reader.get_industry_memberships(
        l1_code="L1-01", limit=1, cursor=first["next_cursor"]
    )
    by_symbol = reader.get_industry_memberships(
        symbol="600000.SH", l2_code="L2-03", l3_code="L3-03"
    )

    assert first["total_rows"] == 2
    assert first["rows"][0]["data"]["symbol"] == "000001.SZ"
    assert second["rows"][0]["data"]["symbol"] == "000002.SZ"
    assert second["next_cursor"] is None
    assert by_symbol["total_rows"] == 1
    assert by_symbol["rows"][0]["data"]["membership_key"] == "member-3"
    assert by_symbol["metadata"]["coverage_missing_count"] == 1


def test_industry_reader_clamps_page_size_to_1000(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = sqlite3.connect(industry_db)
    conn.executemany(
        """
        INSERT INTO market_industry_taxonomy (
            taxonomy_node_key, snapshot_id, taxonomy_system, taxonomy_version,
            level, index_code, industry_code, industry_name,
            parent_industry_code, is_published, provider, collected_at, raw_json
        ) VALUES (?, 'snap-a', 'SW', 'SW2021', 'L3', ?, ?, ?, 'L2-X', '1',
                  'tushare_index_classify', '2026-07-11T00:28:00+00:00', '{}')
        """,
        [
            (f"bulk-{i:04d}", f"9{i:05d}.SI", f"B-{i:04d}", f"Bulk {i}")
            for i in range(997)
        ],
    )
    conn.commit()
    conn.close()
    reader = _use_industry_db(monkeypatch, industry_db)

    page = reader.get_industry_taxonomy(limit=50_000)

    assert page["row_count"] == 1000
    assert page["total_rows"] == 1001
    assert page["next_cursor"] is not None


def test_industry_caches_follow_sqlite_mtime_after_snapshot_promotion(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _use_industry_db(monkeypatch, industry_db)
    assert reader.get_industry_snapshot()[0]["data"]["snapshot_id"] == "snap-a"
    assert reader.get_industry_taxonomy()["metadata"]["snapshot_id"] == "snap-a"

    conn = sqlite3.connect(industry_db)
    conn.execute(
        "UPDATE market_industry_snapshots SET status = 'superseded' "
        "WHERE snapshot_id = 'snap-a'"
    )
    conn.execute(
        """
        INSERT INTO market_industry_snapshots (
            snapshot_id, taxonomy_system, taxonomy_version, provider,
            started_at, completed_at, status, expected_partition_count,
            successful_partition_count, taxonomy_row_count,
            membership_row_count, unique_symbol_count, active_universe_count,
            coverage_ratio, validation_errors_json, source_run_id, promoted_at
        ) VALUES (
            'snap-new', 'SW', 'SW2021', 'tushare',
            '2026-07-12T00:00:00+00:00', '2026-07-12T00:30:00+00:00',
            'promoted', 31, 31, 1, 0, 0, 4, 0.0, '[]', 'run-new',
            '2026-07-12T00:30:00+00:00'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO market_industry_taxonomy (
            taxonomy_node_key, snapshot_id, taxonomy_system, taxonomy_version,
            level, index_code, industry_code, industry_name,
            parent_industry_code, is_published, provider, collected_at, raw_json
        ) VALUES (
            'new-tax-1', 'snap-new', 'SW', 'SW2021', 'L1', '900001.SI',
            'NEW-L1', 'New Industry', '', '1', 'tushare_index_classify',
            '2026-07-12T00:20:00+00:00', '{}'
        )
        """
    )
    conn.commit()
    conn.close()
    stat = industry_db.stat()
    future_ns = max(stat.st_mtime_ns + 1_000_000_000, time.time_ns() + 1_000_000_000)
    os.utime(industry_db, ns=(stat.st_atime_ns, future_ns))

    snapshot = reader.get_industry_snapshot()
    page = reader.get_industry_taxonomy()

    assert snapshot[0]["data"]["snapshot_id"] == "snap-new"
    assert page["metadata"]["snapshot_id"] == "snap-new"
    assert page["rows"][0]["data"]["taxonomy_node_key"] == "new-tax-1"


def test_corrupt_snapshot_metadata_degrades_instead_of_looking_like_bad_request(
    industry_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = sqlite3.connect(industry_db)
    conn.execute(
        "UPDATE market_industry_snapshots SET coverage_ratio = 'invalid' "
        "WHERE snapshot_id = 'snap-a'"
    )
    conn.commit()
    conn.close()
    reader = _use_industry_db(monkeypatch, industry_db)

    page = reader.get_industry_taxonomy()

    assert page["row_count"] == 0
    assert page["rows"][0]["degraded"] is True
    assert "reader failed" in page["rows"][0]["lineage"]["reason"]


@pytest.mark.parametrize("mode", ["missing_table", "no_promoted_snapshot"])
def test_industry_readers_fail_closed_without_tables_or_promoted_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    db_path = tmp_path / f"{mode}.sqlite"
    conn = sqlite3.connect(db_path)
    if mode == "no_promoted_snapshot":
        from storage.schema import SCHEMA_SQL

        conn.executescript(SCHEMA_SQL)
    else:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()
    reader = _use_industry_db(monkeypatch, db_path)

    snapshot = reader.get_industry_snapshot()
    taxonomy = reader.get_industry_taxonomy()
    memberships = reader.get_industry_memberships()

    assert snapshot[0]["degraded"] is True
    assert snapshot[0]["data"] == {}
    for page in (taxonomy, memberships):
        assert page["rows"][0]["degraded"] is True
        assert page["rows"][0]["data"] == {}
        assert page["next_cursor"] is None
        assert page["row_count"] == 0
        assert page["total_rows"] == 0
        assert page["metadata"]["snapshot_id"] is None
