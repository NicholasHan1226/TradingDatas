from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

import storage.read_model_store as read_model_store
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


def _db_counts(path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(path)
    try:
        data_rows = conn.execute(
            "SELECT COUNT(*) FROM market_bars_daily"
        ).fetchone()[0]
        success_receipts = conn.execute(
            "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
        ).fetchone()[0]
        return data_rows, success_receipts
    finally:
        conn.close()


def _swap_parent(
    authority_parent: Path,
    retired_parent: Path,
    db_name: str,
) -> Path:
    authority_parent.replace(retired_parent)
    authority_parent.mkdir()
    replacement = authority_parent / db_name
    _create_db(replacement)
    return replacement


def _patch_rw_connection(
    monkeypatch: pytest.MonkeyPatch,
    connection_type: type[sqlite3.Connection],
) -> None:
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if str(database).endswith("?mode=rw"):
            kwargs["factory"] = connection_type
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(read_model_store.sqlite3, "connect", connect)


def _tamper_success_receipt(
    conn: sqlite3.Connection,
    *,
    receipt_id: str,
    tamper_kind: str,
) -> None:
    notes_row = conn.execute(
        "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
        (receipt_id,),
    ).fetchone()
    assert notes_row is not None
    raw_notes = notes_row[0]
    if tamper_kind == "duplicate_key":
        tampered_notes = (
            '{"schema_version":"unrecognized.receipt.v999",' + raw_notes[1:]
        )
        conn.execute(
            "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
            (tampered_notes, receipt_id),
        )
        return

    notes = json.loads(raw_notes)
    if tamper_kind == "boolean_count":
        notes["counts"]["returned"] = True
    elif tamper_kind == "paired_finished_at":
        replacement = "2099-12-31T23:59:59+00:00"
        notes["finished_at"] = replacement
        conn.execute(
            "UPDATE market_ingest_runs SET finished_at = ? WHERE run_id = ?",
            (replacement, receipt_id),
        )
    elif tamper_kind == "unknown_schema":
        notes["schema_version"] = "unrecognized.receipt.v999"
    else:
        raise AssertionError(f"unsupported tamper_kind: {tamper_kind}")
    conn.execute(
        "UPDATE market_ingest_runs SET notes = ? WHERE run_id = ?",
        (
            json.dumps(notes, separators=(",", ":"), sort_keys=True),
            receipt_id,
        ),
    )


def _assert_postcommit_authority_failure(
    error: RuntimeError,
    *,
    reason_code: str,
    receipt_id: str,
) -> None:
    assert getattr(error, "error_code", None) == "storage_authority_failed"
    assert getattr(error, "phase", None) == "post_commit"
    assert getattr(error, "reason_code", None) == reason_code
    assert getattr(error, "receipt_id", None) == receipt_id
    assert getattr(error, "commit_succeeded", None) is True


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


def test_data_and_success_receipt_commit_in_one_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    canonical_path = db_path.absolute()
    real_lock = read_model_store._read_model_lock
    real_connect = sqlite3.connect
    lock_paths: list[Path] = []
    connect_calls: list[tuple[object, dict[str, object]]] = []

    @contextmanager
    def capture_lock(path: Path):
        lock_paths.append(path)
        with real_lock(path):
            yield

    def capture_connect(database, *args, **kwargs):
        connect_calls.append((database, dict(kwargs)))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(read_model_store, "_read_model_lock", capture_lock)
    monkeypatch.setattr(read_model_store.sqlite3, "connect", capture_connect)

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
    assert lock_paths == [canonical_path]
    assert connect_calls == [
        (
            f"{canonical_path.as_uri()}?mode=rw",
            {"uri": True, "timeout": 30},
        ),
        (
            f"{canonical_path.as_uri()}?mode=ro",
            {"uri": True, "timeout": 30},
        ),
    ]

    conn = real_connect(db_path)
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
    context = _context()

    result = ingest_rows_with_receipts(
        db_path,
        "market_bars_daily",
        _daily_rows(5),
        context=context,
        source_name="chunked_daily_test",
        max_transaction_rows=2,
    )

    assert result.counts.returned == result.counts.validated == 5
    assert result.counts.committed == 5
    assert result.receipt_ids == tuple(
        make_receipt_id(context, "market_bars_daily", transaction_index)
        for transaction_index in range(3)
    )
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


def test_atomic_ingest_rejects_sqlite_symlink_alias_without_writing_target(
    tmp_path: Path,
) -> None:
    authority_path = tmp_path / "authority.sqlite"
    alias_path = tmp_path / "alias.sqlite"
    _create_db(authority_path)
    alias_path.symlink_to(authority_path.name)

    with pytest.raises(ValueError, match="symbolic link"):
        ingest_rows_with_receipts(
            alias_path,
            "market_bars_daily",
            _daily_rows(1),
            context=_context("018f47de-0000-7000-8000-000000000013"),
        )

    conn = sqlite3.connect(authority_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_atomic_ingest_rejects_inode_drift_before_rw_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_path = tmp_path / "authority.sqlite"
    replacement_path = tmp_path / "replacement.sqlite"
    retired_path = tmp_path / "retired.sqlite"
    _create_db(authority_path)
    _create_db(replacement_path)
    original_check = read_model_store._require_unchanged_sqlite_binding
    swapped = False

    def swap_before_first_binding_check(binding) -> None:
        nonlocal swapped
        if not swapped:
            authority_path.replace(retired_path)
            replacement_path.replace(authority_path)
            swapped = True
        original_check(binding)

    monkeypatch.setattr(
        read_model_store,
        "_require_unchanged_sqlite_binding",
        swap_before_first_binding_check,
    )

    with pytest.raises(RuntimeError, match="binding changed"):
        ingest_rows_with_receipts(
            authority_path,
            "market_bars_daily",
            _daily_rows(1),
            context=_context("018f47de-0000-7000-8000-000000000014"),
        )

    for path in (authority_path, retired_path):
        conn = sqlite3.connect(path)
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0]
                == 0
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0]
                == 0
            )
        finally:
            conn.close()


def test_atomic_ingest_rolls_back_parent_swap_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_parent = tmp_path / "authority"
    retired_parent = tmp_path / "retired"
    authority_parent.mkdir()
    authority_path = authority_parent / "marketdata.sqlite"
    _create_db(authority_path)
    original_insert = read_model_store.insert_ingest_receipt

    def insert_then_swap_parent(*args, **kwargs):
        receipt_id = original_insert(*args, **kwargs)
        authority_parent.replace(retired_parent)
        authority_parent.mkdir()
        _create_db(authority_path)
        return receipt_id

    monkeypatch.setattr(
        read_model_store,
        "insert_ingest_receipt",
        insert_then_swap_parent,
    )

    with pytest.raises(RuntimeError, match="binding changed"):
        ingest_rows_with_receipts(
            authority_path,
            "market_bars_daily",
            _daily_rows(1),
            context=_context("018f47de-0000-7000-8000-000000000015"),
        )

    for path in (authority_path, retired_parent / "marketdata.sqlite"):
        conn = sqlite3.connect(path)
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM market_bars_daily").fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM market_ingest_runs WHERE status = 'success'"
                ).fetchone()[0]
                == 0
            )
        finally:
            conn.close()


def test_atomic_ingest_rejects_reviewer_final_check_race_without_false_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_parent = tmp_path / "authority"
    retired_parent = tmp_path / "retired"
    authority_parent.mkdir()
    authority_path = authority_parent / "marketdata.sqlite"
    _create_db(authority_path)
    context = _context("018f47de-0000-7000-8000-000000000016")
    receipt_id = make_receipt_id(context, "market_bars_daily", 0)
    original_check = read_model_store._require_unchanged_sqlite_binding
    calls = 0

    def swap_after_final_precommit_check(binding) -> None:
        nonlocal calls
        calls += 1
        original_check(binding)
        if calls == 5:
            _swap_parent(authority_parent, retired_parent, authority_path.name)

    monkeypatch.setattr(
        read_model_store,
        "_require_unchanged_sqlite_binding",
        swap_after_final_precommit_check,
    )

    with pytest.raises(RuntimeError, match="storage-authority") as captured:
        ingest_rows_with_receipts(
            authority_path,
            "market_bars_daily",
            _daily_rows(1),
            context=context,
        )

    assert calls == 5
    _assert_postcommit_authority_failure(
        captured.value,
        reason_code="binding_changed",
        receipt_id=receipt_id,
    )
    assert _db_counts(authority_path) == (0, 0)
    assert _db_counts(retired_parent / authority_path.name) == (1, 1)


def test_atomic_ingest_rejects_parent_swap_after_commit_without_false_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_parent = tmp_path / "authority"
    retired_parent = tmp_path / "retired"
    authority_parent.mkdir()
    authority_path = authority_parent / "marketdata.sqlite"
    _create_db(authority_path)
    context = _context("018f47de-0000-7000-8000-000000000017")
    receipt_id = make_receipt_id(context, "market_bars_daily", 0)
    swapped = False

    class SwapAfterCommitConnection(sqlite3.Connection):
        def commit(self) -> None:
            nonlocal swapped
            super().commit()
            if not swapped:
                swapped = True
                _swap_parent(
                    authority_parent,
                    retired_parent,
                    authority_path.name,
                )

    _patch_rw_connection(monkeypatch, SwapAfterCommitConnection)

    with pytest.raises(RuntimeError, match="storage-authority") as captured:
        ingest_rows_with_receipts(
            authority_path,
            "market_bars_daily",
            _daily_rows(1),
            context=context,
        )

    _assert_postcommit_authority_failure(
        captured.value,
        reason_code="binding_changed",
        receipt_id=receipt_id,
    )
    assert _db_counts(authority_path) == (0, 0)
    assert _db_counts(retired_parent / authority_path.name) == (1, 1)


@pytest.mark.parametrize("transaction_index", [0, 1, 2])
def test_atomic_ingest_requires_canonical_receipt_readback_for_every_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transaction_index: int,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    context = _context(f"chunk-readback-missing-{transaction_index}")
    receipt_id = make_receipt_id(context, "market_bars_daily", transaction_index)
    commit_index = 0
    injected = False

    class DeleteReceiptAfterCommitConnection(sqlite3.Connection):
        def commit(self) -> None:
            nonlocal commit_index, injected
            super().commit()
            if commit_index == transaction_index and not injected:
                injected = True
                self.execute(
                    "DELETE FROM market_ingest_runs WHERE run_id = ?",
                    (receipt_id,),
                )
                super().commit()
            commit_index += 1

    _patch_rw_connection(monkeypatch, DeleteReceiptAfterCommitConnection)

    with pytest.raises(RuntimeError, match="storage-authority") as captured:
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(5),
            context=context,
            max_transaction_rows=2,
        )

    _assert_postcommit_authority_failure(
        captured.value,
        reason_code="receipt_missing",
        receipt_id=receipt_id,
    )
    expected_data_rows = min((transaction_index + 1) * 2, 5)
    assert _db_counts(db_path) == (expected_data_rows, transaction_index)


@pytest.mark.parametrize(
    "tamper_kind",
    ["unknown_schema", "boolean_count", "paired_finished_at", "duplicate_key"],
)
def test_atomic_ingest_rejects_tampered_canonical_receipt_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    context = _context(f"tampered-canonical-receipt-{tamper_kind}")
    receipt_id = make_receipt_id(context, "market_bars_daily", 0)
    injected = False

    class TamperReceiptAfterCommitConnection(sqlite3.Connection):
        def commit(self) -> None:
            nonlocal injected
            super().commit()
            if not injected:
                injected = True
                _tamper_success_receipt(
                    self,
                    receipt_id=receipt_id,
                    tamper_kind=tamper_kind,
                )
                super().commit()

    _patch_rw_connection(monkeypatch, TamperReceiptAfterCommitConnection)

    with pytest.raises(RuntimeError, match="storage-authority") as captured:
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(1),
            context=context,
        )

    _assert_postcommit_authority_failure(
        captured.value,
        reason_code="receipt_evidence_mismatch",
        receipt_id=receipt_id,
    )
    assert _db_counts(db_path) == (1, 1)


def test_atomic_ingest_structures_unexpected_ro_open_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    context = _context("unexpected-ro-open-exception")
    receipt_id = make_receipt_id(context, "market_bars_daily", 0)

    def fail_open(_binding):
        raise TypeError("unexpected ro-open failure")

    monkeypatch.setattr(
        read_model_store,
        "_open_canonical_receipt_reader",
        fail_open,
    )

    with pytest.raises(RuntimeError, match="storage-authority") as captured:
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(1),
            context=context,
        )

    _assert_postcommit_authority_failure(
        captured.value,
        reason_code="readback_failed",
        receipt_id=receipt_id,
    )
    assert _db_counts(db_path) == (1, 1)


def test_atomic_ingest_preserves_primary_commit_error_over_rollback_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    class CommitAndRollbackFailConnection(sqlite3.Connection):
        def commit(self) -> None:
            raise sqlite3.OperationalError("primary commit failure")

        def rollback(self) -> None:
            raise RuntimeError("secondary rollback failure")

    _patch_rw_connection(monkeypatch, CommitAndRollbackFailConnection)

    with pytest.raises(sqlite3.OperationalError, match="primary commit failure"):
        ingest_rows_with_receipts(
            db_path,
            "market_bars_daily",
            _daily_rows(1),
            context=_context("018f47de-0000-7000-8000-000000000019"),
        )

    assert _db_counts(db_path) == (0, 0)
