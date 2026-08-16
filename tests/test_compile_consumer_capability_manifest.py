from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from tools.compile_consumer_capability_manifest import (
    DEFAULT_PROFILE,
    DEFAULT_REGISTRY,
    compile_manifest,
)


def test_manifest_is_deterministic_and_binds_the_exact_registry_bytes() -> None:
    first = compile_manifest(profile_path=DEFAULT_PROFILE, registry_path=DEFAULT_REGISTRY)
    second = compile_manifest(profile_path=DEFAULT_PROFILE, registry_path=DEFAULT_REGISTRY)

    assert first == second
    assert first["schema_version"] == 1
    assert first["registry_sha256"] == hashlib.sha256(DEFAULT_REGISTRY.read_bytes()).hexdigest()
    assert first["coverage"]["dataset_count"] == 191
    assert first["coverage"]["by_cadence"]["session_minute"] >= 1
    assert [item["dataset_id"] for item in first["datasets"]] == sorted(
        item["dataset_id"] for item in first["datasets"]
    )
    for item in first["datasets"]:
        read_contract = item["read_contract"]
        assert isinstance(read_contract["identity_fields"], list)
        assert read_contract["freshness_sla_seconds"] > 0
        assert set(read_contract["default_projection"]).issubset(
            read_contract["readable_fields"]
        )


def test_manifest_projects_contract_and_consumer_scope_without_runtime_claims() -> None:
    manifest = compile_manifest(profile_path=DEFAULT_PROFILE, registry_path=DEFAULT_REGISTRY)
    rt_min = next(item for item in manifest["datasets"] if item["dataset_id"] == "cn.dataset.rt_min")

    assert rt_min["cadence"] == "session_minute"
    assert rt_min["request_shape"] == "event_or_intraday_window"
    assert rt_min["read_contract"] == {
        "identity_fields": ["ts_code", "time"],
        "freshness_sla_seconds": 600,
        "readable_fields": [
            "ts_code",
            "freq",
            "time",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
        ],
        "default_projection": [
            "ts_code",
            "time",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
        ],
    }
    assert rt_min["entity_scope"] == {
        "kind": "versioned_literal_values",
        "frozen": True,
        "batch_size": 300,
        "value_count": 5963,
        "values_sha256": "70f42a1f6f211f2aa74dc46c19de5eb89009235bcfe22935cec61734cfb36b29",
    }
    assert rt_min["consumer_applicability"] == [
        {
            "consumer_id": "tradingagent",
            "access_mode": "api_read_only",
            "contract_eligible": True,
            "runtime_readiness_required": ["formal_ready"],
        }
    ]
    assert rt_min["runtime_evidence"] == {
        "authority": "onboarding_status_artifact",
        "status": "not_attested_by_contract_manifest",
    }
    assert "ready" not in rt_min
    assert "live" not in rt_min
    assert "stable" not in rt_min


def test_single_ts_code_request_template_is_not_a_frozen_universe(tmp_path: Path) -> None:
    registry_document = yaml.safe_load(DEFAULT_REGISTRY.read_bytes())
    assert isinstance(registry_document, dict)
    datasets = registry_document["datasets"]
    assert isinstance(datasets, list)
    rt_min = next(item for item in datasets if item["dataset_id"] == "cn.dataset.rt_min")
    assert isinstance(rt_min, dict)
    binding = rt_min["provider_bindings"][0]
    assert isinstance(binding, dict)
    binding["request_template"]["ts_code"] = "600000.SH"
    binding["fanout"] = {"strategy": "none"}
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump(registry_document, allow_unicode=True, sort_keys=False))

    manifest = compile_manifest(profile_path=DEFAULT_PROFILE, registry_path=registry_path)
    record = next(item for item in manifest["datasets"] if item["dataset_id"] == "cn.dataset.rt_min")

    assert record["entity_scope"] == {"kind": "none"}


def test_manifest_fails_closed_when_consumer_profile_does_not_match_registry_scope(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        """version: 1
profile_id: invalid-profile
consumers:
  - consumer_id: tradingagent
    access_mode: api_read_only
    markets: [US]
    required_scopes: [market_data]
    data_classifications: [objective_factual]
    runtime_readiness_required: [formal_ready]
"""
    )

    with pytest.raises(ValueError, match="does not match any registry dataset"):
        compile_manifest(profile_path=profile, registry_path=DEFAULT_REGISTRY)
