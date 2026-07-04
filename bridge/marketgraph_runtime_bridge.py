#!/usr/bin/env python3
"""Merge MarketGraph runtime staging rows into tracked CSV tables.

High-frequency workers should write newline-delimited JSON files under
MarketGraphRuntime/staging/<stream>/ instead of editing Git-tracked CSV files
directly. This bridge is the bounded checkpoint gate that validates those rows
against the canonical CSV schema and upserts them into the tracked tables.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ROOT = Path(
    os.environ.get("MARKETGRAPH_RUNTIME_ROOT") or os.environ.get("MARKETGRAPH_RUNTIME_DIR") or os.environ.get("MARKETGRAPH_RUNTIME", str(ROOT.parent / "MarketGraphRuntime"))
)
DEFAULT_APPLY_MIN_FILE_AGE_SECONDS = float(os.environ.get("MARKETGRAPH_RUNTIME_MIN_FILE_AGE_SECONDS", "30"))
LOCK_MAX_AGE_SECONDS = 30 * 60
LOCAL_README = """# MarketGraphRuntime

This directory is intentionally outside the MarketGraph Git repository.

KimiWork and other high-frequency workers write NDJSON staging files here:

- staging/event_candidates/<run_id>.ndjson
- staging/collection_runs/<run_id>.ndjson
- staging/enterprise_relation_source_results/<run_id>.ndjson
- staging/event_candidate_repair_workpack/<run_id>.ndjson
- staging/market_move_observations/<run_id>.ndjson
- staging/sentiment_signals/<run_id>.ndjson

Each line is either a CSV-row JSON object or {"row": {...}}. The tracked
MarketGraph CSV files are updated only by tools/marketgraph_runtime_bridge.py.
Writers should write <run_id>.ndjson.tmp first, then rename it to <run_id>.ndjson
after the file is complete.
"""


class StreamSpec(NamedTuple):
    name: str
    target: Path
    key_fields: tuple[str, ...]
    boundary: str
    preserve_existing_on_blank: bool = False


DEFAULT_STREAM_FIELDS: dict[str, list[str]] = {
    "sentiment_signals": [
        "signal_id",
        "collected_at",
        "source_date",
        "producer",
        "producer_run_id",
        "market",
        "subject",
        "subject_code",
        "subject_name",
        "subject_type",
        "source_class",
        "source_name",
        "source_url",
        "source_id",
        "title",
        "summary",
        "extracted_entities",
        "matched_entity_id",
        "match_status",
        "evidence_tier",
        "proposed_event_type",
        "proposed_impact_hint",
        "confidence",
        "status",
        "reviewer",
        "review_note",
        "promote_target",
        "promoted_event_id",
        "boundary",
        "collected_at_dt",
        "next_action",
        "signal_priority",
        "freshness_minutes",
        "source_tier",
        "cross_validation_group",
    ],
}


STREAMS: dict[str, StreamSpec] = {
    "event_candidates": StreamSpec(
        name="event_candidates",
        target=ROOT / "data" / "intake" / "event_candidates.csv",
        key_fields=("candidate_id",),
        boundary="candidate intake only; no formal event promotion or trading authority.",
        preserve_existing_on_blank=True,
    ),
    "collection_runs": StreamSpec(
        name="collection_runs",
        target=ROOT / "data" / "intake" / "collection_runs.csv",
        key_fields=("run_id",),
        boundary="collection audit only; rows_promoted must remain zero.",
    ),
    "enterprise_relation_source_results": StreamSpec(
        name="enterprise_relation_source_results",
        target=ROOT / "data" / "enterprise_relation_source_results.csv",
        key_fields=("source_result_id",),
        boundary="source-result intake only; deterministic owner tools decide any formal promotion.",
    ),
    "event_candidate_repair_workpack": StreamSpec(
        name="event_candidate_repair_workpack",
        target=ROOT / "data" / "intake" / "event_candidate_repair_workpack.csv",
        key_fields=("workpack_id",),
        boundary="repair workpack only; no formal event promotion or trading authority.",
    ),
    "market_move_observations": StreamSpec(
        name="market_move_observations",
        target=ROOT / "data" / "intake" / "market_move_observations.csv",
        key_fields=("observation_id",),
        boundary="market-move observation intake only; attribution remains shadow review context and creates no trading authority.",
    ),
    "sentiment_signals": StreamSpec(
        name="sentiment_signals",
        target=ROOT / "data" / "intake" / "sentiment_signals.csv",
        key_fields=("signal_id",),
        boundary="sentiment / news signal intake only; fast-promote pipeline handles formal event promotion.",
        preserve_existing_on_blank=True,
    ),
}


EVENT_STATUS_RANK = {"rejected": 0, "needs_review": 1, "verified": 2}
EVENT_MATCH_STATUS_RANK = {
    "rejected_noise": 0,
    "rejected_entity_mismatch": 0,
    "duplicate_official_source": 0,
    "needs_review": 1,
    "entity_matched": 2,
}
EVENT_SIGNAL_PRIORITY_RANK = {"reference_only": 0, "P2": 1, "P1": 2, "P0": 3}
SENTIMENT_STATUS_RANK = {"rejected": 0, "needs_review": 1, "sentiment_signal": 2, "verified": 3}
COLLECTION_RUN_RUNTIME_METADATA_FIELDS = {
    "batch_size_processed",
    "batch_size_requested",
    "dispatch_mode",
    "producer",
    "status_reason",
    "stream",
}
ENTERPRISE_SOURCE_RESULT_RUNTIME_METADATA_FIELDS = {
    "attempt_count",
    "processed_at",
    "run_id",
    "source_id",
    "trust_tier",
    "workpack_id",
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def read_csv_or_empty(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        return read_csv(path)
    except FileNotFoundError:
        return [], []


def resolve_fieldnames(spec: StreamSpec, fieldnames: list[str]) -> list[str]:
    """Return canonical fields when a runtime-owned target CSV is empty."""

    if fieldnames:
        return fieldnames
    return list(DEFAULT_STREAM_FIELDS.get(spec.name, []))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        tmp_path.unlink(missing_ok=True)


def init_runtime(runtime_root: Path) -> None:
    for stream in STREAMS:
        (runtime_root / "staging" / stream).mkdir(parents=True, exist_ok=True)
    (runtime_root / "archive").mkdir(parents=True, exist_ok=True)
    (runtime_root / "rejected").mkdir(parents=True, exist_ok=True)
    readme = runtime_root / "README.md"
    if not readme.exists() or ".ndjson.tmp" not in readme.read_text(encoding="utf-8"):
        readme.write_text(LOCAL_README, encoding="utf-8")


def staging_files(runtime_root: Path, stream: str, *, min_file_age_seconds: float = 0) -> tuple[list[Path], list[Path]]:
    staging = runtime_root / "staging"
    candidates: list[Path] = []
    stream_dir = staging / stream
    if stream_dir.exists():
        candidates.extend(sorted(path for path in stream_dir.iterdir() if path.suffix in {".ndjson", ".jsonl"}))
    for suffix in (".ndjson", ".jsonl"):
        direct = staging / f"{stream}{suffix}"
        if direct.exists():
            candidates.append(direct)
    if min_file_age_seconds <= 0:
        return candidates, []
    now = time.time()
    stable: list[Path] = []
    skipped_recent: list[Path] = []
    for path in candidates:
        if now - path.stat().st_mtime < min_file_age_seconds:
            skipped_recent.append(path)
        else:
            stable.append(path)
    return stable, skipped_recent


def _decode_runtime_payloads(text: str, path: Path) -> tuple[list[Any], list[str]]:
    stripped = text.strip()
    if not stripped:
        return [], []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return _decode_json_stream(stripped, path)
    if isinstance(payload, list):
        return payload, []
    return [payload], []


def _decode_json_stream(text: str, path: Path) -> tuple[list[Any], list[str]]:
    decoder = json.JSONDecoder()
    payloads: list[Any] = []
    errors: list[str] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            payload, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            line_no = text.count("\n", 0, index) + 1
            errors.append(f"{path}:{line_no}: invalid json: {exc.msg}")
            break
        payloads.append(payload)
        index = end
    return payloads, errors


def load_runtime_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    text = path.read_text(encoding="utf-8-sig")
    payloads, errors = _decode_runtime_payloads(text, path)
    for payload_index, payload in enumerate(payloads, 1):
        if isinstance(payload, dict) and isinstance(payload.get("row"), dict):
            payload = payload["row"]
        if not isinstance(payload, dict):
            errors.append(f"{path}:payload {payload_index}: expected object or object.row")
            continue
        rows.append({str(key): "" if value is None else str(value) for key, value in payload.items()})
    return rows, errors


def normalize_row(row: dict[str, str], fieldnames: list[str], spec: StreamSpec) -> tuple[dict[str, str] | None, str | None]:
    if spec.name == "collection_runs":
        row = normalize_collection_run_runtime_metadata(row, fieldnames)
    elif spec.name == "enterprise_relation_source_results":
        row = normalize_enterprise_source_result_runtime_metadata(row, fieldnames)
    unknown = sorted(set(row) - set(fieldnames))
    if unknown:
        return None, f"{spec.name}: unknown fields: {', '.join(unknown)}"
    missing_key = [field for field in spec.key_fields if not row.get(field, "").strip()]
    if missing_key:
        return None, f"{spec.name}: missing key fields: {', '.join(missing_key)}"
    normalized = {field: row.get(field, "") for field in fieldnames}
    if spec.name == "collection_runs":
        normalized["rows_promoted"] = "0"
    return normalized, None


def append_detail(existing: str, detail: str) -> str:
    existing = existing.strip()
    detail = detail.strip()
    if not detail:
        return existing
    if not existing:
        return detail
    if detail in existing:
        return existing
    return f"{existing}; {detail}"


def normalize_collection_run_runtime_metadata(row: dict[str, str], fieldnames: list[str]) -> dict[str, str]:
    unknown_metadata = sorted(set(row) & COLLECTION_RUN_RUNTIME_METADATA_FIELDS)
    if not unknown_metadata:
        return row
    normalized = dict(row)
    if normalized.get("batch_size_requested") and not normalized.get("rows_requested"):
        normalized["rows_requested"] = normalized["batch_size_requested"]
    if normalized.get("batch_size_processed"):
        normalized.setdefault("rows_collected", normalized["batch_size_processed"])
        normalized.setdefault("rows_written", normalized["batch_size_processed"])
    if normalized.get("producer"):
        normalized.setdefault("executor", normalized["producer"])
        normalized.setdefault("executor_type", "agent")
    if normalized.get("stream"):
        normalized.setdefault("source_id", normalized["stream"])
        normalized.setdefault("source_name", normalized["stream"])
        normalized.setdefault("task_type", f"{normalized['stream']}_runtime_collection")
    if normalized.get("status_reason"):
        normalized["failure_reason"] = append_detail(
            normalized.get("failure_reason", ""),
            normalized["status_reason"],
        )
    metadata_note = "runtime_metadata=" + ",".join(unknown_metadata)
    if "next_action" in fieldnames:
        normalized["next_action"] = append_detail(
            normalized.get("next_action", ""),
            metadata_note,
        )
    normalized["rows_promoted"] = "0"
    return {field: value for field, value in normalized.items() if field in fieldnames}


def compact_key(value: str, *, fallback: str = "unknown") -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[:;,\n\r\t]+", "_", text)
    return text[:80] or fallback


def enterprise_result_prefix(status: str) -> str:
    if status == "candidate_hint":
        return "candidate"
    if status == "verified_source":
        return "verified"
    if status.startswith("blocked"):
        return status
    if status in {"no_new_data", "duplicate_skip", "needs_alternative_source"}:
        return status
    return "candidate"


def infer_enterprise_source_result_id(row: dict[str, str]) -> str:
    status = row.get("verification_status", "").strip() or "candidate_hint"
    prefix = enterprise_result_prefix(status)
    company = compact_key(row.get("company_code", ""), fallback="unknown_company")
    relation_type = compact_key(row.get("relation_type", ""), fallback="relation")
    counterparty = compact_key(row.get("counterparty_name", ""), fallback="")
    period = compact_key(row.get("report_period") or row.get("source_date") or row.get("run_id"), fallback="runtime")
    if counterparty:
        return f"{prefix}:{company}:{relation_type}:{counterparty}_{period}"
    return f"{prefix}:{company}:{relation_type}:{compact_key(row.get('run_id', ''), fallback=period)}"


def infer_enterprise_source_type(row: dict[str, str]) -> str:
    source_id = (row.get("source_id") or "").lower()
    url = (row.get("source_url") or "").lower()
    if any(token in source_id or token in url for token in ("cninfo", "sse", "szse", "bse", "hkex")):
        return "company_disclosure"
    if any(token in source_id or token in url for token in ("sina", "10jqka", "eastmoney")):
        return "media_mirror"
    if any(token in source_id or token in url for token in ("ir", "irm", "p5w")):
        return "investor_relation"
    return "runtime_source_candidate"


def default_enterprise_confidence(status: str, trust_tier: str) -> str:
    if status == "verified_source":
        return {"S": "0.90", "A": "0.80", "B": "0.60"}.get(trust_tier, "0.45")
    if status == "candidate_hint":
        return {"S": "0.55", "A": "0.50", "B": "0.35"}.get(trust_tier, "0.25")
    return "0.00"


def normalize_enterprise_source_result_runtime_metadata(row: dict[str, str], fieldnames: list[str]) -> dict[str, str]:
    known_runtime_metadata = sorted(set(row) & ENTERPRISE_SOURCE_RESULT_RUNTIME_METADATA_FIELDS)
    if not known_runtime_metadata and row.get("source_result_id"):
        return row

    normalized = dict(row)
    original_status = (normalized.get("verification_status") or "").strip()
    if not normalized.get("source_result_id"):
        if original_status == "verified_source":
            normalized["verification_status"] = "candidate_hint"
            normalized["note"] = append_detail(
                normalized.get("note", ""),
                "runtime_bridge downgraded raw verified_source without canonical source_result_id; requires domain owner re-validation",
            )
        else:
            normalized["verification_status"] = original_status or "candidate_hint"
        normalized["source_result_id"] = infer_enterprise_source_result_id(normalized)

    normalized.setdefault("backlog_id", normalized.get("source_task_id", "").replace("source:", "", 1))
    normalized.setdefault(
        "source_title",
        f"{normalized.get('company_name') or normalized.get('company_code') or 'enterprise'} source candidate",
    )
    normalized.setdefault("source_type", infer_enterprise_source_type(normalized))
    normalized.setdefault(
        "confidence",
        default_enterprise_confidence(normalized.get("verification_status", ""), normalized.get("trust_tier", "")),
    )
    normalized.setdefault(
        "strength",
        "0.30" if normalized.get("verification_status") == "candidate_hint" else "0.00",
    )
    normalized.setdefault("reviewer", "kimiwork_runtime_bridge")
    normalized.setdefault("collected_at", normalized.get("processed_at", ""))
    metadata_bits = [
        f"{field}={normalized.get(field, '')}"
        for field in known_runtime_metadata
        if normalized.get(field, "").strip()
    ]
    if metadata_bits:
        normalized["note"] = append_detail(
            normalized.get("note", ""),
            "runtime_metadata: " + "; ".join(metadata_bits),
        )
    normalized.setdefault(
        "boundary",
        "Enterprise relation source result only; no formal relation promotion or trading authority.",
    )
    return {field: value for field, value in normalized.items() if field in fieldnames}


def looks_like_misrouted_collection_run(row: dict[str, str], spec: StreamSpec) -> bool:
    if spec.name == "collection_runs":
        return False
    if not (row.get("run_id") or "").strip():
        return False
    audit_markers = {"stage", "records", "rows", "rows_promoted", "started_at", "ended_at", "created_at"}
    if not (set(row) & audit_markers):
        return False
    return not all((row.get(field) or "").strip() for field in spec.key_fields)


def infer_collection_status(row: dict[str, str]) -> str:
    records_text = (row.get("records") or "").lower()
    rows = int(row.get("rows") or "0") if (row.get("rows") or "").isdigit() else 0
    if rows <= 0:
        return "no_new_data"
    if "verified_source" in records_text or "candidate" in records_text:
        return "partial_success" if any(token in records_text for token in ("blocked", "no_new_data")) else "success"
    if any(token in records_text for token in ("blocked", "no_new_data", "duplicate")):
        return "partial_success"
    return "success"


def normalize_misrouted_collection_run(
    row: dict[str, str],
    fieldnames: list[str],
    source_spec: StreamSpec,
    source_path: Path,
) -> dict[str, str]:
    rows = row.get("rows", "")
    note = (row.get("note") or "").strip()
    recovered = {
        "run_id": (row.get("run_id") or source_path.stem).strip(),
        "started_at": (row.get("started_at") or row.get("created_at") or "").strip(),
        "finished_at": (row.get("finished_at") or row.get("ended_at") or row.get("created_at") or "").strip(),
        "executor_type": "agent",
        "market_scope": (row.get("market_scope") or "all_markets").strip(),
        "source_id": (row.get("source") or row.get("stream") or source_spec.name).strip(),
        "source_name": (row.get("source") or row.get("stream") or source_spec.name).strip(),
        "task_type": (
            "enterprise_relation_source_collection"
            if "enterprise" in source_spec.name or "enterprise" in (row.get("stream") or "")
            else f"{source_spec.name}_runtime_collection"
        ),
        "input_ref": f"MarketGraphRuntime/staging/{source_spec.name}/{source_path.name}",
        "output_ref": str(source_spec.target.relative_to(ROOT)) if source_spec.target.is_relative_to(ROOT) else str(source_spec.target),
        "rows_requested": rows,
        "rows_collected": rows,
        "rows_written": rows,
        "rows_promoted": "0",
        "rows_rejected": "0",
        "status": infer_collection_status(row),
        "failure_reason": f"misrouted_collection_run_recovered_from:{source_spec.name}",
        "next_action": (
            (note + "; ") if note else ""
        ) + "runtime_bridge 已把误放入业务流的审计摘要转写到 collection_runs；后续写入 staging/collection_runs。",
        "boundary": "Recovered collection audit row only; no formal promotion or trading authority.",
        "formal_delta_ref": "",
        "formal_delta_count": "",
    }
    return {field: recovered.get(field, "") for field in fieldnames}


def upsert_collection_run_rows(rows: list[dict[str, str]], *, apply: bool) -> int:
    if not rows:
        return 0
    spec = STREAMS["collection_runs"]
    fieldnames, existing_rows = read_csv_or_empty(spec.target)
    merged: dict[tuple[str, ...], dict[str, str]] = {}
    order: list[tuple[str, ...]] = []
    for row in existing_rows:
        key = key_for(row, spec)
        if key not in merged:
            order.append(key)
        merged[key] = row
    for row in rows:
        key = key_for(row, spec)
        if key not in merged:
            order.append(key)
        merged[key] = row
    if apply:
        write_csv(spec.target, fieldnames, [merged[key] for key in order])
    return len({key_for(row, spec) for row in rows})


def key_for(row: dict[str, str], spec: StreamSpec) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in spec.key_fields)


def should_preserve_event_candidate_quality_field(field: str, existing_value: str, staged_value: str) -> bool:
    existing = existing_value.strip()
    staged = staged_value.strip()
    if not existing or not staged:
        return False
    if field == "status":
        if existing == "rejected" and staged != existing:
            return True
        if staged == "verified" and existing != "verified":
            return True
        return EVENT_STATUS_RANK.get(staged, EVENT_STATUS_RANK.get(existing, 0)) < EVENT_STATUS_RANK.get(existing, 0)
    if field == "match_status":
        if existing in {"rejected_noise", "rejected_entity_mismatch", "duplicate_official_source"} and staged != existing:
            return True
        return EVENT_MATCH_STATUS_RANK.get(staged, EVENT_MATCH_STATUS_RANK.get(existing, 0)) < EVENT_MATCH_STATUS_RANK.get(existing, 0)
    if field == "signal_priority":
        return EVENT_SIGNAL_PRIORITY_RANK.get(staged, EVENT_SIGNAL_PRIORITY_RANK.get(existing, 0)) < EVENT_SIGNAL_PRIORITY_RANK.get(existing, 0)
    return False


def merge_staged_row(
    existing: dict[str, str],
    staged: dict[str, str],
    fieldnames: list[str],
    spec: StreamSpec,
) -> tuple[dict[str, str], int, int]:
    if not spec.preserve_existing_on_blank:
        return staged, 0, 0
    merged = dict(existing)
    blank_preserved = 0
    protected_preserved = 0
    key_fields = set(spec.key_fields)
    for field in fieldnames:
        staged_value = staged.get(field, "")
        if staged_value.strip():
            existing_value = existing.get(field, "")
            if spec.name == "event_candidates" and should_preserve_event_candidate_quality_field(
                field,
                existing_value,
                staged_value,
            ):
                merged[field] = existing_value
                protected_preserved += 1
                continue
            merged[field] = staged_value
            continue
        existing_value = existing.get(field, "")
        merged[field] = existing_value
        if field not in key_fields and existing_value.strip():
            blank_preserved += 1
    return merged, blank_preserved, protected_preserved



def archive_path(runtime_root: Path, kind: str, stream: str, source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    destination = runtime_root / kind / stamp / stream
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if target.exists():
        target = destination / f"{source.stem}_{datetime.now().strftime('%H%M%S')}{source.suffix}"
    return target


def merge_stream(
    spec: StreamSpec,
    runtime_root: Path,
    *,
    apply: bool,
    min_file_age_seconds: float = 0,
) -> dict[str, Any]:
    fieldnames, existing_rows = read_csv_or_empty(spec.target)
    fieldnames = resolve_fieldnames(spec, fieldnames)
    files, skipped_recent_files = staging_files(
        runtime_root,
        spec.name,
        min_file_age_seconds=min_file_age_seconds if apply else 0,
    )
    summary: dict[str, Any] = {
        "stream": spec.name,
        "target": str(spec.target),
        "files": [str(path) for path in files],
        "skipped_recent_files": [str(path) for path in skipped_recent_files],
        "min_file_age_seconds": min_file_age_seconds if apply else 0,
        "rows_seen": 0,
        "rows_valid": 0,
        "rows_upserted": 0,
        "blank_fields_preserved": 0,
        "protected_fields_preserved": 0,
        "files_archived": 0,
        "files_rejected": 0,
        "files_rerouted": 0,
        "rows_rerouted_to_collection_runs": 0,
        "errors": [],
        "boundary": spec.boundary,
    }
    if not files:
        return summary

    staged_rows: list[dict[str, str]] = []
    rerouted_collection_rows: list[dict[str, str]] = []
    valid_files: list[Path] = []
    rejected_files: list[Path] = []
    for path in files:
        raw_rows, parse_errors = load_runtime_rows(path)
        file_errors = list(parse_errors)
        normalized_rows: list[dict[str, str]] = []
        rerouted_rows: list[dict[str, str]] = []
        for raw_row in raw_rows:
            if looks_like_misrouted_collection_run(raw_row, spec):
                collection_fields, _ = read_csv_or_empty(STREAMS["collection_runs"].target)
                rerouted_rows.append(
                    normalize_misrouted_collection_run(raw_row, collection_fields, spec, path)
                )
                continue
            normalized, error = normalize_row(raw_row, fieldnames, spec)
            if error:
                file_errors.append(f"{path}: {error}")
                continue
            assert normalized is not None
            normalized_rows.append(normalized)
        summary["rows_seen"] += len(raw_rows)
        if file_errors:
            summary["errors"].extend(file_errors)
            rejected_files.append(path)
            continue
        if rerouted_rows:
            rerouted_collection_rows.extend(rerouted_rows)
            summary["rows_rerouted_to_collection_runs"] += len(rerouted_rows)
            summary["files_rerouted"] += 1
        summary["rows_valid"] += len(normalized_rows)
        staged_rows.extend(normalized_rows)
        valid_files.append(path)

    if rerouted_collection_rows:
        summary["rows_upserted"] += upsert_collection_run_rows(rerouted_collection_rows, apply=apply)

    if staged_rows:
        merged: dict[tuple[str, ...], dict[str, str]] = {}
        order: list[tuple[str, ...]] = []
        for row in existing_rows:
            key = key_for(row, spec)
            if key not in merged:
                order.append(key)
            merged[key] = row
        for row in staged_rows:
            key = key_for(row, spec)
            if key not in merged:
                order.append(key)
                merged[key] = row
            else:
                merged[key], blank_preserved, protected_preserved = merge_staged_row(merged[key], row, fieldnames, spec)
                summary["blank_fields_preserved"] += blank_preserved
                summary["protected_fields_preserved"] += protected_preserved
        summary["rows_upserted"] += len({key_for(row, spec) for row in staged_rows})
        if apply:
            write_csv(spec.target, fieldnames, [merged[key] for key in order])

    if apply:
        for path in valid_files:
            shutil.move(str(path), archive_path(runtime_root, "archive", spec.name, path))
            summary["files_archived"] += 1
        for path in rejected_files:
            shutil.move(str(path), archive_path(runtime_root, "rejected", spec.name, path))
            summary["files_rejected"] += 1
    return summary


def merge_runtime(
    runtime_root: Path,
    *,
    apply: bool,
    streams: list[str] | None = None,
    min_file_age_seconds: float = 0,
) -> dict[str, Any]:
    init_runtime(runtime_root)
    selected = streams or list(STREAMS)
    summaries = [
        merge_stream(
            STREAMS[stream],
            runtime_root,
            apply=apply,
            min_file_age_seconds=min_file_age_seconds,
        )
        for stream in selected
    ]
    status = "success"
    if any(item["errors"] for item in summaries):
        status = "partial_success" if any(item["rows_valid"] for item in summaries) else "blocked"
    return {
        "mode": "apply" if apply else "dry_run",
        "runtime_root": str(runtime_root),
        "status": status,
        "streams": summaries,
        "rows_valid": sum(int(item["rows_valid"]) for item in summaries),
        "rows_upserted": sum(int(item["rows_upserted"]) for item in summaries),
        "files_archived": sum(int(item["files_archived"]) for item in summaries),
        "files_rejected": sum(int(item["files_rejected"]) for item in summaries),
        "skipped_recent_files": sum(len(item["skipped_recent_files"]) for item in summaries),
        "boundary": "Runtime bridge validates staging rows and checkpoints them into tracked CSVs; it does not create trading authority.",
    }


def runtime_lock_path(runtime_root: Path) -> Path:
    return runtime_root / ".marketgraph_runtime_bridge.lock"


def acquire_runtime_lock(runtime_root: Path) -> int:
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = runtime_lock_path(runtime_root)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age > LOCK_MAX_AGE_SECONDS:
            path.unlink(missing_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    payload = {
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "max_age_seconds": LOCK_MAX_AGE_SECONDS,
    }
    os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return fd


def release_runtime_lock(runtime_root: Path, fd: int) -> None:
    os.close(fd)
    runtime_lock_path(runtime_root).unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--apply", action="store_true", help="write tracked CSVs and archive processed runtime files")
    parser.add_argument("--init", action="store_true", help="create runtime directories and exit")
    parser.add_argument("--stream", action="append", choices=sorted(STREAMS), help="limit processing to a stream")
    parser.add_argument(
        "--min-file-age-seconds",
        type=float,
        default=None,
        help="when applying, skip staging files modified more recently than this; default is 30 seconds",
    )
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.init:
        init_runtime(args.runtime_root)
        payload = {"mode": "init", "runtime_root": str(args.runtime_root), "streams": sorted(STREAMS)}
    else:
        min_file_age_seconds = (
            args.min_file_age_seconds
            if args.min_file_age_seconds is not None
            else (DEFAULT_APPLY_MIN_FILE_AGE_SECONDS if args.apply else 0)
        )
        lock_fd: int | None = None
        try:
            if args.apply:
                lock_fd = acquire_runtime_lock(args.runtime_root)
            payload = merge_runtime(
                args.runtime_root,
                apply=args.apply,
                streams=args.stream,
                min_file_age_seconds=min_file_age_seconds,
            )
        except FileExistsError:
            payload = {
                "mode": "apply" if args.apply else "dry_run",
                "runtime_root": str(args.runtime_root),
                "status": "skipped_locked",
                "streams": [],
                "lock_path": str(runtime_lock_path(args.runtime_root)),
                "next_action": "another runtime bridge apply is active; retry on the next checkpoint cadence.",
                "boundary": "Runtime bridge did not write tracked CSVs while locked.",
            }
        finally:
            if lock_fd is not None:
                release_runtime_lock(args.runtime_root, lock_fd)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
