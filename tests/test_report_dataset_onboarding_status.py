from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from dataset_registry import (  # noqa: E402
    DatasetRegistry,
    FanoutPolicy,
    load_runtime_dataset_registry,
)
import report_dataset_onboarding_status as report_module  # noqa: E402
from report_dataset_onboarding_status import (  # noqa: E402
    PartitionRegistration,
    TRAVERSAL_POLICY,
    _load_partition_registrations,
    _partition_fact_summary,
    _verify_partition_audit_replay,
    build_artifact,
    generate_artifact,
)
from query_contract import public_catalog_version  # noqa: E402
from storage.receipt_projection import (  # noqa: E402
    DatasetRuntimeEvidence,
    DatasetRuntimeProjection,
)


NOW = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _dataset():
    return load_runtime_dataset_registry().resolve("cn.equity.daily")


def _evidence(dataset_id: str, state: str, *, receipt: str | None = "receipt:1"):
    if state == "unobserved":
        return DatasetRuntimeEvidence(
            projection=DatasetRuntimeProjection(dataset_id, state, True, None, None, None, ()),
            current_receipt_status=None,
            current_providers=(),
            last_success_receipt_id=None,
            last_success_providers=(),
            last_success_data_through=None,
        )
    status = "empty" if state == "empty" else "failed" if state == "failed" else "success"
    return DatasetRuntimeEvidence(
        projection=DatasetRuntimeProjection(
            dataset_id, state, state != "success", "20260731", "2026-08-01T08:00:00Z", receipt, ()
        ),
        current_receipt_status=status,
        current_providers=("tushare",),
        last_success_receipt_id=receipt if status == "success" else None,
        last_success_providers=("tushare",) if status == "success" else (),
        last_success_data_through="20260731" if status == "success" else None,
        current_receipt_ids=(receipt,) if receipt else (),
        last_success_receipt_ids=(receipt,) if status == "success" and receipt else (),
    )


def _report(dataset, evidence, *, snapshot=None):
    return build_artifact(
        DatasetRegistry((dataset,)),
        {dataset.dataset_id: evidence},
        now=NOW,
        registry_sha256=HASH,
        api_snapshot=snapshot,
        api_snapshot_sha256=None if snapshot is None else "b" * 64,
    )["datasets"][0]


def _snapshot(dataset, metadata, *, registry_sha256: str = HASH, **envelope):
    registry = DatasetRegistry((dataset,))
    return {
        "api_version": "v1",
        "catalog_version": public_catalog_version(registry),
        "registry_sha256": registry_sha256,
        "queries": {
            dataset.dataset_id: {
                "api_version": "v1",
                "catalog_version": public_catalog_version(registry),
                "dataset_id": dataset.dataset_id,
                "metadata": metadata,
                **envelope,
            }
        },
    }


def _metadata(
    state: str,
    *,
    freshness: str = "fresh",
    quality: str = "valid",
    complete: bool = True,
    degraded: bool = False,
    receipt_id: str | None = "receipt:1",
    data_through: str | None = "20260731",
    observed_at: str | None = "2026-08-01T08:00:00Z",
    providers: list[str] | None = None,
):
    return {
        "state": state,
        "degraded": degraded,
        "freshness": {"state": freshness},
        "quality": {"state": quality},
        "lineage": {"complete": complete, "providers": ["tushare"] if providers is None else providers},
        "receipt_id": receipt_id,
        "data_through": data_through,
        "observed_at": observed_at,
        "reasons": [],
    }


def test_formal_ready_requires_matching_formal_query_projection() -> None:
    dataset = _dataset()
    record = _report(
        dataset,
        _evidence(dataset.dataset_id, "success"),
        snapshot=_snapshot(dataset, _metadata("ready")),
    )
    assert record["readiness_class"] == "formal_ready"
    assert record["lineage_complete"] is True
    assert record["next_action"] == "maintain_registered_cadence"


def test_missing_receipt_is_unobserved_without_formal_snapshot() -> None:
    dataset = _dataset()
    record = _report(dataset, _evidence(dataset.dataset_id, "unobserved"))
    assert record["readiness_class"] == "unobserved"
    assert record["api_projection_state"] == "not_provided"
    assert record["latest_receipt_state"] is None


def test_stale_failed_and_legal_empty_are_distinct() -> None:
    dataset = _dataset()
    stale = _report(dataset, _evidence(dataset.dataset_id, "stale"))
    failed = _report(dataset, _evidence(dataset.dataset_id, "failed"))
    empty = _report(
        dataset,
        _evidence(dataset.dataset_id, "empty"),
        snapshot=_snapshot(dataset, _metadata("empty")),
    )
    assert stale["readiness_class"] == "stale"
    assert failed["readiness_class"] == "failed"
    assert empty["readiness_class"] == "legal_empty"


def test_partial_api_projection_is_not_formal_ready() -> None:
    dataset = _dataset()
    record = _report(
        dataset,
        _evidence(dataset.dataset_id, "success"),
        snapshot=_snapshot(dataset, _metadata("partial", quality="degraded", complete=False)),
    )
    assert record["readiness_class"] == "observed_isolated_only"


def test_unbound_or_degraded_api_metadata_never_upgrades_receipt_to_formal_ready() -> None:
    dataset = _dataset()
    evidence = _evidence(dataset.dataset_id, "success")
    forged = _report(
        dataset,
        evidence,
        snapshot=_snapshot(dataset, _metadata("ready", receipt_id=None, data_through=None, observed_at=None)),
    )
    degraded = _report(
        dataset,
        evidence,
        snapshot=_snapshot(dataset, _metadata("ready", degraded=True)),
    )
    assert forged["readiness_class"] == "observed_isolated_only"
    assert degraded["readiness_class"] == "observed_isolated_only"
    assert "api_projection_unbound" in forged["blocker_codes"]
    assert "api_projection_unbound" in degraded["blocker_codes"]


def test_locked_and_paused_registry_states_are_fail_closed() -> None:
    dataset = _dataset()
    locked = replace(dataset, provider_bindings=(replace(dataset.provider_bindings[0], entitlement_state="locked", activation_state="paused"),))
    paused = replace(dataset, provider_bindings=(replace(dataset.provider_bindings[0], activation_state="paused"),))
    assert _report(locked, _evidence(locked.dataset_id, "unobserved"))["readiness_class"] == "locked"
    assert _report(paused, _evidence(paused.dataset_id, "unobserved"))["readiness_class"] == "paused"


def test_missing_required_fanout_seed_is_explicit() -> None:
    dataset = _dataset()
    source = load_runtime_dataset_registry().resolve("cn.equity.security_master")
    dependent = replace(
        dataset,
        provider_bindings=(
            replace(
                dataset.provider_bindings[0],
                fanout=FanoutPolicy(strategy="dataset_field", source_dataset_id=source.dataset_id),
            ),
        ),
    )
    artifact = build_artifact(
        DatasetRegistry((dependent, source)),
        {
            dependent.dataset_id: _evidence(dependent.dataset_id, "success"),
            source.dataset_id: _evidence(source.dataset_id, "unobserved"),
        },
        now=NOW,
        registry_sha256=HASH,
    )
    record = next(item for item in artifact["datasets"] if item["dataset_id"] == dependent.dataset_id)
    assert record["seed_receipt_state"] == "missing"
    assert record["readiness_class"] == "seed_missing"


def test_registry_drift_is_explicit_and_output_is_deterministic() -> None:
    dataset = _dataset()
    snapshot = _snapshot(dataset, _metadata("ready"), registry_sha256="c" * 64)
    first = _report(dataset, _evidence(dataset.dataset_id, "success"), snapshot=snapshot)
    second = _report(dataset, _evidence(dataset.dataset_id, "success"), snapshot=snapshot)
    assert first == second
    assert first["readiness_class"] == "contract_missing"
    assert "registry_drift" in first["blocker_codes"]


def test_snapshot_root_requires_api_catalog_and_registry_bindings() -> None:
    dataset = _dataset()
    cases = []
    missing_registry = _snapshot(dataset, _metadata("ready"))
    del missing_registry["registry_sha256"]
    cases.append(missing_registry)
    wrong_api = _snapshot(dataset, _metadata("ready"))
    wrong_api["api_version"] = "v2"
    cases.append(wrong_api)
    wrong_catalog = _snapshot(dataset, _metadata("ready"))
    wrong_catalog["catalog_version"] = "v1-wrong"
    cases.append(wrong_catalog)
    for snapshot in cases:
        record = _report(dataset, _evidence(dataset.dataset_id, "success"), snapshot=snapshot)
        assert record["readiness_class"] != "formal_ready"
        assert record["readiness_class"] != "legal_empty"


def test_query_envelope_cannot_be_rebound_to_another_dataset() -> None:
    dataset = _dataset()
    snapshot = _snapshot(dataset, _metadata("ready"))
    snapshot["queries"][dataset.dataset_id]["dataset_id"] = "cn.dataset.adj_factor"
    record = _report(dataset, _evidence(dataset.dataset_id, "success"), snapshot=snapshot)
    assert record["readiness_class"] == "observed_isolated_only"
    assert "api_snapshot_envelope_unbound" in record["blocker_codes"]


def test_cross_dataset_metadata_with_matching_receipt_cannot_upgrade() -> None:
    dataset = _dataset()
    snapshot = _snapshot(dataset, _metadata("ready"))
    snapshot["queries"][dataset.dataset_id]["catalog_version"] = "v1-other"
    record = _report(dataset, _evidence(dataset.dataset_id, "success"), snapshot=snapshot)
    assert record["readiness_class"] == "observed_isolated_only"
    assert "api_snapshot_envelope_unbound" in record["blocker_codes"]


def _partition_conn(dataset, binding, rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE provider_dataset_rows (
            dataset_id TEXT, provider TEXT, schema_major INTEGER,
            partition_value TEXT, row_key TEXT, receipt_id TEXT, payload_json TEXT
        )"""
    )
    for index, (receipt_id, payload) in enumerate(rows):
        conn.execute(
            "INSERT INTO provider_dataset_rows VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                dataset.dataset_id,
                binding.provider,
                dataset.schema_major,
                "20260731",
                f"row:{index}",
                receipt_id,
                json.dumps(payload),
            ),
        )
    return conn


def test_partition_registration_manifest_is_exact_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partitions.json"
    value = {
        "schema_version": 1,
        "partitions": [
            {
                "dataset_id": "cn.equity.daily",
                "purpose": "nonempty_control",
                "request_window": {"trade_date": "20260731"},
            }
        ],
    }
    path.write_text(json.dumps(value))
    registrations, digest = _load_partition_registrations(path)
    assert registrations == (
        PartitionRegistration(
            "cn.equity.daily", "nonempty_control", {"trade_date": "20260731"}
        ),
    )
    assert digest is not None and len(digest) == 64
    value["partitions"].append(value["partitions"][0])
    path.write_text(json.dumps(value))
    try:
        _load_partition_registrations(path)
    except ValueError as exc:
        assert str(exc) == "partition audit registrations must be unique"
    else:
        raise AssertionError("duplicate partition registration was accepted")


def test_partition_facts_reject_untrusted_receipt() -> None:
    dataset, binding = _dataset(), _dataset().provider_bindings[0]
    conn = _partition_conn(
        dataset,
        binding,
        [
            ("receipt:trusted", {"ts_code": "000001.SZ", "trade_date": "20260731"}),
            ("receipt:forged", {"ts_code": "000002.SZ", "trade_date": "20260731"}),
        ],
    )
    try:
        try:
            _partition_fact_summary(
                conn,
                dataset=dataset,
                binding=binding,
                partition_value="20260731",
                trusted_success_receipt_ids=("receipt:trusted",),
            )
        except ValueError as exc:
            assert str(exc) == "partition audit facts reference an untrusted receipt"
        else:
            raise AssertionError("untrusted partition fact receipt was accepted")
    finally:
        conn.close()


def test_partition_facts_allow_multiple_trusted_append_only_receipts() -> None:
    dataset, binding = _dataset(), _dataset().provider_bindings[0]
    conn = _partition_conn(
        dataset,
        binding,
        [
            ("receipt:one", {"ts_code": "000001.SZ", "trade_date": "20260731"}),
            ("receipt:two", {"ts_code": "000002.SZ", "trade_date": "20260731"}),
        ],
    )
    try:
        facts = _partition_fact_summary(
            conn,
            dataset=dataset,
            binding=binding,
            partition_value="20260731",
            trusted_success_receipt_ids=("receipt:one", "receipt:two"),
        )
    finally:
        conn.close()
    assert facts["fact_row_count"] == 2
    assert facts["facts_receipt_bound"] is True


def test_empty_or_failed_receipt_cannot_reuse_old_partition_facts(monkeypatch) -> None:
    dataset, binding = _dataset(), _dataset().provider_bindings[0]
    for state in ("empty", "failed"):
        evidence = replace(
            _evidence(dataset.dataset_id, state, receipt=f"receipt:{state}"),
            as_of_success_receipt_ids=("receipt:old",),
        )
        conn = _partition_conn(
            dataset,
            binding,
            [("receipt:old", {"ts_code": "000001.SZ", "trade_date": "20260731"})],
        )
        try:
            monkeypatch.setattr(
                report_module,
                "project_dataset_runtime_evidence",
                lambda *args, **kwargs: evidence,
            )
            audit = report_module.build_partition_audits(
                conn,
                DatasetRegistry((dataset,)),
                {dataset.dataset_id: evidence},
                (
                    PartitionRegistration(
                        dataset.dataset_id,
                        "legal_empty_control",
                        {"trade_date": "20260731"},
                    ),
                ),
                now=NOW,
            )[0]
        finally:
            conn.close()
        assert audit["facts_receipt_bound"] is False
        assert "partition_receipt_fact_conflict" in audit["reasons"]
        assert audit["historical_readiness"] == "observation_only"


def test_artifact_declares_read_only_traversal_policy() -> None:
    dataset = _dataset()
    artifact = build_artifact(
        DatasetRegistry((dataset,)),
        {dataset.dataset_id: _evidence(dataset.dataset_id, "success")},
        now=NOW,
        registry_sha256=HASH,
        partition_audits=[
            {"dataset_id": dataset.dataset_id, "historical_readiness": "observation_only"}
        ],
        partition_manifest_sha256="c" * 64,
    )
    assert artifact["traversal_policy"] == TRAVERSAL_POLICY
    assert artifact["source_hashes"]["partition_manifest_sha256"] == "c" * 64


def test_partition_audit_replay_requires_two_identical_traversals() -> None:
    audit = [{"dataset_id": "cn.equity.daily", "fact_row_count": 1}]
    verified = _verify_partition_audit_replay(audit, audit)
    assert verified["traversal_count"] == 2
    assert verified["semantic_replay_equal"] is True
    try:
        _verify_partition_audit_replay(
            audit, [{"dataset_id": "cn.equity.daily", "fact_row_count": 2}]
        )
    except ValueError as exc:
        assert str(exc) == "partition audit replay drift"
    else:
        raise AssertionError("partition audit replay drift was accepted")


def test_generate_artifact_uses_two_independent_partition_audit_snapshots(
    monkeypatch, tmp_path: Path
) -> None:
    dataset = _dataset()
    registry = DatasetRegistry((dataset,))
    manifest_path = tmp_path / "partitions.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "partitions": [
                    {
                        "dataset_id": dataset.dataset_id,
                        "purpose": "nonempty_control",
                        "request_window": {"trade_date": "20260731"},
                    }
                ],
            }
        )
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}")
    opened: list[object] = []

    @contextmanager
    def snapshot(_db_path: Path):
        connection = object()
        opened.append(connection)
        yield connection

    evidence = _evidence(dataset.dataset_id, "success")
    monkeypatch.setattr(report_module, "load_runtime_dataset_registry", lambda: registry)
    monkeypatch.setattr(
        report_module,
        "load_interface_runtime_report",
        lambda *args, **kwargs: {"datasets": {dataset.dataset_id: {"state": "success"}}},
    )
    monkeypatch.setattr(report_module, "open_verified_read_model_snapshot", snapshot)
    monkeypatch.setattr(
        report_module,
        "project_dataset_runtime_evidence",
        lambda *args, **kwargs: evidence,
    )
    monkeypatch.setattr(
        report_module,
        "build_partition_audits",
        lambda *args, **kwargs: [{"dataset_id": dataset.dataset_id, "fact_row_count": 1}],
    )

    artifact = generate_artifact(
        db_path=tmp_path / "read_model.sqlite",
        registry_path=registry_path,
        now=NOW,
        partition_manifest_path=manifest_path,
    )

    assert len(opened) == 2
    assert opened[0] is not opened[1]
    assert artifact["partition_audit_verification"]["traversal_count"] == 2
