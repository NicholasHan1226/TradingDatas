from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess
import sys

import pytest

import data_plane_runtime
import dataset_registry
import tools.collect_provider_dataset as provider_runner


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_SHA256 = (
    "d6f58ff1934ee568d8b774ea283b51d67a915bdc66f9bb8c964624524d4d64a5"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_registry_bytes_and_legacy_loader_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, raising=False)

    assert _sha256(dataset_registry.DATASET_REGISTRY_PATH) == DEFAULT_REGISTRY_SHA256
    assert (
        dataset_registry.runtime_dataset_registry_path()
        == dataset_registry.DATASET_REGISTRY_PATH
    )
    assert (
        dataset_registry.load_runtime_dataset_registry().resolve("cn.equity.daily")
        == dataset_registry.load_dataset_registry().resolve("cn.equity.daily")
    )


def test_compiler_deterministically_rebuilds_checked_in_target_registry() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "compile_provider_native_registry.py"),
            "--kind",
            "candidate",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    assert completed.stderr == b""
    assert completed.stdout == (
        dataset_registry.PROVIDER_NATIVE_DATASET_REGISTRY_PATH.read_bytes()
    )


def test_target_registry_is_fully_dormant_and_provider_native_where_resolved() -> None:
    registry = dataset_registry.load_dataset_registry(
        dataset_registry.PROVIDER_NATIVE_DATASET_REGISTRY_PATH
    )
    bindings = tuple(
        registry.provider_binding(dataset.dataset_id, "tushare")
        for dataset in registry.datasets
    )
    provider_native = tuple(
        dataset
        for dataset in registry.datasets
        if dataset.read_model_adapter.storage_kind == "provider_native_rows"
    )
    unresolved = tuple(
        dataset
        for dataset in registry.datasets
        if dataset.read_model_adapter.storage_kind != "provider_native_rows"
    )

    assert [dataset.dataset_id for dataset in registry.datasets] == [
        "cn.market.trade_calendar"
    ]
    assert len(provider_native) == 1
    assert unresolved == ()
    assert all(binding.activation_state == "paused" for binding in bindings)
    assert all(binding.entitlement_state != "active" for binding in bindings)
    assert all(
        registry.provider_binding(dataset.dataset_id, "tushare").requested_fields
        == ()
        for dataset in provider_native
    )
    completeness = bindings[0].response_completeness
    assert completeness is not None
    assert completeness.strategy == "one_row_per_calendar_date"
    assert completeness.date_field == "cal_date"


def test_runtime_selector_accepts_only_the_checked_in_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = dataset_registry.PROVIDER_NATIVE_DATASET_REGISTRY_PATH
    monkeypatch.setenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, str(target))

    assert dataset_registry.runtime_dataset_registry_path() == target
    assert len(dataset_registry.load_runtime_dataset_registry().datasets) == 1

    for rejected in (
        "config/provider_native_dataset_registry.yaml",
        str(dataset_registry.DATASET_REGISTRY_PATH),
        str(tmp_path / "untrusted.yaml"),
        f"{target.parent}/../config/{target.name}",
        f"{target} ",
    ):
        monkeypatch.setenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, rejected)
        with pytest.raises(ValueError):
            dataset_registry.runtime_dataset_registry_path()


def test_runtime_selector_rejects_missing_link_and_non_regular_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(
        dataset_registry,
        "PROVIDER_NATIVE_DATASET_REGISTRY_PATH",
        missing,
    )
    monkeypatch.setenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, str(missing))
    with pytest.raises(FileNotFoundError):
        dataset_registry.runtime_dataset_registry_path()

    link = tmp_path / "link.yaml"
    link.symlink_to(dataset_registry.DATASET_REGISTRY_PATH)
    monkeypatch.setattr(
        dataset_registry,
        "PROVIDER_NATIVE_DATASET_REGISTRY_PATH",
        link,
    )
    monkeypatch.setenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, str(link))
    with pytest.raises(ValueError, match="symlink"):
        dataset_registry.runtime_dataset_registry_path()

    directory = tmp_path / "registry-directory"
    directory.mkdir()
    monkeypatch.setattr(
        dataset_registry,
        "PROVIDER_NATIVE_DATASET_REGISTRY_PATH",
        directory,
    )
    monkeypatch.setenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, str(directory))
    with pytest.raises(ValueError, match="regular file"):
        dataset_registry.runtime_dataset_registry_path()


def test_data_plane_runtime_uses_process_selected_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        dataset_registry.DATASET_REGISTRY_PATH_ENV,
        str(dataset_registry.PROVIDER_NATIVE_DATASET_REGISTRY_PATH),
    )
    monkeypatch.setenv(
        "SHAREDSIGNALS_CURSOR_SIGNING_KEY",
        "dual-registry-test-signing-key-32-bytes-minimum",
    )
    runtime_module = importlib.reload(data_plane_runtime)
    runtime_module._reset_data_plane_runtime_for_tests()
    try:
        runtime = runtime_module.build_data_plane_runtime()
        assert len(runtime.registry.datasets) == 1
        assert runtime.catalog._registry is runtime.registry  # noqa: SLF001
        assert runtime.query._registry is runtime.registry  # noqa: SLF001
        assert runtime.legacy_registry is not runtime.registry
        assert runtime.legacy._registry is runtime.legacy_registry  # noqa: SLF001
        assert runtime.legacy_query._registry is runtime.legacy_registry  # noqa: SLF001
        assert runtime.legacy_query is not runtime.query
        assert (
            runtime.registry.resolve(
                "tushare.trade_cal"
            ).read_model_adapter.primary_table
            == "provider_dataset_rows"
        )
        assert (
            runtime.legacy_registry.resolve(
                "tushare.daily"
            ).read_model_adapter.primary_table
            == "market_bars_daily"
        )
        assert (
            runtime.legacy_registry.resolve(
                "cn.equity.security_master"
            ).read_model_adapter.primary_table
            == "market_assets"
        )
    finally:
        runtime_module._reset_data_plane_runtime_for_tests()


def test_data_plane_runtime_without_selector_keeps_legacy_default_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(dataset_registry.DATASET_REGISTRY_PATH_ENV, raising=False)
    monkeypatch.setenv(
        "SHAREDSIGNALS_CURSOR_SIGNING_KEY",
        "dual-registry-test-signing-key-32-bytes-minimum",
    )
    runtime_module = importlib.reload(data_plane_runtime)
    runtime_module._reset_data_plane_runtime_for_tests()
    try:
        runtime = runtime_module.build_data_plane_runtime()
        assert runtime.registry is runtime.legacy_registry
        assert runtime.query._registry is runtime.registry  # noqa: SLF001
        assert runtime.legacy._registry is runtime.legacy_registry  # noqa: SLF001
        assert runtime.legacy_query._registry is runtime.legacy_registry  # noqa: SLF001
        assert runtime.legacy_query is not runtime.query
        assert (
            runtime.legacy_registry.resolve(
                "tushare.daily"
            ).read_model_adapter.primary_table
            == "market_bars_daily"
        )
    finally:
        runtime_module._reset_data_plane_runtime_for_tests()


def test_collection_cli_has_no_registry_path_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        provider_runner.parse_args(
            [
                "--db-path",
                "/tmp/not-opened.sqlite",
                "--dataset-id",
                "cn.equity.daily",
                "--request-window-json",
                "{}",
                "--registry",
                "/tmp/untrusted.yaml",
            ]
        )

    assert raised.value.code == 2
    assert "unrecognized arguments: --registry" in capsys.readouterr().err
