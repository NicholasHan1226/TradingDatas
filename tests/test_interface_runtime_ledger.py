from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import storage.ingest_receipts as receipt_module
import storage.receipt_projection as projection_module
import tools.interface_runtime_ledger as ledger_module
from dataset_registry import DatasetDefinition, DatasetRegistry, load_dataset_registry
from storage.ingest_receipts import IngestContext, IngestCounts, insert_ingest_receipt
from storage.receipt_projection import (
    RuntimeProjectionError,
    load_interface_runtime_report,
    rebuild_interface_runtime_cache,
)
from storage.schema import SCHEMA_SQL
from tools.interface_runtime_ledger import (
    expected_tushare_api_names,
    record_tushare_stats,
)


NOW = datetime(2026, 7, 15, 1, tzinfo=timezone.utc)
CONFIG_HASH = "a" * 64
PAYLOAD_FINGERPRINT = "b" * 64


@pytest.fixture(autouse=True)
def _maintenance_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = tmp_path / "read_model_maintenance.lock"
    lock_path.touch()
    monkeypatch.setenv("SHAREDSIGNALS_MAINTENANCE_LOCK_FILE", str(lock_path))


def _create_writer_lock(path: Path) -> None:
    (path.parent / f".{path.name}.read_model_store.lock").touch()


def _dataset(*, active: bool = True) -> DatasetDefinition:
    base = load_dataset_registry().resolve("tushare.daily")
    binding = replace(
        base.provider_bindings[0],
        entitlement_state="active",
        activation_state="active" if active else "paused",
    )
    return replace(base, provider_bindings=(binding,), freshness_sla_seconds=3_600)


def _registry(*, active: bool = True) -> DatasetRegistry:
    return DatasetRegistry((_dataset(active=active),))


def _file_db(path: Path, *, wal: bool = False) -> sqlite3.Connection:
    _create_writer_lock(path)
    conn = sqlite3.connect(path)
    if wal:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _insert_success(
    monkeypatch: pytest.MonkeyPatch,
    conn: sqlite3.Connection,
    *,
    attempt_id: str = "attempt-success",
) -> str:
    monkeypatch.setattr(
        receipt_module,
        "_utc_now",
        lambda: "2026-07-15T00:01:00+00:00",
    )
    receipt_id = insert_ingest_receipt(
        conn,
        context=IngestContext(
            attempt_id=attempt_id,
            dataset_id="cn.equity.daily",
            provider="tushare",
            provider_api="daily",
            request_window={"trade_date": "20260715"},
            config_hash=CONFIG_HASH,
            adapter_version="tushare-direct-sqlite.v1",
            started_at="2026-07-15T00:00:00+00:00",
            data_through="2026-07-15T08:00:00+08:00",
        ),
        target_table="market_bars_daily",
        transaction_index=0,
        status="success",
        counts=IngestCounts(
            returned=1,
            validated=1,
            inserted=1,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1,
            count_semantics="exact_row_outcomes",
        ),
        errors=(),
        payload_fingerprint=PAYLOAD_FINGERPRINT,
    )
    conn.commit()
    return receipt_id


def test_runtime_ledger_expected_names_come_from_registry_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_names = frozenset({"registry_only", "rt_fut_min"})
    monkeypatch.setattr(
        ledger_module,
        "TUSHARE_ALLOWED_API_NAMES",
        registry_names,
        raising=False,
    )

    assert expected_tushare_api_names() == set(registry_names)


def test_runtime_ledger_legacy_path_argument_does_not_override_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_names = frozenset({"registry_only", "rt_fut_min"})
    monkeypatch.setattr(
        ledger_module,
        "TUSHARE_ALLOWED_API_NAMES",
        registry_names,
        raising=False,
    )
    legacy_path = tmp_path / "legacy-capability-plan.yaml"
    legacy_path.write_text(
        "modules:\n  - apis:\n      - api_name: legacy_only\n",
        encoding="utf-8",
    )

    assert expected_tushare_api_names(path=legacy_path) == set(registry_names)


def test_cache_rebuild_projects_registry_and_derives_summary_from_datasets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        receipt_id = _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    output_path = tmp_path / "interface_runtime.json"
    output_path.write_text(
        '{"status":"red","summary":{"failed":999}}\n',
        encoding="utf-8",
    )

    result = rebuild_interface_runtime_cache(
        db_path,
        _registry(),
        output_path,
        now=NOW,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert result is None
    assert report["authority"] == "sqlite_ingest_receipts"
    assert report["status"] == "green"
    assert report["summary"] == {
        "degraded": 0,
        "empty": 0,
        "expected": 1,
        "failed": 0,
        "observed": 1,
        "paused": 0,
        "stale": 0,
        "success": 1,
        "unobserved": 0,
    }
    assert report["datasets"]["cn.equity.daily"]["receipt_id"] == receipt_id
    assert report["interfaces"]["daily"]["dataset_id"] == "cn.equity.daily"
    assert report["interfaces"]["daily"]["state"] == "success"


def test_deleted_cache_rebuilds_identically_from_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    output_path = tmp_path / "interface_runtime.json"

    rebuild_interface_runtime_cache(db_path, _registry(), output_path, now=NOW)
    first = json.loads(output_path.read_text(encoding="utf-8"))
    output_path.unlink()
    rebuild_interface_runtime_cache(db_path, _registry(), output_path, now=NOW)
    second = json.loads(output_path.read_text(encoding="utf-8"))

    assert second == first


def test_record_tushare_stats_ignores_supplied_stats_and_crafted_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    output_path = tmp_path / "interface_runtime.json"
    output_path.write_text(
        '{"status":"red","interfaces":{"daily":{"state":"failed"}}}\n',
        encoding="utf-8",
    )

    report = record_tushare_stats(
        {
            "daily": {
                "rows": 0,
                "calls": 1,
                "failure_count": 1,
                "sqlite_rows": 0,
                "sqlite_status": "failed",
                "sqlite_errors": ["crafted failure"],
            }
        },
        tier="crafted-tier",
        started_at="1999-01-01T00:00:00+00:00",
        finished_at="1999-01-01T00:01:00+00:00",
        expected_api_names={"crafted-only"},
        output_path=output_path,
        db_path=db_path,
        registry=_registry(),
        now=NOW,
    )

    assert report["status"] == "green"
    assert report["summary"]["success"] == 1
    assert report["interfaces"]["daily"]["state"] == "success"
    assert "crafted-only" not in report["interfaces"]


def test_read_only_projection_sees_committed_wal_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    writer = _file_db(db_path, wal=True)
    try:
        receipt_id = _insert_success(monkeypatch, writer)
        report = load_interface_runtime_report(db_path, _registry(), now=NOW)
    finally:
        writer.close()

    assert report["datasets"]["cn.equity.daily"]["receipt_id"] == receipt_id
    assert report["status"] == "green"


def test_read_only_projection_rejects_wal_without_existing_shm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    writer = _file_db(db_path, wal=True)
    try:
        _insert_success(monkeypatch, writer)
        (tmp_path / f"{db_path.name}-shm").unlink()

        with pytest.raises(RuntimeProjectionError):
            load_interface_runtime_report(db_path, _registry(), now=NOW)
    finally:
        writer.close()


def test_read_only_projection_rejects_new_main_with_old_wal_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    old_writer = _file_db(db_path, wal=True)
    try:
        _insert_success(monkeypatch, old_writer)
        replacement = tmp_path / "replacement.sqlite"
        replacement_writer = _file_db(replacement, wal=True)
        replacement_writer.close()
        replacement.replace(db_path)

        with pytest.raises(RuntimeProjectionError):
            load_interface_runtime_report(db_path, _registry(), now=NOW)
    finally:
        old_writer.close()


def test_read_only_projection_rejects_symlinked_parent_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    db_path = real_parent / "marketdata.sqlite"
    conn = _file_db(db_path)
    conn.close()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    connect_calls = 0

    def unexpected_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("sqlite3.connect must not follow a parent symlink")

    monkeypatch.setattr(projection_module.sqlite3, "connect", unexpected_connect)

    with pytest.raises(RuntimeProjectionError):
        load_interface_runtime_report(
            linked_parent / db_path.name,
            _registry(),
            now=NOW,
        )

    assert connect_calls == 0


def test_read_only_projection_rejects_parent_identity_drift_during_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_parent = tmp_path / "trusted-parent"
    redirect_parent = tmp_path / "redirect-parent"
    stashed_parent = tmp_path / "stashed-parent"
    trusted_parent.mkdir()
    redirect_parent.mkdir()
    db_path = trusted_parent / "marketdata.sqlite"
    replacement = redirect_parent / db_path.name
    _file_db(db_path).close()
    _file_db(replacement).close()
    real_connect = sqlite3.connect

    def swapping_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        trusted_parent.rename(stashed_parent)
        trusted_parent.symlink_to(redirect_parent, target_is_directory=True)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(projection_module.sqlite3, "connect", swapping_connect)

    with pytest.raises(RuntimeProjectionError):
        load_interface_runtime_report(db_path, _registry(), now=NOW)


def test_read_only_projection_rejects_database_inode_drift_during_connect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    original_backup = tmp_path / "original.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    _file_db(db_path).close()
    _file_db(replacement).close()
    real_connect = sqlite3.connect

    def swapping_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        db_path.rename(original_backup)
        replacement.rename(db_path)
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(projection_module.sqlite3, "connect", swapping_connect)

    with pytest.raises(RuntimeProjectionError):
        load_interface_runtime_report(db_path, _registry(), now=NOW)


def test_read_only_projection_rejects_temporary_connect_target_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    alternate = tmp_path / "alternate.sqlite"
    _file_db(alternate).close()
    stashed = tmp_path / "stashed.sqlite"
    real_connect = sqlite3.connect
    swapped = False

    def swapping_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        nonlocal swapped
        if swapped:
            return real_connect(*args, **kwargs)  # type: ignore[arg-type]
        swapped = True
        db_path.replace(stashed)
        alternate.replace(db_path)
        opened = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        opened.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
        db_path.replace(alternate)
        stashed.replace(db_path)
        return opened

    monkeypatch.setattr(projection_module.sqlite3, "connect", swapping_connect)

    with pytest.raises(RuntimeProjectionError):
        load_interface_runtime_report(db_path, _registry(), now=NOW)


def test_registry_change_reprojects_without_consulting_existing_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    output_path = tmp_path / "interface_runtime.json"
    rebuild_interface_runtime_cache(db_path, _registry(), output_path, now=NOW)

    active = load_interface_runtime_report(db_path, _registry(), now=NOW)
    paused = load_interface_runtime_report(
        db_path,
        _registry(active=False),
        now=NOW,
    )

    assert active["datasets"]["cn.equity.daily"]["state"] == "success"
    assert paused["datasets"]["cn.equity.daily"]["state"] == "paused"
    assert paused["status"] == "yellow"


@pytest.mark.parametrize("db_kind", ["missing", "damaged", "missing_table"])
def test_missing_or_damaged_db_fails_closed_without_creation_or_json_fallback(
    tmp_path: Path,
    db_kind: str,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    if db_kind == "damaged":
        db_path.write_bytes(b"not a SQLite database")
    elif db_kind == "missing_table":
        sqlite3.connect(db_path).close()
    output_path = tmp_path / "interface_runtime.json"
    crafted = b'{"status":"green","summary":{"success":999}}\n'
    output_path.write_bytes(crafted)

    with pytest.raises(RuntimeProjectionError):
        record_tushare_stats(
            {},
            tier="ignored",
            started_at="1999-01-01T00:00:00+00:00",
            finished_at="1999-01-01T00:01:00+00:00",
            output_path=output_path,
            db_path=db_path,
            registry=_registry(),
            now=NOW,
        )

    if db_kind == "missing":
        assert not db_path.exists()
    assert output_path.read_bytes() == crafted


def test_missing_writer_lock_fails_closed_without_creating_artifacts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _file_db(db_path).close()
    writer_lock = tmp_path / f".{db_path.name}.read_model_store.lock"
    writer_lock.unlink()
    output_path = tmp_path / "interface_runtime.json"
    previous = b'{"diagnostic":"previous"}\n'
    output_path.write_bytes(previous)

    with pytest.raises(RuntimeProjectionError):
        rebuild_interface_runtime_cache(
            db_path,
            _registry(),
            output_path,
            now=NOW,
        )

    assert not writer_lock.exists()
    assert output_path.read_bytes() == previous
    assert not list(tmp_path.glob("interface_runtime.json.*.tmp"))


def test_atomic_cache_replace_failure_preserves_previous_cache_and_db_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    conn = _file_db(db_path)
    try:
        _insert_success(monkeypatch, conn)
    finally:
        conn.close()
    output_path = tmp_path / "interface_runtime.json"
    previous = b'{"diagnostic":"previous"}\n'
    output_path.write_bytes(previous)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(projection_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        rebuild_interface_runtime_cache(db_path, _registry(), output_path, now=NOW)

    assert output_path.read_bytes() == previous
    assert not list(tmp_path.glob("interface_runtime.json.*.tmp"))
    authoritative = load_interface_runtime_report(db_path, _registry(), now=NOW)
    assert authoritative["status"] == "green"
