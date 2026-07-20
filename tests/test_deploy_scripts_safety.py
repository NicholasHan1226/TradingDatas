from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ENV_EXAMPLE = ROOT / ".env.example"


def test_deploy_tree_contains_only_the_internal_v1_service_surface() -> None:
    files = {
        path.relative_to(DEPLOY).as_posix()
        for path in DEPLOY.rglob("*")
        if path.is_file()
    }

    assert files == {
        "runtime_paths.sh",
        "systemd/tradingdatas-provider-native-collect.service",
        "systemd/tradingdatas-provider-native-collect.timer",
        "systemd/tradingdatas-v1-internal.service",
        "tradingdatas_internal.env",
    }


def test_deploy_tree_has_no_public_ingress_or_legacy_scheduler() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in DEPLOY.rglob("*") if path.is_file()
    ).lower()

    for forbidden in (
        "cloudflared",
        "nginx",
        "proxy_pass",
        "crontab",
        "sharedsignals",
        "location /tushare",
        "/source_status",
        "/opening_gate",
    ):
        assert forbidden not in text


def test_deploy_tree_has_one_provider_neutral_scheduler_surface() -> None:
    service = (
        DEPLOY / "systemd" / "tradingdatas-provider-native-collect.service"
    ).read_text(encoding="utf-8")
    timer = (
        DEPLOY / "systemd" / "tradingdatas-provider-native-collect.timer"
    ).read_text(encoding="utf-8")

    assert service.count("ExecStart=") == 1
    assert "tools/run_provider_native_schedule.py" in service
    assert "--execute" in service
    assert "https://api.quicksync.cn" in service
    assert "TUSHARE_TOKEN_FILE=/etc/tradingdatas/quicksync.token" in service
    assert "TUSHARE_TOKEN=" not in service
    assert "QUICKSYNC_TOKEN=" not in service
    assert "dataset_id" not in service.lower()
    assert "api_name" not in service.lower()
    assert "OnCalendar=*-*-* *:0/5:00" in timer
    assert "Unit=tradingdatas-provider-native-collect.service" in timer
    assert "WantedBy=timers.target" in timer


def test_env_example_uses_only_file_backed_quicksync_credentials() -> None:
    source = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "TUSHARE_API_URL=https://api.quicksync.cn" in source
    assert "TUSHARE_TOKEN_FILE=/etc/tradingdatas/quicksync.token" in source
    assert "TUSHARE_TOKEN=" not in source
    assert "QUICKSYNC_TOKEN=" not in source


def _check_runtime_paths(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    helper = DEPLOY / "runtime_paths.sh"
    command = (
        f'source "{helper}"; tradingdatas_load_runtime_paths; '
        'load_rc=$?; [ "$load_rc" -eq 0 ] || exit "$load_rc"; '
        "tradingdatas_assert_runtime_paths"
    )
    return subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_runtime_path_contract_accepts_one_canonical_data_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    data_root = tmp_path / "data"
    root.mkdir()
    (root / "config").mkdir()
    (root / "config" / "provider_native_dataset_registry.yaml").touch()
    (data_root / "read_model").mkdir(parents=True)
    (data_root / "read_model" / "provider_native.sqlite").touch()
    env = {
        "TRADINGDATAS_ROOT": str(root),
        "TRADINGDATAS_ENV_FILE": str(tmp_path / "missing.env"),
        "TRADINGDATAS_DATA_ROOT": str(data_root),
        "TRADINGDATAS_DB_PATH": str(
            data_root / "read_model" / "provider_native.sqlite"
        ),
        "TRADINGDATAS_REGISTRY_PATH": str(
            root / "config" / "provider_native_dataset_registry.yaml"
        ),
        "TRADINGDATAS_DATA_MOUNT": str(tmp_path),
        "TRADINGDATAS_REQUIRE_MOUNT": "0",
    }

    result = _check_runtime_paths(env)

    assert result.returncode == 0, result.stderr


def test_runtime_path_contract_rejects_relative_cross_root_or_symlink_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    data_root = tmp_path / "data"
    base = {
        "TRADINGDATAS_ROOT": str(root),
        "TRADINGDATAS_ENV_FILE": str(tmp_path / "missing.env"),
        "TRADINGDATAS_DATA_ROOT": str(data_root),
        "TRADINGDATAS_DB_PATH": str(
            data_root / "read_model" / "provider_native.sqlite"
        ),
        "TRADINGDATAS_REGISTRY_PATH": str(
            root / "config" / "provider_native_dataset_registry.yaml"
        ),
        "TRADINGDATAS_DATA_MOUNT": str(tmp_path),
        "TRADINGDATAS_REQUIRE_MOUNT": "0",
    }

    relative = _check_runtime_paths(
        {**base, "TRADINGDATAS_REGISTRY_PATH": "config/registry.yaml"}
    )
    assert relative.returncode == 78
    assert "must be absolute" in relative.stderr

    cross_root = _check_runtime_paths(
        {**base, "TRADINGDATAS_DB_PATH": str(tmp_path / "other.sqlite")}
    )
    assert cross_root.returncode == 78
    assert "must remain below TRADINGDATAS_DATA_ROOT" in cross_root.stderr

    data_root.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    linked_read_model = data_root / "read_model"
    linked_read_model.symlink_to(target, target_is_directory=True)
    symlink = _check_runtime_paths(base)
    assert symlink.returncode == 78
    assert "may not be a symlink" in symlink.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRADINGDATAS_DATA_ROOT", "/tmp/tradingdatas/../escape"),
        ("TRADINGDATAS_DB_PATH", "/tmp/tradingdatas//provider.sqlite"),
        ("TRADINGDATAS_DATA_MOUNT", "/tmp/tradingdatas/./mount"),
        ("TRADINGDATAS_ROOT", "/tmp/tradingdatas-root/"),
    ],
)
def test_runtime_path_contract_rejects_noncanonical_lexical_paths(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    root = tmp_path / "repo"
    data_root = tmp_path / "data"
    base = {
        "TRADINGDATAS_ROOT": str(root),
        "TRADINGDATAS_ENV_FILE": str(tmp_path / "missing.env"),
        "TRADINGDATAS_DATA_ROOT": str(data_root),
        "TRADINGDATAS_DB_PATH": str(
            data_root / "read_model" / "provider_native.sqlite"
        ),
        "TRADINGDATAS_REGISTRY_PATH": str(
            root / "config" / "provider_native_dataset_registry.yaml"
        ),
        "TRADINGDATAS_DATA_MOUNT": str(tmp_path),
        "TRADINGDATAS_REQUIRE_MOUNT": "0",
    }

    result = _check_runtime_paths({**base, name: value})

    assert result.returncode == 78
    assert "canonical" in result.stderr


def test_runtime_path_contract_rejects_symlinked_parent_and_mount_escape(
    tmp_path: Path,
) -> None:
    physical_root = tmp_path / "physical-root"
    physical_root.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(physical_root, target_is_directory=True)
    data_root = tmp_path / "data"
    base = {
        "TRADINGDATAS_ROOT": str(linked_parent / "repo"),
        "TRADINGDATAS_ENV_FILE": str(tmp_path / "missing.env"),
        "TRADINGDATAS_DATA_ROOT": str(data_root),
        "TRADINGDATAS_DB_PATH": str(
            data_root / "read_model" / "provider_native.sqlite"
        ),
        "TRADINGDATAS_REGISTRY_PATH": str(
            linked_parent / "repo" / "config" / "registry.yaml"
        ),
        "TRADINGDATAS_DATA_MOUNT": str(tmp_path),
        "TRADINGDATAS_REQUIRE_MOUNT": "0",
    }

    linked = _check_runtime_paths(base)
    escaped_root = tmp_path.parent / "outside"
    escaped = _check_runtime_paths(
        {
            **base,
            "TRADINGDATAS_ROOT": str(tmp_path / "repo"),
            "TRADINGDATAS_REGISTRY_PATH": str(tmp_path / "repo/config/registry.yaml"),
            "TRADINGDATAS_DATA_ROOT": str(escaped_root),
            "TRADINGDATAS_DB_PATH": str(
                escaped_root / "read_model" / "provider_native.sqlite"
            ),
        }
    )

    assert linked.returncode == 78
    assert "symlink" in linked.stderr
    assert escaped.returncode == 78
    assert "DATA_MOUNT" in escaped.stderr


def test_runtime_path_contract_does_not_accept_old_environment_names() -> None:
    source = (DEPLOY / "runtime_paths.sh").read_text(encoding="utf-8")

    assert "TRADINGDATAS_" in source
    assert "SHAREDSIGNALS_" not in source
    assert "SharedSignals" not in source
    assert "sharedsignals" not in source


@pytest.mark.parametrize(
    "invalid_tail",
    [
        "BROKEN_LINE",
        "SHAREDSIGNALS_OLD_KEY=value",
        "TRADINGDATAS_TEST_GOOD=duplicate",
        "TRADINGDATAS_ROOT=/private/tmp/redirected-root",
    ],
    ids=["malformed", "old-key", "duplicate-key", "root-redirect"],
)
def test_runtime_env_parse_failure_has_zero_partial_environment_mutation(
    tmp_path: Path,
    invalid_tail: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    env_file = tmp_path / "runtime.env"
    env_file.write_text(
        f"TRADINGDATAS_API_PORT=19000\nTRADINGDATAS_TEST_GOOD=staged\n{invalid_tail}\n",
        encoding="utf-8",
    )
    helper = DEPLOY / "runtime_paths.sh"
    command = (
        'TRADINGDATAS_API_PORT="18082"; unset TRADINGDATAS_TEST_GOOD; '
        f'source "{helper}"; '
        "tradingdatas_load_runtime_paths >/dev/null 2>&1; load_rc=$?; "
        '[ "$load_rc" -eq 78 ] || exit 90; '
        '[ "$TRADINGDATAS_API_PORT" = "18082" ] || exit 91; '
        '[ -z "${TRADINGDATAS_TEST_GOOD+x}" ] || exit 92'
    )

    result = subprocess.run(
        ["bash", "-c", command],
        env={
            **os.environ,
            "TRADINGDATAS_ROOT": str(root),
            "TRADINGDATAS_ENV_FILE": str(env_file),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
