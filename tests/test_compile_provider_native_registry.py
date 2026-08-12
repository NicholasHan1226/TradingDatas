from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from collectors.tushare.provider_native_ingest import _provider_scan_budget
from dataset_registry import load_dataset_registry
import tools.compile_provider_native_registry as compiler_module
from tools.compile_provider_native_registry import (
    DEFAULT_QUERY_DEFAULTS,
    compile_provider_native_registry,
    load_upstream_contract_bundle,
    render_registry,
)
from tests.synthetic_activation_evidence import (
    build_synthetic_activation_evidence,
    build_synthetic_raw_probe_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
OBSERVATIONS_PATH = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
TARGET_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"
OPERATIONS_PATH = ROOT / "docs" / "OPERATIONS.md"


def test_runtime_activation_evidence_is_not_repository_owned() -> None:
    assert not (
        ROOT / "config" / "quicksync_https_activation_evidence.v1.yaml"
    ).exists()
    assert not hasattr(compiler_module, "DEFAULT_ACTIVATION_EVIDENCE_PATH")


def _read_yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _bundle() -> dict[str, object]:
    return deepcopy(_read_yaml(CONTRACT_PATH))


def _observations() -> dict[str, object]:
    return deepcopy(_read_yaml(OBSERVATIONS_PATH))


def _trade_calendar(bundle: dict[str, object]) -> dict[str, object]:
    contracts = bundle["contracts"]
    assert isinstance(contracts, list)
    contract = next(
        item
        for item in contracts
        if isinstance(item, dict) and item["dataset_id"] == "cn.market.trade_calendar"
    )
    return contract


def test_disclosure_date_observation_projects_reviewed_identity_without_missing_field() -> (
    None
):
    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    contracts = registry["datasets"]
    assert isinstance(contracts, list)
    contract = next(
        item
        for item in contracts
        if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.disclosure_date"
    )

    assert contract["schema_version"] == "2.0.0"
    assert contract["primary_key"] == ["ann_date", "end_date", "ts_code"]
    assert contract["partition_field"] == "ann_date"
    binding = contract["provider_bindings"][0]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "partition_field": "ann_date",
        "request_partition_key": "ann_date",
    }
    assert "modify_date" not in {field["name"] for field in contract["fields"]}
    assert binding["ingest_contract_state"] == "ready"
    assert "modify_date" not in binding["requested_fields"]


@pytest.mark.parametrize(
    ("dataset_id", "primary_key", "partition_field"),
    [
        (
            "cn.dataset.share_float",
            ["ann_date", "float_date", "ts_code", "holder_name", "share_type"],
            "ann_date",
        ),
        (
            "cn.dataset.top_list",
            ["trade_date", "ts_code", "reason"],
            "trade_date",
        ),
    ],
)
def test_nonmarket_evidence_observations_project_reviewed_partition_identities(
    dataset_id: str, primary_key: list[str], partition_field: str
) -> None:
    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    contracts = registry["datasets"]
    assert isinstance(contracts, list)
    contract = next(
        item
        for item in contracts
        if isinstance(item, dict) and item["dataset_id"] == dataset_id
    )

    assert contract["schema_version"] == "1.0.0"
    assert contract["primary_key"] == primary_key
    assert contract["partition_field"] == partition_field
    binding = contract["provider_bindings"][0]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "partition_field": partition_field,
        "request_partition_key": partition_field,
    }
    assert binding["ingest_contract_state"] == "ready"
    assert set(primary_key).issubset(binding["requested_fields"])


def test_fut_settle_projects_receipt_bound_day_identity_without_claiming_as_of() -> None:
    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    contracts = registry["datasets"]
    assert isinstance(contracts, list)
    contract = next(
        item
        for item in contracts
        if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.fut_settle"
    )

    assert contract["primary_key"] == ["trade_date", "ts_code"]
    assert contract["as_of_field"] is None
    assert contract["range_field"] is None
    assert contract["partition_field"] is None
    binding = contract["provider_bindings"][0]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
    }


def test_fut_basic_projects_contract_identity_and_deterministic_catalog_order() -> None:
    """The M-contract consumer cannot paginate or replay an identity-less catalog."""

    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    contract = next(
        item
        for item in datasets
        if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.fut_basic"
    )

    assert contract["primary_key"] == ["ts_code"]
    assert [f"{field}:asc" for field in contract["primary_key"]] == ["ts_code:asc"]


def test_fut_mapping_projects_complete_day_identity_and_catalog_order() -> None:
    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    contract = next(
        item
        for item in datasets
        if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.fut_mapping"
    )

    fields = {field["name"]: field for field in contract["fields"]}
    assert fields["trade_date"]["nullable"] is False
    assert fields["ts_code"]["nullable"] is False
    assert contract["primary_key"] == ["trade_date", "ts_code"]
    assert [f"{field}:asc" for field in contract["primary_key"]] == [
        "trade_date:asc",
        "ts_code:asc",
    ]
    assert contract["as_of_field"] is None
    assert contract["range_field"] is None
    assert contract["partition_field"] is None
    binding = contract["provider_bindings"][0]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
    }


def test_fut_daily_projects_complete_day_identity_and_catalog_order() -> None:
    """Frozen document 138 identifies a daily row by its day and contract."""

    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    contract = next(
        item
        for item in datasets
        if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.fut_daily"
    )

    fields = {field["name"]: field for field in contract["fields"]}
    assert fields["trade_date"]["nullable"] is False
    assert fields["ts_code"]["nullable"] is False
    assert contract["primary_key"] == ["trade_date", "ts_code"]
    assert [f"{field}:asc" for field in contract["primary_key"]] == [
        "trade_date:asc",
        "ts_code:asc",
    ]
    assert contract["as_of_field"] is None
    assert contract["range_field"] is None
    assert contract["partition_field"] is None
    binding = contract["provider_bindings"][0]
    assert binding["requested_fields"] == [
        "ts_code",
        "trade_date",
        "pre_close",
        "pre_settle",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "change1",
        "change2",
        "vol",
        "amount",
        "oi",
        "oi_chg",
    ]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
    }


def test_fut_index_daily_projects_complete_day_identity_and_catalog_order() -> None:
    registry = compile_provider_native_registry(_bundle(), observations_document=_observations())
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    contract = next(item for item in datasets if isinstance(item, dict) and item["dataset_id"] == "cn.dataset.fut_index_daily")
    fields = {field["name"]: field for field in contract["fields"]}
    assert fields["trade_date"]["nullable"] is False
    assert fields["ts_code"]["nullable"] is False
    assert contract["primary_key"] == ["trade_date", "ts_code"]
    assert contract["as_of_field"] is None
    assert contract["range_field"] is None
    assert contract["partition_field"] is None
    assert contract["provider_bindings"][0]["requested_fields"] == [
        "trade_date",
        "ts_code",
        "close",
        "open",
        "high",
        "low",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    assert contract["provider_bindings"][0]["response_completeness"] == {"strategy": "single_partition_unique_primary_key", "fixed_field_matches": {}, "reject_at_row_limit": True, "partition_field": "trade_date", "request_partition_key": "trade_date"}


def test_fut_weekly_monthly_projects_frequency_scoped_day_identity_and_completeness() -> None:
    """Frozen document 337 identifies a week/month row by frequency, day and contract."""

    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    contract = next(
        item
        for item in registry["datasets"]
        if isinstance(item, dict)
        and item["dataset_id"] == "cn.dataset.fut_weekly_monthly"
    )
    fields = {field["name"]: field for field in contract["fields"]}

    assert fields["trade_date"]["nullable"] is False
    assert fields["freq"]["nullable"] is False
    assert fields["ts_code"]["nullable"] is False
    assert contract["primary_key"] == ["trade_date", "freq", "ts_code"]
    assert contract["as_of_field"] is None
    assert contract["range_field"] is None
    assert contract["partition_field"] is None
    binding = contract["provider_bindings"][0]
    assert binding["request_variants"] == [{"freq": "week"}, {"freq": "month"}]
    assert binding["requested_fields"] == [
        "ts_code",
        "trade_date",
        "end_date",
        "freq",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "settle",
        "pre_settle",
        "vol",
        "amount",
        "oi",
        "oi_chg",
        "exchange",
        "change1",
        "change2",
    ]
    assert binding["response_completeness"] == {
        "strategy": "single_partition_unique_primary_key",
        "fixed_field_matches": {"freq": "freq"},
        "reject_at_row_limit": True,
        "partition_field": "trade_date",
        "request_partition_key": "trade_date",
    }


def test_compiler_has_single_registry_authority_and_no_legacy_inputs() -> None:
    parameters = inspect.signature(compile_provider_native_registry).parameters

    assert tuple(parameters) == (
        "upstream_contracts",
        "observations_document",
        "activation_evidence_document",
        "query_defaults",
        "compilation_mode",
    )
    source = inspect.getsource(compiler_module)
    for forbidden in (
        "tushare_capability_plan.yaml",
        "collectors/tushare/config.yaml",
        "config/dataset_registry.yaml",
        "registry_document",
        "capability_plan",
        "collector_config",
        "legacy owner",
    ):
        assert forbidden not in source


def test_contract_bundle_is_the_only_dataset_authority_and_inputs_are_immutable(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    source = deepcopy(bundle)

    registry = compile_provider_native_registry(bundle)
    output = tmp_path / "registry.yaml"
    output.write_text(render_registry(registry), encoding="utf-8")
    loaded = load_dataset_registry(output)

    assert bundle == source
    assert registry["version"] == 1
    assert registry["query_defaults"] == DEFAULT_QUERY_DEFAULTS
    dataset_ids = [dataset.dataset_id for dataset in loaded.datasets]
    assert len(dataset_ids) == 190
    assert dataset_ids == sorted(dataset_ids)
    assert {
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }.issubset(dataset_ids)
    for dataset in loaded.datasets:
        binding = dataset.provider_bindings[0]
        assert binding.entitlement_state == "unknown"
        assert binding.activation_state == "paused"
        assert binding.target_tables == ("provider_dataset_rows",)


def test_compiler_projects_all_input_fields_byte_for_byte() -> None:
    bundle = _bundle()
    registry = compile_provider_native_registry(bundle)
    contracts = {contract["api_name"]: contract for contract in bundle["contracts"]}
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }

    assert len(contracts) == 190
    assert set(bindings) == set(contracts)
    for api_name, contract in contracts.items():
        input_fields = contract["input_fields"]
        assert input_fields
        assert bindings[api_name]["input_fields"] == input_fields
        assert all(
            set(input_field) == {"name", "declared_source_type", "required"}
            for input_field in input_fields
        )


def test_compiler_preserves_exact_fanout_snapshot_contract() -> None:
    registry = compile_provider_native_registry(_bundle())
    binding = next(
        dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
        if dataset["dataset_id"] == "cn.dataset.rt_min"
    )

    assert binding["response_completeness"] == {
        "strategy": "unique_primary_key_snapshot",
        "fixed_field_matches": {"freq": "freq"},
        "reject_at_row_limit": True,
        "fanout_field": "ts_code",
        "snapshot_field": "time",
    }


def test_compiler_normalizes_windowed_primary_key_completeness() -> None:
    completeness = compiler_module._completeness(  # noqa: SLF001
        {
            "strategy": "windowed_unique_primary_key",
            "date_field": "pub_time",
            "request_start_key": "start_time",
            "request_end_key": "end_time",
            "fanout_field": "src",
            "fixed_field_matches": {},
            "reject_at_row_limit": True,
        },
        fields={"src", "pub_time", "title"},
        template={
            "start_time": "${window.start_time}",
            "end_time": "${window.end_time}",
        },
        window={
            "required_keys": ["start_time", "end_time"],
            "formats": {
                "start_time": "local_datetime_seconds",
                "end_time": "local_datetime_seconds",
            },
            "range_start_key": "start_time",
            "range_end_key": "end_time",
            "max_span_days": 1,
        },
        label="synthetic.response_completeness",
    )

    assert completeness == {
        "strategy": "windowed_unique_primary_key",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
        "date_field": "pub_time",
        "request_start_key": "start_time",
        "request_end_key": "end_time",
        "fanout_field": "src",
    }


def test_numeric_leading_provider_fields_compile_without_per_api_code() -> None:
    registry = compile_provider_native_registry(_bundle())
    by_api = {
        item["provider_bindings"][0]["api_name"]: item for item in registry["datasets"]
    }

    assert "1w" in {field["name"] for field in by_api["shibor"]["fields"]}
    assert "1m_a" in {field["name"] for field in by_api["shibor_quote"]["fields"]}
    assert "10day" in {field["name"] for field in by_api["tdx_daily"]["fields"]}


def test_observation_declaration_is_the_only_entitlement_and_activation_authority() -> (
    None
):
    registry = compile_provider_native_registry(
        _bundle(), observations_document=_observations()
    )
    bindings = {
        dataset["dataset_id"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }

    assert bindings["cn.market.trade_calendar"]["entitlement_state"] == "active"
    assert bindings["cn.market.trade_calendar"]["activation_state"] == "active"
    assert bindings["cn.equity.daily"]["entitlement_state"] == "active"
    assert bindings["cn.equity.daily"]["activation_state"] == "active"
    assert bindings["cn.dataset.adj_factor"]["entitlement_state"] == "active"
    assert bindings["cn.dataset.adj_factor"]["activation_state"] == "active"
    assert bindings["cn.dataset.cb_price_chg"]["entitlement_state"] == "locked"
    assert bindings["cn.dataset.etf_sh_cons"]["entitlement_state"] == "excluded"


def test_fresh_https_evidence_promotes_exactly_the_ingest_ready_result_set() -> None:
    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
        ),
        compilation_mode="preactivation_candidate",
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    active = {
        api_name
        for api_name, binding in bindings.items()
        if binding["activation_state"] == "active"
    }

    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert active == set(active_evidence)
    assert all(
        bindings[api_name]["entitlement_state"] == "active" for api_name in active
    )


@pytest.mark.parametrize(
    ("api_name", "expected_format"),
    (
        ("broker_recommend", "yyyymm"),
        ("cn_gdp", "yyyy_qn"),
    ),
)
def test_fresh_https_evidence_promotes_supported_non_daily_windows(
    api_name: str, expected_format: str
) -> None:
    """Monthly and quarterly contracts use the same generic planner path."""

    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name=api_name,
        ),
        compilation_mode="preactivation_candidate",
    )
    binding = next(
        dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
        if dataset["provider_bindings"][0]["api_name"] == api_name
    )

    assert binding["activation_state"] == "active"
    assert set(binding["request_window_policy"]["formats"].values()) == {
        expected_format
    }


def test_fresh_https_evidence_promotes_bounded_on_demand_local_event_window() -> None:
    """A proven event cohort is collectible without making it schedulable."""

    bundle = _bundle()
    contracts = bundle["contracts"]
    assert isinstance(contracts, list)
    major_news = next(
        item
        for item in contracts
        if isinstance(item, dict) and item["api_name"] == "major_news"
    )
    major_news["primary_key"] = ["src", "pub_time", "title"]
    major_news["default_projection"] = ["src", "pub_time", "title"]
    major_news["request_shape"] = "event_or_intraday_window"
    major_news["request_template"] = {
        "start_date": "${window.start_date}",
        "end_date": "${window.end_date}",
    }
    major_news["fanout"] = {
        "strategy": "literal_values",
        "parameter": "src",
        "values": ["新浪财经"],
        "batch_size": 1,
    }
    major_news["response_completeness"] = {
        "strategy": "windowed_unique_primary_key",
        "date_field": "pub_time",
        "request_start_key": "start_date",
        "request_end_key": "end_date",
        "fanout_field": "src",
        "fixed_field_matches": {},
        "reject_at_row_limit": True,
    }
    major_news["requested_fields"] = ["src", "pub_time", "title"]
    fields = major_news["fields"]
    assert isinstance(fields, list)
    for field in fields:
        assert isinstance(field, dict)
        if field["name"] in {"src", "pub_time", "title"}:
            field["nullable"] = False

    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    active_evidence.pop("major_news", None)
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name="major_news",
        ),
        compilation_mode="preactivation_candidate",
    )
    dataset = next(
        item
        for item in registry["datasets"]
        if item["provider_bindings"][0]["api_name"] == "major_news"
    )
    binding = dataset["provider_bindings"][0]

    assert binding["activation_state"] == "active"
    assert dataset["cadence_class"] == "on_demand"
    assert set(binding["request_window_policy"]["formats"].values()) == {
        "local_datetime_seconds"
    }

    major_news["cadence_class"] = "session_minute"
    paused_registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name="major_news",
        ),
        compilation_mode="preactivation_candidate",
    )
    paused_binding = next(
        item["provider_bindings"][0]
        for item in paused_registry["datasets"]
        if item["provider_bindings"][0]["api_name"] == "major_news"
    )
    assert paused_binding["activation_state"] == "paused"


def test_partial_https_evidence_promotes_only_its_verified_cohort() -> None:
    """A bounded probe cannot claim activation for unexecuted interfaces."""

    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name="major_news",
            cohort_api_names={"major_news"},
        ),
        compilation_mode="preactivation_candidate",
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert bindings["major_news"]["activation_state"] == "active"
    assert all(
        bindings[api_name]["activation_state"] == "active"
        for api_name in active_evidence
    )
    assert bindings["forecast"]["activation_state"] == "paused"


def test_partial_https_evidence_rejects_executable_coverage_drift() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_activation_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
        cohort_api_names={"major_news"},
    )
    payload = evidence["evidence"]
    assert isinstance(payload, dict)
    coverage = payload["coverage"]
    assert isinstance(coverage, dict)
    coverage["executable"] = int(coverage["executable"]) - 1
    coverage["blocked"] = int(coverage["blocked"]) + 1

    with pytest.raises(ValueError, match="executable coverage drifted"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_promotes_only_its_verified_cohort() -> None:
    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_raw_probe_evidence(
            bundle,
            observations,
            promoted_api_name="major_news",
        ),
        compilation_mode="preactivation_candidate",
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["major_news"]["activation_state"] == "active"
    assert bindings["forecast"]["activation_state"] == "paused"


def _raw_cb_dependent_evidence(
    *, api_name: str = "cb_rate", state: str = "success"
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Build a seed-bound raw cohort without embedding provider rows."""

    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="cb_basic",
    )
    authorities = observations["dependency_seed_authorities"]
    assert isinstance(authorities, list)
    evidence["seed_authorities"] = [
        {
            key: authorities[0][key]
            for key in ("dataset_id", "field", "schema_version", "receipt_id", "data_through")
        }
    ]
    coverage = evidence["coverage"]
    assert isinstance(coverage, dict)
    coverage["executable"] += len(authorities[0]["dependent_api_names"])
    coverage["blocked"] -= len(authorities[0]["dependent_api_names"])
    evidence["run_clock"] = "2026-08-11T22:13:40+00:00"
    evidence["started_at"] = "2026-08-11T22:13:41+00:00"
    evidence["finished_at"] = "2026-08-11T22:13:42+00:00"
    evidence["scheduled_partition"] = "20260812"

    results = evidence["results"]
    assert isinstance(results, list) and len(results) == 1
    result = results[0]
    assert isinstance(result, dict)
    result["api_name"] = api_name
    result["state"] = state
    if state == "valid_empty":
        result["row_count"] = 0
    source_result = {
        key: result[key]
        for key in (
            "api_name",
            "state",
            "provider_class",
            "row_count",
            "response_bytes",
            "response_sha256",
            "fields",
            "elapsed_ms",
        )
    }
    summary = evidence["summary"]
    assert isinstance(summary, dict)
    for key in summary:
        summary[key] = 1 if key == state else 0
    return bundle, observations, evidence


def test_raw_probe_evidence_reuses_exact_formal_seed_for_listed_dependent() -> None:
    bundle, observations, evidence = _raw_cb_dependent_evidence()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["cb_rate"]["activation_state"] == "active"
    assert bindings["cb_rate"]["probe_state"] == "executable"
    assert bindings["top10_cb_holders"]["activation_state"] == "active"
    assert bindings["cb_price_chg"]["activation_state"] == "paused"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("receipt_id", "receipt:0000000000000000000000000000000000000000000000000000000000000000"),
        ("data_through", "2026-08-11T21:22:20.352479Z"),
        ("schema_version", "9.9.9"),
        ("field", "wrong_field"),
    ],
)
def test_raw_probe_evidence_rejects_nonmatching_formal_seed_binding(
    field: str, value: str
) -> None:
    bundle, observations, evidence = _raw_cb_dependent_evidence()
    seed = evidence["seed_authorities"][0]
    assert isinstance(seed, dict)
    seed[field] = value
    with pytest.raises(
        ValueError,
        match="(?:does not match formal dependency seed|does not match source dataset)",
    ):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_rejects_unlisted_dependent_api() -> None:
    bundle, observations, evidence = _raw_cb_dependent_evidence()
    authorities = observations["dependency_seed_authorities"]
    assert isinstance(authorities, list)
    dependents = authorities[0]["dependent_api_names"]
    assert isinstance(dependents, list)
    authorities[0]["dependent_api_names"] = [
        name for name in dependents if name != "cb_rate"
    ]
    transport_observations = yaml.safe_dump(
        dict(observations),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")
    evidence["transport_observations_sha256"] = hashlib.sha256(
        transport_observations
    ).hexdigest()
    with pytest.raises(ValueError, match="dependent API is not formally listed"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_keeps_formal_empty_dependent_result_promotable() -> None:
    bundle, observations, evidence = _raw_cb_dependent_evidence(
        api_name="cb_share", state="valid_empty"
    )
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["cb_share"]["activation_state"] == "active"


def test_raw_probe_evidence_executable_scope_promotes_fresh_eligible_api_only() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="cb_basic",
    )
    evidence["scope"] = "executable"
    coverage = evidence["coverage"]
    assert isinstance(coverage, dict)
    coverage["planned"] = coverage["executable"]
    coverage["blocked"] = 0

    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )

    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["cb_basic"]["activation_state"] == "active"
    # The raw result is a strict executable subset; unrelated prior active
    # evidence remains active even though it is absent from this cohort.
    assert bindings["major_news"]["activation_state"] == "active"
    assert bindings["forecast"]["activation_state"] == "paused"


def test_raw_probe_evidence_executable_scope_rejects_non_executable_result_api() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="cb_basic",
    )
    evidence["scope"] = "executable"
    coverage = evidence["coverage"]
    assert isinstance(coverage, dict)
    coverage["planned"] = coverage["executable"]
    coverage["blocked"] = 0
    result = evidence["results"][0]
    assert isinstance(result, dict)
    source_result = {
        key: result[key]
        for key in (
            "api_name",
            "state",
            "provider_class",
            "row_count",
            "response_bytes",
            "response_sha256",
            "fields",
            "elapsed_ms",
        )
    }
    source_result["api_name"] = "balancesheet"
    result.update(source_result)

    with pytest.raises(ValueError, match="result API is not executable"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_rejects_unknown_scope() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="cb_basic",
    )
    evidence["scope"] = "all"

    with pytest.raises(ValueError, match="scope must be gaps or executable"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_accepts_asia_shanghai_partition_for_utc_previous_day() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    evidence["run_clock"] = "2026-08-11T19:15:55+00:00"
    evidence["started_at"] = "2026-08-11T19:16:00+00:00"
    evidence["finished_at"] = "2026-08-11T19:16:01+00:00"
    evidence["scheduled_partition"] = "20260812"

    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )

    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["major_news"]["activation_state"] == "active"


def test_raw_probe_evidence_rejects_asia_shanghai_local_date_mismatch() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    evidence["run_clock"] = "2026-08-11T19:15:55+00:00"
    evidence["started_at"] = "2026-08-11T19:16:00+00:00"
    evidence["finished_at"] = "2026-08-11T19:16:01+00:00"
    evidence["scheduled_partition"] = "20260811"

    with pytest.raises(ValueError, match="scheduled_partition must match run_clock"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_normalizes_sparse_probe_summary() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    results = evidence["results"]
    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    state = results[0]["state"]
    assert isinstance(state, str)
    evidence["summary"] = {state: 1}

    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )

    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["major_news"]["activation_state"] == "active"


def test_raw_probe_evidence_accepts_a_plan_subset_of_executable_contracts() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    coverage = evidence["coverage"]
    assert isinstance(coverage, dict)
    coverage["executable"] = int(coverage["executable"]) - 1
    coverage["blocked"] = int(coverage["blocked"]) + 1

    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=evidence,
        compilation_mode="preactivation_candidate",
    )

    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    assert bindings["major_news"]["activation_state"] == "active"
    assert bindings["forecast"]["activation_state"] == "paused"


def test_raw_probe_evidence_rejects_sparse_summary_count_drift() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    results = evidence["results"]
    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    state = results[0]["state"]
    assert isinstance(state, str)
    evidence["summary"] = {state: 2}

    with pytest.raises(ValueError, match="raw HTTPS probe evidence summary is inconsistent"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_rejects_redacted_results() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    results = evidence["results"]
    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    results[0]["response_redacted"] = True

    with pytest.raises(ValueError, match="redacted results are not promotable"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


def test_raw_probe_evidence_cli_binding_accepts_exact_observation_bytes(
    tmp_path: Path,
) -> None:
    observations_path = tmp_path / "observations.yaml"
    observations_path.write_text(
        "# preserve the immutable source bytes used by the probe\n"
        + yaml.safe_dump(_observations(), sort_keys=False),
        encoding="utf-8",
    )
    observations = _read_yaml(observations_path)
    evidence = build_synthetic_raw_probe_evidence(
        _bundle(),
        observations,
        promoted_api_name="major_news",
    )
    evidence["transport_observations_sha256"] = hashlib.sha256(
        observations_path.read_bytes()
    ).hexdigest()
    evidence_path = tmp_path / "raw-probe-evidence.yaml"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")

    normalized = compiler_module._load_activation_evidence(
        evidence_path,
        observations_document=observations,
        observations_sha256=hashlib.sha256(observations_path.read_bytes()).hexdigest(),
    )

    expected_semantic_hash = hashlib.sha256(
        yaml.safe_dump(
            dict(observations),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=100,
        ).encode("utf-8")
    ).hexdigest()
    assert normalized["transport_observations_sha256"] == expected_semantic_hash


def test_raw_probe_evidence_cli_binding_rejects_observation_byte_drift(
    tmp_path: Path,
) -> None:
    observations_path = tmp_path / "observations.yaml"
    observations_path.write_text(
        yaml.safe_dump(_observations(), sort_keys=False), encoding="utf-8"
    )
    observations = _read_yaml(observations_path)
    evidence = build_synthetic_raw_probe_evidence(
        _bundle(),
        observations,
        promoted_api_name="major_news",
    )
    evidence["transport_observations_sha256"] = "0" * 64
    evidence_path = tmp_path / "raw-probe-evidence.yaml"
    evidence_path.write_text(yaml.safe_dump(evidence, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        ValueError, match="raw HTTPS probe evidence transport observations drifted"
    ):
        compiler_module._load_activation_evidence(
            evidence_path,
            observations_document=observations,
            observations_sha256=hashlib.sha256(
                observations_path.read_bytes()
            ).hexdigest(),
        )


def test_raw_probe_evidence_rejects_planned_api_binding_drift() -> None:
    bundle = _bundle()
    observations = _observations()
    evidence = build_synthetic_raw_probe_evidence(
        bundle,
        observations,
        promoted_api_name="major_news",
    )
    evidence["api_names_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="planned API set does not match"):
        compile_provider_native_registry(
            bundle,
            observations_document=observations,
            activation_evidence_document=evidence,
            compilation_mode="preactivation_candidate",
        )


@pytest.mark.parametrize(
    "api_name",
    ("cb_factor_pro", "fund_factor_pro", "idx_factor_pro"),
)
def test_candidate_compiler_caps_active_row_budget_to_runtime_scan_limit(
    api_name: str,
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    observations = _observations()
    registry_document = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name=api_name,
        ),
        compilation_mode="preactivation_candidate",
    )
    output = tmp_path / "registry.yaml"
    output.write_text(render_registry(registry_document), encoding="utf-8")
    registry = load_dataset_registry(output)
    dataset = next(
        item
        for item in registry.datasets
        if registry.provider_binding(item.dataset_id, "tushare").api_name == api_name
    )
    binding = registry.provider_binding(dataset.dataset_id, "tushare")

    assert binding.activation_state == "active"
    assert binding.max_rows_per_attempt == 9_459
    _provider_scan_budget(dataset, binding)


def test_candidate_compiler_admits_wide_contract_with_bounded_row_budget() -> None:
    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
            promoted_api_name="stk_factor_pro",
        ),
        compilation_mode="preactivation_candidate",
    )
    binding = next(
        item["provider_bindings"][0]
        for item in registry["datasets"]
        if item["provider_bindings"][0]["api_name"] == "stk_factor_pro"
    )

    assert binding["entitlement_state"] == "active"
    assert binding["activation_state"] == "active"
    assert binding["max_rows_per_attempt"] < 10_000


def test_formal_mode_never_promotes_preactivation_evidence() -> None:
    bundle = _bundle()
    observations = _observations()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=observations,
        activation_evidence_document=build_synthetic_activation_evidence(
            bundle,
            observations,
        ),
    )
    active = {
        dataset["provider_bindings"][0]["api_name"]
        for dataset in registry["datasets"]
        if dataset["provider_bindings"][0]["activation_state"] == "active"
    }

    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert active == set(active_evidence)


def test_formal_mode_does_not_validate_or_depend_on_activation_evidence() -> None:
    registry = compile_provider_native_registry(
        _bundle(),
        observations_document=_observations(),
        activation_evidence_document={"runtime_artifact": "must_be_ignored"},
    )
    active = {
        dataset["provider_bindings"][0]["api_name"]
        for dataset in registry["datasets"]
        if dataset["provider_bindings"][0]["activation_state"] == "active"
    }

    active_evidence = _observations()["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert active == set(active_evidence)


def test_wave4_exact8_active_evidence_is_formal_and_fail_closed() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    wave4_ref = "server-evidence/ashare-wave4-current-exact11-20260812T0345CST"
    wave4_exact8 = {
        "cb_basic",
        "cn_schedule",
        "fund_factor_pro",
        "shibor_lpr",
        "st",
        "stk_alert",
        "stk_factor",
        "stk_high_shock",
    }
    assert {
        api_name for api_name, evidence_ref in active_evidence.items()
        if evidence_ref == wave4_ref
    } == wave4_exact8

    registry = compile_provider_native_registry(
        _bundle(), observations_document=observations
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    active = {
        api_name
        for api_name, binding in bindings.items()
        if binding["activation_state"] == "active"
    }
    assert len(active) == 127
    assert len(bindings) - len(active) == 63
    assert wave4_exact8 <= active
    assert not active & {"forecast", "pledge_detail", "stk_nineturn"}
    assert "forecast" not in active_evidence
    assert "pledge_detail" not in active_evidence
    assert "stk_nineturn" not in active_evidence


def test_wave5_batch_a_active_evidence_is_formal_and_fail_closed() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    batch_a_ref = "server-evidence/ashare-wave5-exact4-20260812T0618Z"
    batch_a = {"cb_rate", "cb_rating", "cb_share"}
    assert {api_name for api_name in batch_a if active_evidence[api_name] == batch_a_ref} == batch_a

    registry = compile_provider_native_registry(
        _bundle(), observations_document=observations
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    active = {
        api_name
        for api_name, binding in bindings.items()
        if binding["activation_state"] == "active"
    }
    assert len(active) == 127
    assert len(bindings) - len(active) == 63
    assert batch_a <= active
    assert "top10_cb_holders" in active
    assert not active & {"cb_price_chg", "forecast", "pledge_detail", "stk_nineturn"}
    assert active_evidence.get("top10_cb_holders") == batch_a_ref


def test_wave5_batch_b_top10_active_evidence_is_formal_and_fail_closed() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    batch_b_ref = "server-evidence/ashare-wave5-exact4-20260812T0618Z"
    assert active_evidence.get("top10_cb_holders") == batch_b_ref

    registry = compile_provider_native_registry(
        _bundle(), observations_document=observations
    )
    bindings = {
        dataset["provider_bindings"][0]["api_name"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }
    active = {
        api_name
        for api_name, binding in bindings.items()
        if binding["activation_state"] == "active"
    }
    assert len(active) == 127
    assert len(bindings) - len(active) == 63
    assert "top10_cb_holders" in active
    assert not active & {"cb_price_chg", "forecast", "pledge_detail", "stk_nineturn"}


def test_wave7_financial_exact7_valid_empty_evidence_is_formal_and_fail_closed() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    wave7_ref = "server-evidence/ashare-wave7-financial-exact7-20260812T1815CST"
    wave7_exact7 = {
        "balancesheet",
        "cashflow",
        "express",
        "fina_audit",
        "fina_indicator",
        "fina_mainbz",
        "income",
    }
    assert {api for api in wave7_exact7 if active_evidence.get(api) == wave7_ref} == wave7_exact7
    registry = compile_provider_native_registry(_bundle(), observations_document=observations)
    bindings = {d["provider_bindings"][0]["api_name"]: d["provider_bindings"][0] for d in registry["datasets"]}
    active = {api for api, binding in bindings.items() if binding["activation_state"] == "active"}
    assert len(bindings) == 190
    assert len(active) == 127
    assert len(bindings) - len(active) == 63
    assert wave7_exact7 <= active
    assert not active & {"pledge_stat", "rt_min_daily", "stk_mins", "stk_rewards", "top10_floatholders", "top10_holders"}
    assert not active & {"forecast", "pledge_detail", "stk_nineturn", "cb_price_chg"}


def test_wave7_tradedate_exact3_evidence_is_formal_and_fail_closed() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    ref = "server-evidence/ashare-wave7-tradedate-exact3-20260812T1851CST"
    exact3 = {"cyq_chips", "cyq_perf", "daily_basic"}
    assert {api for api in exact3 if active_evidence.get(api) == ref} == exact3
    registry = compile_provider_native_registry(_bundle(), observations_document=observations)
    bindings = {d["provider_bindings"][0]["api_name"]: d["provider_bindings"][0] for d in registry["datasets"]}
    active = {api for api, binding in bindings.items() if binding["activation_state"] == "active"}
    assert len(bindings) == 190
    assert len(active) == 127
    assert len(bindings) - len(active) == 63
    assert exact3 <= active
    assert not active & {"pledge_stat", "rt_min_daily", "stk_mins", "stk_rewards", "top10_floatholders", "top10_holders"}
    assert not active & {"forecast", "pledge_detail", "stk_nineturn", "cb_price_chg"}


def test_active_evidence_remains_fail_closed_for_blocked_observation_classes() -> None:
    observations = _observations()
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    for api_name in ("fund_company", "cb_price_chg", "fut_weekly_detail", "rt_etf_min"):
        with pytest.raises(ValueError, match="verified full-field contract"):
            candidate = deepcopy(observations)
            candidate["active_evidence"][api_name] = "server-evidence/test"  # type: ignore[index]
            _ = compile_provider_native_registry(
                _bundle(), observations_document=candidate
            )


def test_preactivation_mode_requires_explicit_activation_evidence() -> None:
    with pytest.raises(
        ValueError,
        match="preactivation candidate mode requires activation evidence",
    ):
        compile_provider_native_registry(
            _bundle(),
            observations_document=_observations(),
            compilation_mode="preactivation_candidate",
        )


def test_compiler_preserves_typed_variants_request_shape_fanout_pagination_and_budgets() -> (
    None
):
    bundle = _bundle()
    contract = _trade_calendar(bundle)
    template = contract["request_template"]
    assert isinstance(template, dict)
    template["limit"] = "100"
    contract["request_variants"] = [
        {"exchange": "SSE", "limit": "100"},
        {"exchange": "SZSE", "limit": 100},
        {"exchange": "BSE", "limit": 100.5},
        {"exchange": "OTHER", "limit": True},
    ]
    contract["request_shape"] = "dimension_fanout"
    contract["fanout"] = {
        "strategy": "dataset_field",
        "parameter": "exchange",
        "source_dataset_id": "cn.reference.exchanges",
        "source_field": "exchange",
        "batch_size": 10,
    }
    contract["pagination"] = {
        "strategy": "offset",
        "limit_parameter": "limit",
        "offset_parameter": "offset",
        "page_size": 5000,
        "max_pages": 20,
    }

    registry = compile_provider_native_registry(bundle)
    dataset = next(
        item
        for item in registry["datasets"]
        if item["dataset_id"] == "cn.market.trade_calendar"
    )
    binding = dataset["provider_bindings"][0]

    assert binding["request_variants"] == contract["request_variants"]
    assert binding["request_shape"] == "dimension_fanout"
    assert binding["fanout"] == contract["fanout"]
    assert binding["pagination"] == contract["pagination"]
    assert dataset["cadence_class"] == contract["cadence_class"]
    for key, value in contract["budgets"].items():
        assert binding[key] == value


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda item: item.update(cadence_class="daily"), "cadence_class"),
        (lambda item: item.update(request_shape="other"), "request_shape"),
        (
            lambda item: item.update(
                request_shape="entity_fanout", fanout={"strategy": "none"}
            ),
            "fanout.*dataset_field",
        ),
        (
            lambda item: item.update(
                pagination={
                    "strategy": "offset",
                    "limit_parameter": "offset",
                    "offset_parameter": "offset",
                    "page_size": 100,
                    "max_pages": 2,
                }
            ),
            "must differ",
        ),
        (
            lambda item: item["budgets"].update(max_rows_per_attempt=0),
            "positive integer",
        ),
        (
            lambda item: item.update(request_variants=[{"exchange": ["SSE"]}]),
            "finite JSON scalar",
        ),
        (
            lambda item: item.update(primary_key=["cal_date"]),
            "primary_key.*date_field",
        ),
        (
            lambda item: item.update(empty_data_policy="allowed"),
            "empty_data_policy.*forbidden",
        ),
        (
            lambda item: item.update(
                requested_fields=["cal_date", "is_open", "pretrade_date"]
            ),
            "requested_fields.*completeness",
        ),
    ],
)
def test_bundle_contracts_fail_closed(
    mutator: object,
    message: str,
) -> None:
    bundle = _bundle()
    mutator(_trade_calendar(bundle))  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_upstream_contract_bundle(bundle)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item.pop("input_fields"),
            "missing key.*input_fields",
        ),
        (
            lambda item: item["input_fields"].append(  # type: ignore[index,union-attr]
                deepcopy(item["input_fields"][0])  # type: ignore[index]
            ),
            "input_fields.*duplicate",
        ),
        (
            lambda item: item["input_fields"][0].update(extra=True),  # type: ignore[index,union-attr]
            "input_fields.*unknown key",
        ),
        (
            lambda item: item["input_fields"][0].pop("required"),  # type: ignore[index,union-attr]
            "missing key.*required",
        ),
        (
            lambda item: item["input_fields"][0].update(  # type: ignore[index,union-attr]
                declared_source_type="string"
            ),
            "declared_source_type.*one of",
        ),
        (
            lambda item: item["input_fields"][0].update(required="N"),  # type: ignore[index,union-attr]
            "required.*boolean or null",
        ),
        (
            lambda item: item.update(input_fields=[]),
            "input_fields.*must not be empty",
        ),
    ],
)
def test_input_field_contracts_fail_closed(
    mutator: object,
    message: str,
) -> None:
    bundle = _bundle()
    mutator(_trade_calendar(bundle))  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        load_upstream_contract_bundle(bundle)


def test_downstream_compiler_rejects_fully_legacy_bundle_without_input_fields() -> None:
    bundle = _bundle()
    for contract in bundle["contracts"]:
        contract.pop("input_fields")

    with pytest.raises(ValueError, match="missing input_fields"):
        compile_provider_native_registry(bundle)


def test_catalog_only_append_only_contract_can_defer_unverified_primary_key() -> None:
    bundle = _bundle()
    contract = _trade_calendar(bundle)
    contract["point_in_time"] = "append_only"
    contract["primary_key"] = []
    contract["response_completeness"] = None
    contract["empty_data_policy"] = "allowed"

    loaded = load_upstream_contract_bundle(bundle)
    normalized = next(
        item
        for item in loaded["contracts"]
        if item["dataset_id"] == "cn.market.trade_calendar"
    )

    assert normalized["primary_key"] == []
    assert normalized["response_completeness"] is None


def test_current_snapshot_contract_cannot_defer_primary_key() -> None:
    bundle = _bundle()
    contract = _trade_calendar(bundle)
    contract["primary_key"] = []
    contract["response_completeness"] = None

    with pytest.raises(ValueError, match="current_snapshot.*non-empty primary_key"):
        load_upstream_contract_bundle(bundle)


@pytest.mark.parametrize(
    "query_defaults",
    [
        {**DEFAULT_QUERY_DEFAULTS, "unknown": 1},
        {
            key: value
            for key, value in DEFAULT_QUERY_DEFAULTS.items()
            if key != "max_page_size"
        },
        {**DEFAULT_QUERY_DEFAULTS, "max_page_size": 0},
        {**DEFAULT_QUERY_DEFAULTS, "max_page_size": True},
    ],
)
def test_query_default_declaration_fails_closed(
    query_defaults: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        compile_provider_native_registry(_bundle(), query_defaults=query_defaults)


def test_repository_declarations_rebuild_the_checked_in_single_registry() -> None:
    contracts = _read_yaml(CONTRACT_PATH)
    observations = _read_yaml(OBSERVATIONS_PATH)

    first = compile_provider_native_registry(
        contracts,
        observations_document=observations,
        query_defaults=DEFAULT_QUERY_DEFAULTS,
    )
    second = compile_provider_native_registry(
        deepcopy(contracts),
        observations_document=deepcopy(observations),
        query_defaults=deepcopy(DEFAULT_QUERY_DEFAULTS),
    )

    assert first == second
    assert first == _read_yaml(TARGET_PATH)
    assert render_registry(first) == TARGET_PATH.read_text(encoding="utf-8")
    loaded = load_dataset_registry(TARGET_PATH)
    active_dataset_ids: set[str] = set()
    paused_dataset_ids: set[str] = set()
    request_shapes: set[str] = set()
    for dataset in loaded.datasets:
        binding = dataset.provider_bindings[0]
        request_shapes.add(binding.request_shape)
        assert binding.fanout is not None
        assert binding.pagination is not None
        if binding.activation_state == "active":
            assert binding.entitlement_state == "active"
            active_dataset_ids.add(dataset.dataset_id)
        else:
            assert binding.activation_state == "paused"
            paused_dataset_ids.add(dataset.dataset_id)
    active_evidence = observations["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert active_dataset_ids == {
        dataset["dataset_id"]
        for dataset in contracts["contracts"]
        if isinstance(dataset, dict) and dataset["api_name"] in active_evidence
    }
    assert len(active_dataset_ids) + len(paused_dataset_ids) == len(loaded.datasets)
    assert request_shapes == {
        "snapshot_or_date_range",
        "entity_fanout",
        "event_or_intraday_window",
        "dimension_fanout",
    }
    assert request_shapes.issubset(
        {
            "snapshot_or_date_range",
            "entity_fanout",
            "dimension_fanout",
            "event_or_intraday_window",
        }
    )


def test_cli_writes_external_registry_and_preserves_release_files(
    tmp_path: Path,
) -> None:
    activation_evidence_path = tmp_path / "synthetic-activation-evidence.yaml"
    activation_evidence_path.write_text(
        yaml.safe_dump(
            build_synthetic_activation_evidence(
                _bundle(),
                _observations(),
                promoted_api_name="moneyflow",
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    protected_release_paths = (
        CONTRACT_PATH,
        OBSERVATIONS_PATH,
        activation_evidence_path,
        TARGET_PATH,
    )
    before = {path: path.read_bytes() for path in protected_release_paths}
    output = tmp_path / "registry.yaml"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--upstream-contracts",
            str(CONTRACT_PATH),
            "--observations",
            str(OBSERVATIONS_PATH),
            "--activation-evidence",
            str(activation_evidence_path),
            "--compilation-mode",
            "preactivation_candidate",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == ""
    assert completed.stderr == ""
    loaded = load_dataset_registry(output)
    active_evidence = _observations()["active_evidence"]
    assert isinstance(active_evidence, dict)
    assert (
        sum(
            dataset.provider_bindings[0].activation_state == "active"
            for dataset in loaded.datasets
        )
        == len(active_evidence)
    )
    # The checked-in target is already the current compiled registry.  The
    # external preactivation compile must be reproducible rather than mutate
    # or manufacture a second registry variant.
    assert output.read_bytes() == before[TARGET_PATH]
    assert before == {path: path.read_bytes() for path in protected_release_paths}


def test_cli_refuses_repository_owned_activation_evidence(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--upstream-contracts",
            str(CONTRACT_PATH),
            "--observations",
            str(OBSERVATIONS_PATH),
            "--activation-evidence",
            str(CONTRACT_PATH),
            "--compilation-mode",
            "preactivation_candidate",
            "--output",
            str(tmp_path / "candidate-registry.yaml"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "activation evidence must be outside the repository" in completed.stderr


@pytest.mark.parametrize(
    "output",
    (TARGET_PATH, ROOT / "preactivation-candidate.registry.yaml"),
)
def test_cli_refuses_candidate_mode_inside_repository(
    output: Path,
    tmp_path: Path,
) -> None:
    activation_evidence_path = tmp_path / "synthetic-activation-evidence.yaml"
    activation_evidence_path.write_text(
        yaml.safe_dump(
            build_synthetic_activation_evidence(_bundle(), _observations()),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--upstream-contracts",
            str(CONTRACT_PATH),
            "--observations",
            str(OBSERVATIONS_PATH),
            "--activation-evidence",
            str(activation_evidence_path),
            "--compilation-mode",
            "preactivation_candidate",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert (
        "preactivation candidate cannot overwrite the checked registry"
        in completed.stderr
    )
    assert output == TARGET_PATH or not output.exists()


def test_operations_registry_verification_cannot_write_or_follow_current() -> None:
    source = OPERATIONS_PATH.read_text(encoding="utf-8")
    section = source.split("## 运行顺序", 1)[1].split("## 发布门禁", 1)[0]

    assert 'FINAL="/opt/investment/releases/tradingdatas/$TARGET_COMMIT"' in section
    assert 'test ! -L "$FINAL"' in section
    assert (
        'REGISTRY_VERIFY="$(umask 077 && mktemp '
        '/tmp/tradingdatas-registry.verify.XXXXXX)"' in section
    )
    assert '"$FINAL/tools/compile_provider_native_registry.py"' in section
    assert '--output "$REGISTRY_VERIFY"' in section
    assert "cmp --silent" in section
    assert "trap 'rm -f -- \"$REGISTRY_VERIFY\"' EXIT" in section
    assert "/current/tools/compile_provider_native_registry.py" not in section


def test_cli_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    observations = tmp_path / "observations.yaml"
    observations.write_text(
        """\
version: 1
provider: tushare
provider: tushare
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--observations",
            str(observations),
            "--output",
            str(tmp_path / "registry.yaml"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "duplicate YAML mapping key: provider" in completed.stderr
