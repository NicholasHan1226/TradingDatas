from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


NATIVE_ID_FIELDS = (
    "event_id",
    "id",
    "accessionNumber",
    "accession_number",
    "ann_id",
    "report_id",
)


def source_family(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value.startswith("tushare_"):
        return "tushare"
    return value or "unknown"


def stable_event_id(provider: str, event_type: str, row: Mapping[str, Any]) -> str:
    native = next(
        (
            str(row.get(key) or "").strip()
            for key in NATIVE_ID_FIELDS
            if row.get(key)
        ),
        "",
    )
    canonical_url = str(row.get("url") or row.get("link") or "").strip().split("#", 1)[0]
    fallback = "|".join(
        str(row.get(key) or "").strip()
        for key in ("datetime", "pub_time", "date", "title")
    )
    identity = native or canonical_url or fallback
    digest = hashlib.sha256(
        f"{source_family(provider)}|{event_type}|{identity}".encode()
    ).hexdigest()[:32]
    return f"evt:{digest}"


def event_content_fingerprint(row: Mapping[str, Any]) -> str:
    payload = {
        key: row.get(key)
        for key in (
            "title",
            "content",
            "url",
            "source",
            "src",
            "symbol",
            "event_time",
            "trade_date",
        )
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
