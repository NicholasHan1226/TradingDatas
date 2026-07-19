#!/usr/bin/env python3
"""Compile the pinned official Tushare interface index into an offline catalog.

The official Markdown index is capability authority. The legacy 114-name plan is
read only to produce a migration coverage diff. Scope classification and the one
reviewed duplicate-document resolution live in a separate versioned config file.
This module has no provider or network path and emits no runtime activation data.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_capability_scope.v1.yaml"
)
DEFAULT_LEGACY_PATH = REPOSITORY_ROOT / "config" / "tushare_capability_plan.yaml"
DEFAULT_CATALOG_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_capability_catalog.v1.yaml"
)

PINNED_REPOSITORY_URL = "https://github.com/waditu-tushare/skills.git"
PINNED_SOURCE_COMMIT = "5e12b31d09123e262c5fb38564e80c26d05cb830"
PINNED_INDEX_PATH = "tushare/references/数据接口.md"
PINNED_INDEX_SHA256 = (
    "0df85aa1265a59b963fca6660eb3f58bec232aa2347c9c44d763d0d55a1b9cb2"
)

EXPECTED_OFFICIAL_COUNTS = {
    "official_source_rows": 240,
    "official_unique_api_names": 239,
}
EXPECTED_SCOPE_COUNTS = {
    "in_scope": 190,
    "locked": 0,
    "unknown": 4,
    "excluded": 36,
    "retired": 5,
    "non_data_operation": 4,
}
EXPECTED_LEGACY_COUNTS = {
    "legacy_api_names": 114,
    "official_legacy_overlap": 109,
    "official_only": 130,
    "legacy_only": 5,
}
SCOPE_STATES = tuple(EXPECTED_SCOPE_COUNTS)

_EXPECTED_PREAMBLE = (
    "",
    "",
    "# 接口列表",
    "",
    "根据需求确定接口，然后访问在线链接，读取具体的使用说明，比如入参，出参等。",
    "",
)
_EXPECTED_HEADER = ("在线文档", "接口名", "标题", "分类", "描述")
_API_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_DOC_URL_PATTERN = re.compile(
    r"https://tushare\.pro/wctapi/documents/[1-9][0-9]*\.md"
)
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]*")
_SEPARATOR_PATTERN = re.compile(r":?-{3,}:?")

_SCOPE_ROOT_KEYS = frozenset(
    {
        "version",
        "scope_id",
        "catalog_id",
        "provider",
        "official_source",
        "expected_counts",
        "duplicate_api_resolutions",
        "classifications",
        "legacy_coverage",
    }
)
_SOURCE_KEYS = frozenset(
    {"repository_url", "pinned_commit", "index_path", "index_sha256"}
)
_DUPLICATE_RESOLUTION_KEYS = frozenset(
    {"api_name", "canonical_doc_url", "reason"}
)
_CLASSIFICATION_KEYS = frozenset({"scope_state", "reason", "api_names"})
_LEGACY_SCOPE_KEYS = frozenset(
    {
        "authority",
        "inventory_path",
        "inventory_sha256",
        "expected_counts",
        "legacy_only_reviews",
    }
)
_LEGACY_REVIEW_KEYS = frozenset({"api_name", "review_state", "reason"})

_CATALOG_ROOT_KEYS = frozenset(
    {
        "version",
        "catalog_id",
        "provider",
        "provenance",
        "scope",
        "counts",
        "scope_counts",
        "legacy_coverage",
        "capabilities",
    }
)
_CATALOG_SCOPE_KEYS = frozenset({"scope_id", "scope_sha256"})
_CATALOG_LEGACY_KEYS = frozenset(
    {
        "authority",
        "inventory_path",
        "inventory_sha256",
        "counts",
        "legacy_only_reviews",
    }
)
_CAPABILITY_KEYS = frozenset(
    {
        "api_name",
        "doc_url",
        "title",
        "category",
        "description",
        "source_rows",
        "source_resolution",
        "scope_state",
        "scope_reason",
        "in_legacy_inventory",
    }
)
_SOURCE_ROW_KEYS = frozenset(
    {
        "line_number",
        "row_sha256",
        "api_name",
        "doc_url",
        "title",
        "category",
        "description",
    }
)
_LEGACY_PLAN_ROOT_KEYS = frozenset(
    {"version", "purpose", "activation_modes", "modules"}
)
_LEGACY_MODULE_KEYS = frozenset(
    {"module", "market", "default_cadence", "apis"}
)
_LEGACY_API_KEYS = frozenset({"api_name", "mode", "tier", "cadence"})


@dataclass(frozen=True)
class OfficialIndexRow:
    """One physical Markdown table row in the pinned official index."""

    api_name: str
    doc_url: str
    title: str
    category: str
    description: str
    line_number: int
    row_sha256: str

    def as_catalog_source_row(self) -> dict[str, object]:
        return {
            "line_number": self.line_number,
            "row_sha256": self.row_sha256,
            "api_name": self.api_name,
            "doc_url": self.doc_url,
            "title": self.title,
            "category": self.category,
            "description": self.description,
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _reject_unknown_keys(
    value: Mapping[str, object],
    allowed: frozenset[str],
    label: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown key(s): {', '.join(unknown)}")
    missing = sorted((required or allowed) - set(value))
    if missing:
        raise ValueError(f"{label} is missing key(s): {', '.join(missing)}")


def _required_text(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
    allow_surrounding: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValueError(f"{label} must be a non-empty string")
    if value != normalized and not allow_surrounding:
        raise ValueError(f"{label} must not have surrounding whitespace")
    return normalized if allow_surrounding else value


def _required_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _validate_api_name(value: object, label: str) -> str:
    api_name = _required_text(value, label)
    if _API_NAME_PATTERN.fullmatch(api_name) is None:
        raise ValueError(f"{label} is not a valid api_name")
    return api_name


def _validate_doc_url(value: object, label: str) -> str:
    doc_url = _required_text(value, label)
    if _DOC_URL_PATTERN.fullmatch(doc_url) is None:
        raise ValueError(f"{label} is not a valid official doc_url")
    return doc_url


def _validate_hash(value: object, label: str) -> str:
    digest = _required_text(value, label)
    if _HASH_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return digest


def _validate_exact_counts(
    value: object, expected: Mapping[str, int], label: str
) -> dict[str, int]:
    counts = _mapping(value, label)
    _reject_unknown_keys(counts, frozenset(expected), label)
    normalized = {
        key: _required_int(counts[key], f"{label}.{key}") for key in expected
    }
    if normalized != dict(expected):
        raise ValueError(f"{label} does not match the frozen expected counts")
    return normalized


def validate_scope_document(document: object) -> dict[str, Any]:
    """Validate the reviewed scope config with a closed schema."""

    root = _mapping(document, "scope document")
    _reject_unknown_keys(root, _SCOPE_ROOT_KEYS, "scope document")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("scope document.version must be integer 1")

    for key in ("scope_id", "catalog_id"):
        value = _required_text(root[key], f"scope document.{key}")
        if _ID_PATTERN.fullmatch(value) is None:
            raise ValueError(f"scope document.{key} is invalid")
    if root["provider"] != "tushare":
        raise ValueError("scope document.provider must be tushare")

    source = _mapping(root["official_source"], "scope document.official_source")
    _reject_unknown_keys(source, _SOURCE_KEYS, "scope document.official_source")
    expected_source = {
        "repository_url": PINNED_REPOSITORY_URL,
        "pinned_commit": PINNED_SOURCE_COMMIT,
        "index_path": PINNED_INDEX_PATH,
        "index_sha256": PINNED_INDEX_SHA256,
    }
    if source != expected_source:
        raise ValueError("scope document.official_source does not match the frozen pin")
    _validate_exact_counts(
        root["expected_counts"],
        EXPECTED_OFFICIAL_COUNTS,
        "scope document.expected_counts",
    )

    resolution_names: set[str] = set()
    for index, raw_resolution in enumerate(
        _sequence(
            root["duplicate_api_resolutions"],
            "scope document.duplicate_api_resolutions",
        )
    ):
        label = f"scope document.duplicate_api_resolutions[{index}]"
        resolution = _mapping(raw_resolution, label)
        _reject_unknown_keys(resolution, _DUPLICATE_RESOLUTION_KEYS, label)
        api_name = _validate_api_name(resolution["api_name"], f"{label}.api_name")
        _validate_doc_url(
            resolution["canonical_doc_url"], f"{label}.canonical_doc_url"
        )
        _required_text(resolution["reason"], f"{label}.reason")
        if api_name in resolution_names:
            raise ValueError(f"duplicate resolution for api_name: {api_name}")
        resolution_names.add(api_name)

    classification_names: set[str] = set()
    observed_states: set[str] = set()
    observed_counts: Counter[str] = Counter()
    for index, raw_classification in enumerate(
        _sequence(root["classifications"], "scope document.classifications")
    ):
        label = f"scope document.classifications[{index}]"
        classification = _mapping(raw_classification, label)
        _reject_unknown_keys(classification, _CLASSIFICATION_KEYS, label)
        state = _required_text(
            classification["scope_state"], f"{label}.scope_state"
        )
        if state not in SCOPE_STATES:
            raise ValueError(f"{label}.scope_state is invalid: {state}")
        if state in observed_states:
            raise ValueError(f"duplicate scope_state classification: {state}")
        observed_states.add(state)
        _required_text(classification["reason"], f"{label}.reason")
        for api_index, raw_api_name in enumerate(
            _sequence(classification["api_names"], f"{label}.api_names")
        ):
            api_name = _validate_api_name(
                raw_api_name, f"{label}.api_names[{api_index}]"
            )
            if api_name in classification_names:
                raise ValueError(f"duplicate classification for api_name: {api_name}")
            classification_names.add(api_name)
            observed_counts[state] += 1
    if observed_states != set(SCOPE_STATES):
        missing = sorted(set(SCOPE_STATES) - observed_states)
        raise ValueError(f"scope document is missing scope_state(s): {', '.join(missing)}")
    normalized_scope_counts = {
        state: observed_counts[state] for state in SCOPE_STATES
    }
    if normalized_scope_counts != EXPECTED_SCOPE_COUNTS:
        raise ValueError("scope classification counts do not match the frozen review")

    legacy = _mapping(root["legacy_coverage"], "scope document.legacy_coverage")
    _reject_unknown_keys(legacy, _LEGACY_SCOPE_KEYS, "scope document.legacy_coverage")
    if legacy["authority"] != "migration_input_only":
        raise ValueError("legacy coverage authority must be migration_input_only")
    if legacy["inventory_path"] != "config/tushare_capability_plan.yaml":
        raise ValueError("legacy coverage inventory_path is not the frozen input")
    _validate_hash(
        legacy["inventory_sha256"],
        "scope document.legacy_coverage.inventory_sha256",
    )
    _validate_exact_counts(
        legacy["expected_counts"],
        EXPECTED_LEGACY_COUNTS,
        "scope document.legacy_coverage.expected_counts",
    )
    review_names: list[str] = []
    for index, raw_review in enumerate(
        _sequence(
            legacy["legacy_only_reviews"],
            "scope document.legacy_coverage.legacy_only_reviews",
        )
    ):
        label = f"scope document.legacy_coverage.legacy_only_reviews[{index}]"
        review = _mapping(raw_review, label)
        _reject_unknown_keys(review, _LEGACY_REVIEW_KEYS, label)
        review_names.append(
            _validate_api_name(review["api_name"], f"{label}.api_name")
        )
        if review["review_state"] != "migration_review_required":
            raise ValueError(f"{label}.review_state is invalid")
        _required_text(review["reason"], f"{label}.reason")
    if review_names != sorted(review_names):
        raise ValueError("legacy-only reviews must be sorted by api_name")
    if len(review_names) != len(set(review_names)):
        raise ValueError("legacy-only reviews contain duplicate api_name values")
    if len(review_names) != EXPECTED_LEGACY_COUNTS["legacy_only"]:
        raise ValueError("legacy-only review count does not match the frozen review")
    return root


def load_scope_document(path: Path = DEFAULT_SCOPE_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_scope_document(payload)


def _table_cells(line: str, line_number: int) -> tuple[str, ...]:
    if not line.startswith("|") or not line.endswith("|"):
        raise ValueError(f"official index format drift at line {line_number}")
    cells = tuple(cell.strip() for cell in line.split("|")[1:-1])
    if len(cells) != 5:
        raise ValueError(
            f"official index line {line_number} must contain exactly five cells"
        )
    return cells


def parse_official_index(index_bytes: bytes) -> tuple[OfficialIndexRow, ...]:
    """Parse the closed five-column Markdown grammar without deduplicating."""

    if b"\r" in index_bytes:
        raise ValueError("official index format drift: CR line endings are not allowed")
    if not index_bytes.endswith(b"\n"):
        raise ValueError("official index format drift: final newline is required")
    try:
        text = index_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("official index must be valid UTF-8") from exc
    lines = text.splitlines()
    if tuple(lines[:6]) != _EXPECTED_PREAMBLE:
        raise ValueError("official index preamble format drift")
    if len(lines) < 9:
        raise ValueError("official index table is missing")

    try:
        header = _table_cells(lines[6], 7)
    except ValueError as exc:
        raise ValueError(
            "official index header does not match expected fields"
        ) from exc
    if header != _EXPECTED_HEADER:
        raise ValueError("official index header does not match expected fields")
    separator = _table_cells(lines[7], 8)
    if any(_SEPARATOR_PATTERN.fullmatch(cell) is None for cell in separator):
        raise ValueError("official index separator format drift")

    rows: list[OfficialIndexRow] = []
    for zero_index, raw_line in enumerate(lines[8:], start=8):
        line_number = zero_index + 1
        if not raw_line:
            raise ValueError(f"official index format drift at line {line_number}")
        doc_url, api_name, title, category, description = _table_cells(
            raw_line, line_number
        )
        _validate_doc_url(doc_url, f"official index line {line_number}.doc_url")
        _validate_api_name(api_name, f"official index line {line_number}.api_name")
        _required_text(title, f"official index line {line_number}.title")
        _required_text(category, f"official index line {line_number}.category")
        _required_text(
            description,
            f"official index line {line_number}.description",
            allow_empty=True,
        )
        rows.append(
            OfficialIndexRow(
                api_name=api_name,
                doc_url=doc_url,
                title=title,
                category=category,
                description=description,
                line_number=line_number,
                row_sha256=_sha256_bytes(raw_line.encode("utf-8")),
            )
        )
    return tuple(rows)


def resolve_official_rows(
    rows: Sequence[OfficialIndexRow],
    duplicate_resolutions: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Resolve only explicitly reviewed duplicate names and preserve all rows."""

    grouped: dict[str, list[OfficialIndexRow]] = defaultdict(list)
    for row in rows:
        grouped[row.api_name].append(row)

    resolutions: dict[str, tuple[str, str]] = {}
    for index, raw_resolution in enumerate(duplicate_resolutions):
        label = f"duplicate_api_resolutions[{index}]"
        resolution = _mapping(raw_resolution, label)
        _reject_unknown_keys(resolution, _DUPLICATE_RESOLUTION_KEYS, label)
        api_name = _validate_api_name(resolution["api_name"], f"{label}.api_name")
        canonical_doc_url = _validate_doc_url(
            resolution["canonical_doc_url"], f"{label}.canonical_doc_url"
        )
        reason = _required_text(resolution["reason"], f"{label}.reason")
        if api_name in resolutions:
            raise ValueError(f"duplicate resolution for api_name: {api_name}")
        resolutions[api_name] = (canonical_doc_url, reason)

    duplicate_names = {name for name, values in grouped.items() if len(values) > 1}
    missing = sorted(duplicate_names - set(resolutions))
    if missing:
        raise ValueError(f"unreviewed duplicate api_name(s): {', '.join(missing)}")
    extra = sorted(set(resolutions) - duplicate_names)
    if extra:
        raise ValueError(
            "duplicate resolution references non-duplicated api_name(s): "
            + ", ".join(extra)
        )

    resolved: list[dict[str, object]] = []
    for api_name, source_rows in grouped.items():
        row_hashes = [row.row_sha256 for row in source_rows]
        if len(row_hashes) != len(set(row_hashes)):
            raise ValueError(f"duplicate official source row for api_name: {api_name}")
        if len(source_rows) == 1:
            canonical = source_rows[0]
            resolution_reason = "single_official_index_row"
        else:
            canonical_url, resolution_reason = resolutions[api_name]
            candidates = [row for row in source_rows if row.doc_url == canonical_url]
            if len(candidates) != 1:
                raise ValueError(
                    f"canonical_doc_url must select exactly one row for {api_name}"
                )
            canonical = candidates[0]
        resolved.append(
            {
                "api_name": canonical.api_name,
                "doc_url": canonical.doc_url,
                "title": canonical.title,
                "category": canonical.category,
                "description": canonical.description,
                "source_rows": [
                    row.as_catalog_source_row()
                    for row in sorted(source_rows, key=lambda item: item.line_number)
                ],
                "source_resolution": resolution_reason,
            }
        )
    return tuple(resolved)


def _parse_legacy_api_names(legacy_bytes: bytes) -> tuple[str, ...]:
    try:
        document = yaml.safe_load(legacy_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("legacy inventory must be valid UTF-8 YAML") from exc
    root = _mapping(document, "legacy inventory")
    _reject_unknown_keys(root, _LEGACY_PLAN_ROOT_KEYS, "legacy inventory")
    _required_text(
        root["purpose"],
        "legacy inventory.purpose",
        allow_surrounding=True,
    )
    activation_modes = _mapping(
        root["activation_modes"], "legacy inventory.activation_modes"
    )
    for mode, description in activation_modes.items():
        _required_text(mode, "legacy inventory.activation_modes key")
        _required_text(
            description, f"legacy inventory.activation_modes.{mode}"
        )

    names: list[str] = []
    for module_index, raw_module in enumerate(
        _sequence(root["modules"], "legacy inventory.modules")
    ):
        label = f"legacy inventory.modules[{module_index}]"
        module = _mapping(raw_module, label)
        _reject_unknown_keys(module, _LEGACY_MODULE_KEYS, label)
        for key in ("module", "market", "default_cadence"):
            _required_text(module[key], f"{label}.{key}")
        for api_index, raw_api in enumerate(
            _sequence(module["apis"], f"{label}.apis")
        ):
            api_label = f"{label}.apis[{api_index}]"
            api = _mapping(raw_api, api_label)
            _reject_unknown_keys(
                api,
                _LEGACY_API_KEYS,
                api_label,
                required=frozenset({"api_name", "mode", "cadence"}),
            )
            names.append(
                _validate_api_name(api["api_name"], f"{api_label}.api_name")
            )
            _required_text(api["mode"], f"{api_label}.mode")
            _required_text(api["cadence"], f"{api_label}.cadence")
            if "tier" in api:
                _required_text(api["tier"], f"{api_label}.tier")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"legacy inventory duplicate api_name(s): {', '.join(duplicates)}")
    return tuple(sorted(names))


def _classification_index(
    scope: Mapping[str, object], official_names: set[str]
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    classifications = _sequence(scope["classifications"], "scope.classifications")
    for raw_classification in classifications:
        classification = _mapping(raw_classification, "scope classification")
        state = str(classification["scope_state"])
        reason = str(classification["reason"])
        for api_name in _sequence(
            classification["api_names"], "scope classification.api_names"
        ):
            result[str(api_name)] = (state, reason)
    missing = sorted(official_names - set(result))
    extra = sorted(set(result) - official_names)
    if missing:
        raise ValueError(f"official api_name(s) lack classification: {', '.join(missing)}")
    if extra:
        raise ValueError(f"scope classifies unknown api_name(s): {', '.join(extra)}")
    return result


def compile_capability_catalog(
    *,
    index_bytes: bytes,
    scope_document: object,
    scope_sha256: str,
    legacy_bytes: bytes,
) -> dict[str, object]:
    """Compile one deterministic catalog from already-local bytes."""

    scope = validate_scope_document(scope_document)
    _validate_hash(scope_sha256, "scope_sha256")
    source = _mapping(scope["official_source"], "scope.official_source")
    if _sha256_bytes(index_bytes) != source["index_sha256"]:
        raise ValueError("official index SHA-256 does not match the frozen source")
    rows = parse_official_index(index_bytes)
    if len(rows) != EXPECTED_OFFICIAL_COUNTS["official_source_rows"]:
        raise ValueError("official source row count does not match the frozen source")
    official_names = {row.api_name for row in rows}
    if len(official_names) != EXPECTED_OFFICIAL_COUNTS["official_unique_api_names"]:
        raise ValueError("official unique api_name count does not match the frozen source")
    resolved = resolve_official_rows(
        rows,
        _sequence(
            scope["duplicate_api_resolutions"],
            "scope.duplicate_api_resolutions",
        ),
    )
    classifications = _classification_index(scope, official_names)

    legacy = _mapping(scope["legacy_coverage"], "scope.legacy_coverage")
    if _sha256_bytes(legacy_bytes) != legacy["inventory_sha256"]:
        raise ValueError("legacy inventory SHA-256 does not match the reviewed input")
    legacy_names = set(_parse_legacy_api_names(legacy_bytes))
    overlap = official_names & legacy_names
    official_only = official_names - legacy_names
    legacy_only = legacy_names - official_names
    coverage_counts = {
        "legacy_api_names": len(legacy_names),
        "official_legacy_overlap": len(overlap),
        "official_only": len(official_only),
        "legacy_only": len(legacy_only),
    }
    if coverage_counts != EXPECTED_LEGACY_COUNTS:
        raise ValueError("legacy coverage diff does not match the frozen review")

    raw_reviews = _sequence(
        legacy["legacy_only_reviews"], "legacy.legacy_only_reviews"
    )
    review_names = {str(review["api_name"]) for review in raw_reviews}
    if review_names != legacy_only:
        missing = sorted(legacy_only - review_names)
        extra = sorted(review_names - legacy_only)
        raise ValueError(
            "legacy-only reviews do not match the coverage diff; "
            f"missing={missing}, extra={extra}"
        )

    capabilities: list[dict[str, object]] = []
    for capability in sorted(resolved, key=lambda item: str(item["api_name"])):
        api_name = str(capability["api_name"])
        state, reason = classifications[api_name]
        capabilities.append(
            {
                "api_name": api_name,
                "doc_url": capability["doc_url"],
                "title": capability["title"],
                "category": capability["category"],
                "description": capability["description"],
                "source_rows": capability["source_rows"],
                "source_resolution": capability["source_resolution"],
                "scope_state": state,
                "scope_reason": reason,
                "in_legacy_inventory": api_name in legacy_names,
            }
        )

    catalog: dict[str, object] = {
        "version": 1,
        "catalog_id": scope["catalog_id"],
        "provider": "tushare",
        "provenance": {
            "repository_url": source["repository_url"],
            "pinned_commit": source["pinned_commit"],
            "index_path": source["index_path"],
            "index_sha256": source["index_sha256"],
        },
        "scope": {
            "scope_id": scope["scope_id"],
            "scope_sha256": scope_sha256,
        },
        "counts": dict(EXPECTED_OFFICIAL_COUNTS),
        "scope_counts": dict(EXPECTED_SCOPE_COUNTS),
        "legacy_coverage": {
            "authority": "migration_input_only",
            "inventory_path": legacy["inventory_path"],
            "inventory_sha256": legacy["inventory_sha256"],
            "counts": coverage_counts,
            "legacy_only_reviews": [
                {
                    "api_name": review["api_name"],
                    "review_state": review["review_state"],
                    "reason": review["reason"],
                }
                for review in raw_reviews
            ],
        },
        "capabilities": capabilities,
    }
    return validate_catalog_document(catalog)


def _git_head(source_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(source_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("cannot verify pinned source checkout HEAD") from exc
    if completed.returncode != 0:
        raise ValueError("source root is not a readable Git checkout")
    head = completed.stdout.strip()
    if _COMMIT_PATTERN.fullmatch(head) is None:
        raise ValueError("source checkout returned an invalid Git HEAD")
    return head


def _read_pinned_index(source_root: Path) -> bytes:
    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("source root must be a directory")
    head = _git_head(root)
    if head != PINNED_SOURCE_COMMIT:
        raise ValueError(
            f"source checkout HEAD {head} does not match {PINNED_SOURCE_COMMIT}"
        )
    relative = PurePosixPath(PINNED_INDEX_PATH)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("pinned index path must be repository-relative")
    index_path = root.joinpath(*relative.parts)
    index_bytes = index_path.read_bytes()
    if _sha256_bytes(index_bytes) != PINNED_INDEX_SHA256:
        raise ValueError("pinned source index SHA-256 mismatch")
    return index_bytes


def compile_from_paths(
    *,
    source_root: Path,
    scope_path: Path = DEFAULT_SCOPE_PATH,
    legacy_path: Path = DEFAULT_LEGACY_PATH,
) -> dict[str, object]:
    """Compile from an offline pinned checkout and local reviewed config."""

    scope_bytes = scope_path.read_bytes()
    try:
        scope_payload = yaml.safe_load(scope_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("scope config must be valid UTF-8 YAML") from exc
    return compile_capability_catalog(
        index_bytes=_read_pinned_index(source_root),
        scope_document=scope_payload,
        scope_sha256=_sha256_bytes(scope_bytes),
        legacy_bytes=legacy_path.read_bytes(),
    )


def validate_catalog_document(document: object) -> dict[str, Any]:
    """Validate generated catalog bytes with a closed, self-consistent schema."""

    root = _mapping(document, "capability catalog")
    _reject_unknown_keys(root, _CATALOG_ROOT_KEYS, "capability catalog")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("capability catalog.version must be integer 1")
    catalog_id = _required_text(root["catalog_id"], "capability catalog.catalog_id")
    if _ID_PATTERN.fullmatch(catalog_id) is None:
        raise ValueError("capability catalog.catalog_id is invalid")
    if root["provider"] != "tushare":
        raise ValueError("capability catalog.provider must be tushare")

    provenance = _mapping(root["provenance"], "capability catalog.provenance")
    _reject_unknown_keys(provenance, _SOURCE_KEYS, "capability catalog.provenance")
    if provenance != {
        "repository_url": PINNED_REPOSITORY_URL,
        "pinned_commit": PINNED_SOURCE_COMMIT,
        "index_path": PINNED_INDEX_PATH,
        "index_sha256": PINNED_INDEX_SHA256,
    }:
        raise ValueError("capability catalog provenance does not match the frozen pin")

    scope = _mapping(root["scope"], "capability catalog.scope")
    _reject_unknown_keys(scope, _CATALOG_SCOPE_KEYS, "capability catalog.scope")
    scope_id = _required_text(scope["scope_id"], "capability catalog.scope.scope_id")
    if _ID_PATTERN.fullmatch(scope_id) is None:
        raise ValueError("capability catalog.scope.scope_id is invalid")
    _validate_hash(scope["scope_sha256"], "capability catalog.scope.scope_sha256")
    _validate_exact_counts(
        root["counts"], EXPECTED_OFFICIAL_COUNTS, "capability catalog.counts"
    )
    _validate_exact_counts(
        root["scope_counts"],
        EXPECTED_SCOPE_COUNTS,
        "capability catalog.scope_counts",
    )

    legacy = _mapping(root["legacy_coverage"], "capability catalog.legacy_coverage")
    _reject_unknown_keys(legacy, _CATALOG_LEGACY_KEYS, "capability catalog.legacy_coverage")
    if legacy["authority"] != "migration_input_only":
        raise ValueError("catalog legacy authority must be migration_input_only")
    if legacy["inventory_path"] != "config/tushare_capability_plan.yaml":
        raise ValueError("catalog legacy inventory_path is invalid")
    _validate_hash(
        legacy["inventory_sha256"],
        "capability catalog.legacy_coverage.inventory_sha256",
    )
    legacy_counts = _validate_exact_counts(
        legacy["counts"],
        EXPECTED_LEGACY_COUNTS,
        "capability catalog.legacy_coverage.counts",
    )
    legacy_review_names: list[str] = []
    for index, raw_review in enumerate(
        _sequence(
            legacy["legacy_only_reviews"],
            "capability catalog.legacy_coverage.legacy_only_reviews",
        )
    ):
        label = f"capability catalog.legacy_coverage.legacy_only_reviews[{index}]"
        review = _mapping(raw_review, label)
        _reject_unknown_keys(review, _LEGACY_REVIEW_KEYS, label)
        legacy_review_names.append(
            _validate_api_name(review["api_name"], f"{label}.api_name")
        )
        if review["review_state"] != "migration_review_required":
            raise ValueError(f"{label}.review_state is invalid")
        _required_text(review["reason"], f"{label}.reason")
    if legacy_review_names != sorted(legacy_review_names):
        raise ValueError("catalog legacy-only reviews must be sorted")
    if len(set(legacy_review_names)) != legacy_counts["legacy_only"]:
        raise ValueError("catalog legacy-only reviews are duplicate or incomplete")

    capabilities = _sequence(root["capabilities"], "capability catalog.capabilities")
    api_names: list[str] = []
    actual_scope_counts: Counter[str] = Counter()
    source_line_numbers: list[int] = []
    source_row_hashes: list[str] = []
    legacy_overlap_count = 0
    for index, raw_capability in enumerate(capabilities):
        label = f"capability catalog.capabilities[{index}]"
        capability = _mapping(raw_capability, label)
        _reject_unknown_keys(capability, _CAPABILITY_KEYS, label)
        api_name = _validate_api_name(capability["api_name"], f"{label}.api_name")
        api_names.append(api_name)
        doc_url = _validate_doc_url(capability["doc_url"], f"{label}.doc_url")
        title = _required_text(capability["title"], f"{label}.title")
        category = _required_text(capability["category"], f"{label}.category")
        description = _required_text(
            capability["description"], f"{label}.description", allow_empty=True
        )
        resolution = _required_text(
            capability["source_resolution"], f"{label}.source_resolution"
        )
        state = _required_text(capability["scope_state"], f"{label}.scope_state")
        if state not in SCOPE_STATES:
            raise ValueError(f"{label}.scope_state is invalid")
        actual_scope_counts[state] += 1
        _required_text(capability["scope_reason"], f"{label}.scope_reason")
        if type(capability["in_legacy_inventory"]) is not bool:
            raise ValueError(f"{label}.in_legacy_inventory must be a boolean")
        legacy_overlap_count += int(capability["in_legacy_inventory"])

        source_rows = _sequence(capability["source_rows"], f"{label}.source_rows")
        if not source_rows:
            raise ValueError(f"{label}.source_rows must not be empty")
        canonical_matches = 0
        local_line_numbers: list[int] = []
        for row_index, raw_source_row in enumerate(source_rows):
            row_label = f"{label}.source_rows[{row_index}]"
            source_row = _mapping(raw_source_row, row_label)
            _reject_unknown_keys(source_row, _SOURCE_ROW_KEYS, row_label)
            line_number = _required_int(
                source_row["line_number"], f"{row_label}.line_number", minimum=1
            )
            local_line_numbers.append(line_number)
            source_line_numbers.append(line_number)
            source_row_hashes.append(
                _validate_hash(source_row["row_sha256"], f"{row_label}.row_sha256")
            )
            row_api_name = _validate_api_name(
                source_row["api_name"], f"{row_label}.api_name"
            )
            row_doc_url = _validate_doc_url(
                source_row["doc_url"], f"{row_label}.doc_url"
            )
            row_title = _required_text(source_row["title"], f"{row_label}.title")
            row_category = _required_text(
                source_row["category"], f"{row_label}.category"
            )
            row_description = _required_text(
                source_row["description"],
                f"{row_label}.description",
                allow_empty=True,
            )
            if row_api_name != api_name:
                raise ValueError(f"{row_label}.api_name does not match its capability")
            if (
                row_doc_url,
                row_title,
                row_category,
                row_description,
            ) == (doc_url, title, category, description):
                canonical_matches += 1
        if local_line_numbers != sorted(local_line_numbers):
            raise ValueError(f"{label}.source_rows must be ordered by line_number")
        if len(local_line_numbers) != len(set(local_line_numbers)):
            raise ValueError(f"{label}.source_rows contain duplicate line identity")
        if canonical_matches != 1:
            raise ValueError(f"{label} canonical fields must match exactly one source row")
        if len(source_rows) == 1 and resolution != "single_official_index_row":
            raise ValueError(f"{label}.source_resolution is invalid for one source row")
        if len(source_rows) > 1 and resolution == "single_official_index_row":
            raise ValueError(f"{label}.source_resolution lacks reviewed duplicate reason")

    duplicate_api_names = sorted(
        name for name, count in Counter(api_names).items() if count > 1
    )
    if duplicate_api_names:
        raise ValueError(
            f"capability catalog duplicate api_name(s): {', '.join(duplicate_api_names)}"
        )
    if api_names != sorted(api_names):
        raise ValueError("capability catalog api_name values must be sorted")
    if len(api_names) != EXPECTED_OFFICIAL_COUNTS["official_unique_api_names"]:
        raise ValueError("capability catalog does not contain exactly 239 api_name values")
    if {
        state: actual_scope_counts[state] for state in SCOPE_STATES
    } != EXPECTED_SCOPE_COUNTS:
        raise ValueError("capability rows do not match scope_counts")
    if legacy_overlap_count != legacy_counts["official_legacy_overlap"]:
        raise ValueError("capability legacy overlap flags do not match coverage counts")
    if len(source_line_numbers) != EXPECTED_OFFICIAL_COUNTS["official_source_rows"]:
        raise ValueError("catalog source row count does not match counts")
    if len(source_line_numbers) != len(set(source_line_numbers)):
        raise ValueError("catalog contains duplicate source line identity")
    if set(source_line_numbers) != set(range(9, 249)):
        raise ValueError("catalog source line identities do not cover the pinned table")
    if len(source_row_hashes) != len(set(source_row_hashes)):
        raise ValueError("catalog contains duplicate source row SHA-256 identity")
    if set(legacy_review_names) & set(api_names):
        raise ValueError("legacy-only review api_name appears in official catalog")
    return root


def load_capability_catalog(path: Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_catalog_document(payload)


def render_catalog(document: object) -> bytes:
    validated = validate_catalog_document(document)
    rendered = yaml.safe_dump(
        validated,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1_000,
    )
    return rendered.encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {parent}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="local offline checkout at the frozen Git commit",
    )
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE_PATH)
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY_PATH)
    parser.add_argument(
        "--catalog-path",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="checked-in catalog used by --check",
    )
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument("--check", action="store_true")
    output_mode.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        catalog = compile_from_paths(
            source_root=args.source_root,
            scope_path=args.scope,
            legacy_path=args.legacy,
        )
        rendered = render_catalog(catalog)
        if args.check:
            if args.catalog_path.read_bytes() != rendered:
                print("checked-in capability catalog is stale", file=sys.stderr)
                return 1
        elif args.output is not None:
            _atomic_write(args.output, rendered)
        else:
            sys.stdout.buffer.write(rendered)
        coverage = catalog["legacy_coverage"]["counts"]
        print(
            "official=239 legacy=114 overlap="
            f"{coverage['official_legacy_overlap']} official_only="
            f"{coverage['official_only']} legacy_only={coverage['legacy_only']}",
            file=sys.stderr,
        )
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"capability catalog compilation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
