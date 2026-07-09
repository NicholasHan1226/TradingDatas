#!/usr/bin/env python3
"""Manual SEC EDGAR filings pilot collector.

This collector is intentionally not installed in production cron. It is a B1
source-expansion pilot that writes filing metadata directly to market_events.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(os.environ.get("SHAREDSIGNALS_ROOT", Path(__file__).resolve().parents[2]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_paths import marketdata_sqlite_path
from storage.read_model_store import ingest_rows_to_sqlite

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_USER_AGENT_ENV = "SHAREDSIGNALS_SEC_USER_AGENT"
SOURCE_ID = "sec_edgar"
DEFAULT_COMPANY_FACT_CONCEPTS = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "Revenues",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "NetCashProvidedByUsedInOperatingActivities",
)


def normalize_cik(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        raise ValueError("CIK must contain digits")
    if len(digits) > 10:
        raise ValueError("CIK must be at most 10 digits")
    return digits.zfill(10)


def sec_headers(user_agent: str) -> dict[str, str]:
    user_agent = str(user_agent or "").strip()
    if not user_agent:
        raise ValueError(f"{DEFAULT_USER_AGENT_ENV} or --user-agent User-Agent is required for SEC fair-access requests")
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


def fetch_company_submissions(cik: str, *, user_agent: str, timeout: float = 20.0) -> dict[str, Any]:
    normalized_cik = normalize_cik(cik)
    url = SEC_SUBMISSIONS_URL.format(cik=quote(normalized_cik))
    response = requests.get(url, headers=sec_headers(user_agent), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected SEC submissions payload for CIK {normalized_cik}")
    return payload


def fetch_company_facts(cik: str, *, user_agent: str, timeout: float = 20.0) -> dict[str, Any]:
    normalized_cik = normalize_cik(cik)
    url = SEC_COMPANY_FACTS_URL.format(cik=quote(normalized_cik))
    response = requests.get(url, headers=sec_headers(user_agent), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected SEC companyfacts payload for CIK {normalized_cik}")
    return payload


def filing_rows_from_submissions(payload: dict[str, Any], *, limit: int = 100) -> list[dict[str, Any]]:
    cik = normalize_cik(str(payload.get("cik") or payload.get("CIK") or ""))
    company_name = str(payload.get("name") or "").strip()
    tickers = payload.get("tickers") if isinstance(payload.get("tickers"), list) else []
    primary_ticker = str(tickers[0]).strip().upper() if tickers else ""
    recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload.get("filings"), dict) else {}
    accession_numbers = list(recent.get("accessionNumber") or [])
    forms = list(recent.get("form") or [])
    filing_dates = list(recent.get("filingDate") or [])
    report_dates = list(recent.get("reportDate") or [])
    primary_docs = list(recent.get("primaryDocument") or [])
    descriptions = list(recent.get("primaryDocDescription") or [])
    accepted_times = list(recent.get("acceptanceDateTime") or [])
    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for idx, accession in enumerate(accession_numbers[: max(limit, 0)]):
        form = _get(forms, idx)
        filing_date = _get(filing_dates, idx)
        report_date = _get(report_dates, idx)
        accepted_time = _get(accepted_times, idx)
        primary_doc = _get(primary_docs, idx)
        accession_clean = str(accession).replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary_doc}"
            if primary_doc
            else f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/"
        )
        event_time = _event_time(accepted_time, filing_date)
        title_parts = [part for part in (form, company_name, filing_date) if part]
        raw = {
            "cik": cik,
            "company_name": company_name,
            "ticker": primary_ticker,
            "accession_number": accession,
            "form": form,
            "filing_date": filing_date,
            "report_date": report_date,
            "accepted_at": accepted_time,
            "primary_document": primary_doc,
            "description": _get(descriptions, idx),
            "url": url,
        }
        rows.append(
            {
                "provider": SOURCE_ID,
                "event_type": f"sec_edgar:{form or 'filing'}",
                "event_time": event_time,
                "trade_date": str(filing_date or "").replace("-", ""),
                "market": "US",
                "symbol": f"CIK{cik}",
                "title": " | ".join(title_parts) or f"SEC filing {accession}",
                "content": json.dumps(raw, ensure_ascii=False, sort_keys=True),
                "url": url,
                "source": "SEC EDGAR submissions",
                "collected_at": now,
                "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def company_fact_rows_from_companyfacts(
    payload: dict[str, Any],
    *,
    concepts: list[str] | tuple[str, ...] | None = None,
    limit_per_concept: int = 8,
) -> list[dict[str, Any]]:
    cik = normalize_cik(str(payload.get("cik") or payload.get("CIK") or ""))
    company_name = str(payload.get("entityName") or payload.get("name") or "").strip()
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    us_gaap = facts.get("us-gaap") if isinstance(facts.get("us-gaap"), dict) else {}
    selected = list(concepts or DEFAULT_COMPANY_FACT_CONCEPTS)
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for concept in selected:
        concept_payload = us_gaap.get(concept)
        if not isinstance(concept_payload, dict):
            continue
        label = str(concept_payload.get("label") or concept).strip()
        units = concept_payload.get("units") if isinstance(concept_payload.get("units"), dict) else {}
        for unit, items in units.items():
            if not isinstance(items, list):
                continue
            ordered = sorted(
                (item for item in items if isinstance(item, dict)),
                key=lambda item: str(item.get("filed") or item.get("end") or ""),
                reverse=True,
            )
            for item in ordered[: max(limit_per_concept, 0)]:
                value = item.get("val")
                if value in (None, ""):
                    continue
                end = str(item.get("end") or item.get("fy") or item.get("filed") or "").strip()
                raw = {
                    "cik": cik,
                    "company_name": company_name,
                    "concept": concept,
                    "label": label,
                    "unit": unit,
                    "form": item.get("form"),
                    "fiscal_year": item.get("fy"),
                    "fiscal_period": item.get("fp"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "filed": item.get("filed"),
                    "accession_number": item.get("accn"),
                    "frame": item.get("frame"),
                    "value": value,
                }
                rows.append(
                    {
                        "provider": "sec_edgar_companyfacts",
                        "market": "US",
                        "symbol": f"CIK{cik}",
                        "concept": concept,
                        "unit": unit,
                        concept: value,
                        "end_date": end,
                        "filed_date": item.get("filed"),
                        "form": item.get("form"),
                        "collected_at": now,
                        "source_file": "sec_edgar_companyfacts",
                        "raw_json": json.dumps(raw, ensure_ascii=False, sort_keys=True),
                    }
                )
    return rows


def run_collection(
    *,
    ciks: list[str],
    db_path: Path,
    user_agent: str,
    limit_per_cik: int = 100,
    mode: str = "filings",
    concepts: list[str] | None = None,
    timeout: float = 20.0,
    sleep_seconds: float = 0.2,
    dry_run: bool = False,
) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    normalized_ciks = [normalize_cik(cik) for cik in ciks]
    for index, cik in enumerate(normalized_ciks):
        if index > 0 and sleep_seconds > 0:
            time.sleep(sleep_seconds)
        if mode == "companyfacts":
            payload = fetch_company_facts(cik, user_agent=user_agent, timeout=timeout)
            all_rows.extend(company_fact_rows_from_companyfacts(payload, concepts=concepts, limit_per_concept=limit_per_cik))
        else:
            payload = fetch_company_submissions(cik, user_agent=user_agent, timeout=timeout)
            all_rows.extend(filing_rows_from_submissions(payload, limit=limit_per_cik))

    rows_written = 0
    if not dry_run and all_rows:
        rows_written = ingest_rows_to_sqlite(
            db_path,
            "market_factors" if mode == "companyfacts" else "market_events",
            "sec_edgar_companyfacts" if mode == "companyfacts" else "sec_edgar_filings",
            all_rows,
            source_name="sec_edgar_companyfacts" if mode == "companyfacts" else "sec_edgar_filings",
        )
    return {
        "source_id": SOURCE_ID,
        "mode": mode,
        "status": "dry_run" if dry_run else "ok",
        "ciks": normalized_ciks,
        "rows_read": len(all_rows),
        "rows_written": rows_written,
        "db_path": str(db_path),
    }


def _get(items: list[Any], index: int) -> str:
    if index >= len(items):
        return ""
    return str(items[index] or "").strip()


def _event_time(accepted_time: str, filing_date: str) -> str:
    if accepted_time:
        return accepted_time
    if filing_date:
        return f"{filing_date}T00:00:00+00:00"
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect SEC EDGAR filing metadata into SharedSignals market_events")
    parser.add_argument("--cik", action="append", default=[], help="Company CIK. Repeat for multiple companies.")
    parser.add_argument("--ciks", default="", help="Comma-separated CIK list.")
    parser.add_argument("--db", type=Path, default=marketdata_sqlite_path(), help="SQLite read-model path.")
    parser.add_argument("--user-agent", default=os.environ.get(DEFAULT_USER_AGENT_ENV, ""), help="SEC fair-access User-Agent.")
    parser.add_argument("--limit-per-cik", type=int, default=100)
    parser.add_argument("--mode", choices=["filings", "companyfacts"], default="filings")
    parser.add_argument("--concept", action="append", default=[], help="SEC us-gaap concept for companyfacts mode. Repeat for multiple concepts.")
    parser.add_argument("--concepts", default="", help="Comma-separated SEC us-gaap concepts for companyfacts mode.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ciks = list(args.cik)
    if args.ciks:
        ciks.extend(part.strip() for part in args.ciks.split(",") if part.strip())
    if not ciks:
        raise SystemExit("--cik or --ciks is required")
    concepts = list(args.concept)
    if args.concepts:
        concepts.extend(part.strip() for part in args.concepts.split(",") if part.strip())
    result = run_collection(
        ciks=ciks,
        db_path=args.db,
        user_agent=args.user_agent,
        limit_per_cik=args.limit_per_cik,
        mode=args.mode,
        concepts=concepts or None,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
