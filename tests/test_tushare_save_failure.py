from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from collectors.tushare import collector as collector_module
from collectors.tushare import sync_daily
from collectors.tushare.collector import TushareCollector
from collectors.tushare.sync_daily import sync_tier


def test_save_failure_after_rows_raises_save_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_collector = TushareCollector()
    monkeypatch.setattr(test_collector, "DATA_ROOT", tmp_path / "tushare")

    def fail_replace(src: str, dst: str) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(collector_module.os, "replace", fail_replace)
    expected_error = getattr(collector_module, "SaveError", OSError)

    with pytest.raises(expected_error):
        test_collector.save("daily", [{"ts_code": "000001.SZ", "trade_date": "20260702"}], "20260702")


class _SaveFailCollector(TushareCollector):
    def collect(self, api_name: str, params: dict[str, Any], fields: str | None = None) -> list[dict[str, Any]]:
        self.last_collect_failed = False
        return [{"ts_code": "000001.SZ", "trade_date": "20260702"}]

    def save(
        self,
        api_name: str,
        rows: list[dict[str, Any]],
        trade_date: str,
        filename: str | None = None,
    ) -> Path | None:
        raise collector_module.SaveError(api_name, Path("/tmp/failed.csv"), "No space left on device")


def test_sync_tier_counts_save_failures_separately_from_api_failures() -> None:
    stats = sync_tier(
        _SaveFailCollector(),
        "P1_eod_daily",
        [{"api_name": "daily", "per_stock": False, "params": {}}],
        stock_codes=["000001.SZ"],
        trade_date="20260702",
        start_date="20260702",
        end_date="20260702",
        sqlite_bridge_enabled=False,
    )

    assert stats["daily"]["rows"] == 1
    assert stats["daily"]["failure_count"] == 0
    assert stats["daily"]["save_failure_count"] == 1
    assert stats["_tier_summary"]["failure_count"] == 0
    assert stats["_tier_summary"]["save_failure_count"] == 1


def test_exit_on_failure_considers_api_save_and_bridge_failures() -> None:
    assert sync_daily._failure_exit_code(
        {"calls": 10, "failure_count": 6, "save_failure_count": 0, "bridge_failure_count": 0},
        threshold=0.5,
        exit_on_failure=True,
    ) == 2
    assert sync_daily._failure_exit_code(
        {"calls": 10, "failure_count": 0, "save_failure_count": 1, "bridge_failure_count": 0},
        threshold=0.5,
        exit_on_failure=True,
    ) == 2
    assert sync_daily._failure_exit_code(
        {"calls": 10, "failure_count": 0, "save_failure_count": 0, "bridge_failure_count": 1},
        threshold=0.5,
        exit_on_failure=True,
    ) == 2
    assert sync_daily._failure_exit_code(
        {"calls": 10, "failure_count": 4, "save_failure_count": 0, "bridge_failure_count": 0},
        threshold=0.5,
        exit_on_failure=True,
    ) == 0
    assert sync_daily._failure_exit_code(
        {"calls": 10, "failure_count": 10, "save_failure_count": 10, "bridge_failure_count": 10},
        threshold=0.5,
        exit_on_failure=False,
    ) == 0
