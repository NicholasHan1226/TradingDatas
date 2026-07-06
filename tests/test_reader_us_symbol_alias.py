from __future__ import annotations

import sqlite3


def test_get_market_data_accepts_us_symbol_without_suffix(tmp_path):
    import reader

    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE market_bars_daily (
            market TEXT,
            symbol TEXT,
            trade_date TEXT,
            close REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO market_bars_daily VALUES (?, ?, ?, ?)",
        ("US", "AAPL.US", "20260702", 204.0),
    )
    conn.commit()
    conn.close()

    reader.SQLITE_PATH = reader._LazyPath(lambda: db_path)
    reader.clear_caches()

    rows = reader.get_market_data("AAPL", "20260702", "20260702")

    assert len(rows) == 1
    assert rows[0]["data"]["symbol"] == "AAPL.US"
    assert rows[0]["degraded"] is False


def test_get_market_data_accepts_us_symbol_with_suffix_when_db_has_plain_symbol(tmp_path):
    import reader

    db_path = tmp_path / "marketdata.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE market_bars_daily (
            market TEXT,
            symbol TEXT,
            trade_date TEXT,
            close REAL
        )
        """
    )
    conn.execute(
        "INSERT INTO market_bars_daily VALUES (?, ?, ?, ?)",
        ("US", "MSFT", "20260702", 510.0),
    )
    conn.commit()
    conn.close()

    reader.SQLITE_PATH = reader._LazyPath(lambda: db_path)
    reader.clear_caches()

    rows = reader.get_market_data("MSFT.US", "20260702", "20260702")

    assert len(rows) == 1
    assert rows[0]["data"]["symbol"] == "MSFT"
    assert rows[0]["degraded"] is False
