from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from dataset_registry import load_dataset_registry
from tools.compile_provider_native_registry import compile_provider_native_registry
from tools.compile_tushare_runtime_contracts import (
    RuntimeContractCompilationError,
    compile_https_probe_plan,
    compile_runtime_contract_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REVIEWED = ROOT / "config" / "tushare_reviewed_contracts.v1.yaml"
POLICY = ROOT / "config" / "tushare_runtime_contract_policy.v1.yaml"
CADENCE_POLICY = ROOT / "config" / "tushare_cadence_policy.v1.yaml"
REQUEST_OBSERVATIONS = ROOT / "config" / "tushare_request_observations.v1.yaml"
TRANSPORT_OBSERVATIONS = ROOT / "config" / "quicksync_interface_observations.v1.yaml"
UPSTREAM_CONTRACTS = ROOT / "config" / "tushare_upstream_contracts.v1.yaml"
PROVIDER_NATIVE_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"

# QuickSync silently returns zero rows when comma-separated ts_code values are
# combined with any filter parameter, and pledge_stat caps every response at
# 1000 rows, so the report family and pledge_stat fan out one code per request
# (see test_report_family_fanouts_are_single_code_in_generated_registry).  The
# APIs below stay at ten codes because their requests carry ts_code as the only
# provider parameter or tolerate multi-value codes with their filter.
TEN_CODE_FANOUT_APIS = {
    "cyq_chips",
    "cyq_perf",
    "stk_rewards",
    "top10_floatholders",
    "top10_holders",
}


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def _yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(_bytes(path))
    assert isinstance(document, dict)
    return document


def _sha(path: Path) -> str:
    return hashlib.sha256(_bytes(path)).hexdigest()


def _yaml_bytes(document: dict[str, object]) -> bytes:
    return yaml.safe_dump(
        document,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _compile(
    *,
    documents: dict[str, object] | None = None,
    request_observations: dict[str, object] | None = None,
    transport_observations: dict[str, object] | None = None,
) -> dict[str, object]:
    document_bytes = (
        _bytes(DOCUMENTS)
        if documents is None or documents == _yaml(DOCUMENTS)
        else _yaml_bytes(documents)
    )
    transport_bytes = (
        _bytes(TRANSPORT_OBSERVATIONS)
        if transport_observations is None
        or transport_observations == _yaml(TRANSPORT_OBSERVATIONS)
        else _yaml_bytes(transport_observations)
    )
    request_document = (
        _yaml(REQUEST_OBSERVATIONS)
        if request_observations is None
        else deepcopy(request_observations)
    )
    if request_observations is None and documents is not None:
        request_document["provenance"]["official_contracts"]["sha256"] = hashlib.sha256(
            document_bytes
        ).hexdigest()
    if request_observations is None and transport_observations is not None:
        request_document["provenance"]["quicksync_interface_observations"]["sha256"] = (
            hashlib.sha256(transport_bytes).hexdigest()
        )
    request_bytes = (
        _bytes(REQUEST_OBSERVATIONS)
        if request_observations is None
        and documents is None
        and transport_observations is None
        else _yaml_bytes(request_document)
    )
    return compile_runtime_contract_bundle(
        document_bytes,
        _bytes(REVIEWED),
        _bytes(POLICY),
        _bytes(CADENCE_POLICY),
        request_observations=request_bytes,
        transport_observations=transport_bytes,
        official_contract_sha256=hashlib.sha256(document_bytes).hexdigest(),
        transport_observations_sha256=hashlib.sha256(transport_bytes).hexdigest(),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )


def _compile_plan(
    *,
    request_observations: dict[str, object] | None = None,
    dataset_field_values: list[dict[str, object]] | None = None,
    registered_contract_bundle: dict[str, object] | None = None,
) -> dict[str, object]:
    registered_bytes = (
        _bytes(UPSTREAM_CONTRACTS)
        if registered_contract_bundle is None
        else _yaml_bytes(registered_contract_bundle)
    )
    request_bytes = (
        _bytes(REQUEST_OBSERVATIONS)
        if request_observations is None
        else _yaml_bytes(request_observations)
    )
    return compile_https_probe_plan(
        _bytes(DOCUMENTS),
        request_bytes,
        _bytes(TRANSPORT_OBSERVATIONS),
        registered_contract_bundle=registered_bytes,
        official_contract_sha256=_sha(DOCUMENTS),
        transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
        request_observations_sha256=hashlib.sha256(request_bytes).hexdigest(),
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
        dataset_field_values=dataset_field_values,
    )


def _entry(document: dict[str, object], api_name: str) -> dict[str, object]:
    entries = document["entries"]
    assert isinstance(entries, list)
    return next(entry for entry in entries if entry["api_name"] == api_name)


def _contract(bundle: dict[str, object], api_name: str) -> dict[str, object]:
    contracts = bundle["contracts"]
    assert isinstance(contracts, list)
    return next(item for item in contracts if item["api_name"] == api_name)


def test_request_observations_are_exactly_190_and_keep_probe_separate_from_activation() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    entries = observations["entries"]
    assert isinstance(entries, list)
    api_names = [entry["api_name"] for entry in entries]

    assert len(api_names) == 190
    assert api_names == sorted(api_names)
    assert len(set(api_names)) == 190
    assert observations["counts"] == {
        "interfaces": 190,
        "probe_executable": 141,
        "probe_blocked": 49,
        "ingest_contract_ready": 126,
        "ingest_contract_blocked": 64,
        "row_limit_ingest_contract_blocked": 15,
    }
    assert observations["counts"] == {
        "interfaces": len(entries),
        "probe_executable": sum(
            entry["probe_state"] == "executable" for entry in entries
        ),
        "probe_blocked": sum(entry["probe_state"] == "blocked" for entry in entries),
        "ingest_contract_ready": sum(
            entry["ingest_contract_state"] == "ready" for entry in entries
        ),
        "ingest_contract_blocked": sum(
            entry["ingest_contract_state"] == "blocked" for entry in entries
        ),
        "row_limit_ingest_contract_blocked": sum(
            entry["row_limit_observation"] is not None for entry in entries
        ),
    }

    seed_apis = {
        "cb_basic",
        "etf_basic",
        "fut_basic",
        "index_basic",
        "index_classify",
        "opt_basic",
        "stock_basic",
    }
    assert all(
        _entry(observations, api_name)["probe_state"] == "executable"
        for api_name in seed_apis
    )

    fund_nav = _entry(observations, "fund_nav")
    assert fund_nav["probe_state"] == "executable"
    assert fund_nav["probe_block_reasons"] == []
    assert fund_nav["ingest_contract_state"] == "blocked"
    assert fund_nav["ingest_contract_block_reasons"] == [
        "response_completeness_unresolved_at_observed_limit"
    ]

    news = _entry(observations, "news")
    assert news["probe_state"] == "executable"
    assert news["probe_block_reasons"] == []
    assert news["unresolved_parameter_keys"] == []
    assert news["parameters"]["src"] == {"source": "literal", "value": "sina"}
    assert news["ingest_contract_state"] == "ready"
    assert news["ingest_contract_block_reasons"] == []


def test_reviewed_active_requests_are_frozen_without_guessing() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)

    assert _entry(observations, "daily")["parameters"] == {
        "trade_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        }
    }
    assert _entry(observations, "stock_basic")["parameters"] == {
        "list_status": {"source": "literal", "value": "L"}
    }
    assert _entry(observations, "stock_basic")["request_variants"] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert _entry(observations, "trade_cal")["parameters"] == {
        "end_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        },
        "exchange": {"source": "literal", "value": "SSE"},
        "start_date": {
            "source": "scheduled_partition",
            "transform": "yyyymmdd",
            "offset_seconds": 0,
        },
    }
    assert _entry(observations, "rt_min")["request_shape"] == "event_or_intraday_window"
    assert _entry(observations, "rt_min")["parameters"] == {
        "freq": {"source": "literal", "value": "5MIN"},
        "ts_code": {"source": "literal", "value": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"},
    }
    observation_fanout = _entry(observations, "rt_min")["fanout"]
    assert observation_fanout["parameter"] == "ts_code"
    assert observation_fanout["batch_size"] == 300
    assert len(observation_fanout["values"]) == 5963
    assert observation_fanout["values"] == sorted(observation_fanout["values"])
    assert _entry(observations, "rt_min")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }

    bundle = _compile()
    assert _contract(bundle, "daily")["request_template"] == {
        "trade_date": "${window.trade_date}"
    }
    assert _contract(bundle, "stock_basic")["request_variants"] == [
        {"list_status": "L"},
        {"list_status": "D"},
        {"list_status": "P"},
    ]
    assert _contract(bundle, "trade_cal")["request_template"] == {
        "end_date": "${window.end_date}",
        "exchange": "SSE",
        "start_date": "${window.start_date}",
    }
    rt_min = _contract(bundle, "rt_min")
    assert rt_min["request_template"] == {"freq": "5MIN", "ts_code": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"}
    assert rt_min["request_shape"] == "event_or_intraday_window"
    assert rt_min["fanout"]["strategy"] == "literal_values"
    assert rt_min["fanout"]["parameter"] == "ts_code"
    assert rt_min["fanout"]["batch_size"] == 300
    assert len(rt_min["fanout"]["values"]) == 5963
    assert rt_min["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }
    assert rt_min["primary_key"] == ["ts_code", "time"]
    assert rt_min["default_projection"] == [
        "ts_code",
        "time",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ]


def test_rt_min_registry_uses_the_exact_frozen_full_universe() -> None:
    registry = _yaml(PROVIDER_NATIVE_REGISTRY)
    datasets = registry["datasets"]
    assert isinstance(datasets, list)
    dataset = next(item for item in datasets if item["dataset_id"] == "cn.dataset.rt_min")
    bindings = dataset["provider_bindings"]
    assert isinstance(bindings, list) and len(bindings) == 1
    binding = bindings[0]

    assert binding["request_shape"] == "event_or_intraday_window"
    fanout = binding["fanout"]
    assert fanout["strategy"] == "literal_values"
    assert fanout["parameter"] == "ts_code"
    assert fanout["batch_size"] == 300
    symbols = fanout["values"]
    assert isinstance(symbols, list)
    official_symbols = binding["request_template"]["ts_code"].split(",")
    assert len(official_symbols) == len(set(official_symbols)) == 30
    assert set(official_symbols).issubset(symbols)
    assert len(set(symbols) - set(official_symbols)) == 5933
    assert len(symbols) == len(set(symbols)) == 5963
    assert binding["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 20,
    }
    assert all(re.fullmatch(r"(?:\d{6}|T\d{5,6}|TS\d{4})\.(?:SZ|SH|BJ)", symbol) for symbol in symbols)


def test_rt_min_observation_fanout_mismatch_fails_closed() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "rt_min")["fanout"]["parameter"] = "unknown"

    with pytest.raises(RuntimeContractCompilationError, match="mapped provider parameter"):
        _compile(request_observations=observations)


def test_literal_values_dimension_fanout_compiles_without_a_seed_dataset() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)

    bundle = _compile(request_observations=observations)

    assert _contract(bundle, "major_news")["fanout"] == {
        "strategy": "literal_values",
        "parameter": "src",
        "values": [
            "新华网",
            "凤凰财经",
            "同花顺",
            "新浪财经",
            "华尔街见闻",
            "中证网",
            "财新网",
            "第一财经",
            "财联社",
        ],
        "batch_size": 1,
    }
    assert _contract(bundle, "major_news")["budgets"]["max_rows_per_attempt"] == 2000
    assert (
        _contract(bundle, "major_news")["budgets"]["max_payload_bytes_per_row"]
        == 131_072
    )

    observations["provenance"]["registered_contract_bundle"]["sha256"] = (
        hashlib.sha256(_yaml_bytes(bundle)).hexdigest()
    )
    plan = _compile_plan(
        request_observations=observations,
        registered_contract_bundle=bundle,
    )
    major_news_probe = _entry(plan, "major_news")
    assert major_news_probe["probe_state"] == "executable"
    assert major_news_probe["params"]["src"] == "新华网"


def test_catalog_only_requests_compile_into_the_existing_generic_data_plane() -> None:
    bundle = _compile()
    adj_factor = _contract(bundle, "adj_factor")
    assert adj_factor["probe_state"] == "executable"
    assert adj_factor["ingest_contract_state"] == "ready"
    assert adj_factor["request_shape"] == "snapshot_or_date_range"
    assert adj_factor["request_template"] == {"trade_date": "${window.trade_date}"}
    assert adj_factor["request_window_policy"] == {
        "required_keys": ["trade_date"],
        "formats": {"trade_date": "yyyymmdd"},
        "range_start_key": "trade_date",
        "range_end_key": "trade_date",
        "max_span_days": 1,
    }

    fund_nav = _contract(bundle, "fund_nav")
    assert fund_nav["probe_state"] == "executable"
    assert fund_nav["ingest_contract_state"] == "blocked"
    assert fund_nav["ingest_contract_block_reasons"] == [
        "response_completeness_unresolved_at_observed_limit"
    ]

    news = _contract(bundle, "news")
    assert news["probe_state"] == "executable"
    assert news["request_template"] == {
        "end_date": "${window.end_date}",
        "src": "sina",
        "start_date": "${window.start_date}",
    }
    assert news["request_variants"] == [{}]


def test_dataset_field_batch_size_defaults_to_one_and_compiles_explicit_values() -> (
    None
):
    observations = _yaml(REQUEST_OBSERVATIONS)
    bundle = _compile()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=_yaml(TRANSPORT_OBSERVATIONS),
    )
    runtime_bindings = {
        binding["api_name"]: binding
        for dataset in registry["datasets"]
        for binding in dataset["provider_bindings"]
    }

    for api_name in TEN_CODE_FANOUT_APIS:
        declaration = _entry(observations, api_name)["parameters"]["ts_code"]
        assert declaration["batch_size"] == 10
        assert _contract(bundle, api_name)["fanout"]["batch_size"] == 10
        assert runtime_bindings[api_name]["fanout"]["batch_size"] == 10

    # rt_min_daily carries an explicit five-code batch: one session holds
    # ~241 one-minute bars per code, so ten codes overflow any feasible
    # max_rows_per_attempt late in the session (scan-envelope fix).
    minute_declaration = _entry(observations, "rt_min_daily")["parameters"][
        "ts_code"
    ]
    assert minute_declaration["batch_size"] == 5
    assert _contract(bundle, "rt_min_daily")["fanout"]["batch_size"] == 5
    assert runtime_bindings["rt_min_daily"]["fanout"]["batch_size"] == 5

    report_family = (
        "balancesheet",
        "cashflow",
        "express",
        "fina_audit",
        "fina_indicator",
        "income",
        "pledge_stat",
    )
    # cashflow / express / fina_audit left the ann_date continuation:
    # official ts_code is independently required (not 二选一), and date +
    # 1-code fanout stayed empty.  Empty ≠ success.  Undated ts_code-only
    # matches pledge_stat.
    undated_report_family = {"cashflow", "express", "fina_audit", "pledge_stat"}
    for api_name in report_family:
        expected_progress = {"cursor_contract_version": 2, "max_batches_per_run": 1}
        if api_name not in undated_report_family:
            expected_progress.update(
                progress_mode="partition_continuation",
                continuation_max_age_days=31,
                partition_date_field="ann_date",
            )
        assert _entry(observations, api_name)["resumable_fanout"] == expected_progress
        assert _entry(observations, api_name)["parameters"]["ts_code"]["batch_size"] == 1
        assert _contract(bundle, api_name)["cadence_class"] == "event"
        assert _contract(bundle, api_name)["resumable_fanout"] == expected_progress
        assert _contract(bundle, api_name)["fanout"]["batch_size"] == 1
        if api_name in undated_report_family:
            assert "ann_date" not in _entry(observations, api_name)["parameters"]
            assert _contract(bundle, api_name)["request_template"] == {}
            assert _contract(bundle, api_name)["request_window_policy"] is None
    assert _entry(observations, "cb_share")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
        "progress_mode": "partition_continuation",
        "continuation_max_age_days": 31,
        "partition_date_field": "publish_date",
    }
    assert _contract(bundle, "cb_share")["cadence_class"] == "event"
    assert _contract(bundle, "cb_basic")["cadence_class"] == "daily_reference"
    assert "resumable_fanout" not in _contract(bundle, "cb_basic")
    # Regular forecast is official single-stock history; forecast_vip is the
    # all-names date/period API and is not this transport.  GZ ac458530
    # ann_date-only returned provider_error / 0 rows.  Empty ≠ success.
    # ts_code-only fanout matches pledge_stat / cashflow / express / fina_audit.
    assert _contract(bundle, "forecast")["cadence_class"] == "event"
    assert _contract(bundle, "forecast")["request_template"] == {}
    assert _contract(bundle, "forecast")["request_window_policy"] is None
    assert _contract(bundle, "forecast")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.equity.security_master",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "forecast")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    assert "ann_date" not in _entry(observations, "forecast")["parameters"]
    assert "ts_code" in _entry(observations, "forecast")["parameters"]
    # fina_mainbz: QuickSync has no ann_date.  Drop run-clock start/end and
    # type=P; ts_code-only single-code history matches pledge_stat.
    assert _contract(bundle, "fina_mainbz")["cadence_class"] == "event"
    assert _contract(bundle, "fina_mainbz")["request_template"] == {}
    assert _contract(bundle, "fina_mainbz")["request_window_policy"] is None
    assert _contract(bundle, "fina_mainbz")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.equity.security_master",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "fina_mainbz")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    assert "type" not in _entry(observations, "fina_mainbz")["parameters"]
    assert "start_date" not in _entry(observations, "fina_mainbz")["parameters"]
    assert "end_date" not in _entry(observations, "fina_mainbz")["parameters"]
    assert _contract(bundle, "pledge_detail")["cadence_class"] == "event"
    assert _contract(bundle, "pledge_detail")["request_template"] == {
        "ann_date": "${window.ann_date}"
    }
    assert _contract(bundle, "top10_cb_holders")["cadence_class"] == "event"
    assert _contract(bundle, "top10_cb_holders")["fanout"] == {
        "strategy": "dataset_field",
        "parameter": "ts_code",
        "source_dataset_id": "cn.dataset.cb_basic",
        "source_field": "ts_code",
        "batch_size": 1,
    }
    assert _contract(bundle, "top10_cb_holders")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }
    # Live ids stay trade_date-only snapshots.  margin / margin_detail are
    # official T+1 08:30 previous-day publishes; prior_open_morning requests
    # the previous open trade_date after 08:30.  Empty ≠ success.
    # margin_secs is 盘前 and can succeed after 16:30 on an open day.
    assert _contract(bundle, "margin")["cadence_class"] == "prior_open_morning"
    assert _contract(bundle, "margin_detail")["cadence_class"] == "prior_open_morning"
    assert _contract(bundle, "margin_secs")["cadence_class"] == "postclose_daily"
    for api_name in ("margin", "margin_detail", "margin_secs"):
        assert _contract(bundle, api_name)["request_template"] == {
            "trade_date": "${window.trade_date}"
        }
        assert _contract(bundle, api_name)["fanout"]["strategy"] == "none"
        assert "trade_date" in _entry(observations, api_name)["parameters"]

    default_observations = deepcopy(observations)
    _entry(default_observations, "express")["parameters"]["ts_code"].pop(
        "batch_size"
    )
    default_bundle = _compile(request_observations=default_observations)
    assert _contract(default_bundle, "express")["fanout"]["batch_size"] == 1

    generic_observations = deepcopy(observations)
    _entry(generic_observations, "cb_price_chg")["parameters"]["ts_code"][
        "batch_size"
    ] = 7
    generic_bundle = _compile(request_observations=generic_observations)
    assert _contract(generic_bundle, "cb_price_chg")["fanout"]["batch_size"] == 7


@pytest.mark.parametrize("batch_size", [0, -1, True])
def test_dataset_field_batch_size_must_be_a_positive_integer(batch_size: object) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "express")["parameters"]["ts_code"]["batch_size"] = (
        batch_size
    )

    with pytest.raises(RuntimeContractCompilationError, match="positive integer"):
        _compile(request_observations=observations)


def test_dataset_field_declaration_rejects_extra_keys() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, "express")["parameters"]["ts_code"]["unexpected"] = (
        "dataset-specific-override"
    )

    with pytest.raises(RuntimeContractCompilationError, match="unknown=unexpected"):
        _compile(request_observations=observations)


def test_probe_plan_keeps_190_audit_entries_but_never_materializes_blocked_params() -> (
    None
):
    plan = _compile_plan()
    entries = plan["entries"]
    assert isinstance(entries, list)
    assert len(entries) == 190
    assert set(plan) == {
        "schema_version",
        "production_ready",
        "provenance",
        "counts",
        "entries",
    }
    assert set(entries[0]) == {
        "api_name",
        "scope_labels",
        "probe_state",
        "probe_block_reasons",
        "ingest_contract_state",
        "ingest_contract_block_reasons",
        "params",
        "fields",
    }
    assert set(plan["provenance"]) == {
        "expected_commit",
        "official_contract_sha256",
        "transport_observations_sha256",
        "request_observations_sha256",
        "api_names_sha256",
        "scheduled_partition",
        "run_clock",
        "seed_authorities",
    }
    assert plan["counts"] == {
        "planned": 190,
        "executable": 141,
        "blocked": 49,
        "ingest_contract_ready": 126,
        "ingest_contract_blocked": 64,
    }

    daily = _entry(plan, "daily")
    assert daily["params"] == {"trade_date": "20260718"}
    assert daily["probe_state"] == "executable"
    assert daily["fields"]

    news = _entry(plan, "news")
    assert news["params"] == {
        "end_date": "2026-07-21 18:30:00",
        "src": "sina",
        "start_date": "2026-07-21 18:29:00",
    }
    assert news["probe_state"] == "executable"
    assert news["probe_block_reasons"] == []
    assert news["ingest_contract_state"] == "ready"
    assert news["ingest_contract_block_reasons"] == []
    assert news["scope_labels"] == ["all", "gaps"]
    assert all(
        entry["params"] == {} for entry in entries if entry["probe_state"] == "blocked"
    )

    daily_basic = _entry(plan, "daily_basic")
    assert daily_basic["probe_state"] == "executable"
    assert daily_basic["probe_block_reasons"] == []
    assert daily_basic["params"] == {"trade_date": "20260718"}

    rt_min = _entry(plan, "rt_min")
    assert rt_min["probe_state"] == "executable"
    assert rt_min["probe_block_reasons"] == []
    assert rt_min["params"] == {"freq": "5MIN", "ts_code": "600000.SH,000001.SZ,600519.SH,601318.SH,000858.SZ,002594.SZ,601988.SH,600036.SH,000333.SZ,601899.SH,000837.SZ,000938.SZ,000963.SZ,002049.SZ,002050.SZ,002294.SZ,002422.SZ,002436.SZ,002472.SZ,002747.SZ,002979.SZ,600161.SH,600196.SH,600276.SH,600410.SH,600521.SH,600566.SH,600602.SH,600845.SH,601138.SH"}


def test_checked_probe_authorities_compile_without_test_rebinding() -> None:
    assert (
        _yaml(REQUEST_OBSERVATIONS)["provenance"]["registered_contract_bundle"][
            "sha256"
        ]
        == _sha(UPSTREAM_CONTRACTS)
    )
    plan = _compile_plan()
    assert plan["provenance"]["request_observations_sha256"] == _sha(
        REQUEST_OBSERVATIONS
    )


def test_probe_plan_unlocks_dataset_fanout_only_from_a_fresh_success_receipt() -> None:
    seed = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "2.0.0",
        "fresh": True,
    }
    plan = _compile_plan(dataset_field_values=[seed])
    assert plan["counts"] == {
        "planned": 190,
        "executable": 158,
        "blocked": 32,
        "ingest_contract_ready": 143,
        "ingest_contract_blocked": 47,
    }
    express = _entry(plan, "express")
    assert express["probe_state"] == "executable"
    assert express["probe_block_reasons"] == []
    assert express["params"] == {"ts_code": "600000.SH"}
    cashflow = _entry(plan, "cashflow")
    assert cashflow["probe_state"] == "executable"
    assert cashflow["probe_block_reasons"] == []
    assert cashflow["params"] == {"ts_code": "600000.SH"}
    fina_audit = _entry(plan, "fina_audit")
    assert fina_audit["probe_state"] == "executable"
    assert fina_audit["probe_block_reasons"] == []
    assert fina_audit["params"] == {"ts_code": "600000.SH"}
    forecast = _entry(plan, "forecast")
    assert forecast["probe_state"] == "executable"
    assert forecast["probe_block_reasons"] == []
    assert forecast["params"] == {"ts_code": "600000.SH"}
    assert "600000.SH" not in yaml.safe_dump(plan["provenance"])
    assert plan["provenance"]["seed_authorities"] == [
        {
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "receipt_id": "receipt-stock-basic-20260718",
            "data_through": "20260718",
            "schema_version": "2.0.0",
        }
    ]
    assert set(plan["provenance"]["seed_authorities"][0]) == {
        "dataset_id",
        "field",
        "receipt_id",
        "data_through",
        "schema_version",
    }
    assert "value" not in plan["provenance"]["seed_authorities"][0]

    cb_seed = {
        "dataset_id": "cn.dataset.cb_basic",
        "field": "ts_code",
        "value": "110000.SH",
        "receipt_id": "receipt-cb-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }
    multi_seed_plan = _compile_plan(dataset_field_values=[seed, cb_seed])
    seed_authorities = multi_seed_plan["provenance"]["seed_authorities"]
    assert [
        (authority["dataset_id"], authority["field"]) for authority in seed_authorities
    ] == sorted(
        (authority["dataset_id"], authority["field"]) for authority in seed_authorities
    )
    assert all("value" not in authority for authority in seed_authorities)

    with pytest.raises(RuntimeContractCompilationError, match="duplicate trusted seed"):
        _compile_plan(dataset_field_values=[seed, deepcopy(seed)])

    stale = deepcopy(seed)
    stale["fresh"] = False
    with pytest.raises(RuntimeContractCompilationError, match="fresh success receipt"):
        _compile_plan(dataset_field_values=[stale])


@pytest.mark.parametrize(
    ("dataset_id", "field", "message"),
    [
        (
            "cn.dataset.nonexistent",
            "ts_code",
            "references unknown seed dataset",
        ),
        (
            "cn.equity.security_master",
            "nonexistent_field",
            "references unknown seed field",
        ),
    ],
)
def test_probe_plan_rejects_unregistered_seed_declarations_before_generation(
    dataset_id: str,
    field: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    express = _entry(observations, "express")
    declaration = express["parameters"]["ts_code"]
    declaration["dataset_id"] = dataset_id
    declaration["field"] = field
    seed = {
        "dataset_id": dataset_id,
        "field": field,
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "1.0.0",
        "fresh": True,
    }

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile_plan(
            request_observations=observations,
            dataset_field_values=[seed],
        )


def test_probe_plan_rejects_seed_schema_drift_and_blocked_producer() -> None:
    seed = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "value": "600000.SH",
        "receipt_id": "receipt-stock-basic-20260718",
        "receipt_state": "success",
        "data_through": "20260718",
        "schema_version": "v1",
        "fresh": True,
    }
    with pytest.raises(RuntimeContractCompilationError, match="schema_version"):
        _compile_plan(dataset_field_values=[seed])

    seed["schema_version"] = "9.9.9"
    with pytest.raises(
        RuntimeContractCompilationError,
        match="schema_version does not match registered producer",
    ):
        _compile_plan(dataset_field_values=[seed])

    observations = _yaml(REQUEST_OBSERVATIONS)
    producer = _entry(observations, "stock_basic")
    producer["probe_state"] = "blocked"
    producer["probe_block_reasons"] = ["request_anchor_unresolved"]
    observations["counts"]["probe_executable"] = 140
    observations["counts"]["probe_blocked"] = 50
    seed["schema_version"] = "2.0.0"
    with pytest.raises(RuntimeContractCompilationError, match="producer.*executable"):
        _compile_plan(
            request_observations=observations,
            dataset_field_values=[seed],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("invalid_request_shape", "request_shape is unsupported"),
        ("unsafe_variant_placeholder", "concrete finite JSON scalar"),
        ("unsafe_variant_nested", "concrete finite JSON scalar"),
        ("provenance_extra", "provenance keys invalid"),
        ("provenance_source_extra", "official_contracts keys invalid"),
        ("normalization_extra", "normalization_policy keys invalid"),
        ("normalization_drift", "normalization_policy does not match"),
    ],
)
def test_runtime_and_plan_share_closed_request_observation_front_door(
    mutation: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    if mutation == "invalid_request_shape":
        _entry(observations, "daily")["request_shape"] = "custom"
    elif mutation == "unsafe_variant_placeholder":
        _entry(observations, "stock_basic")["request_variants"][0]["list_status"] = (
            "${window.list_status}"
        )
    elif mutation == "unsafe_variant_nested":
        _entry(observations, "stock_basic")["request_variants"][0]["list_status"] = {
            "nested": "L"
        }
    elif mutation == "provenance_extra":
        observations["provenance"]["unexpected"] = "not-authority"
    elif mutation == "provenance_source_extra":
        observations["provenance"]["official_contracts"]["unexpected"] = True
    elif mutation == "normalization_extra":
        observations["normalization_policy"]["unexpected"] = True
    else:
        observations["normalization_policy"]["max_abs_offset_seconds"] = 1

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)
    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile_plan(request_observations=observations)


def test_probe_plan_is_pure_and_does_not_require_migration_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["provenance"].pop("migration_request_profiles")
    observation_bytes = _yaml_bytes(observations)
    document_bytes = _bytes(DOCUMENTS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)
    registered_bytes = _bytes(UPSTREAM_CONTRACTS)
    official_sha = _sha(DOCUMENTS)
    transport_sha = _sha(TRANSPORT_OBSERVATIONS)
    request_sha = hashlib.sha256(observation_bytes).hexdigest()

    def _forbid_io(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("compile_https_probe_plan must not read files")

    monkeypatch.setattr(Path, "open", _forbid_io)
    monkeypatch.setattr(Path, "read_bytes", _forbid_io)
    monkeypatch.setattr(Path, "read_text", _forbid_io)

    plan = compile_https_probe_plan(
        document_bytes,
        observation_bytes,
        transport_bytes,
        registered_contract_bundle=registered_bytes,
        official_contract_sha256=official_sha,
        transport_observations_sha256=transport_sha,
        request_observations_sha256=request_sha,
        expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
        run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
        scheduled_partition="20260718",
    )
    assert plan["counts"]["planned"] == 190


@pytest.mark.parametrize(
    ("authority", "message"),
    [
        ("official", "official contract bytes do not match"),
        ("request", "request observations bytes do not match"),
        ("transport", "transport observations bytes do not match"),
        ("registered", "registered contract bundle bytes do not match"),
    ],
)
def test_probe_plan_rejects_content_drift_behind_frozen_authority_sha(
    authority: str,
    message: str,
) -> None:
    document_bytes = _bytes(DOCUMENTS)
    request_bytes = _bytes(REQUEST_OBSERVATIONS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)
    registered_bytes = _bytes(UPSTREAM_CONTRACTS)

    if authority == "official":
        document = _yaml(DOCUMENTS)
        document["provider"] = "tampered"
        document_bytes = _yaml_bytes(document)
    elif authority == "request":
        request = _yaml(REQUEST_OBSERVATIONS)
        _entry(request, "daily")["parameters"]["trade_date"]["offset_seconds"] = 86400
        request_bytes = _yaml_bytes(request)
    elif authority == "transport":
        transport = _yaml(TRANSPORT_OBSERVATIONS)
        transport["provider"] = "tampered"
        transport_bytes = _yaml_bytes(transport)
    else:
        registered = _yaml(UPSTREAM_CONTRACTS)
        registered["contracts"][0]["domain"] = "tampered"
        registered_bytes = _yaml_bytes(registered)

    with pytest.raises(RuntimeContractCompilationError, match=message):
        compile_https_probe_plan(
            document_bytes,
            request_bytes,
            transport_bytes,
            registered_contract_bundle=registered_bytes,
            official_contract_sha256=_sha(DOCUMENTS),
            transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
            request_observations_sha256=_sha(REQUEST_OBSERVATIONS),
            expected_commit="7d65743732fb178c3120438fb7d3aa19a34cabfa",
            run_clock=datetime(2026, 7, 21, 10, 30, tzinfo=timezone.utc),
            scheduled_partition="20260718",
        )


@pytest.mark.parametrize(
    ("authority", "message"),
    [
        ("official", "official contract bytes do not match"),
        ("request", "request observations bytes do not match"),
        ("transport", "transport observations bytes do not match"),
        ("reviewed", "reviewed contract bundle bytes do not match"),
    ],
)
def test_runtime_compiler_rejects_content_drift_behind_frozen_authority_sha(
    authority: str,
    message: str,
) -> None:
    document_bytes = _bytes(DOCUMENTS)
    reviewed_bytes = _bytes(REVIEWED)
    request_bytes = _bytes(REQUEST_OBSERVATIONS)
    transport_bytes = _bytes(TRANSPORT_OBSERVATIONS)

    if authority == "official":
        document = _yaml(DOCUMENTS)
        document["provider"] = "tampered"
        document_bytes = _yaml_bytes(document)
    elif authority == "request":
        request = _yaml(REQUEST_OBSERVATIONS)
        _entry(request, "bak_daily")["parameters"]["limit"]["value"] = 2
        request_bytes = _yaml_bytes(request)
    elif authority == "transport":
        transport = _yaml(TRANSPORT_OBSERVATIONS)
        transport["provider"] = "tampered"
        transport_bytes = _yaml_bytes(transport)
    else:
        reviewed = _yaml(REVIEWED)
        reviewed["contracts"][0]["domain"] = "tampered"
        reviewed_bytes = _yaml_bytes(reviewed)

    with pytest.raises(RuntimeContractCompilationError, match=message):
        compile_runtime_contract_bundle(
            document_bytes,
            reviewed_bytes,
            _bytes(POLICY),
            _bytes(CADENCE_POLICY),
            request_observations=request_bytes,
            transport_observations=transport_bytes,
            official_contract_sha256=_sha(DOCUMENTS),
            transport_observations_sha256=_sha(TRANSPORT_OBSERVATIONS),
            request_observations_sha256=_sha(REQUEST_OBSERVATIONS),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown_source", "parameter source"),
        ("unknown_transform", "parameter transform"),
        ("required_true_unmapped", "required provider parameter"),
        ("either_or_unmapped", "二选一 parameter"),
        ("required_unknown_executable", "unknown official requiredness"),
        ("executable_with_reason", "probe_state=executable"),
        ("blocked_without_reason", "probe_state=blocked"),
        ("unsorted_reasons", "probe_block_reasons must be sorted"),
    ],
)
def test_request_observation_contract_fails_closed(
    mutation: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    if mutation == "unknown_source":
        _entry(observations, "daily")["parameters"]["trade_date"]["source"] = "today"
    elif mutation == "unknown_transform":
        _entry(observations, "daily")["parameters"]["trade_date"]["transform"] = "date"
    elif mutation == "required_true_unmapped":
        _entry(observations, "fut_basic")["parameters"] = {}
    elif mutation == "either_or_unmapped":
        _entry(observations, "daily_basic")["parameters"] = {}
    elif mutation == "required_unknown_executable":
        item = _entry(observations, "fund_company")
        item["probe_state"] = "executable"
        item["probe_block_reasons"] = []
    elif mutation == "executable_with_reason":
        _entry(observations, "daily")["probe_block_reasons"] = [
            "request_anchor_unresolved"
        ]
    elif mutation == "blocked_without_reason":
        item = _entry(observations, "news")
        item["probe_state"] = "blocked"
        item["probe_block_reasons"] = []
    else:
        _entry(observations, "news")["probe_block_reasons"] = [
            "required_parameter_unresolved",
            "required_enum_unresolved",
        ]

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)


def test_optional_resumable_fanout_is_deterministic_and_absent_is_unchanged() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    target = _entry(observations, "cyq_chips")

    policy = target.pop("resumable_fanout")
    without_policy = _compile(request_observations=observations)
    assert "resumable_fanout" not in _contract(without_policy, "cyq_chips")

    target["resumable_fanout"] = policy
    first = _compile(request_observations=observations)
    second = _compile(request_observations=deepcopy(observations))

    assert first == second
    assert _contract(first, "cyq_chips")["resumable_fanout"] == {
        "cursor_contract_version": 2,
        "max_batches_per_run": 1,
    }


@pytest.mark.parametrize(
    ("policy", "api_name", "message"),
    [
        (
            {
                "cursor_contract_version": 2,
                "max_batches_per_run": 1,
                "unknown": True,
            },
            "cyq_chips",
            "resumable_fanout keys invalid",
        ),
        (
            {"cursor_contract_version": 1, "max_batches_per_run": 1},
            "cyq_chips",
            "cursor_contract_version must be 2",
        ),
        (
            {"cursor_contract_version": 2, "max_batches_per_run": 0},
            "cyq_chips",
            "max_batches_per_run must be a positive integer",
        ),
        (
            {"cursor_contract_version": 2, "max_batches_per_run": 1},
            "daily",
            "requires a non-empty fanout",
        ),
    ],
)
def test_optional_resumable_fanout_fails_closed(
    policy: dict[str, object],
    api_name: str,
    message: str,
) -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    _entry(observations, api_name)["resumable_fanout"] = policy

    with pytest.raises(RuntimeContractCompilationError, match=message):
        _compile(request_observations=observations)


def test_request_observation_source_bytes_and_api_set_are_bound() -> None:
    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["provenance"]["official_contracts"]["sha256"] = "f" * 64
    with pytest.raises(
        RuntimeContractCompilationError, match="official contract bytes"
    ):
        _compile(request_observations=observations)

    observations = _yaml(REQUEST_OBSERVATIONS)
    observations["entries"].pop()
    observations["counts"]["interfaces"] = 189
    with pytest.raises(RuntimeContractCompilationError, match="exactly 190"):
        _compile(request_observations=observations)


def test_active_loader_accepts_runtime_request_window_formats_and_rejects_others(
    tmp_path: Path,
) -> None:
    bundle = _compile()
    registry = compile_provider_native_registry(
        bundle,
        observations_document=_yaml(TRANSPORT_OBSERVATIONS),
    )
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    loaded = load_dataset_registry(path)
    monthly = loaded.provider_binding("cn.dataset.cn_cpi", "tushare")
    assert monthly.activation_state == "active"
    assert monthly.request_window_policy is not None
    assert monthly.request_window_policy.formats["m"] == "yyyymm"

    supported = {
        "cn.dataset.adj_factor": "yyyymmdd",
        "cn.dataset.broker_recommend": "yyyymm",
        "cn.dataset.cn_gdp": "yyyy_qn",
        "cn.dataset.fut_weekly_detail": "yyyyww",
        "cn.dataset.stk_nineturn": "local_datetime_seconds",
    }
    for dataset_id, expected_format in supported.items():
        candidate = deepcopy(registry)
        item = next(
            dataset
            for dataset in candidate["datasets"]
            if dataset["dataset_id"] == dataset_id
        )
        binding = item["provider_bindings"][0]
        binding["entitlement_state"] = "active"
        binding["activation_state"] = "active"
        binding["probe_state"] = "executable"
        binding["probe_block_reasons"] = []
        binding["ingest_contract_state"] = "ready"
        binding["ingest_contract_block_reasons"] = []
        path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
        loaded_binding = load_dataset_registry(path).provider_binding(
            dataset_id, "tushare"
        )
        assert loaded_binding.request_window_policy is not None
        assert set(loaded_binding.request_window_policy.formats.values()) == {
            expected_format
        }

    for unsupported_format in ("identity", "rfc3339"):
        candidate = deepcopy(registry)
        item = next(
            dataset
            for dataset in candidate["datasets"]
            if dataset["dataset_id"] == "cn.dataset.adj_factor"
        )
        binding = item["provider_bindings"][0]
        binding["activation_state"] = "active"
        binding["request_window_policy"]["formats"]["trade_date"] = (
            unsupported_format
        )
        path.write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
        with pytest.raises(ValueError, match="active.*runtime request_window format"):
            load_dataset_registry(path)


def test_runtime_compiler_does_not_mutate_any_authority_input() -> None:
    documents = _yaml(DOCUMENTS)
    request_observations = _yaml(REQUEST_OBSERVATIONS)
    transport_observations = _yaml(TRANSPORT_OBSERVATIONS)
    before = (
        deepcopy(documents),
        deepcopy(request_observations),
        deepcopy(transport_observations),
    )

    _compile(
        documents=documents,
        request_observations=request_observations,
        transport_observations=transport_observations,
    )

    assert (documents, request_observations, transport_observations) == before
