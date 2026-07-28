from __future__ import annotations

import pytest

from collectors.binance.collector import BinanceSpotPublicCollector, _RejectRedirects
from dataset_registry import (
    BINANCE_SPOT_CANARY_MODE,
    BINANCE_SPOT_CANARY_REGISTRY_PATH,
    load_dataset_registry,
    runtime_dataset_registry_path,
)
from provider_transport import provider_transport_profile


def test_canary_registry_freezes_only_the_two_symbols_and_rule_sets() -> None:
    registry = load_dataset_registry(BINANCE_SPOT_CANARY_REGISTRY_PATH)
    assert [item.dataset_id for item in registry.datasets] == [
        "crypto.spot.binance.btcusdt.5m",
        "crypto.spot.binance.ethusdt.5m",
        "crypto.spot.binance.btcusdt.rules",
        "crypto.spot.binance.ethusdt.rules",
    ]
    bar = registry.resolve("crypto.spot.binance.btcusdt.5m")
    assert bar.primary_key == ("symbol", "open_time")
    assert bar.as_of_field == "close_time"
    assert bar.timezone == "UTC"
    assert bar.freshness_sla_seconds == 600


def test_canary_mode_selects_only_the_pinned_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADINGDATAS_CANARY_MODE", BINANCE_SPOT_CANARY_MODE)
    monkeypatch.delenv("TRADINGDATAS_REGISTRY_PATH", raising=False)
    assert runtime_dataset_registry_path() == BINANCE_SPOT_CANARY_REGISTRY_PATH
    monkeypatch.setenv("TRADINGDATAS_REGISTRY_PATH", str(BINANCE_SPOT_CANARY_REGISTRY_PATH))
    with pytest.raises(ValueError, match="does not accept a path override"):
        runtime_dataset_registry_path()


def test_binance_collector_rejects_symbols_outside_the_frozen_canary() -> None:
    outcome = BinanceSpotPublicCollector().collect_outcome(
        "klines_btcusdt",
        {
            "symbol": "DOGEUSDT",
            "interval": "5m",
            "start_open_time": "2026-07-28T00:00:00Z",
            "end_open_time": "2026-07-28T00:05:00Z",
        },
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"


def test_binance_transport_is_credential_free_and_market_data_only() -> None:
    profile = provider_transport_profile("binance_spot")
    assert profile["credential_mode"] == "none"
    assert profile["market_data_only"] is True
    assert profile["transport_service"] == "binance_public_market_data"


def test_binance_transport_rejects_redirects() -> None:
    with pytest.raises(OSError, match="redirect rejected"):
        _RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid/"
        )
