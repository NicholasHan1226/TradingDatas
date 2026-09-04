#!/usr/bin/env python3
"""Build the public index of domestic interfaces not yet in the runtime registry.

This is an explicit capability-scope projection. It intentionally never assigns
dataset IDs, fields, cadence, entitlement, or collection health to a candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = ROOT / "config" / "tushare_capability_scope.v2.yaml"
REGISTRY_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"
OUTPUT_PATH = ROOT / "public-web" / "src" / "discoveryInterfaceSnapshot.json"


def _dimension_values(document: dict[str, object], name: str) -> dict[str, set[str]]:
    groups = document["dimensions"][name]
    return {group["value"]: set(group["api_names"]) for group in groups}


def build_snapshot() -> dict[str, object]:
    scope = yaml.safe_load(SCOPE_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    dimensions = {
        name: _dimension_values(scope, name)
        for name in ("product_scope", "lifecycle", "contract_state")
    }
    registered = {
        binding["api_name"]
        for dataset in registry["datasets"]
        for binding in dataset["provider_bindings"]
        if binding["provider"] == "tushare"
    }
    candidate_names = (
        dimensions["product_scope"]["domestic_read_dataset"]
        & dimensions["lifecycle"]["current"]
        & (dimensions["contract_state"]["missing_official_contract"] | dimensions["contract_state"]["review_required"])
    ) - registered
    state_by_name = {
        api_name: state
        for state, names in dimensions["contract_state"].items()
        for api_name in names
    }
    candidates = [
        {"apiName": api_name, "contractState": state_by_name[api_name]}
        for api_name in sorted(candidate_names)
    ]
    return {
        "schemaVersion": 1,
        "authority": "capability_scope_only",
        "warning": "Candidates are not runtime contracts and have no inferred dataset ID, schema, cadence, entitlement, collection state, or customer access.",
        "scopeId": scope["scope_id"],
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("discovery interface snapshot is stale")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
