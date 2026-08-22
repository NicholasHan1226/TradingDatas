from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ci_uses_four_xdist_shards_and_a_nightly_full_suite() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "schedule:" in workflow
    assert 'cron: "17 18 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "expected_sha:" in workflow
    assert "SOURCE_SHA:" in workflow
    assert workflow.count("Verify checkout identity") == 3
    assert "Nightly full tests" in workflow
    assert "Nightly local HTTP timing tests (serial)" in workflow
    assert "PR fast tests" in workflow
    assert "shard_id: [0, 1, 2, 3]" in workflow
    assert "--shard-id=${{ matrix.shard_id }} --num-shards=4" in workflow
    assert workflow.count("-n auto") == 2
    assert workflow.count("--dist=loadfile") == 2
    assert '-m "not slow"' in workflow
    assert "--ignore=tests/test_v1_api.py" in workflow
    assert "python -m pytest tests/test_v1_api.py -q --tb=short" in workflow


def test_canary_and_timing_runtime_suites_are_marked_slow() -> None:
    for path in (
        "tests/test_binance_oi_dump_canary.py",
        "tests/test_binance_premium_dump_canary.py",
        "tests/test_binance_spot_canary.py",
        "tests/test_binance_usdm_canary.py",
        "tests/test_crypto_loopback_runtime.py",
        "tests/test_v1_api.py",
    ):
        assert "pytestmark = pytest.mark.slow" in _read(path)


def test_automerge_binds_controller_acceptance_to_the_exact_head() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert 'CONTROLLER_ACCEPT_LABEL: controller-accepted' in workflow
    assert 'ACCEPTANCE_CANDIDATE="$(' in workflow
    assert 'contains("AUTODEV_RETURN_V1") and contains("decision=accepted")' in workflow
    assert 'candidate=([0-9a-f]{40})' in workflow
    assert '"$ACCEPTANCE_CANDIDATE" == "$HEAD_SHA"' in workflow
    assert 'gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --merge --auto' in workflow
    assert 'actions: write' in workflow
    assert 'actions/workflows/ci.yml/dispatches' in workflow
    assert 'inputs[expected_sha]=$MERGE_SHA' in workflow
    assert "--auto can return before GitHub actually merges" in workflow
    assert "MERGED_AT=\"$(jq -r '.merged_at // empty' <<<\"$PR_AFTER\")\"" in workflow
    assert 'actions/workflows/deploy.yml/dispatches' in workflow
    assert "grep -q '^static/'" in workflow


def test_automerge_keeps_m0_narrow_and_m1_controller_bound() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert 'M0_AUTOMERGE_LABEL: automerge-m0' in workflow
    assert "grep -qx 'change_class=M0'" in workflow
    assert 'grep -qx "candidate=$HEAD_SHA"' in workflow
    assert "README\\.md|CONTRIBUTING\\.md|docs/|tests/|static/" in workflow
    assert 'AUTODEV_RETURN_V1' in workflow
    assert 'if [[ "$HAS_M0" != true && "$BASE_SHA" != "$CURRENT_MAIN_SHA" ]]; then' in workflow
    assert "M0 base advanced. The exact tested head and narrow path allowlist" in workflow


def test_automerge_never_mutates_a_stale_candidate_branch() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert 'pulls/${PR_NUMBER}/update-branch' not in workflow
    assert "do not mutate the candidate branch" in workflow


def test_static_deploy_has_a_published_route_readback() -> None:
    workflow = _read(".github/workflows/deploy.yml")

    assert "workflow_dispatch:" in workflow
    assert "expected_sha:" in workflow
    assert "SOURCE_SHA:" in workflow
    assert "Verify checkout identity" in workflow
    assert "Read back published static route" in workflow
    assert "https://tradingdatas-admin.pages.dev/" in workflow
