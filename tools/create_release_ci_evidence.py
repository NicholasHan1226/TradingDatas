#!/usr/bin/env python3
"""Capture exact-main CI evidence using the operator's existing local gh login."""

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.safe_release import REPOSITORY, WORKFLOW, validate_ci  # noqa: E402 - disable bytecode before importing release-local code
from tools.release_manifest import _validate_hex  # noqa: E402 - disable bytecode before importing release-local code


def capture(target, gh=None):
    _validate_hex(target, name="target")

    def request(endpoint):
        if gh is not None:
            return gh(endpoint)
        return json.loads(
            subprocess.check_output(
                ["gh", "api", endpoint], text=True, stderr=subprocess.PIPE, timeout=30
            )
        )

    endpoint = f"repos/{REPOSITORY}/git/ref/heads/main"
    if request(endpoint)["object"]["sha"] != target:
        raise ValueError("target is not GitHub main")
    runs = request(
        f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?branch=main&head_sha={target}&per_page=30"
    )["workflow_runs"]
    runs = [run for run in runs if run["event"] in {"push", "workflow_dispatch"}]
    if not runs:
        raise ValueError("exact-main CI run is missing")
    run = max(runs, key=lambda value: (value["run_number"], value["run_attempt"]))
    if request(endpoint)["object"]["sha"] != target:
        raise ValueError("GitHub main changed during CI capture")
    if run["head_repository"]["full_name"] != REPOSITORY:
        raise ValueError("CI belongs to another repository")
    result = {
        "version": 1,
        "repository": REPOSITORY,
        "workflow_path": run["path"],
        "target": target,
        "main_sha": target,
        "head_sha": run["head_sha"],
        "head_branch": run["head_branch"],
        "event": run["event"],
        "status": run["status"],
        "conclusion": run["conclusion"],
        "run_id": run["id"],
        "run_url": run["html_url"],
        "created_at": run["created_at"],
        "completed_at": run["updated_at"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    assert WORKFLOW == ".github/workflows/ci.yml"
    validate_ci(result, target, datetime.now(timezone.utc))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = capture(a.target)
    with os.fdopen(
        os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
        "w",
    ) as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                "target": a.target,
                "run_id": result["run_id"],
                "conclusion": result["conclusion"],
            }
        )
    )


if __name__ == "__main__":
    main()
