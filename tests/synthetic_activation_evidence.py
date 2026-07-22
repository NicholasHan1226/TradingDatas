from __future__ import annotations

import hashlib
import json
from typing import Mapping

import yaml


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
    ingest_ready_api_names = {
        api_name
        for api_name in executable_api_names
        if by_api[api_name]["ingest_contract_state"] == "ready"
    }
    fresh_api_names = {*active_evidence, promoted_api_name}
    assert fresh_api_names <= ingest_ready_api_names

    results: list[dict[str, object]] = []
    summary = {
        "success": 0,
        "valid_empty": 0,
        "provider_failed_unclassified": 0,
        "field_contract_mismatch": 0,
    }
    for api_name in sorted(executable_api_names):
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

    candidate_api_names = fresh_api_names & ingest_ready_api_names
    active_api_names = {
        api_name
        for api_name in candidate_api_names
        if (
            by_api[api_name]["request_window_policy"] is None
            or set(by_api[api_name]["request_window_policy"]["formats"].values())
            <= {"yyyymmdd"}
        )
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
        "executed_api_names_sha256": _api_names_sha256(executable_api_names),
        "results_sha256": _canonical_json_sha256(
            [{key: value for key, value in result.items() if key != "result_sha256"} for result in results]
        ),
        "started_at": "2000-01-01T00:00:01+00:00",
        "finished_at": "2000-01-01T00:00:02+00:00",
        "run_clock": "2000-01-01T00:00:00+00:00",
        "scheduled_partition": "20000101",
        "scope": "gaps",
        "interface_count": len(executable_api_names),
        "coverage": {
            "planned": len(planned_api_names),
            "executable": len(executable_api_names),
            "selected": len(executable_api_names),
            "executed": len(executable_api_names),
            "blocked": len(planned_api_names - executable_api_names),
        },
        "summary": summary,
        "transport": {
            "endpoint_host": "api.quicksync.cn",
            "scheme": "https",
        },
        "concurrency": 1,
        "rate_budget": {
            "max_requests": len(executable_api_names) + 1,
            "window_seconds": 60,
            "authorizations": {
                "active_before_first": 0,
                "active_after_last": 0,
                "authorized": len(executable_api_names),
                "first_authorized_at_epoch": 1,
                "last_authorized_at_epoch": 2,
            },
        },
        "response_budget": {
            "observed_bytes": len(executable_api_names),
            "per_call_bytes": 16,
            "per_run_bytes": len(executable_api_names) + 16,
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
            "ingest_ready_count": len(ingest_ready_api_names),
            "ingest_ready_api_names_sha256": _api_names_sha256(
                ingest_ready_api_names
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
