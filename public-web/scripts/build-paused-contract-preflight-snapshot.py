#!/usr/bin/env python3
"""Project paused Tushare contracts into a public, non-runtime preflight view.

The snapshot is intentionally narrower than a provider probe.  It compiles the
same frozen request plan in memory, then keeps only paused contracts that have
an observed active entitlement.  It never calls QuickSync, writes a receipt,
or changes activation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.compile_tushare_runtime_contracts import compile_https_probe_plan  # noqa: E402
from tools.compile_provider_native_registry import (  # noqa: E402
    _activation_window_is_supported,
    load_upstream_contract_bundle,
)


CONFIG = ROOT / "config"
OUTPUT_PATH = ROOT / "public-web" / "src" / "pausedContractPreflightSnapshot.json"


def _read(name: str) -> bytes:
    return (CONFIG / name).read_bytes()


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def build_snapshot() -> dict[str, object]:
    documents = _read("tushare_document_contracts.v1.yaml")
    request_observations = _read("tushare_request_observations.v1.yaml")
    transport_observations = _read("quicksync_interface_observations.v1.yaml")
    registered_contracts = _read("tushare_upstream_contracts.v1.yaml")
    now = datetime.now(timezone.utc)
    partition = now.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    plan = compile_https_probe_plan(
        documents,
        request_observations,
        transport_observations,
        registered_contract_bundle=registered_contracts,
        official_contract_sha256=hashlib.sha256(documents).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_observations).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_observations).hexdigest(),
        expected_commit=_head(),
        run_clock=now,
        scheduled_partition=partition,
    )
    contracts = {
        contract["api_name"]: contract
        for contract in load_upstream_contract_bundle(
            yaml.safe_load(registered_contracts)
        )["contracts"]
    }
    registry = yaml.safe_load((CONFIG / "provider_native_dataset_registry.yaml").read_text(encoding="utf-8"))
    paused = {
        binding["api_name"]: dataset["dataset_id"]
        for dataset in registry["datasets"]
        for binding in dataset["provider_bindings"]
        if binding["provider"] == "tushare"
        and binding["activation_state"] == "paused"
        and binding["entitlement_state"] == "active"
    }
    states = {
        "ready_for_bounded_https_probe": [],
        "requires_seed_receipt": [],
        "requires_activation_window_contract": [],
    }
    for entry in plan["entries"]:
        api_name = entry["api_name"]
        if api_name not in paused:
            continue
        row = {"apiName": api_name, "datasetId": paused[api_name]}
        if entry["probe_state"] == "executable" and entry["ingest_contract_state"] == "ready":
            # Probe/ingest readiness alone does not imply that the activation
            # compiler accepts this window. Reuse its exact structural gate.
            if _activation_window_is_supported(contracts[api_name]):
                states["ready_for_bounded_https_probe"].append(row)
            else:
                states["requires_activation_window_contract"].append({
                    **row,
                    "probeState": entry["probe_state"],
                    "reasonCode": "activation_window_contract_unsupported",
                })
        elif entry["probe_block_reasons"] == ["dependency_seed_receipt_unresolved"]:
            states["requires_seed_receipt"].append(row)
    return {
        "schemaVersion": 1,
        "authority": "compiled_contract_preflight_only",
        "warning": "This static preflight snapshot makes no provider call and proves neither observation, collection, customer access, nor sellability.",
        "groups": [
            {"id": group_id, "interfaces": states[group_id]}
            for group_id in states
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("paused contract preflight snapshot is stale")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
