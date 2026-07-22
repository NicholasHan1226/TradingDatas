from __future__ import annotations

import sqlite3
import stat
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

import storage.ingest_receipts as receipt_module
import storage.sqlite_authority_lock as lock_module
from dataset_registry import load_dataset_registry
from storage.ingest_receipts import IngestContext, ProviderRequestIdentity
from storage.provider_dataset_rows import (
    ingest_provider_native_rows,
    validate_provider_dataset_store,
)
from storage.receipt_projection import load_dataset_runtime_projection
from storage.schema import SCHEMA_SQL
from storage.sqlite_authority_lock import (
    SqliteAuthorityLockError,
    sqlite_authority_lock,
    sqlite_authority_lock_path,
)


def _fresh_authority(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def test_writer_creates_the_one_lock_reused_by_readers(tmp_path: Path) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    lock_path = sqlite_authority_lock_path(db_path)

    with sqlite_authority_lock(
        db_path,
        mode="exclusive",
        create=True,
        timeout=0.0,
    ):
        assert lock_path.is_file()
        assert not bool(lock_path.stat().st_mode & stat.S_IWOTH)

    with sqlite_authority_lock(
        db_path,
        mode="shared",
        create=False,
        timeout=0.0,
    ):
        validate_provider_dataset_store(db_path)


def test_reader_never_creates_a_missing_coordination_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    lock_path = sqlite_authority_lock_path(db_path)

    with pytest.raises(SqliteAuthorityLockError, match="unavailable"):
        with sqlite_authority_lock(
            db_path,
            mode="shared",
            create=False,
            timeout=0.0,
        ):
            pass

    assert not lock_path.exists()


def test_lock_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    target = tmp_path / "unrelated.txt"
    target.write_text("unchanged", encoding="utf-8")
    sqlite_authority_lock_path(db_path).symlink_to(target)

    with pytest.raises(SqliteAuthorityLockError, match="unsafe"):
        with sqlite_authority_lock(
            db_path,
            mode="exclusive",
            create=True,
            timeout=0.0,
        ):
            pass

    assert target.read_text(encoding="utf-8") == "unchanged"


def test_replaced_sentinel_cannot_create_a_second_live_lock_domain(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    lock_path = sqlite_authority_lock_path(db_path)
    second_entered = threading.Event()

    def acquire_shared() -> None:
        with sqlite_authority_lock(
            db_path,
            mode="shared",
            create=False,
            timeout=2.0,
        ):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(SqliteAuthorityLockError, match="binding changed"):
            with sqlite_authority_lock(
                db_path,
                mode="exclusive",
                create=True,
                timeout=0.0,
            ):
                lock_path.unlink()
                lock_path.touch(mode=0o600)
                future = executor.submit(acquire_shared)
                assert second_entered.wait(timeout=0.2) is False
        future.result(timeout=3.0)

    assert second_entered.is_set()


def test_body_error_still_checks_replaced_sentinel_and_fails_closed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    lock_path = sqlite_authority_lock_path(db_path)

    class InjectedBodyError(RuntimeError):
        pass

    with pytest.raises(SqliteAuthorityLockError, match="binding changed") as caught:
        with sqlite_authority_lock(
            db_path,
            mode="exclusive",
            create=True,
            timeout=0.0,
        ):
            lock_path.unlink()
            lock_path.touch(mode=0o600)
            raise InjectedBodyError("primary body failure")

    assert isinstance(caught.value.__cause__, InjectedBodyError)


def test_base_exception_during_acquisition_releases_the_directory_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    original = lock_module._acquire_flock
    call_count = 0

    class InjectedBaseError(BaseException):
        pass

    def fail_second_flock(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise InjectedBaseError("sentinel acquisition interrupted")
        original(*args, **kwargs)

    monkeypatch.setattr(lock_module, "_acquire_flock", fail_second_flock)
    with pytest.raises(InjectedBaseError):
        with sqlite_authority_lock(
            db_path,
            mode="exclusive",
            create=True,
            timeout=0.0,
        ):
            pytest.fail("interrupted acquisition must not enter the body")

    monkeypatch.setattr(lock_module, "_acquire_flock", original)
    with sqlite_authority_lock(
        db_path,
        mode="exclusive",
        create=True,
        timeout=0.0,
    ):
        pass


def test_provider_store_rejects_any_third_business_table(tmp_path: Path) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE market_events (event_id TEXT)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="unsupported tables"):
        validate_provider_dataset_store(db_path)


def test_generic_write_and_projection_share_one_clean_slate_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "tradingdatas.sqlite"
    _fresh_authority(db_path)
    registry = load_dataset_registry()
    dataset = registry.resolve("tushare.daily")
    binding = dataset.provider_bindings[0]
    request_identity = ProviderRequestIdentity(
        request_variant=dict(binding.request_variants[0]),
        fanout_parameter=None,
        fanout_values=(),
        page_offset=None,
        page_index=0,
    )
    context = IngestContext(
        attempt_id="clean-slate-daily-call",
        dataset_id=dataset.dataset_id,
        provider=binding.provider,
        provider_api=binding.api_name,
        request_window={"trade_date": "20260720"},
        config_hash="a" * 64,
        adapter_version=binding.adapter_version,
        started_at="2026-07-20T00:00:00+00:00",
        data_through="20260720",
        request_identity=request_identity,
    )
    monkeypatch.setattr(
        receipt_module,
        "_utc_now",
        lambda: "2026-07-20T00:01:00+00:00",
    )

    result = ingest_provider_native_rows(
        db_path,
        dataset=dataset,
        binding=binding,
        rows=(
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260720",
                "open": 10.0,
                "close": 10.5,
            },
        ),
        context=context,
    )
    projection = load_dataset_runtime_projection(
        db_path,
        dataset,
        registry=registry,
        now=datetime(2026, 7, 20, 0, 5, tzinfo=timezone.utc),
    )
    conn = sqlite3.connect(db_path)
    try:
        notes = conn.execute(
            "SELECT notes FROM market_ingest_runs WHERE run_id = ?",
            (result.receipt_ids[0],),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result.status == "success"
    assert projection.state == "success"
    assert projection.receipt_id == result.receipt_ids[0]
    assert json.loads(notes)["request_identity"] == (
        request_identity.canonical_payload()
    )


def test_active_storage_modules_do_not_import_retired_read_model_store() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "storage/provider_dataset_rows.py",
        "storage/receipt_projection.py",
        "storage/sqlite_authority_lock.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "read_model_store" not in source
