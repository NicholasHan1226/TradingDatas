from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from dataset_registry import load_dataset_registry
from tools.compile_provider_native_registry import compile_provider_native_registry
from tools.compile_tushare_runtime_contracts import (
    RuntimeContractCompilationError,
    compile_https_probe_plan,
    compile_runtime_contract_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
CADENCE_POLICY = ROOT / "config" / "tushare_cadence_policy.v1.yaml"
REQUEST_OBSERVATIONS = ROOT / "config" / "tushare_request_observations.v1.yaml"
TRANSPORT_OBSERVATIONS = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
UPSTREAM_CONTRACTS = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
PROVIDER_NATIVE_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"

# QuickSync silently returns zero rows when comma-separated ts_code values are
# combined with any filter parameter, and pledge_stat caps every response at
# 1000 rows, so the report family and pledge_stat fan out one code per request
# (see test_report_family_fanouts_are_single_code_in_generated_registry).  The
# APIs below stay at ten codes because their requests carry ts_code as the only
# provider parameter or tolerate multi-value codes with their filter.
TEN_CODE_FANOUT_APIS = {
    "cyq_chips",
    "cyq_perf",
    "stk_rewards",
    "top10_floatholders",
    "top10_holders",
}


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def _yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(_bytes(path))
    assert isinstance(document, dict)
    return document


def _sha(path: Path) -> str:
    return hashlib.sha256(_bytes(path)).hexdigest()


def _yaml_bytes(document: dict[str, object]) -> bytes:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _compile(
    *,
    documents: dict[str, object] | None = None,
    request_observations: dict[str, object] | None = None,
    transport_observations: dict[str, object] | None = None,
) -> dict[str, object]:
    document_bytes = (
        _bytes(DOCUMENTS)
        if documents is None or documents == _yaml(DOCUMENTS)
        else _yaml_bytes(documents)
    )
    transport_bytes = (
        _bytes(TRANSPORT_OBSERVATIONS)
        if transport_observations is None
        or transport_observations == _yaml(TRANSPORT_OBSERVATIONS)
        else _yaml_bytes(transport_observations)
    )
    request_document = (
        _yaml(REQUEST_OBSERVATIONS)
        if request_observations is None
        else deepcopy(request_observations)
    )
    if request_observations is None and documents is not None:
        request_document["provenance"]["official_contracts"]["sha256"] = hashlib.sha256(
            document_bytes
        ).hexdigest()
    if request_observations is None and transport_observations is not None:
        request_document["provenance"]["quicksync_interface_observations"]["sha256"] = (
            hashlib.sha256(transport_bytes).hexdigest()
        )
    request_bytes = (
        _bytes(REQUEST_OBSERVATIONS)
        if request_observations is None
        and documents is None
        and transport_observations is None
        else _yaml_bytes(request_document)
    )
    return compile_runtime_contract_bundle(
        document_bytes,
        _bytes(REVIEWED),
        _bytes(POLICY),
        _bytes(CADENCE_POLICY),
        request_observations=request_bytes,
        transport_observations=transport_bytes,
        official_contract_sha256=hashlib.sha256(document_bytes).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_bytes).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )


def _compile_plan(
    *,
    request_observations: dict[str, object] | None = None,
    dataset_field_values: list[dict[str, object]] | None = None,
    registered_contract_bundle: dict[str, object] | None = None,
) -> dict[str, object]:
    if registered_contract_bundle is None:
        # Request observations may add fanout before the frozen dump is
        # regenerated. Probe plans must bind a matching compiled bundle.
        registered_contract_bundle = _compile(
            request_observations=request_observations
        )
        if request_observations is None:
            request_observations = _yaml(REQUEST_OBSERVATIONS)
        else:
            request_observations = deepcopy(request_observations)
        request_observations["provenance"]["registered_contract_bundle"][
            "sha256"
        ] = hashlib.sha256(_yaml_bytes(registered_contract_bundle)).hexdigest()
    registered_bytes = _yaml_bytes(registered_contract_bundle)
    request_bytes = (
        _bytes(REQUEST_OBSERVATIONS)
        if request_observations is None
        else _yaml_bytes(request_observations)
    )
    return compile_https_probe_plan(
        _bytes(DOCUMENTS),
        request_bytes,
        _bytes(TRANSPORT_OBSERVATIONS),
        registered_contract_bundle=registered_bytes,
        official_contract_sha256=_sha(DOCUMENTS),
        transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
        dataset_field_values=dataset_field_values,
    )


def _entry(document: dict[str, object], api_name: str) -> dict[str, object]:
    entries = document["entries"]
    assert isinstance(entries, list)
    return next(entry for entry in entries if entry["api_name"] == api_name)


def _contract(bundle: dict[str, object], api_name: str) -> dict[str, object]:
    contracts = bundle["contracts"]
    assert isinstance(contracts, list)
    return next(item for item in contracts if item["api_name"] == api_name)


def test_request_observations_are_exactly_190_and_keep_probe_separate_from_activation() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    entries = observations["entries"]
    assert isinstance(entries, list)
    api_names = [entry["api_name"] for entry in entries]

    assert len(api_names) == 190
    assert api_names == sorted(api_names)
    assert len(set(api_names)) == 190
    assert observations["counts"] == {
        "interfaces": 190,
        "probe_executable": 135,
        "probe_blocked": 55,
        "ingest_contract_ready": 128,
        "ingest_contract_blocked": 62,
        "row_limit_ingest_contract_blocked": 15,
    }
    assert observations["counts"] == {
        "interfaces": len(entries),
        "probe_executable": sum(
            entry["probe_state"] == "executable" for entry in entries
        ),
        "probe_blocked": sum(entry["probe_state"] == "blocked" for entry in entries),
        "ingest_contract_ready": sum(
            entry["ingest_contract_state"] == "ready" for entry in entries
        ),
        "ingest_contract_blocked": sum(
            entry["ingest_contract_state"] == "blocked" for entry in entries
        ),
        "row_limit_ingest_contract_blocked": sum(
            entry["row_limit_observation"] is not None
            and "response_completeness_unresolved_at_observed_limit"
            in entry["ingest_contract_block_reasons"]
            for entry in entries
        ),
    }

    seed_apis = {
        "cb_basic",
        "dc_index",
        "etf_basic",
        "fund_basic",
        "fut_basic",
        "index_basic",
        "index_classify",
        "opt_basic",
        "stock_basic",
    }
    assert all(
        _entry(observations, api_name)["probe_state"] == "executable"
        for api_name in seed_apis
    )

    fund_nav = _entry(observations, "fund_nav")
    assert fund_nav["probe_state"] == "blocked"
    assert fund_nav["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert fund_nav["ingest_contract_state"] == "blocked"
    assert fund_nav["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]

    fund_daily = _entry(observations, "fund_daily")
    assert fund_daily["ingest_contract_state"] == "blocked"
    assert fund_daily["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert fund_daily["row_limit_observation"] == {
        "observed_count": 2000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    dc_concept_cons = _entry(observations, "dc_concept_cons")
    assert dc_concept_cons["ingest_contract_state"] == "blocked"
    assert dc_concept_cons["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert dc_concept_cons["row_limit_observation"] == {
        "observed_count": 3000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    opt_daily = _entry(observations, "opt_daily")
    assert opt_daily["ingest_contract_state"] == "blocked"
    assert opt_daily["parameters"]["exchange"] == {
        "source": "literal",
        "value": "SSE",
    }
    assert opt_daily["request_variants"] == [
        {"exchange": "SSE"},
        {"exchange": "SZSE"},
        {"exchange": "CFFEX"},
        {"exchange": "DCE"},
        {"exchange": "SHFE"},
        {"exchange": "CZCE"},
    ]
    assert opt_daily["row_limit_observation"] == {
        "observed_count": 15000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }

    news = _entry(observations, "news")
    assert news["probe_state"] == "executable"
    assert news["probe_block_reasons"] == []
    assert news["unresolved_parameter_keys"] == []
    assert news["parameters"]["src"] == {"source": "literal", "value": "sina"}
    assert news["ingest_contract_state"] == "ready"
    assert news["ingest_contract_block_reasons"] == []


def test_fund_basic_uses_documented_market_literals_as_request_anchor() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    fund_basic = _entry(observations, "fund_basic")
    assert fund_basic["request_shape"] == "snapshot_or_date_range"
    assert fund_basic["probe_state"] == "executable"
    assert fund_basic["probe_block_reasons"] == []
    assert fund_basic["ingest_contract_state"] == "ready"
    assert fund_basic["ingest_contract_block_reasons"] == []
    assert fund_basic["unresolved_parameter_keys"] == []
    assert fund_basic["parameters"] == {
        "market": {"source": "literal", "value": "E"}
    }
    assert fund_basic["request_variants"] == [
        {"market": "E"},
        {"market": "O"},
    ]
    assert "status" not in fund_basic["parameters"]
    assert "ts_code" not in fund_basic["parameters"]
    assert fund_basic["row_limit_observation"] is None

    bundle = _compile()
    contract = _contract(bundle, "fund_basic")
    assert contract["probe_state"] == "executable"
    assert contract["ingest_contract_state"] == "ready"
    assert contract["request_template"] == {"market": "E"}
    assert contract["request_variants"] == [
        {"market": "E"},
        {"market": "O"},
    ]
    assert contract["fanout"] == {"strategy": "none"}

    plan = _compile_plan()
    probe = _entry(plan, "fund_basic")
    assert probe["probe_state"] == "executable"
    assert probe["probe_block_reasons"] == []
    assert probe["params"] == {"market": "E"}
    assert probe["ingest_contract_state"] == "ready"
    assert probe["ingest_contract_block_reasons"] == []


def test_sge_basic_empty_snapshot_is_official_all_list_and_hm_list_stays_blocked() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    sge_basic = _entry(observations, "sge_basic")
    assert sge_basic["request_shape"] == "snapshot_or_date_range"
    assert sge_basic["probe_state"] == "executable"
    assert sge_basic["probe_block_reasons"] == []
    assert sge_basic["ingest_contract_state"] == "ready"
    assert sge_basic["ingest_contract_block_reasons"] == []
    assert sge_basic["unresolved_parameter_keys"] == []
    assert sge_basic["parameters"] == {}
    assert sge_basic["row_limit_observation"] is None
    assert "ts_code" not in sge_basic

    hm_list = _entry(observations, "hm_list")
    assert hm_list["request_shape"] == "snapshot_or_date_range"
    assert hm_list["probe_state"] == "blocked"
    assert hm_list["probe_block_reasons"] == ["request_anchor_unresolved"]
    assert hm_list["ingest_contract_state"] == "blocked"
    assert hm_list["ingest_contract_block_reasons"] == ["request_anchor_unresolved"]
    assert hm_list["unresolved_parameter_keys"] == []
    assert hm_list["parameters"] == {}
    assert "name" not in hm_list["parameters"]

    bundle = _compile()
    sge_contract = _contract(bundle, "sge_basic")
    assert sge_contract["probe_state"] == "executable"
    assert sge_contract["ingest_contract_state"] == "ready"
    assert sge_contract["request_template"] == {}
    assert sge_contract["request_variants"] == [{}]
    assert sge_contract["fanout"] == {"strategy": "none"}
    hm_contract = _contract(bundle, "hm_list")
    assert hm_contract["probe_state"] == "blocked"
    assert hm_contract["ingest_contract_state"] == "blocked"
    assert hm_contract["request_template"] == {}

    plan = _compile_plan()
    sge_probe = _entry(plan, "sge_basic")
    assert sge_probe["probe_state"] == "executable"
    assert sge_probe["params"] == {}
    assert sge_probe["ingest_contract_state"] == "ready"
    hm_probe = _entry(plan, "hm_list")
    assert hm_probe["probe_state"] == "blocked"
    assert hm_probe["params"] == {}
    assert hm_probe["ingest_contract_state"] == "blocked"


def test_bse_mapping_empty_snapshot_does_not_guess_codes() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    bse_mapping = _entry(observations, "bse_mapping")
    assert bse_mapping["request_shape"] == "snapshot_or_date_range"
    assert bse_mapping["probe_state"] == "executable"
    assert bse_mapping["probe_block_reasons"] == []
    assert bse_mapping["ingest_contract_state"] == "ready"
    assert bse_mapping["ingest_contract_block_reasons"] == []
    assert bse_mapping["unresolved_parameter_keys"] == []
    assert bse_mapping["parameters"] == {}
    assert bse_mapping["row_limit_observation"] is None
    assert "o_code" not in bse_mapping["parameters"]
    assert "n_code" not in bse_mapping["parameters"]

    ths_index = _entry(observations, "ths_index")
    assert ths_index["probe_state"] == "blocked"
    assert ths_index["probe_block_reasons"] == ["request_anchor_unresolved"]
    assert "exchange" not in ths_index["parameters"]

    index_basic = _entry(observations, "index_basic")
    assert index_basic["probe_state"] == "executable"
    assert index_basic["ingest_contract_state"] == "blocked"
    assert index_basic["parameters"] == {"market": {"source": "literal", "value": "SSE"}}
    assert index_basic["request_variants"] == [
        {"market": "MSCI"},
        {"market": "CSI"},
        {"market": "SSE"},
        {"market": "SZSE"},
        {"market": "CICC"},
        {"market": "SW"},
        {"market": "OTH"},
    ]
    assert index_basic["row_limit_observation"] == {
        "observed_count": 6000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }

    bc_otcqt = _entry(observations, "bc_otcqt")
    assert bc_otcqt["probe_state"] == "executable"
    assert bc_otcqt["ingest_contract_state"] == "blocked"
    assert list(bc_otcqt["parameters"]) == ["trade_date"]
    assert "ts_code" not in bc_otcqt["parameters"]
    assert "bank" not in bc_otcqt["parameters"]

    bundle = _compile()
    contract = _contract(bundle, "bse_mapping")
    assert contract["probe_state"] == "executable"
    assert contract["ingest_contract_state"] == "ready"
    assert contract["request_template"] == {}
    assert contract["request_variants"] == [{}]
    assert contract["fanout"] == {"strategy": "none"}
    index_contract = _contract(bundle, "index_basic")
    assert index_contract["ingest_contract_state"] == "blocked"
    assert index_contract["request_template"] == {"market": "SSE"}
    assert index_contract["request_variants"] == [
        {"market": "MSCI"},
        {"market": "CSI"},
        {"market": "SSE"},
        {"market": "SZSE"},
        {"market": "CICC"},
        {"market": "SW"},
        {"market": "OTH"},
    ]

    plan = _compile_plan()
    probe = _entry(plan, "bse_mapping")
    assert probe["probe_state"] == "executable"
    assert probe["params"] == {}
    assert probe["ingest_contract_state"] == "ready"


def test_index_weekly_uses_index_basic_seed_fanout_without_clearing_completeness() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    index_weekly = _entry(observations, "index_weekly")
    assert index_weekly["request_shape"] == "entity_fanout"
    assert index_weekly["probe_state"] == "blocked"
    assert index_weekly["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert index_weekly["ingest_contract_state"] == "blocked"
    assert index_weekly["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert index_weekly["row_limit_observation"] == {
        "observed_count": 1000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert index_weekly["parameters"]["ts_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.index_basic",
        "field": "ts_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert index_weekly["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert index_weekly["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }

    bundle = _compile()
    contract = _contract(bundle, "index_weekly")
    assert contract["ingest_contract_state"] == "blocked"
    assert contract["request_template"] == {"trade_date": "${window.trade_date}"}
    assert contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.index_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert "response_completeness_unresolved_at_observed_limit" in contract[
        "ingest_contract_block_reasons"
    ]

    seed = {
        "dataset_id": "cn.dataset.index_basic",
        "field": "ts_code",
        "value": "000300.SH",
        "receipt_id": "receipt-index-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[seed],
    )
    probe = _entry(plan, "index_weekly")
    assert probe["probe_state"] == "executable"
    assert probe["params"] == {
        "trade_date": "20260721",
        "ts_code": "000300.SH",
    }
    assert probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in probe[
        "ingest_contract_block_reasons"
    ]


def test_ci_index_member_and_index_member_all_use_security_master_fanout_without_clearing_completeness() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    expected = {
        "ci_index_member": 5000,
        "index_member_all": 2000,
    }
    for api_name, observed_count in expected.items():
        entry = _entry(observations, api_name)
        assert entry["request_shape"] == "entity_fanout"
        assert entry["probe_state"] == "blocked"
        assert entry["probe_block_reasons"] == [
            "dependency_seed_receipt_unresolved"
        ]
        assert entry["ingest_contract_state"] == "blocked"
        assert entry["ingest_contract_block_reasons"] == [
            "dependency_seed_receipt_unresolved",
            "response_completeness_unresolved_at_observed_limit",
        ]
        assert entry["row_limit_observation"] == {
            "observed_count": observed_count,
            "detection": "observed_count_equals_round_provider_style_boundary",
            "reject_at_limit": True,
        }
        assert entry["parameters"]["is_new"] == {"source": "literal", "value": "Y"}
        assert entry["parameters"]["ts_code"] == {
            "source": "dataset_field",
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "requires_fresh_success_receipt": True,
            "batch_size": 1,
        }
        assert "l1_code" not in entry["parameters"]
        assert "l2_code" not in entry["parameters"]
        assert "l3_code" not in entry["parameters"]
        dumped = yaml.safe_dump(entry)
        assert "cn.dataset.index_member" not in dumped
        assert dumped.count("index_member") == 1
        assert entry["resumable_fanout"] == {
            "cursor_contract_version": 2,
            "max_batches_per_run": 1,
        }

    bundle = _compile()
    seed = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "2.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[seed],
    )
    for api_name in expected:
        contract = _contract(bundle, api_name)
        assert contract["ingest_contract_state"] == "blocked"
        assert contract["request_template"] == {"is_new": "Y"}
        assert contract["fanout"] == {
            "strategy": "dataset_field",
            "parameter": "ts_code",
            "source_dataset_id": "cn.equity.security_master",
            "source_field": "ts_code",
            "batch_size": 1,
        }
        assert "response_completeness_unresolved_at_observed_limit" in contract[
            "ingest_contract_block_reasons"
        ]
        probe = _entry(plan, api_name)
        assert probe["probe_state"] == "executable"
        assert probe["params"] == {"is_new": "Y", "ts_code": "600000.SH"}
        assert probe["ingest_contract_state"] == "blocked"
        assert "response_completeness_unresolved_at_observed_limit" in probe[
            "ingest_contract_block_reasons"
        ]


def test_fund_nav_uses_fund_basic_seed_fanout_without_clearing_completeness() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    fund_nav = _entry(observations, "fund_nav")
    assert fund_nav["request_shape"] == "entity_fanout"
    assert fund_nav["probe_state"] == "blocked"
    assert fund_nav["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert fund_nav["ingest_contract_state"] == "blocked"
    assert fund_nav["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert fund_nav["row_limit_observation"] == {
        "observed_count": 6000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert fund_nav["parameters"]["ts_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.fund_basic",
        "field": "ts_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert fund_nav["parameters"]["nav_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert "etf_basic" not in yaml.safe_dump(fund_nav)
    assert fund_nav["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }

    bundle = _compile()
    contract = _contract(bundle, "fund_nav")
    assert contract["ingest_contract_state"] == "blocked"
    assert contract["request_template"] == {"nav_date": "${window.nav_date}"}
    assert contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.fund_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert contract["resumable_fanout"] == fund_nav["resumable_fanout"]
    assert "response_completeness_unresolved_at_observed_limit" in contract[
        "ingest_contract_block_reasons"
    ]

    seed = {
        "dataset_id": "cn.dataset.fund_basic",
        "field": "ts_code",
        "value": "510300.OF",
        "receipt_id": "receipt-fund-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[seed],
    )
    probe = _entry(plan, "fund_nav")
    assert probe["probe_state"] == "executable"
    assert probe["params"] == {
        "nav_date": "20260721",
        "ts_code": "510300.OF",
    }
    assert probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in probe[
        "ingest_contract_block_reasons"
    ]


def test_fund_daily_and_dc_concept_cons_use_existing_seed_fanout_without_clearing_completeness() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    fund_daily = _entry(observations, "fund_daily")
    assert fund_daily["request_shape"] == "entity_fanout"
    assert fund_daily["probe_state"] == "blocked"
    assert fund_daily["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert fund_daily["parameters"]["ts_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.etf_basic",
        "field": "ts_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert fund_daily["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert "fund_basic" not in yaml.safe_dump(fund_daily)
    assert fund_daily["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }

    dc_concept_cons = _entry(observations, "dc_concept_cons")
    assert dc_concept_cons["request_shape"] == "entity_fanout"
    assert dc_concept_cons["parameters"]["theme_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.dc_concept",
        "field": "theme_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert dc_concept_cons["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert dc_concept_cons["resumable_fanout"] == fund_daily["resumable_fanout"]

    bundle = _compile()
    fund_contract = _contract(bundle, "fund_daily")
    assert fund_contract["ingest_contract_state"] == "blocked"
    assert fund_contract["request_template"] == {"trade_date": "${window.trade_date}"}
    assert fund_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.etf_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert fund_contract["resumable_fanout"] == fund_daily["resumable_fanout"]
    dc_contract = _contract(bundle, "dc_concept_cons")
    assert dc_contract["ingest_contract_state"] == "blocked"
    assert dc_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "theme_code",
        "source_dataset_id": "cn.dataset.dc_concept",
        "source_field": "theme_code",
        "batch_size": 1,
    }

    etf_seed = {
        "dataset_id": "cn.dataset.etf_basic",
        "field": "ts_code",
        "value": "510300.SH",
        "receipt_id": "receipt-etf-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    theme_seed = {
        "dataset_id": "cn.dataset.dc_concept",
        "field": "theme_code",
        "value": "000001.DC",
        "receipt_id": "receipt-dc-concept-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "2.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[etf_seed, theme_seed],
    )
    fund_probe = _entry(plan, "fund_daily")
    assert fund_probe["probe_state"] == "executable"
    assert fund_probe["params"] == {
        "trade_date": "20260721",
        "ts_code": "510300.SH",
    }
    assert fund_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in fund_probe[
        "ingest_contract_block_reasons"
    ]
    theme_probe = _entry(plan, "dc_concept_cons")
    assert theme_probe["probe_state"] == "executable"
    assert theme_probe["params"] == {
        "theme_code": "000001.DC",
        "trade_date": "20260721",
    }
    assert theme_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in theme_probe[
        "ingest_contract_block_reasons"
    ]


def test_etf_sz_cons_and_dc_member_use_existing_seed_fanout_without_clearing_completeness() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    etf_sz_cons = _entry(observations, "etf_sz_cons")
    assert etf_sz_cons["request_shape"] == "entity_fanout"
    assert etf_sz_cons["probe_state"] == "blocked"
    assert etf_sz_cons["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert etf_sz_cons["ingest_contract_state"] == "blocked"
    assert etf_sz_cons["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert etf_sz_cons["row_limit_observation"] == {
        "observed_count": 3000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert etf_sz_cons["parameters"]["ts_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.etf_basic",
        "field": "ts_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert etf_sz_cons["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert "source_equals" not in etf_sz_cons["parameters"]["ts_code"]
    assert etf_sz_cons["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }

    dc_member = _entry(observations, "dc_member")
    assert dc_member["request_shape"] == "entity_fanout"
    assert dc_member["probe_state"] == "blocked"
    assert dc_member["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert dc_member["ingest_contract_state"] == "blocked"
    assert dc_member["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert dc_member["row_limit_observation"] == {
        "observed_count": 5000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert dc_member["parameters"]["ts_code"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.dc_index",
        "field": "ts_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert dc_member["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert dc_member["resumable_fanout"] == etf_sz_cons["resumable_fanout"]

    kpl_concept_cons = _entry(observations, "kpl_concept_cons")
    assert kpl_concept_cons["request_shape"] == "snapshot_or_date_range"
    assert kpl_concept_cons["probe_state"] == "executable"
    assert kpl_concept_cons["parameters"] == {
        "trade_date": {
            "source": "run_clock",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        }
    }
    assert kpl_concept_cons["ingest_contract_state"] == "blocked"
    assert kpl_concept_cons["ingest_contract_block_reasons"] == [
        "response_completeness_unresolved_at_observed_limit"
    ]
    dumped = yaml.safe_dump(kpl_concept_cons)
    assert "cn.dataset.kpl_concept" not in dumped
    assert "dataset_field" not in dumped

    bundle = _compile()
    etf_contract = _contract(bundle, "etf_sz_cons")
    assert etf_contract["ingest_contract_state"] == "blocked"
    assert etf_contract["request_template"] == {"trade_date": "${window.trade_date}"}
    assert etf_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.etf_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert etf_contract["resumable_fanout"] == etf_sz_cons["resumable_fanout"]
    dc_contract = _contract(bundle, "dc_member")
    assert dc_contract["ingest_contract_state"] == "blocked"
    assert dc_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.dc_index",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    kpl_contract = _contract(bundle, "kpl_concept_cons")
    assert kpl_contract["fanout"] == {"strategy": "none"}
    assert kpl_contract["ingest_contract_state"] == "blocked"

    etf_seed = {
        "dataset_id": "cn.dataset.etf_basic",
        "field": "ts_code",
        "value": "159915.SZ",
        "receipt_id": "receipt-etf-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    dc_index_seed = {
        "dataset_id": "cn.dataset.dc_index",
        "field": "ts_code",
        "value": "BK0473.DC",
        "receipt_id": "receipt-dc-index-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[etf_seed, dc_index_seed],
    )
    etf_probe = _entry(plan, "etf_sz_cons")
    assert etf_probe["probe_state"] == "executable"
    assert etf_probe["params"] == {
        "trade_date": "20260721",
        "ts_code": "159915.SZ",
    }
    assert etf_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in etf_probe[
        "ingest_contract_block_reasons"
    ]
    dc_probe = _entry(plan, "dc_member")
    assert dc_probe["probe_state"] == "executable"
    assert dc_probe["params"] == {
        "trade_date": "20260721",
        "ts_code": "BK0473.DC",
    }
    assert dc_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in dc_probe[
        "ingest_contract_block_reasons"
    ]
    kpl_probe = _entry(plan, "kpl_concept_cons")
    assert kpl_probe["probe_state"] == "executable"
    assert kpl_probe["params"] == {"trade_date": "20260721"}
    assert kpl_probe["ingest_contract_state"] == "blocked"
    assert kpl_probe["ingest_contract_block_reasons"] == [
        "response_completeness_unresolved_at_observed_limit"
    ]


def test_fut_holding_and_fut_wsr_use_existing_seed_fanout_without_clearing_completeness() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    fut_holding = _entry(observations, "fut_holding")
    assert fut_holding["request_shape"] == "entity_fanout"
    assert fut_holding["probe_state"] == "blocked"
    assert fut_holding["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert fut_holding["ingest_contract_state"] == "blocked"
    assert fut_holding["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert fut_holding["row_limit_observation"] == {
        "observed_count": 2000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert fut_holding["parameters"]["symbol"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.fut_basic",
        "field": "symbol",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert fut_holding["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert "ts_code" not in fut_holding["parameters"]
    assert fut_holding["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }

    fut_wsr = _entry(observations, "fut_wsr")
    assert fut_wsr["request_shape"] == "entity_fanout"
    assert fut_wsr["probe_state"] == "blocked"
    assert fut_wsr["probe_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert fut_wsr["ingest_contract_state"] == "blocked"
    assert fut_wsr["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]
    assert fut_wsr["row_limit_observation"] == {
        "observed_count": 1000,
        "detection": "observed_count_equals_round_provider_style_boundary",
        "reject_at_limit": True,
    }
    assert fut_wsr["parameters"]["symbol"] == {
        "source": "dataset_field",
        "dataset_id": "cn.dataset.fut_basic",
        "field": "fut_code",
        "requires_fresh_success_receipt": True,
        "batch_size": 1,
    }
    assert fut_wsr["parameters"]["trade_date"] == {
        "source": "run_clock",
        "transform": "yyyymmdd",
        "offset_seconds": 0,
    }
    assert fut_wsr["resumable_fanout"] == fut_holding["resumable_fanout"]

    bundle = _compile()
    holding_contract = _contract(bundle, "fut_holding")
    assert holding_contract["ingest_contract_state"] == "blocked"
    assert holding_contract["request_template"] == {
        "trade_date": "${window.trade_date}"
    }
    assert holding_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "symbol",
        "source_dataset_id": "cn.dataset.fut_basic",
        "source_field": "symbol",
        "batch_size": 1,
    }
    assert holding_contract["resumable_fanout"] == fut_holding["resumable_fanout"]
    wsr_contract = _contract(bundle, "fut_wsr")
    assert wsr_contract["ingest_contract_state"] == "blocked"
    assert wsr_contract["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "symbol",
        "source_dataset_id": "cn.dataset.fut_basic",
        "source_field": "fut_code",
        "batch_size": 1,
    }

    symbol_seed = {
        "dataset_id": "cn.dataset.fut_basic",
        "field": "symbol",
        "value": "cu2509",
        "receipt_id": "receipt-fut-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    fut_code_seed = {
        "dataset_id": "cn.dataset.fut_basic",
        "field": "fut_code",
        "value": "CU",
        "receipt_id": "receipt-fut-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(bundle)
    ).hexdigest()
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
        dataset_field_values=[symbol_seed, fut_code_seed],
    )
    holding_probe = _entry(plan, "fut_holding")
    assert holding_probe["probe_state"] == "executable"
    assert holding_probe["params"] == {
        "symbol": "cu2509",
        "trade_date": "20260721",
    }
    assert holding_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in holding_probe[
        "ingest_contract_block_reasons"
    ]
    wsr_probe = _entry(plan, "fut_wsr")
    assert wsr_probe["probe_state"] == "executable"
    assert wsr_probe["params"] == {
        "symbol": "CU",
        "trade_date": "20260721",
    }
    assert wsr_probe["ingest_contract_state"] == "blocked"
    assert "response_completeness_unresolved_at_observed_limit" in wsr_probe[
        "ingest_contract_block_reasons"
    ]


def test_probe_only_limit_offset_replaced_by_reusable_date_windows() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    expected = {
        "bak_daily": (
            "trade_date",
            {
                "source": "run_clock",
                "transform": "yyyymmdd",
                "offset_seconds": 0,
            },
        ),
        "fund_adj": (
            "trade_date",
            {
                "source": "run_clock",
                "transform": "yyyymmdd",
                "offset_seconds": 0,
            },
        ),
        "fund_manager": (
            "ann_date",
            {
                "source": "run_clock",
                "transform": "yyyymmdd",
                "offset_seconds": 0,
            },
        ),
    }

    for api_name, (window_key, window) in expected.items():
        entry = _entry(observations, api_name)
        assert entry["request_shape"] == "snapshot_or_date_range"
        assert entry["probe_state"] == "executable"
        assert entry["ingest_contract_state"] == "blocked"
        assert entry["ingest_contract_block_reasons"] == [
            "response_completeness_unresolved_at_observed_limit"
        ]
        assert entry["parameters"] == {window_key: window}
        assert "limit" not in entry["parameters"]
        assert "offset" not in entry["parameters"]
        assert entry.get("pagination_max_pages", 1) == 1
        assert entry["row_limit_observation"] is None

    bundle = _compile()
    compiled = {
        "bak_daily": ("trade_date", "${window.trade_date}"),
        "fund_adj": ("trade_date", "${window.trade_date}"),
        "fund_manager": ("ann_date", "${window.ann_date}"),
    }
    for api_name, (window_key, placeholder) in compiled.items():
        contract = _contract(bundle, api_name)
        assert contract["ingest_contract_state"] == "blocked"
        assert contract["request_template"] == {window_key: placeholder}
        assert contract["pagination"] == {"strategy": "none"}
        assert contract["request_window_policy"] is not None
        assert contract["request_window_policy"]["formats"][window_key] == "yyyymmdd"


def test_reviewed_active_requests_are_frozen_without_guessing() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)

    assert _entry(observations, "daily")["parameters"] == {
        "trade_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        }
    }
    assert _entry(observations, "stock_basic")["parameters"] == {
        "list_status": {"source": "literal", "value": "L"}
    }
    assert _entry(observations, "stock_basic")["request_variants"] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert _entry(observations, "trade_cal")["parameters"] == {
        "end_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        },
        "exchange": {"source": "literal", "value": "SSE"},
        "start_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        },
    }
    assert _entry(observations, "rt_min")["request_shape"] == "event_or_intraday_window"
    assert _entry(observations, "rt_min")["parameters"] == {
        "freq": {"source": "literal", "value": "5MIN"},
        "ts_code": {"source": "literal", "value": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"},
    }
    observation_fanout = _entry(observations, "rt_min")["fanout"]
    assert observation_fanout["parameter"] == "ts_code"
    assert observation_fanout["batch_size"] == 300
    assert len(observation_fanout["values"]) == 5963
    assert observation_fanout["values"] == sorted(observation_fanout["values"])
    assert _entry(observations, "rt_min")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }

    bundle = _compile()
    assert _contract(bundle, "daily")["request_template"] == {
        "trade_date": "${window.trade_date}"
    }
    assert _contract(bundle, "stock_basic")["request_variants"] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert _contract(bundle, "trade_cal")["request_template"] == {
        "end_date": "${window.end_date}",
        "exchange": "SSE",
        "start_date": "${window.start_date}",
    }
    rt_min = _contract(bundle, "rt_min")
    assert rt_min["request_template"] == {"freq": "5MIN", "ts_code": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"}
    assert rt_min["request_shape"] == "event_or_intraday_window"
    assert rt_min["fanout"]["strategy"] == "literal_values"
    assert rt_min["fanout"]["parameter"] == "ts_code"
    assert rt_min["fanout"]["batch_size"] == 300
    assert len(rt_min["fanout"]["values"]) == 5963
    assert rt_min["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }
    assert rt_min["primary_key"] == ["ts_code", "time"]
    assert rt_min["default_projection"] == [
        "ts_code",
        "time",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ]


def test_rt_min_registry_uses_the_exact_frozen_full_universe() -> None:
    registry = _yaml(PROVIDER_NATIVE_REGISTRY)
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    dataset = next(item for item in datasets if item["dataset_id"] == "cn.dataset.rt_min")
    bindings = dataset["provider_bindings"]
    assert isinstance(bindings, list) and len(bindings) == 1
    binding = bindings[0]

    assert binding["request_shape"] == "event_or_intraday_window"
    fanout = binding["fanout"]
    assert fanout["strategy"] == "literal_values"
    assert fanout["parameter"] == "ts_code"
    assert fanout["batch_size"] == 300
    symbols = fanout["values"]
    assert isinstance(symbols, list)
    official_symbols = binding["request_template"]["ts_code"].split(",")
    assert len(official_symbols) == len(set(official_symbols)) == 30
    assert set(official_symbols).issubset(symbols)
    assert len(set(symbols) - set(official_symbols)) == 5933
    assert len(symbols) == len(set(symbols)) == 5963
    assert binding["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }
    assert all(re.fullmatch(r"(?:\d{6}|T\d{5,6}|TS\d{4})\.(?:SZ|SH|BJ)", symbol) for symbol in symbols)


def test_rt_min_observation_fanout_mismatch_fails_closed() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "rt_min")["fanout"]["parameter"] = "unknown"

    with pytest.raises(RuntimeContractCompilationError, match="mapped provider parameter"):
        _compile(request_observations=observations)


def test_literal_values_dimension_fanout_compiles_without_a_seed_dataset() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)

    bundle = _compile(request_observations=observations)

    assert _contract(bundle, "major_news")["fanout"] == {
        "strategy": "literal_values",
        "parameter": "src",
        "values": [
            "新华网",
            "凤凰财经",
            "同花顺",
            "新浪财经",
            "华尔街见闻",
            "中证网",
            "财新网",
            "第一财经",
            "财联社",
        ],
        "batch_size": 1,
    }
    assert _contract(bundle, "major_news")["budgets"]["max_rows_per_attempt"] == 2000
    assert (
        _contract(bundle, "major_news")["budgets"]["max_payload_bytes_per_row"]
        == 131_072
    )

    observations["provenance"]["registered_contract_bundle"]["sha256"] = (
        hashlib.sha256(_yaml_bytes(bundle)).hexdigest()
    )
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
    )
    major_news_probe = _entry(plan, "major_news")
    assert major_news_probe["probe_state"] == "executable"
    assert major_news_probe["params"]["src"] == "新华网"


def test_catalog_only_requests_compile_into_the_existing_generic_data_plane() -> None:
    bundle = _compile()
    adj_factor = _contract(bundle, "adj_factor")
    assert adj_factor["probe_state"] == "executable"
    assert adj_factor["ingest_contract_state"] == "ready"
    assert adj_factor["request_shape"] == "snapshot_or_date_range"
    assert adj_factor["request_template"] == {"trade_date": "${window.trade_date}"}
    assert adj_factor["request_window_policy"] == {
        "required_keys": ["trade_date"],
        "formats": {"trade_date": "yyyymmdd"},
        "range_start_key": "trade_date",
        "range_end_key": "trade_date",
        "max_span_days": 1,
    }

    fund_nav = _contract(bundle, "fund_nav")
    assert fund_nav["probe_state"] == "blocked"
    assert fund_nav["ingest_contract_state"] == "blocked"
    assert fund_nav["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved",
        "response_completeness_unresolved_at_observed_limit",
    ]

    news = _contract(bundle, "news")
    assert news["probe_state"] == "executable"
    assert news["request_template"] == {
        "end_date": "${window.end_date}",
        "src": "sina",
        "start_date": "${window.start_date}",
    }
    assert news["request_variants"] == [{}]


def _set_row_limit_ready(
    observations: dict[str, object],
    api_name: str,
    *,
    reject_at_limit: bool,
) -> None:
    entry = _entry(observations, api_name)
    row_limit = entry["row_limit_observation"]
    assert isinstance(row_limit, dict)
    row_limit["reject_at_limit"] = reject_at_limit
    had_completeness = (
        "response_completeness_unresolved_at_observed_limit"
        in entry["ingest_contract_block_reasons"]
    )
    entry["ingest_contract_block_reasons"] = [
        reason
        for reason in entry["ingest_contract_block_reasons"]
        if reason != "response_completeness_unresolved_at_observed_limit"
    ]
    if not entry["ingest_contract_block_reasons"]:
        was_blocked = entry["ingest_contract_state"] == "blocked"
        entry["ingest_contract_state"] = "ready"
        if was_blocked:
            counts = observations["counts"]
            assert isinstance(counts, dict)
            counts["ingest_contract_ready"] = int(counts["ingest_contract_ready"]) + 1
            counts["ingest_contract_blocked"] = int(counts["ingest_contract_blocked"]) - 1
    if had_completeness:
        counts = observations["counts"]
        assert isinstance(counts, dict)
        counts["row_limit_ingest_contract_blocked"] = (
            int(counts["row_limit_ingest_contract_blocked"]) - 1
        )


def test_row_limit_under_hard_budget_allows_finite_coverage_without_activation_block() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    for api_name, expected_count in (("fund_daily", 2000), ("dc_concept_cons", 3000)):
        entry = _entry(observations, api_name)
        row_limit = entry["row_limit_observation"]
        assert isinstance(row_limit, dict)
        assert row_limit["observed_count"] == expected_count
        assert row_limit["observed_count"] < 10000
        _set_row_limit_ready(observations, api_name, reject_at_limit=False)

    bundle = _compile(request_observations=observations)
    for api_name in ("fund_daily", "dc_concept_cons"):
        contract = _contract(bundle, api_name)
        assert contract["ingest_contract_state"] == "blocked"
        assert contract["ingest_contract_block_reasons"] == [
            "dependency_seed_receipt_unresolved"
        ]
        assert contract["budgets"]["max_rows_per_attempt"] == 10000
        assert contract["request_template"] == {"trade_date": "${window.trade_date}"}


def test_row_limit_under_hard_budget_keeps_explicit_reject_at_limit_without_forcing_block() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    row_limit = _entry(observations, "fund_daily")["row_limit_observation"]
    assert isinstance(row_limit, dict)
    assert row_limit["reject_at_limit"] is True
    _set_row_limit_ready(observations, "fund_daily", reject_at_limit=True)

    bundle = _compile(request_observations=observations)
    contract = _contract(bundle, "fund_daily")
    assert contract["ingest_contract_state"] == "blocked"
    assert contract["ingest_contract_block_reasons"] == [
        "dependency_seed_receipt_unresolved"
    ]
    assert contract["budgets"]["max_rows_per_attempt"] == 10000


def test_row_limit_over_hard_budget_still_requires_activation_block() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    entry = _entry(observations, "opt_daily")
    row_limit = entry["row_limit_observation"]
    assert isinstance(row_limit, dict)
    assert row_limit["observed_count"] == 15000
    entry["ingest_contract_state"] = "ready"
    entry["ingest_contract_block_reasons"] = []
    counts = observations["counts"]
    assert isinstance(counts, dict)
    counts["ingest_contract_ready"] = 128
    counts["ingest_contract_blocked"] = 62
    counts["row_limit_ingest_contract_blocked"] = 14

    with pytest.raises(
        RuntimeContractCompilationError,
        match="over hard budget must block activation",
    ):
        _compile(request_observations=observations)


def test_row_limit_over_hard_budget_cannot_clear_reject_at_limit() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    row_limit = _entry(observations, "opt_daily")["row_limit_observation"]
    assert isinstance(row_limit, dict)
    row_limit["reject_at_limit"] = False

    with pytest.raises(
        RuntimeContractCompilationError,
        match="over hard budget must set reject_at_limit",
    ):
        _compile(request_observations=observations)


def test_row_limit_reject_at_limit_must_be_boolean() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    row_limit = _entry(observations, "fund_daily")["row_limit_observation"]
    assert isinstance(row_limit, dict)
    row_limit["reject_at_limit"] = "true"

    with pytest.raises(
        RuntimeContractCompilationError, match="reject_at_limit must be a boolean"
    ):
        _compile(request_observations=observations)


def test_dataset_field_batch_size_defaults_to_one_and_compiles_explicit_values() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    bundle = _compile()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=_yaml(TRANSPORT_OBSERVATIONS),
    )
    runtime_bindings = {
        binding["api_name"]: binding
        for dataset in registry["datasets"]
        for binding in dataset["provider_bindings"]
    }

    for api_name in TEN_CODE_FANOUT_APIS:
        declaration = _entry(observations, api_name)["parameters"]["ts_code"]
        assert declaration["batch_size"] == 10
        assert _contract(bundle, api_name)["fanout"]["batch_size"] == 10
        assert runtime_bindings[api_name]["fanout"]["batch_size"] == 10

    # rt_min_daily carries an explicit five-code batch: one session holds
    # ~241 one-minute bars per code, so ten codes overflow any feasible
    # max_rows_per_attempt late in the session (scan-envelope fix).
    minute_declaration = _entry(observations, "rt_min_daily")["parameters"][
        "ts_code"
    ]
    assert minute_declaration["batch_size"] == 5
    assert _contract(bundle, "rt_min_daily")["fanout"]["batch_size"] == 5
    assert runtime_bindings["rt_min_daily"]["fanout"]["batch_size"] == 5

    report_family = (
        "balancesheet",
        "cashflow",
        "express",
        "fina_audit",
        "fina_indicator",
        "income",
        "pledge_stat",
    )
    # cashflow / express / fina_audit left the ann_date continuation:
    # official ts_code is independently required (not 二选一), and date +
    # 1-code fanout stayed empty.  Empty ≠ success.  Undated ts_code-only
    # matches pledge_stat.
    undated_report_family = {"cashflow", "express", "fina_audit", "pledge_stat"}
    for api_name in report_family:
        expected_progress = {"cursor_contract_version": 2, "max_batches_per_run": 1}
        if api_name not in undated_report_family:
            expected_progress.update(
                progress_mode="partition_continuation",
                continuation_max_age_days=31,
                partition_date_field="ann_date",
            )
        assert _entry(observations, api_name)["resumable_fanout"] == expected_progress
        assert _entry(observations, api_name)["parameters"]["ts_code"]["batch_size"] == 1
        assert _contract(bundle, api_name)["cadence_class"] == "event"
        assert _contract(bundle, api_name)["resumable_fanout"] == expected_progress
        assert _contract(bundle, api_name)["fanout"]["batch_size"] == 1
        if api_name in undated_report_family:
            assert "ann_date" not in _entry(observations, api_name)["parameters"]
            assert _contract(bundle, api_name)["request_template"] == {}
            assert _contract(bundle, api_name)["request_window_policy"] is None
    assert _entry(observations, "cb_share")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
        "progress_mode": "partition_continuation",
        "continuation_max_age_days": 31,
        "partition_date_field": "publish_date",
    }
    assert _contract(bundle, "cb_share")["cadence_class"] == "event"
    assert _contract(bundle, "cb_basic")["cadence_class"] == "daily_reference"
    assert "resumable_fanout" not in _contract(bundle, "cb_basic")
    # Regular forecast is official single-stock history; forecast_vip is the
    # all-names date/period API and is not this transport.  GZ ac458530
    # ann_date-only returned provider_error / 0 rows.  Empty ≠ success.
    # ts_code-only fanout matches pledge_stat / cashflow / express / fina_audit.
    assert _contract(bundle, "forecast")["cadence_class"] == "event"
    assert _contract(bundle, "forecast")["request_template"] == {}
    assert _contract(bundle, "forecast")["request_window_policy"] is None
    assert _contract(bundle, "forecast")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.equity.security_master",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "forecast")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    assert "ann_date" not in _entry(observations, "forecast")["parameters"]
    assert "ts_code" in _entry(observations, "forecast")["parameters"]
    # fina_mainbz: QuickSync has no ann_date.  Drop run-clock start/end and
    # type=P; ts_code-only single-code history matches pledge_stat.
    assert _contract(bundle, "fina_mainbz")["cadence_class"] == "event"
    assert _contract(bundle, "fina_mainbz")["request_template"] == {}
    assert _contract(bundle, "fina_mainbz")["request_window_policy"] is None
    assert _contract(bundle, "fina_mainbz")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.equity.security_master",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "fina_mainbz")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    assert "type" not in _entry(observations, "fina_mainbz")["parameters"]
    assert "start_date" not in _entry(observations, "fina_mainbz")["parameters"]
    assert "end_date" not in _entry(observations, "fina_mainbz")["parameters"]
    assert _contract(bundle, "pledge_detail")["cadence_class"] == "event"
    assert _contract(bundle, "pledge_detail")["request_template"] == {}
    assert _contract(bundle, "pledge_detail")["request_window_policy"] is None
    assert _contract(bundle, "pledge_detail")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.equity.security_master",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "pledge_detail")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    assert "ann_date" not in _entry(observations, "pledge_detail")["parameters"]
    assert "ts_code" in _entry(observations, "pledge_detail")["parameters"]
    assert _contract(bundle, "top10_cb_holders")["cadence_class"] == "event"
    assert _contract(bundle, "top10_cb_holders")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.cb_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "top10_cb_holders")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    # Live ids stay trade_date-only snapshots.  margin / margin_detail are
    # official T+1 08:30 previous-day publishes; prior_open_morning requests
    # the previous open trade_date after 08:30.  Empty ≠ success.
    # margin_secs is 盘前 and can succeed after 16:30 on an open day.
    assert _contract(bundle, "margin")["cadence_class"] == "prior_open_morning"
    assert _contract(bundle, "margin_detail")["cadence_class"] == "prior_open_morning"
    assert _contract(bundle, "margin_secs")["cadence_class"] == "postclose_daily"
    for api_name in ("margin", "margin_detail", "margin_secs"):
        assert _contract(bundle, api_name)["request_template"] == {
            "trade_date": "${window.trade_date}"
        }
        assert _contract(bundle, api_name)["fanout"]["strategy"] == "none"
        assert "trade_date" in _entry(observations, api_name)["parameters"]

    default_observations = deepcopy(observations)
    _entry(default_observations, "express")["parameters"]["ts_code"].pop(
        "batch_size"
    )
    default_bundle = _compile(request_observations=default_observations)
    assert _contract(default_bundle, "express")["fanout"]["batch_size"] == 1

    generic_observations = deepcopy(observations)
    _entry(generic_observations, "cb_price_chg")["parameters"]["ts_code"][
        "batch_size"
    ] = 7
    generic_bundle = _compile(request_observations=generic_observations)
    assert _contract(generic_bundle, "cb_price_chg")["fanout"]["batch_size"] == 7


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_dataset_field_batch_size_must_be_a_positive_integer(batch_size: object) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "express")["parameters"]["ts_code"]["batch_size"] = (
        batch_size
    )

    with pytest.raises(RuntimeContractCompilationError, match="positive integer"):
        _compile(request_observations=observations)


def test_dataset_field_declaration_rejects_extra_keys() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "express")["parameters"]["ts_code"]["unexpected"] = (
        "dataset-specific-override"
    )

    with pytest.raises(RuntimeContractCompilationError, match="unknown=unexpected"):
        _compile(request_observations=observations)


def test_probe_plan_keeps_190_audit_entries_but_never_materializes_blocked_params() -> (
    None
):
    plan = _compile_plan()
    entries = plan["entries"]
    assert isinstance(entries, list)
    assert len(entries) == 190
    assert set(plan) == {
        "schema_version",
        "production_ready",
        "provenance",
        "counts",
        "entries",
    }
    assert set(entries[0]) == {
        "api_name",
        "scope_labels",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
        "params",
        "fields",
    }
    assert set(plan["provenance"]) == {
        "expected_commit",
        "official_contract_sha256",
        "transport_observations_sha256",
        "request_observations_sha256",
        "api_names_sha256",
        "scheduled_partition",
        "run_clock",
        "seed_authorities",
    }
    assert plan["counts"] == {
        "planned": 190,
        "executable": 135,
        "blocked": 55,
        "ingest_contract_ready": 128,
        "ingest_contract_blocked": 62,
    }

    daily = _entry(plan, "daily")
    assert daily["params"] == {"trade_date": "20260718"}
    assert daily["probe_state"] == "executable"
    assert daily["fields"]

    news = _entry(plan, "news")
    assert news["params"] == {
        "end_date": "2026-07-21 18:30:00",
        "src": "sina",
        "start_date": "2026-07-21 18:29:00",
    }
    assert news["probe_state"] == "executable"
    assert news["probe_block_reasons"] == []
    assert news["ingest_contract_state"] == "ready"
    assert news["ingest_contract_block_reasons"] == []
    assert news["scope_labels"] == ["all", "gaps"]
    assert all(
        entry["params"] == {} for entry in entries if entry["probe_state"] == "blocked"
    )

    daily_basic = _entry(plan, "daily_basic")
    assert daily_basic["probe_state"] == "executable"
    assert daily_basic["probe_block_reasons"] == []
    assert daily_basic["params"] == {"trade_date": "20260718"}

    bak_daily = _entry(plan, "bak_daily")
    assert bak_daily["probe_state"] == "executable"
    assert bak_daily["ingest_contract_state"] == "blocked"
    assert bak_daily["params"] == {"trade_date": "20260721"}
    fund_adj = _entry(plan, "fund_adj")
    assert fund_adj["params"] == {"trade_date": "20260721"}
    fund_manager = _entry(plan, "fund_manager")
    assert fund_manager["params"] == {"ann_date": "20260721"}

    rt_min = _entry(plan, "rt_min")
    assert rt_min["probe_state"] == "executable"
    assert rt_min["probe_block_reasons"] == []
    assert rt_min["params"] == {"freq": "5MIN", "ts_code": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"}


def test_checked_probe_authorities_compile_without_test_rebinding() -> None:
    assert (
        _yaml(REQUEST_OBSERVATIONS)["provenance"]["registered_contract_bundle"][
            "sha256"
        ]
        == _sha(UPSTREAM_CONTRACTS)
    )
    plan = compile_https_probe_plan(
        _bytes(DOCUMENTS),
        _bytes(REQUEST_OBSERVATIONS),
        _bytes(TRANSPORT_OBSERVATIONS),
        registered_contract_bundle=_bytes(UPSTREAM_CONTRACTS),
        official_contract_sha256=_sha(DOCUMENTS),
        transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
        request_observations_sha256=_sha(REQUEST_OBSERVATIONS),
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
    )
    assert plan["counts"]["planned"] == 190
    assert plan["counts"] == {
        "planned": 190,
        "executable": 135,
        "blocked": 55,
        "ingest_contract_ready": 128,
        "ingest_contract_blocked": 62,
    }


def test_probe_plan_unlocks_dataset_fanout_only_from_a_fresh_success_receipt() -> None:
    seed = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "2.0.0",
        "fresh": True,
    }
    plan = _compile_plan(dataset_field_values=[seed])
    assert plan["counts"] == {
        "planned": 190,
        "executable": 155,
        "blocked": 35,
        "ingest_contract_ready": 146,
        "ingest_contract_blocked": 44,
    }
    express = _entry(plan, "express")
    assert express["probe_state"] == "executable"
    assert express["probe_block_reasons"] == []
    assert express["params"] == {"ts_code": "600000.SH"}
    cashflow = _entry(plan, "cashflow")
    assert cashflow["probe_state"] == "executable"
    assert cashflow["probe_block_reasons"] == []
    assert cashflow["params"] == {"ts_code": "600000.SH"}
    fina_audit = _entry(plan, "fina_audit")
    assert fina_audit["probe_state"] == "executable"
    assert fina_audit["probe_block_reasons"] == []
    assert fina_audit["params"] == {"ts_code": "600000.SH"}
    forecast = _entry(plan, "forecast")
    assert forecast["probe_state"] == "executable"
    assert forecast["probe_block_reasons"] == []
    assert forecast["params"] == {"ts_code": "600000.SH"}
    assert "600000.SH" not in yaml.safe_dump(plan["provenance"])
    assert plan["provenance"]["seed_authorities"] == [
        {
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "receipt_id": "receipt-stock-basic-20260718",
            "data_through": "20260718",
            "schema_version": "2.0.0",
        }
    ]
    assert set(plan["provenance"]["seed_authorities"][0]) == {
        "dataset_id",
        "field",
        "receipt_id",
        "data_through",
        "schema_version",
    }
    assert "value" not in plan["provenance"]["seed_authorities"][0]

    cb_seed = {
        "dataset_id": "cn.dataset.cb_basic",
        "field": "ts_code",
        "value": "110000.SH",
        "receipt_id": "receipt-cb-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    multi_seed_plan = _compile_plan(dataset_field_values=[seed, cb_seed])
    seed_authorities = multi_seed_plan["provenance"]["seed_authorities"]
    assert [
        (authority["dataset_id"], authority["field"]) for authority in seed_authorities
    ] == sorted(
        (authority["dataset_id"], authority["field"]) for authority in seed_authorities
    )
    assert all("value" not in authority for authority in seed_authorities)

    with pytest.raises(RuntimeContractCompilationError, match="duplicate trusted seed"):
        _compile_plan(dataset_field_values=[seed, deepcopy(seed)])

    stale = deepcopy(seed)
    stale["fresh"] = False
    with pytest.raises(RuntimeContractCompilationError, match="fresh success receipt"):
        _compile_plan(dataset_field_values=[stale])


@pytest.mark.parametrize(
    ("dataset_id", "field", "message"),
    [
        (
            "cn.dataset.nonexistent",
            "ts_code",
            "references unknown seed dataset",
        ),
        (
            "cn.equity.security_master",
            "nonexistent_field",
            "references unknown seed field",
        ),
    ],
)
def test_probe_plan_rejects_unregistered_seed_declarations_before_generation(
    dataset_id: str,
    field: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    express = _entry(observations, "express")
    declaration = express["parameters"]["ts_code"]
    declaration["dataset_id"] = dataset_id
    declaration["field"] = field
    seed = {
        "dataset_id": dataset_id,
        "field": field,
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile_plan(
            request_observations=observations,
            dataset_field_values=[seed],
        )


def test_probe_plan_rejects_seed_schema_drift_and_blocked_producer() -> None:
    seed = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "v1",
        "fresh": True,
    }
    with pytest.raises(RuntimeContractCompilationError, match="schema_version"):
        _compile_plan(dataset_field_values=[seed])

    seed["schema_version"] = "9.9.9"
    with pytest.raises(
        RuntimeContractCompilationError,
        match="schema_version does not match registered producer",
    ):
        _compile_plan(dataset_field_values=[seed])

    observations = _yaml(REQUEST_OBSERVATIONS)
    live_bundle = _compile(request_observations=observations)
    producer = _entry(observations, "stock_basic")
    producer["probe_state"] = "blocked"
    producer["probe_block_reasons"] = ["request_anchor_unresolved"]
    observations["counts"]["probe_executable"] = 134
    observations["counts"]["probe_blocked"] = 56
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(live_bundle)
    ).hexdigest()
    seed["schema_version"] = "2.0.0"
    with pytest.raises(RuntimeContractCompilationError, match="producer.*executable"):
        _compile_plan(
            request_observations=observations,
            registered_contract_bundle=live_bundle,
            dataset_field_values=[seed],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("invalid_request_shape", "request_shape is unsupported"),
        ("unsafe_variant_placeholder", "concrete finite JSON scalar"),
        ("unsafe_variant_nested", "concrete finite JSON scalar"),
        ("provenance_extra", "provenance keys invalid"),
        ("provenance_source_extra", "official_contracts keys invalid"),
        ("normalization_extra", "normalization_policy keys invalid"),
        ("normalization_drift", "normalization_policy does not match"),
    ],
)
def test_runtime_and_plan_share_closed_request_observation_front_door(
    mutation: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    if mutation == "invalid_request_shape":
        _entry(observations, "daily")["request_shape"] = "custom"
    elif mutation == "unsafe_variant_placeholder":
        _entry(observations, "stock_basic")["request_variants"][0]["list_status"] = (
            "${window.list_status}"
        )
    elif mutation == "unsafe_variant_nested":
        _entry(observations, "stock_basic")["request_variants"][0]["list_status"] = {
            "nested": "L"
        }
    elif mutation == "provenance_extra":
        observations["provenance"]["unexpected"] = "not-authority"
    elif mutation == "provenance_source_extra":
        observations["provenance"]["official_contracts"]["unexpected"] = True
    elif mutation == "normalization_extra":
        observations["normalization_policy"]["unexpected"] = True
    else:
        observations["normalization_policy"]["max_abs_offset_seconds"] = 1

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)
    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile_plan(request_observations=observations)


def test_probe_plan_is_pure_and_does_not_require_migration_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["provenance"].pop("migration_request_profiles")
    live_bundle = _compile(request_observations=observations)
    observations["provenance"]["registered_contract_bundle"]["sha256"] = hashlib.sha256(
        _yaml_bytes(live_bundle)
    ).hexdigest()
    observation_bytes = _yaml_bytes(observations)
    document_bytes = _bytes(DOCUMENTS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)
    registered_bytes = _yaml_bytes(live_bundle)
    official_sha = _sha(DOCUMENTS)
    transport_sha = _sha(TRANSPORT_OBSERVATIONS)
    request_sha = hashlib.sha256(observation_bytes).hexdigest()

    def _forbid_io(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("compile_https_probe_plan must not read files")

    monkeypatch.setattr(Path, "open", _forbid_io)
    monkeypatch.setattr(Path, "read_bytes", _forbid_io)
    monkeypatch.setattr(Path, "read_text", _forbid_io)

    plan = compile_https_probe_plan(
        document_bytes,
        observation_bytes,
        transport_bytes,
        registered_contract_bundle=registered_bytes,
        official_contract_sha256=official_sha,
        transport_observations_sha256=transport_sha,
        request_observations_sha256=request_sha,
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
    )
    assert plan["counts"]["planned"] == 190


@pytest.mark.parametrize(
    ("authority", "message"),
    [
        ("official", "official contract bytes do not match"),
        ("request", "request observations bytes do not match"),
        ("transport", "transport observations bytes do not match"),
        ("registered", "registered contract bundle bytes do not match"),
    ],
)
def test_probe_plan_rejects_content_drift_behind_frozen_authority_sha(
    authority: str,
    message: str,
) -> None:
    document_bytes = _bytes(DOCUMENTS)
    request_bytes = _bytes(REQUEST_OBSERVATIONS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)
    registered_bytes = _bytes(UPSTREAM_CONTRACTS)

    if authority == "official":
        document = _yaml(DOCUMENTS)
        document["provider"] = "tampered"
        document_bytes = _yaml_bytes(document)
    elif authority == "request":
        request = _yaml(REQUEST_OBSERVATIONS)
        _entry(request, "daily")["parameters"]["trade_date"]["offset_seconds"] = 86400
        request_bytes = _yaml_bytes(request)
    elif authority == "transport":
        transport = _yaml(TRANSPORT_OBSERVATIONS)
        transport["provider"] = "tampered"
        transport_bytes = _yaml_bytes(transport)
    else:
        registered = _yaml(UPSTREAM_CONTRACTS)
        registered["contracts"][0]["domain"] = "tampered"
        registered_bytes = _yaml_bytes(registered)

    with pytest.raises(RuntimeContractCompilationError, match=message):
        compile_https_probe_plan(
            document_bytes,
            request_bytes,
            transport_bytes,
            registered_contract_bundle=registered_bytes,
            official_contract_sha256=_sha(DOCUMENTS),
            transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
            request_observations_sha256=_sha(REQUEST_OBSERVATIONS),
            expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
            run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
            scheduled_partition="20260718",
        )


@pytest.mark.parametrize(
    ("authority", "message"),
    [
        ("official", "official contract bytes do not match"),
        ("request", "request observations bytes do not match"),
        ("transport", "transport observations bytes do not match"),
        ("reviewed", "reviewed contract bundle bytes do not match"),
    ],
)
def test_runtime_compiler_rejects_content_drift_behind_frozen_authority_sha(
    authority: str,
    message: str,
) -> None:
    document_bytes = _bytes(DOCUMENTS)
    reviewed_bytes = _bytes(REVIEWED)
    request_bytes = _bytes(REQUEST_OBSERVATIONS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)

    if authority == "official":
        document = _yaml(DOCUMENTS)
        document["provider"] = "tampered"
        document_bytes = _yaml_bytes(document)
    elif authority == "request":
        request = _yaml(REQUEST_OBSERVATIONS)
        _entry(request, "bak_daily")["parameters"]["trade_date"]["offset_seconds"] = 86400
        request_bytes = _yaml_bytes(request)
    elif authority == "transport":
        transport = _yaml(TRANSPORT_OBSERVATIONS)
        transport["provider"] = "tampered"
        transport_bytes = _yaml_bytes(transport)
    else:
        reviewed = _yaml(REVIEWED)
        reviewed["contracts"][0]["domain"] = "tampered"
        reviewed_bytes = _yaml_bytes(reviewed)

    with pytest.raises(RuntimeContractCompilationError, match=message):
        compile_runtime_contract_bundle(
            document_bytes,
            reviewed_bytes,
            _bytes(POLICY),
            _bytes(CADENCE_POLICY),
            request_observations=request_bytes,
            transport_observations=transport_bytes,
            official_contract_sha256=_sha(DOCUMENTS),
            transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
            request_observations_sha256=_sha(REQUEST_OBSERVATIONS),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown_source", "parameter source"),
        ("unknown_transform", "parameter transform"),
        ("required_true_unmapped", "required provider parameter"),
        ("either_or_unmapped", "二选一 parameter"),
        ("required_unknown_executable", "unknown official requiredness"),
        ("executable_with_reason", "probe_state=executable"),
        ("blocked_without_reason", "probe_state=blocked"),
        ("unsorted_reasons", "probe_block_reasons must be sorted"),
    ],
)
def test_request_observation_contract_fails_closed(
    mutation: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    if mutation == "unknown_source":
        _entry(observations, "daily")["parameters"]["trade_date"]["source"] = "today"
    elif mutation == "unknown_transform":
        _entry(observations, "daily")["parameters"]["trade_date"]["transform"] = "date"
    elif mutation == "required_true_unmapped":
        _entry(observations, "fut_basic")["parameters"] = {}
    elif mutation == "either_or_unmapped":
        _entry(observations, "daily_basic")["parameters"] = {}
    elif mutation == "required_unknown_executable":
        item = _entry(observations, "fund_company")
        item["probe_state"] = "executable"
        item["probe_block_reasons"] = []
    elif mutation == "executable_with_reason":
        _entry(observations, "daily")["probe_block_reasons"] = [
            "request_anchor_unresolved"
        ]
    elif mutation == "blocked_without_reason":
        item = _entry(observations, "news")
        item["probe_state"] = "blocked"
        item["probe_block_reasons"] = []
    else:
        _entry(observations, "news")["probe_block_reasons"] = [
            "required_parameter_unresolved",
            "required_enum_unresolved",
        ]

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)


def test_optional_resumable_fanout_is_deterministic_and_absent_is_unchanged() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    target = _entry(observations, "cyq_chips")

    policy = target.pop("resumable_fanout")
    without_policy = _compile(request_observations=observations)
    assert "resumable_fanout" not in _contract(without_policy, "cyq_chips")

    target["resumable_fanout"] = policy
    first = _compile(request_observations=observations)
    second = _compile(request_observations=deepcopy(observations))

    assert first == second
    assert _contract(first, "cyq_chips")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }


@pytest.mark.parametrize(
    ("policy", "api_name", "message"),
    [
        (
            {
                "cursor_contract_version": 2,
                "max_batches_per_run": 1,
                "unknown": True,
            },
            "cyq_chips",
            "resumable_fanout keys invalid",
        ),
        (
            {"cursor_contract_version": 1, "max_batches_per_run": 1},
            "cyq_chips",
            "cursor_contract_version must be 2",
        ),
        (
            {"cursor_contract_version": 2, "max_batches_per_run": 0},
            "cyq_chips",
            "max_batches_per_run must be a positive integer",
        ),
        (
            {"cursor_contract_version": 2, "max_batches_per_run": 1},
            "daily",
            "requires a non-empty fanout",
        ),
    ],
)
def test_optional_resumable_fanout_fails_closed(
    policy: dict[str, object],
    api_name: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, api_name)["resumable_fanout"] = policy

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)


def test_request_observation_source_bytes_and_api_set_are_bound() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["provenance"]["official_contracts"]["sha256"] = "f" * 64
    with pytest.raises(
        RuntimeContractCompilationError, match="official contract bytes"
    ):
        _compile(request_observations=observations)

    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["entries"].pop()
    observations["counts"]["interfaces"] = 189
    with pytest.raises(RuntimeContractCompilationError, match="exactly 190"):
        _compile(request_observations=observations)


def test_active_loader_accepts_runtime_request_window_formats_and_rejects_others(
    tmp_path: Path,
) -> None:
    bundle = _compile()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=_yaml(TRANSPORT_OBSERVATIONS),
    )
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    loaded = load_dataset_registry(path)
    monthly = loaded.provider_binding("cn.dataset.cn_cpi", "tushare")
    assert monthly.activation_state == "active"
    assert monthly.request_window_policy is not None
    assert monthly.request_window_policy.formats["m"] == "yyyymm"

    supported = {
        "cn.dataset.adj_factor": "yyyymmdd",
        "cn.dataset.broker_recommend": "yyyymm",
        "cn.dataset.cn_gdp": "yyyy_qn",
        "cn.dataset.fut_weekly_detail": "yyyyww",
        "cn.dataset.stk_nineturn": "local_datetime_seconds",
    }
    for dataset_id, expected_format in supported.items():
        candidate = deepcopy(registry)
        item = next(
            dataset
            for dataset in candidate["datasets"]
            if dataset["dataset_id"] == dataset_id
        )
        binding = item["provider_bindings"][0]
        binding["entitlement_state"] = "active"
        binding["activation_state"] = "active"
        binding["probe_state"] = "executable"
        binding["probe_block_reasons"] = []
        binding["ingest_contract_state"] = "ready"
        binding["ingest_contract_block_reasons"] = []
        path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
        loaded_binding = load_dataset_registry(path).provider_binding(
            dataset_id, "tushare"
        )
        assert loaded_binding.request_window_policy is not None
        assert set(loaded_binding.request_window_policy.formats.values()) == {
            expected_format
        }

    for unsupported_format in ("identity", "rfc3339"):
        candidate = deepcopy(registry)
        item = next(
            dataset
            for dataset in candidate["datasets"]
            if dataset["dataset_id"] == "cn.dataset.adj_factor"
        )
        binding = item["provider_bindings"][0]
        binding["activation_state"] = "active"
        binding["request_window_policy"]["formats"]["trade_date"] = (
            unsupported_format
        )
        path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
        with pytest.raises(ValueError, match="active.*runtime request_window format"):
            load_dataset_registry(path)


def test_runtime_compiler_does_not_mutate_any_authority_input() -> None:
    documents = _yaml(DOCUMENTS)
    request_observations = _yaml(REQUEST_OBSERVATIONS)
    transport_observations = _yaml(TRANSPORT_OBSERVATIONS)
    before = (
        deepcopy(documents),
        deepcopy(request_observations),
        deepcopy(transport_observations),
    )

    _compile(
        documents=documents,
        request_observations=request_observations,
        transport_observations=transport_observations,
    )

    assert (documents, request_observations, transport_observations) == before
