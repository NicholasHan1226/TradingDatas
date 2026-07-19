from __future__ import annotations

from copy import deepcopy
import hashlib
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
ACTIVATION_PATH = ROOT / "config" / "provider_native_activation.yaml"
TARGET_PATH = ROOT / "config" / "provider_native_dataset_registry.yaml"


def _read_yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle() -> dict[str, object]:
    return deepcopy(_read_yaml(CONTRACT_PATH))


def _activation(
    *,
    dataset_id: str = "cn.market.trade_calendar",
    provider: str = "tushare",
    entitlement_state: str = "active",
    activation_state: str = "active",
    evidence_ref: object = "server-evidence/compiler-test",
) -> dict[str, object]:
    return {
        "version": 1,
        "activations": [
            {
                "dataset_id": dataset_id,
                "provider": provider,
                "entitlement_state": entitlement_state,
                "activation_state": activation_state,
                "evidence_ref": evidence_ref,
            }
        ],
    }


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
        "activation_document",
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


def test_activation_declaration_is_the_only_entitlement_and_activation_authority() -> (
    None
):
    registry = compile_provider_native_registry(
        _bundle(), activation_document=_activation()
    )
    bindings = {
        dataset["dataset_id"]: dataset["provider_bindings"][0]
        for dataset in registry["datasets"]
    }

    assert bindings["cn.market.trade_calendar"]["entitlement_state"] == "active"
    assert bindings["cn.market.trade_calendar"]["activation_state"] == "active"
    assert bindings["cn.equity.daily"]["entitlement_state"] == "unknown"
    assert bindings["cn.equity.daily"]["activation_state"] == "paused"


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
    ("mutator", "message"),
    [
        (lambda item: item.update(entitlement_state="maybe"), "entitlement_state"),
        (lambda item: item.update(activation_state="scheduled"), "activation_state"),
        (
            lambda item: item.update(entitlement_state="locked"),
            "activation_state=active requires entitlement_state=active",
        ),
        (lambda item: item.update(evidence_ref=None), "requires evidence_ref"),
        (lambda item: item.update(evidence_ref="../secret"), "evidence_ref"),
        (lambda item: item.update(dataset_id="cn.unknown"), "unknown activation"),
    ],
)
def test_activation_declarations_fail_closed(mutator: object, message: str) -> None:
    activation = _activation()
    entry = activation["activations"][0]  # type: ignore[index]
    mutator(entry)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        compile_provider_native_registry(_bundle(), activation_document=activation)


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
    activation = _read_yaml(ACTIVATION_PATH)

    first = compile_provider_native_registry(
        contracts,
        activation_document=activation,
        query_defaults=DEFAULT_QUERY_DEFAULTS,
    )
    second = compile_provider_native_registry(
        deepcopy(contracts),
        activation_document=deepcopy(activation),
        query_defaults=deepcopy(DEFAULT_QUERY_DEFAULTS),
    )

    assert first == second
    assert first == _read_yaml(TARGET_PATH)
    assert render_registry(first) == TARGET_PATH.read_text(encoding="utf-8")
    loaded = load_dataset_registry(TARGET_PATH)
    active_dataset_ids: set[str] = set()
    paused_dataset_ids: set[str] = set()
    for dataset in loaded.datasets:
        binding = dataset.provider_bindings[0]
        assert binding.request_shape == "snapshot_or_date_range"
        assert binding.fanout is not None
        assert binding.pagination is not None
        if binding.activation_state == "active":
            assert binding.entitlement_state == "active"
            active_dataset_ids.add(dataset.dataset_id)
        else:
            assert binding.activation_state == "paused"
            assert binding.entitlement_state == "unknown"
            paused_dataset_ids.add(dataset.dataset_id)
    assert active_dataset_ids == {
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    }
    assert len(paused_dataset_ids) == 187


def test_cli_reads_only_declarations_writes_one_registry_and_preserves_inputs(
    tmp_path: Path,
) -> None:
    before = {path: _sha256(path) for path in (CONTRACT_PATH, ACTIVATION_PATH)}
    output = tmp_path / "registry.yaml"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--upstream-contracts",
            str(CONTRACT_PATH),
            "--activation",
            str(ACTIVATION_PATH),
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
    assert output.read_text(encoding="utf-8") == TARGET_PATH.read_text(encoding="utf-8")
    assert before == {path: _sha256(path) for path in before}


def test_cli_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    activation = tmp_path / "activation.yaml"
    activation.write_text(
        """\
version: 1
activations:
- dataset_id: cn.market.trade_calendar
  provider: tushare
  provider: tushare
  entitlement_state: active
  activation_state: active
  evidence_ref: server-evidence/duplicate
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--activation",
            str(activation),
            "--output",
            str(tmp_path / "registry.yaml"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "duplicate YAML mapping key: provider" in completed.stderr
