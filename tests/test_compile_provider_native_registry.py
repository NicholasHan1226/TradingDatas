from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from dataset_registry import load_dataset_registry
import tools.compile_provider_native_registry as compiler_module
from tools.compile_provider_native_registry import (
    DEFAULT_QUERY_DEFAULTS,
    compile_provider_native_registry,
    load_upstream_contract_bundle,
    render_registry,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
OBSERVATIONS_PATH = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
TARGET_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"
OPERATIONS_PATH = ROOT / "docs" / "OPERATIONS.md"


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


def test_compiler_has_single_registry_authority_and_no_legacy_inputs() -> None:
    parameters = inspect.signature(compile_provider_native_registry).parameters

    assert tuple(parameters) == (
        "upstream_contracts",
        "observations_document",
        "query_defaults",
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
    assert bindings["cn.dataset.adj_factor"]["activation_state"] == "paused"
    assert bindings["cn.dataset.cb_price_chg"]["entitlement_state"] == "locked"
    assert bindings["cn.dataset.etf_sh_cons"]["entitlement_state"] == "excluded"


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
    assert active_dataset_ids == {
        "cn.dataset.index_classify",
        "cn.dataset.sw_daily",
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }
    assert len(paused_dataset_ids) == 185
    assert request_shapes == {
        "snapshot_or_date_range",
        "entity_fanout",
        "event_or_intraday_window",
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
    protected_release_paths = (CONTRACT_PATH, OBSERVATIONS_PATH, TARGET_PATH)
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
    assert output.read_bytes() == before[TARGET_PATH]
    assert before == {path: path.read_bytes() for path in protected_release_paths}


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
