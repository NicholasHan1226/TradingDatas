from __future__ import annotations

from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import sqlite3
from types import MappingProxyType

import pytest

import collectors.firecrawl.collector as fc
from dataset_registry import DatasetRegistry, load_dataset_registry
from collectors.tushare.provider_native_ingest import collect_provider_native_dataset
from query_contract import QueryAccessContext
from query_cursor import SignedCursorCodec
from tests.test_provider_dataset_rows import _db
from storage.provider_dataset_rows import (
    ProviderNativeAdmissionError,
    _prepare_rows,
    _quality_issues,
)
from provider_ingest_contract import provider_ingest_config_hash
from query_contract import QueryExecutionOptions, QueryRequest
import query_service as query_module
from storage.receipt_projection import DatasetRuntimeEvidence, DatasetRuntimeProjection
from tests.test_firecrawl_collector import API_KEY, _SCRAPE_PARAMS, _key_file


MODE = {"publication_provenance_mode": "raw_item_v1"}
NEW_FIELDS = {"provider_published_at", "raw_item_json", "publication_precision"}


def _item(published_at="Aug. 14, 2026"):
    return {
        "title": "A source headline",
        "url": "https://www.sec.gov/item#original",
        "published_at": published_at,
    }


def _collect(item, monkeypatch, tmp_path, *, api_name="scrape_page_global", mode=MODE):
    _key_file(tmp_path, monkeypatch)
    collector = fc.FirecrawlWebCollector()
    calls = []

    def post(path, body, *, api_key):
        calls.append((path, body))
        return {"success": True, "data": {"json": {"items": [item]}}}

    monkeypatch.setattr(collector, "_post", post)
    return collector.collect_outcome(api_name, {**_SCRAPE_PARAMS, **mode}), calls


@pytest.mark.parametrize(
    "source_time,precision",
    [
        ("Aug. 14, 2026", "date"),
        ("8/13/2026", "date"),
        ("2026-08-14", "date"),
        ("2026.08.14", "date"),
        ("20260814", "date"),
        ("2026-08-14T00:00:00-04:00", "datetime"),
        ("2026.08.14 00:00:00", "datetime"),
        ("2026-08-14T09:30:00Z", "datetime"),
        ("08:09", "time"),
        ("08:09:28", "time"),
    ],
)
def test_global_provenance_classifies_source_not_normalized_midnight(
    source_time, precision, monkeypatch, tmp_path
):
    item = _item(source_time)
    original = deepcopy(item)
    result, calls = _collect(item, monkeypatch, tmp_path)
    assert result.state == "success"
    row = dict(result.rows[0])
    assert row["provider_published_at"] == source_time
    assert row["publication_precision"] == precision
    assert json.loads(row["raw_item_json"]) == original == item
    assert len(calls) == 1 and "publication_provenance_mode" not in calls[0][1]


def test_raw_item_precedes_all_normalization_and_reserved_field_overwrites(
    monkeypatch, tmp_path
):
    item = _item(" Aug. 14, 2026 ")
    item.update(
        url=":",
        source="original-source",
        content_uid="original-id",
        published_local="original-local",
        event_date="original-date",
        provider_published_at={"original": True},
        publication_precision="original-precision",
        raw_item_json="original-raw-key",
        unknown={"nested": [None, True, 'quoted " 中文']},
    )
    original = deepcopy(item)
    result, _ = _collect(item, monkeypatch, tmp_path)
    assert result.state == "success"
    row = dict(result.rows[0])
    assert row["url"] is None
    assert row["provider_published_at"] == " Aug. 14, 2026 "
    assert json.loads(row["raw_item_json"]) == original == item
    assert row["publication_precision"] == "date"
    assert tuple(row["unknown"]["nested"]) == tuple(original["unknown"]["nested"])


@pytest.mark.parametrize("bad", [None, "", "not-a-date", "2026-02-30", 123])
def test_missing_or_invalid_time_does_not_acquire_capture_time(
    bad, monkeypatch, tmp_path
):
    result, _ = _collect(_item(bad), monkeypatch, tmp_path)
    assert result.state == "failed" and not result.rows


@pytest.mark.parametrize(
    "api_name,mode",
    [
        ("scrape_page", MODE),
        ("search_news", MODE),
        ("scrape_page_global", {"publication_provenance_mode": None}),
        ("scrape_page_global", {"publication_provenance_mode": "unknown-v9"}),
    ],
)
def test_mode_is_explicit_global_only_and_invalid_mode_never_reaches_provider(
    api_name, mode, monkeypatch, tmp_path
):
    result, calls = _collect(
        _item(), monkeypatch, tmp_path, api_name=api_name, mode=mode
    )
    assert result.state == "failed" and not calls


def test_legacy_cn_and_global_default_outputs_are_unchanged(monkeypatch, tmp_path):
    for api_name, zone in [
        ("scrape_page", fc._LOCAL_TIMEZONE),
        ("scrape_page_global", fc._GLOBAL_TIMEZONE),
    ]:
        item = _item()
        expected = fc._normalize_item(
            item,
            source=_SCRAPE_PARAMS["url"],
            time_key="published_at",
            summary_key=None,
            timezone=zone,
        )
        result, _ = _collect(item, monkeypatch, tmp_path, api_name=api_name, mode={})
        assert result.state == "success" and dict(result.rows[0]) == expected
        assert not NEW_FIELDS.intersection(result.rows[0])


def test_provenance_does_not_change_legacy_identity_or_normalized_values(
    monkeypatch, tmp_path
):
    item = _item()
    baseline, _ = _collect(item, monkeypatch, tmp_path, mode={})
    enhanced, _ = _collect(item, monkeypatch, tmp_path)
    assert enhanced.state == "success"
    assert {
        key: value for key, value in enhanced.rows[0].items() if key not in NEW_FIELDS
    } == dict(baseline.rows[0])
    assert dict(enhanced.rows[0]) == dict(
        _collect(item, monkeypatch, tmp_path)[0].rows[0]
    )


def test_secret_only_in_replaced_url_is_still_rejected(monkeypatch, tmp_path):
    item = _item()
    item["url"] = API_KEY  # Invalid URL used to disappear during normalization.
    result, _ = _collect(item, monkeypatch, tmp_path)
    assert result.state == "failed" and not result.rows
    assert API_KEY not in (result.error_message or "")


def test_global_minor_schema_keeps_identity_defaults_and_unknown_completeness():
    dataset = load_dataset_registry().resolve("global.news.flash")
    (binding,) = dataset.provider_bindings
    assert dataset.schema_version == "1.1.0"
    assert dataset.primary_key == ("source", "published_local", "content_uid")
    assert not NEW_FIELDS.intersection(dataset.default_projection)
    assert binding.response_completeness is None
    assert (
        dict(binding.request_template)["publication_provenance_mode"] == "raw_item_v1"
    )
    fields = {field.name: field for field in dataset.fields}
    assert all(
        fields[name].nullable and fields[name].logical_type == "text"
        for name in NEW_FIELDS
    )
    old = fc._normalize_item(
        _item(),
        source=_SCRAPE_PARAMS["url"],
        time_key="published_at",
        summary_key=None,
        timezone=fc._GLOBAL_TIMEZONE,
    )
    assert {
        issue
        for issue in _quality_issues(dataset, old)
        if issue.startswith("missing_field:")
    } == {f"missing_field:{name}" for name in NEW_FIELDS}
    cn = load_dataset_registry().resolve("cn.news.flash")
    assert cn.schema_version == "1.0.0"
    assert "publication_provenance_mode" not in cn.provider_bindings[0].request_template


def test_provenance_payload_uses_existing_storage_budget_without_truncation():
    dataset = load_dataset_registry().resolve("global.news.flash")
    (binding,) = dataset.provider_bindings
    item = _item()
    item["extra_large_provider_field"] = "x" * binding.max_payload_bytes_per_row
    row = fc._normalize_item(
        item,
        source=_SCRAPE_PARAMS["url"],
        time_key="published_at",
        summary_key=None,
        timezone=fc._GLOBAL_TIMEZONE,
        preserve_publication_provenance=True,
    )
    assert json.loads(row["raw_item_json"]) == item
    with pytest.raises(ProviderNativeAdmissionError) as error:
        _prepare_rows(dataset=dataset, binding=binding, rows=[row])
    assert error.value.error_code == "resource_budget"


def test_new_provenance_is_valid_but_unknown_provider_keys_stay_schema_drift():
    dataset = load_dataset_registry().resolve("global.news.flash")
    item = _item()
    row = fc._normalize_item(
        item,
        source=_SCRAPE_PARAMS["url"],
        time_key="published_at",
        summary_key=None,
        timezone=fc._GLOBAL_TIMEZONE,
        preserve_publication_provenance=True,
    )
    assert _quality_issues(dataset, row) == []
    row["unknown_provider_key"] = 42
    assert _quality_issues(dataset, row) == ["unknown_field:unknown_provider_key"]


def test_global_success_provenance_never_upgrades_completeness_or_watermark():
    registry = load_dataset_registry()
    dataset = registry.resolve("global.news.flash")
    (binding,) = dataset.provider_bindings
    request = QueryRequest(
        dataset_id=dataset.dataset_id,
        schema_major=1,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=1,
        cursor=None,
    )
    prepared = query_module._prepare_query(
        request,
        QueryExecutionOptions(),
        dataset,
        registry,
        now=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
    )
    evidence = DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id=dataset.dataset_id,
            state="success",
            degraded=False,
            data_through="2026-08-30T11:00:00+00:00",
            observed_at="2026-08-30T11:00:00+00:00",
            receipt_id="synthetic-provenance-receipt",
            reasons=(),
        ),
        current_receipt_status="success",
        current_providers=("firecrawl",),
        last_success_receipt_id=None,
        last_success_providers=(),
        last_success_data_through=None,
        current_provider_config_hashes=(
            ("firecrawl", provider_ingest_config_hash(dataset, binding)),
        ),
    )
    metadata, allow_rows = query_module._runtime_metadata(
        dataset, prepared, evidence, "synthetic-watermark"
    )
    assert allow_rows is True
    assert metadata["state"] == "partial" and metadata["degraded"] is True
    assert metadata["data_through"] is None
    assert metadata["quality"]["valid"] is False
    assert metadata["reasons"] == [
        "freshness_watermark_unverified",
        "response_completeness_unverified",
    ]


@pytest.mark.parametrize("value", [None, 123, "", "unparsed source label"])
def test_unrecognized_source_precision_is_not_inferred(value):
    assert fc._publication_precision(value) == "unknown"


@pytest.mark.parametrize("seed_old_receipts", [True, False])
def test_minor_append_only_versions_and_old_registry_rollback_are_explicitly_degraded(
    monkeypatch, tmp_path, seed_old_receipts
):
    # Reconstruct exactly the a735163 global 1.0 contract: only the additive
    # provenance fields/input/template and minor version differ from 1.1.
    registry = load_dataset_registry()
    new = registry.resolve("global.news.flash")
    (binding,) = new.provider_bindings
    old_binding = replace(
        binding,
        input_fields=tuple(
            field
            for field in binding.input_fields
            if field.name != "publication_provenance_mode"
        ),
        request_template=MappingProxyType(
            {
                key: (
                    value.replace('"required":["title","url","published_at"]',
                                  '"required":["title","url"]')
                    if key == "extraction_schema" else value
                )
                for key, value in binding.request_template.items()
                if key != "publication_provenance_mode"
            }
        ),
    )
    old = replace(
        new,
        schema_version="1.0.0",
        fields=tuple(field for field in new.fields if field.name not in NEW_FIELDS),
        provider_bindings=(old_binding,),
    )
    assert provider_ingest_config_hash(old, old_binding) == (
        "5bff586c35ac12db3533e25e9244d7f40f55448b638359651fc4436f11031db7"
    )
    old_registry = DatasetRegistry((old,), query_defaults=registry.query_defaults)
    db_path = tmp_path / "provenance-roundtrip.sqlite"
    _db(db_path)
    _key_file(tmp_path, monkeypatch)
    collector = fc.FirecrawlWebCollector()
    monkeypatch.setattr(
        collector,
        "_post",
        lambda *args, **kwargs: {
            "success": True,
            "data": {"json": {"items": [_item()]}},
        },
    )
    now = datetime.now(timezone.utc)
    started_at = now.isoformat(timespec="seconds")
    selected_registries = (old_registry, registry) if seed_old_receipts else (registry,)
    for index, selected_registry in enumerate(selected_registries, 1):
        result = collect_provider_native_dataset(
            db_path,
            registry=selected_registry,
            collector=collector,
            dataset_id=new.dataset_id,
            request_window={
                "start_time": "2026-08-30 00:00:00",
                "end_time": "2026-08-30 23:59:59",
            },
            attempt_id=f"018f47de-0000-7000-8000-{index:012d}",
            started_at=started_at,
        )
        assert result.status == "success"
        with sqlite3.connect(db_path) as conn:
            facts = conn.execute(
                "SELECT row_key, payload_json, revision FROM provider_dataset_rows ORDER BY row_key"
            ).fetchall()
        if selected_registry is old_registry:
            original_keys = [row[0] for row in facts]
            assert all(
                not NEW_FIELDS.intersection(json.loads(row[1])) and row[2] == 1
                for row in facts
            )
        elif seed_old_receipts:
            assert new.point_in_time == "append_only"
            assert len(facts) == 2 * len(original_keys)
            assert set(original_keys) < {row[0] for row in facts}
            assert all(row[2] == 1 for row in facts)
            new_facts = [row for row in facts if row[0] not in original_keys]
            assert all(NEW_FIELDS <= json.loads(row[1]).keys() for row in new_facts)
            assert all(
                json.loads(json.loads(row[1])["raw_item_json"]) == _item()
                for row in new_facts
            )
    request = QueryRequest(
        dataset_id=new.dataset_id,
        schema_major=1,
        fields=(),
        filters={},
        as_of=None,
        order=None,
        limit=100,
        cursor=None,
    )
    access = QueryAccessContext.from_grants(
        tenant_id="synthetic-provenance-test",
        scopes=("read",),
        allowed_dataset_ids=(new.dataset_id,),
    )
    for selected_registry in (registry, old_registry):
        service = query_module.QueryService(
            db_path=db_path,
            registry=selected_registry,
            cursor_codec=SignedCursorCodec(b"provenance-test-cursor-key-32-bytes"),
        )
        response = service.execute(
            request,
            access=access,
            now=now + timedelta(minutes=1),
            request_id="provenance-rollback-test",
        )
        assert response["metadata"]["degraded"] is True
        if selected_registry is registry:
            assert len(response["data"]) == len(facts)
        elif seed_old_receipts:
            assert len(response["data"]) == len(facts)
            assert response["metadata"]["reasons"] == [
                "freshness_watermark_unverified",
                "response_completeness_unverified",
            ]
            assert any(NEW_FIELDS <= row.keys() for row in response["data"])

        else:
            assert response["data"] == []
            assert "active_config_receipt_mismatch" in response["metadata"]["reasons"]


@pytest.mark.parametrize(
    "reserved", ["source", "content_uid", "publication_precision", "raw_item_json"]
)
@pytest.mark.parametrize("credential_key", ["api_key", "token"])
def test_raw_reserved_structured_credentials_are_rejected_before_serialization(
    reserved, credential_key, monkeypatch, tmp_path
):
    item = _item()
    item[reserved] = {"nested": {credential_key: "synthetic-foreign-value"}}
    result, _ = _collect(item, monkeypatch, tmp_path)
    assert result.state == "failed" and not result.rows
    assert "synthetic-foreign-value" not in (result.error_message or "")


def test_raw_reserved_structure_respects_original_scan_budget(monkeypatch, tmp_path):
    _key_file(tmp_path, monkeypatch)
    collector = fc.FirecrawlWebCollector()
    item = _item()
    item["source"] = {"nested": {"more": {"non_sensitive": "value"}}}
    monkeypatch.setattr(
        collector,
        "_post",
        lambda *args, **kwargs: {"success": True, "data": {"json": {"items": [item]}}},
    )
    result = collector.collect_outcome(
        "scrape_page_global",
        {**_SCRAPE_PARAMS, **MODE},
        scan_budget=fc.SensitiveScanBudget(max_depth=4),
    )
    assert result.state == "failed" and not result.rows


def test_raw_reserved_node_count_respects_original_scan_budget(monkeypatch, tmp_path):
    _key_file(tmp_path, monkeypatch)
    collector = fc.FirecrawlWebCollector()
    item = _item()
    item["source"] = {"values": list(range(200))}
    monkeypatch.setattr(
        collector,
        "_post",
        lambda *args, **kwargs: {"success": True, "data": {"json": {"items": [item]}}},
    )
    result = collector.collect_outcome(
        "scrape_page_global",
        {**_SCRAPE_PARAMS, **MODE},
        scan_budget=fc.SensitiveScanBudget(max_nodes=100),
    )
    assert result.state == "failed" and not result.rows


def test_raw_business_prose_about_credentials_is_not_a_credential(
    monkeypatch, tmp_path
):
    item = _item()
    item["source"] = {
        "description": "A public report about token and api_key terminology"
    }
    result, _ = _collect(item, monkeypatch, tmp_path)
    assert result.state == "success"
    assert json.loads(result.rows[0]["raw_item_json"]) == item


def test_publication_requirement_changes_ingest_hash_not_output_contract():
    dataset = load_dataset_registry().resolve("global.news.flash")
    (binding,) = dataset.provider_bindings
    schema = json.loads(binding.request_template["extraction_schema"])
    assert schema["properties"]["items"]["items"]["required"] == ["title", "url", "published_at"]
    old_template = dict(binding.request_template)
    old_template["extraction_schema"] = old_template["extraction_schema"].replace(
        '"required":["title","url","published_at"]', '"required":["title","url"]'
    )
    old_binding = replace(binding, request_template=MappingProxyType(old_template))
    old_dataset = replace(dataset, provider_bindings=(old_binding,))
    assert provider_ingest_config_hash(old_dataset, old_binding) != provider_ingest_config_hash(dataset, binding)
    assert replace(old_dataset, provider_bindings=dataset.provider_bindings) == dataset
    assert dataset.schema_version == "1.1.0"


@pytest.mark.parametrize("date_value", [None, "", "not-a-date", "Aug. 14, 2026"])
def test_registry_date_requirement_is_sent_and_never_fills_missing_date(
    tmp_path, monkeypatch, date_value,
):
    dataset = load_dataset_registry().resolve("global.news.flash")
    (binding,) = dataset.provider_bindings
    _key_file(tmp_path, monkeypatch)
    params = dict(binding.request_template)
    params.update(url=binding.fanout.values[0], window_start="2026-08-14 00:00:00", window_end="2026-08-14 23:59:59")
    item = _item(date_value)
    if date_value is None:
        del item["published_at"]
    calls = []
    def post(path, body, *, api_key):
        calls.append(body)
        assert "published_at" in body["formats"][0]["schema"]["properties"]["items"]["items"]["required"]
        return {"success": True, "data": {"json": {"items": [item]}}}
    collector = fc.FirecrawlWebCollector()
    monkeypatch.setattr(collector, "_post", post)
    monkeypatch.setattr(fc._OPENER, "open", lambda *a, **kw: pytest.fail("offline only"))
    result = collector.collect_outcome("scrape_page_global", params)
    assert len(calls) == 1
    if date_value == "Aug. 14, 2026":
        assert result.state == "success"
        assert result.rows[0]["provider_published_at"] == date_value
        assert result.rows[0]["publication_precision"] == "date"
    else:
        assert result.state == "failed" and result.rows == ()
        assert result.error_message == "firecrawl response item invalid"
