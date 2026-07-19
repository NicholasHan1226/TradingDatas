from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import tools.internal_v1_probe as probe


ROOT = Path(__file__).resolve().parents[1]
TARGET_REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"
EXPECTED_PROVIDER_NATIVE_ONESHOT_TIMEOUTS = {
    "sharedsignals-provider-native-collect.service": "900s",
    "sharedsignals-v1-probe.service": "120s",
}


def _registry_with_active_datasets(
    path: Path,
    active_dataset_ids: set[str],
) -> Path:
    raw = yaml.safe_load(TARGET_REGISTRY.read_text(encoding="utf-8"))
    for dataset in raw["datasets"]:
        for binding in dataset["provider_bindings"]:
            active = dataset["dataset_id"] in active_dataset_ids
            binding["entitlement_state"] = "active" if active else "unknown"
            binding["activation_state"] = "active" if active else "paused"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _catalog_row(dataset_id: str, *, runtime_state: str = "success") -> dict[str, Any]:
    degraded = runtime_state not in {"success", "empty"}
    return {
        "dataset_id": dataset_id,
        "schema_major": 2,
        "timezone": "Asia/Shanghai",
        "runtime": {
            "state": runtime_state,
            "degraded": degraded,
            "receipt_id": None if degraded else "receipt-shared",
            "data_through": None if degraded else "20260718",
            "observed_at": None if degraded else "2026-07-18T09:00:00Z",
            "reasons": [runtime_state] if degraded else [],
        },
    }


def _catalog(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "api_version": "v1",
        "catalog_version": "v1-test",
        "request_id": "request-catalog",
        "data": rows,
        "next_cursor": None,
    }


def _query(dataset_id: str, *, runtime_state: str = "success") -> dict[str, Any]:
    degraded = runtime_state not in {"success", "empty"}
    healthy = runtime_state == "success"
    return {
        "api_version": "v1",
        "catalog_version": "v1-test",
        "request_id": f"request-{dataset_id}",
        "dataset_id": dataset_id,
        "schema_version": "2.0.0",
        "data": [{"value": 1}] if healthy else [],
        "next_cursor": None,
        "metadata": {
            "state": "ready" if healthy else runtime_state,
            "runtime_state": runtime_state,
            "degraded": degraded,
            "freshness": {
                "state": "fresh" if healthy else runtime_state,
                "stale": runtime_state == "stale",
                "sla_seconds": 60,
            },
            "quality": {
                "state": "valid" if healthy else "degraded",
                "valid": healthy,
                "evidence": [],
            },
            "lineage": {
                "state": "complete" if healthy else "missing",
                "complete": healthy,
                "provider_neutral": True,
                "authority": "sqlite_ingest_receipts",
                "dataset_id": dataset_id,
                "providers": ["tushare"] if healthy else [],
                "receipt_watermark": "receipt-query" if healthy else None,
            },
            "receipt_id": "receipt-shared" if healthy else None,
            "data_through": ("2026-07-18T00:00:00+08:00" if healthy else None),
            "observed_at": ("2026-07-18T09:00:00+00:00" if healthy else None),
            "requested_as_of": None,
            "resolved_as_of": None,
            "reasons": [] if healthy else [runtime_state],
        },
    }


class _FakeTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None]] = []

    def __call__(
        self,
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        assert timeout > 0
        self.calls.append((url, method, headers, body))
        return self.responses.pop(0)


def test_probe_uses_only_authenticated_catalog_and_query() -> None:
    dataset_id = "cn.synthetic.internal"
    transport = _FakeTransport(
        [_catalog([_catalog_row(dataset_id)]), _query(dataset_id)]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="not-printed-secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 0
    assert result.payload["status"] == "healthy"
    assert "not-printed-secret" not in json.dumps(result.payload)
    assert [call[0] for call in transport.calls] == [
        "http://127.0.0.1:18082/v1/catalog?limit=500",
        "http://127.0.0.1:18082/v1/query",
    ]
    assert all(
        call[2]["Authorization"] == "Bearer not-printed-secret"
        for call in transport.calls
    )
    assert transport.calls[1][3] == {
        "as_of": None,
        "cursor": None,
        "dataset_id": dataset_id,
        "fields": [],
        "filters": {},
        "limit": 1,
        "schema_major": 2,
    }


def test_http_200_degraded_dataset_fails_strict_probe() -> None:
    dataset_id = "cn.synthetic.internal"
    transport = _FakeTransport(
        [
            _catalog([_catalog_row(dataset_id, runtime_state="stale")]),
            _query(dataset_id, runtime_state="stale"),
        ]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1
    assert result.payload["status"] == "failed"
    assert result.payload["datasets"][0]["state"] == "stale"


def test_http_200_empty_expected_dataset_is_not_ready() -> None:
    dataset_id = "cn.synthetic.internal"
    transport = _FakeTransport(
        [
            _catalog([_catalog_row(dataset_id, runtime_state="empty")]),
            _query(dataset_id, runtime_state="empty"),
        ]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1
    assert result.payload["datasets"][0]["state"] == "empty"


def test_missing_receipt_watermark_fails_even_when_other_metadata_is_healthy() -> None:
    dataset_id = "cn.synthetic.internal"
    response = _query(dataset_id)
    del response["metadata"]["lineage"]["receipt_watermark"]
    transport = _FakeTransport([_catalog([_catalog_row(dataset_id)]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


def test_success_requires_at_least_one_data_row() -> None:
    dataset_id = "cn.synthetic.internal"
    response = _query(dataset_id)
    response["data"] = []
    transport = _FakeTransport([_catalog([_catalog_row(dataset_id)]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("quality", "evidence"), "not-a-list"),
        (("lineage", "state"), "incomplete"),
        (("lineage", "providers"), [1]),
    ],
)
def test_success_requires_complete_typed_quality_and_lineage(
    path: tuple[str, str],
    value: object,
) -> None:
    dataset_id = "cn.synthetic.internal"
    response = _query(dataset_id)
    response["metadata"][path[0]][path[1]] = value
    transport = _FakeTransport([_catalog([_catalog_row(dataset_id)]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize("catalog_receipt", [None, "different-receipt"])
def test_catalog_success_evidence_is_complete_and_matches_query(
    catalog_receipt: object,
) -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["runtime"]["receipt_id"] = catalog_receipt
    transport = _FakeTransport([_catalog([catalog_row]), _query(dataset_id)])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("catalog_data_through", "query_data_through"),
    [
        ("20260718", "2026-07-18T00:00:00+08:00"),
        ("2026-07-18T01:00:00Z", "2026-07-18T09:00:00+08:00"),
    ],
)
def test_catalog_and_query_accept_semantically_equal_runtime_timestamps(
    catalog_data_through: str,
    query_data_through: str,
) -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["runtime"]["data_through"] = catalog_data_through
    catalog_row["runtime"]["observed_at"] = "2026-07-18T09:00:00Z"
    response = _query(dataset_id)
    response["metadata"]["data_through"] = query_data_through
    response["metadata"]["observed_at"] = "2026-07-18T17:00:00+08:00"
    transport = _FakeTransport([_catalog([catalog_row]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 0


def test_frozen_contract_catalog_and_query_runtime_evidence_is_healthy() -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/sharedsignals_v1_query_contract.json").read_text(
            encoding="utf-8"
        )
    )
    catalog = fixture["catalog_response"]
    query = fixture["healthy_query"]["response"]
    dataset_id = query["dataset_id"]
    transport = _FakeTransport([catalog, query])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 0


def test_catalog_unambiguous_local_data_through_matches_canonical_query() -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["runtime"]["data_through"] = "2026-07-18T09:00:00"
    response = _query(dataset_id)
    response["metadata"]["data_through"] = "2026-07-18T09:00:00+08:00"
    transport = _FakeTransport([_catalog([catalog_row]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("field", "catalog_value", "query_value"),
    [
        ("data_through", "20260718", "2026-07-18T00:00:00Z"),
        (
            "observed_at",
            "2026-07-18T09:00:00Z",
            "2026-07-18T09:00:01Z",
        ),
    ],
)
def test_catalog_and_query_reject_different_runtime_evidence_instants(
    field: str,
    catalog_value: str,
    query_value: str,
) -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["runtime"][field] = catalog_value
    response = _query(dataset_id)
    response["metadata"][field] = query_value
    transport = _FakeTransport([_catalog([catalog_row]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("timezone_name", "catalog_value", "query_value"),
    [
        (
            "America/New_York",
            "2026-11-01T01:30:00",
            "2026-11-01T05:30:00+00:00",
        ),
        (
            "America/New_York",
            "2026-03-08T02:30:00",
            "2026-03-08T07:30:00+00:00",
        ),
        (
            "Asia/Shanghai",
            "20260230",
            "2026-03-02T00:00:00+08:00",
        ),
    ],
)
def test_catalog_rejects_ambiguous_nonexistent_or_invalid_data_through(
    timezone_name: str,
    catalog_value: str,
    query_value: str,
) -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["timezone"] = timezone_name
    catalog_row["runtime"]["data_through"] = catalog_value
    response = _query(dataset_id)
    response["metadata"]["data_through"] = query_value
    transport = _FakeTransport([_catalog([catalog_row]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("field", "query_value"),
    [
        ("data_through", "20260718"),
        ("data_through", "2026-07-18T00:00:00+08:00 "),
        ("observed_at", "2026-07-18T09:00:00Z"),
        ("observed_at", "2026-07-18T09:00:00.000000+00:00"),
    ],
)
def test_query_runtime_evidence_must_be_canonical_rfc3339(
    field: str,
    query_value: str,
) -> None:
    dataset_id = "cn.synthetic.internal"
    response = _query(dataset_id)
    response["metadata"][field] = query_value
    transport = _FakeTransport([_catalog([_catalog_row(dataset_id)]), response])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


def test_catalog_observed_at_must_be_aware() -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["runtime"]["observed_at"] = "2026-07-18T09:00:00"
    transport = _FakeTransport([_catalog([catalog_row]), _query(dataset_id)])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize("timezone_name", [None, "", "Mars/Olympus_Mons"])
def test_catalog_runtime_requires_a_valid_dataset_timezone(
    timezone_name: object,
) -> None:
    dataset_id = "cn.synthetic.internal"
    catalog_row = _catalog_row(dataset_id)
    catalog_row["timezone"] = timezone_name
    transport = _FakeTransport([_catalog([catalog_row]), _query(dataset_id)])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1


@pytest.mark.parametrize("runtime_state", ["paused", "unobserved"])
def test_bootstrap_policy_distinguishes_startup_states(runtime_state: str) -> None:
    dataset_id = "cn.synthetic.internal"
    transport = _FakeTransport(
        [
            _catalog([_catalog_row(dataset_id, runtime_state=runtime_state)]),
            _query(dataset_id, runtime_state=runtime_state),
        ]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="bootstrap",
        transport=transport,
    )

    assert result.exit_code == 2
    assert result.payload["status"] == "starting"
    assert result.payload["datasets"][0] == {
        "dataset_id": dataset_id,
        "state": runtime_state,
        "status": "starting",
    }


def test_missing_expected_dataset_fails_without_query() -> None:
    transport = _FakeTransport([_catalog([])])

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=("cn.synthetic.missing",),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1
    assert result.payload["status"] == "failed"
    assert len(transport.calls) == 1


def test_catalog_extra_dataset_fails_bidirectional_registry_match() -> None:
    expected = "cn.synthetic.expected"
    extra = "cn.synthetic.extra"
    transport = _FakeTransport(
        [
            _catalog([_catalog_row(expected), _catalog_row(extra)]),
            _query(expected),
        ]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(expected,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1
    assert len(transport.calls) == 1


def test_catalog_and_query_runtime_evidence_must_agree() -> None:
    dataset_id = "cn.synthetic.internal"
    transport = _FakeTransport(
        [
            _catalog([_catalog_row(dataset_id, runtime_state="unobserved")]),
            _query(dataset_id, runtime_state="success"),
        ]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 1
    assert result.payload["status"] == "failed"


def test_expected_dataset_uses_the_public_query_identity_grammar() -> None:
    dataset_id = "market.daily"
    transport = _FakeTransport(
        [_catalog([_catalog_row(dataset_id)]), _query(dataset_id)]
    )

    result = probe.probe_internal_v1(
        base_url="http://127.0.0.1:18082",
        token="secret",
        expected_dataset_ids=(dataset_id,),
        startup_policy="strict",
        transport=transport,
    )

    assert result.exit_code == 0


@pytest.mark.parametrize(
    "base_url",
    [
        "https://signals.example.com",
        "http://127.0.0.1:8082",
        "http://127.0.0.1:18083",
        "http://localhost:18082",
        "http://[::1]:18082",
        "http://127.0.0.1:18082/",
        "http://127.0.0.1:18082/path",
        "http://127.0.0.1:18082?probe=1",
        "http://user@127.0.0.1:18082",
    ],
)
def test_probe_rejects_non_loopback_or_non_root_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        probe.probe_internal_v1(
            base_url=base_url,
            token="secret",
            expected_dataset_ids=("cn.synthetic.internal",),
            startup_policy="strict",
            transport=lambda *args, **kwargs: pytest.fail("must not call HTTP"),
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:18082",
        "http://127.0.0.1:8082",
        "http://[::1]:18082",
        "http://127.0.0.1:18082/path",
        "http://127.0.0.1:18082?probe=1",
        "http://user@127.0.0.1:18082",
        "http://127.0.0.1:18082/",
    ],
)
def test_main_rejects_noncanonical_origin_before_sensitive_reads_or_transport(
    base_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = {"token": 0, "registry": 0}

    def token_reader() -> str:
        calls["token"] += 1
        return "probe-sentinel-secret"

    def registry_reader(path: Path) -> tuple[str, ...]:
        calls["registry"] += 1
        return ("cn.equity.daily",)

    transport = _FakeTransport([])
    monkeypatch.setattr(probe, "_probe_token_from_environment", token_reader)
    monkeypatch.setattr(probe, "expected_dataset_ids_from_registry", registry_reader)
    monkeypatch.setattr(probe, "_urlopen_transport", transport)

    code = probe.main(
        [
            "--registry",
            "/must-not-be-read/registry.yaml",
            "--base-url",
            base_url,
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert calls == {"token": 0, "registry": 0}
    assert transport.calls == []
    assert "probe-sentinel-secret" not in output


def test_probe_requires_token_and_nonempty_unique_expected_datasets() -> None:
    for token, datasets in (
        ("", ("cn.synthetic.internal",)),
        ("secret", ()),
        ("secret", ("cn.synthetic.internal", "cn.synthetic.internal")),
    ):
        with pytest.raises(ValueError):
            probe.probe_internal_v1(
                base_url="http://127.0.0.1:18082",
                token=token,
                expected_dataset_ids=datasets,
                startup_policy="strict",
                transport=lambda *args, **kwargs: pytest.fail("must not call HTTP"),
            )


def test_registry_derives_the_three_active_entitled_dataset_ids(tmp_path: Path) -> None:
    registry_path = _registry_with_active_datasets(
        tmp_path / "registry.yaml",
        {
            "cn.equity.daily",
            "cn.equity.security_master",
            "cn.market.trade_calendar",
        },
    )

    assert probe.expected_dataset_ids_from_registry(registry_path) == (
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    )


def test_main_reads_token_and_dataset_set_from_registry_without_printing_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_path = _registry_with_active_datasets(
        tmp_path / "registry.yaml",
        {"cn.synthetic.internal"},
    )
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    raw["datasets"][0]["dataset_id"] = "cn.synthetic.internal"
    raw["datasets"][0]["aliases"] = ["synthetic.internal"]
    raw["datasets"][0]["provider_bindings"][0]["entitlement_state"] = "active"
    raw["datasets"][0]["provider_bindings"][0]["activation_state"] = "active"
    raw["datasets"] = raw["datasets"][:1]
    registry_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("SHAREDSIGNALS_INTERNAL_V1_BASE_URL", "http://127.0.0.1:18082")
    monkeypatch.setenv("SHAREDSIGNALS_INTERNAL_V1_TOKEN", "environment-secret")
    monkeypatch.setenv("HOME", "/nonexistent-protected-home")
    monkeypatch.setattr(
        probe,
        "_urlopen_transport",
        _FakeTransport(
            [
                _catalog([_catalog_row("cn.synthetic.internal")]),
                _query("cn.synthetic.internal"),
            ]
        ),
    )

    code = probe.main(["--registry", str(registry_path)])

    output = capsys.readouterr().out
    assert code == 0
    assert json.loads(output)["status"] == "healthy"
    assert "environment-secret" not in output


def test_missing_registry_or_probe_token_fails_before_http_without_logging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = _FakeTransport([])
    monkeypatch.setattr(probe, "_urlopen_transport", transport)
    monkeypatch.setenv("SHAREDSIGNALS_INTERNAL_V1_TOKEN", "probe-secret")

    missing_registry = probe.main(
        ["--registry", str(tmp_path / "missing-registry.yaml")]
    )
    output = capsys.readouterr().out
    assert missing_registry == 1
    assert transport.calls == []
    assert "probe-secret" not in output

    registry_path = _registry_with_active_datasets(
        tmp_path / "registry.yaml",
        {"cn.equity.daily"},
    )
    monkeypatch.setenv("SHAREDSIGNALS_INTERNAL_V1_TOKEN", " wrong-secret ")
    wrong_token = probe.main(["--registry", str(registry_path)])
    output = capsys.readouterr().out
    assert wrong_token == 1
    assert transport.calls == []
    assert "wrong-secret" not in output

    monkeypatch.setenv("SHAREDSIGNALS_INTERNAL_V1_TOKEN", "probe-secret")
    monkeypatch.setenv("QUICKSYNC_TOKEN", "collector-secret")
    crossed_secret = probe.main(["--registry", str(registry_path)])
    output = capsys.readouterr().out
    assert crossed_secret == 1
    assert transport.calls == []
    assert "probe-secret" not in output
    assert "collector-secret" not in output


def test_systemd_units_separate_secrets_and_bind_registry_without_cross_exposure() -> (
    None
):
    root = Path(__file__).resolve().parents[1]
    unit_paths = (
        root / "deploy/systemd/sharedsignals-provider-native-collect.service",
        root / "deploy/systemd/sharedsignals-v1-probe.service",
    )
    for path in unit_paths:
        text = path.read_text(encoding="utf-8")
        assert "sharedsignals-v1-internal.service" in text
        assert (
            "EnvironmentFile=/opt/investment/releases/sharedsignals-v1/current/"
            "deploy/provider_native_internal.env"
        ) in text
        assert 'Environment="' not in text
        assert "token" not in text.casefold()
        assert "REAL_TRADING" not in text

    for unit_name, timeout in EXPECTED_PROVIDER_NATIVE_ONESHOT_TIMEOUTS.items():
        unit_text = (root / "deploy/systemd" / unit_name).read_text(encoding="utf-8")
        assert unit_text.count(f"TimeoutStartSec={timeout}") == 1
        assert "TimeoutStartSec=infinity" not in unit_text.casefold()

    collect = unit_paths[0].read_text(encoding="utf-8")
    probe_unit = unit_paths[1].read_text(encoding="utf-8")
    collector_secret = "/etc/sharedsignals/provider-native-collector.secrets"
    probe_secret = "/etc/sharedsignals/provider-native-probe.secrets"
    registry = (
        "/opt/investment/releases/sharedsignals-v1/current/config/"
        "provider_native_dataset_registry.yaml"
    )
    assert f"EnvironmentFile={collector_secret}" in collect
    assert probe_secret not in collect
    assert "provider-native-internal.secrets" not in collect
    assert f"EnvironmentFile={probe_secret}" in probe_unit
    assert collector_secret not in probe_unit
    assert "provider-native-internal.secrets" not in probe_unit
    assert f"ConditionPathExists={collector_secret}" in collect
    assert f"ConditionPathExists={probe_secret}" in probe_unit
    assert f"ConditionPathExists={registry}" in collect
    assert f"ConditionPathExists={registry}" in probe_unit
    assert "tools/run_provider_native_schedule.py --execute" in collect
    assert (
        f"tools/internal_v1_probe.py --registry {registry} --startup-policy strict"
        in probe_unit
    )
    assert (
        "/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite"
        not in collect
    )
    assert "http://127.0.0.1:18082" not in probe_unit

    timer = (
        root / "deploy/systemd/sharedsignals-provider-native-collect.timer"
    ).read_text(encoding="utf-8")
    assert "OnUnitActiveSec=15min" in timer
