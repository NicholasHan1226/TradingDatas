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
        lambda _mod, _func, _args: {"latency_ms": 1.0, "rows": 1, "error": ""},
    )

    result = capability_scan.run_scan(test_only=True, write_doc=False)

    assert result["doc_path"] == "(suppressed)"
    assert registry_path.exists()
    assert changes_path.exists()
    assert not doc_path.exists()
