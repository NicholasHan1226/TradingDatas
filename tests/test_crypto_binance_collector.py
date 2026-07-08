from __future__ import annotations

import sqlite3

import requests

from collectors.crypto.binance import CryptoCollector
from storage.schema import SCHEMA_SQL


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


class _FlakySession:
    def __init__(self) -> None:
        self.calls = 0
        self.proxies = {}

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise requests.exceptions.SSLError("transient eof")
        return _Response()


def test_binance_health_check_retries_transient_requests_errors():
    collector = CryptoCollector(config={"retry": {"max_attempts": 1}})
    session = _FlakySession()
    collector._session = session
    collector.retry_base_delay = 0
    collector.retry_jitter = False

    result = collector.health_check()

    assert result["status"] == "available"
    assert session.calls == 2


def test_binance_get_falls_back_to_second_proxy():
    collector = CryptoCollector(config={"retry": {"max_attempts": 1}}, proxy="http://sg-relay:8080,http://127.0.0.1:7890")
    seen: list[dict] = []

    class Session:
        def get(self, *args, **kwargs):
            seen.append(kwargs.get("proxies") or {})
            if kwargs.get("proxies", {}).get("https") == "http://sg-relay:8080":
                raise requests.exceptions.ProxyError("sg relay unavailable")
            return _Response()

    collector._session = Session()

    response = collector._get("https://api.binance.com/api/v3/ping", timeout=10)

    assert response.status_code == 200
    assert seen == [
        {"http": "http://sg-relay:8080", "https": "http://sg-relay:8080"},
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    ]


def test_binance_save_writes_directly_to_sqlite(tmp_path):
    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()

    collector = CryptoCollector(config={"db": str(db_path), "retry": {"max_attempts": 1}})
    rows = [
        {
            "market": "Crypto",
            "symbol": "BTCUSDT",
            "trade_date": "20260708",
            "interval": "24h_ticker",
            "bar_time": "2026-07-08T00:00:00+00:00",
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 12.0,
            "amount": 1260.0,
            "provider": "binance",
            "collected_at": "2026-07-08T00:00:00+00:00",
            "raw_json": "{}",
        }
    ]

    result = collector.save(rows, task={"type": "ticker"})

    assert result["rows_written"] == 1
    conn = sqlite3.connect(db_path)
    try:
        saved = conn.execute(
            "SELECT market, symbol, interval, close, source_file FROM market_bars_intraday"
        ).fetchone()
    finally:
        conn.close()
    assert saved == ("Crypto", "BTCUSDT", "24h_ticker", 105.0, "binance_direct")
