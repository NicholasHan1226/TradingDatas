from __future__ import annotations

import hashlib
import json

import pytest

from tools.validate_cn_minute_universe import validate_universe_contract


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _synthetic_symbols() -> list[str]:
    """Structural fixture only; it is not a proposed or real market universe."""

    return [f"{value:06d}.SZ" for value in range(1, 501)]


def _contract(symbols: list[str] | None = None) -> dict[str, object]:
    values = _synthetic_symbols() if symbols is None else symbols
    return {
        "schema_version": 1,
        "universe_id": "cn-equity-mainboard-rt-min-500-v1",
        "as_of": "2026-08-03T00:00:00Z",
        "source": {
            "dataset_id": "cn.equity.security_master",
            "provider": "tushare",
            "receipt_id": "receipt:source-snapshot",
            "registry_sha256": "a" * 64,
            "snapshot_sha256": "b" * 64,
        },
        "selection": {
            "source_field": "ts_code",
            "source_equals": {
                "curr_type": "CNY",
                "list_status": "L",
                "market": "主板",
            },
            "source_date_field": "list_date",
            "source_date_lte_days": 30,
            "source_order": "stable_hash",
        },
        "batch_size": 100,
        "symbols": values,
        "symbols_sha256": _sha256(values),
    }


def test_validator_emits_a_hash_bound_five_shard_reference() -> None:
    contract = _contract()

    artifact = validate_universe_contract(contract)

    assert artifact["symbol_count"] == 500
    assert artifact["symbols_sha256"] == contract["symbols_sha256"]
    assert artifact["sharding"] == {
        "parameter": "ts_code",
        "batch_size": 100,
        "shard_count": 5,
        "shards": [
            {"index": index, "value_count": 100}
            for index in range(5)
        ],
    }
    assert artifact["registry_manifest_reference"] == {
        "dataset_id": "cn.dataset.rt_min",
        "provider": "tushare",
        "api_name": "rt_min",
        "parameter": "ts_code",
        "universe_id": "cn-equity-mainboard-rt-min-500-v1",
        "universe_sha256": artifact["universe_sha256"],
    }


@pytest.mark.parametrize(
    ("symbols", "message"),
    [
        (_synthetic_symbols()[:-1], "must contain exactly 500 symbols"),
        (_synthetic_symbols()[:-1] + ["000001.SZ"], "must be unique"),
        (_synthetic_symbols()[:-1] + ["not-a-ts-code"], "contains an invalid ts_code"),
    ],
)
def test_validator_rejects_non_frozen_symbol_lists(
    symbols: list[str], message: str
) -> None:
    contract = _contract(symbols)
    contract["symbols_sha256"] = _sha256(symbols)

    with pytest.raises(ValueError, match=message):
        validate_universe_contract(contract)
