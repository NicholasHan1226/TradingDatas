from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tools.run_binance_spot_canary import latest_closed_window, run


ROOT = Path(__file__).resolve().parents[1]


def test_crypto_collector_window_uses_only_two_closed_adjacent_bars() -> None:
    window = latest_closed_window(datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc))
    assert window == {
        "start_open_time": "2026-07-28T09:35:00Z",
        "end_open_time": "2026-07-28T09:40:00Z",
    }


def test_crypto_runner_plan_never_calls_provider_or_writes() -> None:
    result = run(
        db_path=Path("/private/tmp/unused.sqlite"),
        lock_path=Path("/private/tmp/unused.lock"),
        execute=False,
        now=datetime(2026, 7, 28, 9, 47, tzinfo=timezone.utc),
    )
    assert result["state"] == "planned"
    assert result["will_call_provider"] is False
    assert result["will_write_database"] is False


def test_crypto_units_are_physically_isolated_from_ashare_runtime() -> None:
    api = (ROOT / "deploy/systemd/tradingdatas-crypto-v1-internal.service").read_text()
    collector = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.service"
    ).read_text()
    timer = (
        ROOT / "deploy/systemd/tradingdatas-crypto-binance-collect.timer"
    ).read_text()
    profile = (ROOT / "deploy/crypto/tradingdatas_crypto_internal.env").read_text()

    assert "127.0.0.1:18082" not in api + collector + timer + profile
    assert "18083" in profile
    assert "tradingdatas-crypto" in api + collector
    assert "/opt/investment-data/tradingdatas-crypto" in api + collector + profile
    assert "/opt/investment/releases/tradingdatas/current" not in api + collector
    assert "/opt/investment/releases/tradingdatas-crypto/current" in api + collector
    assert "TRADINGDATAS_CANARY_MODE=binance_spot_v1" in profile
    assert "tradingdatas-crypto-binance-collect.service" in timer
    assert "quicksync" not in collector.lower()


def test_crypto_api_has_no_mutable_runtime_environment_override() -> None:
    api = (ROOT / "deploy/systemd/tradingdatas-crypto-v1-internal.service").read_text()

    assert "/etc/tradingdatas-crypto/internal-api.env" not in api
    assert api.count("EnvironmentFile=") == 1
    assert (
        "EnvironmentFile=/opt/investment/releases/tradingdatas-crypto/current/"
        "deploy/crypto/tradingdatas_crypto_internal.env"
    ) in api
    assert 'Environment="TRADINGDATAS_TOKEN_HASH_FILE=' in api
    assert 'Environment="TRADINGDATAS_TOKEN_SALT_FILE=' in api
    assert (
        'Environment="TRADINGDATAS_CURSOR_SIGNING_KEY_FILE='
        "/etc/tradingdatas-crypto/cursor_signing_key"
        '"'
    ) in api
    assert "TRADINGDATAS_CURSOR_SIGNING_KEY=" not in api
    assert "ConditionPathExists=/etc/tradingdatas-crypto/cursor_signing_key" in api
