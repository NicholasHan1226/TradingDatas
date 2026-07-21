#!/usr/bin/env python3
"""Compile provider-neutral Tushare capability catalogs from offline snapshots.

Version 1 preserves the pinned official Markdown index compiler. Version 2 merges
that checked-in official catalog with a metadata-only MCP capability snapshot and
keeps product scope, lifecycle, contract state, MCP visibility, entitlement, and
activation independent. This module has no provider, network, database, public
route, or runtime execution path.
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
DEFAULT_SCOPE_PATH = REPOSITORY_ROOT / "config" / "tushare_capability_scope.v1.yaml"
DEFAULT_CATALOG_PATH = REPOSITORY_ROOT / "config" / "tushare_capability_catalog.v1.yaml"
DEFAULT_SCOPE_V2_PATH = REPOSITORY_ROOT / "config" / "tushare_capability_scope.v2.yaml"
DEFAULT_MCP_SNAPSHOT_PATH = (
    REPOSITORY_ROOT / "config" / "tushare_mcp_capability_snapshot.v1.yaml"
)

PINNED_REPOSITORY_URL = "https://github.com/waditu-tushare/skills.git"
PINNED_SOURCE_COMMIT = "5e12b31d09123e262c5fb38564e80c26d05cb830"
PINNED_INDEX_PATH = "tushare/references/数据接口.md"
PINNED_INDEX_SHA256 = "0df85aa1265a59b963fca6660eb3f58bec232aa2347c9c44d763d0d55a1b9cb2"

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
SCOPE_STATES = tuple(EXPECTED_SCOPE_COUNTS)

EXPECTED_V2_COUNTS = {
    "official_unique_api_names": 239,
    "mcp_unique_tool_names": 258,
    "union_unique_names": 268,
    "domestic_read_dataset": 222,
    "excluded_overseas": 41,
    "account_operation": 4,
    "helper": 1,
    "denominator_additions": 32,
    "mcp_absent_domestic_datasets": 9,
}
V2_DIMENSION_VALUES = {
    "product_scope": (
        "domestic_read_dataset",
        "excluded_overseas",
        "account_operation",
        "helper",
    ),
    "lifecycle": ("current", "retired"),
    "contract_state": (
        "official_cataloged",
        "review_required",
        "missing_official_contract",
    ),
    "mcp_visibility": ("visible", "absent"),
    "entitlement": ("unobserved",),
    "activation": ("paused", "not_applicable"),
}
EXPECTED_V2_DIMENSION_COUNTS = {
    "product_scope": {
        "domestic_read_dataset": 222,
        "excluded_overseas": 41,
        "account_operation": 4,
        "helper": 1,
    },
    "lifecycle": {"current": 261, "retired": 7},
    "contract_state": {
        "official_cataloged": 236,
        "review_required": 3,
        "missing_official_contract": 29,
    },
    "mcp_visibility": {"visible": 258, "absent": 10},
    "entitlement": {"unobserved": 268},
    "activation": {"paused": 222, "not_applicable": 46},
}
EXPECTED_V2_DATASET_DIMENSION_COUNTS = {
    "product_scope": {"domestic_read_dataset": 222},
    "lifecycle": {"current": 215, "retired": 7},
    "contract_state": {
        "official_cataloged": 195,
        "review_required": 3,
        "missing_official_contract": 24,
    },
    "mcp_visibility": {"visible": 213, "absent": 9},
    "entitlement": {"unobserved": 222},
    "activation": {"paused": 222},
}

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
_DOC_URL_PATTERN = re.compile(r"https://tushare\.pro/wctapi/documents/[1-9][0-9]*\.md")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]*")
_SEPARATOR_PATTERN = re.compile(r":?-{3,}:?")
_UTC_TIMESTAMP_PATTERN = re.compile(
    r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:"
    r"[0-5][0-9](?:\.[0-9]+)?Z"
)

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
    }
)
_SOURCE_KEYS = frozenset(
    {"repository_url", "pinned_commit", "index_path", "index_sha256"}
)
_DUPLICATE_RESOLUTION_KEYS = frozenset({"api_name", "canonical_doc_url", "reason"})
_CLASSIFICATION_KEYS = frozenset({"scope_state", "reason", "api_names"})
_CATALOG_ROOT_KEYS = frozenset(
    {
        "version",
        "catalog_id",
        "provider",
        "provenance",
        "scope",
        "counts",
        "scope_counts",
        "capabilities",
    }
)
_CATALOG_SCOPE_KEYS = frozenset({"scope_id", "scope_sha256"})
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

_MCP_SNAPSHOT_ROOT_KEYS = frozenset(
    {"version", "snapshot_id", "source", "entitlement_asserted", "tools"}
)
_MCP_SOURCE_KEYS = frozenset(
    {"metadata", "tool_prefix", "observed_at", "parameter_schema_hash"}
)
_MCP_HASH_SPEC_KEYS = frozenset({"algorithm", "canonicalization"})
_MCP_TOOL_KEYS = frozenset({"name", "parameter_schema_sha256"})
_SCOPE_V2_ROOT_KEYS = frozenset(
    {
        "version",
        "scope_id",
        "catalog_id",
        "provider",
        "sources",
        "expected_counts",
        "baseline",
        "dimensions",
    }
)
_SCOPE_V2_SOURCES_KEYS = frozenset({"official_catalog", "mcp_snapshot"})
_SCOPE_V2_OFFICIAL_SOURCE_KEYS = frozenset({"path", "catalog_id", "sha256"})
_SCOPE_V2_MCP_SOURCE_KEYS = frozenset({"path", "snapshot_id", "sha256"})
_SCOPE_V2_BASELINE_KEYS = frozenset(
    {
        "scope_id",
        "domestic_read_dataset_count",
        "denominator_additions",
        "mcp_absent_domestic_datasets",
    }
)
_SCOPE_V2_REVIEW_SET_KEYS = frozenset({"reason", "api_names"})
_SCOPE_V2_DIMENSION_GROUP_KEYS = frozenset({"value", "reason", "api_names"})
_CATALOG_V2_ROOT_KEYS = frozenset(
    {"version", "catalog_id", "provider", "provenance", "scope", "counts", "datasets"}
)
_CATALOG_V2_PROVENANCE_KEYS = frozenset({"official_catalog", "mcp_snapshot"})
_CATALOG_V2_SOURCE_KEYS = frozenset({"id", "sha256"})
_CATALOG_V2_SCOPE_KEYS = frozenset({"scope_id", "sha256"})
_CATALOG_V2_DATASET_KEYS = frozenset(
    {
        "name",
        "official_doc_url",
        "mcp_parameter_schema_sha256",
        "dimensions",
    }
)


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
    normalized = {key: _required_int(counts[key], f"{label}.{key}") for key in expected}
    if normalized != dict(expected):
        raise ValueError(f"{label} does not match the frozen expected counts")
    return normalized


def _sorted_unique_api_names(value: object, label: str) -> list[str]:
    names = [
        _validate_api_name(raw_name, f"{label}[{index}]")
        for index, raw_name in enumerate(_sequence(value, label))
    ]
    if names != sorted(names):
        raise ValueError(f"{label} must be sorted")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"{label} contains duplicate name(s): {', '.join(duplicates)}")
    return names


def validate_mcp_snapshot_document(document: object) -> dict[str, Any]:
    """Validate the metadata-only MCP snapshot without claiming entitlement."""

    root = _mapping(document, "MCP capability snapshot")
    _reject_unknown_keys(root, _MCP_SNAPSHOT_ROOT_KEYS, "MCP capability snapshot")
    if type(root["version"]) is not int or root["version"] != 1:
        raise ValueError("MCP capability snapshot.version must be integer 1")
    if root["snapshot_id"] != "tushare-mcp-capability-snapshot.v1":
        raise ValueError("MCP capability snapshot.snapshot_id is invalid")
    if root["entitlement_asserted"] is not False:
        raise ValueError("MCP capability snapshot cannot assert entitlement")

    source = _mapping(root["source"], "MCP capability snapshot.source")
    _reject_unknown_keys(source, _MCP_SOURCE_KEYS, "MCP capability snapshot.source")
    if source["metadata"] != "current_session.ALL_TOOLS":
        raise ValueError("MCP capability snapshot.source.metadata is invalid")
    if source["tool_prefix"] != "mcp__tushareMcp__":
        raise ValueError("MCP capability snapshot.source.tool_prefix is invalid")
    observed_at = _required_text(
        source["observed_at"], "MCP capability snapshot.source.observed_at"
    )
    if _UTC_TIMESTAMP_PATTERN.fullmatch(observed_at) is None:
        raise ValueError("MCP capability snapshot.source.observed_at must be UTC")
    hash_spec = _mapping(
        source["parameter_schema_hash"],
        "MCP capability snapshot.source.parameter_schema_hash",
    )
    _reject_unknown_keys(
        hash_spec,
        _MCP_HASH_SPEC_KEYS,
        "MCP capability snapshot.source.parameter_schema_hash",
    )
    if hash_spec != {
        "algorithm": "sha256",
        "canonicalization": ("typescript_args_without_line_comments_or_whitespace.v1"),
    }:
        raise ValueError("MCP capability snapshot schema hash specification is invalid")

    tools = _sequence(root["tools"], "MCP capability snapshot.tools")
    names: list[str] = []
    for index, raw_tool in enumerate(tools):
        label = f"MCP capability snapshot.tools[{index}]"
        tool = _mapping(raw_tool, label)
        _reject_unknown_keys(tool, _MCP_TOOL_KEYS, label)
        names.append(_validate_api_name(tool["name"], f"{label}.name"))
        _validate_hash(
            tool["parameter_schema_sha256"],
            f"{label}.parameter_schema_sha256",
        )
    if names != sorted(names):
        raise ValueError("MCP capability snapshot tool names must be sorted")
    if len(names) != len(set(names)):
        raise ValueError("MCP capability snapshot tool names must be unique")
    if len(names) != EXPECTED_V2_COUNTS["mcp_unique_tool_names"]:
        raise ValueError("MCP capability snapshot must contain exactly 258 tools")
    return root


def load_mcp_snapshot(
    path: Path = DEFAULT_MCP_SNAPSHOT_PATH,
) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_mcp_snapshot_document(payload)


def _validate_scope_v2_review_set(
    value: object,
    label: str,
    *,
    expected_count: int,
) -> set[str]:
    review_set = _mapping(value, label)
    _reject_unknown_keys(review_set, _SCOPE_V2_REVIEW_SET_KEYS, label)
    _required_text(review_set["reason"], f"{label}.reason")
    names = _sorted_unique_api_names(review_set["api_names"], f"{label}.api_names")
    if len(names) != expected_count:
        raise ValueError(f"{label} must contain exactly {expected_count} names")
    return set(names)


def _validate_scope_v2_dimensions(
    value: object,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    dimensions = _mapping(value, "scope v2.dimensions")
    _reject_unknown_keys(
        dimensions,
        frozenset(V2_DIMENSION_VALUES),
        "scope v2.dimensions",
    )
    indexes: dict[str, dict[str, str]] = {}
    universe: set[str] | None = None
    for dimension, expected_values in V2_DIMENSION_VALUES.items():
        groups = _sequence(dimensions[dimension], f"scope v2.dimensions.{dimension}")
        observed_values: list[str] = []
        index: dict[str, str] = {}
        counts: Counter[str] = Counter()
        for group_index, raw_group in enumerate(groups):
            label = f"scope v2.dimensions.{dimension}[{group_index}]"
            group = _mapping(raw_group, label)
            _reject_unknown_keys(group, _SCOPE_V2_DIMENSION_GROUP_KEYS, label)
            group_value = _required_text(group["value"], f"{label}.value")
            observed_values.append(group_value)
            _required_text(group["reason"], f"{label}.reason")
            names = _sorted_unique_api_names(group["api_names"], f"{label}.api_names")
            for name in names:
                if name in index:
                    raise ValueError(
                        f"scope v2 dimension {dimension} classifies {name} twice"
                    )
                index[name] = group_value
            counts[group_value] = len(names)
        if tuple(observed_values) != expected_values:
            raise ValueError(
                f"scope v2 dimension {dimension} values do not match the frozen order"
            )
        if dict(counts) != EXPECTED_V2_DIMENSION_COUNTS[dimension]:
            raise ValueError(
                f"scope v2 dimension {dimension} counts do not match the frozen review"
            )
        current_universe = set(index)
        if universe is None:
            universe = current_universe
        elif current_universe != universe:
            raise ValueError("scope v2 dimensions do not classify the same union")
        indexes[dimension] = index
    if universe is None or len(universe) != EXPECTED_V2_COUNTS["union_unique_names"]:
        raise ValueError("scope v2 dimensions must classify exactly 268 names")
    return indexes, universe


def validate_scope_v2_document(document: object) -> dict[str, Any]:
    """Validate exhaustive, dimension-separated scope-v2 review data."""

    root = _mapping(document, "scope v2")
    _reject_unknown_keys(root, _SCOPE_V2_ROOT_KEYS, "scope v2")
    if type(root["version"]) is not int or root["version"] != 2:
        raise ValueError("scope v2.version must be integer 2")
    if root["scope_id"] != "tushare-capability-scope.v2":
        raise ValueError("scope v2.scope_id is invalid")
    if root["catalog_id"] != "tushare-domestic-read-capabilities.v2":
        raise ValueError("scope v2.catalog_id is invalid")
    if root["provider"] != "tushare":
        raise ValueError("scope v2.provider must be tushare")

    sources = _mapping(root["sources"], "scope v2.sources")
    _reject_unknown_keys(sources, _SCOPE_V2_SOURCES_KEYS, "scope v2.sources")
    official_source = _mapping(
        sources["official_catalog"], "scope v2.sources.official_catalog"
    )
    _reject_unknown_keys(
        official_source,
        _SCOPE_V2_OFFICIAL_SOURCE_KEYS,
        "scope v2.sources.official_catalog",
    )
    if official_source["path"] != "config/tushare_capability_catalog.v1.yaml":
        raise ValueError("scope v2 official catalog path is invalid")
    if official_source["catalog_id"] != "tushare-official-capabilities.v1":
        raise ValueError("scope v2 official catalog id is invalid")
    _validate_hash(official_source["sha256"], "scope v2 official catalog sha256")
    mcp_source = _mapping(sources["mcp_snapshot"], "scope v2.sources.mcp_snapshot")
    _reject_unknown_keys(
        mcp_source,
        _SCOPE_V2_MCP_SOURCE_KEYS,
        "scope v2.sources.mcp_snapshot",
    )
    if mcp_source["path"] != "config/tushare_mcp_capability_snapshot.v1.yaml":
        raise ValueError("scope v2 MCP snapshot path is invalid")
    if mcp_source["snapshot_id"] != "tushare-mcp-capability-snapshot.v1":
        raise ValueError("scope v2 MCP snapshot id is invalid")
    _validate_hash(mcp_source["sha256"], "scope v2 MCP snapshot sha256")
    _validate_exact_counts(
        root["expected_counts"], EXPECTED_V2_COUNTS, "scope v2.expected_counts"
    )

    baseline = _mapping(root["baseline"], "scope v2.baseline")
    _reject_unknown_keys(baseline, _SCOPE_V2_BASELINE_KEYS, "scope v2.baseline")
    if baseline["scope_id"] != "tushare-capability-scope.v1":
        raise ValueError("scope v2 baseline.scope_id is invalid")
    if baseline["domestic_read_dataset_count"] != 190:
        raise ValueError("scope v2 baseline count must be 190")
    additions = _validate_scope_v2_review_set(
        baseline["denominator_additions"],
        "scope v2.baseline.denominator_additions",
        expected_count=EXPECTED_V2_COUNTS["denominator_additions"],
    )
    absent = _validate_scope_v2_review_set(
        baseline["mcp_absent_domestic_datasets"],
        "scope v2.baseline.mcp_absent_domestic_datasets",
        expected_count=EXPECTED_V2_COUNTS["mcp_absent_domestic_datasets"],
    )
    indexes, _ = _validate_scope_v2_dimensions(root["dimensions"])
    domestic = {
        name
        for name, state in indexes["product_scope"].items()
        if state == "domestic_read_dataset"
    }
    if not additions <= domestic:
        raise ValueError("scope v2 denominator additions must be domestic datasets")
    if not absent <= domestic:
        raise ValueError("scope v2 MCP-absent review set must be domestic datasets")
    if any(indexes["mcp_visibility"][name] != "absent" for name in absent):
        raise ValueError("scope v2 MCP-absent review set contradicts visibility")
    return root


def load_scope_v2_document(
    path: Path = DEFAULT_SCOPE_V2_PATH,
) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_scope_v2_document(payload)


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
        _validate_doc_url(resolution["canonical_doc_url"], f"{label}.canonical_doc_url")
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
        state = _required_text(classification["scope_state"], f"{label}.scope_state")
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
        raise ValueError(
            f"scope document is missing scope_state(s): {', '.join(missing)}"
        )
    normalized_scope_counts = {state: observed_counts[state] for state in SCOPE_STATES}
    if normalized_scope_counts != EXPECTED_SCOPE_COUNTS:
        raise ValueError("scope classification counts do not match the frozen review")

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
        raise ValueError(
            f"official api_name(s) lack classification: {', '.join(missing)}"
        )
    if extra:
        raise ValueError(f"scope classifies unknown api_name(s): {', '.join(extra)}")
    return result


def compile_capability_catalog(
    *,
    index_bytes: bytes,
    scope_document: object,
    scope_sha256: str,
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
        raise ValueError(
            "official unique api_name count does not match the frozen source"
        )
    resolved = resolve_official_rows(
        rows,
        _sequence(
            scope["duplicate_api_resolutions"],
            "scope.duplicate_api_resolutions",
        ),
    )
    classifications = _classification_index(scope, official_names)

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

    capabilities = _sequence(root["capabilities"], "capability catalog.capabilities")
    api_names: list[str] = []
    actual_scope_counts: Counter[str] = Counter()
    source_line_numbers: list[int] = []
    source_row_hashes: list[str] = []
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
            raise ValueError(
                f"{label} canonical fields must match exactly one source row"
            )
        if len(source_rows) == 1 and resolution != "single_official_index_row":
            raise ValueError(f"{label}.source_resolution is invalid for one source row")
        if len(source_rows) > 1 and resolution == "single_official_index_row":
            raise ValueError(
                f"{label}.source_resolution lacks reviewed duplicate reason"
            )

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
        raise ValueError(
            "capability catalog does not contain exactly 239 api_name values"
        )
    if {
        state: actual_scope_counts[state] for state in SCOPE_STATES
    } != EXPECTED_SCOPE_COUNTS:
        raise ValueError("capability rows do not match scope_counts")
    if len(source_line_numbers) != EXPECTED_OFFICIAL_COUNTS["official_source_rows"]:
        raise ValueError("catalog source row count does not match counts")
    if len(source_line_numbers) != len(set(source_line_numbers)):
        raise ValueError("catalog contains duplicate source line identity")
    if set(source_line_numbers) != set(range(9, 249)):
        raise ValueError("catalog source line identities do not cover the pinned table")
    if len(source_row_hashes) != len(set(source_row_hashes)):
        raise ValueError("catalog contains duplicate source row SHA-256 identity")
    return root


def load_capability_catalog(path: Path = DEFAULT_CATALOG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return validate_catalog_document(payload)


def _scope_v2_indexes(scope: Mapping[str, object]) -> dict[str, dict[str, str]]:
    indexes, _ = _validate_scope_v2_dimensions(scope["dimensions"])
    return indexes


def compile_capability_catalog_v2(
    *,
    official_catalog_document: object,
    official_catalog_sha256: str,
    mcp_snapshot_document: object,
    mcp_snapshot_sha256: str,
    scope_document: object,
    scope_sha256: str,
) -> dict[str, object]:
    """Merge the frozen official catalog and current metadata-only MCP snapshot."""

    official = validate_catalog_document(official_catalog_document)
    mcp = validate_mcp_snapshot_document(mcp_snapshot_document)
    scope = validate_scope_v2_document(scope_document)
    for value, label in (
        (official_catalog_sha256, "official_catalog_sha256"),
        (mcp_snapshot_sha256, "mcp_snapshot_sha256"),
        (scope_sha256, "scope_sha256"),
    ):
        _validate_hash(value, label)
    sources = _mapping(scope["sources"], "scope v2.sources")
    official_source = _mapping(
        sources["official_catalog"], "scope v2.sources.official_catalog"
    )
    mcp_source = _mapping(sources["mcp_snapshot"], "scope v2.sources.mcp_snapshot")
    if official_source["sha256"] != official_catalog_sha256:
        raise ValueError("scope v2 official catalog SHA-256 mismatch")
    if mcp_source["sha256"] != mcp_snapshot_sha256:
        raise ValueError("scope v2 MCP snapshot SHA-256 mismatch")
    if official_source["catalog_id"] != official["catalog_id"]:
        raise ValueError("scope v2 official catalog identity mismatch")
    if mcp_source["snapshot_id"] != mcp["snapshot_id"]:
        raise ValueError("scope v2 MCP snapshot identity mismatch")

    official_rows = _sequence(official["capabilities"], "official capabilities")
    official_by_name = {str(row["api_name"]): row for row in official_rows}
    mcp_rows = _sequence(mcp["tools"], "MCP tools")
    mcp_by_name = {str(row["name"]): row for row in mcp_rows}
    official_names = set(official_by_name)
    mcp_names = set(mcp_by_name)
    union_names = official_names | mcp_names
    if len(official_names) != EXPECTED_V2_COUNTS["official_unique_api_names"]:
        raise ValueError("scope v2 official source must contain 239 names")
    if len(mcp_names) != EXPECTED_V2_COUNTS["mcp_unique_tool_names"]:
        raise ValueError("scope v2 MCP source must contain 258 names")
    if len(union_names) != EXPECTED_V2_COUNTS["union_unique_names"]:
        raise ValueError("scope v2 source union must contain 268 names")

    indexes = _scope_v2_indexes(scope)
    if set(indexes["product_scope"]) != union_names:
        raise ValueError("scope v2 dimensions do not match the source union")
    product_scope = indexes["product_scope"]
    domestic = {
        name
        for name, state in product_scope.items()
        if state == "domestic_read_dataset"
    }
    excluded = {
        name for name, state in product_scope.items() if state == "excluded_overseas"
    }
    operations = {
        name for name, state in product_scope.items() if state == "account_operation"
    }
    helpers = {name for name, state in product_scope.items() if state == "helper"}

    official_by_old_state: dict[str, set[str]] = defaultdict(set)
    for name, row in official_by_name.items():
        official_by_old_state[str(row["scope_state"])].add(name)
    baseline = official_by_old_state["in_scope"]
    if len(baseline) != 190 or not baseline <= domestic:
        raise ValueError("scope v2 does not preserve the 190-name domestic baseline")
    if official_by_old_state["excluded"] != excluded & official_names:
        raise ValueError("scope v2 official overseas exclusion drift")
    if official_by_old_state["non_data_operation"] != operations:
        raise ValueError("scope v2 account-operation classification drift")
    if not official_by_old_state["retired"] <= domestic:
        raise ValueError("scope v2 must retain retired official datasets")
    if len(helpers) != 1 or helpers != official_by_old_state["unknown"] - domestic:
        raise ValueError("scope v2 helper classification drift")

    baseline_config = _mapping(scope["baseline"], "scope v2.baseline")
    additions_config = _mapping(
        baseline_config["denominator_additions"],
        "scope v2.baseline.denominator_additions",
    )
    additions = set(_sequence(additions_config["api_names"], "denominator additions"))
    if additions != domestic - baseline:
        raise ValueError("scope v2 denominator additions do not equal 222 minus 190")
    absent_config = _mapping(
        baseline_config["mcp_absent_domestic_datasets"],
        "scope v2.baseline.mcp_absent_domestic_datasets",
    )
    absent = set(_sequence(absent_config["api_names"], "MCP-absent domestic datasets"))
    if absent != domestic - mcp_names:
        raise ValueError("scope v2 MCP-absent domestic review set is stale")

    if {
        name
        for name, state in indexes["contract_state"].items()
        if state == "missing_official_contract"
    } != mcp_names - official_names:
        raise ValueError("scope v2 missing-contract classification drift")
    expected_review = official_by_old_state["unknown"] & domestic
    if {
        name
        for name, state in indexes["contract_state"].items()
        if state == "review_required"
    } != expected_review:
        raise ValueError("scope v2 contract-review classification drift")
    if {
        name for name, state in indexes["mcp_visibility"].items() if state == "visible"
    } != mcp_names:
        raise ValueError("scope v2 MCP visibility does not match the snapshot")
    if any(state != "unobserved" for state in indexes["entitlement"].values()):
        raise ValueError("scope v2 cannot infer entitlement from metadata")
    paused = {
        name for name, state in indexes["activation"].items() if state == "paused"
    }
    if paused != domestic:
        raise ValueError("scope v2 domestic datasets must all remain paused")
    retired = {
        name for name, state in indexes["lifecycle"].items() if state == "retired"
    }
    if not official_by_old_state["retired"] <= retired <= domestic:
        raise ValueError("scope v2 retired datasets must be discoverable and paused")

    datasets: list[dict[str, object]] = []
    for name in sorted(domestic):
        official_row = official_by_name.get(name)
        mcp_row = mcp_by_name.get(name)
        datasets.append(
            {
                "name": name,
                "official_doc_url": (
                    official_row["doc_url"] if official_row is not None else None
                ),
                "mcp_parameter_schema_sha256": (
                    mcp_row["parameter_schema_sha256"] if mcp_row is not None else None
                ),
                "dimensions": {
                    dimension: indexes[dimension][name]
                    for dimension in V2_DIMENSION_VALUES
                },
            }
        )
    catalog: dict[str, object] = {
        "version": 2,
        "catalog_id": scope["catalog_id"],
        "provider": "tushare",
        "provenance": {
            "official_catalog": {
                "id": official["catalog_id"],
                "sha256": official_catalog_sha256,
            },
            "mcp_snapshot": {
                "id": mcp["snapshot_id"],
                "sha256": mcp_snapshot_sha256,
            },
        },
        "scope": {"scope_id": scope["scope_id"], "sha256": scope_sha256},
        "counts": dict(EXPECTED_V2_COUNTS),
        "datasets": datasets,
    }
    return validate_catalog_v2_document(catalog)


def validate_catalog_v2_document(document: object) -> dict[str, Any]:
    """Validate the 222-item domestic read catalog with a closed schema."""

    root = _mapping(document, "capability catalog v2")
    _reject_unknown_keys(root, _CATALOG_V2_ROOT_KEYS, "capability catalog v2")
    if type(root["version"]) is not int or root["version"] != 2:
        raise ValueError("capability catalog v2.version must be integer 2")
    if root["catalog_id"] != "tushare-domestic-read-capabilities.v2":
        raise ValueError("capability catalog v2.catalog_id is invalid")
    if root["provider"] != "tushare":
        raise ValueError("capability catalog v2.provider must be tushare")

    provenance = _mapping(root["provenance"], "capability catalog v2.provenance")
    _reject_unknown_keys(
        provenance, _CATALOG_V2_PROVENANCE_KEYS, "capability catalog v2.provenance"
    )
    expected_source_ids = {
        "official_catalog": "tushare-official-capabilities.v1",
        "mcp_snapshot": "tushare-mcp-capability-snapshot.v1",
    }
    for source_name, expected_id in expected_source_ids.items():
        label = f"capability catalog v2.provenance.{source_name}"
        source = _mapping(provenance[source_name], label)
        _reject_unknown_keys(source, _CATALOG_V2_SOURCE_KEYS, label)
        if source["id"] != expected_id:
            raise ValueError(f"{label}.id is invalid")
        _validate_hash(source["sha256"], f"{label}.sha256")
    scope = _mapping(root["scope"], "capability catalog v2.scope")
    _reject_unknown_keys(scope, _CATALOG_V2_SCOPE_KEYS, "capability catalog v2.scope")
    if scope["scope_id"] != "tushare-capability-scope.v2":
        raise ValueError("capability catalog v2 scope identity is invalid")
    _validate_hash(scope["sha256"], "capability catalog v2.scope.sha256")
    _validate_exact_counts(
        root["counts"], EXPECTED_V2_COUNTS, "capability catalog v2.counts"
    )

    datasets = _sequence(root["datasets"], "capability catalog v2.datasets")
    names: list[str] = []
    dimension_counts: dict[str, Counter[str]] = {
        dimension: Counter() for dimension in V2_DIMENSION_VALUES
    }
    for index, raw_dataset in enumerate(datasets):
        label = f"capability catalog v2.datasets[{index}]"
        dataset = _mapping(raw_dataset, label)
        _reject_unknown_keys(dataset, _CATALOG_V2_DATASET_KEYS, label)
        name = _validate_api_name(dataset["name"], f"{label}.name")
        names.append(name)
        doc_url = dataset["official_doc_url"]
        if doc_url is not None:
            _validate_doc_url(doc_url, f"{label}.official_doc_url")
        mcp_hash = dataset["mcp_parameter_schema_sha256"]
        if mcp_hash is not None:
            _validate_hash(mcp_hash, f"{label}.mcp_parameter_schema_sha256")
        dimensions = _mapping(dataset["dimensions"], f"{label}.dimensions")
        _reject_unknown_keys(
            dimensions,
            frozenset(V2_DIMENSION_VALUES),
            f"{label}.dimensions",
        )
        for dimension, allowed_values in V2_DIMENSION_VALUES.items():
            value = _required_text(
                dimensions[dimension], f"{label}.dimensions.{dimension}"
            )
            if value not in allowed_values:
                raise ValueError(f"{label}.dimensions.{dimension} is invalid")
            dimension_counts[dimension][value] += 1
        if dimensions["product_scope"] != "domestic_read_dataset":
            raise ValueError(f"{label} is not a domestic read dataset")
        if dimensions["entitlement"] != "unobserved":
            raise ValueError(f"{label} improperly asserts entitlement")
        if dimensions["activation"] != "paused":
            raise ValueError(f"{label} must remain paused")
        if dimensions["contract_state"] == "missing_official_contract":
            if doc_url is not None:
                raise ValueError(f"{label} synthesizes an official doc URL")
        elif doc_url is None:
            raise ValueError(f"{label} lacks its frozen official doc URL")
        if dimensions["mcp_visibility"] == "visible":
            if mcp_hash is None:
                raise ValueError(f"{label} lacks its MCP parameter schema hash")
        elif mcp_hash is not None:
            raise ValueError(f"{label} has an MCP hash while marked absent")
    if names != sorted(names):
        raise ValueError("capability catalog v2 dataset names must be sorted")
    if len(names) != len(set(names)):
        raise ValueError("capability catalog v2 dataset names must be unique")
    if len(names) != EXPECTED_V2_COUNTS["domestic_read_dataset"]:
        raise ValueError("capability catalog v2 must contain exactly 222 datasets")
    normalized_counts = {
        dimension: dict(counts) for dimension, counts in dimension_counts.items()
    }
    if normalized_counts != EXPECTED_V2_DATASET_DIMENSION_COUNTS:
        raise ValueError("capability catalog v2 dataset dimension counts drifted")
    return root


def compile_v2_from_paths(
    *,
    official_catalog_path: Path = DEFAULT_CATALOG_PATH,
    mcp_snapshot_path: Path = DEFAULT_MCP_SNAPSHOT_PATH,
    scope_path: Path = DEFAULT_SCOPE_V2_PATH,
) -> dict[str, object]:
    """Compile v2 strictly from checked-in local snapshots and reviewed scope."""

    official_bytes = official_catalog_path.read_bytes()
    mcp_bytes = mcp_snapshot_path.read_bytes()
    scope_bytes = scope_path.read_bytes()
    try:
        official_payload = yaml.safe_load(official_bytes.decode("utf-8"))
        mcp_payload = yaml.safe_load(mcp_bytes.decode("utf-8"))
        scope_payload = yaml.safe_load(scope_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("capability v2 inputs must be valid UTF-8 YAML") from exc
    return compile_capability_catalog_v2(
        official_catalog_document=official_payload,
        official_catalog_sha256=_sha256_bytes(official_bytes),
        mcp_snapshot_document=mcp_payload,
        mcp_snapshot_sha256=_sha256_bytes(mcp_bytes),
        scope_document=scope_payload,
        scope_sha256=_sha256_bytes(scope_bytes),
    )


def render_catalog_v2(document: object) -> bytes:
    validated = validate_catalog_v2_document(document)
    rendered = yaml.safe_dump(
        validated,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1_000,
    )
    return rendered.encode("utf-8")


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
        "--v2",
        action="store_true",
        help="merge the checked-in official catalog and MCP metadata snapshot",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="v1-only local offline checkout at the frozen Git commit",
    )
    parser.add_argument("--scope", type=Path)
    parser.add_argument(
        "--official-catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="v2 pinned official catalog snapshot",
    )
    parser.add_argument(
        "--mcp-snapshot",
        type=Path,
        default=DEFAULT_MCP_SNAPSHOT_PATH,
        help="v2 metadata-only MCP capability snapshot",
    )
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
        if args.v2:
            catalog = compile_v2_from_paths(
                official_catalog_path=args.official_catalog,
                mcp_snapshot_path=args.mcp_snapshot,
                scope_path=args.scope or DEFAULT_SCOPE_V2_PATH,
            )
            rendered = render_catalog_v2(catalog)
            summary = (
                "official=239 mcp=258 union=268 catalog=222 "
                "excluded=41 operations=4 helper=1"
            )
        else:
            if args.source_root is None:
                raise ValueError("--source-root is required unless --v2 is selected")
            catalog = compile_from_paths(
                source_root=args.source_root,
                scope_path=args.scope or DEFAULT_SCOPE_PATH,
            )
            rendered = render_catalog(catalog)
            summary = "official=239 in_scope=190"
        if args.check:
            if args.catalog_path.read_bytes() != rendered:
                print("checked-in capability catalog is stale", file=sys.stderr)
                return 1
        elif args.output is not None:
            _atomic_write(args.output, rendered)
        else:
            sys.stdout.buffer.write(rendered)
        print(summary, file=sys.stderr)
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"capability catalog compilation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
