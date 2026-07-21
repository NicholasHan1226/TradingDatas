from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest
import yaml

from collectors.tushare.tushare_common import ProviderCallOutcome
from tools import probe_quicksync_interfaces as probe


COMMIT = "a" * 40
REQUEST_SHA = "b" * 64
OFFICIAL_SHA = "c" * 64
RESPONSE_SHA = "d" * 64
TRANSPORT_SHA = "e" * 64
RUN_CLOCK = "2026-07-21T10:30:00+00:00"
SCHEDULED_PARTITION = "20260718"


def _plan_document(
    *, gap_count: int = 2, interface_count: int = 190
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for index in range(interface_count):
        labels = ["all"]
        if index < gap_count:
            labels.append("gaps")
        entries.append(
            {
                "api_name": f"api_{index:03d}",
                "scope_labels": labels,
                "probe_state": "executable",
                "probe_block_reasons": [],
                "ingest_contract_state": "ready",
                "ingest_contract_block_reasons": [],
                "params": {"trade_date": "20260720", "offset": index},
                "fields": ["code", "value"],
            }
        )
    api_names_sha256 = hashlib.sha256(
        ("\n".join(item["api_name"] for item in entries) + "\n").encode()
    ).hexdigest()
    return {
        "schema_version": "tradingdatas.quicksync.https_probe_plan.v1",
        "production_ready": False,
        "provenance": {
            "expected_commit": COMMIT,
            "official_contract_sha256": OFFICIAL_SHA,
            "transport_observations_sha256": TRANSPORT_SHA,
            "request_observations_sha256": REQUEST_SHA,
            "api_names_sha256": api_names_sha256,
            "scheduled_partition": SCHEDULED_PARTITION,
            "run_clock": RUN_CLOCK,
            "seed_authorities": [],
        },
        "counts": {
            "planned": interface_count,
            "executable": interface_count,
            "blocked": 0,
            "ingest_contract_ready": interface_count,
            "ingest_contract_blocked": 0,
        },
        "entries": entries,
    }


def _sync_counts(document: dict[str, object]) -> None:
    entries = document["entries"]
    assert isinstance(entries, list)
    document["counts"] = {
        "planned": len(entries),
        "executable": sum(
            entry.get("probe_state") == "executable"
            for entry in entries
            if isinstance(entry, dict)
        ),
        "blocked": sum(
            entry.get("probe_state") == "blocked"
            for entry in entries
            if isinstance(entry, dict)
        ),
        "ingest_contract_ready": sum(
            entry.get("ingest_contract_state") == "ready"
            for entry in entries
            if isinstance(entry, dict)
        ),
        "ingest_contract_blocked": sum(
            entry.get("ingest_contract_state") == "blocked"
            for entry in entries
            if isinstance(entry, dict)
        ),
    }


def _write_plan(tmp_path: Path, document: dict[str, object] | None = None) -> Path:
    path = tmp_path / "request-plan.yaml"
    path.write_text(
        yaml.safe_dump(
            _plan_document() if document is None else document,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _bind_authority_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    bound = _plan_document() if document is None else document
    entries = bound["entries"]
    assert isinstance(entries, list)
    source_path = tmp_path / "tushare_request_observations.v1.yaml"
    source_path.write_text(
        "schema_version: test-request-observations.v1\n", encoding="utf-8"
    )
    official_path = tmp_path / "tushare_document_contracts.v1.yaml"
    official_path.write_text(
        yaml.safe_dump(
            {
                "contracts": [
                    {"api_name": entry["api_name"]}
                    for entry in entries
                    if isinstance(entry, dict)
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    provenance = bound["provenance"]
    assert isinstance(provenance, dict)
    provenance["request_observations_sha256"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    provenance["official_contract_sha256"] = hashlib.sha256(
        official_path.read_bytes()
    ).hexdigest()
    transport_path = tmp_path / "quicksync_interface_observations.v1.yaml"
    transport_path.write_text(
        "schema_version: test-transport-observations.v1\n", encoding="utf-8"
    )
    provenance["transport_observations_sha256"] = hashlib.sha256(
        transport_path.read_bytes()
    ).hexdigest()
    monkeypatch.setattr(probe, "REQUEST_OBSERVATIONS_PATH", source_path)
    monkeypatch.setattr(probe, "OFFICIAL_CONTRACTS_PATH", official_path)
    monkeypatch.setattr(probe, "TRANSPORT_OBSERVATIONS_PATH", transport_path)
    return bound, source_path, official_path


def _success_outcome(
    *,
    rows: tuple[dict[str, object], ...] = ({"code": "000001", "value": 1},),
) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="success",
        rows=rows,
        provider_code=0,
        error_code=None,
        error_message=None,
    )


def _failed_outcome(
    provider_code: int,
    *,
    error_code: str = "provider_error",
    error_message: str = "provider request failed",
) -> ProviderCallOutcome:
    return ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=provider_code,
        error_code=error_code,
        error_message=error_message,
    )


def _call_with(
    outcomes: dict[str, ProviderCallOutcome] | None = None,
    *,
    response_bytes: int = 128,
    calls: list[dict[str, object]] | None = None,
):
    configured = outcomes or {}

    def call(
        api_name: str,
        token: str,
        *,
        params: dict[str, object],
        fields: str,
        max_response_bytes: int,
        response_observer,
    ) -> ProviderCallOutcome:
        if calls is not None:
            calls.append(
                {
                    "api_name": api_name,
                    "token": token,
                    "params": params,
                    "fields": fields,
                    "max_response_bytes": max_response_bytes,
                }
            )
        response_observer(response_bytes, RESPONSE_SHA)
        return configured.get(api_name, _success_outcome())

    return call


def _execute_probe(plan: probe.ProbePlan, **kwargs):
    authorizations: list[probe.RequestStartReservation] = []

    def authorize_request_start() -> probe.RequestStartReservation:
        active_before = len(authorizations)
        authorization = probe.RequestStartReservation(
            reserved_at_epoch=1000.0,
            reserved=1,
            active_before=active_before,
            active_after=active_before + 1,
        )
        authorizations.append(authorization)
        return authorization

    return probe.execute_probe(
        plan,
        transport_scheme="https",
        endpoint_host="api.quicksync.cn",
        authorize_request_start=authorize_request_start,
        **kwargs,
    )


def test_absolute_script_entrypoint_bootstraps_repository_imports(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(Path(probe.__file__).resolve()), "--help"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout


def test_symlinked_script_entrypoint_preserves_release_identity_gate(
    tmp_path: Path,
) -> None:
    alias = tmp_path / "current"
    alias.symlink_to(
        Path(probe.__file__).resolve().parents[1], target_is_directory=True
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    script = """
import runpy
import sys

module = runpy.run_path(sys.argv[1], run_name="probe_alias")
try:
    module["_current_commit"]()
except module["ProbeValidationError"] as exc:
    if "may not traverse a symlink" in str(exc):
        raise SystemExit(0)
    raise
raise SystemExit(3)
"""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(alias / "tools/probe_quicksync_interfaces.py"),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_plan_accepts_current_190_unique_sorted_entries_and_matching_api_hash(
    tmp_path: Path,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))

    assert len(plan.entries) == 190
    assert len(plan.select("all")) == 190
    assert [entry.api_name for entry in plan.select("gaps")] == [
        "api_000",
        "api_001",
    ]
    assert plan.expected_commit == COMMIT
    assert plan.request_observations_sha256 == REQUEST_SHA
    assert plan.transport_observations_sha256 == TRANSPORT_SHA
    assert plan.official_contract_sha256 == OFFICIAL_SHA

    duplicate = _plan_document()
    duplicate["entries"][1]["api_name"] = "api_000"  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, duplicate))

    wrong_hash = _plan_document()
    wrong_hash["provenance"]["api_names_sha256"] = "f" * 64  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, wrong_hash))


def test_plan_count_is_bounded_but_not_hard_coded_to_190(tmp_path: Path) -> None:
    expanded = probe.load_probe_plan(
        _write_plan(tmp_path, _plan_document(interface_count=224))
    )
    assert len(expanded.entries) == 224
    assert expanded.counts["planned"] == 224

    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(
            _write_plan(tmp_path, _plan_document(gap_count=0, interface_count=0))
        )
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(
            _write_plan(tmp_path, _plan_document(interface_count=513))
        )


def test_plan_accepts_compiler_provenance_and_rejects_old_provenance(
    tmp_path: Path,
) -> None:
    document = _plan_document()
    document["provenance"]["seed_authorities"] = [  # type: ignore[index]
        {
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "receipt_id": "receipt-stock-basic-20260718",
            "data_through": "20260718",
            "schema_version": "1.0.0",
        }
    ]
    plan = probe.load_probe_plan(_write_plan(tmp_path, document))

    assert plan.scheduled_partition == SCHEDULED_PARTITION
    assert plan.run_clock == RUN_CLOCK
    assert [dict(item) for item in plan.seed_authorities] == [
        {
            "dataset_id": "cn.equity.security_master",
            "field": "ts_code",
            "receipt_id": "receipt-stock-basic-20260718",
            "data_through": "20260718",
            "schema_version": "1.0.0",
        }
    ]

    old = _plan_document()
    provenance = old["provenance"]
    assert isinstance(provenance, dict)
    provenance["source_request_observations_sha256"] = provenance.pop(
        "request_observations_sha256"
    )
    provenance["api_set_sha256"] = provenance.pop("api_names_sha256")
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, old))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda provenance: provenance.update(scheduled_partition="20260230"),
        lambda provenance: provenance.update(run_clock="2026-07-21T10:30:00"),
        lambda provenance: provenance.update(
            seed_authorities=[
                {
                    "dataset_id": "cn.equity.security_master",
                    "field": "ts_code",
                    "receipt_id": "receipt-safe",
                    "data_through": "20260718",
                    "schema_version": "1.0.0",
                    "value": "600000.SH",
                }
            ]
        ),
        lambda provenance: provenance.update(
            seed_authorities=[
                {
                    "dataset_id": "cn.equity.security_master",
                    "field": "ts_code",
                    "receipt_id": "bearer-secret",
                    "data_through": "20260718",
                    "schema_version": "1.0.0",
                }
            ]
        ),
    ],
)
def test_plan_rejects_unsafe_compiler_provenance(
    tmp_path: Path,
    mutation,
) -> None:
    document = _plan_document()
    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    mutation(provenance)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))


def test_plan_rejects_unsorted_or_duplicate_seed_authorities(tmp_path: Path) -> None:
    first = {
        "dataset_id": "cn.equity.security_master",
        "field": "ts_code",
        "receipt_id": "receipt-one",
        "data_through": "20260718",
        "schema_version": "1.0.0",
    }
    second = {
        "dataset_id": "cn.dataset.trade_calendar",
        "field": "cal_date",
        "receipt_id": "receipt-two",
        "data_through": "20260718",
        "schema_version": "1.0.0",
    }
    unsorted = _plan_document()
    unsorted["provenance"]["seed_authorities"] = [first, second]  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, unsorted))

    duplicate = _plan_document()
    duplicate["provenance"]["seed_authorities"] = [first, dict(first)]  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, duplicate))


def test_plan_separates_probe_and_ingest_contract_without_sending_blocked(
    tmp_path: Path,
) -> None:
    document = _plan_document(gap_count=3)
    blocked = document["entries"][0]  # type: ignore[index]
    blocked["probe_state"] = "blocked"
    blocked["probe_block_reasons"] = ["required_parameter_unresolved"]
    blocked["ingest_contract_state"] = "blocked"
    blocked["ingest_contract_block_reasons"] = [
        "response_completeness_unresolved_at_observed_limit"
    ]
    blocked["params"] = {}
    ingest_blocked_only = document["entries"][1]  # type: ignore[index]
    ingest_blocked_only["ingest_contract_state"] = "blocked"
    ingest_blocked_only["ingest_contract_block_reasons"] = [
        "response_completeness_unresolved_at_observed_limit"
    ]
    _sync_counts(document)

    plan = probe.load_probe_plan(_write_plan(tmp_path, document))

    assert len(plan.planned("all")) == 190
    assert len(plan.blocked("all")) == 1
    assert len(plan.select("all")) == 189
    assert [entry.api_name for entry in plan.select("gaps")] == [
        "api_001",
        "api_002",
    ]
    assert plan.select("gaps")[0].ingest_contract_state == "blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("probe_state", "unknown"),
        ("probe_block_reasons", ["unknown_reason"]),
        ("ingest_contract_state", "unknown"),
        ("ingest_contract_block_reasons", ["unknown_reason"]),
    ],
)
def test_plan_rejects_invalid_probe_or_ingest_contract(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    document = _plan_document()
    document["entries"][0][field] = value  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))

    blocked_with_params = _plan_document()
    blocked_with_params["entries"][0].update(  # type: ignore[index]
        {
            "probe_state": "blocked",
            "probe_block_reasons": ["required_parameter_unresolved"],
        }
    )
    _sync_counts(blocked_with_params)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, blocked_with_params))


def test_plan_recomputes_and_rejects_untrusted_top_level_counts(
    tmp_path: Path,
) -> None:
    document = _plan_document()
    document["counts"]["executable"] = 189  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))

    document = _plan_document()
    document["counts"]["planned"] = True  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))

    document = _plan_document()
    document["counts"]["unexpected"] = 0  # type: ignore[index]
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update(production_ready=True),
        lambda document: document["entries"][0].update(unknown="value"),
        lambda document: document["entries"][0].update(
            scope_labels=["all", "unexpected"]
        ),
        lambda document: document["entries"][0].update(activation_state="active"),
        lambda document: document["entries"][0].update(
            params={"access_token": "must-not-be-accepted"}
        ),
        lambda document: document["entries"][0].update(fields=["code", "code"]),
    ],
)
def test_plan_schema_is_strict_and_rejects_credential_shaped_parameters(
    tmp_path: Path,
    mutation,
) -> None:
    document = _plan_document()
    mutation(document)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(_write_plan(tmp_path, document))


def test_plan_rejects_symlink_wrong_mode_and_linked_file(tmp_path: Path) -> None:
    path = _write_plan(tmp_path)
    path.chmod(0o644)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(path)

    path.chmod(0o600)
    linked = tmp_path / "linked-plan.yaml"
    os.link(path, linked)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(path)
    linked.unlink()

    symlink = tmp_path / "plan-link.yaml"
    symlink.symlink_to(path)
    with pytest.raises(probe.ProbeValidationError):
        probe.load_probe_plan(symlink)


def test_default_main_is_plan_only_and_never_reads_credentials_or_calls_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: pytest.fail("plan mode read credentials"),
    )
    monkeypatch.setattr(
        probe,
        "tushare_rows_outcome",
        lambda *args, **kwargs: pytest.fail("plan mode called provider"),
    )

    assert probe.main(["--request-plan", str(path), "--scope", "all"]) == 0
    assert capsys.readouterr() == ("", "")


def test_plan_binding_reads_actual_authority_bytes_and_official_api_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, source_path, official_path = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)

    assert probe.main(["--request-plan", str(path)]) == 0

    source_path.write_text("schema_version: changed\n", encoding="utf-8")
    assert probe.main(["--request-plan", str(path)]) == 2

    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    probe.TRANSPORT_OBSERVATIONS_PATH.write_text(
        "schema_version: changed\n", encoding="utf-8"
    )
    assert probe.main(["--request-plan", str(path)]) == 2

    document, _, official_path = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    official = yaml.safe_load(official_path.read_text(encoding="utf-8"))
    official["contracts"][0]["api_name"] = "different_api"
    official_path.write_text(yaml.safe_dump(official), encoding="utf-8")
    document["provenance"]["official_contract_sha256"] = hashlib.sha256(  # type: ignore[index]
        official_path.read_bytes()
    ).hexdigest()
    path = _write_plan(tmp_path, document)
    assert probe.main(["--request-plan", str(path)]) == 2


def test_default_budget_path_is_fixed_persistent_runtime_path() -> None:
    assert probe.DEFAULT_LOCK_PATH == Path(
        "/opt/investment-data/tradingdatas/evidence/.quicksync-interface-probe.lock"
    )
    assert "lock" not in vars(probe.parse_args(["--request-plan", "/tmp/plan"]))


def test_release_commit_identity_uses_strict_immutable_directory_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = tmp_path / "opt" / "investment" / "releases" / "tradingdatas"
    release = releases / COMMIT
    release.mkdir(parents=True)
    release.chmod(0o555)
    monkeypatch.setattr(probe, "IMMUTABLE_RELEASES_ROOT", releases)
    monkeypatch.setattr(probe, "IMMUTABLE_RELEASE_OWNER_UID", os.geteuid())
    monkeypatch.setattr(probe, "ENTRY_ROOT", release)
    monkeypatch.setattr(probe, "ROOT", release)
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("immutable release consulted git"),
    )

    assert probe._current_commit() == COMMIT

    release.chmod(0o755)
    (release / ".git").mkdir()
    release.chmod(0o555)
    with pytest.raises(probe.ProbeValidationError):
        probe._current_commit()
    release.chmod(0o755)
    (release / ".git").rmdir()
    release.chmod(0o555)

    release.chmod(0o755)
    with pytest.raises(probe.ProbeValidationError):
        probe._current_commit()
    release.chmod(0o555)

    alias = tmp_path / "release-alias"
    alias.symlink_to(release, target_is_directory=True)
    monkeypatch.setattr(probe, "ENTRY_ROOT", alias)
    monkeypatch.setattr(probe, "ROOT", release)
    with pytest.raises(probe.ProbeValidationError):
        probe._current_commit()

    noncanonical = releases / ("f" * 39)
    noncanonical.mkdir()
    noncanonical.chmod(0o555)
    monkeypatch.setattr(probe, "ENTRY_ROOT", noncanonical)
    monkeypatch.setattr(probe, "ROOT", noncanonical)
    with pytest.raises(probe.ProbeValidationError):
        probe._current_commit()


def test_release_symlink_entry_fails_before_lock_config_provider_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = tmp_path / "opt" / "investment" / "releases" / "tradingdatas"
    release = releases / COMMIT
    release.mkdir(parents=True)
    release.chmod(0o555)
    alias = tmp_path / "current"
    alias.symlink_to(release, target_is_directory=True)
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    lock_path = tmp_path / "probe.lock"
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(probe, "IMMUTABLE_RELEASES_ROOT", releases)
    monkeypatch.setattr(probe, "IMMUTABLE_RELEASE_OWNER_UID", os.geteuid())
    monkeypatch.setattr(probe, "ENTRY_ROOT", alias)
    monkeypatch.setattr(probe, "ROOT", release)
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", lock_path)
    authority_reads: list[bool] = []
    monkeypatch.setattr(
        probe,
        "validate_authority_sources",
        lambda plan: authority_reads.append(True),
    )
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: pytest.fail("release alias read provider config"),
    )
    monkeypatch.setattr(
        probe,
        "tushare_rows_outcome",
        lambda *args, **kwargs: pytest.fail("release alias called provider"),
    )

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "all",
                "--output",
                str(output),
                "--expected-plan-sha256",
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
        )
        == 2
    )
    assert authority_reads == []
    assert not lock_path.exists()
    assert not output.exists()


def test_missing_request_observations_fails_closed_before_any_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, source_path, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    source_path.unlink()
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(
        probe,
        "tushare_rows_outcome",
        lambda *args, **kwargs: pytest.fail("provider called without authority"),
    )

    assert probe.main(["--request-plan", str(path), "--execute"]) == 2


def test_authority_source_symlink_is_rejected_even_when_bytes_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, source_path, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    target = tmp_path / "source-target.yaml"
    source_path.rename(target)
    source_path.symlink_to(target)
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)

    assert probe.main(["--request-plan", str(path)]) == 2


def test_execute_requires_explicit_output_and_matching_frozen_plan_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: {"api_url": "https://api.quicksync.cn", "token": "test-token"},
    )
    monkeypatch.setattr(probe, "tushare_rows_outcome", _call_with())
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", tmp_path / "probe.lock")

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "gaps",
            ]
        )
        == 2
    )
    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "gaps",
                "--output",
                str(tmp_path / "evidence.json"),
                "--expected-plan-sha256",
                "0" * 64,
            ]
        )
        == 2
    )
    assert not (tmp_path / "evidence.json").exists()

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "gaps",
                "--output",
                str(tmp_path / "evidence.json"),
                "--expected-plan-sha256",
                plan_hash,
            ]
        )
        == 0
    )


def test_execute_calls_each_selected_interface_once_with_resolved_plan_only(
    tmp_path: Path,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))
    calls: list[dict[str, object]] = []
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=2,
        call=_call_with(calls=calls),
    )

    assert [item["api_name"] for item in calls] == ["api_000", "api_001"]
    assert all(item["token"] == "private-token" for item in calls)
    assert calls[0]["params"] == {"trade_date": "20260720", "offset": 0}
    assert calls[0]["fields"] == "code,value"
    assert all(item["max_response_bytes"] <= 2 * 1024 * 1024 for item in calls)
    assert evidence["interface_count"] == 2
    assert evidence["retries"] == 0
    assert evidence["production_ready"] is False
    assert evidence["transport_observations_sha256"] == TRANSPORT_SHA
    assert evidence["request_observations_sha256"] == REQUEST_SHA
    assert evidence["scheduled_partition"] == SCHEDULED_PARTITION
    assert evidence["run_clock"] == RUN_CLOCK
    assert evidence["seed_authorities"] == []
    assert evidence["transport"] == {
        "endpoint_host": "api.quicksync.cn",
        "scheme": "https",
    }
    assert evidence["coverage"] == {
        "blocked": 0,
        "executable": 2,
        "executed": 2,
        "planned": 2,
        "selected": 2,
    }


def test_all_scope_with_blocked_entry_fails_before_lock_config_or_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _plan_document()
    document["entries"][0].update(  # type: ignore[index]
        {
            "probe_state": "blocked",
            "probe_block_reasons": ["required_parameter_unresolved"],
            "params": {},
        }
    )
    _sync_counts(document)
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch, document)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    lock_path = tmp_path / "probe.lock"
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", lock_path)
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: pytest.fail("blocked all scope read provider config"),
    )
    monkeypatch.setattr(
        probe,
        "tushare_rows_outcome",
        lambda *args, **kwargs: pytest.fail("blocked all scope called provider"),
    )

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "all",
                "--output",
                str(tmp_path / "evidence.json"),
                "--expected-plan-sha256",
                plan_hash,
            ]
        )
        == 2
    )
    assert not lock_path.exists()
    assert not (tmp_path / "evidence.json").exists()


def test_gaps_scope_executes_only_executable_and_reports_full_coverage(
    tmp_path: Path,
) -> None:
    document = _plan_document(gap_count=3)
    document["entries"][0].update(  # type: ignore[index]
        {
            "probe_state": "blocked",
            "probe_block_reasons": ["required_parameter_unresolved"],
            "params": {},
        }
    )
    _sync_counts(document)
    plan = probe.load_probe_plan(_write_plan(tmp_path, document))
    calls: list[dict[str, object]] = []
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=2,
        call=_call_with(calls=calls),
    )

    assert [item["api_name"] for item in calls] == ["api_001", "api_002"]
    assert evidence["interface_count"] == 2
    assert evidence["coverage"] == {
        "blocked": 1,
        "executable": 2,
        "executed": 2,
        "planned": 3,
        "selected": 2,
    }


def test_execute_rechecks_head_after_provider_calls_and_writes_no_stale_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    commits = iter((COMMIT, "e" * 40))
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(probe, "_current_commit", lambda: next(commits))
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: {"api_url": "https://api.quicksync.cn", "token": "test-token"},
    )
    monkeypatch.setattr(probe, "tushare_rows_outcome", _call_with(calls=calls))
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", tmp_path / "probe.lock")
    output = tmp_path / "evidence.json"

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "gaps",
                "--output",
                str(output),
                "--expected-plan-sha256",
                plan_hash,
            ]
        )
        == 2
    )
    assert len(calls) == 2
    assert not output.exists()


def test_permission_and_other_provider_errors_are_recorded_without_numeric_guessing(
    tmp_path: Path,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=1,
        call=_call_with(
            {
                "api_000": _failed_outcome(40101, error_code="permission_denied"),
                "api_001": _failed_outcome(
                    40102,
                    error_message="interface is unsupported",
                ),
            }
        ),
    )

    assert [
        (item["state"], item["provider_class"]) for item in evidence["results"]
    ] == [
        ("permission_denied", "permission_denied"),
        ("provider_failed", "provider_failed"),
    ]
    assert all("ingest" not in item for item in evidence["results"])
    assert evidence["production_ready"] is False


def test_same_numeric_codes_use_safe_outcome_and_message_not_historical_class(
    tmp_path: Path,
) -> None:
    document = _plan_document(gap_count=4)
    plan = probe.load_probe_plan(_write_plan(tmp_path, document))
    calls: list[dict[str, object]] = []
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=1,
        call=_call_with(
            {
                "api_000": _failed_outcome(
                    40101,
                    error_message="authentication failed",
                ),
                "api_001": _failed_outcome(
                    40101,
                    error_message="permission denied.",
                ),
                "api_002": _failed_outcome(
                    40203,
                    error_code="permission_denied",
                    error_message="permission denied.",
                ),
            },
            calls=calls,
        ),
    )

    assert [item["api_name"] for item in calls] == [
        "api_000",
        "api_001",
        "api_002",
        "api_003",
    ]
    assert [
        (item["state"], item["provider_class"]) for item in evidence["results"]
    ] == [
        ("credential_rejected", "credential_rejected"),
        ("permission_denied", "permission_denied"),
        ("permission_denied", "permission_denied"),
        ("success", "ok"),
    ]


def test_unclassified_per_interface_failure_is_recorded_and_run_continues(
    tmp_path: Path,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=1,
        call=_call_with(
            {
                "api_000": _failed_outcome(
                    40101,
                    error_message="provider request failed",
                )
            }
        ),
    )

    assert [item["state"] for item in evidence["results"]] == [
        "provider_failed",
        "success",
    ]


@pytest.mark.parametrize(
    ("outcome", "response_bytes"),
    [
        (_failed_outcome(429, error_code="rate_limited"), 128),
        (_failed_outcome(500, error_code="transport_error"), 0),
        (_failed_outcome(500, error_code="resource_budget"), 2 * 1024 * 1024 + 1),
    ],
)
def test_rate_transport_and_resource_fail_closed_without_evidence(
    tmp_path: Path,
    outcome: ProviderCallOutcome,
    response_bytes: int,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))
    calls: list[dict[str, object]] = []
    with pytest.raises(probe.ProbeExecutionError):
        _execute_probe(
            plan,
            scope="gaps",
            token="private-token",
            concurrency=1,
            call=_call_with(
                {"api_000": outcome},
                response_bytes=response_bytes,
                calls=calls,
            ),
        )
    assert [item["api_name"] for item in calls] == ["api_000"]


def test_redacted_provider_diagnostic_is_only_recorded_as_provider_failed(
    tmp_path: Path,
) -> None:
    plan = probe.load_probe_plan(_write_plan(tmp_path))
    outcome = ProviderCallOutcome(
        state="failed",
        rows=(),
        provider_code=40102,
        error_code="provider_error",
        error_message="provider diagnostic [REDACTED]",
    )
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="private-token",
        concurrency=1,
        call=_call_with({"api_000": outcome}),
    )
    assert evidence["results"][0]["state"] == "provider_failed"


def test_total_response_budget_stops_before_an_unbudgeted_call(tmp_path: Path) -> None:
    document = _plan_document(gap_count=18)
    plan = probe.load_probe_plan(_write_plan(tmp_path, document))
    calls: list[dict[str, object]] = []
    with pytest.raises(probe.ProbeExecutionError):
        _execute_probe(
            plan,
            scope="gaps",
            token="private-token",
            concurrency=1,
            call=_call_with(
                response_bytes=2 * 1024 * 1024,
                calls=calls,
            ),
        )

    assert len(calls) == 16


def test_exclusive_process_lock_rejects_concurrent_probe(tmp_path: Path) -> None:
    lock_path = tmp_path / "probe.lock"
    with probe.exclusive_probe_lock(lock_path):
        with pytest.raises(probe.ProbeBusyError):
            with probe.exclusive_probe_lock(lock_path):
                pass
    metadata = lock_path.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1


def test_cross_run_budget_prechecks_capacity_and_records_actual_starts(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "probe.lock"
    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 190, now=1000.0) == 0
        first = [probe.authorize_request_start(lock, now=1000.0) for _ in range(190)]
    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 10, now=1000.0) == 190
        second = [probe.authorize_request_start(lock, now=1000.0) for _ in range(10)]
    with probe.exclusive_probe_lock(lock_path) as lock:
        with pytest.raises(probe.ProbeRateBudgetError):
            probe.check_request_start_capacity(lock, 1, now=1000.0)

    assert (
        first[0].active_before,
        first[-1].active_after,
        sum(item.reserved for item in first),
    ) == (0, 190, 190)
    assert (
        second[0].active_before,
        second[-1].active_after,
        sum(item.reserved for item in second),
    ) == (
        190,
        200,
        10,
    )

    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 200, now=1061.0) == 0
        recovered = probe.authorize_request_start(lock, now=1061.0)
    assert (recovered.active_before, recovered.active_after) == (0, 1)


def test_capacity_precheck_persists_no_future_request_starts(tmp_path: Path) -> None:
    lock_path = tmp_path / "probe.lock"
    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 200, now=1000.0) == 0

    state = json.loads(lock_path.read_text(encoding="utf-8"))
    assert state == {
        "request_starts": [],
        "schema_version": "tradingdatas.quicksync.request_start_budget.v1",
    }
    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 200, now=1000.0) == 0


def test_second_full_cli_run_fails_before_config_or_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    calls: list[dict[str, object]] = []
    config_reads: list[bool] = []
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(probe, "_epoch_now", lambda: 1000.0)
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", tmp_path / "probe.lock")
    monkeypatch.setattr(probe, "tushare_rows_outcome", _call_with(calls=calls))
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: (
            config_reads.append(True)
            or {"api_url": "https://api.quicksync.cn", "token": "test-token"}
        ),
    )

    common = [
        "--request-plan",
        str(path),
        "--execute",
        "--scope",
        "all",
        "--expected-plan-sha256",
        plan_hash,
    ]
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"
    assert probe.main([*common, "--output", str(first_output)]) == 0
    assert len(calls) == 190
    assert len(config_reads) == 1
    assert probe.main([*common, "--output", str(second_output)]) == 2
    assert len(calls) == 190
    assert len(config_reads) == 1
    assert not second_output.exists()
    first = json.loads(first_output.read_text(encoding="utf-8"))
    assert first["rate_budget"]["authorizations"] == {
        "active_after_last": 190,
        "active_before_first": 0,
        "authorized": 190,
        "first_authorized_at_epoch": 1000.0,
        "last_authorized_at_epoch": 1000.0,
    }


def test_long_run_and_cross_process_cannot_exceed_rolling_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _plan_document(gap_count=200, interface_count=200)
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch, document)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    calls: list[dict[str, object]] = []
    config_reads: list[bool] = []
    logical_clock = [0.0]

    def epoch_now() -> float:
        observed = logical_clock[0]
        logical_clock[0] = round(observed + 0.6, 10)
        return observed

    lock_path = tmp_path / "probe.lock"
    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(probe, "_epoch_now", epoch_now)
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", lock_path)
    monkeypatch.setattr(probe, "tushare_rows_outcome", _call_with(calls=calls))
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: (
            config_reads.append(True)
            or {"api_url": "https://api.quicksync.cn", "token": "test-token"}
        ),
    )
    common = [
        "--request-plan",
        str(path),
        "--execute",
        "--scope",
        "all",
        "--expected-plan-sha256",
        plan_hash,
        "--concurrency",
        "4",
    ]
    first_output = tmp_path / "long-run.json"
    second_output = tmp_path / "second-long-run.json"

    assert probe.main([*common, "--output", str(first_output)]) == 0
    assert len(calls) == 200
    assert len(config_reads) == 1
    evidence = json.loads(first_output.read_text(encoding="utf-8"))
    assert evidence["rate_budget"]["authorizations"] == {
        "active_after_last": 101,
        "active_before_first": 0,
        "authorized": 200,
        "first_authorized_at_epoch": 0.6,
        "last_authorized_at_epoch": 120.0,
    }

    # The run consumed 120 logical seconds.  An immediately following full
    # run must count the still-active 100 actual starts and fail before config
    # or a provider call, rather than trusting a stale t0 reservation.
    assert probe.main([*common, "--output", str(second_output)]) == 2
    assert len(calls) == 200
    assert len(config_reads) == 1
    assert not second_output.exists()

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from pathlib import Path\n"
                "from tools import probe_quicksync_interfaces as probe\n"
                "with probe.exclusive_probe_lock(Path(sys.argv[2])) as lock:\n"
                "    try:\n"
                "        probe.check_request_start_capacity("
                "lock, 200, now=float(sys.argv[3]))\n"
                "    except probe.ProbeRateBudgetError:\n"
                "        raise SystemExit(0)\n"
                "raise SystemExit(3)\n"
            ),
            str(probe.ROOT),
            str(lock_path),
            str(logical_clock[0]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 0, child.stderr


def test_provider_exception_does_not_refund_persisted_request_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _plan_document(gap_count=1, interface_count=1)
    document, _, _ = _bind_authority_files(tmp_path, monkeypatch, document)
    path = _write_plan(tmp_path, document)
    plan_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    calls: list[str] = []
    lock_path = tmp_path / "probe.lock"

    def exploding_call(api_name: str, *_args, **_kwargs) -> ProviderCallOutcome:
        calls.append(api_name)
        raise RuntimeError("provider failed after request start")

    monkeypatch.setattr(probe, "_current_commit", lambda: COMMIT)
    monkeypatch.setattr(probe, "_epoch_now", lambda: 1000.0)
    monkeypatch.setattr(probe, "DEFAULT_LOCK_PATH", lock_path)
    monkeypatch.setattr(probe, "tushare_rows_outcome", exploding_call)
    monkeypatch.setattr(
        probe,
        "get_tushare_config",
        lambda: {"api_url": "https://api.quicksync.cn", "token": "test-token"},
    )
    output = tmp_path / "must-not-exist.json"

    assert (
        probe.main(
            [
                "--request-plan",
                str(path),
                "--execute",
                "--scope",
                "all",
                "--expected-plan-sha256",
                plan_hash,
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert calls == ["api_000"]
    assert not output.exists()
    with probe.exclusive_probe_lock(lock_path) as lock:
        with pytest.raises(probe.ProbeRateBudgetError):
            probe.check_request_start_capacity(lock, 200, now=1000.0)


def test_request_start_at_exact_window_boundary_remains_chargeable(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "probe.lock"
    with probe.exclusive_probe_lock(lock_path) as lock:
        authorization = probe.authorize_request_start(lock, now=940.0)
    assert authorization.active_after == 1

    with probe.exclusive_probe_lock(lock_path) as lock:
        with pytest.raises(probe.ProbeRateBudgetError):
            probe.check_request_start_capacity(lock, 200, now=1000.0)
    with probe.exclusive_probe_lock(lock_path) as lock:
        assert probe.check_request_start_capacity(lock, 200, now=1000.000001) == 0


def test_budget_state_corrupt_future_or_unsafe_fails_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.lock"
    corrupt.write_text("{not-json", encoding="utf-8")
    corrupt.chmod(0o600)
    with probe.exclusive_probe_lock(corrupt) as lock:
        with pytest.raises(probe.ProbeValidationError):
            probe.check_request_start_capacity(lock, 1, now=1000.0)

    future = tmp_path / "future.lock"
    future.write_text(
        json.dumps(
            {
                "schema_version": "tradingdatas.quicksync.request_start_budget.v1",
                "request_starts": [1001.0],
            }
        ),
        encoding="utf-8",
    )
    future.chmod(0o600)
    with probe.exclusive_probe_lock(future) as lock:
        with pytest.raises(probe.ProbeValidationError):
            probe.check_request_start_capacity(lock, 1, now=1000.0)

    unsafe = tmp_path / "unsafe.lock"
    unsafe.write_text("{}", encoding="utf-8")
    unsafe.chmod(0o644)
    with pytest.raises(probe.ProbeValidationError):
        with probe.exclusive_probe_lock(unsafe):
            pass

    linked = tmp_path / "linked.lock"
    unsafe.chmod(0o600)
    os.link(unsafe, linked)
    with pytest.raises(probe.ProbeValidationError):
        with probe.exclusive_probe_lock(unsafe):
            pass

    linked.unlink()
    symlink = tmp_path / "symlink.lock"
    symlink.symlink_to(unsafe)
    with pytest.raises(probe.ProbeValidationError):
        with probe.exclusive_probe_lock(symlink):
            pass


def test_cli_cannot_select_an_alternate_lock_path(tmp_path: Path) -> None:
    path = _write_plan(tmp_path)
    with pytest.raises(SystemExit):
        probe.parse_args(
            [
                "--request-plan",
                str(path),
                "--lock-path",
                str(tmp_path / "alternate.lock"),
            ]
        )


def test_concurrency_four_stops_after_first_failed_batch_and_returns_no_evidence(
    tmp_path: Path,
) -> None:
    document = _plan_document(gap_count=12)
    plan = probe.load_probe_plan(_write_plan(tmp_path, document))
    calls: list[dict[str, object]] = []
    with pytest.raises(probe.ProbeExecutionError):
        _execute_probe(
            plan,
            scope="gaps",
            token="private-token",
            concurrency=4,
            call=_call_with(
                {"api_000": _failed_outcome(429, error_code="rate_limited")},
                calls=calls,
            ),
        )
    assert 1 <= len(calls) <= 4
    assert {item["api_name"] for item in calls}.issubset(
        {"api_000", "api_001", "api_002", "api_003"}
    )


def test_atomic_evidence_is_0600_single_link_and_contains_no_sensitive_values(
    tmp_path: Path,
) -> None:
    document = _plan_document()
    secret_param = "HIGHLY-SENSITIVE-PARAMETER"
    document["entries"][0]["params"]["symbol"] = secret_param  # type: ignore[index]
    plan_path = _write_plan(tmp_path, document)
    plan = probe.load_probe_plan(plan_path)
    row_secret = "ROW-SECRET-VALUE"
    evidence = _execute_probe(
        plan,
        scope="gaps",
        token="HIGHLY-SENSITIVE-TOKEN",
        concurrency=1,
        call=_call_with(
            {
                "api_000": _success_outcome(
                    rows=({"code": "000001", "value": row_secret},)
                )
            }
        ),
    )
    output = tmp_path / "evidence.json"
    probe.write_evidence_atomic(output, evidence)

    raw = output.read_text(encoding="utf-8")
    payload = json.loads(raw)
    metadata = output.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    assert "HIGHLY-SENSITIVE" not in raw
    assert row_secret not in raw
    assert "params" not in raw
    assert payload["results"][0] == {
        "api_name": "api_000",
        "elapsed_ms": payload["results"][0]["elapsed_ms"],
        "fields": ["code", "value"],
        "provider_class": "ok",
        "response_bytes": 128,
        "response_sha256": RESPONSE_SHA,
        "row_count": 1,
        "state": "success",
    }

    with pytest.raises(probe.ProbeValidationError):
        probe.write_evidence_atomic(output, evidence)

    target = tmp_path / "target.json"
    target.write_text("unchanged", encoding="utf-8")
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    with pytest.raises(probe.ProbeValidationError):
        probe.write_evidence_atomic(symlink, evidence)
    assert target.read_text(encoding="utf-8") == "unchanged"
