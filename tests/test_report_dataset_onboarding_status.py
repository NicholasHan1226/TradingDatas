from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
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
from report_dataset_onboarding_status import build_artifact  # noqa: E402
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
