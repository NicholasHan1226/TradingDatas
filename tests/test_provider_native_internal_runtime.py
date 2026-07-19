from __future__ import annotations

import os
import importlib.util
import json
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from storage.schema_contract import PROVIDER_DATASET_ROWS_INDEX_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "provider_native_internal.env"
UNIT = ROOT / "deploy" / "systemd" / "sharedsignals-v1-internal.service"
CONDITIONED_UNITS = (
    UNIT,
    ROOT / "deploy" / "systemd" / "sharedsignals-provider-native-collect.service",
    ROOT / "deploy" / "systemd" / "sharedsignals-v1-probe.service",
)
RELEASE = ROOT / "deploy" / "provider_native_internal_release.sh"
INIT = ROOT / "tools" / "init_provider_native_store.py"
V1_WRAPPER = ROOT / "tools" / "serve_provider_native_v1.py"
NEW_DB = Path("/opt/investment-data/sharedsignals-v1/read_model/provider_native.sqlite")
OLD_DB = Path("/opt/investment-data/SharedSignals/runtime/read_model/marketdata.sqlite")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _bash(script: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )


def _crash_atomic_store_initializer(
    boundary: str,
    database_path: Path,
    legacy_path: Path,
    maintenance_lock_path: Path,
) -> subprocess.CompletedProcess[str]:
    script = """
import os
import sys
from pathlib import Path

import tools.init_provider_native_store as init_store

target = sys.argv[1]
def crash_boundary(boundary):
    if boundary == target:
        os._exit(88)

init_store._initialization_boundary = crash_boundary
init_store.initialize_provider_native_store(
    Path(sys.argv[2]),
    legacy_db_path=Path(sys.argv[3]),
    maintenance_lock_path=Path(sys.argv[4]),
)
"""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            boundary,
            str(database_path),
            str(legacy_path),
            str(maintenance_lock_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_git_owned_internal_profile_is_fixed_loopback_and_contains_no_secrets() -> None:
    lines = [
        line
        for line in PROFILE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    values = dict(line.split("=", 1) for line in lines)

    assert values == {
        "REAL_TRADING_ENABLED": "false",
        "SHAREDSIGNALS_API_HOST": "127.0.0.1",
        "SHAREDSIGNALS_API_PORT": "18082",
        "SHAREDSIGNALS_API_SURFACE": "provider-native-v1-only",
        "SHAREDSIGNALS_DATASET_REGISTRY_PATH": (
            "/opt/investment/releases/sharedsignals-v1/current/"
            "config/provider_native_dataset_registry.yaml"
        ),
        "SHAREDSIGNALS_INTERNAL_RUNTIME_PROFILE": "provider-native-v1-internal",
        "SHAREDSIGNALS_LOCALHOST_BYPASS": "0",
        "SHAREDSIGNALS_MAINTENANCE_LOCK_FILE": (
            "/opt/investment-data/sharedsignals-v1/locks/read_model_maintenance.lock"
        ),
        "SHAREDSIGNALS_MARKETDATA_DB": str(NEW_DB),
        "SHAREDSIGNALS_READ_MODEL_LOCK_TIMEOUT": "30",
        "SHAREDSIGNALS_READ_MODEL_READ_LOCK_TIMEOUT": "5",
        "SHAREDSIGNALS_ROOT": ("/opt/investment/releases/sharedsignals-v1/current"),
        "SHAREDSIGNALS_RUNTIME_ROOT": ("/opt/investment-data/sharedsignals-v1"),
    }
    upper = PROFILE.read_text(encoding="utf-8").upper()
    for forbidden in (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PRIVATE_KEY",
        "ACCESS_KEY",
        "TUSHARE_",
    ):
        assert forbidden not in upper
    assert str(OLD_DB) not in PROFILE.read_text(encoding="utf-8")


def test_internal_unit_is_loopback_authenticated_and_isolated_from_legacy_service() -> (
    None
):
    source = UNIT.read_text(encoding="utf-8")

    assert "Description=SharedSignals provider-native V1 internal API" in source
    assert "User=marketgraph" in source
    assert "Group=marketgraph" in source
    assert (
        "EnvironmentFile=/opt/investment/releases/sharedsignals-v1/current/"
        "deploy/provider_native_internal.env" in source
    )
    assert (
        "EnvironmentFile=/etc/sharedsignals/provider-native-internal.secrets" in source
    )
    assert 'Environment="SHAREDSIGNALS_LOCALHOST_BYPASS=0"' in source
    assert (
        "ExecStart=/opt/investment/releases/sharedsignals-v1/current/"
        "deploy/provider_native_internal_release.sh serve" in source
    )
    assert "ReadOnlyPaths=/opt/investment-data/sharedsignals-v1" in source
    assert "ReadWritePaths=" not in source
    assert "NoNewPrivileges=true" in source
    assert "ProtectSystem=strict" in source
    assert "PrivateTmp=true" in source
    assert "sharedsignals-api.service" not in source
    assert "/opt/investment/SharedSignals/.env" not in source
    assert "8082" not in source
    assert "nginx reload" not in source.lower()
    assert "cloudflared tunnel" not in source.lower()


def test_v1_wrapper_dispatches_every_method_only_through_v1_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHAREDSIGNALS_API_SURFACE", "provider-native-v1-only")
    monkeypatch.setenv(
        "SHAREDSIGNALS_INTERNAL_RUNTIME_PROFILE", "provider-native-v1-internal"
    )
    monkeypatch.setenv("SHAREDSIGNALS_API_HOST", "127.0.0.1")
    monkeypatch.setenv("SHAREDSIGNALS_API_PORT", "18082")
    monkeypatch.setenv("SHAREDSIGNALS_LOCALHOST_BYPASS", "0")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "false")
    spec = importlib.util.spec_from_file_location(
        "provider_native_v1_wrapper", V1_WRAPPER
    )
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)

    handler = object.__new__(wrapper.ProviderNativeV1Handler)
    calls: list[str] = []
    handler._handle_v1 = calls.append
    for path, method_name, expected in (
        ("/v1/catalog", "do_GET", "GET"),
        ("/v1/query", "do_POST", "POST"),
        ("/v1/catalog", "do_OPTIONS", "OPTIONS"),
        ("/health", "do_GET", "GET"),
        ("/tushare", "do_POST", "POST"),
        ("/cache/invalidate", "do_DELETE", "DELETE"),
    ):
        handler.path = path
        getattr(handler, method_name)()
        assert calls.pop() == expected
    assert not calls

    source = V1_WRAPPER.read_text(encoding="utf-8")
    assert "_ensure_runtime_loaded" not in source
    assert "api_server.main" not in source
    assert "ProviderNativeV1Handler" in source


def test_init_creates_one_new_store_and_required_coordination_locks(
    tmp_path: Path,
) -> None:
    from tools.init_provider_native_store import initialize_provider_native_store

    runtime = tmp_path / "runtime"
    read_model = runtime / "read_model"
    locks = runtime / "locks"
    db_path = read_model / "provider_native.sqlite"
    maintenance_lock = locks / "read_model_maintenance.lock"

    result = initialize_provider_native_store(
        db_path,
        legacy_db_path=tmp_path / "legacy" / "marketdata.sqlite",
        maintenance_lock_path=maintenance_lock,
    )

    database_lock = read_model / ".provider_native.sqlite.read_model_store.lock"
    assert result.database_path == db_path.resolve(strict=True)
    assert result.database_lock_path == database_lock.resolve(strict=True)
    assert result.maintenance_lock_path == maintenance_lock.resolve(strict=True)
    assert _mode(db_path) == 0o600
    assert _mode(database_lock) == 0o600
    assert _mode(maintenance_lock) == 0o600
    assert db_path.stat().st_uid == os.geteuid()
    assert database_lock.stat().st_uid == os.geteuid()
    assert maintenance_lock.stat().st_uid == os.geteuid()
    with sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "provider_dataset_rows" in tables
        assert "market_ingest_runs" in tables
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert set(PROVIDER_DATASET_ROWS_INDEX_COLUMNS).issubset(indexes)


@pytest.mark.parametrize("existing_kind", ["database", "database_symlink"])
def test_init_refuses_existing_or_linked_database(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    from tools.init_provider_native_store import StoreInitializationError
    from tools.init_provider_native_store import initialize_provider_native_store

    read_model = tmp_path / "runtime" / "read_model"
    locks = tmp_path / "runtime" / "locks"
    read_model.mkdir(parents=True)
    locks.mkdir()
    db_path = read_model / "provider_native.sqlite"
    if existing_kind == "database":
        db_path.write_bytes(b"must-not-change")
    else:
        target = tmp_path / "elsewhere.sqlite"
        target.write_bytes(b"must-not-change")
        db_path.symlink_to(target)
    before = db_path.read_bytes()

    with pytest.raises(StoreInitializationError, match="partial or unsafe"):
        initialize_provider_native_store(
            db_path,
            legacy_db_path=tmp_path / "legacy.sqlite",
            maintenance_lock_path=locks / "read_model_maintenance.lock",
        )

    assert db_path.read_bytes() == before
    assert not (read_model / ".provider_native.sqlite.read_model_store.lock").exists()
    assert not (locks / "read_model_maintenance.lock").exists()


def test_init_refuses_legacy_path_and_unsafe_coordination_artifacts(
    tmp_path: Path,
) -> None:
    from tools.init_provider_native_store import StoreInitializationError
    from tools.init_provider_native_store import initialize_provider_native_store

    read_model = tmp_path / "runtime" / "read_model"
    locks = tmp_path / "runtime" / "locks"
    read_model.mkdir(parents=True)
    locks.mkdir()
    db_path = read_model / "provider_native.sqlite"
    database_lock = read_model / ".provider_native.sqlite.read_model_store.lock"
    unsafe_target = tmp_path / "unsafe.lock"
    unsafe_target.touch()
    database_lock.symlink_to(unsafe_target)

    with pytest.raises(StoreInitializationError, match="partial or unsafe"):
        initialize_provider_native_store(
            db_path,
            legacy_db_path=tmp_path / "legacy.sqlite",
            maintenance_lock_path=locks / "read_model_maintenance.lock",
        )
    assert not db_path.exists()

    runtime = tmp_path / "fresh-runtime"
    legacy = runtime / "read_model" / "provider_native.sqlite"
    with pytest.raises(StoreInitializationError, match="legacy database"):
        initialize_provider_native_store(
            legacy,
            legacy_db_path=legacy,
            maintenance_lock_path=runtime / "locks" / "read_model_maintenance.lock",
        )
    assert not legacy.exists()


def test_init_compensates_all_new_artifacts_when_schema_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.init_provider_native_store as init_store

    runtime = tmp_path / "runtime"
    read_model = runtime / "read_model"
    locks = runtime / "locks"
    db_path = read_model / "provider_native.sqlite"
    maintenance_lock = locks / "read_model_maintenance.lock"
    monkeypatch.setattr(init_store, "SCHEMA_SQL", "CREATE TABLE broken (")

    with pytest.raises(
        init_store.StoreInitializationError, match="initialization failed"
    ):
        init_store.initialize_provider_native_store(
            db_path,
            legacy_db_path=tmp_path / "legacy.sqlite",
            maintenance_lock_path=maintenance_lock,
        )

    assert not runtime.exists()
    assert len(list(tmp_path.glob(".runtime.init-*"))) == 1


def test_init_leaves_unpublished_staging_when_exclusive_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.init_provider_native_store as init_store

    runtime = tmp_path / "runtime"
    read_model = runtime / "read_model"
    locks = runtime / "locks"
    db_path = read_model / "provider_native.sqlite"
    maintenance_lock = locks / "read_model_maintenance.lock"
    monkeypatch.setattr(
        init_store,
        "_publish_directory_noreplace",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated publish failure")),
    )
    with pytest.raises(
        init_store.StoreInitializationError, match="initialization failed"
    ):
        init_store.initialize_provider_native_store(
            db_path,
            legacy_db_path=tmp_path / "legacy.sqlite",
            maintenance_lock_path=maintenance_lock,
        )

    assert not runtime.exists()
    assert len(list(tmp_path.glob(".runtime.init-*"))) == 1


@pytest.mark.parametrize(
    "crash_boundary",
    (
        "after_staging_root",
        "after_staging_directories",
        "after_coordination_files",
        "after_sqlite_build",
        "before_publish",
        "after_publish",
        "after_parent_fsync",
    ),
)
def test_atomic_root_init_recovers_after_process_crash(
    tmp_path: Path,
    crash_boundary: str,
) -> None:
    from tools.init_provider_native_store import initialize_provider_native_store

    runtime = tmp_path / "runtime"
    db_path = runtime / "read_model" / "provider_native.sqlite"
    maintenance_lock = runtime / "locks" / "read_model_maintenance.lock"
    legacy = tmp_path / "legacy.sqlite"
    legacy.write_bytes(b"legacy-must-not-change")
    legacy_before = (
        legacy.stat().st_dev,
        legacy.stat().st_ino,
        legacy.read_bytes(),
    )

    crashed = _crash_atomic_store_initializer(
        crash_boundary,
        db_path,
        legacy,
        maintenance_lock,
    )
    assert crashed.returncode == 88, crashed.stdout + crashed.stderr
    published_identity = None
    if runtime.exists():
        published_identity = (runtime.stat().st_dev, runtime.stat().st_ino)

    result = initialize_provider_native_store(
        db_path,
        legacy_db_path=legacy,
        maintenance_lock_path=maintenance_lock,
    )

    assert result.database_path == db_path
    assert db_path.is_file()
    assert maintenance_lock.is_file()
    if published_identity is not None:
        assert (runtime.stat().st_dev, runtime.stat().st_ino) == published_identity
    assert (legacy.stat().st_dev, legacy.stat().st_ino, legacy.read_bytes()) == (
        legacy_before
    )


def test_atomic_root_init_is_idempotent_and_preserves_later_valid_data(
    tmp_path: Path,
) -> None:
    from tools.init_provider_native_store import initialize_provider_native_store

    runtime = tmp_path / "runtime"
    db_path = runtime / "read_model" / "provider_native.sqlite"
    database_lock = (
        runtime / "read_model" / (".provider_native.sqlite.read_model_store.lock")
    )
    maintenance_lock = runtime / "locks" / "read_model_maintenance.lock"
    legacy = tmp_path / "legacy.sqlite"
    legacy.write_bytes(b"legacy")
    first = initialize_provider_native_store(
        db_path,
        legacy_db_path=legacy,
        maintenance_lock_path=maintenance_lock,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO market_ingest_runs "
            "(run_id, started_at, finished_at, status, source, rows_read, "
            "rows_written, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("later", "2026-07-19T00:00:00Z", None, "running", "test", 0, 0, None),
        )
    before = {
        path: (path.stat().st_dev, path.stat().st_ino, path.read_bytes())
        for path in (db_path, database_lock, maintenance_lock)
    }

    second = initialize_provider_native_store(
        db_path,
        legacy_db_path=legacy,
        maintenance_lock_path=maintenance_lock,
    )

    assert second == first
    assert {
        path: (path.stat().st_dev, path.stat().st_ino, path.read_bytes())
        for path in before
    } == before


def test_atomic_root_init_ignores_but_never_deletes_stale_staging(
    tmp_path: Path,
) -> None:
    from tools.init_provider_native_store import initialize_provider_native_store

    stale = tmp_path / ".runtime.init-untrusted"
    stale.mkdir()
    marker = stale / "must-remain"
    marker.write_bytes(b"foreign")
    runtime = tmp_path / "runtime"

    initialize_provider_native_store(
        runtime / "read_model" / "provider_native.sqlite",
        legacy_db_path=tmp_path / "legacy.sqlite",
        maintenance_lock_path=runtime / "locks" / "read_model_maintenance.lock",
    )

    assert marker.read_bytes() == b"foreign"


def test_atomic_root_init_refuses_partial_final_root_without_mutation(
    tmp_path: Path,
) -> None:
    from tools.init_provider_native_store import StoreInitializationError
    from tools.init_provider_native_store import initialize_provider_native_store

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    marker = runtime / "must-remain"
    marker.write_bytes(b"foreign")

    with pytest.raises(StoreInitializationError, match="partial"):
        initialize_provider_native_store(
            runtime / "read_model" / "provider_native.sqlite",
            legacy_db_path=tmp_path / "legacy.sqlite",
            maintenance_lock_path=runtime / "locks" / "read_model_maintenance.lock",
        )

    assert marker.read_bytes() == b"foreign"


def test_init_cli_has_no_database_path_selector() -> None:
    source = INIT.read_text(encoding="utf-8")
    assert "DEFAULT_DATABASE_PATH" in source
    assert str(NEW_DB) in source
    assert str(OLD_DB) in source
    assert "--database" not in source
    assert "--db" not in source


def test_release_control_plane_has_fixed_scope_and_fail_closed_commands() -> None:
    source = RELEASE.read_text(encoding="utf-8")

    for command in (
        "enable-ops",
        "init-store",
        "preflight",
        "apply",
        "readback",
        "rollback",
        "serve",
    ):
        assert command in source
    assert 'SERVICE="sharedsignals-v1-internal.service"' in source
    assert 'LEGACY_SERVICE="sharedsignals-api.service"' in source
    assert 'CURRENT_LINK="/opt/investment/releases/sharedsignals-v1/current"' in source
    assert 'RUNTIME_ROOT="/opt/investment-data/sharedsignals-v1"' in source
    assert f'DATABASE="{NEW_DB}"' in source
    assert f'LEGACY_DATABASE="{OLD_DB}"' in source
    assert 'SECRET_ENV="/etc/sharedsignals/provider-native-internal.secrets"' in source
    assert 'PORT="18082"' in source
    assert 'LEGACY_PORT="8082"' in source
    for unit in (
        "sharedsignals-provider-native-collect.service",
        "sharedsignals-provider-native-collect.timer",
        "sharedsignals-v1-probe.service",
        "sharedsignals-v1-probe.timer",
    ):
        assert unit in source
    assert 'git -C "$SOURCE_ROOT" archive' in source
    assert 'git -C "$SOURCE_ROOT" status --porcelain' in source
    assert "flock -n" in source
    assert '"$SHA256SUM" -c' in source
    assert "PRAGMA quick_check" in source
    assert (
        "from tools.init_provider_native_store import initialize_provider_native_store"
        in source
    )
    assert "provider_dataset_rows" in source
    assert "market_ingest_runs" in source
    assert "ln -s" in source and "mv -Tf" in source
    assert '"$SYSTEMCTL" daemon-reload' in source
    assert '"$SYSTEMCTL" restart "$SERVICE"' in source
    assert '"$SYSTEMCTL" restart "$LEGACY_SERVICE"' not in source
    assert '"$SYSTEMCTL" stop "$LEGACY_SERVICE"' not in source
    assert '"$SYSTEMCTL" disable "$LEGACY_SERVICE"' not in source
    assert 'rm -rf "$RELEASES_DIR' not in source
    assert 'rm -f "$DATABASE"' not in source
    assert "nginx reload" not in source.lower()
    assert "cloudflared tunnel" not in source.lower()
    assert "export PYTHONDONTWRITEBYTECODE=1" in source
    assert '"$VENV_PYTHON" -B -P' in source
    assert "trap 'handle_apply_error \"$state\"' ERR" in source
    assert "automatic rollback failed" in source
    assert '"$release_path/tools/init_provider_native_store.py"' in source
    assert "validate_runtime_parent" in source
    assert "prepare_runtime_directories" not in source
    init_store_source = source.split("init_store_release() {", 1)[1].split(
        "assert_ops_disabled_after_apply() {", 1
    )[0]
    assert "install -d" not in init_store_source
    post_init = init_store_source.index("unset output")
    post_init_validation = init_store_source.index(
        'validate_release "$release_path" "$expected_commit"', post_init
    )
    assert post_init < post_init_validation < init_store_source.index(
        "require_runtime_store_complete", post_init
    )

    serve_source = source.split("serve() {", 1)[1].split("usage() {", 1)[0]
    assert "validate_secret_env" not in serve_source
    assert "SHAREDSIGNALS_TOKEN_HASH_FILE" in serve_source
    assert "SHAREDSIGNALS_TOKEN_SALT" in serve_source
    assert "SHAREDSIGNALS_CURSOR_SIGNING_KEY" in serve_source


def test_release_control_never_writes_python_bytecode_into_release_tree(
    tmp_path: Path,
) -> None:
    module_root = tmp_path / "immutable-release"
    module_root.mkdir()
    (module_root / "release_probe.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _bash(
        f"unset PYTHONDONTWRITEBYTECODE; "
        f"source {shlex.quote(str(RELEASE))}; "
        f"cd {shlex.quote(str(tmp_path))}; "
        f"PYTHONPATH={shlex.quote(str(module_root))} "
        f"{shlex.quote(sys.executable)} -P -c 'import release_probe; assert release_probe.VALUE == 1'; "
        f"test ! -e {shlex.quote(str(module_root / '__pycache__'))}"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_systemd_units_use_supported_required_path_conditions() -> None:
    for path in CONDITIONED_UNITS:
        source = path.read_text(encoding="utf-8")
        assert "ConditionPathIsRegular=" not in source
        assert "ConditionPathExists=" in source


def test_ops_unit_validation_binds_public_profile_and_secret_lane(
    tmp_path: Path,
) -> None:
    collect = tmp_path / "collect.service"
    collect.write_text(
        "[Service]\n"
        "EnvironmentFile=/opt/investment/releases/sharedsignals-v1/current/deploy/provider_native_internal.env\n"
        "EnvironmentFile=/etc/sharedsignals/provider-native-collector.secrets\n"
        "TimeoutStartSec=900s\n"
        "ExecStart=/opt/sharedsignals/venv/bin/python3 /opt/investment/releases/sharedsignals-v1/current/tools/run_provider_native_schedule.py --execute\n",
        encoding="utf-8",
    )
    prefix = f"source {shlex.quote(str(RELEASE))}; "
    valid = _bash(
        prefix
        + f"validate_ops_unit_source {shlex.quote(str(collect))} "
        + "sharedsignals-provider-native-collect.service"
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr

    collect.write_text(
        collect.read_text(encoding="utf-8").replace(
            "/opt/investment/releases/sharedsignals-v1/current/deploy/provider_native_internal.env",
            "/tmp/unapproved.env",
        ),
        encoding="utf-8",
    )
    wrong_profile = _bash(
        prefix
        + f"validate_ops_unit_source {shlex.quote(str(collect))} "
        + "sharedsignals-provider-native-collect.service"
    )
    assert wrong_profile.returncode != 0
    assert "public profile path is invalid" in wrong_profile.stderr

    timer = tmp_path / "probe.timer"
    timer.write_text(
        "[Timer]\n"
        "EnvironmentFile=/etc/sharedsignals/provider-native-probe.secrets\n"
        "Unit=sharedsignals-v1-probe.service\n",
        encoding="utf-8",
    )
    secret_timer = _bash(
        prefix
        + f"validate_ops_unit_source {shlex.quote(str(timer))} "
        + "sharedsignals-v1-probe.timer"
    )
    assert secret_timer.returncode != 0
    assert "timer may not load an EnvironmentFile" in secret_timer.stderr


def test_release_library_builds_and_verifies_immutable_manifest(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    for relative in (
        "api_server.py",
        "dataset_registry.py",
        "config/dataset_registry.yaml",
        "config/provider_native_dataset_registry.yaml",
        "deploy/provider_native_internal.env",
        "deploy/provider_native_internal_release.sh",
        "deploy/systemd/sharedsignals-v1-internal.service",
        "tools/init_provider_native_store.py",
        "tools/serve_provider_native_v1.py",
    ):
        source = ROOT / relative
        target = source_repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    activation = source_repo / "config/provider_native_activation.yaml"
    activation.write_text(
        "version: 1\n"
        "activations:\n"
        "- dataset_id: cn.equity.daily\n"
        "  provider: tushare\n"
        "  entitlement_state: active\n"
        "  activation_state: active\n"
        "  evidence_ref: test/daily\n"
        "- dataset_id: cn.equity.security_master\n"
        "  provider: tushare\n"
        "  entitlement_state: active\n"
        "  activation_state: active\n"
        "  evidence_ref: test/security-master\n"
        "- dataset_id: cn.market.trade_calendar\n"
        "  provider: tushare\n"
        "  entitlement_state: active\n"
        "  activation_state: active\n"
        "  evidence_ref: test/trade-calendar\n",
        encoding="utf-8",
    )
    (source_repo / "config/provider_native_schedule.yaml").write_text(
        "version: 1\n", encoding="utf-8"
    )
    for relative in (
        "tools/internal_v1_probe.py",
        "tools/run_provider_native_schedule.py",
    ):
        target = source_repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    registry = source_repo / "config/provider_native_dataset_registry.yaml"
    registry.write_text(
        registry.read_text(encoding="utf-8")
        .replace("entitlement_state: unknown", "entitlement_state: active")
        .replace("activation_state: paused", "activation_state: active"),
        encoding="utf-8",
    )
    systemd = source_repo / "deploy/systemd"
    (systemd / "sharedsignals-provider-native-collect.service").write_text(
        "[Service]\n"
        "EnvironmentFile=/opt/investment/releases/sharedsignals-v1/current/deploy/provider_native_internal.env\n"
        "EnvironmentFile=/etc/sharedsignals/provider-native-collector.secrets\n"
        "TimeoutStartSec=900s\n"
        "ExecStart=/opt/sharedsignals/venv/bin/python3 /opt/investment/releases/sharedsignals-v1/current/tools/run_provider_native_schedule.py --execute\n",
        encoding="utf-8",
    )
    (systemd / "sharedsignals-provider-native-collect.timer").write_text(
        "[Timer]\nUnit=sharedsignals-provider-native-collect.service\n",
        encoding="utf-8",
    )
    (systemd / "sharedsignals-v1-probe.service").write_text(
        "[Service]\n"
        "EnvironmentFile=/opt/investment/releases/sharedsignals-v1/current/deploy/provider_native_internal.env\n"
        "EnvironmentFile=/etc/sharedsignals/provider-native-probe.secrets\n"
        "TimeoutStartSec=120s\n"
        "ExecStart=/opt/sharedsignals/venv/bin/python3 /opt/investment/releases/sharedsignals-v1/current/tools/internal_v1_probe.py --registry /opt/investment/releases/sharedsignals-v1/current/config/provider_native_dataset_registry.yaml --startup-policy strict\n",
        encoding="utf-8",
    )
    (systemd / "sharedsignals-v1-probe.timer").write_text(
        "[Timer]\nUnit=sharedsignals-v1-probe.service\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=source_repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=source_repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SharedSignals Test"],
        cwd=source_repo,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test release"],
        cwd=source_repo,
        check=True,
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source_repo, text=True
    ).strip()
    releases = tmp_path / "releases"
    releases.mkdir()
    sha256sum = shutil.which("sha256sum")
    assert sha256sum is not None
    script = f"""
source {shlex.quote(str(RELEASE))}
SOURCE_ROOT={shlex.quote(str(source_repo))}
RELEASES_DIR={shlex.quote(str(releases))}
SHA256SUM={shlex.quote(sha256sum)}
VENV_PYTHON={shlex.quote(sys.executable)}
release_path="$(build_release {shlex.quote(commit)})"
validate_release "$release_path" {shlex.quote(commit)}
printf '%s' "$release_path"
"""
    result = _bash(script)
    assert result.returncode == 0, result.stdout + result.stderr
    release_path = Path(result.stdout)
    assert release_path == releases / commit
    assert (release_path / ".sharedsignals-v1-release.env").is_file()
    assert (release_path / ".sharedsignals-v1-SHA256SUMS").is_file()
    assert not any(path.is_symlink() for path in release_path.rglob("*"))
    assert _mode(release_path) == 0o555
    assert all(_mode(path) & 0o222 == 0 for path in release_path.rglob("*"))

    shadow_cwd = tmp_path / "shadow-cwd"
    shadow_cwd.mkdir()
    (shadow_cwd / "dataset_registry.py").write_text(
        "raise RuntimeError('source cwd must not override release modules')\n",
        encoding="utf-8",
    )
    target_bound = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"SHA256SUM={shlex.quote(sha256sum)}; "
        f"RELEASES_DIR={shlex.quote(str(releases))}; "
        f"VENV_PYTHON={shlex.quote(sys.executable)}; "
        f"validate_release {shlex.quote(str(release_path))} {shlex.quote(commit)}",
        cwd=shadow_cwd,
    )
    assert target_bound.returncode == 0, target_bound.stdout + target_bound.stderr

    release_path.chmod(0o755)
    rogue = release_path / "read-only-extra.pyc"
    rogue.write_bytes(b"not a tracked release artifact")
    rogue.chmod(0o444)
    release_path.chmod(0o555)
    extra_artifact = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"SHA256SUM={shlex.quote(sha256sum)}; "
        f"RELEASES_DIR={shlex.quote(str(releases))}; "
        f"VENV_PYTHON={shlex.quote(sys.executable)}; "
        f"validate_release {shlex.quote(str(release_path))} {shlex.quote(commit)}"
    )
    assert extra_artifact.returncode != 0
    assert "release artifact set is invalid" in extra_artifact.stderr
    release_path.chmod(0o755)
    rogue.unlink()
    release_path.chmod(0o555)

    (release_path / "api_server.py").chmod(0o644)
    (release_path / "api_server.py").write_text("tampered\n", encoding="utf-8")
    (release_path / "api_server.py").chmod(0o444)
    tampered = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"SHA256SUM={shlex.quote(sha256sum)}; "
        f"RELEASES_DIR={shlex.quote(str(releases))}; "
        f"VENV_PYTHON={shlex.quote(sys.executable)}; "
        f"validate_release {shlex.quote(str(release_path))} {shlex.quote(commit)}"
    )
    assert tampered.returncode != 0
    assert "manifest validation failed" in tampered.stderr


def test_release_library_detects_legacy_database_or_service_identity_drift(
    tmp_path: Path,
) -> None:
    legacy_db = tmp_path / "legacy.sqlite"
    legacy_db.write_bytes(b"legacy")
    state = tmp_path / "legacy.env"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = is-active ]; then printf active; else printf enabled; fi\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_ss = tmp_path / "ss"
    fake_ss.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'LISTEN 0 128 127.0.0.1:8082 0.0.0.0:* users:((legacy,pid=123,fd=4))'\n",
        encoding="utf-8",
    )
    fake_ss.chmod(0o755)
    sha256sum = shutil.which("sha256sum")
    assert sha256sum is not None
    script = f"""
source {shlex.quote(str(RELEASE))}
LEGACY_DATABASE={shlex.quote(str(legacy_db))}
SYSTEMCTL={shlex.quote(str(fake_systemctl))}
SS={shlex.quote(str(fake_ss))}
SHA256SUM={shlex.quote(sha256sum)}
capture_legacy_identity {shlex.quote(str(state))}
assert_legacy_identity {shlex.quote(str(state))}
"""
    result = _bash(script)
    assert result.returncode == 0, result.stdout + result.stderr

    legacy_db.write_bytes(b"same-inode-but-changed-size-and-mtime")
    drift = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"LEGACY_DATABASE={shlex.quote(str(legacy_db))}; "
        f"SYSTEMCTL={shlex.quote(str(fake_systemctl))}; "
        f"SS={shlex.quote(str(fake_ss))}; "
        f"SHA256SUM={shlex.quote(sha256sum)}; "
        f"assert_legacy_identity {shlex.quote(str(state))}"
    )
    assert drift.returncode != 0
    assert "legacy database fingerprint changed" in drift.stderr


def test_runtime_store_presence_distinguishes_absent_complete_and_partial(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    db = runtime_root / "read_model" / "provider_native.sqlite"
    db_lock = (
        runtime_root / "read_model" / ".provider_native.sqlite.read_model_store.lock"
    )
    maintenance = runtime_root / "locks" / "read_model_maintenance.lock"
    prefix = (
        f"source {shlex.quote(str(RELEASE))}; "
        f"RUNTIME_ROOT={shlex.quote(str(runtime_root))}; "
        f"DATABASE={shlex.quote(str(db))}; "
        f"DATABASE_LOCK={shlex.quote(str(db_lock))}; "
        f"MAINTENANCE_LOCK={shlex.quote(str(maintenance))}; "
    )
    absent = _bash(prefix + "runtime_store_presence")
    assert absent.returncode == 0, absent.stdout + absent.stderr
    assert absent.stdout == "absent"

    runtime_root.mkdir()
    partial = _bash(prefix + "runtime_store_presence")
    assert partial.returncode == 0, partial.stdout + partial.stderr
    assert partial.stdout == "partial"

    db.parent.mkdir()
    maintenance.parent.mkdir()
    db.touch()
    db_lock.touch()
    maintenance.touch()
    complete = _bash(prefix + "runtime_store_presence")
    assert complete.returncode == 0, complete.stdout + complete.stderr
    assert complete.stdout == "complete"


def test_enable_ops_requires_latest_success_receipt_and_fact_conservation(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    (release / "config").mkdir(parents=True)
    (release / "config/provider_native_dataset_registry.yaml").write_text(
        "version: 1\n", encoding="utf-8"
    )
    datasets = (
        "cn.equity.daily",
        "cn.equity.security_master",
        "cn.market.trade_calendar",
    )
    activation_rows = "".join(
        "- dataset_id: {dataset_id}\n"
        "  provider: tushare\n"
        "  entitlement_state: active\n"
        "  activation_state: active\n"
        "  evidence_ref: test/evidence\n".format(dataset_id=dataset_id)
        for dataset_id in datasets
    )
    (release / "config/provider_native_activation.yaml").write_text(
        "version: 1\nactivations:\n" + activation_rows,
        encoding="utf-8",
    )
    current = tmp_path / "current"
    current.symlink_to(release)
    database = tmp_path / "provider-native.sqlite"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE provider_dataset_rows (
                dataset_id TEXT NOT NULL,
                receipt_id TEXT NOT NULL
            );
            CREATE TABLE market_ingest_runs (
                run_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                rows_read INTEGER NOT NULL,
                rows_written INTEGER NOT NULL,
                notes TEXT NOT NULL
            );
            """
        )
        for index, dataset_id in enumerate(datasets):
            receipt_id = f"receipt:{index}"
            counts = {
                "committed": 1,
                "inserted": 1,
                "rejected": 0,
                "returned": 1,
                "unchanged": 0,
                "updated": 0,
                "validated": 1,
            }
            notes = {
                "counts": counts,
                "dataset_id": dataset_id,
                "receipt_id": receipt_id,
                "status": "success",
                "target_table": "provider_dataset_rows",
            }
            conn.execute(
                "INSERT INTO provider_dataset_rows VALUES (?, ?)",
                (dataset_id, receipt_id),
            )
            conn.execute(
                "INSERT INTO market_ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt_id,
                    "2026-07-19T01:00:00Z",
                    f"2026-07-19T01:00:0{index}Z",
                    "success",
                    dataset_id,
                    1,
                    1,
                    json.dumps(notes, sort_keys=True),
                ),
            )
    script = f"""
source {shlex.quote(str(RELEASE))}
CURRENT_LINK={shlex.quote(str(current))}
DATABASE={shlex.quote(str(database))}
VENV_PYTHON={shlex.quote(sys.executable)}
verify_expected_facts_and_receipts
"""
    valid = _bash(script)
    assert valid.returncode == 0, valid.stdout + valid.stderr

    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_ingest_runs SET rows_written = 2 "
            "WHERE source = 'cn.equity.daily'"
        )
    mismatched = _bash(script)
    assert mismatched.returncode != 0


def test_secret_preflight_checks_only_names_owner_and_mode_without_values(
    tmp_path: Path,
) -> None:
    token_hashes = tmp_path / "token-hashes.json"
    token_hashes.write_text("{}\n", encoding="utf-8")
    token_hashes.chmod(0o640)
    secret = tmp_path / "provider-native-internal.secrets"
    secret.write_text(
        f"SHAREDSIGNALS_TOKEN_HASH_FILE={token_hashes}\n"
        "SHAREDSIGNALS_TOKEN_SALT=redacted-salt\n"
        f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
        encoding="utf-8",
    )
    secret.chmod(0o600)
    script = f"""
source {shlex.quote(str(RELEASE))}
SECRET_ENV={shlex.quote(str(secret))}
SECRET_OWNER_UID={os.geteuid()}
SECRET_HASH_GROUP_GID={os.getegid()}
validate_secret_env
"""
    result = _bash(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "redacted" not in result.stdout + result.stderr

    secret.chmod(0o644)
    bad_mode = _bash(script)
    assert bad_mode.returncode != 0
    assert "mode 0600" in bad_mode.stderr
    assert "redacted" not in bad_mode.stdout + bad_mode.stderr

    secret.chmod(0o600)
    secret.write_text(
        secret.read_text(encoding="utf-8") + "TUSHARE_TOKEN=do-not-load\n",
        encoding="utf-8",
    )
    extra_key = _bash(script)
    assert extra_key.returncode != 0
    assert "unexpected key" in extra_key.stderr
    assert "do-not-load" not in extra_key.stdout + extra_key.stderr

    secret.write_text(
        f"SHAREDSIGNALS_TOKEN_HASH_FILE={token_hashes}\n"
        "SHAREDSIGNALS_TOKEN_SALT=redacted-salt\n"
        "SHAREDSIGNALS_TOKEN_SALT=duplicate-redacted-salt\n"
        f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
        encoding="utf-8",
    )
    duplicate_key = _bash(script)
    assert duplicate_key.returncode != 0
    assert "key set is invalid" in duplicate_key.stderr
    assert "redacted" not in duplicate_key.stdout + duplicate_key.stderr


def test_secret_preflight_rejects_empty_or_quoted_values_and_unsafe_hash_file(
    tmp_path: Path,
) -> None:
    token_hashes = tmp_path / "token-hashes.json"
    token_hashes.write_text("{}\n", encoding="utf-8")
    token_hashes.chmod(0o640)
    secret = tmp_path / "provider-native-internal.secrets"
    secret.touch()
    secret.chmod(0o600)
    prefix = f"""
source {shlex.quote(str(RELEASE))}
SECRET_ENV={shlex.quote(str(secret))}
SECRET_OWNER_UID={os.geteuid()}
SECRET_HASH_GROUP_GID={os.getegid()}
validate_secret_env
"""

    for invalid_value in ("", "quoted value", '"quoted"', "'quoted'"):
        secret.write_text(
            f"SHAREDSIGNALS_TOKEN_HASH_FILE={token_hashes}\n"
            f"SHAREDSIGNALS_TOKEN_SALT={invalid_value}\n"
            f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
            encoding="utf-8",
        )
        result = _bash(prefix)
        assert result.returncode != 0
        if invalid_value:
            assert invalid_value not in result.stdout + result.stderr

    secret.write_text(
        f"SHAREDSIGNALS_TOKEN_HASH_FILE={token_hashes}\n"
        "SHAREDSIGNALS_TOKEN_SALT=redacted-salt\n"
        f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
        encoding="utf-8",
    )
    token_hashes.chmod(0o600)
    bad_mode = _bash(prefix)
    assert bad_mode.returncode != 0
    assert "token hash file" in bad_mode.stderr

    token_hashes.chmod(0o640)
    secret.write_text(
        "SHAREDSIGNALS_TOKEN_HASH_FILE=relative-token-hashes.json\n"
        "SHAREDSIGNALS_TOKEN_SALT=redacted-salt\n"
        f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
        encoding="utf-8",
    )
    relative = _bash(prefix)
    assert relative.returncode != 0
    assert "absolute and canonical" in relative.stderr


def test_preflight_validates_three_independent_exact_secret_contracts(
    tmp_path: Path,
) -> None:
    token_hashes = tmp_path / "token-hashes.json"
    token_hashes.write_text("{}\n", encoding="utf-8")
    token_hashes.chmod(0o640)
    api = tmp_path / "api.secrets"
    api.write_text(
        f"SHAREDSIGNALS_TOKEN_HASH_FILE={token_hashes}\n"
        "SHAREDSIGNALS_TOKEN_SALT=redacted-salt\n"
        f"SHAREDSIGNALS_CURSOR_SIGNING_KEY={'c' * 32}\n",
        encoding="utf-8",
    )
    collector = tmp_path / "collector.secrets"
    collector.write_text(
        "QUICKSYNC_API_URL=https://example.invalid/v1\n"
        "QUICKSYNC_TOKEN=redacted-collector\n",
        encoding="utf-8",
    )
    probe = tmp_path / "probe.secrets"
    probe.write_text(
        "SHAREDSIGNALS_INTERNAL_V1_TOKEN=redacted-probe\n",
        encoding="utf-8",
    )
    for path in (api, collector, probe):
        path.chmod(0o600)
    script = f"""
source {shlex.quote(str(RELEASE))}
SECRET_ENV={shlex.quote(str(api))}
COLLECTOR_SECRET_ENV={shlex.quote(str(collector))}
PROBE_SECRET_ENV={shlex.quote(str(probe))}
SECRET_OWNER_UID={os.geteuid()}
SECRET_HASH_GROUP_GID={os.getegid()}
validate_all_secret_envs
"""
    valid = _bash(script)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "redacted" not in valid.stdout + valid.stderr

    collector.write_text(
        collector.read_text(encoding="utf-8") + "TUSHARE_TOKEN=forbidden\n",
        encoding="utf-8",
    )
    invalid = _bash(script)
    assert invalid.returncode != 0
    assert "key set is invalid" in invalid.stderr
    assert "forbidden" not in invalid.stdout + invalid.stderr


def test_release_port_preflight_allows_idle_or_current_unit_only(
    tmp_path: Path,
) -> None:
    fake_ss = tmp_path / "ss"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        '#!/bin/sh\nif [ "$1" = show ]; then printf 123; else printf active; fi\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_ss.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ss.chmod(0o755)
    prefix = (
        f"source {shlex.quote(str(RELEASE))}; "
        f"SS={shlex.quote(str(fake_ss))}; "
        f"SYSTEMCTL={shlex.quote(str(fake_systemctl))}; "
    )
    idle = _bash(prefix + "require_port_idle_or_owned")
    assert idle.returncode == 0, idle.stdout + idle.stderr

    fake_ss.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'LISTEN 0 128 127.0.0.1:18082 0.0.0.0:* users:((python,pid=123,fd=4))'\n",
        encoding="utf-8",
    )
    owned = _bash(prefix + "require_port_idle_or_owned")
    assert owned.returncode == 0, owned.stdout + owned.stderr

    fake_ss.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'LISTEN 0 128 127.0.0.1:18082 0.0.0.0:* users:((python,pid=999,fd=4))'\n",
        encoding="utf-8",
    )
    unrelated = _bash(prefix + "require_port_idle_or_owned")
    assert unrelated.returncode != 0
    assert "does not belong" in unrelated.stderr


def test_absent_lane_rejects_loaded_active_or_residual_wants_state(
    tmp_path: Path,
) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = is-active ]; then printf inactive; '
        'elif [ "$1" = is-enabled ]; then printf not-found; '
        'elif [ "$1" = show ]; then printf not-found; fi\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    script = f"""
source {shlex.quote(str(RELEASE))}
UNIT_DIR={shlex.quote(str(unit_dir))}
UNIT_TARGET="$UNIT_DIR/sharedsignals-v1-internal.service"
SYSTEMCTL={shlex.quote(str(fake_systemctl))}
assert_no_absent_lane_residue
"""
    clean = _bash(script)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    wants = unit_dir / "timers.target.wants"
    wants.mkdir()
    (wants / "sharedsignals-v1-probe.timer").symlink_to("../missing.timer")
    residue = _bash(script)
    assert residue.returncode != 0
    assert "residual dependency link" in residue.stderr
    (wants / "sharedsignals-v1-probe.timer").unlink()

    fake_systemctl.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = is-active ]; then printf active; '
        'elif [ "$1" = is-enabled ]; then printf not-found; '
        'elif [ "$1" = show ]; then printf not-found; fi\n',
        encoding="utf-8",
    )
    active = _bash(script)
    assert active.returncode != 0
    assert "residual active state" in active.stderr


def test_release_refuses_non_link_current_pointer(tmp_path: Path) -> None:
    current = tmp_path / "current"
    current.write_text("must-not-overwrite\n", encoding="utf-8")
    result = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"CURRENT_LINK={shlex.quote(str(current))}; "
        "validate_current_pointer_optional"
    )
    assert result.returncode != 0
    assert "must be a symbolic link" in result.stderr
    assert current.read_text(encoding="utf-8") == "must-not-overwrite\n"


def test_apply_error_handler_reports_rollback_success_and_failure(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "restored"
    success = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        f"restore_from_state() {{ : > {shlex.quote(str(marker))}; }}; "
        "set +e; (exit 37); handle_apply_error ignored"
    )
    assert success.returncode == 37
    assert marker.is_file()
    assert "automatic rollback completed" in success.stderr

    failed = _bash(
        f"source {shlex.quote(str(RELEASE))}; "
        "restore_from_state() { return 55; }; "
        "set +e; (exit 37); handle_apply_error ignored"
    )
    assert failed.returncode == 79
    assert "automatic rollback failed with rc=55" in failed.stderr


@pytest.mark.parametrize("failing_action", ["stop", "disable"])
def test_restore_does_not_swallow_stop_or_disable_failure(
    tmp_path: Path,
    failing_action: str,
) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = {shlex.quote(failing_action)} ]; then exit 55; fi\n'
        'if [ "$1" = is-active ]; then printf inactive; '
        'elif [ "$1" = is-enabled ]; then printf disabled; fi\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_ss = tmp_path / "ss"
    fake_ss.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_ss.chmod(0o755)
    script = f"""
source {shlex.quote(str(RELEASE))}
SYSTEMCTL={shlex.quote(str(fake_systemctl))}
SS={shlex.quote(str(fake_ss))}
CURRENT_LINK={shlex.quote(str(tmp_path / "current"))}
UNIT_TARGET={shlex.quote(str(tmp_path / "unit"))}
state_value() {{
  case "$2" in
    PREVIOUS_RELEASE) printf none ;;
    PREVIOUS_RELEASE_PRESENT|PREVIOUS_UNIT_PRESENT) printf 0 ;;
    PREVIOUS_UNIT_BACKUP) printf none ;;
    PREVIOUS_SERVICE_ACTIVE) printf inactive ;;
    PREVIOUS_SERVICE_ENABLED) printf disabled ;;
  esac
}}
assert_legacy_identity() {{ :; }}
restore_from_state ignored
"""
    result = _bash(script)
    assert result.returncode != 0


def test_state_and_manifest_readers_reject_duplicate_keys(tmp_path: Path) -> None:
    state = tmp_path / "state.env"
    state.write_text("KEY=one\nKEY=two\n", encoding="utf-8")
    manifest = tmp_path / "manifest.env"
    manifest.write_text("KEY=one\nKEY=two\n", encoding="utf-8")
    for function, path in (("state_value", state), ("manifest_value", manifest)):
        result = _bash(
            f"source {shlex.quote(str(RELEASE))}; "
            f"{function} {shlex.quote(str(path))} KEY"
        )
        assert result.returncode != 0
        assert "duplicates KEY" in result.stderr


def test_readback_token_fd_is_bounded_before_read() -> None:
    for descriptor in ("0", "2", "1024", "999999"):
        result = _bash(
            f"source {shlex.quote(str(RELEASE))}; "
            f"SHAREDSIGNALS_V1_READBACK_TOKEN_FD={descriptor}; "
            "read_token_from_fd"
        )
        assert result.returncode != 0
        assert "token FD is invalid" in result.stderr
