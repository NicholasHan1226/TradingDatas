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
    assert contract.note_tables == ()
    assert len(contract.doc_sha256) == 64


def test_parse_document_retains_post_input_note_tables() -> None:
    document = DOCUMENT.replace(
        b"close | float | Y | close",
        b"""close | float | Y | close

**\xe5\xb8\x82\xe5\x9c\xba\xe8\xaf\xb4\xe6\x98\x8e(market)**

\xe5\xb8\x82\xe5\x9c\xba\xe4\xbb\xa3\xe7\xa0\x81 | \xe8\xaf\xb4\xe6\x98\x8e
-- | --
SSE | \xe4\xb8\x8a\xe4\xba\xa4\xe6\x89\x80\xe6\x8c\x87\xe6\x95\xb0
SZSE | \xe6\xb7\xb1\xe4\xba\xa4\xe6\x89\x80\xe6\x8c\x87\xe6\x95\xb0

```
ignored | table
-- | --
NOPE | skip
```
""",
    )
    contract = parse_document(_capability(), document)
    assert contract.note_tables == (
        {
            "heading": "市场说明(market)",
            "headers": ["市场代码", "说明"],
            "rows": [
                {"市场代码": "SSE", "说明": "上交所指数"},
                {"市场代码": "SZSE", "说明": "深交所指数"},
            ],
        },
    )


def test_parse_document_rejects_missing_output_table() -> None:
    with pytest.raises(ContractSnapshotError, match="missing"):
        parse_document(_capability(), DOCUMENT.split(b"**\xe8\xbe\x93\xe5\x87\xba")[0])


def test_parse_document_keeps_documented_empty_all_input_without_stealing_output() -> (
    None
):
    document = """## 基金管理人

接口：fund_company
描述：获取公募基金管理人列表

**输入参数**

无，可提取全部

**输出参数**

名称 | 类型 | 默认显示 | 描述
--- | ---- | ---- | ----
name | str | Y | 基金公司名称
shortname | str | Y | 简称
""".encode()
    contract = parse_document(
        {
            **_capability(),
            "api_name": "fund_company",
            "doc_url": "https://tushare.pro/wctapi/documents/118.md",
        },
        document,
    )
    assert contract.input_fields == ()
    assert [field["name"] for field in contract.output_fields] == [
        "name",
        "shortname",
    ]
    assert contract.note_tables == ()


def test_parse_document_does_not_treat_limit_prose_as_empty_all() -> None:
    document = DOCUMENT.replace(
        "名称 | 类型 | 必选 | 描述\n--- | --- | --- | ---\nts_code | str | N | stock code\ntrade_date | str | N | date\n".encode(),
        "一次可提取全部数据\n".encode(),
    )
    with pytest.raises(ContractSnapshotError, match="input table is missing"):
        parse_document(_capability(), document)


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


def test_snapshot_only_refreshes_selected_api_into_existing_output(
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
                        **_capability(),
                        "api_name": "index_basic",
                        "doc_url": "https://tushare.pro/wctapi/documents/94.md",
                        "scope_state": "in_scope",
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
        workers=1,
    )
    refreshed = DOCUMENT.replace(
        b"close | float | Y | close",
        b"close | float | Y | close\n\n**market**\n\ncode | name\n-- | --\nSSE | shanghai\n",
    )
    monkeypatch.setattr(
        "tools.snapshot_tushare_contracts.fetch_document",
        lambda *_args, **_kwargs: refreshed,
    )
    snapshot_contracts(
        catalog,
        output,
        cache_dir=None,
        timeout_seconds=1,
        max_attempts=1,
        workers=1,
        only_api_names=frozenset({"index_basic"}),
    )
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    by_api = {item["api_name"]: item for item in payload["contracts"]}
    assert set(by_api) == {"daily", "index_basic"}
    assert "note_tables" not in by_api["daily"]
    assert by_api["index_basic"]["note_tables"] == [
        {
            "heading": "market",
            "headers": ["code", "name"],
            "rows": [{"code": "SSE", "name": "shanghai"}],
        }
    ]


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
    index_basic = next(
        contract for contract in contracts if contract["api_name"] == "index_basic"
    )
    assert index_basic["doc_url"] == "https://tushare.pro/wctapi/documents/94.md"
    assert (
        index_basic["doc_sha256"]
        == "d61a1551efc5d119b5588c9cc875eb6318b4c7c2a295851deffa1c81f19773e1"
    )
    assert [row["市场代码"] for row in index_basic["note_tables"][0]["rows"]] == [
        "MSCI",
        "CSI",
        "SSE",
        "SZSE",
        "CICC",
        "SW",
        "OTH",
    ]
    stock_hsgt = next(
        contract for contract in contracts if contract["api_name"] == "stock_hsgt"
    )
    assert stock_hsgt["doc_url"] == "https://tushare.pro/wctapi/documents/398.md"
    assert (
        stock_hsgt["doc_sha256"]
        == "c49e3313931b2b6594fbbb09868997f6044f23e7d3b3e5012f276bb93d9efdba"
    )
    assert [row["类型"] for row in stock_hsgt["note_tables"][0]["rows"]] == [
        "HK_SZ",
        "SZ_HK",
        "HK_SH",
        "SH_HK",
    ]
    fund_company = next(
        contract for contract in contracts if contract["api_name"] == "fund_company"
    )
    stock_company = next(
        contract for contract in contracts if contract["api_name"] == "stock_company"
    )
    assert fund_company["input_fields"] == []
    assert "note_tables" not in fund_company
    assert [field["name"] for field in stock_company["input_fields"]] == [
        "ts_code",
        "exchange",
    ]
    assert all(field["required"] == "" for field in stock_company["input_fields"])
    assert "note_tables" not in stock_company
