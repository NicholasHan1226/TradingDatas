"""Stateless query parsing and response helpers for the SharedSignals HTTP API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_int(value: Any, default: int, *, min_val: int = 1, max_val: int = 10000) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, result))


def apply_row_limit(rows: Any, params: dict[str, str], *, default: int | None = None) -> Any:
    if not isinstance(rows, list):
        return rows
    raw_limit = params.get("limit")
    if raw_limit in (None, "") and default is None:
        return rows
    fallback = default if default is not None else len(rows)
    return rows[:to_int(raw_limit, fallback, min_val=1, max_val=10000)]


def validate_json_query_params(params: dict[str, str]) -> None:
    json_param_names = {"params", "filters", "payload"}
    for key, value in params.items():
        if key not in json_param_names and not key.endswith("_json"):
            continue
        if not value:
            continue
        try:
            json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON in query parameter '{key}': {exc.msg}") from exc


def aggregate_metadata(rows: Any) -> tuple[Any, dict[str, Any], str | None]:
    empty_metadata = {
        "freshness": None,
        "quality": None,
        "degraded": False,
        "degraded_reasons": [],
        "lineage": [],
    }
    if not isinstance(rows, list):
        return rows, dict(empty_metadata), None
    if not rows:
        return [], dict(empty_metadata), None
    if not all(isinstance(row, dict) and "data" in row for row in rows):
        return rows, dict(empty_metadata), None

    data_rows = [
        row.get("data")
        for row in rows
        if not (bool(row.get("degraded")) and row.get("data") in ({}, None))
    ]
    degraded = any(bool(row.get("degraded")) for row in rows)
    freshness_rows = [row.get("freshness") for row in rows if isinstance(row.get("freshness"), dict)]
    quality_rows = [row.get("quality") for row in rows if isinstance(row.get("quality"), dict)]
    degraded_reasons: list[str] = []
    lineages: list[dict[str, Any]] = []
    sources: list[str] = []
    for row in rows:
        provenance = row.get("provenance")
        if isinstance(provenance, dict) and provenance.get("source_id"):
            sources.append(str(provenance["source_id"]))
        lineage = row.get("lineage")
        if isinstance(lineage, dict) and lineage:
            lineages.append(lineage)
            if lineage.get("reason"):
                degraded_reasons.append(str(lineage["reason"]))
        row_reasons = row.get("degraded_reasons")
        if isinstance(row_reasons, list):
            degraded_reasons.extend(str(reason) for reason in row_reasons if reason)
        elif row_reasons:
            degraded_reasons.append(str(row_reasons))

    freshness: dict[str, Any] | None = None
    if freshness_rows:
        age_hours = [float(item.get("age_hours", 0.0)) for item in freshness_rows if item.get("age_hours") is not None]
        scores = [float(item.get("score", 0.0)) for item in freshness_rows if item.get("score") is not None]
        freshness = {
            "stale": any(bool(item.get("stale")) for item in freshness_rows),
            "age_hours_max": max(age_hours) if age_hours else None,
            "age_hours_min": min(age_hours) if age_hours else None,
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
        }
        if len(freshness_rows) == 1:
            freshness = freshness_rows[0]

    quality: dict[str, Any] | None = None
    if quality_rows:
        scores = [float(item.get("score", 0.0)) for item in quality_rows if item.get("score") is not None]
        completeness = [float(item.get("completeness", 0.0)) for item in quality_rows if item.get("completeness") is not None]
        quality = {
            "score_min": min(scores) if scores else None,
            "score_avg": round(sum(scores) / len(scores), 4) if scores else None,
            "completeness_min": min(completeness) if completeness else None,
        }
        if len(quality_rows) == 1:
            quality = quality_rows[0]

    unique_reasons = list(dict.fromkeys(degraded_reasons))
    return data_rows, {
        "freshness": freshness,
        "quality": quality,
        "degraded": degraded,
        "degraded_reasons": unique_reasons,
        "lineage": lineages[0] if len(lineages) == 1 else lineages,
    }, sources[0] if sources else None


def wrap_response(payload: Any, metadata: dict[str, Any], source: str | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("degraded_reasons", [])
    normalized.setdefault("lineage", [])
    return {
        "data": payload,
        "metadata": normalized,
        "source": source,
        "timestamp": utc_now_iso(),
    }
