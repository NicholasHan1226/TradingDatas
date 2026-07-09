from __future__ import annotations

from types import SimpleNamespace

from tools import capability_scan


def test_run_scan_can_refresh_registry_without_rewriting_doc(tmp_path, monkeypatch) -> None:
    registry_path = tmp_path / "capability_registry.json"
    changes_path = tmp_path / "capability_changes.jsonl"
    doc_path = tmp_path / "API_CONTRACT.md"

    monkeypatch.setattr(capability_scan, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(capability_scan, "CHANGES_PATH", changes_path)
    monkeypatch.setattr(capability_scan, "DOC_PATH", doc_path)
    monkeypatch.setattr(capability_scan, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(capability_scan, "_load_previous_registry", lambda: {})
    monkeypatch.setattr(capability_scan, "_import_module", lambda _name: SimpleNamespace())
    monkeypatch.setattr(
        capability_scan,
        "_call_func",
        lambda _mod, _func, _args, _kwargs=None: {"latency_ms": 1.0, "rows": 1, "error": "", "degraded_reason": ""},
    )

    result = capability_scan.run_scan(test_only=True, write_doc=False)

    assert result["doc_path"] == "(suppressed)"
    assert registry_path.exists()
    assert changes_path.exists()
    assert not doc_path.exists()


def test_capability_scan_resolves_provider_specific_smoke_samples(monkeypatch) -> None:
    monkeypatch.setattr(
        capability_scan,
        "_read_latest_sample",
        lambda **kwargs: {"symbol": "700001.TI", "trade_date": "20260708"},
    )
    monkeypatch.setattr(
        capability_scan,
        "_latest_provider_sample",
        lambda table, provider, fallback_symbol="", fallback_date="": {
            "tushare_daily": {"symbol": "000001.SZ", "trade_date": "20260708"},
            "tushare_moneyflow": {"symbol": "", "trade_date": "20260706"},
            "tushare_limit_list_d": {"symbol": "", "trade_date": "20260707"},
            "tushare_margin": {"symbol": "", "trade_date": "20260705"},
        }.get(provider, {"symbol": fallback_symbol, "trade_date": fallback_date}),
    )
    monkeypatch.setattr(capability_scan, "_latest_event_date", lambda: "20260709")

    daily_args, _daily_kwargs = capability_scan._resolve_smoke_args(
        capability_scan.READER_REGISTRY["get_market_data"]
    )
    _moneyflow_args, moneyflow_kwargs = capability_scan._resolve_smoke_args(
        capability_scan.READER_REGISTRY["get_moneyflow"]
    )
    _limit_args, limit_kwargs = capability_scan._resolve_smoke_args(
        capability_scan.READER_REGISTRY["get_limit_list"]
    )

    assert daily_args == ["000001.SZ", "20260708", "20260708"]
    assert moneyflow_kwargs["date"] == "20260706"
    assert limit_kwargs["trade_date"] == "20260707"


def test_retired_reference_capability_is_skipped() -> None:
    assert capability_scan.READER_REGISTRY["get_reference"]["status_override"] == "skipped"
