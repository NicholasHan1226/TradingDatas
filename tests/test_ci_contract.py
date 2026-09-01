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


def test_automerge_requires_pm_merge_and_exact_head_ci() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert "PM_MERGE_LABEL: pm-merge" in workflow
    assert "github.event.label.name == 'pm-merge'" in workflow
    assert 'grep -qx "$PM_MERGE_LABEL"' in workflow
    assert "CI green but pm-merge is not present." in workflow
    assert '[[ "$HEAD_SHA" == "$RUN_HEAD_SHA" ]]' in workflow
    assert 'select(.name == "TradingDatas CI")' in workflow
    assert "CI_CONCLUSION" in workflow
    assert "controller-accepted" not in workflow
    assert "automerge-m0" not in workflow
    assert "AUTODEV_RETURN_V1" not in workflow
    assert "change_class=M0" not in workflow
    assert 'gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --merge --auto' in workflow
    assert "actions: write" in workflow
    assert "actions/workflows/ci.yml/dispatches" in workflow
    assert "inputs[expected_sha]=$MERGE_SHA" in workflow
    assert "--auto can return before GitHub actually merges" in workflow
    assert "MERGED_AT=\"$(jq -r '.merged_at // empty' <<<\"$PR_AFTER\")\"" in workflow
    assert "actions/workflows/deploy.yml/dispatches" in workflow
    assert "grep -Eq '^(static/|public-web/)'" in workflow
    assert "plus Cloudflare deploy when static or public-web changed." in workflow
    assert "GZ/immutable runtime is not auto-deployed." in workflow


def test_automerge_never_merges_workflow_changes_or_forks() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert r"grep -Eq '^\.github/workflows/'" in workflow
    assert "Workflow-governance changes require a separate trusted bootstrap merge." in workflow
    assert "Fork PRs never auto-merge." in workflow


def test_automerge_never_mutates_a_stale_candidate_branch() -> None:
    workflow = _read(".github/workflows/automerge.yml")

    assert "pulls/${PR_NUMBER}/update-branch" not in workflow
    assert "Tested SHA ${RUN_HEAD_SHA:0:8} no longer matches PR head ${HEAD_SHA:0:8}." in workflow


def test_static_deploy_has_a_published_route_readback() -> None:
    workflow = _read(".github/workflows/deploy.yml")

    assert "workflow_dispatch:" in workflow
    assert "expected_sha:" in workflow
    assert "SOURCE_SHA:" in workflow
    assert "Verify checkout identity" in workflow
    assert "Read back published static route" in workflow
    assert "https://tradingdatas-admin.pages.dev/" in workflow
    assert "Deploy public website Worker with session secret" in workflow
    assert "working-directory: public-web" in workflow
    assert "SESSION_ENCRYPTION_KEY: ${{ secrets.SESSION_ENCRYPTION_KEY }}" in workflow
    assert "umask 077" in workflow
    assert 'secrets_file="$(mktemp)"' in workflow
    assert "trap 'rm -f \"$secrets_file\"' EXIT" in workflow
    assert "jq -n '{SESSION_ENCRYPTION_KEY: env.SESSION_ENCRYPTION_KEY}'" in workflow
    assert "npx --yes wrangler@4.127.1 deploy --config wrangler.jsonc" in workflow
    assert '--secrets-file "$secrets_file"' in workflow
    assert "secret put SESSION_ENCRYPTION_KEY" not in workflow
    assert "secrets: |\n            SESSION_ENCRYPTION_KEY" not in workflow
    assert "for attempt in {1..12}" in workflow
    assert "sleep 5" in workflow
    assert '[[ "$published" != true ]]' in workflow
    assert "was not visible at $route after 12 attempts" in workflow


def test_public_worker_commits_only_the_non_secret_account_upstream() -> None:
    config = _read("public-web/wrangler.jsonc")

    assert '"ACCOUNT_API_BASE": "https://td-admin-api.tradingagent.cc"' in config
    assert "SESSION_ENCRYPTION_KEY" not in config
