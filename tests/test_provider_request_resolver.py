from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

from collectors.tushare import request_profile_resolver as resolver_module
from collectors.tushare.request_profile_resolver import (
    ProbeSpec,
    resolve_request_profile,
)
from tools import probe_provider_entitlements as probe


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "provider_entitlement_probes.v1.yaml"
REQUEST_PROFILES = ROOT / "config" / "tushare_request_profiles.v1.yaml"
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"


def _load_policy() -> probe.ProbePolicy:
    return probe.load_probe_policy(POLICY, DOCUMENTS, REGISTRY, REQUEST_PROFILES)


def _resolved(dataset_id: str, observed_at: str = "2025-12-31T16:00:00Z"):
    profile = _load_policy().request_profile_specs[dataset_id]
    return resolve_request_profile(profile, observed_at=observed_at)


def test_first_output_field_accepts_numeric_leading_provider_name() -> None:
    assert resolver_module._first_legal_output_field(
        {"output_fields": [{"name": "1w"}]}, "shibor"
    ) == "1w"


def test_first_output_field_rejects_names_longer_than_frozen_contract() -> None:
    with pytest.raises(ValueError, match="no legal documented output field"):
        resolver_module._first_legal_output_field(
            {"output_fields": [{"name": "a" * 65}]}, "synthetic_api"
        )


def test_input_contract_rejects_parameter_names_longer_than_64_characters() -> None:
    with pytest.raises(ValueError, match="input field names are invalid"):
        resolver_module._input_contract(
            {"input_fields": [{"name": "a" * 65, "required": "N"}]},
            "synthetic_api",
        )


def test_all_135_executable_profiles_resolve_deterministically_to_one_field():
    policy = _load_policy()
    documents = yaml.safe_load(DOCUMENTS.read_text(encoding="utf-8"))
    document_by_api = {
        contract["api_name"]: contract for contract in documents["contracts"]
    }
    legal_field = re.compile(r"[A-Za-z0-9_]{1,64}")
    profiles = tuple(
        profile
        for profile in policy.request_profile_specs.values()
        if profile.executable
    )

    assert len(profiles) == 135
    for profile in profiles:
        first = resolve_request_profile(
            profile,
            observed_at="2026-07-20T10:00:00Z",
        )
        second = resolve_request_profile(
            profile,
            observed_at="2026-07-20T10:00:00Z",
        )
        assert isinstance(first, ProbeSpec)
        assert first == second
        assert len(first.fields) == 1
        assert first.fields == (
            next(
                field["name"]
                for field in document_by_api[first.api_name]["output_fields"]
                if type(field) is dict
                and type(field.get("name")) is str
                and legal_field.fullmatch(field["name"]) is not None
            ),
        )
        assert set(first.parameter_sources) == set(first.params)
        assert first.max_response_bytes == 128 * 1024


def test_literal_and_clock_transforms_use_asia_shanghai_and_offsets():
    assert _resolved("cn.dataset.bak_daily").params == {"limit": 1, "offset": 0}
    assert _resolved("cn.dataset.adj_factor").params == {"trade_date": "20260101"}
    assert _resolved("cn.dataset.cn_cpi").params == {"m": "202601"}
    assert _resolved("cn.dataset.cn_gdp").params == {"q": "2026Q1"}
    assert _resolved("cn.dataset.fut_weekly_detail").params == {"week": "202601"}
    assert _resolved("cn.dataset.major_news").params == {
        "end_date": "2026-01-01 00:00:00",
        "start_date": "2025-12-31 23:59:00",
    }
    assert _resolved("cn.dataset.dc_index").params == {
        "idx_type": "行业板块",
        "trade_date": "20260101",
    }


def test_plan_only_profile_cannot_be_resolved():
    profile = _load_policy().request_profile_specs["cn.dataset.pledge_stat"]

    assert profile.executable is False
    with pytest.raises(ValueError, match="not executable"):
        resolve_request_profile(profile, observed_at="2026-07-20T10:00:00Z")


def test_plan_only_quarter_transform_is_validated_but_not_resolved():
    profile = _load_policy().request_profile_specs["cn.dataset.stk_rewards"]

    assert profile.executable is False
    assert profile.parameters["end_date"].transform == "last_completed_quarter_end"
    with pytest.raises(ValueError, match="not executable"):
        resolve_request_profile(profile, observed_at="2026-07-20T10:00:00Z")
