"""Compile one paused, receipt-bound 100-symbol CN-minute registry candidate.

The compiler is deliberately offline.  It accepts a validated immutable
500-symbol universe and an existing runtime registry, then writes a *paused*
candidate for exactly one contiguous 100-symbol shard.  It never calls a
provider, opens SQLite, changes the active registry, or enables a service or
timer.  Promotion still requires independent activation evidence and the full
receipt-to-consumer readback chain recorded in its companion reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from tools.validate_cn_minute_universe import validate_universe_contract

_DATASET_ID = "cn.dataset.rt_min"
_SHARD_SIZE = 100
_ROLLBACK_CANARY = (
    "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,"
    "600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,"
    "002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,"
    "600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,"
    "600845.SH,601138.SH"
)
_PROMOTION_REQUIREMENTS = [
    "independent_activation_evidence",
    "complete_same_snapshot_receipt_cohort",
    "catalog_and_bounded_query_readback",
    "tradingagent_consumer_readback",
    "tradingcopilot_consumer_readback",
]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _rt_min_binding(registry: Mapping[str, object]) -> dict[str, Any]:
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise TypeError("base registry datasets are invalid")
    matches = [
        item
        for item in datasets
        if isinstance(item, dict) and item.get("dataset_id") == _DATASET_ID
    ]
    if len(matches) != 1:
        raise ValueError("base registry must contain exactly one cn.dataset.rt_min dataset")
    bindings = matches[0].get("provider_bindings")
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise ValueError("base registry rt_min binding is invalid")
    return _object(bindings[0], "base registry rt_min binding")


def _validate_rollback_canary(registry: Mapping[str, object]) -> None:
    binding = _rt_min_binding(registry)
    template = binding.get("request_template")
    if not isinstance(template, dict) or template != {"freq": "5MIN", "ts_code": _ROLLBACK_CANARY}:
        raise ValueError("base registry frozen 30-symbol rollback canary has drifted")
    if binding.get("request_variants") != [{}] or binding.get("fanout") != {"strategy": "none"}:
        raise ValueError("base registry frozen 30-symbol rollback canary has drifted")


def compile_capacity_candidate(
    *,
    universe_contract: Mapping[str, object],
    base_registry: Mapping[str, object],
    shard_index: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return a paused registry candidate and its receipt-bound promotion reference."""

    if type(shard_index) is not int or not 0 <= shard_index < 5:
        raise ValueError("shard_index must select one shard from the frozen five-by-100 contract")
    validated = validate_universe_contract(universe_contract)
    symbols = universe_contract.get("symbols")
    if not isinstance(symbols, list):  # defensive; validator above owns the exact contract check
        raise TypeError("minute universe symbols are invalid")
    start = shard_index * _SHARD_SIZE
    shard_symbols = symbols[start : start + _SHARD_SIZE]
    if len(shard_symbols) != _SHARD_SIZE:
        raise ValueError("minute universe shard is incomplete")

    _validate_rollback_canary(base_registry)
    candidate = deepcopy(dict(base_registry))
    binding = _rt_min_binding(candidate)
    binding["activation_state"] = "paused"
    binding["request_template"] = {"freq": "5MIN", "ts_code": ",".join(shard_symbols)}
    binding["request_variants"] = [{}]

    source = validated["source"]
    if not isinstance(source, dict):  # defensive; validator owns this shape
        raise TypeError("validated source is invalid")
    reference = {
        "schema_version": 1,
        "state": "candidate",
        "dataset_id": _DATASET_ID,
        "universe_id": validated["universe_id"],
        "universe_sha256": validated["universe_sha256"],
        "source": source,
        "shard": {
            "index": shard_index,
            "symbol_count": _SHARD_SIZE,
            "symbols_sha256": _sha256(shard_symbols),
        },
        "promotion_requirements": list(_PROMOTION_REQUIREMENTS),
    }
    return candidate, reference


def _document(path: Path, label: str) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} must be readable YAML") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--base-registry", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--registry-output", required=True, type=Path)
    parser.add_argument("--reference-output", required=True, type=Path)
    args = parser.parse_args(argv)

    candidate, reference = compile_capacity_candidate(
        universe_contract=_document(args.universe, "universe contract"),
        base_registry=_document(args.base_registry, "base registry"),
        shard_index=args.shard_index,
    )
    args.registry_output.write_text(
        yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    args.reference_output.write_bytes(_canonical_json(reference) + b"\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
