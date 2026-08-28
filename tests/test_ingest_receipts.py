from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import storage.ingest_receipts as receipt_module
from storage.ingest_receipts import (
    RECEIPT_SCHEMA_VERSION,
    IngestContext,
    IngestCounts,
    IngestResult,
    ProviderRequestIdentity,
    insert_ingest_receipt,
    make_receipt_id,
    write_terminal_receipt,
)
from storage.schema import SCHEMA_SQL
from storage.schema_contract import require_clean_sqlite_authority_schema
from storage.sqlite_authority_lock import (
    SqliteAuthorityLockError,
    sqlite_authority_lock_path,
)


CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64
FINISHED_AT = "2026-07-15T04:05:06.123456Z"


def _context(
    *,
    attempt_id: str = "018f47de-0000-7000-8000-000000000001",
    request_window: dict[str, str] | None = None,
    request_identity: ProviderRequestIdentity | None = None,
) -> IngestContext:
    return IngestContext(
        attempt_id=attempt_id,
        dataset_id="cn.equity.daily",
        provider="tushare",
        provider_api="daily",
        request_window=request_window
        if request_window is not None
        else {"end_date": "20260715", "start_date": "20260715"},
        config_hash=CONFIG_HASH,
        adapter_version="tushare-direct-sqlite.v1",
        started_at="2026-07-15T04:00:00+00:00",
        data_through="2026-07-15",
        request_identity=request_identity or ProviderRequestIdentity.trivial(),
    )


def _counts(**overrides: object) -> IngestCounts:
    values: dict[str, object] = {
        "returned": 3,
        "validated": 2,
        "inserted": 1,
        "updated": 0,
        "unchanged": 1,
        "rejected": 1,
        "committed": 2,
        "count_semantics": "exact_row_outcomes",
    }
    values.update(overrides)
    return IngestCounts(**values)  # type: ignore[arg-type]


def _zero_counts(
    *,
    optional_outcomes: int | None = 0,
) -> IngestCounts:
    return IngestCounts(
        returned=0,
        validated=0,
        inserted=optional_outcomes,
        updated=optional_outcomes,
        unchanged=optional_outcomes,
        rejected=0,
        committed=0,
        count_semantics="terminal_no_data_transaction",
    )


def _memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _file_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _receipt_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0]
    finally:
        conn.close()


def test_terminal_receipt_uses_authority_lock_and_rolls_back_on_sentinel_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "terminal.sqlite"
    _file_db(db_path)
    original = receipt_module.insert_ingest_receipt_with_evidence

    def replace_sentinel_after_insert(*args: object, **kwargs: object):
        evidence = original(*args, **kwargs)
        lock_path = sqlite_authority_lock_path(db_path)
        lock_path.unlink()
        lock_path.touch(mode=0o600)
        return evidence

    monkeypatch.setattr(
        receipt_module,
        "insert_ingest_receipt_with_evidence",
        replace_sentinel_after_insert,
    )

    with pytest.raises(SqliteAuthorityLockError, match="binding changed"):
        write_terminal_receipt(
            db_path,
            context=_context(attempt_id="terminal-sentinel-swap"),
            status="failed",
            errors=("storage_failed",),
        )

    assert _receipt_count(db_path) == 0


def test_terminal_receipt_rejects_silent_ignore_trigger_without_success(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "terminal.sqlite"
    _file_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """CREATE TRIGGER ignore_terminal_receipt
               BEFORE INSERT ON market_ingest_runs
               BEGIN SELECT RAISE(IGNORE); END;"""
        )

    with pytest.raises(RuntimeError, match="unsupported.*triggers"):
        write_terminal_receipt(
            db_path,
            context=_context(attempt_id="terminal-ignore-trigger"),
            status="failed",
            errors=("storage_failed",),
        )

    assert _receipt_count(db_path) == 0


def test_receipt_value_objects_are_frozen_and_context_copies_request_window() -> None:
    request_window = {"trade_date": "20260715"}
    context = _context(request_window=request_window)
    counts = _counts()
    result = IngestResult(
        status="success",
        counts=counts,
        receipt_ids=("receipt-id",),
        errors=(),
    )

    request_window["trade_date"] = "19990101"
    assert dict(context.request_window) == {"trade_date": "20260715"}
    with pytest.raises(TypeError):
        context.request_window["trade_date"] = "20000101"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        context.attempt_id = "replacement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        counts.returned = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


def test_receipt_id_binds_full_request_attempt_table_and_transaction_index() -> None:
    context = _context()
    next_page = _context(
        request_identity=ProviderRequestIdentity(
            request_variant={},
            fanout_parameter=None,
            fanout_values=(),
            page_offset=None,
            page_index=1,
        )
    )

    receipt_id = make_receipt_id(context, "market_bars_daily", 0)

    assert receipt_id == make_receipt_id(context, "market_bars_daily", 0)
    assert receipt_id != make_receipt_id(next_page, "market_bars_daily", 0)
    assert receipt_id != make_receipt_id(context, "market_bars_daily", 1)
    assert receipt_id != make_receipt_id(context, "market_events", 0)
    assert receipt_id != make_receipt_id(context, None, 0)


def test_same_day_reruns_with_different_attempt_ids_have_unique_receipt_ids() -> None:
    first = _context(attempt_id="018f47de-0000-7000-8000-000000000001")
    rerun = _context(attempt_id="018f47de-0000-7000-8000-000000000002")

    assert first.started_at == rerun.started_at
    assert make_receipt_id(first, "market_bars_daily", 0) != make_receipt_id(
        rerun,
        "market_bars_daily",
        0,
    )


@pytest.mark.parametrize("transaction_index", [-1, True])
def test_receipt_id_rejects_invalid_transaction_index(
    transaction_index: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="transaction_index"):
        make_receipt_id(_context(), "market_bars_daily", transaction_index)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("returned", -1),
        ("validated", -1),
        ("inserted", -1),
        ("updated", -1),
        ("unchanged", -1),
        ("rejected", -1),
        ("committed", -1),
        ("returned", True),
    ],
)
def test_counts_reject_negative_or_non_integer_values(
    field: str, value: object
) -> None:
    with pytest.raises((TypeError, ValueError), match=field):
        _counts(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"returned": 4},
        {"committed": 3},
        {"inserted": 0},
        {"inserted": None, "updated": 0, "unchanged": None},
    ],
)
def test_counts_enforce_row_conservation(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="count"):
        _counts(**overrides)


def test_counts_allow_explicitly_unknown_outcome_breakdown() -> None:
    counts = _counts(
        inserted=None,
        updated=None,
        unchanged=None,
        count_semantics="generic_upsert_outcomes_unavailable",
    )

    assert counts.committed == counts.validated == 2


def test_counts_require_a_nonempty_semantics_label() -> None:
    with pytest.raises(ValueError, match="count_semantics"):
        _counts(count_semantics=" ")


def test_insert_serializes_canonical_versioned_notes_without_owning_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: FINISHED_AT)
    conn = _memory_db()
    context = _context(
        request_window={"start_date": "20260714", "end_date": "20260715"}
    )
    counts = _counts()
    try:
        conn.execute("BEGIN IMMEDIATE")
        receipt_id = insert_ingest_receipt(
            conn,
            context=context,
            target_table="market_bars_daily",
            transaction_index=0,
            status="success",
            counts=counts,
            errors=(),
            payload_fingerprint=PAYLOAD_FINGERPRINT,
        )
        row = conn.execute(
            "SELECT run_id, started_at, finished_at, status, source, "
            "rows_read, rows_written, notes FROM market_ingest_runs"
        ).fetchone()

        expected_payload = {
            "adapter_version": context.adapter_version,
            "attempt_id": context.attempt_id,
            "config_hash": context.config_hash,
            "counts": {
                "committed": 2,
                "count_semantics": "exact_row_outcomes",
                "inserted": 1,
                "rejected": 1,
                "returned": 3,
                "unchanged": 1,
                "updated": 0,
                "validated": 2,
            },
            "data_through": context.data_through,
            "dataset_id": context.dataset_id,
            "errors": [],
            "finished_at": FINISHED_AT,
            "payload_fingerprint": PAYLOAD_FINGERPRINT,
            "provider": context.provider,
            "provider_api": context.provider_api,
            "receipt_id": receipt_id,
            "request_window": {
                "end_date": "20260715",
                "start_date": "20260714",
            },
            "request_identity": context.request_identity.canonical_payload(),
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "started_at": context.started_at,
            "status": "success",
            "target_table": "market_bars_daily",
            "transaction_index": 0,
        }
        expected_notes = json.dumps(
            expected_payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        assert row == (
            receipt_id,
            context.started_at,
            FINISHED_AT,
            "success",
            context.dataset_id,
            3,
            2,
            expected_notes,
        )
        assert (
            json.dumps(
                json.loads(row[7]),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            == row[7]
        )
        assert conn.in_transaction is True

        conn.rollback()
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    "request_window",
    [
        {"api_token": "sk-secret-value"},
        {"source_file": "/tmp/provider-payload.json"},
        {"detail": 'Traceback (most recent call last): File "/tmp/job.py"'},
    ],
)
def test_context_rejects_secret_path_or_stacktrace_material(
    request_window: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="request_window"):
        _context(request_window=request_window)


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "accessToken",
        "refreshToken",
        "clientSecret",
        "authorizationHeader",
        "dbPath",
    ],
)
def test_context_rejects_camel_case_sensitive_request_window_keys(
    sensitive_key: str,
) -> None:
    with pytest.raises(ValueError, match="request_window"):
        _context(request_window={sensitive_key: "redacted"})


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "Bearer eyJhbGciOiJIUzI1NiJ9.signature",
        "relative/path/to/provider.json",
        "file:provider.json",
        "/absolute/path/to/provider.json",
        "file:///tmp/provider.json",
        "provider failed at /var/log/sharedsignals/provider.log",
        r"C:\Users\Nicholas\provider.json",
        "provider failed at C:/Temp/provider.json",
        r"..\secrets\token.txt",
        "Traceback (most recent call last): collector failed",
        'File "collector.py", line 42, in fetch',
        "provider.py:42 in fetch",
        "at com.example.Provider.fetch(Provider.java:42)",
        "java.lang.IllegalStateException at Provider.java:42",
        "Caused by: java.lang.IllegalStateException: provider failed",
        'Exception in thread "main" java.lang.IllegalStateException',
    ],
)
def test_context_rejects_secret_path_and_stacktrace_value_shapes(
    unsafe_value: str,
) -> None:
    with pytest.raises(ValueError, match="request_window"):
        _context(request_window={"detail": unsafe_value})


def test_context_rejects_windows_drive_relative_path() -> None:
    with pytest.raises(ValueError, match="request_window"):
        _context(request_window={"detail": "C:provider_payload.json"})


def test_context_rejects_embedded_file_uri() -> None:
    with pytest.raises(ValueError, match="request_window"):
        _context(request_window={"detail": "provider payload at file:payload.json"})


def test_context_rejects_sensitive_material_in_identity_fields() -> None:
    with pytest.raises(ValueError, match="attempt_id"):
        _context(attempt_id="Bearer eyJhbGciOiJIUzI1NiJ9.signature")


def test_insert_accepts_only_structured_error_codes() -> None:
    conn = _memory_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="error"):
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table=None,
                transaction_index=0,
                status="failed",
                counts=_counts(
                    returned=0,
                    validated=0,
                    inserted=0,
                    updated=0,
                    unchanged=0,
                    rejected=0,
                    committed=0,
                    count_semantics="terminal_no_data_transaction",
                ),
                errors=("provider_error: token=sk-secret /tmp/job.py Traceback",),
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.rollback()
        conn.close()


def test_insert_accepts_transport_error_as_a_terminal_receipt() -> None:
    conn = _memory_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        receipt_id = insert_ingest_receipt(
            conn,
            context=_context(),
            target_table=None,
            transaction_index=0,
            status="failed",
            counts=_zero_counts(),
            errors=("transport_error",),
            payload_fingerprint=PAYLOAD_FINGERPRINT,
        )
        notes = conn.execute(
            "SELECT notes FROM market_ingest_runs WHERE run_id = ?", (receipt_id,)
        ).fetchone()[0]
        assert json.loads(notes)["errors"] == ["transport_error"]
    finally:
        conn.rollback()
        conn.close()


def test_unknown_error_code_rejection_does_not_echo_sensitive_input() -> None:
    conn = _memory_db()
    unsafe_error = "Bearer eyJhbGciOiJIUzI1NiJ9.signature /tmp/provider.py"
    try:
        with pytest.raises(ValueError) as exc_info:
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table=None,
                transaction_index=0,
                status="failed",
                counts=_zero_counts(),
                errors=(unsafe_error,),
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
        assert unsafe_error not in str(exc_info.value)
        assert "Bearer" not in str(exc_info.value)
        assert "/tmp/provider.py" not in str(exc_info.value)
    finally:
        conn.close()


def test_duplicate_receipt_uses_plain_insert_and_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: FINISHED_AT)
    conn = _memory_db()
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    kwargs = {
        "context": _context(),
        "target_table": "market_bars_daily",
        "transaction_index": 0,
        "status": "success",
        "counts": _counts(),
        "errors": (),
        "payload_fingerprint": PAYLOAD_FINGERPRINT,
    }
    try:
        conn.execute("BEGIN IMMEDIATE")
        insert_ingest_receipt(conn, **kwargs)
        with pytest.raises(sqlite3.IntegrityError):
            insert_ingest_receipt(conn, **kwargs)

        receipt_inserts = [
            statement
            for statement in statements
            if "INSERT" in statement.upper()
            and "MARKET_INGEST_RUNS" in statement.upper()
        ]
        assert receipt_inserts
        assert all(
            "INSERT OR" not in statement.upper() for statement in receipt_inserts
        )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize(
    ("status", "errors"),
    [
        ("success", ("provider_error",)),
        ("empty", ("provider_error",)),
        ("failed", ()),
        ("stale", ()),
    ],
)
def test_insert_rejects_inconsistent_status_and_errors(
    status: str,
    errors: tuple[str, ...],
) -> None:
    conn = _memory_db()
    try:
        with pytest.raises(ValueError, match="status|error"):
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table="market_bars_daily" if status == "success" else None,
                transaction_index=0,
                status=status,
                counts=_counts(),
                errors=errors,
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
    finally:
        conn.close()


def test_success_receipt_requires_a_target_table() -> None:
    conn = _memory_db()
    try:
        with pytest.raises(ValueError, match="target_table"):
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table=None,
                transaction_index=0,
                status="success",
                counts=_counts(),
                errors=(),
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("target_table", "counts"),
    [
        ("market_bars_daily", _zero_counts()),
        (None, _counts()),
        (
            None,
            IngestCounts(
                returned=1,
                validated=1,
                inserted=None,
                updated=None,
                unchanged=None,
                rejected=0,
                committed=0,
                count_semantics="storage_failure_before_commit",
            ),
        ),
    ],
)
def test_failed_receipt_rejects_target_table_or_nonzero_counts(
    target_table: str | None,
    counts: IngestCounts,
) -> None:
    conn = _memory_db()
    try:
        with pytest.raises(ValueError, match="failed|target_table|zero"):
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table=target_table,
                transaction_index=0,
                status="failed",
                counts=counts,
                errors=("storage_failed",),
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_failed_receipt_with_zero_counts_writes_zero_rows_and_no_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: FINISHED_AT)
    conn = _memory_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        receipt_id = insert_ingest_receipt(
            conn,
            context=_context(),
            target_table=None,
            transaction_index=0,
            status="failed",
            counts=_zero_counts(),
            errors=("storage_failed",),
            payload_fingerprint=PAYLOAD_FINGERPRINT,
        )
        row = conn.execute(
            "SELECT rows_written, notes FROM market_ingest_runs WHERE run_id = ?",
            (receipt_id,),
        ).fetchone()
        assert row[0] == 0
        notes = json.loads(row[1])
        assert notes["target_table"] is None
        assert notes["counts"]["committed"] == 0
        assert notes["counts"]["inserted"] == 0
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize(
    ("status", "errors"),
    [("empty", ()), ("failed", ("storage_failed",))],
)
def test_terminal_insert_requires_explicit_integer_zero_outcomes(
    status: str,
    errors: tuple[str, ...],
) -> None:
    conn = _memory_db()
    try:
        with pytest.raises(ValueError, match="zero"):
            insert_ingest_receipt(
                conn,
                context=_context(),
                target_table=None,
                transaction_index=0,
                status=status,
                counts=_zero_counts(optional_outcomes=None),
                errors=errors,
                payload_fingerprint=PAYLOAD_FINGERPRINT,
            )
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    "receipt_ids",
    [
        "receipt-id",
        (receipt_id for receipt_id in ("receipt-id",)),
    ],
)
def test_ingest_result_requires_a_real_non_string_receipt_id_sequence(
    receipt_ids: object,
) -> None:
    with pytest.raises(TypeError, match="receipt_ids"):
        IngestResult(
            status="success",
            counts=_counts(),
            receipt_ids=receipt_ids,  # type: ignore[arg-type]
            errors=(),
        )


def test_ingest_result_success_requires_receipt_id_and_success_counts() -> None:
    with pytest.raises(ValueError, match="success|receipt"):
        IngestResult(
            status="success",
            counts=_counts(),
            receipt_ids=(),
            errors=(),
        )
    with pytest.raises(ValueError, match="success|count"):
        IngestResult(
            status="success",
            counts=_zero_counts(),
            receipt_ids=("receipt-id",),
            errors=(),
        )


@pytest.mark.parametrize(
    ("status", "errors"),
    [("empty", ()), ("failed", ("provider_error",))],
)
def test_ingest_result_terminal_states_require_zero_counts(
    status: str,
    errors: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="zero|count"):
        IngestResult(
            status=status,
            counts=_counts(),
            receipt_ids=("receipt-id",),
            errors=errors,
        )


@pytest.mark.parametrize(
    ("status", "errors"),
    [("empty", ()), ("failed", ("provider_error",))],
)
def test_terminal_result_requires_explicit_integer_zero_outcomes(
    status: str,
    errors: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="zero"):
        IngestResult(
            status=status,
            counts=_zero_counts(optional_outcomes=None),
            receipt_ids=("receipt-id",),
            errors=errors,
        )


@pytest.mark.parametrize(
    ("status", "errors"),
    [("empty", ()), ("failed", ("provider_error",))],
)
def test_terminal_receipt_commits_an_independent_receipt_only_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    errors: tuple[str, ...],
) -> None:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: FINISHED_AT)
    db_path = tmp_path / f"{status}.sqlite"
    _file_db(db_path)
    context = _context(attempt_id=f"terminal-{status}-attempt")

    result = write_terminal_receipt(
        db_path,
        context=context,
        status=status,
        errors=errors,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT run_id, status, rows_read, rows_written, notes "
            "FROM market_ingest_runs"
        ).fetchone()
    finally:
        conn.close()
    assert result == IngestResult(
        status=status,
        counts=IngestCounts(
            returned=0,
            validated=0,
            inserted=0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=0,
            count_semantics="terminal_no_data_transaction",
        ),
        receipt_ids=(row[0],),
        errors=errors,
    )
    assert row[:4] == (result.receipt_ids[0], status, 0, 0)
    notes = json.loads(row[4])
    assert notes["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert notes["target_table"] is None
    assert notes["transaction_index"] == 0
    assert notes["errors"] == list(errors)


def test_terminal_receipt_rejects_duplicate_without_replacing_first_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(receipt_module, "_utc_now", lambda: FINISHED_AT)
    db_path = tmp_path / "duplicate.sqlite"
    _file_db(db_path)
    context = _context(attempt_id="terminal-duplicate-attempt")

    first = write_terminal_receipt(db_path, context=context, status="empty", errors=())
    with pytest.raises(sqlite3.IntegrityError):
        write_terminal_receipt(db_path, context=context, status="empty", errors=())

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT run_id, status FROM market_ingest_runs").fetchall()
    finally:
        conn.close()
    assert rows == [(first.receipt_ids[0], "empty")]


@pytest.mark.parametrize(
    ("status", "errors"),
    [("success", ()), ("empty", ("provider_error",)), ("failed", ())],
)
def test_terminal_writer_accepts_only_honest_terminal_states(
    tmp_path: Path,
    status: str,
    errors: tuple[str, ...],
) -> None:
    db_path = tmp_path / "terminal-invalid.sqlite"
    _file_db(db_path)

    with pytest.raises(ValueError, match="terminal|error"):
        write_terminal_receipt(
            db_path,
            context=_context(),
            status=status,
            errors=errors,
        )

    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_terminal_writer_rejects_missing_path_without_creating_file(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing.sqlite"

    with pytest.raises(FileNotFoundError, match="exist"):
        write_terminal_receipt(
            db_path,
            context=_context(),
            status="empty",
            errors=(),
        )

    assert not db_path.exists()


def test_terminal_writer_accepts_direct_nested_parent_chain(tmp_path: Path) -> None:
    db_path = tmp_path / "direct" / "nested" / "terminal.sqlite"
    db_path.parent.mkdir(parents=True)
    _file_db(db_path)

    result = write_terminal_receipt(
        db_path,
        context=_context(attempt_id="direct-parent-chain-attempt"),
        status="empty",
        errors=(),
    )

    assert result.status == "empty"
    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 1
        )
    finally:
        conn.close()


def test_terminal_writer_rejects_symlinked_parent_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    target = real_parent / "terminal.sqlite"
    _file_db(target)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    connect_calls = 0

    def unexpected_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("sqlite3.connect must not run after unsafe preflight")

    with monkeypatch.context() as patch:
        patch.setattr(receipt_module.sqlite3, "connect", unexpected_connect)
        with pytest.raises(ValueError, match="parent|symbolic|directory"):
            write_terminal_receipt(
                linked_parent / target.name,
                context=_context(),
                status="empty",
                errors=(),
            )

    assert connect_calls == 0
    conn = sqlite3.connect(target)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_terminal_writer_rejects_non_directory_parent_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_directory = tmp_path / "not-a-directory"
    non_directory.write_text("ordinary file", encoding="utf-8")
    connect_calls = 0

    def unexpected_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("sqlite3.connect must not run after unsafe preflight")

    with monkeypatch.context() as patch:
        patch.setattr(receipt_module.sqlite3, "connect", unexpected_connect)
        with pytest.raises(ValueError, match="parent|directory"):
            write_terminal_receipt(
                non_directory / "terminal.sqlite",
                context=_context(),
                status="empty",
                errors=(),
            )

    assert connect_calls == 0


def test_terminal_writer_rolls_back_if_database_inode_changes_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "terminal.sqlite"
    original_backup = tmp_path / "original.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _file_db(db_path)
    _file_db(replacement)
    real_connect = sqlite3.connect

    def swapping_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        db_path.rename(original_backup)
        replacement.rename(db_path)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(receipt_module.sqlite3, "connect", swapping_connect)
        with pytest.raises(RuntimeError, match="binding|changed"):
            write_terminal_receipt(
                db_path,
                context=_context(attempt_id="database-swap-attempt"),
                status="empty",
                errors=(),
            )

    assert _receipt_count(original_backup) == 0
    assert _receipt_count(db_path) == 0


def test_terminal_writer_rolls_back_if_parent_becomes_symlink_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_parent = tmp_path / "trusted-parent"
    redirect_parent = tmp_path / "redirect-parent"
    stashed_parent = tmp_path / "stashed-parent"
    trusted_parent.mkdir()
    redirect_parent.mkdir()
    db_path = trusted_parent / "terminal.sqlite"
    replacement = redirect_parent / db_path.name
    _file_db(db_path)
    _file_db(replacement)
    real_connect = sqlite3.connect

    def swapping_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        trusted_parent.rename(stashed_parent)
        trusted_parent.symlink_to(redirect_parent, target_is_directory=True)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patch:
        patch.setattr(receipt_module.sqlite3, "connect", swapping_connect)
        with pytest.raises(RuntimeError, match="binding|changed"):
            write_terminal_receipt(
                db_path,
                context=_context(attempt_id="parent-swap-attempt"),
                status="failed",
                errors=("storage_failed",),
            )

    assert _receipt_count(stashed_parent / db_path.name) == 0
    assert _receipt_count(replacement) == 0


@pytest.mark.parametrize("kind", ["directory", "empty_file", "text_file"])
def test_terminal_writer_rejects_non_sqlite_regular_path_shapes(
    tmp_path: Path,
    kind: str,
) -> None:
    db_path = tmp_path / "invalid.sqlite"
    if kind == "directory":
        db_path.mkdir()
    elif kind == "empty_file":
        db_path.touch()
    else:
        db_path.write_text("not a SQLite database", encoding="utf-8")
    before = db_path.read_bytes() if db_path.is_file() else None

    with pytest.raises(ValueError, match="regular SQLite"):
        write_terminal_receipt(
            db_path,
            context=_context(),
            status="empty",
            errors=(),
        )

    if before is not None:
        assert db_path.read_bytes() == before


def test_terminal_writer_rejects_symbolic_link_without_writing_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.sqlite"
    _file_db(target)
    link = tmp_path / "linked.sqlite"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic|regular SQLite"):
        write_terminal_receipt(
            link,
            context=_context(),
            status="empty",
            errors=(),
        )

    conn = sqlite3.connect(target)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM market_ingest_runs").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_insert_ingest_receipt_lazily_builds_source_index(tmp_path: Path) -> None:
    db_path = tmp_path / "lazy-index.sqlite"
    _file_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP INDEX market_ingest_runs_source_idx")
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")
        insert_ingest_receipt(
            conn,
            context=_context(),
            target_table="market_bars_daily",
            transaction_index=0,
            status="success",
            counts=_counts(),
            errors=(),
            payload_fingerprint=PAYLOAD_FINGERPRINT,
        )
        conn.commit()

        index_names = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA main.index_list('market_ingest_runs')"
            ).fetchall()
        }
        assert "market_ingest_runs_source_idx" in index_names
        require_clean_sqlite_authority_schema(conn)
    finally:
        conn.close()


def test_ingest_result_error_message_defaults_to_none_and_round_trips() -> None:
    default = IngestResult(
        status="failed",
        counts=_zero_counts(),
        receipt_ids=(),
        errors=("provider_error",),
    )
    assert default.error_message is None
    carried = IngestResult(
        status="failed",
        counts=_zero_counts(),
        receipt_ids=(),
        errors=("provider_error",),
        error_message="firecrawl request failed with HTTP status 500",
    )
    assert carried.error_message == "firecrawl request failed with HTTP status 500"


def test_ingest_result_rejects_unsafe_error_message_shapes() -> None:
    base = {
        "status": "failed",
        "counts": _zero_counts(),
        "receipt_ids": (),
        "errors": ("provider_error",),
    }
    with pytest.raises(TypeError, match="error_message"):
        IngestResult(**base, error_message=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="length"):
        IngestResult(**base, error_message="x" * 401)
    with pytest.raises(ValueError, match="one line"):
        IngestResult(**base, error_message="line one\nline two")
    with pytest.raises(ValueError, match="error_message"):
        IngestResult(**base, error_message="Bearer production-token")
