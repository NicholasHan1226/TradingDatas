from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors.polymarket.collector import (
    PolymarketSnapshotCollector,
    SshRelayTransport,
    StarterMarket,
    _gamma_markets_url,
)


@pytest.fixture
def market() -> StarterMarket:
    return StarterMarket(
        slug="will-bitcoin-hit-200k-in-2026",
        question="Will Bitcoin hit $200k in 2026?",
        category="bitcoin_price",
        verification_required=True,
    )


@pytest.fixture
def gamma_payload() -> list[dict[str, object]]:
    return [{
        "id": "12345",
        "slug": "will-bitcoin-hit-200k-in-2026",
        "question": "Will Bitcoin hit $200k in 2026?",
        "endDate": "2026-12-31T23:59:00Z",
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.42","0.58"]',
        "volume": "12345.67",
        "liquidity": "456.78",
        "active": True,
        "closed": False,
        "provider_extra": "preserved",
    }]


class FakeTransport:
    def __init__(self, result: object) -> None:
        self.result = result
        self.urls: list[str] = []

    def get_json(self, url: str, *, timeout_seconds: int) -> object:
        assert timeout_seconds == 30
        self.urls.append(url)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _params(market: StarterMarket) -> dict[str, object]:
    return {"slug": market.slug, "question": market.question, "category": market.category}


def test_happy_path_normalizes_provider_payload(
    market: StarterMarket, gamma_payload: list[dict[str, object]]
) -> None:
    transport = FakeTransport(gamma_payload)
    outcome = PolymarketSnapshotCollector(transport=transport).collect_outcome(
        "market_snapshot", _params(market)
    )
    assert outcome.state == "success"
    row = outcome.mutable_rows()[0]
    assert row["question_id"] == "12345"
    assert row["category"] == "bitcoin_price"
    assert row["outcomes"] == ["Yes", "No"]
    assert row["outcome_prices"] == [0.42, 0.58]
    assert row["provider_extra"] == "preserved"
    assert len(row["snapshot_id"]) == 64
    assert transport.urls == [_gamma_markets_url(slug=market.slug, limit=1, offset=0)]


def test_malformed_payload_fails_closed(market: StarterMarket) -> None:
    malformed = [{"id": "123", "slug": market.slug}]
    outcome = PolymarketSnapshotCollector(transport=FakeTransport(malformed)).collect_outcome(
        "market_snapshot", _params(market)
    )
    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert outcome.error_code == "provider_error"


def test_ssh_relay_command_uses_the_fixed_allowlisted_template() -> None:
    relay = SshRelayTransport(
        host="relay-host",
        user="collector",
        run_command=lambda command, timeout: b"[]",
    )
    url = _gamma_markets_url(slug="will-bitcoin-hit-200k-in-2026", limit=1, offset=0)
    # The relay wrapper's sole input is the bare URL as the SSH remote
    # command; it re-validates the allowlist server-side.
    assert relay.command_for(url, timeout_seconds=30) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "collector@relay-host",
        "https://gamma-api.polymarket.com/markets?slug=will-bitcoin-hit-200k-in-2026&limit=1&offset=0",
    ]


def test_timeout_fails_closed_with_no_rows(market: StarterMarket) -> None:
    outcome = PolymarketSnapshotCollector(transport=FakeTransport(TimeoutError())).collect_outcome(
        "market_snapshot", _params(market)
    )
    assert outcome.state == "failed"
    assert outcome.error_code == "transport_error"
    assert outcome.rows == ()


def test_starter_file_is_json_compatible_yaml() -> None:
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "config/polymarket_starter_markets.v1.yaml").read_text()
    )
    assert payload["status"] == "draft_unverified_candidates"
    assert len(payload["markets"]) == 20
    assert all(item["verification_required"] is True for item in payload["markets"])
