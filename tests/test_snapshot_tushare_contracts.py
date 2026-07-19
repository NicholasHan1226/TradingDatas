from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.snapshot_tushare_contracts import (
    ContractSnapshotError,
    parse_document,
    snapshot_contracts,
)


DOCUMENT = b"""## A-share daily\n\ninterface notes\nData description\n\n**\xe8\xbe\x93\xe5\x85\xa5\xe5\x8f\x82\xe6\x95\xb0**\n\n\xe5\x90\x8d\xe7\xa7\xb0 | \xe7\xb1\xbb\xe5\x9e\x8b | \xe5\xbf\x85\xe9\x80\x89 | \xe6\x8f\x8f\xe8\xbf\xb0\n--- | --- | --- | ---\nts_code | str | N | stock code\ntrade_date | str | N | date\n\n**\xe8\xbe\x93\xe5\x87\xba\xe5\x8f\x82\xe6\x95\xb0**\n\n\xe5\x90\x8d\xe7\xa7\xb0 | \xe7\xb1\xbb\xe5\x9e\x8b | \xe9\xbb\x98\xe8\xae\xa4\xe6\x98\xbe\xe7\xa4\xba | \xe6\x8f\x8f\xe8\xbf\xb0\n--- | --- | --- | ---\nts_code | str | Y | stock code\ntrade_date | str | Y | date\nclose | float | Y | close\n"""


def _capability() -> dict[str, str]:
    return {
        "api_name": "daily",
        "doc_url": "https://tushare.pro/wctapi/documents/27.md",
        "title": "A-share daily",
        "category": "stock",
        "description": "daily prices",
    }


def test_parse_document_freezes_input_and_output_contract() -> None:
    contract = parse_document(_capability(), DOCUMENT)
    assert contract.api_name == "daily"
    assert [field["name"] for field in contract.input_fields] == [
        "ts_code",
        "trade_date",
    ]
    assert [field["name"] for field in contract.output_fields] == [
        "ts_code",
        "trade_date",
        "close",
    ]
    assert contract.output_fields[-1]["declared_type"] == "float"
    assert len(contract.doc_sha256) == 64


def test_parse_document_rejects_missing_output_table() -> None:
    with pytest.raises(ContractSnapshotError, match="missing"):
        parse_document(_capability(), DOCUMENT.split(b"**\xe8\xbe\x93\xe5\x87\xba")[0])


def test_parse_document_ignores_inline_output_words_and_preserves_blank_cells() -> None:
    document = (
        DOCUMENT.replace(
            b"interface notes",
            "描述：输出参数 only appears inline".encode(),
        )
        .replace(
            "**输入参数**".encode(),
            "**daily输入参数**".encode(),
        )
        .replace(
            b"close | float | Y | close",
            b"close | float | close\namount | float | Y | ",
        )
    )
    contract = parse_document(_capability(), document)
    assert contract.output_fields[-2] == {
        "name": "close",
        "declared_type": "float",
        "description": "close",
        "default_display": "",
    }
    assert contract.output_fields[-1]["description"] == ""


def test_snapshot_uses_only_in_scope_and_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = tmp_path / "catalog.yaml"
    output = tmp_path / "contracts.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "catalog_id": "catalog.v1",
                "provenance": {"pinned_commit": "abc123"},
                "capabilities": [
                    {**_capability(), "scope_state": "in_scope"},
                    {
                        "api_name": "hk_daily",
                        "doc_url": "https://tushare.pro/wctapi/documents/191.md",
                        "scope_state": "excluded",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tools.snapshot_tushare_contracts.fetch_document",
        lambda *_args, **_kwargs: DOCUMENT,
    )
    snapshot_contracts(
        catalog,
        output,
        cache_dir=None,
        timeout_seconds=1,
        max_attempts=1,
        workers=2,
    )
    first = output.read_bytes()
    snapshot_contracts(
        catalog,
        output,
        cache_dir=None,
        timeout_seconds=1,
        max_attempts=1,
        workers=2,
    )
    assert output.read_bytes() == first
    payload = yaml.safe_load(first)
    assert payload["counts"] == {"in_scope_contracts": 1, "parse_errors": 0}
    assert [item["api_name"] for item in payload["contracts"]] == ["daily"]


def test_checked_in_contracts_expose_honest_probe_readiness() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = yaml.safe_load(
        (root / "config" / "tushare_document_contracts.v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    contracts = payload["contracts"]
    required_names = {
        contract["api_name"]: tuple(
            field["name"]
            for field in contract["input_fields"]
            if field["required"] == "Y"
        )
        for contract in contracts
    }

    assert len(contracts) == 190
    assert sum(not names for names in required_names.values()) == 144
    assert sum(bool(names) for names in required_names.values()) == 46
    assert required_names["news"] == ("start_date", "end_date", "src")
