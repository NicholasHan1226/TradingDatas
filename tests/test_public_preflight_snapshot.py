"""Public preflight must distinguish a callable probe from activation support."""
from __future__ import annotations

import hashlib
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from tools.compile_tushare_runtime_contracts import (
    compile_https_probe_plan,
    compile_runtime_contract_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "public-web/scripts/build-paused-contract-preflight-snapshot.py"
CONFIG = ROOT / "config"
DOCUMENTS = CONFIG / "tushare_document_contracts.v1.yaml"
REVIEWED = CONFIG / "tushare_reviewed_contracts.v1.yaml"
POLICY = CONFIG / "tushare_runtime_contract_policy.v1.yaml"
CADENCE_POLICY = CONFIG / "tushare_cadence_policy.v1.yaml"
REQUEST_OBSERVATIONS = CONFIG / "tushare_request_observations.v1.yaml"
TRANSPORT_OBSERVATIONS = CONFIG / "quicksync_interface_observations.v1.yaml"
UPSTREAM_CONTRACTS = CONFIG / "tushare_upstream_contracts.v1.yaml"


def _generator():
    spec = importlib.util.spec_from_file_location("public_preflight_snapshot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _groups(snapshot):
    return {group["id"]: group["interfaces"] for group in snapshot["groups"]}


def _yaml_bytes(document: dict[str, object]) -> bytes:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _live_request_and_bundle() -> tuple[bytes, bytes]:
    request_bytes = REQUEST_OBSERVATIONS.read_bytes()
    transport_bytes = TRANSPORT_OBSERVATIONS.read_bytes()
    document_bytes = DOCUMENTS.read_bytes()
    bundle = compile_runtime_contract_bundle(
        document_bytes,
        REVIEWED.read_bytes(),
        POLICY.read_bytes(),
        CADENCE_POLICY.read_bytes(),
        request_observations=request_bytes,
        transport_observations=transport_bytes,
        official_contract_sha256=hashlib.sha256(document_bytes).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_bytes).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )
    observations = yaml.safe_load(request_bytes)
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    return _yaml_bytes(observations), _yaml_bytes(bundle)


def _bind_live_preflight(generator, monkeypatch: pytest.MonkeyPatch) -> None:
    request_bytes, bundle_bytes = _live_request_and_bundle()

    def _read(name: str) -> bytes:
        if name == "tushare_request_observations.v1.yaml":
            return request_bytes
        if name == "tushare_upstream_contracts.v1.yaml":
            return bundle_bytes
        return (CONFIG / name).read_bytes()

    monkeypatch.setattr(generator, "_read", _read)


def test_frozen_dump_binds_wip_observations_without_preflight_json_regen() -> None:
    plan = compile_https_probe_plan(
        DOCUMENTS.read_bytes(),
        REQUEST_OBSERVATIONS.read_bytes(),
        TRANSPORT_OBSERVATIONS.read_bytes(),
        registered_contract_bundle=UPSTREAM_CONTRACTS.read_bytes(),
        official_contract_sha256=hashlib.sha256(DOCUMENTS.read_bytes()).hexdigest(),
        transport_observations_sha256=hashlib.sha256(
            TRANSPORT_OBSERVATIONS.read_bytes()
        ).hexdigest(),
        request_observations_sha256=hashlib.sha256(
            REQUEST_OBSERVATIONS.read_bytes()
        ).hexdigest(),
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
    )
    assert plan["counts"]["planned"] == 190
    assert plan["counts"]["executable"] == 135
    assert plan["counts"]["ingest_contract_ready"] == 128


def test_probe_executable_single_partition_local_datetime_is_window_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _generator()
    original_snapshot = generator.OUTPUT_PATH.read_bytes()
    _bind_live_preflight(generator, monkeypatch)
    groups = _groups(generator.build_snapshot())
    assert {
        "apiName": "stk_nineturn",
        "datasetId": "cn.dataset.stk_nineturn",
    } in groups["ready_for_bounded_https_probe"]
    assert "stk_nineturn" not in {
        row["apiName"] for row in groups["requires_activation_window_contract"]
    }
    assert "index_weight" in {
        row["apiName"] for row in groups["requires_seed_receipt"]
    }
    assert generator.OUTPUT_PATH.read_bytes() == original_snapshot


def test_snapshot_uses_shared_activation_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = _generator()
    _bind_live_preflight(generator, monkeypatch)
    # A future compiler-supported window must move without a dataset-specific
    # front-end exception or a second copy of the activation rules.
    monkeypatch.setattr(generator, "_activation_window_is_supported", lambda contract: True)
    groups = _groups(generator.build_snapshot())
    assert "stk_nineturn" in {
        row["apiName"] for row in groups["ready_for_bounded_https_probe"]
    }
    assert groups["requires_activation_window_contract"] == []
