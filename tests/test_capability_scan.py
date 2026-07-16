from __future__ import annotations

from pathlib import Path
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


def test_stock_master_reference_capability_is_active_and_canonical() -> None:
    meta = capability_scan.READER_REGISTRY["get_reference"]

    assert "status_override" not in meta
    assert meta["func"] == "get_reference"
    assert meta["smoke_args"] == ["stock_master"]
    assert "SQLite market_assets" in meta["description"]
    assert "A-share stock" in meta["description"]
    assert meta["fields"] == [
        "market",
        "symbol",
        "name",
        "asset_type",
        "exchange",
        "sector",
        "list_date",
        "last_trade_date",
        "expiry_date",
        "status",
        "provider",
        "source_file",
        "updated_at",
        "provenance",
        "freshness",
        "quality",
        "degraded",
        "lineage",
    ]


def test_stock_master_reference_is_scanned_in_test_only_mode(tmp_path, monkeypatch) -> None:
    registry_path = tmp_path / "capability_registry.json"
    changes_path = tmp_path / "capability_changes.jsonl"

    monkeypatch.setattr(capability_scan, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(capability_scan, "CHANGES_PATH", changes_path)
    monkeypatch.setattr(capability_scan, "DOCS_DIR", tmp_path)
    monkeypatch.setattr(capability_scan, "_load_previous_registry", lambda: {})
    monkeypatch.setattr(capability_scan, "_resolve_smoke_args", lambda meta: (meta.get("smoke_args", []), {}))
    module = SimpleNamespace()
    monkeypatch.setattr(capability_scan, "_import_module", lambda _name: module)

    calls: list[tuple[str, list[object]]] = []

    def fake_call(_mod, func, args, _kwargs=None):
        calls.append((func, args))
        return {
            "latency_ms": 1.0,
            "rows": 1,
            "error": "",
            "degraded_reason": "",
        }

    monkeypatch.setattr(capability_scan, "_call_func", fake_call)

    result = capability_scan.run_scan(test_only=True, write_doc=False)
    endpoints = {item["name"]: item for item in result["registry"]["endpoints"]}

    assert ("get_reference", ["stock_master"]) in calls
    assert endpoints["get_reference"]["status"] == "ok"
    assert endpoints["get_reference"]["rows"] == 1


def test_stock_master_reference_is_legacy_compatibility_not_public_target() -> None:
    contract = Path("API_CONTRACT.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    status = Path("STATUS.md").read_text(encoding="utf-8")
    matrix = Path("docs/market_capability_matrix.md").read_text(encoding="utf-8")
    prompt = Path("docs/external_agent_api_prompt.md").read_text(encoding="utf-8")

    for document in (readme, status):
        assert "GET /v1/catalog" in document
        assert "POST /v1/query" in document
        assert "/reference?table=stock_master&limit=6000" not in document

    assert "legacy compatibility surface" in contract
    assert "Target contract (not yet live)" in contract
    assert "migration inventory" in matrix
    assert "Legacy compatibility prompt" in prompt

    assert "/reference?table=stock_master&limit=6000" in contract
    assert "/reference?table=stock_master&limit=6000" in matrix
    assert "/reference?table=stock_master&limit=6000" in prompt
    assert "market_assets" in contract
    assert "market_assets" in matrix
    assert "market_assets" in prompt
    assert "最大 10,000" in contract
    assert "缺表或空表" in contract
    assert "provider/CSV fallback" in contract
    assert "Only `stock_master`" in matrix
    assert "Do not substitute another reference table" in prompt
