from __future__ import annotations

import fcntl
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


pytestmark = pytest.mark.slow

import tools.run_binance_spot_canary as canary
from storage.ingest_receipts import IngestCounts, IngestResult
from tools.run_binance_spot_canary import backfill_windows, latest_closed_window, run

ROOT = Path(__file__).resolve().parents[1]


def _ingest_result(
    *, status: str, receipt_id: str, errors: tuple[str, ...] = ()
) -> IngestResult:
    succeeded = status == "success"
    return IngestResult(
        status=status,
        counts=IngestCounts(
            returned=1 if succeeded else 0,
            validated=1 if succeeded else 0,
            inserted=1 if succeeded else 0,
            updated=0,
            unchanged=0,
            rejected=0,
            committed=1 if succeeded else 0,
            count_semantics="exact_row_outcomes"
            if succeeded
            else "terminal_no_data_transaction",
        ),
        receipt_ids=(receipt_id,),
        errors=errors,
    )


def test_crypto_collector_window_uses_only_two_closed_adjacent_bars() -> None:
    window = latest_closed_window(datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc))
    assert window == {
        "start_open_time": "2026-07-28T09:35:00Z",
        "end_open_time": "2026-07-28T09:40:00Z",
    }


def test_backup_wake_reuses_the_same_latest_closed_window() -> None:
    close = datetime(2026, 9, 5, 9, 5, tzinfo=timezone.utc)
    primary_now = close + timedelta(seconds=10)
    backup_now = close + timedelta(seconds=70)
    expected = {
        "start_open_time": "2026-09-05T08:55:00Z",
        "end_open_time": "2026-09-05T09:00:00Z",
    }
    assert latest_closed_window(primary_now) == expected
    assert latest_closed_window(backup_now) == expected
    assert latest_closed_window(backup_now) == latest_closed_window(primary_now)
    planned = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=backup_now,
        backup_wake=True,
    )
    assert planned["windows"] == [expected]
    assert planned["state"] == "planned"


def test_missed_primary_backup_wake_still_writes_latest_closed_bar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    windows: list[dict[str, str]] = []

    def collect(*args, **kwargs):
        del args
        windows.append(dict(kwargs["request_window"]))
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{kwargs['dataset_id']}",
        )

    monkeypatch.setattr(canary, "collect_provider_native_dataset", collect)
    backup_now = datetime(2026, 9, 5, 9, 6, 10, tzinfo=timezone.utc)
    expected = latest_closed_window(datetime(2026, 9, 5, 9, 5, 10, tzinfo=timezone.utc))
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=backup_now,
        backup_wake=True,
    )

    assert result["state"] == "success"
    assert result["window_count"] == 1
    assert {tuple(sorted(window.items())) for window in windows} == {
        tuple(sorted(expected.items()))
    }
    assert all(item["window"] == expected for item in result["datasets"])
    assert len(result["datasets"]) == 40


def test_backup_wake_skips_when_primary_holds_the_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    lock_path = tmp_path / "collect.lock"
    holder = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    calls: list[str] = []

    def collect(*args, **kwargs):
        del args
        calls.append(kwargs["dataset_id"])
        return _ingest_result(status="success", receipt_id="receipt:unused")

    monkeypatch.setattr(canary, "collect_provider_native_dataset", collect)
    try:
        result = run(
            db_path=tmp_path / "unused.sqlite",
            lock_path=lock_path,
            execute=True,
            now=datetime(2026, 9, 5, 9, 6, 10, tzinfo=timezone.utc),
            backup_wake=True,
        )
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert result["state"] == "skipped_lock_held"
    assert result["will_call_provider"] is False
    assert result["windows"] == [
        latest_closed_window(datetime(2026, 9, 5, 9, 5, 10, tzinfo=timezone.utc))
    ]
    assert calls == []


def test_crypto_180_day_backfill_windows_are_contiguous_and_bounded() -> None:
    windows = backfill_windows(
        datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
        days=180,
    )
    assert len(windows) == 60
    previous_end: datetime | None = None
    for window in windows:
        start = datetime.fromisoformat(window["start_open_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(window["end_open_time"].replace("Z", "+00:00"))
        assert end - start <= timedelta(days=3)
        if previous_end is not None:
            assert start == previous_end + timedelta(minutes=5)
        previous_end = end
    assert windows[-1]["end_open_time"] == "2026-07-28T09:40:00Z"


def test_crypto_runner_plan_never_calls_provider_or_writes() -> None:
    result = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
    )
    assert result["state"] == "planned"
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_crypto_rules_plan_never_calls_provider_or_writes() -> None:
    result = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
        collect_rules=True,
    )
    assert result["state"] == "planned"
    assert result["collection_kind"] == "rules"
    assert len(result["datasets"]) == 40
    assert result["windows"] == [{}]
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_crypto_book_ticker_plan_never_calls_provider_or_writes() -> None:
    result = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
        collect_book_ticker=True,
    )
    assert result["state"] == "planned"
    assert result["collection_kind"] == "book_ticker"
    assert len(result["datasets"]) == 40
    assert result["windows"] == [{}]
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_crypto_runner_retries_one_provider_error_and_preserves_both_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    calls: list[tuple[str, str]] = []

    def collect(*args, **kwargs):
        del args
        dataset_id = kwargs["dataset_id"]
        attempt_id = kwargs["attempt_id"]
        calls.append((dataset_id, attempt_id))
        if (
            dataset_id.endswith("ethusdt.5m")
            and sum(item[0] == dataset_id for item in calls) == 1
        ):
            return _ingest_result(
                status="failed",
                receipt_id="receipt:eth-first-failure",
                errors=("provider_error",),
            )
        return _ingest_result(
            status="success",
            receipt_id=f"receipt:{dataset_id}:{len(calls)}",
        )

    monkeypatch.setattr(canary, "collect_provider_native_dataset", collect)
    result = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=datetime(2026, 8, 2, 12, 10, tzinfo=timezone.utc),
    )

    eth = next(
        item for item in result["datasets"] if item["dataset_id"].endswith("ethusdt.5m")
    )
    assert result["state"] == "success"
    assert eth["state"] == "success"
    assert eth["retry_count"] == 1
    assert eth["receipt_ids"][0] == "receipt:eth-first-failure"
    assert len(eth["receipt_ids"]) == 2
    assert sum(dataset_id.endswith("ethusdt.5m") for dataset_id, _ in calls) == 2
    assert len({attempt_id for _, attempt_id in calls}) == len(calls)


def test_crypto_runner_does_not_retry_non_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def collect(*args, **kwargs):
        del args
        calls.append(kwargs["attempt_id"])
        return _ingest_result(
            status="failed",
            receipt_id="receipt:validation-failure",
            errors=("validation_failed",),
        )

    monkeypatch.setattr(canary, "collect_provider_native_dataset", collect)
    attempts = canary._collect_with_one_provider_retry(
        db_path=tmp_path / "unused.sqlite",
        registry=object(),
        collector=object(),
        dataset_id="crypto.spot.binance.ethusdt.5m",
        request_window={"open_time": "2026-08-02T12:00:00Z"},
        now=datetime(2026, 8, 2, 12, 10, tzinfo=timezone.utc),
    )

    assert len(attempts) == 1
    assert attempts[0].errors == ("validation_failed",)
    assert len(calls) == 1


def test_crypto_units_are_physically_isolated_from_ashare_runtime() -> None:
    api = (ROOT / "deploy/systemd/tradingdatas-crypto-v1-internal.service").read_text()
    collector = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.service"
    ).read_text()
    timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.timer"
    ).read_text()
    retry_service = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect-retry.service"
    ).read_text()
    retry_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect-retry.timer"
    ).read_text()
    rules_service = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-rules.service"
    ).read_text()
    rules_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-rules.timer"
    ).read_text()
    book_ticker_service = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-book-ticker.service"
    ).read_text()
    book_ticker_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-book-ticker.timer"
    ).read_text()
    usdm_service = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-usdm-collect.service"
    ).read_text()
    usdm_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-usdm-collect.timer"
    ).read_text()
    oi_dump_service = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-oi-dump-collect.service"
    ).read_text()
    oi_dump_timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-oi-dump-collect.timer"
    ).read_text()
    premium_dump_service = (
        ROOT
        / "deploy/systemd/tradingdatas-crypto-binance-premium-dump-collect.service"
    ).read_text()
    premium_dump_timer = (
        ROOT
        / "deploy/systemd/tradingdatas-crypto-binance-premium-dump-collect.timer"
    ).read_text()
    profile = (ROOT / "deploy/crypto/tradingdatas_crypto_internal.env").read_text()

    units = (
        api
        + collector
        + timer
        + retry_service
        + retry_timer
        + rules_service
        + rules_timer
        + book_ticker_service
        + book_ticker_timer
        + usdm_service
        + usdm_timer
        + oi_dump_service
        + oi_dump_timer
        + premium_dump_service
        + premium_dump_timer
        + profile
    )
    assert "127.0.0.1:18082" not in units
    assert "18083" in profile
    assert "tradingdatas-crypto" in units
    assert "/opt/investment-data/tradingdatas-crypto" in units
    assert "/opt/investment/releases/tradingdatas/current" not in units
    assert "/opt/investment/releases/tradingdatas-crypto/current" in units
    assert "TRADINGDATAS_CANARY_MODE=binance_spot_v1" in profile
    assert "tradingdatas-crypto-binance-collect.service" in timer
    assert "OnCalendar=*-*-* *:0/5:00" in timer
    assert "--backup-wake" not in collector
    assert "tradingdatas-crypto-binance-collect-retry.service" in retry_timer
    assert "OnCalendar=*-*-* *:1/5:00" in retry_timer
    assert "--execute --backup-wake" in retry_service
    assert "/opt/investment-data/tradingdatas-crypto/collect.lock" in retry_service
    assert "tradingdatas-crypto-binance-rules.service" in rules_timer
    assert "--rules --execute" in rules_service
    assert "tradingdatas-crypto-binance-book-ticker.service" in book_ticker_timer
    assert "OnCalendar=*-*-* *:3/5:10" in book_ticker_timer
    assert "OnCalendar=*-*-* *:0/5:40" not in book_ticker_timer
    assert "--book-ticker --execute" in book_ticker_service
    assert "tradingdatas-crypto-binance-usdm-collect.service" in usdm_timer
    assert "OnCalendar=*-*-* *:2/5:00" in usdm_timer
    assert "tools/run_binance_usdm_canary.py" in usdm_service
    assert "/opt/investment-data/tradingdatas-crypto/collect-usdm.lock" in usdm_service
    assert "tradingdatas-crypto-binance-oi-dump-collect.service" in oi_dump_timer
    assert "OnCalendar=*-*-* 00/2:37:00" in oi_dump_timer
    assert "tools/run_binance_oi_dump_canary.py" in oi_dump_service
    assert "/opt/investment-data/tradingdatas-crypto/collect.lock" in oi_dump_service
    assert (
        "tradingdatas-crypto-binance-premium-dump-collect.service"
        in premium_dump_timer
    )
    assert "OnCalendar=*-*-* 01/2:53:00" in premium_dump_timer
    assert "tools/run_binance_premium_dump_canary.py" in premium_dump_service
    assert (
        "/opt/investment-data/tradingdatas-crypto/collect.lock"
        in premium_dump_service
    )
    assert "quicksync" not in units.lower()


def _five_minute_oncalendar_slots(timer_text: str) -> set[tuple[int, int]]:
    match = re.search(
        r"^OnCalendar=\*-\*-\* \*:(\d+)/5:(\d{2})$", timer_text, flags=re.M
    )
    assert match is not None, timer_text
    start_minute = int(match.group(1))
    second = int(match.group(2))
    return {(minute, second) for minute in range(start_minute, 60, 5)}


def test_bar_usdm_and_book_ticker_calendars_do_not_share_a_second() -> None:
    primary = _five_minute_oncalendar_slots(
        (ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.timer").read_text()
    )
    backup = _five_minute_oncalendar_slots(
        (
            ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect-retry.timer"
        ).read_text()
    )
    usdm = _five_minute_oncalendar_slots(
        (
            ROOT / "deploy/systemd/tradingdatas-crypto-binance-usdm-collect.timer"
        ).read_text()
    )
    book_ticker = _five_minute_oncalendar_slots(
        (
            ROOT / "deploy/systemd/tradingdatas-crypto-binance-book-ticker.timer"
        ).read_text()
    )
    assert primary == {(minute, 0) for minute in range(0, 60, 5)}
    assert backup == {(minute, 0) for minute in range(1, 60, 5)}
    assert usdm == {(minute, 0) for minute in range(2, 60, 5)}
    assert book_ticker == {(minute, 10) for minute in range(3, 60, 5)}
    occupied: dict[tuple[int, int], str] = {}
    for name, slots in (
        ("bar-primary", primary),
        ("bar-backup", backup),
        ("usdm", usdm),
        ("book-ticker", book_ticker),
    ):
        overlap = set(occupied).intersection(slots)
        assert not overlap, f"{name} shares {sorted(overlap)}"
        occupied.update(dict.fromkeys(slots, name))


def test_closed_bar_lock_wait_is_300s_and_backup_wake_does_not_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert canary._LOCK_WAIT_SECONDS == 300.0
    assert canary._BACKUP_LOCK_WAIT_SECONDS == 0.0
    waits: list[float] = []

    def fake_lock(path: Path, wait_seconds: float = canary._LOCK_WAIT_SECONDS):
        del path
        waits.append(wait_seconds)
        raise RuntimeError(f"collection lock is still held after {wait_seconds:.0f}s")

    monkeypatch.setattr(canary, "_bounded_lock", fake_lock)
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", "binance_spot_v1")
    now = datetime(2026, 9, 5, 9, 6, 10, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="after 300s"):
        run(
            db_path=tmp_path / "unused.sqlite",
            lock_path=tmp_path / "collect.lock",
            execute=True,
            now=now,
        )
    skipped = run(
        db_path=tmp_path / "unused.sqlite",
        lock_path=tmp_path / "collect.lock",
        execute=True,
        now=now,
        backup_wake=True,
    )
    assert skipped["state"] == "skipped_lock_held"
    assert waits == [300.0, 0.0]


def test_crypto_api_has_no_mutable_runtime_environment_override() -> None:
    api = (ROOT / "deploy/systemd/tradingdatas-crypto-v1-internal.service").read_text()

    assert "/etc/tradingdatas-crypto/internal-api.env" not in api
    assert api.count("EnvironmentFile=") == 1
    assert (
        "EnvironmentFile=/opt/investment/releases/tradingdatas-crypto/current/"
        "deploy/crypto/tradingdatas_crypto_internal.env"
    ) in api
    assert 'Environment="TRADINGDATAS_TOKEN_HASH_FILE=' in api
    assert 'Environment="TRADINGDATAS_TOKEN_SALT_FILE=' in api
    assert (
        'Environment="TRADINGDATAS_CURSOR_SIGNING_KEY_FILE='
        "/etc/tradingdatas-crypto/cursor_signing_key"
        '"'
    ) in api
    assert "TRADINGDATAS_CURSOR_SIGNING_KEY=" not in api
    assert "ConditionPathExists=/etc/tradingdatas-crypto/cursor_signing_key" in api
