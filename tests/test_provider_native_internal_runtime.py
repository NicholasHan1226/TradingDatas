from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "tradingdatas_internal.env"
UNIT = ROOT / "deploy" / "systemd" / "tradingdatas-v1-internal.service"
ENV_EXAMPLE = ROOT / ".env.example"


def _profile_values() -> dict[str, str]:
    lines = [
        line
        for line in PROFILE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return dict(line.split("=", 1) for line in lines)


def test_git_owned_internal_profile_is_loopback_only_and_secret_free() -> None:
    values = _profile_values()

    assert values == {
        "TRADINGDATAS_API_HOST": "127.0.0.1",
        "TRADINGDATAS_API_PORT": "18082",
        "TRADINGDATAS_API_SURFACE": "v1-catalog-query-only",
        "TRADINGDATAS_DATA_ROOT": "/opt/investment-data/tradingdatas",
        "TRADINGDATAS_DB_PATH": (
            "/opt/investment-data/tradingdatas/read_model/provider_native.sqlite"
        ),
    }
    upper = PROFILE.read_text(encoding="utf-8").upper()
    for forbidden in (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PRIVATE_KEY",
        "ACCESS_KEY",
        "TUSHARE_",
    ):
        assert forbidden not in upper


def test_runtime_example_cannot_redirect_release_owned_contracts() -> None:
    source = ENV_EXAMPLE.read_text(encoding="utf-8")

    for forbidden in (
        "TRADINGDATAS_ROOT=",
        "TRADINGDATAS_REGISTRY_PATH=",
        "TRADINGDATAS_SCHEDULE_PATH=",
    ):
        assert forbidden not in source
    assert (
        "TRADINGDATAS_DB_PATH=/opt/investment-data/tradingdatas/"
        "read_model/provider_native.sqlite" in source
    )
    assert "TUSHARE_TOKEN_FILE=/etc/tradingdatas/quicksync.token" in source


def test_internal_unit_is_authenticated_loopback_only_and_read_only() -> None:
    source = UNIT.read_text(encoding="utf-8")

    assert "Description=TradingDatas V1 internal catalog/query API" in source
    assert "WorkingDirectory=/opt/investment/releases/tradingdatas/current" in source
    assert (
        "EnvironmentFile=/opt/investment/releases/tradingdatas/current/"
        "deploy/tradingdatas_internal.env" in source
    )
    assert "EnvironmentFile=/etc/tradingdatas/internal-api.env" in source
    assert "ConditionPathExists=/etc/tradingdatas/api_tokens.json" in source
    assert "ConditionPathExists=/etc/tradingdatas/token_salt" in source
    assert (
        'Environment="TRADINGDATAS_TOKEN_HASH_FILE='
        '/etc/tradingdatas/api_tokens.json"' in source
    )
    assert (
        'Environment="TRADINGDATAS_TOKEN_SALT_FILE='
        '/etc/tradingdatas/token_salt"' in source
    )
    assert "TRADINGDATAS_LOCALHOST_BYPASS" not in source
    assert (
        "ExecStart=/opt/tradingdatas/venv/bin/python3 "
        "/opt/investment/releases/tradingdatas/current/"
        "tools/serve_provider_native_v1.py" in source
    )
    assert "ReadOnlyPaths=/opt/investment-data/tradingdatas" in source
    assert "ReadWritePaths=" not in source
    assert "NoNewPrivileges=true" in source
    assert "ProtectSystem=strict" in source
    assert "PrivateTmp=true" in source
    assert "IPAddressDeny=any" in source
    assert "IPAddressAllow=localhost" in source
    assert "TRADINGDATAS_ROOT" not in source
    assert "TRADINGDATAS_REGISTRY_PATH" not in source
    assert "TRADINGDATAS_SCHEDULE_PATH" not in source


def test_internal_runtime_has_no_old_identity_ingress_or_scheduler() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (PROFILE, UNIT))

    for forbidden in (
        "SHAREDSIGNALS_",
        "SharedSignals",
        "sharedsignals",
        "cloudflared",
        "nginx",
        "API_PORT=8082",
        ":8082",
        "provider-native-collect",
        "probe.timer",
    ):
        assert forbidden not in source


def test_current_entry_binds_registry_and_schedule_to_one_physical_release(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    current.symlink_to(ROOT, target_is_directory=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(current)
    for name in (
        "TRADINGDATAS_ROOT",
        "TRADINGDATAS_REGISTRY_PATH",
    ):
        environment.pop(name, None)
    environment["TRADINGDATAS_SCHEDULE_PATH"] = (
        "/opt/investment/releases/tradingdatas/current/"
        "config/provider_native_schedule.yaml"
    )
    script = """
import json
from pathlib import Path
import dataset_registry
from tools import run_provider_native_schedule

registry = dataset_registry.load_runtime_dataset_registry()
print(json.dumps({
    "dataset_count": len(registry.datasets),
    "module_root": str(Path(dataset_registry.__file__).resolve().parent),
    "registry": str(dataset_registry.runtime_dataset_registry_path()),
    "schedule": str(run_provider_native_schedule.DEFAULT_SCHEDULE_CONFIG),
}, sort_keys=True))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["dataset_count"] == 190
    assert Path(payload["module_root"]) == ROOT
    assert Path(payload["registry"]) == (
        ROOT / "config/provider_native_dataset_registry.yaml"
    )
    assert Path(payload["schedule"]) == ROOT / "config/provider_native_schedule.yaml"
