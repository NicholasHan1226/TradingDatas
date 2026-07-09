from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collectors.events import sec_edgar_filings
from storage.schema import SCHEMA_SQL


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _sample_payload() -> dict:
    return {
        "cik": "320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "form": ["10-K"],
                "filingDate": ["2026-01-30"],
                "reportDate": ["2025-12-31"],
                "acceptanceDateTime": ["2026-01-30T17:01:02.000Z"],
                "primaryDocument": ["aapl-20251231.htm"],
                "primaryDocDescription": ["10-K"],
            }
        },
    }


def test_normalize_cik_zero_pads_and_rejects_empty() -> None:
    assert sec_edgar_filings.normalize_cik("320193") == "0000320193"
    with pytest.raises(ValueError, match="CIK must contain digits"):
        sec_edgar_filings.normalize_cik("abc")


def test_sec_headers_requires_user_agent() -> None:
    with pytest.raises(ValueError, match="User-Agent"):
        sec_edgar_filings.sec_headers("")


def test_filing_rows_from_submissions_maps_to_market_events() -> None:
    rows = sec_edgar_filings.filing_rows_from_submissions(_sample_payload(), limit=1)

    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "sec_edgar"
    assert row["event_type"] == "sec_edgar:10-K"
    assert row["market"] == "US"
    assert row["symbol"] == "CIK0000320193"
    assert row["trade_date"] == "20260130"
    assert "Archives/edgar/data/320193/000032019326000001/aapl-20251231.htm" in row["url"]


def test_run_collection_writes_market_events(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    monkeypatch.setattr(
        sec_edgar_filings,
        "fetch_company_submissions",
        lambda cik, *, user_agent, timeout=20.0: _sample_payload(),
    )

    summary = sec_edgar_filings.run_collection(
        ciks=["320193"],
        db_path=db_path,
        user_agent="SharedSignals test contact@example.com",
        limit_per_cik=1,
        dry_run=False,
    )

    assert summary["rows_read"] == 1
    assert summary["rows_written"] == 1
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT provider, event_type, market, symbol, title FROM market_events"
        ).fetchone()
    finally:
        conn.close()
    assert row[:4] == ("sec_edgar", "sec_edgar:10-K", "US", "CIK0000320193")
    assert "Apple Inc." in row[4]
