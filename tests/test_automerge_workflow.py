from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "automerge.yml"


def _merge_script() -> str:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow["jobs"]["merge"]["steps"][0]["run"]


def test_automerge_workflow_listens_for_optional_pm_merge_label() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["on"]["pull_request_target"]["types"] == [
        "labeled",
    ]
    assert "github.event.label.name == 'pm-merge'" in workflow["jobs"]["merge"]["if"]
    assert "controller-accepted" not in workflow["jobs"]["merge"]["if"]
    assert "automerge-m0" not in workflow["jobs"]["merge"]["if"]


def test_missing_pm_merge_does_not_block_trusted_green_automerge() -> None:
    script = _merge_script()

    assert "disable_unaccepted_auto_merge()" in script
    assert "gh pr merge \"$PR_NUMBER\" --repo \"$GITHUB_REPOSITORY\" --disable-auto" in script
    assert "CI green but pm-merge is not present." not in script
    assert "AUTODEV_RETURN_V1" not in script
    assert "controller-accepted" not in script
    assert "automerge-m0" not in script


def test_automerge_merge_script_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n"],
        input=_merge_script(),
        text=True,
        check=True,
    )
