"""Public preflight must distinguish a callable probe from activation support."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "public-web/scripts/build-paused-contract-preflight-snapshot.py"


def _generator():
    spec = importlib.util.spec_from_file_location("public_preflight_snapshot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _groups(snapshot):
    return {group["id"]: group["interfaces"] for group in snapshot["groups"]}


def test_probe_executable_local_window_is_not_activation_ready() -> None:
    generator = _generator()
    original_snapshot = generator.OUTPUT_PATH.read_bytes()
    groups = _groups(generator.build_snapshot())
    blocked = groups["requires_activation_window_contract"]
    assert {
        "apiName": "stk_nineturn",
        "datasetId": "cn.dataset.stk_nineturn",
        "probeState": "executable",
        "reasonCode": "activation_window_contract_unsupported",
    } in blocked
    assert "stk_nineturn" not in {
        row["apiName"] for row in groups["ready_for_bounded_https_probe"]
    }
    assert "index_weight" in {
        row["apiName"] for row in groups["requires_seed_receipt"]
    }
    assert generator.OUTPUT_PATH.read_bytes() == original_snapshot


def test_snapshot_uses_shared_activation_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = _generator()
    # A future compiler-supported window must move without a dataset-specific
    # front-end exception or a second copy of the activation rules.
    monkeypatch.setattr(generator, "_activation_window_is_supported", lambda contract: True)
    groups = _groups(generator.build_snapshot())
    assert "stk_nineturn" in {
        row["apiName"] for row in groups["ready_for_bounded_https_probe"]
    }
    assert groups["requires_activation_window_contract"] == []
