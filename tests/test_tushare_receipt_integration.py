from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from storage.ingest_receipts import IngestContext, make_receipt_id
from storage.read_model_store import ingest_rows_with_receipts
from storage.schema import SCHEMA_SQL


CONFIG_HASH = "a" * 64


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _context(
    attempt_id: str = "018f47de-0000-7000-8000-000000000008",
    *,
    dataset_id: str = "cn.equity.daily",
    provider_api: str = "daily",
) -> IngestContext:
    return IngestContext(
        attempt_id=attempt_id,
        dataset_id=dataset_id,
        provider="tushare",
        provider_api=provider_api,
        request_window={"trade_date": "20260715"},
        config_hash=CONFIG_HASH,
        adapter_version="tushare-direct-sqlite.v1",
        started_at="2026-07-15T04:00:00+00:00",
        data_through="2026-07-15",
    )


def _daily_rows(count: int) -> list[dict[str, object]]:
    return [
        {
            "ts_code": f"{index:06d}.SZ",
            "trade_date": "20260715",
            "open": 10 + index,
            "high": 11 + index,
            "low": 9 + index,
            "close": 10.5 + index,
            "vol": 1_000 + index,
            "amount": 10_500 + index,
        }
        for index in range(1, count + 1)
    ]


def _receipt_notes(db_path: Path) -> list[dict[str, object]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT notes FROM market_ingest_runs WHERE status = 'success' "
            "ORDER BY run_id"
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(row[0]) for row in rows]


def _reserve_receipt_id(
    db_path: Path,
    *,
    context: IngestContext,
    target_table: str,
    transaction_index: int,
) -> str:
    receipt_id = make_receipt_id(context, target_table, transaction_index)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO market_ingest_runs "
            "(run_id, started_at, finished_at, status, source, rows_read, "
            "rows_written, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                receipt_id,
                context.started_at,
                context.started_at,
                "failed",
                context.dataset_id,
                0,
                0,
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return receipt_id


def test_data_and_success_receipt_commit_in_one_transaction(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    result = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        _daily_rows(2),
        context=_context(),
        source_name="atomic_daily_test",
    )

    assert result.status == "success"
    assert result.counts.returned == result.counts.validated == 2
    assert result.counts.committed == 2
    assert result.counts.inserted is None
    assert result.counts.updated is None
    assert result.counts.unchanged is None
    assert result.counts.count_semantics == "generic_upsert_outcomes_unavailable"
    assert len(result.receipt_ids) == 1

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0] == 2
        stored = conn.execute(
            "SELECT status, rows_read, rows_written, notes FROM market_ingest_runs"
        ).fetchone()
    finally:
        conn.close()

    assert stored is not None
    status, rows_read, rows_written, notes_json = stored
    assert (status, rows_read, rows_written) == ("success", 2, 2)
    notes = json.loads(notes_json)
    assert notes["target_table"] == "market_bars_daily"
    assert notes["transaction_index"] == 0
    assert notes["counts"]["committed"] == 2


def test_receipt_insert_failure_rolls_back_data_transaction(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    context = _context()
    _reserve_receipt_id(
        db_path,
        context=context,
        target_table="market_bars_daily",
        transaction_index=0,
    )

    with pytest.raises(sqlite3.IntegrityError):
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(2),
            context=context,
            source_name="receipt_failure_test",
        )

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_transaction_row_limit_creates_one_receipt_per_real_chunk(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    result = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        _daily_rows(5),
        context=_context(),
        source_name="chunked_daily_test",
        max_transaction_rows=2,
    )

    assert result.counts.returned == result.counts.validated == 5
    assert result.counts.committed == 5
    assert len(result.receipt_ids) == 3
    notes = sorted(_receipt_notes(db_path), key=lambda item: item["transaction_index"])
    assert [item["transaction_index"] for item in notes] == [0, 1, 2]
    assert [item["counts"]["returned"] for item in notes] == [2, 2, 1]
    assert [item["counts"]["committed"] for item in notes] == [2, 2, 1]


def test_later_chunk_failure_preserves_prior_chunk_without_false_success(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    context = _context()
    reserved = _reserve_receipt_id(
        db_path,
        context=context,
        target_table="market_bars_daily",
        transaction_index=1,
    )

    with pytest.raises(sqlite3.IntegrityError):
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(3),
            context=context,
            source_name="later_chunk_failure_test",
            max_transaction_rows=2,
        )

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0] == 2
        success_rows = conn.execute(
            "SELECT run_id, notes FROM market_ingest_runs WHERE status = 'success'"
        ).fetchall()
        assert len(success_rows) == 1
        assert json.loads(success_rows[0][1])["transaction_index"] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM market_ingest_runs WHERE run_id = ?",
                (reserved,),
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_event_replay_reports_exact_unchanged_outcome(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    event = {
        "id": "provider-42",
        "datetime": "2026-07-15 09:00:00",
        "title": "事实新闻",
        "content": "same payload",
    }

    first = ingest_rows_with_receipts(
        db_path,
        "market_events",
        [event],
        context=_context(
            "018f47de-0000-7000-8000-000000000009",
            dataset_id="cn.event.news",
            provider_api="news",
        ),
    )
    replay = ingest_rows_with_receipts(
        db_path,
        "market_events",
        [event],
        context=_context(
            "018f47de-0000-7000-8000-000000000010",
            dataset_id="cn.event.news",
            provider_api="news",
        ),
    )

    assert (first.counts.inserted, first.counts.updated, first.counts.unchanged) == (
        1,
        0,
        0,
    )
    assert (
        replay.counts.inserted,
        replay.counts.updated,
        replay.counts.unchanged,
    ) == (0, 0, 1)
    assert replay.counts.committed == 1
    assert replay.counts.count_semantics == "event_revision_outcomes_exact"
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 2
        )
    finally:
        conn.close()


def test_generic_upsert_never_fabricates_insert_update_or_unchanged_counts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    row = _daily_rows(1)

    first = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        row,
        context=_context("018f47de-0000-7000-8000-000000000011"),
    )
    replay = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        row,
        context=_context("018f47de-0000-7000-8000-000000000012"),
    )

    for result in (first, replay):
        assert result.counts.inserted is None
        assert result.counts.updated is None
        assert result.counts.unchanged is None
        assert result.counts.count_semantics == "generic_upsert_outcomes_unavailable"
