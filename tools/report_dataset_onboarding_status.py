#!/usr/bin/env python3
"""Rebuild a provider-neutral onboarding status artifact from read authority.

The report is intentionally diagnostic-only: it never calls a provider and opens
the SQLite read model through the same verified shared snapshot used by queries.
An optional, redacted formal API snapshot can add the public projection layer;
without it the report refuses to call any dataset ``formal_ready``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    PROVIDER_NATIVE_DATASET_REGISTRY_PATH,
    DatasetDefinition,
    DatasetRegistry,
    load_runtime_dataset_registry,
)
from storage.receipt_projection import (  # noqa: E402
    DatasetRuntimeEvidence,
    open_verified_read_model_snapshot,
    project_dataset_runtime_evidence,
)


ARTIFACT_SCHEMA_VERSION = 1
READINESS_CLASSES = frozenset(
    {
        "formal_ready",
        "observed_isolated_only",
        "legal_empty",
        "stale",
        "failed",
        "paused",
        "locked",
        "contract_missing",
        "seed_missing",
        "unobserved",
    }
)
_API_UNAVAILABLE = "not_provided"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_now(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _api_metadata(snapshot: Mapping[str, object] | None, dataset_id: str) -> Mapping[str, object] | None:
    if snapshot is None:
        return None
    queries = snapshot.get("queries")
    if not isinstance(queries, Mapping):
        return None
    envelope = queries.get(dataset_id)
    if not isinstance(envelope, Mapping):
        return None
    metadata = envelope.get("metadata")
    return metadata if isinstance(metadata, Mapping) else None


def _binding_state(
    dataset: DatasetDefinition,
) -> tuple[str, str, str, tuple[str, ...]]:
    bindings = dataset.provider_bindings
    blockers: set[str] = set()
    if any(binding.entitlement_state == "locked" for binding in bindings):
        blockers.add("entitlement_locked")
        entitlement = "locked"
    elif all(binding.entitlement_state == "active" for binding in bindings):
        entitlement = "active"
    else:
        entitlement = "unknown"
        blockers.add("entitlement_unresolved")
    if any(binding.activation_state == "paused" for binding in bindings):
        activation = "paused"
        blockers.add("activation_paused")
    else:
        activation = "active"
    if any(binding.ingest_contract_state != "ready" for binding in bindings):
        contract_state = "missing"
        blockers.add("ingest_contract_unresolved")
        for binding in bindings:
            blockers.update(binding.ingest_contract_block_reasons)
    else:
        contract_state = "ready"
    return entitlement, activation, contract_state, tuple(sorted(blockers))


def _seed_source_ids(dataset: DatasetDefinition) -> tuple[str, ...]:
    values = {
        binding.fanout.source_dataset_id
        for binding in dataset.provider_bindings
        if binding.fanout is not None and binding.fanout.source_dataset_id is not None
    }
    return tuple(sorted(values))


def _seed_state(
    dataset: DatasetDefinition,
    evidence_by_dataset: Mapping[str, DatasetRuntimeEvidence],
) -> tuple[str, tuple[str, ...]]:
    sources = _seed_source_ids(dataset)
    if not sources:
        return "not_required", ()
    states = []
    for source_id in sources:
        evidence = evidence_by_dataset.get(source_id)
        states.append(None if evidence is None else evidence.projection.state)
    if all(state in {"success", "empty"} for state in states):
        return "ready", ()
    if any(state == "failed" for state in states):
        return "failed", ("seed_receipt_failed",)
    return "missing", ("seed_receipt_missing",)


def _api_fields(metadata: Mapping[str, object] | None) -> tuple[str, str, str, bool | None, tuple[str, ...]]:
    if metadata is None:
        return _API_UNAVAILABLE, _API_UNAVAILABLE, _API_UNAVAILABLE, None, ()
    state = metadata.get("state")
    freshness = metadata.get("freshness")
    quality = metadata.get("quality")
    lineage = metadata.get("lineage")
    reasons = metadata.get("reasons")
    freshness_state = freshness.get("state") if isinstance(freshness, Mapping) else None
    quality_state = quality.get("state") if isinstance(quality, Mapping) else None
    lineage_complete = lineage.get("complete") if isinstance(lineage, Mapping) else None
    if type(state) is not str or type(freshness_state) is not str or type(quality_state) is not str:
        return "invalid_snapshot", "invalid_snapshot", "invalid_snapshot", None, ("api_snapshot_invalid",)
    if type(lineage_complete) is not bool:
        return state, freshness_state, quality_state, None, ("api_snapshot_invalid",)
    if not isinstance(reasons, list) or any(type(reason) is not str for reason in reasons):
        return state, freshness_state, quality_state, lineage_complete, ("api_snapshot_invalid",)
    return state, freshness_state, quality_state, lineage_complete, tuple(sorted(set(reasons)))


def _readiness_class(
    *,
    entitlement: str,
    activation: str,
    contract_state: str,
    seed_state: str,
    evidence: DatasetRuntimeEvidence,
    api_state: str,
    freshness: str,
    quality: str,
    lineage_complete: bool | None,
    registry_drift: bool,
) -> str:
    if registry_drift or contract_state != "ready":
        return "contract_missing"
    if entitlement == "locked":
        return "locked"
    if activation == "paused":
        return "paused"
    if seed_state == "missing":
        return "seed_missing"
    state = evidence.projection.state
    if state == "unobserved":
        return "unobserved"
    if state == "failed" or api_state == "failed":
        return "failed"
    if state == "stale" or freshness == "stale":
        return "stale"
    if api_state == "empty" and quality == "valid" and lineage_complete is True:
        return "legal_empty"
    if (
        api_state == "ready"
        and freshness == "fresh"
        and quality == "valid"
        and lineage_complete is True
        and evidence.projection.receipt_id is not None
    ):
        return "formal_ready"
    return "observed_isolated_only"


def _next_action(readiness: str) -> str:
    return {
        "formal_ready": "maintain_registered_cadence",
        "observed_isolated_only": "capture_formal_api_projection",
        "legal_empty": "await_next_provider_window",
        "stale": "collect_fresh_partition",
        "failed": "investigate_latest_receipt",
        "paused": "complete_activation_evidence",
        "locked": "obtain_entitlement_evidence",
        "contract_missing": "complete_generic_contract",
        "seed_missing": "collect_required_seed",
        "unobserved": "run_bounded_receipt_canary",
    }[readiness]


def build_artifact(
    registry: DatasetRegistry,
    evidence_by_dataset: Mapping[str, DatasetRuntimeEvidence],
    *,
    now: datetime,
    registry_sha256: str,
    api_snapshot: Mapping[str, object] | None = None,
    api_snapshot_sha256: str | None = None,
) -> dict[str, object]:
    """Build a stable, secret-free report from already-read authority."""

    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if len(registry_sha256) != 64:
        raise ValueError("registry_sha256 must be a SHA-256 digest")
    snapshot_registry_hash = None if api_snapshot is None else api_snapshot.get("registry_sha256")
    registry_drift = snapshot_registry_hash is not None and snapshot_registry_hash != registry_sha256
    records: list[dict[str, object]] = []
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        evidence = evidence_by_dataset.get(dataset.dataset_id)
        if evidence is None:
            raise ValueError(f"missing runtime evidence for {dataset.dataset_id}")
        entitlement, activation, contract_state, binding_blockers = _binding_state(dataset)
        seed_state, seed_blockers = _seed_state(dataset, evidence_by_dataset)
        metadata = _api_metadata(api_snapshot, dataset.dataset_id)
        api_state, freshness, quality, lineage_complete, api_blockers = _api_fields(metadata)
        readiness = _readiness_class(
            entitlement=entitlement,
            activation=activation,
            contract_state=contract_state,
            seed_state=seed_state,
            evidence=evidence,
            api_state=api_state,
            freshness=freshness,
            quality=quality,
            lineage_complete=lineage_complete,
            registry_drift=registry_drift,
        )
        blocker_codes = set(binding_blockers) | set(seed_blockers) | set(api_blockers) | set(evidence.projection.reasons)
        if registry_drift:
            blocker_codes.add("registry_drift")
        records.append(
            {
                "dataset_id": dataset.dataset_id,
                "market": dataset.market,
                "data_class": dataset.data_classification,
                "cadence": dataset.cadence_class,
                "entitlement": entitlement,
                "activation": activation,
                "contract_state": contract_state,
                "seed_receipt_state": seed_state,
                "latest_receipt_state": evidence.current_receipt_status,
                "latest_receipt_observed_at": evidence.projection.observed_at,
                "latest_receipt_data_through": evidence.projection.data_through,
                "latest_receipt_id": evidence.projection.receipt_id,
                "api_projection_state": api_state,
                "freshness": freshness,
                "quality": quality,
                "lineage_complete": lineage_complete,
                "blocker_codes": sorted(blocker_codes),
                "next_action": _next_action(readiness),
                "readiness_class": readiness,
            }
        )
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "generated_at": _canonical_now(now),
        "source_hashes": {
            "registry_sha256": registry_sha256,
            "api_snapshot_sha256": api_snapshot_sha256,
        },
        "datasets": records,
    }


def _load_api_snapshot(path: Path | None) -> tuple[Mapping[str, object] | None, str | None]:
    if path is None:
        return None, None
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("api snapshot must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("api snapshot root must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def generate_artifact(
    *,
    db_path: Path,
    registry_path: Path,
    now: datetime,
    api_snapshot_path: Path | None = None,
) -> dict[str, object]:
    """Read the verified SQLite authority once and return the report object."""

    registry = load_runtime_dataset_registry()
    snapshot, snapshot_hash = _load_api_snapshot(api_snapshot_path)
    with open_verified_read_model_snapshot(db_path) as conn:
        evidence = {
            dataset.dataset_id: project_dataset_runtime_evidence(
                conn, dataset, now=now, registry=registry
            )
            for dataset in registry.datasets
        }
    return build_artifact(
        registry,
        evidence,
        now=now,
        registry_sha256=_sha256_file(registry_path),
        api_snapshot=snapshot,
        api_snapshot_sha256=snapshot_hash,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-snapshot", type=Path)
    parser.add_argument("--now", required=True, help="RFC3339 timestamp")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
    registry_path = Path(
        os.environ.get("TRADINGDATAS_REGISTRY_PATH", str(PROVIDER_NATIVE_DATASET_REGISTRY_PATH))
    )
    report = generate_artifact(
        db_path=args.db_path,
        registry_path=registry_path,
        now=now,
        api_snapshot_path=args.api_snapshot,
    )
    args.output.write_bytes(_canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
