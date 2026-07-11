from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from collectors.events import sec_edgar_filings
from storage.event_identity import stable_event_id
from storage.read_model_store import ingest_rows_to_sqlite
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


def _sample_companyfacts_payload() -> dict:
    return {
        "cik": "320193",
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "end": "2026-03-31",
                                "filed": "2026-05-01",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "accn": "0000320193-26-000010",
                                "val": 331000000000,
                            }
                        ]
                    },
                },
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "end": "2026-03-31",
                                "filed": "2026-05-01",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q",
                                "accn": "0000320193-26-000010",
                                "val": 94500000000,
                            }
                        ]
                    },
                },
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


def test_sec_edgar_cli_entrypoint_imports_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, "collectors/events/sec_edgar_filings.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Collect SEC EDGAR filing metadata" in result.stdout


def test_company_fact_rows_from_companyfacts_maps_to_market_factors() -> None:
    rows = sec_edgar_filings.company_fact_rows_from_companyfacts(
        _sample_companyfacts_payload(),
        concepts=["Assets", "Revenues"],
        limit_per_concept=1,
    )

    assert len(rows) == 2
    assert rows[0]["provider"] == "sec_edgar_companyfacts"
    assert rows[0]["market"] == "US"
    assert rows[0]["symbol"] == "CIK0000320193"
    assert rows[0]["concept"] == "Assets"
    assert rows[0]["unit"] == "USD"
    assert rows[0]["Assets"] == 331000000000
    assert rows[0]["end_date"] == "2026-03-31"


def test_company_fact_rows_select_recent_periods_before_latest_filed_comparatives() -> None:
    payload = _sample_companyfacts_payload()
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [
        {
            "end": "2009-12-31",
            "filed": "2026-05-01",
            "form": "10-K",
            "val": 31942000000,
        },
        {
            "end": "2026-03-31",
            "filed": "2026-05-01",
            "form": "10-Q",
            "val": 94500000000,
        },
    ]

    rows = sec_edgar_filings.company_fact_rows_from_companyfacts(
        payload,
        concepts=["Revenues"],
        limit_per_concept=1,
    )

    assert rows[0]["end_date"] == "2026-03-31"
    assert rows[0]["Revenues"] == 94500000000


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


def test_run_collection_writes_companyfacts_to_market_factors(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)

    monkeypatch.setattr(
        sec_edgar_filings,
        "fetch_company_facts",
        lambda cik, *, user_agent, timeout=20.0: _sample_companyfacts_payload(),
    )

    summary = sec_edgar_filings.run_collection(
        ciks=["320193"],
        db_path=db_path,
        user_agent="SharedSignals test contact@example.com",
        mode="companyfacts",
        concepts=["Assets", "Revenues"],
        limit_per_cik=1,
        dry_run=False,
    )

    assert summary["rows_read"] == 2
    assert summary["rows_written"] == 2
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT market, symbol, factor_name, event_time, value, provider FROM market_factors ORDER BY factor_name"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("US", "CIK0000320193", "sec_edgar_companyfacts:Assets", "2026-03-31", 331000000000.0, "sec_edgar_companyfacts"),
        ("US", "CIK0000320193", "sec_edgar_companyfacts:Revenues", "2026-03-31", 94500000000.0, "sec_edgar_companyfacts"),
    ]


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


def test_sec_edgar_event_uses_accession_based_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "marketdata.sqlite"
    _create_db(db_path)
    filing = sec_edgar_filings.filing_rows_from_submissions(_sample_payload(), limit=1)[0]

    assert ingest_rows_to_sqlite(
        db_path,
        "market_events",
        "sec_edgar",
        [filing],
        source_name="sec_edgar_test",
    ) == 1

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT provider, source_family, event_id, revision FROM market_events"
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        "sec_edgar",
        "sec_edgar",
        stable_event_id("sec_edgar", filing["event_type"], filing),
        1,
    )
    assert stable_event_id(
        "sec_edgar",
        filing["event_type"],
        {**filing, "title": "Corrected title"},
    ) == row[2]


def test_sec_identity_reads_nested_accession_before_mutable_url() -> None:
    accession = "0000320193-26-000001"
    raw_json_row = {
        "url": "https://www.sec.gov/filing?output=1",
        "raw_json": '{"accession_number":"0000320193-26-000001"}',
    }
    content_row = {
        "url": "https://www.sec.gov/filing?output=2",
        "content": '{"accessionNumber":"0000320193-26-000001"}',
    }

    assert stable_event_id("sec_edgar", "sec_edgar:10-K", raw_json_row) == stable_event_id(
        "sec_edgar", "sec_edgar:10-K", content_row
    )
    assert accession in raw_json_row["raw_json"]


def test_provider_local_native_ids_are_namespaced_by_provider() -> None:
    row = {"id": "provider-42", "title": "A"}

    assert stable_event_id("tushare_news", "news", row) != stable_event_id(
        "tushare_major_news", "news", row
    )


def test_sparse_event_without_identity_facts_is_rejected() -> None:
    with pytest.raises(ValueError, match="stable event identity"):
        stable_event_id("tushare_news", "news", {"symbol": "000001.SZ"})
