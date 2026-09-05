#!/usr/bin/env python3
"""Freeze official Tushare interface documents into one deterministic contract bundle."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


_ALLOWED_HOST = "tushare.pro"
_ALLOWED_PATH = re.compile(r"/wctapi/documents/[0-9]+\.md\Z")
_SAFE_API_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_TABLE_SEPARATOR = re.compile(r":?-{3,}:?\Z")
_NOTE_TABLE_SEPARATOR = re.compile(r":?-{2,}:?\Z")
_MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
_DOCUMENTED_EMPTY_ALL = frozenset({"无，可提取全部"})


class ContractSnapshotError(RuntimeError):
    """The official document set cannot be frozen without guessing."""


@dataclass(frozen=True)
class DocumentContract:
    api_name: str
    doc_url: str
    doc_sha256: str
    title: str
    category: str
    description: str
    notes: tuple[str, ...]
    input_fields: tuple[Mapping[str, str], ...]
    output_fields: tuple[Mapping[str, str], ...]
    note_tables: tuple[Mapping[str, Any], ...] = ()


def _canonical_heading(line: str) -> str:
    return re.sub(r"[\s#*_:`：-]+", "", line).casefold()


def _table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(
    line: str, expected_columns: int, *, pattern: re.Pattern[str] = _TABLE_SEPARATOR
) -> bool:
    cells = _table_cells(line)
    return len(cells) == expected_columns and all(
        pattern.fullmatch(cell.replace(" ", "")) is not None for cell in cells
    )


def _visible_heading(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("```") or not stripped:
        return None
    if stripped.startswith("#"):
        text = stripped.lstrip("#").strip()
        return text or None
    if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
        return stripped[2:-2].strip() or None
    return None


def _find_section(lines: list[str], label: str) -> int:
    canonical = label.casefold()
    for index, line in enumerate(lines):
        stripped = line.strip()
        is_heading = stripped.startswith("#") or stripped.startswith("**")
        if is_heading and _canonical_heading(line).endswith(canonical):
            return index
    raise ContractSnapshotError(f"document is missing {label}")


def _find_field_table_header(
    lines: list[str],
    section_index: int,
    *,
    section: str,
    stop_index: int | None = None,
) -> tuple[int, list[str]]:
    end_index = len(lines) if stop_index is None else stop_index
    end_index = min(end_index, section_index + 40, len(lines))
    for index in range(section_index + 1, end_index):
        if _visible_heading(lines[index]) is not None:
            break
        if "|" not in lines[index]:
            continue
        candidate = _table_cells(lines[index])
        if len(candidate) < 3 or index + 1 >= end_index:
            continue
        if _is_separator_row(lines[index + 1], len(candidate)):
            return index, candidate
    raise ContractSnapshotError(f"{section} table is missing")


def _input_section_is_documented_empty_all(
    lines: list[str], *, start_index: int, stop_index: int
) -> bool:
    prose: list[str] = []
    for line in lines[start_index + 1 : stop_index]:
        if _visible_heading(line) is not None:
            break
        stripped = line.strip()
        if not stripped:
            continue
        if "|" in stripped:
            return False
        prose.append(stripped)
    return len(prose) == 1 and prose[0] in _DOCUMENTED_EMPTY_ALL


def _parse_generic_table(
    lines: list[str], header_index: int
) -> tuple[list[str], tuple[Mapping[str, str], ...], int] | None:
    if header_index + 1 >= len(lines) or "|" not in lines[header_index]:
        return None
    headers = _table_cells(lines[header_index])
    if len(headers) < 2 or any(not header for header in headers):
        return None
    if len(headers) != len(set(headers)):
        return None
    if not _is_separator_row(
        lines[header_index + 1], len(headers), pattern=_NOTE_TABLE_SEPARATOR
    ):
        return None
    rows: list[Mapping[str, str]] = []
    end_index = header_index + 2
    for offset, line in enumerate(lines[header_index + 2 :], start=header_index + 2):
        stripped = line.strip()
        if not stripped:
            if rows:
                end_index = offset
                break
            continue
        if stripped.startswith("```") or _visible_heading(line) is not None:
            if rows:
                end_index = offset
                break
            continue
        if "|" not in line:
            if rows:
                end_index = offset
                break
            continue
        cells = _table_cells(line)
        if _is_separator_row(line, len(cells), pattern=_NOTE_TABLE_SEPARATOR):
            if rows:
                end_index = offset
                break
            continue
        if len(cells) < len(headers):
            raise ContractSnapshotError("note table row has too few cells")
        if len(cells) > len(headers):
            cells = cells[: len(headers) - 1] + [" | ".join(cells[len(headers) - 1 :])]
        rows.append(dict(zip(headers, cells)))
        end_index = offset + 1
    if not rows:
        return None
    return headers, tuple(rows), end_index


def _collect_note_tables(
    lines: list[str],
    *,
    start_index: int,
    skip_header_indexes: set[int],
) -> tuple[Mapping[str, Any], ...]:
    tables: list[Mapping[str, Any]] = []
    in_fence = False
    heading = ""
    index = start_index
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if in_fence:
            index += 1
            continue
        visible = _visible_heading(lines[index])
        if visible is not None:
            heading = visible
            index += 1
            continue
        if index in skip_header_indexes:
            index += 1
            continue
        parsed = _parse_generic_table(lines, index)
        if parsed is None:
            index += 1
            continue
        headers, rows, end_index = parsed
        tables.append(
            {
                "heading": heading,
                "headers": list(headers),
                "rows": [dict(row) for row in rows],
            }
        )
        index = end_index
    return tuple(tables)


def _parse_table(
    lines: list[str],
    section_index: int,
    *,
    section: str,
    stop_index: int | None = None,
) -> tuple[tuple[Mapping[str, str], ...], int]:
    header_index, headers = _find_field_table_header(
        lines, section_index, section=section, stop_index=stop_index
    )

    normalized_headers = [_canonical_heading(header) for header in headers]
    required_names = {"名称", "类型", "描述"}
    if not required_names.issubset(set(normalized_headers)):
        raise ContractSnapshotError(f"{section} table has unsupported headers")

    rows: list[Mapping[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.strip():
            if rows:
                break
            continue
        if "|" not in line or line.lstrip().startswith(("#", "**")):
            if rows:
                break
            continue
        cells = _table_cells(line)
        if len(cells) == len(headers) - 1:
            optional_header = "必选" if section == "input" else "默认显示"
            if line.strip().endswith("|"):
                cells.append("")
            elif optional_header in normalized_headers:
                cells.insert(normalized_headers.index(optional_header), "")
        if len(cells) < len(headers):
            raise ContractSnapshotError(f"{section} table row has too few cells")
        if len(cells) > len(headers):
            cells = cells[: len(headers) - 1] + [" | ".join(cells[len(headers) - 1 :])]
        if len(cells) != len(normalized_headers):
            raise ValueError(
                f"{section} table row has {len(cells)} cells; "
                f"expected {len(normalized_headers)}"
            )
        raw = dict(zip(normalized_headers, cells))
        name = raw.get("名称", "").strip()
        declared_type = raw.get("类型", "").strip()
        description = raw.get("描述", "").strip()
        if not name or not declared_type:
            raise ContractSnapshotError(f"{section} table has blank name or type")
        field: dict[str, str] = {
            "name": name,
            "declared_type": declared_type,
            "description": description,
        }
        if section == "input":
            field["required"] = raw.get("必选", "").strip()
        else:
            field["default_display"] = raw.get("默认显示", "").strip()
        rows.append(field)
    if not rows:
        raise ContractSnapshotError(f"{section} table has no rows")
    return tuple(rows), header_index


def parse_document(capability: Mapping[str, Any], body: bytes) -> DocumentContract:
    """Parse one pinned official Markdown document without inferring missing fields."""

    api_name = capability.get("api_name")
    doc_url = capability.get("doc_url")
    if not isinstance(api_name, str) or _SAFE_API_NAME.fullmatch(api_name) is None:
        raise ContractSnapshotError("capability has invalid api_name")
    if not isinstance(doc_url, str):
        raise ContractSnapshotError(f"{api_name}: capability has invalid doc_url")
    if len(body) > _MAX_DOCUMENT_BYTES:
        raise ContractSnapshotError(f"{api_name}: document exceeds size limit")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractSnapshotError(f"{api_name}: document is not UTF-8") from exc
    lines = text.splitlines()
    input_index = _find_section(lines, "输入参数")
    output_index = _find_section(lines, "输出参数")
    if output_index <= input_index:
        raise ContractSnapshotError(
            f"{api_name}: output section precedes input section"
        )

    notes = tuple(
        line.strip()
        for line in lines[:input_index]
        if line.strip().startswith(
            ("接口", "数据说明", "调取说明", "描述", "更新时间", "更新频率")
        )
    )
    skip_header_indexes: set[int] = set()
    if _input_section_is_documented_empty_all(
        lines, start_index=input_index, stop_index=output_index
    ):
        input_fields = ()
    else:
        input_fields, input_header_index = _parse_table(
            lines, input_index, section="input", stop_index=output_index
        )
        skip_header_indexes.add(input_header_index)
    output_fields, output_header_index = _parse_table(
        lines, output_index, section="output"
    )
    skip_header_indexes.add(output_header_index)
    return DocumentContract(
        api_name=api_name,
        doc_url=doc_url,
        doc_sha256=hashlib.sha256(body).hexdigest(),
        title=str(capability.get("title") or "").strip(),
        category=str(capability.get("category") or "").strip(),
        description=str(capability.get("description") or "").strip(),
        notes=notes,
        input_fields=input_fields,
        output_fields=output_fields,
        note_tables=_collect_note_tables(
            lines,
            start_index=input_index + 1,
            skip_header_indexes=skip_header_indexes,
        ),
    )


def _validate_doc_url(url: str) -> None:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or _ALLOWED_PATH.fullmatch(parsed.path) is None
    ):
        raise ContractSnapshotError(f"untrusted official document URL: {url}")


def fetch_document(url: str, *, timeout_seconds: float, max_attempts: int) -> bytes:
    """Fetch one bounded official document with retry only for transient failures."""

    _validate_doc_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TradingDatas-contract-snapshot/1.0"},
        method="GET",
    )
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(_MAX_DOCUMENT_BYTES + 1)
                if len(body) > _MAX_DOCUMENT_BYTES:
                    raise ContractSnapshotError("official document exceeds size limit")
                return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 429 and not 500 <= exc.code <= 599:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 4))
    raise ContractSnapshotError(f"failed to fetch {url}: {last_error}")


def _load_catalog(path: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("capabilities"), list):
        raise ContractSnapshotError("capability catalog is invalid")
    capabilities = [
        item
        for item in raw["capabilities"]
        if isinstance(item, dict) and item.get("scope_state") == "in_scope"
    ]
    names = [item.get("api_name") for item in capabilities]
    if len(names) != len(set(names)):
        raise ContractSnapshotError("in-scope capability names are not unique")
    return raw, capabilities


def _contract_payload(contract: DocumentContract) -> dict[str, Any]:
    payload = {
        "api_name": contract.api_name,
        "doc_url": contract.doc_url,
        "doc_sha256": contract.doc_sha256,
        "title": contract.title,
        "category": contract.category,
        "description": contract.description,
        "notes": list(contract.notes),
        "input_fields": [dict(field) for field in contract.input_fields],
        "output_fields": [dict(field) for field in contract.output_fields],
    }
    if contract.note_tables:
        payload["note_tables"] = [dict(table) for table in contract.note_tables]
    return payload


def snapshot_contracts(
    catalog_path: Path,
    output_path: Path,
    *,
    cache_dir: Path | None,
    timeout_seconds: float,
    max_attempts: int,
    workers: int = 8,
    only_api_names: frozenset[str] | None = None,
) -> None:
    catalog, capabilities = _load_catalog(catalog_path)
    existing_by_api: dict[str, dict[str, Any]] | None = None
    if only_api_names:
        available = {str(item["api_name"]) for item in capabilities}
        missing = sorted(only_api_names - available)
        if missing:
            raise ContractSnapshotError(
                "unknown --only API(s): " + ",".join(missing)
            )
        if not output_path.is_file():
            raise ContractSnapshotError(
                "refreshing selected APIs requires an existing snapshot"
            )
        existing = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or not isinstance(
            existing.get("contracts"), list
        ):
            raise ContractSnapshotError("existing snapshot is invalid")
        existing_by_api = {}
        for item in existing["contracts"]:
            if isinstance(item, dict) and isinstance(item.get("api_name"), str):
                existing_by_api[item["api_name"]] = item
        capabilities = [
            item
            for item in capabilities
            if str(item["api_name"]) in only_api_names
        ]
    contracts: list[DocumentContract] = []
    errors: list[str] = []
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    ordered_capabilities = sorted(capabilities, key=lambda item: str(item["api_name"]))

    def load_contract(capability: Mapping[str, Any]) -> DocumentContract:
        api_name = str(capability["api_name"])
        cache_path = None if cache_dir is None else cache_dir / f"{api_name}.md"
        if cache_path is not None and cache_path.is_file():
            body = cache_path.read_bytes()
        else:
            body = fetch_document(
                str(capability["doc_url"]),
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )
            if cache_path is not None:
                cache_path.write_bytes(body)
        return parse_document(capability, body)

    if not 1 <= workers <= 16:
        raise ContractSnapshotError("workers must be between 1 and 16")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(load_contract, capability): str(capability["api_name"])
            for capability in ordered_capabilities
        }
        for future in as_completed(pending):
            api_name = pending[future]
            try:
                contracts.append(future.result())
            except ContractSnapshotError as exc:
                errors.append(f"{api_name}: {exc}")
    if errors:
        raise ContractSnapshotError("contract snapshot failed:\n" + "\n".join(errors))

    refreshed = {
        contract.api_name: _contract_payload(contract) for contract in contracts
    }
    if existing_by_api is not None:
        merged = dict(existing_by_api)
        merged.update(refreshed)
        contract_payloads = [
            merged[api_name] for api_name in sorted(merged)
        ]
    else:
        contract_payloads = [
            refreshed[api_name] for api_name in sorted(refreshed)
        ]

    payload = {
        "version": 1,
        "snapshot_id": "tushare-official-document-contracts.v1",
        "provider": "tushare",
        "source_catalog_id": catalog.get("catalog_id"),
        "source_catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "pinned_commit": (catalog.get("provenance") or {}).get("pinned_commit"),
        "counts": {"in_scope_contracts": len(contract_payloads), "parse_errors": 0},
        "contracts": contract_payloads,
    }
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=_positive_int, default=3)
    parser.add_argument("--workers", type=_positive_int, default=8)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="API",
        help="Refresh only these in-scope APIs and merge them into the existing snapshot.",
    )
    args = parser.parse_args(argv)
    if not 0 < args.timeout_seconds <= 120:
        parser.error("--timeout-seconds must be in (0, 120]")
    snapshot_contracts(
        args.catalog,
        args.output,
        cache_dir=args.cache_dir,
        timeout_seconds=args.timeout_seconds,
        max_attempts=args.max_attempts,
        workers=args.workers,
        only_api_names=frozenset(args.only) if args.only else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
