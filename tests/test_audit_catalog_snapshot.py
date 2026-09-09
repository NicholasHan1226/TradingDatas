"""Offline scope validation must precede every catalog health summary."""

import json
from copy import deepcopy

import pytest

from tools.audit_catalog_snapshot import (
    SnapshotAuditError,
    audit_snapshot,
    load_json,
    main,
)


@pytest.fixture
def snapshot():
    return {
        "api_version": "v1", "catalog_version": "catalog-version",
        "request_id": "synthetic-request", "next_cursor": None,
        "data": [
            {"dataset_id": "cn.example", "runtime": {
                "state": "failed", "degraded": True,
                "data_through": None, "observed_at": None,
                "receipt_id": "receipt:" + "a" * 64,
                "reasons": ["provider_error"],
            }, "payload": "DO_NOT_PRINT_PRIVATE_PAYLOAD"},
            {"dataset_id": "cn.other", "runtime": {
                "state": "empty", "degraded": True,
                "data_through": None, "observed_at": None,
                "receipt_id": None, "reasons": ["provider_returned_no_rows"],
            }},
        ],
    }


IDS = ["cn.example", "cn.other"]


def test_complete_snapshot_safe_summary_keeps_empty_separate(snapshot):
    result = audit_snapshot(snapshot, IDS)
    assert result["state_counts"]["failed"] == 1
    assert result["state_counts"]["empty"] == 1
    assert result["failed_dataset_ids"] == ["cn.example"]
    assert result["recovery_verified"] is False
    assert "DO_NOT_PRINT" not in json.dumps(result)
    snapshot["data"][0]["runtime"]["state"] = "empty"
    assert audit_snapshot(snapshot, IDS)["failed_dataset_ids"] == []
    assert audit_snapshot(snapshot, IDS)["recovery_verified"] is False


@pytest.mark.parametrize("field", [
    "state", "degraded", "data_through", "observed_at", "receipt_id", "reasons",
])
def test_missing_runtime_field_rejected(snapshot, field):
    del snapshot["data"][1]["runtime"][field]
    with pytest.raises(SnapshotAuditError):
        audit_snapshot(snapshot, IDS)


@pytest.mark.parametrize("field", [
    "api_version", "catalog_version", "request_id", "data", "next_cursor",
])
def test_missing_envelope_rejected(snapshot, field):
    del snapshot[field]
    with pytest.raises(SnapshotAuditError):
        audit_snapshot(snapshot, IDS)


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(api_version="v2"),
    lambda s: s.update(data=[]),
    lambda s: s.update(data=s["data"][:1]),
    lambda s: s.update(next_cursor="truncated"),
    lambda s: s["data"].append(deepcopy(s["data"][0])),
    lambda s: s["data"][1].update(dataset_id="cn.wrong"),
    lambda s: s["data"][1].pop("runtime"),
    lambda s: s["data"][1]["runtime"].update(dataset_id="cn.wrong"),
    lambda s: s["data"][1]["runtime"].update(state="recovered"),
    lambda s: s["data"][1]["runtime"].update(degraded=1),
    lambda s: s["data"][1]["runtime"].update(reasons=[None]),
    lambda s: s["data"][1]["runtime"].update(reasons=["a", "a"]),
    lambda s: s["data"][1]["runtime"].update(reasons=["secret=value"]),
    lambda s: s["data"][1]["runtime"].update(receipt_id="private payload"),
])
def test_malformed_or_partial_catalog_rejected(snapshot, mutation):
    mutation(snapshot)
    with pytest.raises(SnapshotAuditError):
        audit_snapshot(snapshot, IDS)


@pytest.mark.parametrize("expected", [[], IDS + IDS, [" cn.example"], "cn.example"])
def test_invalid_expected_scope_rejected(snapshot, expected):
    with pytest.raises(SnapshotAuditError):
        audit_snapshot(snapshot, expected)


def test_duplicate_json_key_rejected(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text('{"data": [], "data": []}')
    with pytest.raises(SnapshotAuditError):
        load_json(path)


def test_cli_rejection_prints_no_partial_summary_or_payload(snapshot, tmp_path, monkeypatch, capsys):
    path = tmp_path / "snapshot.json"
    scope = tmp_path / "scope.json"
    snapshot["data"][1].pop("runtime")
    path.write_text(json.dumps(snapshot))
    scope.write_text(json.dumps(IDS))
    monkeypatch.setattr("sys.argv", ["audit", "--snapshot", str(path),
                                    "--expected-dataset-ids", str(scope)])
    assert main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {"audit": "rejected", "reason": "invalid_runtime"}
