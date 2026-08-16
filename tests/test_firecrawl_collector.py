from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError

import pytest

import collectors.firecrawl.collector as firecrawl_collector
from collectors.firecrawl.collector import (
    FIRECRAWL_API_KEY_FILE_ENV,
    FirecrawlWebCollector,
    _RejectRedirects,
    _normalize_item,
)
from collectors.tushare.provider_native_ingest import (
    _provider_scan_budget,
    _resolved_request,
)
from dataset_registry import load_dataset_registry
from provider_ingest_contract import provider_ingest_config_hash
from provider_transport import provider_transport_profile
import tools.collect_provider_dataset as collect_tool


ROOT = Path(__file__).resolve().parents[1]
API_KEY = "fc-test-key-0123456789abcdef"

_SCRAPE_PARAMS = {
    "url": "https://www.cls.cn/telegraph",
    "extraction_schema": (
        '{"type":"object","properties":{"items":{"type":"array",'
        '"items":{"type":"object"}}},"required":["items"]}'
    ),
    "prompt": "extract objective news items",
    "max_age_ms": "900000",
    "timeout_ms": "30000",
    "window_start": "2026-08-16 09:00:00",
    "window_end": "2026-08-16 15:00:00",
}

_SCRAPE_PAYLOAD = {
    "success": True,
    "data": {
        "json": {
            "items": [
                {
                    "title": "央行开展500亿元逆回购操作",
                    "url": "https://www.cls.cn/detail/2110000",
                    "published_at": "2026-08-16 09:30:00",
                    "summary": None,
                    "provider_extra": "kept for schema drift",
                },
                {
                    "title": "隔夜要闻汇总",
                    "url": "https://www.cls.cn/detail/2110001#frag",
                    "published_at": "2026-08-15T17:30:00Z",
                    "summary": "页面摘要原文",
                },
            ]
        }
    },
}

_SEARCH_PAYLOAD = {
    "success": True,
    "data": {
        "news": [
            {
                "title": "证监会发布新政",
                "url": "https://example.cn/news/1",
                "date": "2026-08-16T08:00:00+08:00",
                "snippet": "快讯摘要",
                "position": 1,
            }
        ]
    },
}


def _key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int = 0o600) -> None:
    path = tmp_path / "firecrawl.key"
    path.write_text(API_KEY, encoding="utf-8")
    os.chmod(path, mode)
    monkeypatch.setenv(FIRECRAWL_API_KEY_FILE_ENV, str(path))


def _scrape_payload(text: str) -> dict[str, object]:
    return {"success": True, "data": {"json": {"items": [json.loads(text)]}}}


def test_firecrawl_transport_profile_is_bearer_key_file_and_serial() -> None:
    profile = provider_transport_profile("firecrawl")
    assert profile["credential_mode"] == "bearer_key_file"
    assert profile["endpoint"] == "https://api.firecrawl.dev/v2"
    assert profile["canonical_host"] == "api.firecrawl.dev"
    assert profile["redirects_allowed"] is False
    assert profile["max_concurrency"] == 1
    assert profile["transport_service"] == "firecrawl_web_scrape_api"
    sha256 = profile["profile_sha256"]
    assert isinstance(sha256, str) and len(sha256) == 64
    assert provider_transport_profile("firecrawl")["profile_sha256"] == sha256


def test_firecrawl_transport_rejects_redirects() -> None:
    assert any(
        isinstance(handler, _RejectRedirects)
        for handler in firecrawl_collector._OPENER.handlers  # noqa: SLF001
    )
    with pytest.raises(OSError, match="redirect rejected"):
        _RejectRedirects().redirect_request(
            None, None, 302, "Found", {}, "https://example.invalid/"
        )


def test_scrape_page_normalizes_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    captured: list[dict[str, object]] = []

    def fake_post(path: str, body: dict[str, object], *, api_key: str) -> object:
        assert api_key == API_KEY
        captured.append(body)
        return _SCRAPE_PAYLOAD

    monkeypatch.setattr(collector, "_post", fake_post)
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))

    assert outcome.state == "success"
    assert len(outcome.rows) == 2
    first, second = (dict(row) for row in outcome.rows)
    assert first["source"] == "https://www.cls.cn/telegraph"
    assert first["published_at"] == "2026-08-16T09:30:00+08:00"
    assert first["published_local"] == "2026-08-16 09:30:00"
    assert first["event_date"] == "20260816"
    assert first["summary"] is None
    assert first["provider_extra"] == "kept for schema drift"
    # UTC input crosses into the next Asia/Shanghai partition.
    assert second["published_at"] == "2026-08-16T01:30:00+08:00"
    assert second["event_date"] == "20260816"
    # The URL fragment is stripped by canonicalization.
    assert second["url"] == "https://www.cls.cn/detail/2110001"
    expected_uid = hashlib.sha256(
        "https://www.cls.cn/detail/2110000|"
        "央行开展500亿元逆回购操作|2026-08-16T09:30:00+08:00".encode("utf-8")
    ).hexdigest()
    assert first["content_uid"] == expected_uid
    # The request body carries the extraction contract and never the key.
    body = captured[0]
    assert body["url"] == "https://www.cls.cn/telegraph"
    assert body["maxAge"] == 900000
    assert body["timeout"] == 30000
    assert API_KEY not in json.dumps(body, ensure_ascii=False)
    formats = body["formats"]
    assert isinstance(formats, list) and formats[0]["type"] == "json"



def test_dotted_local_datetime_published_at_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    payload = {
        "success": True,
        "data": {
            "json": {
                "items": [
                    {
                        "title": "华测检测：2026年半年度净利润同比增长20.63%",
                        "url": "https://www.cls.cn/detail/300012",
                        "published_at": "2026.08.16 03:41:30",
                        "summary": None,
                    }
                ]
            }
        },
    }
    monkeypatch.setattr(collector, "_post", lambda *a, **k: payload)
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert outcome.state == "success"
    row = dict(outcome.rows[0])
    assert row["published_at"] == "2026-08-16T03:41:30+08:00"
    assert row["published_local"] == "2026-08-16 03:41:30"
    assert row["event_date"] == "20260816"


def test_unrecognized_published_at_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    payload = {
        "success": True,
        "data": {
            "json": {
                "items": [
                    {"title": "t", "url": "https://e.com/a", "published_at": "16/08/2026 03:41"}
                ]
            }
        },
    }
    monkeypatch.setattr(collector, "_post", lambda *a, **k: payload)
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert outcome.state == "failed"


def test_scrape_page_content_uid_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    monkeypatch.setattr(
        collector, "_post", lambda path, body, *, api_key: _SCRAPE_PAYLOAD
    )
    first = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    second = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert [row["content_uid"] for row in first.rows] == [
        row["content_uid"] for row in second.rows
    ]

    changed = json.loads(json.dumps(_SCRAPE_PAYLOAD))
    changed["data"]["json"]["items"][0]["title"] = "另一标题"
    monkeypatch.setattr(collector, "_post", lambda path, body, *, api_key: changed)
    third = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert third.rows[0]["content_uid"] != first.rows[0]["content_uid"]


def test_scrape_page_empty_extraction_is_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    monkeypatch.setattr(
        collector,
        "_post",
        lambda path, body, *, api_key: {
            "success": True,
            "data": {"json": {"items": []}},
        },
    )
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert outcome.state == "empty"
    assert outcome.rows == ()


def test_search_news_normalizes_news_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    captured: list[dict[str, object]] = []

    def fake_post(path: str, body: dict[str, object], *, api_key: str) -> object:
        captured.append(body)
        return _SEARCH_PAYLOAD

    monkeypatch.setattr(collector, "_post", fake_post)
    outcome = collector.collect_outcome(
        "search_news", {"query": "央行 降准", "limit": "10", "timeout_ms": "30000"}
    )
    assert outcome.state == "success"
    row = dict(outcome.rows[0])
    assert row["source"] == "firecrawl.search_news"
    assert row["summary"] == "快讯摘要"
    assert row["published_at"] == "2026-08-16T08:00:00+08:00"
    assert row["published_local"] == "2026-08-16 08:00:00"
    assert row["event_date"] == "20260816"
    body = captured[0]
    assert body["sources"] == [{"type": "news"}]
    assert body["limit"] == 10


def test_api_name_outside_allowlist_is_rejected() -> None:
    collector = FirecrawlWebCollector()
    for api_name in ("crawl", "map", "search_web", "interact"):
        outcome = collector.collect_outcome(api_name, {})
        assert outcome.state == "failed"
        assert outcome.error_code == "provider_error"
        assert outcome.rows == ()


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (402, "rate_limited"),
        (429, "rate_limited"),
        (401, "permission_denied"),
        (403, "permission_denied"),
        (500, "provider_error"),
        (503, "provider_error"),
        (404, "provider_error"),
    ),
)
def test_http_error_mapping(
    status: int,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()

    def raise_http(path: str, body: dict[str, object], *, api_key: str) -> object:
        raise HTTPError(
            "https://api.firecrawl.dev/v2/scrape", status, "rejected", {}, None
        )

    monkeypatch.setattr(collector, "_post", raise_http)
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert outcome.state == "failed"
    assert outcome.error_code == expected
    assert outcome.provider_code == status
    assert outcome.error_message is not None
    assert API_KEY not in outcome.error_message


def test_api_key_in_provider_payload_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    monkeypatch.setattr(
        collector,
        "_post",
        lambda path, body, *, api_key: _scrape_payload(
            json.dumps(
                {
                    "title": f"leaked {API_KEY}",
                    "url": "https://www.cls.cn/detail/9",
                    "published_at": "2026-08-16 09:30:00",
                },
                ensure_ascii=False,
            )
        ),
    )
    outcome = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert outcome.state == "failed"
    assert outcome.rows == ()
    assert API_KEY not in str(outcome.error_message)
    assert API_KEY not in str(outcome.provider_code)


def test_key_file_requires_owner_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = FirecrawlWebCollector()
    monkeypatch.setattr(
        collector, "_post", lambda path, body, *, api_key: _SCRAPE_PAYLOAD
    )
    monkeypatch.delenv(FIRECRAWL_API_KEY_FILE_ENV, raising=False)
    missing = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert missing.state == "failed"

    _key_file(tmp_path, monkeypatch, mode=0o644)
    loose = collector.collect_outcome("scrape_page", dict(_SCRAPE_PARAMS))
    assert loose.state == "failed"
    assert loose.rows == ()


def test_scrape_page_rejects_param_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _key_file(tmp_path, monkeypatch)
    collector = FirecrawlWebCollector()
    monkeypatch.setattr(
        collector, "_post", lambda path, body, *, api_key: _SCRAPE_PAYLOAD
    )
    extra = {**_SCRAPE_PARAMS, "formats": "rawHtml"}
    assert (
        collector.collect_outcome("scrape_page", extra).state == "failed"
    )
    bad_timeout = {**_SCRAPE_PARAMS, "timeout_ms": "999999"}
    assert (
        collector.collect_outcome("scrape_page", bad_timeout).state == "failed"
    )
    bad_schema = {**_SCRAPE_PARAMS, "extraction_schema": '["not-an-object"]'}
    assert (
        collector.collect_outcome("scrape_page", bad_schema).state == "failed"
    )


def test_http_announcement_url_is_preserved() -> None:
    collector = FirecrawlWebCollector()
    row = _normalize_item(
        {
            "title": "华测检测：2026年半年度报告",
            "url": "http://static.cninfo.com.cn/finalpage/2026-08-17/1225473313.PDF",
            "published_at": "2026-08-16 03:41:30",
            "summary": None,
        },
        source="https://www.cls.cn/telegraph",
        time_key="published_at",
        summary_key=None,
    )
    assert row["url"] == "http://static.cninfo.com.cn/finalpage/2026-08-17/1225473313.PDF"


def test_empty_url_item_keeps_source_title_identity() -> None:
    row = _normalize_item(
        {"title": "无链接快讯", "url": "", "published_at": "2026-08-16 03:41:30"},
        source="https://www.cls.cn/telegraph",
        time_key="published_at",
        summary_key=None,
    )
    assert row["url"] is None
    assert row["content_uid"] == hashlib.sha256(
        "https://www.cls.cn/telegraph|无链接快讯|2026-08-16T03:41:30+08:00".encode("utf-8")
    ).hexdigest()


def test_relative_or_junk_url_becomes_unlinkable() -> None:
    row = _normalize_item(
        {"title": "t", "url": "/relative/path", "published_at": "2026-08-16 03:41:30"},
        source="https://www.cls.cn/telegraph",
        time_key="published_at",
        summary_key=None,
    )
    assert row["url"] is None
    colon = _normalize_item(
        {"title": "t2", "url": ":", "published_at": "2026-08-16 03:41:30"},
        source="https://www.cls.cn/telegraph",
        time_key="published_at",
        summary_key=None,
    )
    assert colon["url"] is None


def test_registry_freezes_flash_contract_and_executor_identity() -> None:
    registry = load_dataset_registry()
    dataset = registry.resolve("cn.news.flash")
    binding = dataset.provider_bindings[0]
    assert binding.provider == FirecrawlWebCollector.provider
    assert binding.api_name == "scrape_page"
    assert binding.adapter_version == "firecrawl-web-extraction.v1"
    assert binding.activation_state == "active"
    assert binding.entitlement_state == "active"
    assert dataset.cadence_class == "event"
    assert dataset.schema_version == "1.0.0"
    assert dataset.point_in_time == "append_only"
    assert dataset.empty_data_policy == "allowed"
    assert dataset.primary_key == ("source", "published_local", "content_uid")
    assert dataset.as_of_field == "published_at"
    assert dataset.as_of_format == "rfc3339"
    assert dataset.partition_field == "event_date"
    assert binding.fanout is not None
    assert binding.fanout.strategy == "literal_values"
    assert binding.fanout.parameter == "url"
    assert binding.fanout.batch_size == 1
    assert binding.fanout.values == (
        "https://kuaixun.eastmoney.com/7_24.html",
        "https://www.cls.cn/telegraph",
    ) or set(binding.fanout.values) == {
        "https://www.cls.cn/telegraph",
        "https://kuaixun.eastmoney.com/7_24.html",
    }
    completeness = binding.response_completeness
    assert completeness is not None
    assert completeness.strategy == "windowed_unique_primary_key"
    assert completeness.date_field == "published_local"
    assert completeness.fanout_field == "source"

    # Executor compatibility without any provider call: scan budget, request
    # resolution, and the ingest config hash all derive from the contract.
    assert _provider_scan_budget(dataset, binding).max_nodes > 0
    window, params = _resolved_request(
        binding,
        {"start_time": "2026-08-16 09:00:00", "end_time": "2026-08-16 15:00:00"},
    )
    assert params["window_start"] == window["start_time"]
    assert params["extraction_schema"] == binding.request_template["extraction_schema"]
    assert provider_ingest_config_hash(dataset, binding)


def test_plan_mode_plans_the_active_flash_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = collect_tool.main(
        [
            "--db-path",
            str(tmp_path / "provider.sqlite"),
            "--dataset-id",
            "cn.news.flash",
            "--request-window-json",
            '{"start_time": "2026-08-16 09:00:00", "end_time": "2026-08-16 15:00:00"}',
        ]
    )
    assert exit_code == collect_tool.EXIT_SUCCESS
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["state"] == "planned"
    assert rendered["will_call_provider"] is False
