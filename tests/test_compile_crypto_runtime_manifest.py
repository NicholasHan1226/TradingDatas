from __future__ import annotations

import hashlib
import json

from dataset_registry import (
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
)
from query_contract import public_catalog_version
from tools.compile_crypto_runtime_manifest import (
    catalog_contract_row,
    compile_manifest,
    dataset_contract_fingerprint,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_catalog_contract_fingerprints_match_reference_manifest() -> None:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    bars = registry.resolve("crypto.spot.binance.btcusdt.5m")
    rules = registry.resolve("crypto.spot.binance.btcusdt.rules")
    assert (
        dataset_contract_fingerprint(catalog_contract_row(bars))
        == "4d098541e70765e388eefaeb43c4dda95e301404affcb78dd9f16806f443a915"
    )
    assert (
        dataset_contract_fingerprint(catalog_contract_row(rules))
        == "c36175966cafeb7c0e327b4d19dd31819c8c303c3387106641de68337a8c4e7d"
    )


def test_compile_manifest_is_deterministic_and_self_consistent() -> None:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    first = compile_manifest(registry)
    second = compile_manifest(registry)
    assert first == second
    assert first["schema"] == "tradingagent.crypto.delayed_paper_runtime_manifest.v1"
    assert first["catalog_version"] == public_catalog_version(registry)
    assert len(first["profile"]["symbols"]) == 2
    assert first["profile"]["mode"] == "tradingdatas_handoff"
    assert first["profile_sha256"] == hashlib.sha256(
        _canonical_json(first["profile"])
    ).hexdigest()
    # Compilation is byte-deterministic (canonical JSON plus trailing newline).
    assert _canonical_json(first) + b"\n" == _canonical_json(second) + b"\n"
    # Every symbol binding pins the same catalog version as the manifest.
    for binding in first["profile"]["symbols"]:
        for dataset in (binding["bars"], binding["instrument_rules"]):
            assert dataset["catalog_version"] == first["catalog_version"]
