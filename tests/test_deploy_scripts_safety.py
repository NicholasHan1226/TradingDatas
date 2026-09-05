from __future__ import annotations

from pathlib import Path


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
        "crypto/tradingdatas_crypto_internal.env",
        "systemd/tradingdatas-crypto-binance-book-ticker.service",
        "systemd/tradingdatas-crypto-binance-book-ticker.timer",
        "systemd/tradingdatas-crypto-binance-collect-retry.service",
        "systemd/tradingdatas-crypto-binance-collect-retry.timer",
        "systemd/tradingdatas-crypto-binance-collect.service",
        "systemd/tradingdatas-crypto-binance-collect.timer",
        "systemd/tradingdatas-crypto-binance-oi-dump-collect.service",
        "systemd/tradingdatas-crypto-binance-oi-dump-collect.timer",
        "systemd/tradingdatas-crypto-binance-premium-dump-collect.service",
        "systemd/tradingdatas-crypto-binance-premium-dump-collect.timer",
        "systemd/tradingdatas-crypto-binance-rules.service",
        "systemd/tradingdatas-crypto-binance-rules.timer",
        "systemd/tradingdatas-crypto-binance-usdm-collect.service",
        "systemd/tradingdatas-crypto-binance-usdm-collect.timer",
        "systemd/tradingdatas-crypto-v1-internal.service",
        "systemd/tradingdatas-provider-native-collect.service",
        "systemd/tradingdatas-provider-native-collect.timer",
        "systemd/tradingdatas-v1-internal.service",
        "tradingdatas-collector-watch.sh",
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
    assert "tools/run_provider_native_collector.py" in service
    assert "EnvironmentFile=-/run/tradingdatas/on-demand.env" in service
    assert "RuntimeDirectoryPreserve=yes" in service
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
