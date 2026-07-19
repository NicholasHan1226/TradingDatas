from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "tradingdatas_internal.env"
UNIT = ROOT / "deploy" / "systemd" / "tradingdatas-v1-internal.service"


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
        "TRADINGDATAS_REGISTRY_PATH": (
            "/opt/investment/releases/tradingdatas/current/"
            "config/provider_native_dataset_registry.yaml"
        ),
        "TRADINGDATAS_ROOT": "/opt/investment/releases/tradingdatas/current",
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
