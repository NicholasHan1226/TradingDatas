from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from storage.ndjson_bridge import ingest_crypto_ndjson_to_sqlite
from storage.schema import SCHEMA_SQL


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.close()


def test_crypto_ndjson_bridge_routes_daily_and_intraday(tmp_path: Path):
    db_path = tmp_path / "marketdata.sqlite"
    _init_db(db_path)

    source_root = tmp_path / "data" / "crypto" / "binance"
    daily_dir = source_root / "1d" / "20260705"
    ticker_dir = source_root / "24h_ticker" / "20260705"
    daily_dir.mkdir(parents=True)
    ticker_dir.mkdir(parents=True)

    (daily_dir / "BTCUSDT_000001.ndjson").write_text(
        json.dumps({
            "market": "Crypto",
            "symbol": "BTCUSDT",
            "trade_date": "20260705",
            "interval": "1d",
            "bar_time": "2026-07-05T00:00:00+00:00",
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 10.0,
            "amount": 1050.0,
            "provider": "binance",
            "collected_at": "2026-07-05T00:00:00+00:00",
        }) + "\n",
        encoding="utf-8",
    )
    (ticker_dir / "ticker_000002.ndjson").write_text(
        json.dumps({
            "market": "Crypto",
            "symbol": "ETHUSDT",
            "trade_date": "20260705",
            "interval": "24h_ticker",
            "bar_time": "2026-07-05T00:05:00+00:00",
            "open": 200.0,
            "high": 220.0,
            "low": 190.0,
            "close": 210.0,
            "volume": 20.0,
            "amount": 4200.0,
            "provider": "binance",
            "collected_at": "2026-07-05T00:05:00+00:00",
        }) + "\n",
        encoding="utf-8",
    )

    result = ingest_crypto_ndjson_to_sqlite(db_path, source_root)

    assert result["rows_written"] == 2
    assert result["tables"] == {"market_bars_daily": 1, "market_bars_intraday": 1}

    conn = sqlite3.connect(db_path)
    daily = conn.execute("SELECT symbol, close FROM market_bars_daily").fetchone()
    intraday = conn.execute("SELECT symbol, interval, close FROM market_bars_intraday").fetchone()
    conn.close()

    assert daily == ("BTCUSDT", 105.0)
    assert intraday == ("ETHUSDT", "24h_ticker", 210.0)


def test_crypto_reader_uses_sqlite_not_legacy_csv(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "marketdata.sqlite"
    _init_db(db_path)
    legacy_root = tmp_path / "legacy_crypto"
    legacy_path = legacy_root / "data" / "market" / "klines.csv"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text("symbol,open_time,close\nBTCUSDT,legacy,1\n", encoding="utf-8")

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO market_bars_intraday
        (market, symbol, bar_time, trade_date, interval, open, high, low, close, volume, amount, provider, source_file, collected_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Crypto",
            "BTCUSDT",
            "2026-07-05T00:05:00+00:00",
            "20260705",
            "24h_ticker",
            100.0,
            110.0,
            90.0,
            108.0,
            10.0,
            1080.0,
            "binance",
            "test.ndjson",
            "2026-07-05T00:05:00+00:00",
            "{}",
        ),
    )
    conn.commit()
    conn.close()

    import reader

    reader.SQLITE_PATH._path = db_path
    monkeypatch.setenv("CRYPTO_ROOT", str(legacy_root))
    reader.clear_caches()

    rows = reader.get_crypto_klines("BTCUSDT", limit=5)

    assert rows
    assert rows[0]["data"]["close"] == 108.0
    assert rows[0]["provenance"]["source_id"] == "binance"
    assert "legacy" not in json.dumps(rows, ensure_ascii=False)
