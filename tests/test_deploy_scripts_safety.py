import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_GUARDED_CRON_SCRIPTS = (
    "capability_scan.sh",
    "cn_futures_5min.sh",
    "cn_futures_daily.sh",
    "collectors.sh",
    "crypto_collect.sh",
    "duckdb_sync.sh",
    "green_gate_report.sh",
    "health_sla.sh",
    "opening_gate.sh",
    "patrol.sh",
    "pm_collect.sh",
    "source_governance_monitor.sh",
    "sqlite_maintenance.sh",
    "sw2021_reference_collect.sh",
    "tushare_events_collect.sh",
    "tushare_low_frequency_collect.sh",
    "watchdog.sh",
)


def _read_script(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_deploy_snapshot_uses_temp_file_space_gate_and_validation() -> None:
    script = _read_script("deploy.sh")

    assert "DB_BACKUP_TMP" in script
    assert "df -PB1" in script
    assert "validate_sqlite_snapshot" in script
    assert "backup_sqlite_database" in script
    assert "source.backup(target)" in script
    assert 'cp "$SQLITE_DB" "$DB_BACKUP_TMP"' not in script
    assert "mv \"$DB_BACKUP_TMP\" \"$DB_BACKUP\"" in script
    assert "refusing deployment before pull or migration" in script
    assert "exit 77" in script
    assert "skipping DB snapshot" not in script.split(
        'if [ "$DB_AVAIL" -lt "$MIN_AVAIL" ]', 1
    )[1].split("else", 1)[0]
    assert script.index('git tag "$TAG"') > script.index(
        'success "SQLite snapshot saved and validated"'
    )
    assert script.index('git tag "$TAG"') < script.index("# ---- Phase 2: Pull new code ----")
    assert (
        "bash \"${REPO_DIR}/rollback.sh\" \"$TAG\" \"$TIMESTAMP\" "
        "\"${DEPLOYED_HEAD:-}\"" in script
    )


def test_rollback_does_not_fallback_to_unrelated_latest_backup() -> None:
    script = _read_script("rollback.sh")

    assert "head -1" not in script
    assert "No exact SQLite backup found for $TAG" in script
    assert "validate_sqlite_snapshot" in script
    assert "backup_sqlite_database" in script
    assert "RESTORE_TMP" in script
    assert 'mv -f "$RESTORE_TMP" "$SQLITE_DB"' in script
    assert "rm -f \"${SQLITE_DB}-wal\" \"${SQLITE_DB}-shm\"" in script
    assert "sharedsignals-api.service" in script


def test_deploy_and_manual_rollback_share_a_nonblocking_lock() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for script in (deploy, rollback):
        assert "SHAREDSIGNALS_DEPLOY_LOCK_FILE" in script
        assert "flock -n 9" in script

    assert "SHAREDSIGNALS_DEPLOY_LOCK_HELD=1" in deploy
    assert '"${SHAREDSIGNALS_DEPLOY_LOCK_HELD:-0}" = "1"' in rollback


def test_rollback_refuses_to_overwrite_a_newer_deployment() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    assert "DEPLOYED_HEAD=$(git rev-parse HEAD)" in deploy
    assert 'EXPECTED_CURRENT_HEAD="${3:-}"' in rollback
    assert '"$CURRENT" != "$EXPECTED_CURRENT_HEAD"' in rollback
    assert '"$CURRENT" != "$TARGET"' in rollback
    assert "Stale rollback refused" in rollback
    pull_position = deploy.index('git merge --ff-only "$REMOTE_REF"')
    captured_head_position = deploy.index("DEPLOYED_HEAD=$(git rev-parse HEAD)", pull_position)
    success_log_position = deploy.index('success "Pulled:', pull_position)
    assert captured_head_position < success_log_position


def test_code_only_release_and_rollback_share_path_contract_and_never_touch_database() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")
    helper = _read_script("deploy/runtime_paths.sh")

    for script in (deploy, rollback):
        assert 'source "$PATH_CONTRACT"' in script
        assert "sharedsignals_load_runtime_paths" in script
        assert "sharedsignals_assert_runtime_paths" in script
        assert 'git status --porcelain --untracked-files=no' in script
        assert 'CODE_ONLY=0' in script

    assert 'git merge --ff-only "$REMOTE_REF"' in deploy
    assert 'CODE-ONLY: schema migration explicitly skipped' in deploy
    assert 'CODE-ONLY: explicitly skipping SQLite snapshot and all database mutation' in deploy
    assert 'rollback.sh" --code-only' in deploy
    assert 'CODE-ONLY: SQLite restore explicitly skipped' in rollback
    assert "SHAREDSIGNALS_READ_MODEL_DIR" in helper
    assert "SHAREDSIGNALS_ENV_FILE" in helper
    assert "SHAREDSIGNALS_MARKETDATA_DB" in helper
    assert "SHAREDSIGNALS_BACKUP_DIR" in helper
    assert "SHAREDSIGNALS_RUNTIME_BACKUP_DIR" in helper
    assert "SHAREDSIGNALS_DATA_UUID" in helper
    assert 'mountpoint -q' in helper
    assert 'findmnt -n -o UUID' in helper
    assert "data mount UUID mismatch" in helper
    assert "service mount guard missing or unsafe" in helper
    assert "runtime authority path may not be a symlink" in helper
    assert "runtime env may not redirect the repository root" in helper
    assert "production repository may not disable mount checks" in helper


def test_code_only_bootstrap_requires_a_clean_fresh_separate_candidate() -> None:
    deploy = _read_script("deploy.sh")

    assert '--bootstrap-from-candidate' in deploy
    assert 'BOOTSTRAP_FROM_CANDIDATE=1' in deploy
    assert 'allowed only with --code-only' in deploy
    assert 'PATH_CONTRACT="${RELEASE_SOURCE_ROOT}/deploy/runtime_paths.sh"' in deploy
    assert 'Bootstrap source must be a separate detached candidate tree' in deploy
    assert 'Bootstrap source must be detached' in deploy
    assert 'rev-parse --show-toplevel' in deploy
    assert 'status --porcelain --untracked-files=no' in deploy
    assert 'BOOTSTRAP_HEAD="$(git -C "$RELEASE_SOURCE_ROOT" rev-parse HEAD)"' in deploy
    assert 'Bootstrap candidate must equal a prefetched canonical origin/main' in deploy
    assert 'Bootstrap candidate changed after preflight' in deploy
    assert '"$BOOTSTRAP_HEAD" != "$REMOTE"' in deploy
    assert 'is not fresh $REMOTE_REF' in deploy
    assert deploy.index('"$BOOTSTRAP_HEAD" != "$REMOTE"') < deploy.index(
        'git merge --ff-only "$REMOTE_REF"'
    )
    assert deploy.index('Bootstrap candidate must equal a prefetched canonical origin/main') < deploy.index(
        'source "$PATH_CONTRACT"'
    )


def test_code_only_bootstrap_runs_from_detached_candidate_without_touching_database(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"

    def run(*args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    run("git", "init", "--bare", str(remote))
    run("git", "init", str(canonical))
    run("git", "config", "user.name", "SharedSignals Test", cwd=canonical)
    run("git", "config", "user.email", "sharedsignals-test@example.invalid", cwd=canonical)
    for relative in (
        "deploy.sh",
        "deploy/runtime_paths.sh",
        "deploy/systemd/sharedsignals-api.service",
        "storage/schema.py",
        "bridge/marketgraph_marketdata_db.py",
        "reference/market_calendar.py",
    ):
        source = ROOT / relative
        target = canonical / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    run("git", "add", ".", cwd=canonical)
    run("git", "commit", "-m", "test release", cwd=canonical)
    run("git", "branch", "-M", "main", cwd=canonical)
    run("git", "remote", "add", "origin", str(remote), cwd=canonical)
    run("git", "push", "-u", "origin", "main", cwd=canonical)
    run("git", "worktree", "add", "--detach", str(candidate), "origin/main", cwd=canonical)

    runtime = tmp_path / "runtime"
    read_model = runtime / "read_model"
    backups = tmp_path / "backups"
    runtime_backups = tmp_path / "runtime-backups"
    for path in (read_model, backups, runtime_backups):
        path.mkdir(parents=True)
    database = read_model / "marketdata.sqlite"
    database.write_bytes(b"authority-must-not-change")
    before = database.read_bytes()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_sudo = fake_bin / "sudo"
    fake_flock = fake_bin / "flock"
    for executable in (fake_python, fake_sudo, fake_flock):
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    result = subprocess.run(
        ["bash", str(candidate / "deploy.sh"), "--code-only", "--bootstrap-from-candidate"],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SHAREDSIGNALS_REPO_DIR": str(canonical),
            "SHAREDSIGNALS_ENV_FILE": str(tmp_path / "missing.env"),
            "SHAREDSIGNALS_RUNTIME_ROOT": str(runtime),
            "SHAREDSIGNALS_READ_MODEL_DIR": str(read_model),
            "SHAREDSIGNALS_MARKETDATA_DB": str(database),
            "SHAREDSIGNALS_BACKUP_DIR": str(backups),
            "SHAREDSIGNALS_RUNTIME_BACKUP_DIR": str(runtime_backups),
            "SHAREDSIGNALS_DATA_MOUNT": str(tmp_path),
            "SHAREDSIGNALS_SERVICE_MOUNT_GUARD": str(tmp_path / "unused.guard"),
            "SHAREDSIGNALS_REQUIRE_MOUNTS": "0",
            "SHAREDSIGNALS_VENV_PYTHON": str(fake_python),
            "SHAREDSIGNALS_DEPLOY_LOCK_FILE": str(tmp_path / "deploy.lock"),
            "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE": str(tmp_path / "maintenance.lock"),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Mode: code-only" in result.stdout
    assert "Bootstrap source:" in result.stdout
    assert "schema migration explicitly skipped" in result.stdout
    assert database.read_bytes() == before
    assert not list(backups.glob("marketdata_*.sqlite"))


def test_runtime_path_contract_fails_closed_on_relative_or_cross_root_database(tmp_path: Path) -> None:
    helper = ROOT / "deploy" / "runtime_paths.sh"
    simulated_repo = tmp_path / "repo"
    check_command = (
        f'source "{helper}"; sharedsignals_load_runtime_paths; load_rc=$?; '
        'if [ "$load_rc" -ne 0 ]; then exit "$load_rc"; fi; '
        'sharedsignals_assert_runtime_paths'
    )
    base_env = {
        "SHAREDSIGNALS_REPO_DIR": str(simulated_repo),
        "SHAREDSIGNALS_ENV_FILE": str(tmp_path / "missing.env"),
        "SHAREDSIGNALS_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "SHAREDSIGNALS_READ_MODEL_DIR": str(tmp_path / "runtime" / "read_model"),
        "SHAREDSIGNALS_BACKUP_DIR": str(tmp_path / "backups"),
        "SHAREDSIGNALS_RUNTIME_BACKUP_DIR": str(tmp_path / "runtime-backups"),
        "SHAREDSIGNALS_DATA_MOUNT": str(tmp_path),
        "SHAREDSIGNALS_REQUIRE_MOUNTS": "0",
    }

    import os
    import subprocess

    good = subprocess.run(
        ["bash", "-c", check_command],
        env={**os.environ, **base_env, "SHAREDSIGNALS_MARKETDATA_DB": str(tmp_path / "runtime" / "read_model" / "marketdata.sqlite")},
        capture_output=True,
        text=True,
    )
    assert good.returncode == 0, good.stderr

    canonical_repo = subprocess.run(
        ["bash", "-c", check_command],
        env={
            **os.environ,
            **base_env,
            "SHAREDSIGNALS_REPO_DIR": "/opt/investment/SharedSignals",
        },
        capture_output=True,
        text=True,
    )
    assert canonical_repo.returncode == 78
    assert "may not disable mount checks" in canonical_repo.stderr

    cross_root = subprocess.run(
        ["bash", "-c", check_command],
        env={**os.environ, **base_env, "SHAREDSIGNALS_MARKETDATA_DB": str(tmp_path / "elsewhere.sqlite")},
        capture_output=True,
        text=True,
    )
    assert cross_root.returncode == 78
    assert "must remain below READ_MODEL_DIR" in cross_root.stderr

    relative = subprocess.run(
        ["bash", "-c", check_command],
        env={**os.environ, **base_env, "SHAREDSIGNALS_BACKUP_DIR": "relative/backups"},
        capture_output=True,
        text=True,
    )
    assert relative.returncode == 78
    assert "must be absolute" in relative.stderr

    read_model = tmp_path / "runtime" / "read_model"
    read_model.mkdir(parents=True)
    target_db = tmp_path / "real.sqlite"
    target_db.touch()
    symlink_db = read_model / "marketdata.sqlite"
    symlink_db.symlink_to(target_db)
    symlink = subprocess.run(
        ["bash", "-c", check_command],
        env={**os.environ, **base_env, "SHAREDSIGNALS_MARKETDATA_DB": str(symlink_db)},
        capture_output=True,
        text=True,
    )
    assert symlink.returncode == 78
    assert "may not be a symlink" in symlink.stderr

    real_env = tmp_path / "real.env"
    real_env.write_text("SHAREDSIGNALS_REQUIRE_MOUNTS=0\n", encoding="utf-8")
    env_symlink = tmp_path / "runtime.env"
    env_symlink.symlink_to(real_env)
    unsafe_env = subprocess.run(
        ["bash", "-c", check_command],
        env={**os.environ, **base_env, "SHAREDSIGNALS_ENV_FILE": str(env_symlink)},
        capture_output=True,
        text=True,
    )
    assert unsafe_env.returncode == 78
    assert "env file missing, unreadable or unsafe" in unsafe_env.stderr


def test_deploy_and_rollback_hold_exclusive_read_model_maintenance_lock() -> None:
    deploy = _read_script("deploy.sh")
    rollback = _read_script("rollback.sh")

    for script in (deploy, rollback):
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in script
        assert "SHAREDSIGNALS_MAINTENANCE_LOCK_HELD" in script
        assert 'flock -w "$MAINTENANCE_LOCK_TIMEOUT" 8' in script
        assert "chmod 0666" not in script
        assert "chmod 0660" in script

    helper = _read_script("deploy/runtime_paths.sh")
    assert "SHAREDSIGNALS_MARKETDATA_DB" in helper
    assert 'source "$PATH_CONTRACT"' in deploy
    assert 'source "$PATH_CONTRACT"' in rollback


def test_read_model_cron_jobs_take_shared_maintenance_lock() -> None:
    helper = (ROOT / "cron" / "maintenance_lock.sh").read_text(encoding="utf-8")
    assert "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE" in helper
    assert "flock -s -n 199" in helper

    for name in MAINTENANCE_GUARDED_CRON_SCRIPTS:
        script = (ROOT / "cron" / name).read_text(encoding="utf-8")
        assert 'source "${SCRIPT_DIR}/maintenance_lock.sh"' in script, name
        assert "acquire_sharedsignals_read_model_lock" in script, name


def test_reference_and_maintenance_wrappers_are_bounded_and_atomic() -> None:
    maintenance = _read_script("cron/sqlite_maintenance.sh")
    reference = _read_script("cron/sw2021_reference_collect.sh")

    for script in (maintenance, reference):
        assert 'RUN_AS_USER="${SHAREDSIGNALS_CRON_USER:-marketgraph}"' in script
        assert 'exec runuser -u "${RUN_AS_USER}" -- "$0" "$@"' in script
        assert 'source "${ROOT}/.env"' in script
        assert 'source "${SCRIPT_DIR}/maintenance_lock.sh"' in script
        assert "acquire_sharedsignals_read_model_lock" in script
        assert "flock -n" in script
        assert 'TMP_FILE="${OUTPUT_FILE}.$$"' in script
        assert 'mv "${TMP_FILE}" "${OUTPUT_FILE}"' in script
        assert "/opt/investment/TradingAgent" not in script
        assert "/opt/investment/MarketGraph" not in script

    assert "tools/sqlite_maintenance.py" in maintenance
    assert "VACUUM" not in maintenance.upper()
    assert "-wal" not in maintenance
    assert "-shm" not in maintenance

    assert "collectors/tushare/sw2021_reference.py" in reference
    assert "sync_daily.py" not in reference
    assert "API_TO_TABLE_MAP" not in reference
    collector_pos = reference.index("collectors/tushare/sw2021_reference.py")
    assert reference.index('"$@"', collector_pos) < reference.index(
        '--snapshot-id "${SNAPSHOT_ID}"', collector_pos
    )


def test_sw2021_cron_lines_remain_commented_until_manual_pilot() -> None:
    manifest = _read_script("cron/crontab.txt")
    schedule_lines = {
        "20 3 * * * /opt/investment/SharedSignals/cron/sqlite_maintenance.sh",
        "25 6 * * 1-5 /opt/investment/SharedSignals/cron/sw2021_reference_collect.sh",
    }
    active_lines = {
        line.strip()
        for line in manifest.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert schedule_lines <= {
        line.lstrip("# ")
        for line in manifest.splitlines()
        if line.lstrip().startswith("#")
    }
    assert not schedule_lines & active_lines


def test_legacy_root_duckdb_cron_wrapper_is_retired() -> None:
    assert not (ROOT / "duckdb_merge_cron.sh").exists()


def test_deploy_installs_sharedsignals_owned_systemd_service() -> None:
    service = (ROOT / "deploy" / "systemd" / "sharedsignals-api.service").read_text(encoding="utf-8")
    deploy = _read_script("deploy.sh")

    assert "User=marketgraph" in service
    assert "ExecStart=/opt/sharedsignals/venv/bin/python3" in service
    assert "/opt/marketgraph/venv" not in service
    assert "deploy/systemd/sharedsignals-api.service" in deploy
    assert "systemctl daemon-reload" in deploy


def test_deploy_keeps_only_three_validated_sqlite_snapshots_by_default() -> None:
    deploy = _read_script("deploy.sh")

    assert 'SQLITE_BACKUP_RETENTION="${SHAREDSIGNALS_SQLITE_BACKUP_RETENTION:-3}"' in deploy
    assert "SQLITE_BACKUP_RETENTION + 1" in deploy


def test_tunnel_service_templates_keep_secrets_out_of_units_and_ports_on_loopback() -> None:
    relay = (ROOT / "deploy" / "systemd" / "sharedsignals-sg-relay-tunnel.service").read_text(encoding="utf-8")
    connector = (ROOT / "deploy" / "systemd" / "sharedsignals-cloudflared.service").read_text(encoding="utf-8")

    assert "-R 127.0.0.1:8082:127.0.0.1:8082" in relay
    assert "-R 127.0.0.1:80:127.0.0.1:80" in relay
    assert "-R 127.0.0.1:8787" not in relay
    assert "-L 127.0.0.1:18889:127.0.0.1:18888" in relay
    assert "--token-file /etc/cloudflared/sharedsignals.token" in connector
    assert "--token " not in connector
