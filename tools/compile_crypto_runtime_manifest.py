#!/usr/bin/env python3
"""Compile the Crypto g5 round-trip runtime manifest from the canary registry.

The runtime (TradingAgent ``Crypto/delayed_paper_runtime.py``) binds its
read-only queries to an external manifest that pins the TradingDatas catalog
version, the per-dataset consumer query choices, and a canonical consumer
contract SHA-256 per dataset.  This tool rebuilds that manifest from the
checked-in canary registry so a registry change (for example declaring
``partition_field``) can be released together with a regenerated manifest.

The manifest is emitted in canonical JSON (``sort_keys``, compact separators,
UTF-8, trailing newline) exactly as the runtime reader requires.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    DatasetDefinition,
    load_dataset_registry,
)
from query_contract import public_catalog_version  # noqa: E402


MANIFEST_SCHEMA = "tradingagent.crypto.delayed_paper_runtime_manifest.v1"
DEFAULT_BASE_URL = "http://127.0.0.1:18083"
DEFAULT_ACCESS_POLICY_ID = "tradingagent-crypto-read-v1"
ALLOWED_SYMBOLS = ("BTCUSDT", "ETHUSDT")

BAR_FIELDS = {
    "symbol": "symbol",
    "open_time": "open_time",
    "close_time": "close_time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "quote_volume": "quote_volume",
    "trade_count": "trade_count",
}
RULE_FIELDS = {
    "symbol": "symbol",
    "status": "status",
    "base_asset": "base_asset",
    "quote_asset": "quote_asset",
    "price_tick": "price_filter_tick_size",
    "quantity_step": "lot_size_step_size",
    "min_quantity": "lot_size_min_qty",
    "min_notional": "min_notional",
}
SAFETY = {
    "automatic_promotion_enabled": False,
    "automatic_risk_expansion_enabled": False,
    "execution_authority": False,
    "live_broker_enabled": False,
    "model_network_enabled": False,
    "production_eligible": False,
    "real_trading_enabled": False,
    "testnet_enabled": False,
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def catalog_contract_row(dataset: DatasetDefinition) -> dict[str, object]:
    """Render the catalog row contract fields exactly like the V1 catalog API.

    Mirrors ``catalog_service._serialize_dataset`` for the fields that the
    consumer contract material includes; unrelated metadata is excluded.
    """

    return {
        "dataset_id": dataset.dataset_id,
        "schema_major": dataset.schema_major,
        "default_fields": list(dataset.default_projection),
        "filter_operators": {
            field_name: list(operators)
            for field_name, operators in dataset.filter_operators.items()
        },
        "default_order": [f"{field_name}:asc" for field_name in dataset.primary_key],
        "identity_fields": list(dataset.primary_key),
        "limits": {
            "max_page_size": dataset.max_page_size,
            "max_lookback_days": dataset.max_lookback_days,
        },
    }


def dataset_contract_material(catalog_row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Canonical consumer contract projection (operator order normalized)."""

    operators = {
        field_name: sorted(set(operators))
        for field_name, operators in catalog_row["filter_operators"].items()
    }
    return {
        "dataset_id": catalog_row["dataset_id"],
        "schema_major": catalog_row["schema_major"],
        "default_fields": list(catalog_row["default_fields"]),
        "filter_operators": operators,
        "default_order": list(catalog_row["default_order"]),
        "limits": dict(catalog_row["limits"]),
        "identity_fields": list(catalog_row["identity_fields"]),
    }


def dataset_contract_fingerprint(catalog_row: Mapping[str, Any]) -> str:
    """Stable consumer contract SHA-256 for one catalog row."""

    return _sha256(dataset_contract_material(catalog_row))


def _bar_dataset_profile(
    registry,
    dataset: DatasetDefinition,
    *,
    catalog_version: str,
) -> dict[str, object]:
    return {
        "catalog_version": catalog_version,
        "dataset_id": dataset.dataset_id,
        "schema_major": dataset.schema_major,
        "selected_fields": [
            "symbol",
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trade_count",
        ],
        "query_order": ["symbol:asc", "open_time:desc"],
        "identity_fields": ["symbol", "open_time"],
        "filter_bindings": [
            {"field": "symbol", "operator": "eq", "role": "symbol"},
            {"field": "open_time", "operator": "between", "role": "open_time_window"},
        ],
        "catalog_contract_sha256": dataset_contract_fingerprint(
            catalog_contract_row(dataset)
        ),
        "page_limit": 13,
        "max_pages": 4,
        "max_rows": 30,
    }


def _rule_dataset_profile(
    registry,
    dataset: DatasetDefinition,
    *,
    catalog_version: str,
) -> dict[str, object]:
    return {
        "catalog_version": catalog_version,
        "dataset_id": dataset.dataset_id,
        "schema_major": dataset.schema_major,
        "selected_fields": [
            "symbol",
            "status",
            "base_asset",
            "quote_asset",
            "price_filter_tick_size",
            "lot_size_step_size",
            "lot_size_min_qty",
            "min_notional",
        ],
        "query_order": ["symbol:asc"],
        "identity_fields": ["symbol"],
        "filter_bindings": [
            {"field": "symbol", "operator": "eq", "role": "symbol"},
            {"field": "status", "operator": "eq", "role": "active_status"},
        ],
        "catalog_contract_sha256": dataset_contract_fingerprint(
            catalog_contract_row(dataset)
        ),
        "page_limit": 1,
        "max_pages": 1,
        "max_rows": 1,
    }


def compile_manifest(
    registry,
    *,
    base_url: str = DEFAULT_BASE_URL,
    access_policy_id: str = DEFAULT_ACCESS_POLICY_ID,
    symbols: tuple[str, ...] = ALLOWED_SYMBOLS,
) -> dict[str, object]:
    catalog_version = public_catalog_version(registry)
    profile_symbols = []
    for symbol in symbols:
        lower = symbol.lower()
        bars = registry.resolve(f"crypto.spot.binance.{lower}.5m")
        rules = registry.resolve(f"crypto.spot.binance.{lower}.rules")
        profile_symbols.append(
            {
                "symbol": symbol,
                "bars": _bar_dataset_profile(
                    registry,
                    bars,
                    catalog_version=catalog_version,
                ),
                "instrument_rules": _rule_dataset_profile(
                    registry,
                    rules,
                    catalog_version=catalog_version,
                ),
            }
        )
    profile = {
        "mode": "tradingdatas_handoff",
        "catalog_version": catalog_version,
        "symbols": profile_symbols,
        "bar_fields": BAR_FIELDS,
        "rule_fields": RULE_FIELDS,
        "bar_close_time_semantics": "inclusive_last_millisecond",
        "bar_closed_semantics": "dataset_contract_discards_open_bars",
        "active_rule_status": "TRADING",
        "max_bar_observation_lag_seconds": 600,
        "max_rule_observation_lag_seconds": 86400,
    }
    return {
        "schema": MANIFEST_SCHEMA,
        "catalog_version": catalog_version,
        "base_url": base_url,
        "access_policy_id": access_policy_id,
        "profile": profile,
        "profile_sha256": _sha256(profile),
        "safety": SAFETY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=BINANCE_SPOT_CANARY_REGISTRY_PATH,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--access-policy-id", default=DEFAULT_ACCESS_POLICY_ID)
    args = parser.parse_args(argv)

    registry = load_dataset_registry(args.registry)
    manifest = compile_manifest(
        registry,
        base_url=args.base_url,
        access_policy_id=args.access_policy_id,
    )
    payload = _canonical_json(manifest) + b"\n"
    args.output.write_bytes(payload)
    print(
        json.dumps(
            {
                "catalog_version": manifest["catalog_version"],
                "profile_sha256": manifest["profile_sha256"],
                "manifest_sha256": hashlib.sha256(payload).hexdigest(),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
