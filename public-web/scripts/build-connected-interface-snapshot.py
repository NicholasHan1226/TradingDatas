#!/usr/bin/env python3
"""Build a public, non-runtime interface index from the immutable registry.

The output contains contract/config state only. It intentionally excludes runtime
paths, payloads, receipts, tokens, tenant data, and any claim of current health.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"
OUTPUT_PATH = ROOT / "public-web" / "src" / "connectedInterfaceSnapshot.json"

CATEGORY_RULES = (
    ("intraday", re.compile(r"(^rt_|mins?$|_min_|minute|auction|pre_market|ft_tick)")),
    ("fundamentals", re.compile(r"income|balancesheet|cashflow|fina_|forecast|express|dividend|holder|pledge|share_float|financial")),
    ("funds-indices", re.compile(r"index|idx_|^sw_|^ths_|fund|etf|^cb_|bond|yield|shibor|libor|hibor")),
    ("derivatives", re.compile(r"^fut_|^opt_|option|warehouse|futures")),
    ("flow-positioning", re.compile(r"moneyflow|top_list|top_inst|margin|northbound|southbound|hsgt|ggt_|hm_list|hm_detail")),
    ("macro-policy", re.compile(r"gdp|cpi|ppi|pmi|money_supply|social_fin|eco_cal|monetary|customs|^bo_")),
    ("news-events", re.compile(r"news|anns|report|research|policy|_qa|irm|hot|teleplay|film|ncov|scrape_page")),
)


def classify(api_name: str) -> str:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(api_name):
            return category
    return "market-reference"


def build_snapshot() -> dict[str, object]:
    document = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    interfaces: list[dict[str, object]] = []
    for dataset in document["datasets"]:
        for binding in dataset["provider_bindings"]:
            if binding["provider"] not in {"tushare", "firecrawl"}:
                continue
            interfaces.append(
                {
                    "datasetId": dataset["dataset_id"],
                    "provider": binding["provider"],
                    "apiName": binding["api_name"],
                    "market": dataset["market"],
                    "category": classify(binding["api_name"]),
                    "cadence": dataset["cadence_class"],
                    "activation": binding["activation_state"],
                    "entitlement": binding["entitlement_state"],
                }
            )
    interfaces.sort(key=lambda item: (item["category"], item["provider"], item["apiName"]))
    return {
        "schemaVersion": 1,
        "authority": "contract_config_only",
        "warning": "Activation is registry configuration, not live collection health.",
        "registryVersion": document["version"],
        "interfaces": interfaces,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("connected interface snapshot is stale")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
