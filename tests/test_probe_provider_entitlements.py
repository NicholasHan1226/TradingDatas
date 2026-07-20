from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from collectors.tushare.tushare_common import ProviderCallOutcome
from tools import probe_provider_entitlements as probe


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "provider_entitlement_probes.v1.yaml"
REQUEST_PROFILES = ROOT / "config" / "tushare_request_profiles.v1.yaml"
DOCUMENTS = ROOT / "config" / "tushare_document_contracts.v1.yaml"
REGISTRY = ROOT / "config" / "provider_native_dataset_registry.yaml"


def _load_policy() -> probe.ProbePolicy:
    return probe.load_probe_policy(POLICY, DOCUMENTS, REGISTRY, REQUEST_PROFILES)


def _write_policy(tmp_path: Path, mutate) -> Path:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    mutate(payload)
    target = tmp_path / "policy.yaml"
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def _write_profiles_and_binding(tmp_path: Path, mutate) -> tuple[Path, Path]:
    profiles = yaml.safe_load(REQUEST_PROFILES.read_text(encoding="utf-8"))
    mutate(profiles)
    profile_path = tmp_path / "profiles-mutated.yaml"
    profile_path.write_text(yaml.safe_dump(profiles, sort_keys=False), encoding="utf-8")
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    policy["source_request_profiles"]["sha256"] = hashlib.sha256(
        profile_path.read_bytes()
    ).hexdigest()
    policy_path = tmp_path / "policy-mutated.yaml"
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    return policy_path, profile_path


def test_policy_covers_each_official_contract_once_and_only_reviewed_specs_execute():
    policy = _load_policy()

    assert policy.contract_count == 190
    assert sum(len(values) for values in policy.classifications.values()) == 190
    assert len(set().union(*map(set, policy.classifications.values()))) == 190
    assert [spec.api_name for spec in policy.executable_probes] == [
        "bak_daily",
        "fund_adj",
        "fund_manager",
    ]
    assert all(
        spec.classification == "bounded_static_probe"
        for spec in policy.executable_probes
    )
    assert all(
        spec.params == {"limit": 1, "offset": 0} for spec in policy.executable_probes
    )
    assert policy.request_profile_count == 187
    assert policy.profile_ready_count == 153
    assert policy.parameter_resolved_count == 135
    assert len(policy.request_profiles) == 187
    assert sum(state[0] for state in policy.request_profiles.values()) == 135
    assert policy.max_selected_datasets == 5
    assert policy.request_profiles["cn.dataset.pledge_stat"] == (
        False,
        "requires_fresh_stock_anchor",
    )


def test_policy_rejects_missing_duplicate_and_unreviewed_executable_contracts(tmp_path):
    missing = _write_policy(
        tmp_path,
        lambda payload: payload["classifications"]["time_window_review_required"].pop(),
    )
    with pytest.raises(ValueError, match="exactly cover"):
        probe.load_probe_policy(missing, DOCUMENTS, REGISTRY)

    duplicate = _write_policy(
        tmp_path,
        lambda payload: payload["classifications"][
            "time_window_review_required"
        ].append("bak_daily"),
    )
    with pytest.raises(ValueError, match="sorted and unique"):
        probe.load_probe_policy(duplicate, DOCUMENTS, REGISTRY)

    def add_unreviewed(payload):
        payload["executable_probes"]["adj_factor"] = {
            "dataset_id": "cn.dataset.adj_factor",
            "classification": "time_window_review_required",
            "executable": True,
            "params": {},
            "parameter_sources": {},
            "fields": ["ts_code"],
            "max_response_bytes": 1024,
        }

    unreviewed = _write_policy(tmp_path, add_unreviewed)
    with pytest.raises(ValueError, match="not an executable classification"):
        probe.load_probe_policy(unreviewed, DOCUMENTS, REGISTRY)


def test_policy_rejects_source_hash_drift_before_any_probe(tmp_path):
    drifted = _write_policy(
        tmp_path,
        lambda payload: payload["source_documents"].update({"sha256": "0" * 64}),
    )

    with pytest.raises(ValueError, match="document snapshot SHA-256 mismatch"):
        probe.load_probe_policy(drifted, DOCUMENTS, REGISTRY)

    profile_copy = tmp_path / "profiles.yaml"
    profile_copy.write_bytes(REQUEST_PROFILES.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="request profiles SHA-256 mismatch"):
        probe.load_probe_policy(POLICY, DOCUMENTS, REGISTRY, profile_copy)


def test_policy_rejects_profile_parameter_not_declared_by_official_contract(tmp_path):
    def add_invalid_parameter(profiles):
        profiles["groups"]["literal_pagination"]["parameters"]["not_official"] = {
            "source": "literal",
            "value": 1,
        }

    policy_path, profile_path = _write_profiles_and_binding(
        tmp_path, add_invalid_parameter
    )
    with pytest.raises(ValueError, match="parameters differ"):
        probe.load_probe_policy(policy_path, DOCUMENTS, REGISTRY, profile_path)


def test_plan_is_zero_call_and_does_not_read_credentials(monkeypatch, capsys):
    monkeypatch.setattr(
        probe,
        "read_tushare_config",
        lambda: (_ for _ in ()).throw(AssertionError("credential read is forbidden")),
    )

    result = probe.main(
        [
            "--config",
            str(POLICY),
            "--documents",
            str(DOCUMENTS),
            "--registry",
            str(REGISTRY),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["mode"] == "plan"
    assert payload["provider_calls"] == 0
    assert payload["contract_count"] == 190
    assert payload["executable_probe_count"] == 3
    assert payload["runtime_executable_probe_count"] == 3
    assert payload["request_profile_count"] == 187
    assert payload["profile_ready_count"] == 153
    assert payload["parameter_resolved_profile_count"] == 135
    assert payload["ready_but_zero_call_count"] == 132
    assert payload["plan_only_profile_count"] == 52


def test_plan_cli_runs_from_repository_root_without_project_path_bootstrap():
    completed = subprocess.run(
        [sys.executable, "tools/probe_provider_entitlements.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "plan"
    assert payload["contract_count"] == 190
    assert payload["provider_calls"] == 0


def test_execute_is_one_shot_redacted_and_self_hashing():
    policy = _load_policy()
    calls: list[tuple[str, dict, str, int]] = []
    token = "SYNTHETIC-PRIVATE-TOKEN"
    outcomes = {
        "bak_daily": ProviderCallOutcome(
            state="success",
            rows=({"ts_code": "000001.SZ"},),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
        "fund_adj": ProviderCallOutcome(
            state="empty",
            rows=(),
            provider_code=0,
            error_code=None,
            error_message=None,
        ),
        "fund_manager": ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=-2001,
            error_code="permission_denied",
            error_message="permission denied",
        ),
    }

    def provider_call(
        api_name,
        received_token,
        *,
        params,
        fields,
        max_response_bytes,
        response_observer,
    ):
        assert received_token == token
        calls.append((api_name, params, fields, max_response_bytes))
        response_observer(21, hashlib.sha256(api_name.encode()).hexdigest())
        return outcomes[api_name]

    evidence = probe.execute_probe(
        policy,
        token=token,
        observed_at="2026-07-20T10:00:00Z",
        code_commit="a" * 40,
        provider_call=provider_call,
        selected_dataset_ids=tuple(
            spec.dataset_id for spec in policy.executable_probes
        ),
    )

    assert [call[0] for call in calls] == ["bak_daily", "fund_adj", "fund_manager"]
    assert len(calls) == len(set(call[0] for call in calls)) == 3
    assert [item["decision"] for item in evidence["results"]] == [
        "entitled_active",
        "entitled_active",
        "locked",
    ]
    assert all(item["response_observed_bytes"] == 21 for item in evidence["results"])
    assert all(item["response_truncated"] is False for item in evidence["results"])
    assert evidence["facts_written"] == 0
    assert evidence["ingest_receipts_written"] == 0
    assert evidence["activation_mutations"] == 0
    rendered = json.dumps(evidence, sort_keys=True)
    assert token not in rendered
    assert "TOKEN_FILE" not in rendered
    assert "permission denied" not in rendered
    self_hash = evidence["evidence_self_sha256"]
    unsigned = dict(evidence)
    del unsigned["evidence_self_sha256"]
    assert self_hash == probe.canonical_sha256(unsigned)


def test_provider_exception_or_non_allowlisted_failure_stays_unknown_without_retry():
    policy = _load_policy()
    first = policy.executable_probes[0]
    calls = 0

    def raising_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("private diagnostic must not escape")

    evidence = probe.execute_probe(
        policy,
        token="private-token",
        observed_at="2026-07-20T10:00:00Z",
        code_commit="b" * 40,
        provider_call=raising_call,
        selected_dataset_ids=(first.dataset_id,),
    )
    assert calls == 1
    assert evidence["results"][0]["decision"] == "unknown"
    assert evidence["results"][0]["reasons"] == ["provider_call_exception"]
    assert "private diagnostic" not in json.dumps(evidence)

    def wrong_code(*_args, **_kwargs):
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=-9999,
            error_code="permission_denied",
            error_message="permission denied",
        )

    evidence = probe.execute_probe(
        policy,
        token="private-token",
        observed_at="2026-07-20T10:00:00Z",
        code_commit="c" * 64,
        provider_call=wrong_code,
        selected_dataset_ids=(first.dataset_id,),
    )
    assert evidence["results"][0]["decision"] == "unknown"
    assert evidence["results"][0]["reasons"] == ["provider_failure_unclassified"]


@pytest.mark.parametrize("state", ["success", "empty"])
def test_success_or_empty_without_complete_response_digest_stays_unknown(state):
    policy = _load_policy()
    first = policy.executable_probes[0]

    def incomplete_call(
        *_args,
        response_observer,
        **_kwargs,
    ):
        response_observer(21, None)
        return ProviderCallOutcome(
            state=state,
            rows=({"ts_code": "000001.SZ"},) if state == "success" else (),
            provider_code=0,
            error_code=None,
            error_message=None,
        )

    evidence = probe.execute_probe(
        policy,
        token="private-token",
        observed_at="2026-07-20T10:00:00Z",
        code_commit="d" * 40,
        provider_call=incomplete_call,
        selected_dataset_ids=(first.dataset_id,),
    )

    assert evidence["results"][0]["decision"] == "unknown"
    assert evidence["results"][0]["reasons"] == ["response_metadata_incomplete"]


def test_resource_budget_reports_observed_prefix_not_full_response_size():
    policy = _load_policy()
    first = policy.executable_probes[0]

    def oversized_call(*_args, response_observer, max_response_bytes, **_kwargs):
        response_observer(max_response_bytes + 1, None)
        return ProviderCallOutcome(
            state="failed",
            rows=(),
            provider_code=None,
            error_code="resource_budget",
            error_message="provider response exceeded byte budget",
        )

    evidence = probe.execute_probe(
        policy,
        token="private-token",
        observed_at="2026-07-20T10:00:00Z",
        code_commit="e" * 40,
        provider_call=oversized_call,
        selected_dataset_ids=(first.dataset_id,),
    )
    item = evidence["results"][0]
    assert item["decision"] == "unknown"
    assert item["reasons"] == ["response_resource_budget"]
    assert item["response_truncated"] is True
    assert item["response_observed_bytes"] == first.max_response_bytes + 1
    assert "response_bytes" not in item


def test_selecting_non_executable_is_explicit_unknown_with_zero_calls():
    policy = _load_policy()
    calls = 0

    def provider_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("non-executable dataset must never call the provider")

    evidence = probe.execute_probe(
        policy,
        token="",
        observed_at="2026-07-20T10:00:00Z",
        code_commit="e" * 40,
        provider_call=provider_call,
        selected_dataset_ids=("cn.dataset.adj_factor",),
    )

    assert calls == evidence["provider_calls"] == 0
    assert evidence["results"][0]["decision"] == "unknown"
    assert evidence["results"][0]["reasons"] == ["profile_ready_not_runtime_executable"]
    assert evidence["results"][0]["canonical_request_sha256"] is None


def test_selecting_unknown_dataset_fails_before_provider_call():
    calls = 0

    def provider_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    with pytest.raises(ValueError, match="known policy datasets"):
        probe.execute_probe(
            _load_policy(),
            token="private-token",
            observed_at="2026-07-20T10:00:00Z",
            code_commit="f" * 40,
            provider_call=provider_call,
            selected_dataset_ids=("cn.dataset.not_real",),
        )
    assert calls == 0


def test_execute_requires_nonempty_selection_and_caps_it_at_five():
    policy = _load_policy()
    with pytest.raises(ValueError, match="explicit dataset selection"):
        probe.execute_probe(
            policy,
            token="private-token",
            observed_at="2026-07-20T10:00:00Z",
            code_commit="a" * 40,
        )
    with pytest.raises(ValueError, match="at most 5"):
        probe.execute_probe(
            policy,
            token="private-token",
            observed_at="2026-07-20T10:00:00Z",
            code_commit="b" * 40,
            selected_dataset_ids=tuple(sorted(policy.request_profiles)[:6]),
        )


def test_cli_rejects_missing_selection_before_credential_read(monkeypatch):
    monkeypatch.setattr(
        probe,
        "read_tushare_config",
        lambda: (_ for _ in ()).throw(AssertionError("credential read is forbidden")),
    )
    with pytest.raises(SystemExit) as exc_info:
        probe.main(
            [
                "--execute",
                "--code-commit",
                "a" * 40,
                "--observed-at",
                "2026-07-20T10:00:00Z",
            ]
        )
    assert exc_info.value.code == 2


def test_probe_tool_has_no_ingest_store_or_activation_writer_dependency():
    source = (ROOT / "tools" / "probe_provider_entitlements.py").read_text(
        encoding="utf-8"
    )

    assert "storage." not in source
    assert "provider_native_ingest" not in source
    assert "activation_manifest" not in source
    assert "sqlite3" not in source


def test_execute_requires_explicit_commit_and_utc_observation_time(monkeypatch):
    monkeypatch.setattr(probe, "read_tushare_config", lambda: {"token": "unused"})

    with pytest.raises(ValueError, match="code_commit"):
        probe.execute_probe(
            _load_policy(),
            token="private-token",
            observed_at="2026-07-20T10:00:00Z",
            code_commit="main",
            provider_call=lambda *_args, **_kwargs: None,
        )
    with pytest.raises(ValueError, match="observed_at"):
        probe.execute_probe(
            _load_policy(),
            token="private-token",
            observed_at="2026-07-20T18:00:00+08:00",
            code_commit="d" * 40,
            provider_call=lambda *_args, **_kwargs: None,
        )
