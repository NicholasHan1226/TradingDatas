from __future__ import annotations

import hashlib
import json
from typing import Mapping

import yaml


_AUTOMATIC_REQUEST_WINDOW_FORMATS = frozenset(
    {"yyyymmdd", "yyyymm", "yyyy_qn", "yyyyww"}
)


def _activation_window_is_supported(contract: Mapping[str, object]) -> bool:
    """Mirror the compiler's structural preactivation eligibility rule."""

    window = contract["request_window_policy"]
    if window is None:
        return True
    assert isinstance(window, dict)
    raw_formats = window["formats"]
    assert isinstance(raw_formats, dict)
    formats = set(raw_formats.values())
    if formats <= _AUTOMATIC_REQUEST_WINDOW_FORMATS:
        return True
    fanout = contract["fanout"]
    completeness = contract["response_completeness"]
    primary_key = contract["primary_key"]
    assert isinstance(fanout, dict)
    assert isinstance(completeness, dict)
    assert isinstance(primary_key, list)
    return (
        contract["cadence_class"] == "on_demand"
        and formats == {"local_datetime_seconds"}
        and bool(primary_key)
        and fanout["strategy"] == "literal_values"
        and completeness["strategy"] == "windowed_unique_primary_key"
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _api_names_sha256(api_names: set[str]) -> str:
    return _sha256("\n".join(sorted(api_names)) + "\n")


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def build_synthetic_activation_evidence(
    contracts_document: Mapping[str, object],
    observations_document: Mapping[str, object],
    *,
    promoted_api_name: str = "adj_factor",
    cohort_api_names: set[str] | None = None,
) -> dict[str, object]:
    contracts = contracts_document["contracts"]
    active_evidence = observations_document["active_evidence"]
    assert isinstance(contracts, list)
    assert isinstance(active_evidence, dict)
    by_api = {contract["api_name"]: contract for contract in contracts}
    planned_api_names = set(by_api)
    executable_api_names = {
        api_name
        for api_name, contract in by_api.items()
        if contract["probe_state"] == "executable"
    }
    if cohort_api_names is not None and (
        not cohort_api_names or not cohort_api_names < executable_api_names
    ):
        raise ValueError("synthetic activation cohort must be executable strict subset")
    evidenced_api_names = (
        executable_api_names if cohort_api_names is None else cohort_api_names
    )
    ingest_ready_api_names = {
        api_name
        for api_name in executable_api_names
        if by_api[api_name]["ingest_contract_state"] == "ready"
    }
    formal_dependent_names = {
        api_name
        for authority in observations_document.get("dependency_seed_authorities", [])
        for api_name in authority["dependent_api_names"]
    }
    # The generic synthetic sidecar does not carry dependency-seed proof. Keep
    # those newly formalized dependents in the prior-active projection, but do
    # not invent their executable results in this unrelated fixture.
    synthetic_active_evidence = set(active_evidence) - formal_dependent_names
    fresh_api_names = {*synthetic_active_evidence, promoted_api_name}
    assert fresh_api_names <= ingest_ready_api_names

    results: list[dict[str, object]] = []
    summary = {
        "success": 0,
        "valid_empty": 0,
        "provider_failed_unclassified": 0,
        "field_contract_mismatch": 0,
    }
    for api_name in sorted(evidenced_api_names):
        state = "success" if api_name in fresh_api_names else "provider_failed_unclassified"
        source_result: dict[str, object] = {
            "api_name": api_name,
            "state": state,
            "provider_class": "synthetic_fixture",
            "row_count": 1 if state == "success" else 0,
            "response_bytes": 1,
            "response_sha256": _sha256(f"synthetic-response:{api_name}"),
            "fields": [],
            "elapsed_ms": 0,
        }
        results.append(
            {
                **source_result,
                "result_sha256": _canonical_json_sha256(source_result),
            }
        )
        summary[state] += 1

    candidate_api_names = fresh_api_names & ingest_ready_api_names & evidenced_api_names
    active_api_names = set(active_evidence) | {
        api_name
        for api_name in candidate_api_names
        if _activation_window_is_supported(by_api[api_name])
    }
    paused_api_names = planned_api_names - active_api_names
    transport_observations = yaml.safe_dump(
        dict(observations_document),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")
    evidence: dict[str, object] = {
        "schema_version": "tradingdatas.quicksync.https_probe_evidence.v1",
        "source_sha256": _sha256("synthetic-source"),
        "bindings_sha256": "",
        "promotion_stage": "preactivation_candidate",
        "release_commit": "0" * 40,
        "request_plan_sha256": _sha256("synthetic-request-plan"),
        "official_contract_sha256": _sha256("synthetic-official-contract"),
        "request_observations_sha256": _sha256("synthetic-request-observations"),
        "transport_observations_sha256": hashlib.sha256(
            transport_observations
        ).hexdigest(),
        "planned_api_names_sha256": _api_names_sha256(planned_api_names),
        "executed_api_names_sha256": _api_names_sha256(evidenced_api_names),
        "results_sha256": _canonical_json_sha256(
            [{key: value for key, value in result.items() if key != "result_sha256"} for result in results]
        ),
        "started_at": "2000-01-01T00:00:01+00:00",
        "finished_at": "2000-01-01T00:00:02+00:00",
        "run_clock": "2000-01-01T00:00:00+00:00",
        "scheduled_partition": "20000101",
        "scope": "gaps",
        "interface_count": len(evidenced_api_names),
        "coverage": {
            "planned": len(planned_api_names),
            "executable": len(executable_api_names),
            "selected": len(evidenced_api_names),
            "executed": len(evidenced_api_names),
            "blocked": len(planned_api_names - executable_api_names),
        },
        "summary": summary,
        "transport": {
            "endpoint_host": "api.quicksync.cn",
            "scheme": "https",
        },
        "concurrency": 1,
        "rate_budget": {
            "max_requests": len(evidenced_api_names) + 1,
            "window_seconds": 60,
            "authorizations": {
                "active_before_first": 0,
                "active_after_last": 0,
                "authorized": len(evidenced_api_names),
                "first_authorized_at_epoch": 1,
                "last_authorized_at_epoch": 2,
            },
        },
        "response_budget": {
            "observed_bytes": len(evidenced_api_names),
            "per_call_bytes": 16,
            "per_run_bytes": len(evidenced_api_names) + 16,
        },
        "retries": 0,
        "production_ready": False,
        "raw_data_persisted": False,
        "credential_persisted": False,
        "request_values_persisted": False,
    }
    binding_keys = (
        "source_sha256",
        "release_commit",
        "request_plan_sha256",
        "official_contract_sha256",
        "request_observations_sha256",
        "transport_observations_sha256",
        "planned_api_names_sha256",
        "executed_api_names_sha256",
        "run_clock",
        "scheduled_partition",
        "promotion_stage",
    )
    evidence["bindings_sha256"] = _canonical_json_sha256(
        {key: evidence[key] for key in binding_keys}
    )
    return {
        "version": 1,
        "provider": "tushare",
        "transport_service": "quicksync",
        "evidence": evidence,
        "seed_authorities": [],
        "plan_projection": {
            "ingest_ready_count": len(ingest_ready_api_names & evidenced_api_names),
            "ingest_ready_api_names_sha256": _api_names_sha256(
                ingest_ready_api_names & evidenced_api_names
            ),
        },
        "activation_projection": {
            "candidate_count": len(candidate_api_names),
            "candidate_api_names_sha256": _api_names_sha256(candidate_api_names),
            "active_count": len(active_api_names),
            "active_api_names_sha256": _api_names_sha256(active_api_names),
            "paused_count": len(paused_api_names),
            "paused_api_names_sha256": _api_names_sha256(paused_api_names),
        },
        "results": results,
    }


def build_synthetic_raw_probe_evidence(
    contracts_document: Mapping[str, object],
    observations_document: Mapping[str, object],
    *,
    promoted_api_name: str,
) -> dict[str, object]:
    """Return the external probe shape for one bounded activation cohort."""

    wrapped = build_synthetic_activation_evidence(
        contracts_document,
        observations_document,
        promoted_api_name=promoted_api_name,
        cohort_api_names={promoted_api_name},
    )
    evidence = wrapped["evidence"]
    results = wrapped["results"]
    seeds = wrapped["seed_authorities"]
    assert isinstance(evidence, dict)
    assert isinstance(results, list)
    assert isinstance(seeds, list)
    raw_results: list[dict[str, object]] = []
    for result in results:
        assert isinstance(result, dict)
        raw_results.append(
            {
                key: result[key]
                for key in (
                    "api_name",
                    "state",
                    "provider_class",
                    "row_count",
                    "response_bytes",
                    "response_sha256",
                    "fields",
                    "elapsed_ms",
                )
            }
            | {"response_redacted": False}
        )
    return {
        "schema_version": evidence["schema_version"],
        "production_ready": evidence["production_ready"],
        "raw_data_persisted": evidence["raw_data_persisted"],
        "credential_persisted": evidence["credential_persisted"],
        "request_values_persisted": evidence["request_values_persisted"],
        "commit": evidence["release_commit"],
        "request_plan_sha256": evidence["request_plan_sha256"],
        "official_contract_sha256": evidence["official_contract_sha256"],
        "transport_observations_sha256": evidence[
            "transport_observations_sha256"
        ],
        "request_observations_sha256": evidence["request_observations_sha256"],
        "api_names_sha256": evidence["planned_api_names_sha256"],
        "scheduled_partition": evidence["scheduled_partition"],
        "run_clock": evidence["run_clock"],
        "seed_authorities": seeds,
        "scope": evidence["scope"],
        "interface_count": evidence["interface_count"],
        "coverage": evidence["coverage"],
        "started_at": evidence["started_at"],
        "finished_at": evidence["finished_at"],
        "retries": evidence["retries"],
        "concurrency": evidence["concurrency"],
        "rate_budget": evidence["rate_budget"],
        "response_budget": evidence["response_budget"],
        "transport": evidence["transport"],
        "summary": evidence["summary"],
        "results": raw_results,
    }
