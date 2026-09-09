#!/usr/bin/env python3
"""Operator-owned, locked release session; no provider calls or database writes."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import release_manifest as manifest  # noqa: E402 - disable bytecode before importing release-local code

REPOSITORY = "NicholasHan1226/TradingDatas"
WORKFLOW = ".github/workflows/ci.yml"
MAX_EVIDENCE_AGE = 900
PLANES = (
    (
        "tradingdatas",
        "tradingdatas-v1-internal.service",
        18082,
        "tradingdatas-read.token",
        "provider_native_dataset_registry.yaml",
    ),
    (
        "tradingdatas-crypto",
        "tradingdatas-crypto-v1-internal.service",
        18083,
        "tradingdatas-crypto-read.token",
        "crypto_binance_canary_registry.v1.yaml",
    ),
)
DOC_FILES = {
    "README.md",
    "STATUS.md",
    "AGENTS.md",
    "docs/AGENTS.md",
    "docs/OPERATIONS.md",
}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed


def validate_ci(data, target, now):
    if (
        type(data.get("version")) is not int
        or data.get("version") != 1
        or data.get("repository") != REPOSITORY
        or data.get("workflow_path") != WORKFLOW
        or data.get("target") != target
        or data.get("main_sha") != target
        or data.get("head_sha") != target
        or data.get("head_branch") != "main"
        or data.get("event") not in {"push", "workflow_dispatch"}
        or data.get("status") != "completed"
        or data.get("conclusion") != "success"
        or type(data.get("run_id")) is not int
        or data["run_id"] <= 0
        or data.get("run_url")
        != f"https://github.com/{REPOSITORY}/actions/runs/{data['run_id']}"
    ):
        raise ValueError("CI identity or conclusion is invalid")
    checked = timestamp(data["checked_at"])
    completed = timestamp(data["completed_at"])
    created = timestamp(data["created_at"])
    if not created <= completed <= checked <= now:
        raise ValueError("CI timestamps are inconsistent or future")
    if (now - checked).total_seconds() > MAX_EVIDENCE_AGE:
        raise ValueError("CI evidence is expired")


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evidence key")
        result[key] = value
    return result


def private_json(path, uid=0):
    path = manifest._canonical_absolute_path(path, name="evidence")
    manifest._assert_no_symlink_components(path, name="evidence")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != uid
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > 1024 * 1024
        ):
            raise ValueError("evidence must be private single-link operator-owned JSON")
        with os.fdopen(os.dup(fd), "r") as stream:
            data = json.load(stream, object_pairs_hook=_unique_json_pairs)
        if not isinstance(data, dict):
            raise ValueError("evidence must be an object")
        return data
    finally:
        os.close(fd)


def documentation_only(old, new):
    before = {x["path"]: x for x in old["files"]}
    after = {x["path"]: x for x in new["files"]}
    changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
    return bool(changed) and all(
        p in DOC_FILES
        or re.fullmatch(r"docs/reports/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md", p)
        for p in changed
    )


def validate_catalog_evidence(data, target, expected, now):
    if (
        type(data.get("version")) is not int
        or data.get("version") != 1
        or data.get("target") != target
    ):
        raise ValueError("catalog gate target is invalid")
    measured = timestamp(data["measured_at"])
    if not 0 <= (now - measured).total_seconds() <= MAX_EVIDENCE_AGE:
        raise ValueError("catalog gate is future or expired")
    if set(data.get("planes", {})) != set(expected):
        raise ValueError("catalog planes are incomplete")
    for plane, binding in expected.items():
        item = data["planes"][plane]
        if item.get("registry_sha256") != binding["registry_sha256"]:
            raise ValueError("catalog registry binding changed")
        if (
            item.get("new_process") is not True
            or type(item.get("pid")) is not int
            or item["pid"] <= 0
        ):
            raise ValueError("catalog cold process identity is missing")
        if item.get("cwd_commit") != target:
            raise ValueError("catalog process is not target")
        concurrent = item.get("concurrent")
        if not isinstance(concurrent, list) or len(concurrent) != 2:
            raise ValueError("two same-plane concurrent measurements are required")
        ranges = []
        for sample in [item.get("cold", {}), *concurrent]:
            started, finished = (
                timestamp(sample["started_at"]),
                timestamp(sample["finished_at"]),
            )
            if not started < finished <= measured:
                raise ValueError("catalog sample timing is inconsistent")
            if not 0 <= (now - started).total_seconds() <= MAX_EVIDENCE_AGE:
                raise ValueError("catalog sample is future or expired")
            ranges.append((started, finished))
            seconds = sample.get("seconds")
            if (
                sample.get("http") != 200
                or type(sample.get("count")) is not int
                or sample.get("count") != binding["count"]
                or sample.get("next_cursor") is not None
                or type(seconds) not in (int, float)
                or not math.isfinite(seconds)
                or not 0 < seconds < 15
            ):
                raise ValueError("catalog latency or completeness gate failed")
            if abs((finished - started).total_seconds() - seconds) > 2:
                raise ValueError("catalog elapsed time does not match sample window")
        if ranges[0][1] > min(ranges[1][0], ranges[2][0]):
            raise ValueError("cold sample must precede concurrency samples")
        if max(ranges[1][0], ranges[2][0]) >= min(ranges[1][1], ranges[2][1]):
            raise ValueError("same-plane samples were not concurrent")


class Audit:
    def __init__(self, path, actor, task_id, target):
        for value in (actor, task_id):
            if not re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,160}", value):
                raise ValueError("actor/task_id must be bounded audit identifiers")
        path = manifest._canonical_absolute_path(path, name="audit")
        manifest._assert_no_symlink_components(path.parent, name="audit parent")
        parent = path.parent.stat()
        if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
            raise ValueError(
                "audit parent must be operator-owned and private to writes"
            )
        self.stream = os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
            "w",
        )
        self.identity = {
            "actor": actor,
            "task_id": task_id,
            "target": target,
            "pid": os.getpid(),
        }

    def emit(self, phase, **values):
        self.stream.write(
            json.dumps(
                {
                    **self.identity,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "phase": phase,
                    **values,
                },
                sort_keys=True,
            )
            + "\n"
        )
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        self.stream.close()


class Host:
    def run(self, *args):
        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.PIPE,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            timeout=120,
        ).strip()

    def state(self, unit):
        values = self.run(
            "systemctl", "show", unit, "--property=ActiveState,UnitFileState,MainPID"
        )
        return dict(line.split("=", 1) for line in values.splitlines() if "=" in line)

    def change(self, action, unit):
        self.run("systemctl", action, unit)

    def timers(self):
        lines = self.run(
            "systemctl",
            "list-unit-files",
            "tradingdatas*.timer",
            "--no-legend",
            "--no-pager",
        )
        return sorted(
            line.split()[0]
            for line in lines.splitlines()
            if line
            and (
                line.split()[0] == "tradingdatas-provider-native-collect.timer"
                or line.split()[0].startswith("tradingdatas-crypto-")
            )
        )

    def catalog(self, spec):
        _, _, port, token, _ = spec
        secret = (Path("/run/secrets/tradingagent") / token).read_text().strip()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/catalog",
            headers={"Authorization": "Bearer " + secret},
        )
        start = time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
            return {
                "http": response.status,
                "seconds": time.monotonic() - start,
                "count": len(data.get("data", [])),
                "next_cursor": data.get("next_cursor"),
            }

    def ready(self, spec):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{spec[2]}/v1/catalog", timeout=2
                ).close()
                raise ValueError("API unexpectedly admits anonymous catalog")
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    return
                raise ValueError("API authentication readiness failed") from None
            except OSError:
                time.sleep(1)
        raise TimeoutError("API readiness timeout")

    def cwd(self, unit):
        return Path("/proc") / self.state(unit)["MainPID"] / "cwd"


def restore_units(host, originals, touched, emit):
    errors = []
    for unit in sorted(touched, key=lambda name: (name.endswith(".timer"), name)):
        wanted = originals[unit]
        try:
            if unit.endswith(".timer"):
                action = "enable" if wanted["UnitFileState"] == "enabled" else "disable"
                host.change(action, unit)
            host.change("start" if wanted["ActiveState"] == "active" else "stop", unit)
            actual = host.state(unit)
            keys = ["ActiveState"] + (
                ["UnitFileState"] if unit.endswith(".timer") else []
            )
            if any(actual[k] != wanted[k] for k in keys):
                raise RuntimeError("unit restore state mismatch")
        except Exception as exc:
            errors.append({"unit": unit, "type": type(exc).__name__})
    emit("restored", units=sorted(touched), errors=errors)
    if errors:
        raise RuntimeError("unit restoration failed")


def drain_collectors(host, timers, seconds):
    deadline = time.monotonic() + seconds
    while True:
        busy = []
        for unit in timers:
            state = host.state(unit.replace(".timer", ".service"))
            if state["MainPID"] != "0" or state["ActiveState"] not in {
                "inactive",
                "failed",
            }:
                busy.append(unit)
        if not busy:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("collector drain timeout")
        time.sleep(1)


def session(
    target,
    ci_path,
    catalog_path,
    audit,
    *,
    host=None,
    base=Path("/opt/investment/releases"),
    drain_seconds=2700,
):
    manifest._validate_hex(target, name="target")
    host = host or Host()
    roots = [base / spec[0] for spec in PLANES]
    with ExitStack() as stack:
        leases = {
            root: stack.enter_context(
                manifest.release_root_lock(root, expected_uid=0, expected_gid=0)
            )
            for root in sorted(roots)
        }
        audit.emit("locked")
        old = {
            root: manifest._read_current_target_at(leases[root].descriptor)
            for root in roots
        }

        def load(root, sha):
            return manifest.load_manifest(
                root / "manifests" / (sha + ".json"), expected_uid=0, expected_gid=0
            )

        previous = {root: load(root, old[root]) for root in roots}
        candidates = {root: load(root, target) for root in roots}
        for root in roots:
            manifest.verify_current(
                root,
                previous[root],
                expected_uid=0,
                expected_gid=0,
                session_lock=leases[root],
            )
            manifest.verify_release(
                root / target, candidates[root], expected_uid=0, expected_gid=0
            )
        if all(value == target for value in old.values()):
            audit.emit("skip_already_current")
            return
        if all(
            old[root] == target or documentation_only(previous[root], candidates[root])
            for root in roots
        ):
            audit.emit(
                "skip_documentation_only", current={r.name: s for r, s in old.items()}
            )
            return
        ci = private_json(ci_path)
        gate = private_json(catalog_path)
        now = datetime.now(timezone.utc)
        validate_ci(ci, target, now)
        # Parse data only; never import code from the uncut target.
        import yaml

        expected = {}
        for spec, root in zip(PLANES, roots):
            raw = (root / target / "config" / spec[4]).read_bytes()
            expected[root.name] = {
                "registry_sha256": hashlib.sha256(raw).hexdigest(),
                "count": len(yaml.safe_load(raw)["datasets"]),
            }
        validate_catalog_evidence(gate, target, expected, now)
        timers = host.timers()
        if "tradingdatas-provider-native-collect.timer" not in timers or not any(
            x.startswith("tradingdatas-crypto-") for x in timers
        ):
            raise ValueError("collector timer inventory is incomplete")
        api = [spec[1] for spec in PLANES]
        originals = {unit: host.state(unit) for unit in timers + api}
        for unit, state in originals.items():
            if state["ActiveState"] not in {"active", "inactive"} or (
                unit.endswith(".timer")
                and state["UnitFileState"] not in {"enabled", "disabled"}
            ):
                raise ValueError(
                    "initial unit state is unsupported; no mutation performed"
                )
        audit.emit(
            "preflight",
            rollback={r.name: s for r, s in old.items()},
            ci_run=ci["run_id"],
            ci_checked_at=ci["checked_at"],
            gate_measured_at=gate["measured_at"],
            ci_sha256=hashlib.sha256(
                json.dumps(ci, sort_keys=True).encode()
            ).hexdigest(),
            gate_sha256=hashlib.sha256(
                json.dumps(gate, sort_keys=True).encode()
            ).hexdigest(),
            registry_bindings=expected,
            units=originals,
        )
        touched = set()
        switched = []
        error = None
        restored = False

        def cleanup_emit(phase, **values):
            try:
                audit.emit(phase, **values)
            except Exception:
                pass  # audit I/O failure must never prevent rollback/restoration

        try:
            for unit in timers:
                touched.add(unit)
                host.change("stop", unit)
                host.change("disable", unit)
            drain_collectors(host, timers, drain_seconds)
            # Evidence can expire while draining; do not cut on stale approval.
            validate_ci(ci, target, datetime.now(timezone.utc))
            validate_catalog_evidence(
                gate, target, expected, datetime.now(timezone.utc)
            )
            for root in roots:
                if (
                    manifest._read_current_target_at(leases[root].descriptor)
                    != old[root]
                ):
                    raise ValueError("current changed before API stop")
            for unit in api:
                touched.add(unit)
                host.change("stop", unit)
                if host.state(unit)["ActiveState"] != "inactive":
                    raise RuntimeError("API did not stop")
            for root in roots:
                if (
                    manifest._read_current_target_at(leases[root].descriptor)
                    != old[root]
                ):
                    raise ValueError("current changed outside session")
                if old[root] != target:
                    manifest.switch_current(
                        root,
                        candidates[root],
                        previous[root],
                        expected_uid=0,
                        expected_gid=0,
                        session_lock=leases[root],
                    )
                    switched.append(root)
                    audit.emit("switched", plane=root.name, previous=old[root])
            for spec in PLANES:
                host.change("start", spec[1])
                host.ready(spec)
                if host.cwd(spec[1]).resolve() != base / spec[0] / target:
                    raise RuntimeError("API cwd does not match target")
            with ThreadPoolExecutor(max_workers=2) as pool:
                samples = list(pool.map(host.catalog, PLANES))
            for spec, sample in zip(PLANES, samples):
                if (
                    sample["http"] != 200
                    or sample["count"] != expected[spec[0]]["count"]
                    or sample["next_cursor"] is not None
                    or not 0 < sample["seconds"] < 15
                ):
                    raise ValueError("post-cut catalog gate failed")
            for root in roots:
                manifest.verify_current(
                    root,
                    candidates[root],
                    expected_uid=0,
                    expected_gid=0,
                    session_lock=leases[root],
                )
            audit.emit("readback", catalogs=samples)
            restore_units(host, originals, touched, audit.emit)
            for root in roots:
                manifest.verify_current(
                    root,
                    candidates[root],
                    expected_uid=0,
                    expected_gid=0,
                    session_lock=leases[root],
                )
            audit.emit("complete")
            restored = True
        except BaseException as exc:
            error = exc
            cleanup_emit("failure", type=type(exc).__name__)
            rollback_errors = []
            if switched:
                try:
                    for unit in timers:
                        if unit in touched:
                            host.change("stop", unit)
                            host.change("disable", unit)
                    drain_collectors(host, timers, drain_seconds)
                except Exception as drain_exc:
                    rollback_errors.append(
                        {"type": type(drain_exc).__name__, "phase": "rollback_drain"}
                    )
            for unit in api:
                if unit in touched:
                    try:
                        host.change("stop", unit)
                        if host.state(unit)["ActiveState"] != "inactive":
                            raise RuntimeError("rollback API did not stop")
                    except Exception as stop_exc:
                        rollback_errors.append(
                            {"unit": unit, "type": type(stop_exc).__name__}
                        )
            for root in reversed(switched) if not rollback_errors else ():
                try:
                    if (
                        manifest._read_current_target_at(leases[root].descriptor)
                        != target
                    ):
                        raise RuntimeError("foreign pointer change; rollback refused")
                    manifest.switch_current(
                        root,
                        previous[root],
                        candidates[root],
                        expected_uid=0,
                        expected_gid=0,
                        session_lock=leases[root],
                    )
                    cleanup_emit("rolled_back", plane=root.name, restored=old[root])
                except Exception as rollback_exc:
                    rollback_errors.append(
                        {"plane": root.name, "type": type(rollback_exc).__name__}
                    )
            for spec, root in zip(PLANES, roots):
                try:
                    observed = manifest._read_current_target_at(leases[root].descriptor)
                except Exception:
                    observed = None
                if observed != old[root]:
                    # A noncooperating root writer can bypass flock. Do not start
                    # any service against an unowned pointer during restoration.
                    blocked = {
                        u
                        for u in touched
                        if u == spec[1]
                        or (
                            u.endswith(".timer")
                            and (
                                u.startswith("tradingdatas-crypto-")
                                if root.name.endswith("-crypto")
                                else u == "tradingdatas-provider-native-collect.timer"
                            )
                        )
                    }
                    touched.difference_update(blocked)
                    rollback_errors.append(
                        {
                            "plane": root.name,
                            "type": "PointerNotRestored",
                            "units_left_stopped": sorted(blocked),
                        }
                    )
            if rollback_errors:
                cleanup_emit("rollback_incomplete", errors=rollback_errors)
                error = RuntimeError("rollback incomplete; inspect audit")
        finally:
            if not restored:
                restore_units(host, originals, touched, cleanup_emit)
        if error:
            raise error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True)
    p.add_argument("--ci-evidence", type=Path, required=True)
    p.add_argument("--catalog-evidence", type=Path, required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--audit", type=Path, required=True)
    a = p.parse_args()
    manifest._validate_hex(a.target, name="target")
    if os.geteuid() != 0:
        raise SystemExit("safe release requires the existing root operator")
    sys.dont_write_bytecode = True
    audit = Audit(a.audit, a.actor, a.task_id, a.target)
    try:
        session(a.target, a.ci_evidence, a.catalog_evidence, audit)
    except BaseException as exc:
        audit.emit("stopped", type=type(exc).__name__)
        raise SystemExit(2) from None
    finally:
        audit.close()


if __name__ == "__main__":
    main()
