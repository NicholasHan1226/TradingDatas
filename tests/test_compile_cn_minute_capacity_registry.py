from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from dataset_registry import load_dataset_registry
from tools.compile_cn_minute_capacity_registry import (
    _ROLLBACK_CANARY,
    compile_capacity_candidate,
)
from tools.validate_cn_minute_universe import validate_universe_contract

ROOT = Path(__file__).resolve().parents[1]
BASE_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _contract() -> dict[str, object]:
    symbols = [f"{value:06d}.SZ" for value in range(1, 501)]
    return {
        "schema_version": 2,
        "universe_id": "cn-equity-mainboard-rt-min-500-v1",
        "as_of": "2026-08-03T00:00:00Z",
        "source": {
            "dataset_id": "cn.equity.security_master",
            "provider": "tushare",
            "receipt_id": "receipt:reviewed-security-master",
            "receipt_sha256": "a" * 64,
            "registry_sha256": "b" * 64,
            "snapshot_sha256": "c" * 64,
        },
        "selection": {
            "source_field": "ts_code",
            "source_equals": {"curr_type": "CNY", "list_status": "L", "market": "主板"},
            "source_date_field": "list_date",
            "source_date_lte_days": 30,
            "source_order": "stable_hash",
        },
        "batch_size": 100,
        "symbols": symbols,
        "symbols_sha256": _sha256(symbols),
    }


def _base_registry() -> dict[str, object]:
    document = yaml.safe_load(BASE_REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    # The live rt_min binding has intentionally moved to the frozen full-universe
    # fanout (docs/ASHARE_MINUTE_COHORTS.md keeps the 500/100 shards and the
    # 30-symbol canary as historical rollback evidence only), while the capacity
    # compiler still gates on the frozen 30-symbol rollback canary shape. Restore
    # that shape on the fixture copy so the compiler contract stays testable.
    binding = _rt_min(document)["provider_bindings"][0]
    binding["request_template"] = {"freq": "5MIN", "ts_code": _ROLLBACK_CANARY}
    binding["request_variants"] = [{}]
    binding["fanout"] = {"strategy": "none"}
    binding["resumable_fanout"] = None
    return document


def _rt_min(document: dict[str, object]) -> dict[str, object]:
    datasets = document["datasets"]
    assert isinstance(datasets, list)
    result = next(item for item in datasets if item["dataset_id"] == "cn.dataset.rt_min")
    assert isinstance(result, dict)
    return result


def test_compiler_emits_one_paused_exact_100_symbol_candidate_without_mutating_30_canary(
    tmp_path: Path,
) -> None:
    base = _base_registry()
    before = deepcopy(base)

    candidate, reference = compile_capacity_candidate(
        universe_contract=_contract(), base_registry=base, shard_index=2
    )

    assert base == before
    binding = _rt_min(candidate)["provider_bindings"][0]
    assert binding["activation_state"] == "paused"
    assert binding["request_variants"] == [{}]
    assert binding["request_template"]["freq"] == "5MIN"
    assert binding["request_template"]["ts_code"].split(",") == _contract()["symbols"][200:300]
    assert reference == {
        "schema_version": 1,
        "state": "candidate",
        "dataset_id": "cn.dataset.rt_min",
        "universe_id": "cn-equity-mainboard-rt-min-500-v1",
        "universe_sha256": validate_universe_contract(_contract())["universe_sha256"],
        "source": _contract()["source"],
        "shard": {
            "index": 2,
            "symbol_count": 100,
            "symbols_sha256": _sha256(_contract()["symbols"][200:300]),
        },
        "promotion_requirements": [
            "independent_activation_evidence",
            "complete_same_snapshot_receipt_cohort",
            "catalog_and_bounded_query_readback",
            "tradingagent_consumer_readback",
            "tradingcopilot_consumer_readback",
        ],
    }

    path = tmp_path / "candidate.yaml"
    path.write_text(yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False), encoding="utf-8")
    loaded = load_dataset_registry(path)
    loaded_binding = loaded.resolve("cn.dataset.rt_min").provider_bindings[0]
    assert loaded_binding.activation_state == "paused"


@pytest.mark.parametrize("shard_index", [-1, 5])
def test_compiler_rejects_shards_outside_the_frozen_five_by_100_contract(shard_index: int) -> None:
    with pytest.raises(ValueError, match="shard_index"):
        compile_capacity_candidate(
            universe_contract=_contract(), base_registry=_base_registry(), shard_index=shard_index
        )


def test_compiler_refuses_a_base_registry_when_the_30_symbol_rollback_canary_has_drifted() -> None:
    base = _base_registry()
    binding = _rt_min(base)["provider_bindings"][0]
    binding["request_template"]["ts_code"] = "000001.SZ"

    with pytest.raises(ValueError, match="frozen 30-symbol rollback canary"):
        compile_capacity_candidate(
            universe_contract=_contract(), base_registry=base, shard_index=0
        )
