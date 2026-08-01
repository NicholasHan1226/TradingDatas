#!/usr/bin/env python3
"""Rebuild a provider-neutral onboarding status artifact from read authority.

The report is intentionally diagnostic-only: it never calls a provider and opens
the SQLite read model through the same verified shared snapshot used by queries.
An optional, redacted formal API snapshot can add the public projection layer;
without it the report refuses to call any dataset ``formal_ready``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset_registry import (  # noqa: E402
    PROVIDER_NATIVE_DATASET_REGISTRY_PATH,
    DatasetDefinition,
    DatasetRegistry,
    ProviderBinding,
    load_runtime_dataset_registry,
    normalize_request_window,
)
from query_contract import public_catalog_version  # noqa: E402
from storage.receipt_projection import (  # noqa: E402
    DatasetRuntimeEvidence,
    load_interface_runtime_report,
    open_verified_read_model_snapshot,
    project_dataset_runtime_evidence,
)


ARTIFACT_SCHEMA_VERSION = 1
PARTITION_AUDIT_SCHEMA_VERSION = 1
PARTITION_AUDIT_PURPOSES = frozenset(
    {"legal_empty_control", "nonempty_control", "rare_nonempty_control"}
)
TRAVERSAL_POLICY = {
    "routine_query": "receipt_bound_single_traversal",
    "escalated_verification": {
        "contexts": [
            "onboarding",
            "contract_drift",
            "incident_recovery",
            "daily_scrub",
        ],
        "mode": "independent_double_traversal",
    },
    "historical_pit_without_explicit_vintage": "observation_only",
}
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


@dataclass(frozen=True)
class PartitionRegistration:
    dataset_id: str
    purpose: str
    request_window: Mapping[str, str]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_partition_registrations(
    path: Path | None,
) -> tuple[tuple[PartitionRegistration, ...], str | None]:
    if path is None:
        return (), None
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("partition audit manifest must be JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "partitions",
    }:
        raise ValueError("partition audit manifest has invalid keys")
    if manifest.get("schema_version") != PARTITION_AUDIT_SCHEMA_VERSION:
        raise ValueError("partition audit manifest schema_version is invalid")
    values = manifest.get("partitions")
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        raise ValueError("partition audit manifest partitions are invalid")
    registrations: list[PartitionRegistration] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "dataset_id",
            "purpose",
            "request_window",
        }:
            raise ValueError("partition audit registration has invalid keys")
        dataset_id, purpose, window = (
            value["dataset_id"],
            value["purpose"],
            value["request_window"],
        )
        if type(dataset_id) is not str or not dataset_id:
            raise ValueError("partition audit dataset_id is invalid")
        if purpose not in PARTITION_AUDIT_PURPOSES:
            raise ValueError("partition audit purpose is invalid")
        if (
            not isinstance(window, dict)
            or not window
            or any(
                type(key) is not str or type(item) is not str or not key or not item
                for key, item in window.items()
            )
        ):
            raise ValueError("partition audit request_window is invalid")
        registrations.append(
            PartitionRegistration(dataset_id, purpose, dict(sorted(window.items())))
        )
    registrations.sort(
        key=lambda item: (item.dataset_id, _canonical_json(dict(item.request_window)))
    )
    identities = [
        (item.dataset_id, tuple(item.request_window.items())) for item in registrations
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("partition audit registrations must be unique")
    return tuple(registrations), hashlib.sha256(raw).hexdigest()


def _identity_tuple(
    payload: Mapping[str, object], identity_fields: Sequence[str]
) -> tuple[object, ...] | None:
    values: list[object] = []
    for field in identity_fields:
        value = payload.get(field)
        if (
            value is None
            or isinstance(value, (dict, list))
            or (type(value) is str and not value.strip())
        ):
            return None
        values.append(value)
    return tuple(values)


def _partition_fact_summary(
    conn: object,
    *,
    dataset: DatasetDefinition,
    binding: ProviderBinding,
    partition_value: str,
    trusted_success_receipt_ids: Sequence[str],
) -> dict[str, object]:
    if not dataset.primary_key:
        raise ValueError("partition audit dataset requires a declared primary_key")
    if binding.max_rows_per_attempt is None:
        raise ValueError("partition audit binding requires max_rows_per_attempt")
    rows = conn.execute(
        """SELECT receipt_id, payload_json FROM provider_dataset_rows
           WHERE dataset_id = ? AND provider = ? AND schema_major = ?
             AND partition_value = ? ORDER BY row_key""",
        (dataset.dataset_id, binding.provider, dataset.schema_major, partition_value),
    ).fetchall()
    identities: list[tuple[object, ...]] = []
    nulls = 0
    fact_receipt_ids: set[str] = set()
    for receipt_id, payload_json in rows:
        if type(receipt_id) is not str or not receipt_id:
            raise ValueError("partition audit provider receipt is invalid")
        fact_receipt_ids.add(receipt_id)
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("partition audit provider payload is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("partition audit provider payload is invalid")
        identity = _identity_tuple(payload, dataset.primary_key)
        if identity is None:
            nulls += 1
        else:
            identities.append(identity)
    duplicate_excess = sum(
        count - 1 for count in Counter(identities).values() if count > 1
    )
    trusted_ids = frozenset(trusted_success_receipt_ids)
    if not fact_receipt_ids.issubset(trusted_ids):
        raise ValueError("partition audit facts reference an untrusted receipt")
    return {
        "fact_row_count": len(rows),
        "fact_receipt_ids": sorted(fact_receipt_ids),
        "facts_receipt_bound": True,
        "identity_fields": list(dataset.primary_key),
        "identity_null_count": nulls,
        "identity_duplicate_excess": duplicate_excess,
        "at_row_cap": len(rows) >= binding.max_rows_per_attempt,
        "max_rows_per_attempt": binding.max_rows_per_attempt,
    }


def build_partition_audits(
    conn: object,
    registry: DatasetRegistry,
    evidence_by_dataset: Mapping[str, DatasetRuntimeEvidence],
    registrations: Sequence[PartitionRegistration],
    *,
    now: datetime,
) -> list[dict[str, object]]:
    audits: list[dict[str, object]] = []
    for registration in registrations:
        dataset = registry.resolve(registration.dataset_id)
        if dataset.dataset_id not in evidence_by_dataset:
            raise ValueError(f"missing runtime evidence for {dataset.dataset_id}")
        bindings = tuple(
            binding
            for binding in dataset.provider_bindings
            if binding.entitlement_state == "active"
            and binding.activation_state == "active"
            and binding.ingest_contract_state == "ready"
        )
        if not bindings:
            raise ValueError("partition audit dataset has no eligible provider binding")
        for binding in bindings:
            policy, completeness = (
                binding.request_window_policy,
                binding.response_completeness,
            )
            if (
                policy is None
                or completeness is None
                or completeness.request_partition_key is None
                or completeness.partition_field is None
            ):
                raise ValueError(
                    "partition audit binding lacks an exact partition contract"
                )
            window = normalize_request_window(policy, registration.request_window)
            partition_key = completeness.request_partition_key
            partition_value = window.get(partition_key)
            if partition_value is None:
                raise ValueError("partition audit window lacks the request partition key")
            partition_evidence = project_dataset_runtime_evidence(
                conn,
                dataset,
                now=now,
                registry=registry,
                provider_binding=binding,
                request_partition=(partition_key, partition_value),
                evidence_as_of=now,
            )
            facts = _partition_fact_summary(
                conn,
                dataset=dataset,
                binding=binding,
                partition_value=partition_value,
                trusted_success_receipt_ids=partition_evidence.as_of_success_receipt_ids,
            )
            conflict = facts["fact_row_count"] > 0 and (
                partition_evidence.current_receipt_status in {"empty", "failed"}
            )
            if conflict:
                facts["facts_receipt_bound"] = False
            reasons = sorted(
                set(partition_evidence.projection.reasons)
                | ({"partition_receipt_fact_conflict"} if conflict else set())
            )
            audits.append(
                {
                    "dataset_id": dataset.dataset_id,
                    "purpose": registration.purpose,
                    "request_window": window,
                    "provider": binding.provider,
                    "provider_api": binding.api_name,
                    "receipt_state": partition_evidence.current_receipt_status,
                    "receipt_ids": list(partition_evidence.current_receipt_ids),
                    "projection_state": partition_evidence.projection.state,
                    "degraded": partition_evidence.projection.degraded,
                    "reasons": reasons,
                    "empty_receipt": partition_evidence.current_receipt_status == "empty",
                    "providers": list(partition_evidence.current_providers),
                    "historical_readiness": "observation_only",
                    **facts,
                }
            )
    return audits


def _verify_partition_audit_replay(
    first: Sequence[Mapping[str, object]], replay: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    first_digest = hashlib.sha256(_canonical_json(list(first))).hexdigest()
    replay_digest = hashlib.sha256(_canonical_json(list(replay))).hexdigest()
    if first_digest != replay_digest:
        raise ValueError("partition audit replay drift")
    return {
        "context": "onboarding",
        "traversal_count": 2,
        "first_digest": first_digest,
        "replay_digest": replay_digest,
        "semantic_replay_equal": True,
    }


def _canonical_now(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot_root_state(
    snapshot: Mapping[str, object] | None,
    *,
    registry: DatasetRegistry,
    registry_sha256: str,
) -> tuple[bool, bool, tuple[str, ...]]:
    if snapshot is None:
        return False, False, ()
    blockers: set[str] = set()
    if snapshot.get("api_version") != "v1":
        blockers.add("api_snapshot_api_version_invalid")
    if snapshot.get("catalog_version") != public_catalog_version(registry):
        blockers.add("api_snapshot_catalog_version_invalid")
    registry_drift = snapshot.get("registry_sha256") != registry_sha256
    if registry_drift:
        blockers.add("registry_drift")
    return not blockers, registry_drift, tuple(sorted(blockers))


def _api_metadata(
    snapshot: Mapping[str, object] | None,
    dataset_id: str,
    *,
    root_valid: bool,
) -> tuple[Mapping[str, object] | None, tuple[str, ...]]:
    if snapshot is None or not root_valid:
        return None, ()
    queries = snapshot.get("queries")
    if not isinstance(queries, Mapping):
        return None, ("api_snapshot_invalid",)
    envelope = queries.get(dataset_id)
    if not isinstance(envelope, Mapping):
        return None, ()
    if (
        envelope.get("api_version") != "v1"
        or envelope.get("catalog_version") != snapshot.get("catalog_version")
        or envelope.get("dataset_id") != dataset_id
    ):
        return None, ("api_snapshot_envelope_unbound",)
    request_id = envelope.get("request_id")
    if request_id is not None and (
        type(request_id) is not str or not request_id or request_id != request_id.strip()
    ):
        return None, ("api_snapshot_envelope_unbound",)
    metadata = envelope.get("metadata")
    if not isinstance(metadata, Mapping):
        return None, ("api_snapshot_invalid",)
    return metadata, ()


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


def _api_fields(
    metadata: Mapping[str, object] | None,
    evidence: DatasetRuntimeEvidence,
) -> tuple[str, str, str, bool | None, bool, tuple[str, ...]]:
    if metadata is None:
        return _API_UNAVAILABLE, _API_UNAVAILABLE, _API_UNAVAILABLE, None, False, ()
    state = metadata.get("state")
    freshness = metadata.get("freshness")
    quality = metadata.get("quality")
    lineage = metadata.get("lineage")
    reasons = metadata.get("reasons")
    degraded = metadata.get("degraded")
    receipt_id = metadata.get("receipt_id")
    data_through = metadata.get("data_through")
    observed_at = metadata.get("observed_at")
    freshness_state = freshness.get("state") if isinstance(freshness, Mapping) else None
    quality_state = quality.get("state") if isinstance(quality, Mapping) else None
    lineage_complete = lineage.get("complete") if isinstance(lineage, Mapping) else None
    if type(state) is not str or type(freshness_state) is not str or type(quality_state) is not str:
        return "invalid_snapshot", "invalid_snapshot", "invalid_snapshot", None, False, ("api_snapshot_invalid",)
    if type(lineage_complete) is not bool:
        return state, freshness_state, quality_state, None, False, ("api_snapshot_invalid",)
    if not isinstance(reasons, list) or any(type(reason) is not str for reason in reasons):
        return state, freshness_state, quality_state, lineage_complete, False, ("api_snapshot_invalid",)
    providers = lineage.get("providers") if isinstance(lineage, Mapping) else None
    binding_complete = (
        degraded is False
        and type(receipt_id) is str
        and receipt_id == evidence.projection.receipt_id
        and data_through == evidence.projection.data_through
        and observed_at == evidence.projection.observed_at
        and isinstance(providers, list)
        and tuple(providers) == evidence.current_providers
    )
    blockers = set(reasons)
    if not binding_complete:
        blockers.add("api_projection_unbound")
    return (
        state,
        freshness_state,
        quality_state,
        lineage_complete,
        binding_complete,
        tuple(sorted(blockers)),
    )


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
    api_binding_complete: bool,
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
    if (
        api_state == "empty"
        and quality == "valid"
        and lineage_complete is True
        and api_binding_complete
    ):
        return "legal_empty"
    if (
        api_state == "ready"
        and freshness == "fresh"
        and quality == "valid"
        and lineage_complete is True
        and api_binding_complete
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
    partition_audits: Sequence[Mapping[str, object]] = (),
    partition_manifest_sha256: str | None = None,
    partition_audit_verification: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a stable, secret-free report from already-read authority."""

    if not isinstance(registry, DatasetRegistry):
        raise TypeError("registry must be DatasetRegistry")
    if len(registry_sha256) != 64:
        raise ValueError("registry_sha256 must be a SHA-256 digest")
    root_valid, registry_drift, root_blockers = _snapshot_root_state(
        api_snapshot, registry=registry, registry_sha256=registry_sha256
    )
    records: list[dict[str, object]] = []
    for dataset in sorted(registry.datasets, key=lambda item: item.dataset_id):
        evidence = evidence_by_dataset.get(dataset.dataset_id)
        if evidence is None:
            raise ValueError(f"missing runtime evidence for {dataset.dataset_id}")
        entitlement, activation, contract_state, binding_blockers = _binding_state(dataset)
        seed_state, seed_blockers = _seed_state(dataset, evidence_by_dataset)
        metadata, envelope_blockers = _api_metadata(
            api_snapshot, dataset.dataset_id, root_valid=root_valid
        )
        (
            api_state,
            freshness,
            quality,
            lineage_complete,
            api_binding_complete,
            api_blockers,
        ) = _api_fields(metadata, evidence)
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
            api_binding_complete=api_binding_complete,
            registry_drift=registry_drift,
        )
        blocker_codes = (
            set(binding_blockers)
            | set(seed_blockers)
            | set(root_blockers)
            | set(envelope_blockers)
            | set(api_blockers)
            | set(evidence.projection.reasons)
        )
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
            "partition_manifest_sha256": partition_manifest_sha256,
        },
        "traversal_policy": TRAVERSAL_POLICY,
        "datasets": records,
        "pre_registered_partitions": list(partition_audits),
        "partition_audit_verification": partition_audit_verification,
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
    partition_manifest_path: Path | None = None,
) -> dict[str, object]:
    """Build a report and double-traverse registered partitions from read authority."""

    registry = load_runtime_dataset_registry()
    snapshot, snapshot_hash = _load_api_snapshot(api_snapshot_path)
    registrations, partition_manifest_hash = _load_partition_registrations(
        partition_manifest_path
    )
    runtime_report = load_interface_runtime_report(db_path, registry, now=now)
    runtime_rows = runtime_report.get("datasets")
    if not isinstance(runtime_rows, Mapping):
        raise ValueError("runtime report datasets are invalid")
    with open_verified_read_model_snapshot(db_path) as conn:
        evidence = {
            dataset.dataset_id: project_dataset_runtime_evidence(
                conn, dataset, now=now, registry=registry
            )
            for dataset in registry.datasets
        }
        partition_audits = build_partition_audits(
            conn, registry, evidence, registrations, now=now
        )
    partition_audit_verification = None
    if registrations:
        with open_verified_read_model_snapshot(db_path) as conn:
            replay_evidence = {
                dataset.dataset_id: project_dataset_runtime_evidence(
                    conn, dataset, now=now, registry=registry
                )
                for dataset in registry.datasets
            }
            replay_audits = build_partition_audits(
                conn, registry, replay_evidence, registrations, now=now
            )
        partition_audit_verification = _verify_partition_audit_replay(
            partition_audits, replay_audits
        )
    for dataset_id, item in evidence.items():
        projection = runtime_rows.get(dataset_id)
        if not isinstance(projection, Mapping) or projection.get("state") != item.projection.state:
            raise ValueError("runtime projection drift")
    return build_artifact(
        registry,
        evidence,
        now=now,
        registry_sha256=_sha256_file(registry_path),
        api_snapshot=snapshot,
        api_snapshot_sha256=snapshot_hash,
        partition_audits=partition_audits,
        partition_manifest_sha256=partition_manifest_hash,
        partition_audit_verification=partition_audit_verification,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-snapshot", type=Path)
    parser.add_argument("--partition-manifest", type=Path)
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
        partition_manifest_path=args.partition_manifest,
    )
    args.output.write_bytes(_canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
