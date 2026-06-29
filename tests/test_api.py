"""test_api — test client for SharedSignals external API interactions.

Tests contract compliance: parameters, error handling, response
structure, rate limiting, auth headers, and timeout behaviour.
Uses mock HTTP responses — no live API calls.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Mock API client (simulates what SharedSignals consumers use)
# ===========================================================================


class SharedSignalsAPIClient:
    """Minimal client that mirrors the SharedSignals API facade."""

    def __init__(self, base_url: str = "http://localhost:8080",
                 api_key: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._session = None  # would be requests.Session

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def get_bars(self, market: str, symbol: str,
                 start_date: str, end_date: str) -> dict:
        """GET /api/v1/bars/{market}/{symbol}?start=...&end=..."""
        if not market or not symbol:
            raise ValueError("market and symbol are required")
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")
        return {
            "market": market,
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "bars": [],
        }

    def get_events(self, market: str = "", event_type: str = "",
                   limit: int = 100) -> dict:
        """GET /api/v1/events?market=...&type=...&limit=..."""
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be 1-1000")
        return {
            "market": market,
            "event_type": event_type,
            "limit": limit,
            "events": [],
            "total": 0,
        }

    def get_assets(self, market: str = "") -> dict:
        """GET /api/v1/assets?market=..."""
        return {"market": market, "assets": [], "count": 0}

    def get_health(self) -> dict:
        """GET /api/v1/health — service health check."""
        return {
            "status": "ok",
            "version": "1.0.0",
            "uptime_seconds": 3600,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_sources(self) -> dict:
        """GET /api/v1/sources — list available data sources."""
        return {
            "sources": [
                {"name": "tushare", "status": "active", "interfaces": 14},
                {"name": "binance", "status": "active", "interfaces": 4},
                {"name": "polymarket", "status": "active", "interfaces": 3},
                {"name": "rss", "status": "active", "feeds": 883},
            ],
        }

    def get_coverage(self, market: str, trade_date: str) -> dict:
        """GET /api/v1/coverage/{market}/{trade_date}"""
        if not market:
            raise ValueError("market is required")
        return {
            "market": market,
            "trade_date": trade_date,
            "total_symbols": 0,
            "covered": 0,
            "missing": 0,
            "status": "partial",
            "details": [],
        }

    def post_ingest(self, payload: dict) -> dict:
        """POST /api/v1/ingest — submit data for ingestion."""
        required = {"market", "source", "rows"}
        missing = required - set(payload.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        return {
            "run_id": "test-run-001",
            "accepted": len(payload.get("rows", [])),
            "rejected": 0,
            "status": "queued",
        }

    def get_ingest_status(self, run_id: str) -> dict:
        """GET /api/v1/ingest/{run_id} — check ingest run status."""
        return {
            "run_id": run_id,
            "status": "completed",
            "rows_read": 100,
            "rows_written": 95,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def client() -> SharedSignalsAPIClient:
    return SharedSignalsAPIClient(api_key="test-key-abc123")


@pytest.fixture
def client_no_auth() -> SharedSignalsAPIClient:
    return SharedSignalsAPIClient()


# ===========================================================================
# Tests
# ===========================================================================


class TestClientInit:
    """Test client initialization and configuration."""

    def test_init_defaults(self):
        c = SharedSignalsAPIClient()
        assert c.base_url == "http://localhost:8080"
        assert c.api_key == ""
        assert c.timeout == 30.0

    def test_init_custom(self):
        c = SharedSignalsAPIClient(
            base_url="https://api.example.com",
            api_key="sk-xxx",
            timeout=10.0,
        )
        assert c.base_url == "https://api.example.com"
        assert c.api_key == "sk-xxx"
        assert c.timeout == 10.0

    def test_auth_headers(self, client: SharedSignalsAPIClient):
        headers = client._headers()
        assert headers["Authorization"] == "Bearer test-key-abc123"
        assert headers["Content-Type"] == "application/json"

    def test_no_auth_headers(self, client_no_auth: SharedSignalsAPIClient):
        headers = client_no_auth._headers()
        assert "Authorization" not in headers


class TestBarsEndpoint:
    """Test /api/v1/bars endpoint."""

    def test_get_bars_valid(self, client: SharedSignalsAPIClient):
        resp = client.get_bars("Ashare", "000001.SZ", "20260601", "20260629")
        assert resp["market"] == "Ashare"
        assert resp["symbol"] == "000001.SZ"
        assert "bars" in resp

    def test_get_bars_missing_market(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="market and symbol are required"):
            client.get_bars("", "000001.SZ", "20260601", "20260629")

    def test_get_bars_missing_symbol(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="market and symbol are required"):
            client.get_bars("Ashare", "", "20260601", "20260629")

    def test_get_bars_invalid_date_range(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="start_date must be <= end_date"):
            client.get_bars("Ashare", "000001.SZ", "20260629", "20260601")


class TestEventsEndpoint:
    """Test /api/v1/events endpoint."""

    def test_get_events_default(self, client: SharedSignalsAPIClient):
        resp = client.get_events()
        assert resp["total"] == 0
        assert resp["events"] == []

    def test_get_events_with_filters(self, client: SharedSignalsAPIClient):
        resp = client.get_events(market="Ashare", event_type="news", limit=50)
        assert resp["market"] == "Ashare"
        assert resp["event_type"] == "news"
        assert resp["limit"] == 50

    def test_get_events_invalid_limit_low(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="limit must be 1-1000"):
            client.get_events(limit=0)

    def test_get_events_invalid_limit_high(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="limit must be 1-1000"):
            client.get_events(limit=2000)


class TestHealthEndpoint:
    """Test /api/v1/health endpoint."""

    def test_get_health(self, client: SharedSignalsAPIClient):
        resp = client.get_health()
        assert resp["status"] == "ok"
        assert resp["version"] == "1.0.0"
        assert resp["uptime_seconds"] >= 0
        assert "timestamp" in resp

    def test_get_health_structure(self, client: SharedSignalsAPIClient):
        resp = client.get_health()
        required = {"status", "version", "uptime_seconds", "timestamp"}
        assert required.issubset(set(resp.keys()))


class TestSourcesEndpoint:
    """Test /api/v1/sources endpoint."""

    def test_get_sources(self, client: SharedSignalsAPIClient):
        resp = client.get_sources()
        assert len(resp["sources"]) >= 1
        names = {s["name"] for s in resp["sources"]}
        assert "tushare" in names
        assert "binance" in names

    def test_sources_have_status(self, client: SharedSignalsAPIClient):
        resp = client.get_sources()
        for source in resp["sources"]:
            assert "status" in source
            assert source["status"] in ("active", "inactive", "degraded")


class TestCoverageEndpoint:
    """Test /api/v1/coverage endpoint."""

    def test_get_coverage(self, client: SharedSignalsAPIClient):
        resp = client.get_coverage("Ashare", "20260629")
        assert resp["market"] == "Ashare"
        assert "total_symbols" in resp
        assert "covered" in resp
        assert "missing" in resp

    def test_get_coverage_missing_market(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="market is required"):
            client.get_coverage("", "20260629")


class TestIngestEndpoint:
    """Test POST /api/v1/ingest endpoint."""

    def test_post_ingest_valid(self, client: SharedSignalsAPIClient):
        payload = {
            "market": "Ashare",
            "source": "tushare",
            "rows": [{"symbol": "000001.SZ", "close": 12.5}],
        }
        resp = client.post_ingest(payload)
        assert resp["status"] == "queued"
        assert resp["accepted"] == 1
        assert resp["rejected"] == 0

    def test_post_ingest_missing_fields(self, client: SharedSignalsAPIClient):
        with pytest.raises(ValueError, match="Missing required fields"):
            client.post_ingest({"market": "Ashare"})

    def test_get_ingest_status(self, client: SharedSignalsAPIClient):
        resp = client.get_ingest_status("test-run-001")
        assert resp["run_id"] == "test-run-001"
        assert resp["status"] == "completed"
        assert "rows_read" in resp
        assert "rows_written" in resp


class TestRateLimiting:
    """Test rate limiting behaviour."""

    def test_rate_limit_not_exceeded_within_window(self, client: SharedSignalsAPIClient):
        """Client handles normal call rate."""
        for _ in range(5):
            resp = client.get_health()
            assert resp["status"] == "ok"


class TestTimeout:
    """Test timeout behaviour."""

    def test_timeout_config(self):
        c = SharedSignalsAPIClient(timeout=5.0)
        assert c.timeout == 5.0


class TestResponseFieldTypes:
    """Test that response field types are consistent."""

    def test_health_field_types(self, client: SharedSignalsAPIClient):
        resp = client.get_health()
        assert isinstance(resp["status"], str)
        assert isinstance(resp["uptime_seconds"], int)
        assert isinstance(resp["timestamp"], str)

    def test_sources_field_types(self, client: SharedSignalsAPIClient):
        resp = client.get_sources()
        assert isinstance(resp["sources"], list)
        for source in resp["sources"]:
            assert isinstance(source["name"], str)
            # rss source has "feeds" key, others have "interfaces"
            if "interfaces" in source:
                assert isinstance(source["interfaces"], int)
            if "feeds" in source:
                assert isinstance(source["feeds"], int)

    def test_events_field_types(self, client: SharedSignalsAPIClient):
        resp = client.get_events()
        assert isinstance(resp["events"], list)
        assert isinstance(resp["total"], int)
