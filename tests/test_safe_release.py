from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from tools import safe_release as release
from tools.create_release_ci_evidence import capture

TARGET = "b" * 40
OLD = "a" * 40


def ci(now):
    return {
        "version": 1,
        "repository": release.REPOSITORY,
        "workflow_path": release.WORKFLOW,
        "target": TARGET,
        "main_sha": TARGET,
        "head_sha": TARGET,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "run_id": 123,
        "run_url": f"https://github.com/{release.REPOSITORY}/actions/runs/123",
        "created_at": (now - timedelta(minutes=3)).isoformat(),
        "completed_at": (now - timedelta(minutes=2)).isoformat(),
        "checked_at": now.isoformat(),
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", OLD),
        ("main_sha", OLD),
        ("head_sha", OLD),
        ("repository", "other/repo"),
        ("workflow_path", ".github/workflows/deploy.yml"),
        ("event", "pull_request"),
        ("head_branch", "topic"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("run_id", True),
        ("run_url", "https://example.org/123"),
    ],
)
def test_ci_rejects_wrong_identity_and_nonfinal_result(field, value):
    now = datetime.now(timezone.utc)
    data = ci(now)
    data[field] = value
    with pytest.raises(ValueError):
        release.validate_ci(data, TARGET, now)


def test_ci_rejects_expired_and_future_and_reordered_times():
    now = datetime.now(timezone.utc)
    release.validate_ci(ci(now), TARGET, now)
    for field, value in [
        ("checked_at", now + timedelta(seconds=1)),
        ("completed_at", now + timedelta(seconds=1)),
        ("created_at", now + timedelta(seconds=1)),
    ]:
        data = ci(now)
        data[field] = value.isoformat()
        with pytest.raises(ValueError):
            release.validate_ci(data, TARGET, now)
    with pytest.raises(ValueError, match="expired"):
        release.validate_ci(ci(now - timedelta(minutes=16)), TARGET, now)


def gate(now, expected):
    def sample(start):
        return {
            "http": 200,
            "seconds": 1.0,
            "count": 1,
            "next_cursor": None,
            "started_at": (now - timedelta(seconds=start)).isoformat(),
            "finished_at": (now - timedelta(seconds=start - 1)).isoformat(),
        }

    return {
        "version": 1,
        "target": TARGET,
        "measured_at": now.isoformat(),
        "planes": {
            plane: {
                "registry_sha256": value["registry_sha256"],
                "new_process": True,
                "pid": 123,
                "cwd_commit": TARGET,
                "cold": sample(4),
                "concurrent": [sample(2), sample(2)],
            }
            for plane, value in expected.items()
        },
    }


def test_catalog_gate_requires_real_bound_cold_and_overlapping_samples():
    now = datetime.now(timezone.utc)
    expected = {"plane": {"registry_sha256": "c" * 64, "count": 1}}
    valid = gate(now, expected)
    release.validate_catalog_evidence(valid, TARGET, expected, now)
    for mutate in [
        lambda d: d.update(target=OLD),
        lambda d: d["planes"]["plane"].update(registry_sha256="bad"),
        lambda d: d["planes"]["plane"].update(cwd_commit=OLD),
        lambda d: d["planes"]["plane"].update(pid=True),
        lambda d: d["planes"]["plane"]["cold"].update(seconds=15),
        lambda d: d["planes"]["plane"]["cold"].update(http=503),
        lambda d: d["planes"]["plane"]["concurrent"].pop(),
        lambda d: d["planes"]["plane"]["concurrent"][0].update(
            started_at=(now - timedelta(seconds=10)).isoformat(),
            finished_at=(now - timedelta(seconds=9)).isoformat(),
        ),
    ]:
        data = json.loads(json.dumps(valid))
        mutate(data)
        with pytest.raises(ValueError):
            release.validate_catalog_evidence(data, TARGET, expected, now)
    with pytest.raises(ValueError, match="expired"):
        release.validate_catalog_evidence(
            valid, TARGET, expected, now + timedelta(minutes=16)
        )


def test_private_evidence_rejects_symlink_shared_mode_and_hardlink(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("{}")
    path.chmod(0o600)
    assert release.private_json(path, os.getuid()) == {}
    path.chmod(0o644)
    with pytest.raises(ValueError):
        release.private_json(path, os.getuid())
    path.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(release.manifest.ReleaseManifestError):
        release.private_json(alias, os.getuid())
    os.link(path, tmp_path / "hard")
    with pytest.raises(ValueError):
        release.private_json(path, os.getuid())


def test_ci_capture_reads_main_twice_and_refuses_parallel_change():
    now = datetime.now(timezone.utc)
    record = ci(now)
    run = {
        "path": release.WORKFLOW,
        "head_sha": TARGET,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "id": 123,
        "html_url": record["run_url"],
        "created_at": record["created_at"],
        "updated_at": record["completed_at"],
        "run_number": 1,
        "run_attempt": 1,
        "head_repository": {"full_name": release.REPOSITORY},
    }
    calls = []

    def gh(endpoint):
        calls.append(endpoint)
        if "/runs?" in endpoint:
            return {"workflow_runs": [run]}
        return {"object": {"sha": TARGET if len(calls) == 1 else OLD}}

    with pytest.raises(ValueError, match="changed"):
        capture(TARGET, gh)
    assert len(calls) == 3


class Audit:
    def __init__(self):
        self.events = []

    def emit(self, phase, **values):
        self.events.append((phase, values))


@pytest.fixture
def machine(tmp_path, monkeypatch):
    roots = [tmp_path / spec[0] for spec in release.PLANES]
    raw = b"datasets: [{}]\n"
    for root, spec in zip(roots, release.PLANES):
        path = root / TARGET / "config" / spec[4]
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
    pointers = {r: OLD for r in roots}
    held = set()

    @contextmanager
    def lock(root, **kwargs):
        held.add(root)
        try:
            yield SimpleNamespace(descriptor=root)
        finally:
            held.remove(root)

    def pointer(fd):
        assert len(held) == 2
        return pointers[fd]

    def load(path, **kwargs):
        sha = path.stem
        return {"commit": sha, "files": [{"path": "tools/app.py", "sha256": sha}]}

    def verify(*args, **kwargs):
        assert len(held) == 2
        return {"verified": True}

    def switch(root, target, previous, **kwargs):
        assert len(held) == 2 and pointers[root] == previous["commit"]
        pointers[root] = target["commit"]

    monkeypatch.setattr(release.manifest, "release_root_lock", lock)
    monkeypatch.setattr(release.manifest, "_read_current_target_at", pointer)
    monkeypatch.setattr(release.manifest, "load_manifest", load)
    monkeypatch.setattr(release.manifest, "verify_current", verify)
    monkeypatch.setattr(release.manifest, "verify_release", verify)
    monkeypatch.setattr(release.manifest, "switch_current", switch)
    expected = {
        root.name: {"registry_sha256": hashlib.sha256(raw).hexdigest(), "count": 1}
        for root in roots
    }
    now = datetime.now(timezone.utc)
    evidence = {"ci": ci(now), "gate": gate(now, expected)}
    monkeypatch.setattr(release, "private_json", lambda path: evidence[path])

    class Host:
        def __init__(self):
            self.units = {}
            self.actions = []
            self.fail_catalog = False
            self.busy = False
            self.fail_restore_once = False
            for name in self.timers():
                self.units[name] = {
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                    "MainPID": "0",
                }
                self.units[name.replace(".timer", ".service")] = {
                    "ActiveState": "inactive",
                    "MainPID": "0",
                }
            for spec in release.PLANES:
                self.units[spec[1]] = {
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                    "MainPID": "1",
                }

        def timers(self):
            return [
                "tradingdatas-provider-native-collect.timer",
                "tradingdatas-crypto-binance-collect.timer",
            ]

        def state(self, unit):
            assert len(held) == 2
            if self.busy and unit in [
                u.replace(".timer", ".service") for u in self.timers()
            ]:
                return {"MainPID": "100", "ActiveState": "activating"}
            return self.units[unit].copy()

        def change(self, action, unit):
            assert len(held) == 2
            self.actions.append((action, unit))
            if self.fail_restore_once and action == "enable":
                self.fail_restore_once = False
                raise RuntimeError("restore failure")
            if action in ("start", "stop"):
                self.units[unit]["ActiveState"] = (
                    "active" if action == "start" else "inactive"
                )
            else:
                self.units[unit]["UnitFileState"] = (
                    "enabled" if action == "enable" else "disabled"
                )

        def ready(self, spec):
            assert len(held) == 2

        def cwd(self, unit):
            return roots[[s[1] for s in release.PLANES].index(unit)] / TARGET

        def catalog(self, spec):
            assert len(held) == 2
            if self.fail_catalog:
                raise ValueError("HTTP failure")
            return {"http": 200, "seconds": 1, "count": 1, "next_cursor": None}

    host = Host()
    return SimpleNamespace(
        base=tmp_path,
        roots=roots,
        pointers=pointers,
        held=held,
        host=host,
        evidence=evidence,
        audit=Audit(),
    )


def test_session_success_holds_both_locks_through_restore_and_preserves_inactive_api(
    machine,
):
    m = machine
    inactive = release.PLANES[1][1]
    m.host.units[inactive]["ActiveState"] = "inactive"
    release.session(TARGET, "ci", "gate", m.audit, host=m.host, base=m.base)
    assert set(m.pointers.values()) == {TARGET}
    assert m.host.units[inactive]["ActiveState"] == "inactive"
    assert not m.held
    assert m.audit.events[-1][0] == "complete"


@pytest.mark.parametrize("failure", ["catalog", "drain", "ci", "restore"])
def test_session_failures_restore_owned_state_and_rollback(machine, failure):
    m = machine
    before = json.loads(json.dumps(m.host.units))
    if failure == "catalog":
        m.host.fail_catalog = True
    elif failure == "drain":
        m.host.busy = True
    elif failure == "ci":
        m.evidence["ci"]["conclusion"] = "failure"
    else:
        m.host.fail_restore_once = True
    with pytest.raises((ValueError, TimeoutError, RuntimeError)):
        release.session(
            TARGET, "ci", "gate", m.audit, host=m.host, base=m.base, drain_seconds=0
        )
    assert set(m.pointers.values()) == {OLD}
    assert m.host.units == before
    assert not m.held
    if failure == "ci":
        assert m.host.actions == []


def test_session_refuses_foreign_pointer_without_overwriting(machine):
    m = machine
    original = m.host.catalog

    def catalog(spec):
        m.pointers[m.roots[1]] = "c" * 40
        return original(spec)

    m.host.catalog = catalog

    # Real verifier catches drift. Simulate its post-cut check.
    def verify(root, expected, **kwargs):
        if m.pointers[root] != expected["commit"]:
            raise ValueError("pointer moved")

    from unittest.mock import patch

    with patch.object(release.manifest, "verify_current", verify):
        with pytest.raises(RuntimeError, match="rollback incomplete"):
            release.session(TARGET, "ci", "gate", m.audit, host=m.host, base=m.base)
    assert m.pointers[m.roots[1]] == "c" * 40
    assert m.pointers[m.roots[0]] == OLD
    assert m.host.units[release.PLANES[1][1]]["ActiveState"] == "inactive"


def test_session_already_current_does_not_change_units(machine):
    m = machine
    m.pointers.update({r: TARGET for r in m.roots})
    release.session(TARGET, "missing", "missing", m.audit, host=m.host, base=m.base)
    assert not m.host.actions
    assert m.audit.events[-1][0] == "skip_already_current"


def test_documentation_skip_is_conservative():
    old = {"files": [{"path": "README.md", "sha256": "a"}]}
    new = {
        "files": [
            {"path": "README.md", "sha256": "b"},
            {"path": "docs/reports/2026-09-09-audit.md", "sha256": "c"},
        ]
    }
    assert release.documentation_only(old, new)
    new["files"].append({"path": "docs/reports/run.py", "sha256": "d"})
    assert not release.documentation_only(old, new)


def test_audit_failure_cannot_prevent_pointer_rollback(machine):
    m = machine
    original = m.audit.emit

    def emit(phase, **values):
        if phase in {"switched", "failure", "rolled_back"}:
            raise OSError("audit unavailable")
        original(phase, **values)

    m.audit.emit = emit
    with pytest.raises(OSError):
        release.session(TARGET, "ci", "gate", m.audit, host=m.host, base=m.base)
    assert set(m.pointers.values()) == {OLD}
    assert all(m.host.units[u]["ActiveState"] == "active" for u in m.host.timers())
    assert not m.held


def test_complete_audit_failure_drains_again_before_rollback(machine):
    m = machine
    original = m.audit.emit

    def emit(phase, **values):
        if phase == "complete":
            raise OSError("disk full")
        original(phase, **values)

    m.audit.emit = emit
    with pytest.raises(OSError):
        release.session(TARGET, "ci", "gate", m.audit, host=m.host, base=m.base)
    assert set(m.pointers.values()) == {OLD}
    for timer in m.host.timers():
        assert m.host.actions.count(("disable", timer)) == 2
    assert not m.held


def test_session_documentation_only_skips_even_without_evidence(machine, monkeypatch):
    m = machine
    monkeypatch.setattr(
        release.manifest,
        "load_manifest",
        lambda path, **kwargs: {
            "commit": path.stem,
            "files": [{"path": "STATUS.md", "sha256": path.stem}],
        },
    )
    release.session(TARGET, "missing", "missing", m.audit, host=m.host, base=m.base)
    assert not m.host.actions
    assert set(m.pointers.values()) == {OLD}
    assert m.audit.events[-1][0] == "skip_documentation_only"


def test_private_json_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"target":"a", "target":"b"}')
    path.chmod(0o600)
    with pytest.raises(ValueError, match="duplicate"):
        release.private_json(path, os.getuid())


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_ci_capture_accepts_existing_main_ci_events(event):
    now = datetime.now(timezone.utc)
    record = ci(now)
    record["event"] = event
    release.validate_ci(record, TARGET, now)
    run = {
        "path": release.WORKFLOW,
        "head_sha": TARGET,
        "head_branch": "main",
        "event": event,
        "status": "completed",
        "conclusion": "success",
        "id": 123,
        "html_url": record["run_url"],
        "created_at": record["created_at"],
        "updated_at": record["completed_at"],
        "run_number": 1,
        "run_attempt": 1,
        "head_repository": {"full_name": release.REPOSITORY},
    }

    def gh(endpoint):
        if "/runs?" in endpoint:
            return {"workflow_runs": [run]}
        return {"object": {"sha": TARGET}}

    assert capture(TARGET, gh)["event"] == event


def test_fresh_catalog_envelope_cannot_refresh_expired_samples():
    now = datetime.now(timezone.utc)
    expected = {"plane": {"registry_sha256": "c" * 64, "count": 1}}
    data = gate(now, expected)
    for sample in [
        data["planes"]["plane"]["cold"],
        *data["planes"]["plane"]["concurrent"],
    ]:
        for key in ("started_at", "finished_at"):
            sample[key] = (
                release.timestamp(sample[key]) - timedelta(days=1)
            ).isoformat()
    with pytest.raises(ValueError, match="sample.*expired"):
        release.validate_catalog_evidence(data, TARGET, expected, now)


def test_catalog_sample_expiry_is_rechecked_after_drain():
    now = datetime.now(timezone.utc)
    expected = {"plane": {"registry_sha256": "c" * 64, "count": 1}}
    data = gate(now, expected)
    release.validate_catalog_evidence(data, TARGET, expected, now)
    # Envelope is still younger than 15 minutes, but the oldest cold sample
    # has aged past the bound during collector drain.
    after_drain = now + timedelta(seconds=release.MAX_EVIDENCE_AGE - 2)
    with pytest.raises(ValueError, match="sample.*expired"):
        release.validate_catalog_evidence(data, TARGET, expected, after_drain)
