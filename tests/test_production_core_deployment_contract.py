from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_core_server_bootstrap_shell_parses() -> None:
    subprocess.run(
        ["bash", "-n", str(ROOT / "tools/bootstrap_production_core_server.sh")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_root_core_release_helper_compiles_without_side_effects() -> None:
    source = _read("tools/production_core_release.py")
    compile(source, "tools/production_core_release.py", "exec")


def test_ci_freezes_clean_manifest_before_test_side_effects() -> None:
    workflow = _read(".github/workflows/ci.yml")

    package = workflow.index("Package clean core release candidate")
    install = workflow.index("Install dependencies")
    tests = workflow.index("Run tests")
    upload = workflow.index("Upload tested core release")

    assert package < install < tests < upload
    assert "python tools/release_manifest.py build" in workflow
    assert '--source-root "$GITHUB_WORKSPACE"' in workflow
    assert 'git archive --format=tar.gz' in workflow
    assert '"$GITHUB_SHA"' in workflow
    assert "release manifest commit does not match GITHUB_SHA" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "name: tradingdatas-core-release-${{ github.sha }}" in workflow
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow


def test_core_deploy_workflow_is_exact_run_and_current_main_gated() -> None:
    workflow = _read(".github/workflows/deploy-core-production.yml")

    assert "workflow_run:" in workflow
    assert "- TradingDatas CI" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "vars.TRADINGDATAS_CORE_DEPLOY_ENABLED == 'true'" in workflow
    assert "environment: production-core" in workflow
    assert "actions: read" in workflow
    assert "actions/download-artifact@v5" in workflow
    assert "run-id: ${{ github.event.workflow_run.id }}" in workflow
    assert "name: tradingdatas-core-release-${{ github.event.workflow_run.head_sha }}" in workflow
    assert workflow.count('gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main"') == 2
    assert "Skip stale core deployment" in workflow
    assert "Main advanced during core upload" in workflow
    assert "sudo -n /usr/local/sbin/tradingdatas-core-release" in workflow
    assert "readlink /opt/investment/releases/tradingdatas/current" in workflow


def test_core_deploy_pins_installed_privileged_code_to_tested_sha() -> None:
    workflow = _read(".github/workflows/deploy-core-production.yml")

    assert "sha256sum tools/production_core_release.py" in workflow
    assert "sha256sum tools/release_manifest.py" in workflow
    assert "/usr/local/sbin/tradingdatas-core-release" in workflow
    assert "/usr/local/lib/tradingdatas-release/release_manifest.py" in workflow
    assert "remote_hashes=" in workflow
    assert "grep -Fxq \"$HELPER_CHECKSUM" in workflow
    assert "grep -Fxq \"$VERIFIER_CHECKSUM" in workflow

    # Ordinary deployments must not upload or directly execute a newly supplied
    # privileged helper/verifier from the target release.
    assert "scp tools/production_core_release.py" not in workflow
    assert "scp tools/release_manifest.py" not in workflow
    assert "sudo -n python" not in workflow


def test_core_release_helper_respects_existing_safe_release_order() -> None:
    helper = _read("tools/production_core_release.py")

    assert 'RELEASES_ROOT = Path("/opt/investment/releases/tradingdatas")' in helper
    assert 'API_UNIT = "tradingdatas-v1-internal.service"' in helper
    assert 'COLLECTOR_UNIT = "tradingdatas-provider-native-collect.service"' in helper
    assert 'TIMER_UNIT = "tradingdatas-provider-native-collect.timer"' in helper
    assert 'CATALOG_PATH = "/v1/catalog"' in helper
    assert "status != 401" in helper
    assert "disable\", \"--now\", TIMER_UNIT" in helper
    assert "_wait_collector_inactive()" in helper
    assert '"systemctl", "stop", API_UNIT' in helper
    assert "verifier.switch_current(" in helper
    assert "verifier.verify_current(" in helper
    assert "API process is not running from requested immutable release" in helper

    # A running oneshot collector is allowed to finish; normal cutover must not
    # kill it and risk interrupting transaction/receipt writes.
    assert '"systemctl", "stop", COLLECTOR_UNIT' not in helper
    assert '"systemctl", "kill", COLLECTOR_UNIT' not in helper
    assert "tradingdatas-crypto" not in helper


def test_core_release_helper_keeps_data_and_credentials_outside_release_actions() -> None:
    helper = _read("tools/production_core_release.py")

    for forbidden in (
        "/etc/tradingdatas/quicksync.token",
        "provider_native.sqlite",
        "TRADINGDATAS_DB_PATH",
        "TUSHARE_TOKEN",
        "api_tokens.json",
    ):
        assert forbidden not in helper

    assert "shutil.rmtree(staging" in helper
    assert "uploaded_archive.unlink" in helper
    assert "REQUEST_FILE.unlink" in helper
    assert "rm -rf /opt/investment-data" not in helper


def test_core_bootstrap_requires_verified_normalized_current_and_scoped_sudo() -> None:
    bootstrap = _read("tools/bootstrap_production_core_server.sh")

    assert "current must be normalized to a relative 40-char commit" in bootstrap
    assert "current rollback manifest is required" in bootstrap
    assert '"$installed_verifier" verify-current' in bootstrap
    assert "--expected-uid 0 --expected-gid 0" in bootstrap
    assert "deployment spool is not empty" in bootstrap
    assert "installed_helper=/usr/local/sbin/tradingdatas-core-release" in bootstrap
    assert "installed_verifier=\"$trusted_dir/release_manifest.py\"" in bootstrap
    assert "NOPASSWD: %s" in bootstrap
    assert "visudo -cf" in bootstrap
    assert "TRADINGDATAS_CORE_DEPLOY_ENABLED=false" in bootstrap


def test_core_lane_does_not_expand_deploy_or_crypto_service_surface() -> None:
    helper = _read("tools/production_core_release.py")
    workflow = _read(".github/workflows/deploy-core-production.yml")
    bootstrap = _read("tools/bootstrap_production_core_server.sh")

    combined = "\n".join((helper, workflow, bootstrap))
    assert "tradingdatas-crypto" not in combined
    assert "/opt/investment/releases/tradingdatas-crypto" not in combined

    deploy_tree = ROOT / "deploy"
    files = {
        path.relative_to(deploy_tree).as_posix()
        for path in deploy_tree.rglob("*")
        if path.is_file()
    }
    assert "production_core_release.py" not in files
    assert "bootstrap_production_core_server.sh" not in files
