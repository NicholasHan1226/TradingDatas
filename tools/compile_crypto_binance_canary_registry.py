#!/usr/bin/env python3
"""Expand the frozen Binance canary registry from reviewed symbol templates.

The same versioned universe freezes the forty USDT symbols for both the public
Spot cohort and the public USDⓈ-M perpetual funding-rate/open-interest/
premium-index cohort; the deterministic compiler emits every dataset from its
checked-in BTCUSDT template.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "crypto_binance_spot_universe.v1.yaml"
DEFAULT_REGISTRY = ROOT / "config" / "crypto_binance_canary_registry.v1.yaml"
# The frozen cohort spans forty liquid USDT symbols; the same constant gates the
# compiler's universe validation and the Spot/USDM canary runners' cohort checks.
FROZEN_CRYPTO_SYMBOL_COUNT = 40
_SYMBOL = re.compile(r"[A-Z0-9]{2,16}USDT")

# suffix -> (dataset-id infix, alias prefix)
_DATASET_KINDS = {
    "5m": ("crypto.spot.binance.", "binance_spot."),
    "rules": ("crypto.spot.binance.", "binance_spot."),
    "book_ticker": ("crypto.spot.binance.", "binance_spot."),
    "funding_rate": ("crypto.perp.binance.", "binance_usdm."),
    "open_interest": ("crypto.perp.binance.", "binance_usdm."),
    "premium_index": ("crypto.perp.binance.", "binance_usdm."),
}
_DATASET_KIND_ORDER = (
    "5m",
    "rules",
    "book_ticker",
    "funding_rate",
    "open_interest",
    "premium_index",
)
# (suffix, binding provider) -> provider API prefix
_BINDING_API_PREFIXES = {
    ("5m", "binance_spot"): "klines_",
    ("rules", "binance_spot"): "exchangeInfo_",
    ("book_ticker", "binance_spot"): "bookTicker_",
    ("funding_rate", "binance_usdm"): "fundingRate_",
    ("funding_rate", "binance_usdm_relay"): "fundingRate_",
    ("open_interest", "binance_usdm"): "openInterestHist_",
    ("open_interest", "binance_usdm_dump"): "metricsDump_",
    ("premium_index", "binance_usdm_dump"): "premiumIndexKlinesDump_",
}


def _document(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("Crypto registry input must be an object")
    return payload


def _symbols(path: Path) -> tuple[str, ...]:
    payload = _document(path)
    if set(payload) != {
        "version",
        "selection_policy",
        "selected_at",
        "quote_asset",
        "interval",
        "minimum_history_days",
        "symbols",
    }:
        raise ValueError("Crypto universe contract keys are invalid")
    raw = payload["symbols"]
    if (
        payload["version"] != 1
        or payload["quote_asset"] != "USDT"
        or payload["interval"] != "5m"
        or not isinstance(raw, list)
        or len(raw) != FROZEN_CRYPTO_SYMBOL_COUNT
    ):
        raise ValueError("Crypto universe contract is invalid")
    symbols = tuple(raw)
    if len(set(symbols)) != len(symbols) or any(
        not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None
        for symbol in symbols
    ):
        raise ValueError("Crypto universe symbols are invalid")
    if symbols[:2] != ("BTCUSDT", "ETHUSDT"):
        raise ValueError("Crypto rollback canary symbols must remain first")
    return symbols


def _clone(template: dict[str, object], symbol: str, suffix: str) -> dict[str, object]:
    kind = _DATASET_KINDS.get(suffix)
    if kind is None:
        raise ValueError("Crypto registry template suffix is invalid")
    dataset_prefix, alias_prefix = kind
    item = deepcopy(template)
    lower = symbol.lower()
    item["dataset_id"] = f"{dataset_prefix}{lower}.{suffix}"
    item["aliases"] = [f"{alias_prefix}{lower}.{suffix}"]
    bindings = item["provider_bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("Crypto registry template binding is invalid")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("Crypto registry template binding is invalid")
        provider = binding.get("provider")
        api_prefix = _BINDING_API_PREFIXES.get((suffix, provider))
        if api_prefix is None:
            raise ValueError("Crypto registry template binding provider is invalid")
        binding["api_name"] = api_prefix + lower
        binding["read_discriminator_value"] = f"{provider}_{lower}_{suffix}"
        request = binding["request_template"]
        if not isinstance(request, dict):
            raise ValueError("Crypto registry request template is invalid")
        request["symbol"] = symbol
    return item


def compile_registry(*, universe_path: Path, registry_path: Path) -> bytes:
    symbols = _symbols(universe_path)
    registry = _document(registry_path)
    datasets = registry.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Crypto registry datasets are invalid")
    by_id = {
        item.get("dataset_id"): item for item in datasets if isinstance(item, dict)
    }
    templates: dict[str, dict[str, object]] = {}
    for suffix in _DATASET_KIND_ORDER:
        dataset_prefix = _DATASET_KINDS[suffix][0]
        template = by_id.get(f"{dataset_prefix}btcusdt.{suffix}")
        if not isinstance(template, dict):
            raise ValueError("Crypto registry templates are missing")
        templates[suffix] = template
    registry["datasets"] = [
        _clone(templates[suffix], symbol, suffix)
        for suffix in _DATASET_KIND_ORDER
        for symbol in symbols
    ]
    return yaml.safe_dump(
        registry,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    payload = compile_registry(
        universe_path=args.universe,
        registry_path=args.registry,
    )
    args.output.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
