from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "automerge.yml"


def _merge_script() -> str:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow["jobs"]["merge"]["steps"][0]["run"]


def test_automerge_workflow_listens_for_acceptance_label_removal() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert workflow["on"]["pull_request_target"]["types"] == [
        "labeled",
        "unlabeled",
    ]


def test_unaccepted_automerge_is_explicitly_disabled_and_latest_return_wins() -> None:
    script = _merge_script()

    assert "disable_unaccepted_auto_merge()" in script
    assert "gh pr merge \"$PR_NUMBER\" --repo \"$GITHUB_REPOSITORY\" --disable-auto" in script
    assert "Latest Controller return is not accepted." in script
    assert 'select(.body | contains("AUTODEV_RETURN_V1"))' in script
    assert 'sort_by(.created_at) | last | .body // ""' in script


def test_automerge_merge_script_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n"],
        input=_merge_script(),
        text=True,
        check=True,
    )
