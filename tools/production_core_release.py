#!/opt/tradingdatas/venv/bin/python3
"""Root-owned safe-release orchestrator for the primary TradingDatas runtime."""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from types import ModuleType


RELEASES_ROOT = Path("/opt/investment/releases/tradingdatas")
MANIFESTS_ROOT = RELEASES_ROOT / "manifests"
CURRENT_LINK = RELEASES_ROOT / "current"
SPOOL = Path("/var/tmp/tradingdatas-core-deploy")
REQUEST_FILE = SPOOL / "request"
TRUSTED_VERIFIER = Path("/usr/local/lib/tradingdatas-release/release_manifest.py")
INSTALLED_HELPER = Path("/usr/local/sbin/tradingdatas-core-release")
API_UNIT = "tradingdatas-v1-internal.service"
COLLECTOR_UNIT = "tradingdatas-provider-native-collect.service"
TIMER_UNIT = "tradingdatas-provider-native-collect.timer"
API_HOST = "127.0.0.1"
API_PORT = 18082
CATALOG_PATH = "/v1/catalog"
QUIESCE_TIMEOUT_SECONDS = 330.0
API_READY_TIMEOUT_SECONDS = 12.0
HEX = set("0123456789abcdef")


class ReleaseFailure(RuntimeError):
    """A production release violates the frozen safe-release contract."""


def fail(message: str) -> None:
    raise ReleaseFailure(message)


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in HEX for character in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(arguments),
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        fail(f"command failed: {' '.join(arguments)}: {detail}")
    return result


def _active_state(unit: str) -> str:
    result = _run("systemctl", "is-active", unit, check=False)
    state = result.stdout.strip()
    if state not in {"active", "inactive"}:
        fail(f"unexpected active state for {unit}: {state or result.returncode}")
    return state


def _enabled_state(unit: str) -> str:
    result = _run("systemctl", "is-enabled", unit, check=False)
    state = result.stdout.strip()
    if state not in {"enabled", "disabled"}:
        fail(f"unexpected enablement state for {unit}: {state or result.returncode}")
    return state


def _wait_collector_inactive(timeout: float = QUIESCE_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while True:
        result = _run("systemctl", "is-active", COLLECTOR_UNIT, check=False)
        state = result.stdout.strip()
        if state == "inactive":
            return
        if state == "failed":
            fail("collector is failed; refusing release cutover")
        if time.monotonic() >= deadline:
            fail("collector did not quiesce before the bounded release deadline")
        time.sleep(1.0)


def _port_is_open() -> bool:
    try:
        with socket.create_connection((API_HOST, API_PORT), timeout=0.35):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def _require_port_closed() -> None:
    if _port_is_open():
        fail(f"unexpected listener remains on {API_HOST}:{API_PORT}")


def _catalog_status() -> int:
    connection = http.client.HTTPConnection(API_HOST, API_PORT, timeout=1.0)
    try:
        connection.request("GET", CATALOG_PATH)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def _wait_catalog_unauthenticated(timeout: float = API_READY_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = _catalog_status()
        except (ConnectionRefusedError, TimeoutError, OSError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                fail("TradingDatas API listener did not become ready before timeout")
            time.sleep(0.2)
            continue
        if status != 401:
            fail(f"TradingDatas API returned unexpected unauthenticated status: {status}")
        return


def _load_trusted_verifier() -> ModuleType:
    metadata = os.lstat(TRUSTED_VERIFIER)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        fail("trusted release verifier must be a single-link regular file")
    if metadata.st_uid != 0 or metadata.st_gid != 0 or metadata.st_mode & 0o022:
        fail("trusted release verifier ownership/mode is unsafe")
    spec = importlib.util.spec_from_file_location(
        "tradingdatas_trusted_release_manifest", TRUSTED_VERIFIER
    )
    if spec is None or spec.loader is None:
        fail("cannot load trusted release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_root_trust_boundary() -> str:
    if os.geteuid() != 0:
        fail("helper must run as root through the scoped sudo rule")
    if len(sys.argv) != 1:
        fail("helper accepts no command-line arguments")
    invoked = Path(os.path.realpath(sys.argv[0]))
    if invoked != INSTALLED_HELPER:
        fail(f"helper must run from {INSTALLED_HELPER}")
    metadata = os.lstat(INSTALLED_HELPER)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_mode & 0o022
    ):
        fail("installed helper ownership/mode is unsafe")
    sudo_user = os.environ.get("SUDO_USER", "")
    if not sudo_user or sudo_user == "root":
        fail("missing non-root SUDO_USER")
    return sudo_user


def _require_owned_single_file(path: Path, owner_uid: int, *, name: str) -> None:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != owner_uid
        or metadata.st_mode & 0o022
    ):
        fail(f"{name} ownership/type/mode is unsafe")


def _read_request(sudo_user: str) -> tuple[str, str, str, Path, Path]:
    try:
        owner_uid = int(_run("id", "-u", sudo_user).stdout.strip())
    except ValueError:
        fail("cannot resolve SUDO_USER uid")
    spool_metadata = os.lstat(SPOOL)
    if (
        not stat.S_ISDIR(spool_metadata.st_mode)
        or stat.S_IMODE(spool_metadata.st_mode) != 0o700
        or spool_metadata.st_uid != owner_uid
    ):
        fail("deployment spool ownership/mode is unsafe")
    _require_owned_single_file(REQUEST_FILE, owner_uid, name="request")
    lines = REQUEST_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        fail("request must contain exactly one line")
    parts = lines[0].split(" ")
    if len(parts) != 3 or any(not part for part in parts):
        fail("request must contain SHA, archive checksum and manifest checksum")
    commit, archive_checksum, manifest_checksum = parts
    if not _is_hex(commit, 40):
        fail("request commit is invalid")
    if not _is_hex(archive_checksum, 64) or not _is_hex(manifest_checksum, 64):
        fail("request checksum is invalid")
    archive = SPOOL / f"tradingdatas-core-{commit}.tar.gz"
    manifest = SPOOL / f"{commit}.release.json"
    _require_owned_single_file(archive, owner_uid, name="archive")
    _require_owned_single_file(manifest, owner_uid, name="manifest")
    return commit, archive_checksum, manifest_checksum, archive, manifest


def _copy_root_owned(source: Path, suffix: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix="tradingdatas-core.", suffix=suffix, dir="/var/tmp"
    )
    os.close(descriptor)
    destination = Path(raw_path)
    try:
        shutil.copyfile(source, destination)
        os.chown(destination, 0, 0)
        os.chmod(destination, 0o600)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _expected_directories(manifest: dict[str, object]) -> set[str]:
    directories: set[str] = set()
    for entry in manifest["files"]:  # type: ignore[index]
        parent = PurePosixPath(str(entry["path"])).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _install_release_from_archive(
    archive: Path,
    manifest: dict[str, object],
    verifier: ModuleType,
) -> Path:
    commit = str(manifest["commit"])
    release_dir = RELEASES_ROOT / commit
    if release_dir.exists():
        verifier.verify_release(
            release_dir,
            manifest,
            expected_uid=0,
            expected_gid=0,
        )
        return release_dir

    staging = Path(tempfile.mkdtemp(prefix=f".staging-{commit}.", dir=RELEASES_ROOT))
    committed = False
    try:
        os.chown(staging, 0, 0)
        expected_files = {
            str(entry["path"]): entry for entry in manifest["files"]  # type: ignore[index]
        }
        expected_directories = _expected_directories(manifest)
        observed_files: set[str] = set()
        observed_directories: set[str] = set()

        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                raw = member.name
                normalized = raw[:-1] if member.isdir() and raw.endswith("/") else raw
                path = PurePosixPath(normalized)
                if (
                    not normalized
                    or path.is_absolute()
                    or normalized != path.as_posix()
                    or any(part in {"", ".", ".."} for part in path.parts)
                ):
                    fail(f"release archive contains unsafe path: {raw!r}")
                if member.isdir():
                    if (
                        normalized not in expected_directories
                        or normalized in observed_directories
                    ):
                        fail(
                            "release archive contains unexpected/duplicate directory: "
                            f"{normalized}"
                        )
                    observed_directories.add(normalized)
                    continue
                if not member.isfile():
                    fail(
                        f"release archive contains unsupported member type: {normalized}"
                    )
                if normalized not in expected_files or normalized in observed_files:
                    fail(
                        "release archive contains unexpected/duplicate file: "
                        f"{normalized}"
                    )
                observed_files.add(normalized)

            missing = set(expected_files) - observed_files
            if missing:
                fail(f"release archive is missing tracked file: {sorted(missing)[0]}")

            for relative, entry in expected_files.items():
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                member = bundle.getmember(relative)
                source = bundle.extractfile(member)
                if source is None:
                    fail(f"release archive cannot read tracked file: {relative}")
                destination.write_bytes(source.read())
                mode = 0o555 if entry["git_mode"] == "100755" else 0o444
                os.chown(destination, 0, 0)
                os.chmod(destination, mode)

        for directory in sorted(
            (path for path in staging.rglob("*") if path.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            os.chown(directory, 0, 0)
            os.chmod(directory, 0o555)
        os.chmod(staging, 0o555)

        verifier.verify_release(
            staging,
            manifest,
            expected_uid=0,
            expected_gid=0,
        )
        os.rename(staging, release_dir)
        _fsync_directory(RELEASES_ROOT)
        committed = True
        return release_dir
    finally:
        if not committed and staging.exists():
            os.chmod(staging, 0o700)
            shutil.rmtree(staging, ignore_errors=True)


def _install_manifest(
    root_manifest: Path,
    manifest: dict[str, object],
    verifier: ModuleType,
) -> Path:
    MANIFESTS_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(MANIFESTS_ROOT, 0, 0)
    os.chmod(MANIFESTS_ROOT, 0o755)
    destination = MANIFESTS_ROOT / f"{manifest['commit']}.json"
    if destination.exists():
        existing = verifier.load_manifest(
            destination, expected_uid=0, expected_gid=0
        )
        if existing != manifest:
            fail("existing release manifest differs from the tested target manifest")
        return destination

    temporary = MANIFESTS_ROOT / f".{manifest['commit']}.{os.getpid()}.tmp"
    if temporary.exists():
        fail("temporary manifest path already exists")
    shutil.copyfile(root_manifest, temporary)
    os.chown(temporary, 0, 0)
    os.chmod(temporary, 0o444)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    _fsync_directory(MANIFESTS_ROOT)
    return destination


def _current_commit() -> str:
    if not CURRENT_LINK.is_symlink():
        fail("current must be a normalized relative commit symlink before automation")
    target = os.readlink(CURRENT_LINK)
    if not _is_hex(target, 40):
        fail("current must be a normalized relative 40-character commit symlink")
    return target


def _snapshot_runtime_state() -> dict[str, str]:
    return {
        "api_active": _active_state(API_UNIT),
        "api_enabled": _enabled_state(API_UNIT),
        "timer_active": _active_state(TIMER_UNIT),
        "timer_enabled": _enabled_state(TIMER_UNIT),
    }


def _quiesce_runtime(state: dict[str, str]) -> None:
    if state["timer_active"] == "active" or state["timer_enabled"] == "enabled":
        _run("systemctl", "disable", "--now", TIMER_UNIT)
    if _active_state(TIMER_UNIT) != "inactive" or _enabled_state(TIMER_UNIT) != "disabled":
        fail("collector timer did not enter disabled+inactive release state")
    _wait_collector_inactive()
    if state["api_active"] == "active":
        _wait_catalog_unauthenticated()
        _run("systemctl", "stop", API_UNIT)
    if _active_state(API_UNIT) != "inactive":
        fail("API did not stop for release cutover")
    _require_port_closed()


def _restore_api(state: dict[str, str], release_dir: Path) -> None:
    if state["api_active"] == "active":
        _run("systemctl", "start", API_UNIT)
        _wait_catalog_unauthenticated()
        pid_raw = _run(
            "systemctl", "show", "-p", "MainPID", "--value", API_UNIT
        ).stdout.strip()
        if not pid_raw.isdigit() or int(pid_raw) <= 0:
            fail("API has no valid MainPID after restart")
        cwd = Path(os.path.realpath(f"/proc/{pid_raw}/cwd"))
        if cwd != release_dir:
            fail(f"API process is not running from requested immutable release: {cwd}")
    else:
        if _active_state(API_UNIT) != "inactive":
            fail("previously inactive API unexpectedly started during release")
        _require_port_closed()


def _restore_timer(state: dict[str, str]) -> None:
    if state["timer_enabled"] == "enabled":
        _run("systemctl", "enable", TIMER_UNIT)
    if state["timer_active"] == "active":
        _run("systemctl", "start", TIMER_UNIT)
    if _enabled_state(TIMER_UNIT) != state["timer_enabled"]:
        fail("collector timer enablement state was not restored")
    if _active_state(TIMER_UNIT) != state["timer_active"]:
        fail("collector timer active state was not restored")


def _rollback(
    verifier: ModuleType,
    state: dict[str, str],
    target_manifest: dict[str, object],
    rollback_manifest: dict[str, object],
    rollback_dir: Path,
) -> None:
    errors: list[str] = []
    try:
        _run("systemctl", "disable", "--now", TIMER_UNIT)
        _wait_collector_inactive()
    except BaseException as exc:
        errors.append(f"collector quiesce for rollback failed: {exc}")
    try:
        _run("systemctl", "stop", API_UNIT, check=False)
        _require_port_closed()
    except BaseException as exc:
        errors.append(f"API stop for rollback failed: {exc}")
    if errors:
        fail("; ".join(errors))

    try:
        verifier.switch_current(
            RELEASES_ROOT,
            rollback_manifest,
            target_manifest,
            expected_uid=0,
            expected_gid=0,
        )
        verifier.verify_current(
            RELEASES_ROOT,
            rollback_manifest,
            expected_uid=0,
            expected_gid=0,
        )
        _restore_api(state, rollback_dir)
        _restore_timer(state)
    except BaseException as exc:
        fail(f"SEVERE: rollback restoration failed: {exc}")


def _restore_pre_cutover_runtime(state: dict[str, str]) -> None:
    if state["api_active"] == "active":
        _run("systemctl", "start", API_UNIT)
        _wait_catalog_unauthenticated()
    else:
        _run("systemctl", "stop", API_UNIT, check=False)
        _require_port_closed()

    if state["timer_enabled"] == "enabled":
        _run("systemctl", "enable", TIMER_UNIT)
    else:
        _run("systemctl", "disable", TIMER_UNIT)
    if state["timer_active"] == "active":
        _run("systemctl", "start", TIMER_UNIT)
    else:
        _run("systemctl", "stop", TIMER_UNIT)


def main() -> int:
    os.umask(0o077)
    sudo_user = _require_root_trust_boundary()
    verifier = _load_trusted_verifier()
    (
        commit,
        archive_checksum,
        manifest_checksum,
        uploaded_archive,
        uploaded_manifest,
    ) = _read_request(sudo_user)

    root_archive = _copy_root_owned(uploaded_archive, ".tar.gz")
    root_manifest = _copy_root_owned(uploaded_manifest, ".json")
    switched = False
    state: dict[str, str] | None = None
    target_manifest: dict[str, object] | None = None
    rollback_manifest: dict[str, object] | None = None
    rollback_dir: Path | None = None

    try:
        if _sha256(root_archive) != archive_checksum:
            fail("release archive checksum mismatch")
        if _sha256(root_manifest) != manifest_checksum:
            fail("release manifest checksum mismatch")

        target_manifest = verifier.load_manifest(
            root_manifest,
            expected_uid=0,
            expected_gid=0,
        )
        if target_manifest["commit"] != commit:
            fail("tested manifest commit does not match deployment request")

        current_commit = _current_commit()
        rollback_manifest_path = MANIFESTS_ROOT / f"{current_commit}.json"
        rollback_manifest = verifier.load_manifest(
            rollback_manifest_path,
            expected_uid=0,
            expected_gid=0,
        )
        if rollback_manifest["commit"] != current_commit:
            fail("rollback manifest does not match current commit")

        verifier.verify_current(
            RELEASES_ROOT,
            rollback_manifest,
            expected_uid=0,
            expected_gid=0,
        )
        rollback_dir = RELEASES_ROOT / current_commit

        target_manifest_path = _install_manifest(
            root_manifest, target_manifest, verifier
        )
        target_manifest = verifier.load_manifest(
            target_manifest_path,
            expected_uid=0,
            expected_gid=0,
        )
        target_dir = _install_release_from_archive(
            root_archive, target_manifest, verifier
        )
        verifier.verify_release(
            target_dir,
            target_manifest,
            expected_uid=0,
            expected_gid=0,
        )

        if current_commit == commit:
            verifier.verify_current(
                RELEASES_ROOT,
                target_manifest,
                expected_uid=0,
                expected_gid=0,
            )
            print(
                json.dumps(
                    {"commit": commit, "deployed": True, "switched": False},
                    sort_keys=True,
                )
            )
            uploaded_archive.unlink(missing_ok=True)
            uploaded_manifest.unlink(missing_ok=True)
            REQUEST_FILE.unlink(missing_ok=True)
            return 0

        state = _snapshot_runtime_state()
        _quiesce_runtime(state)

        verifier.switch_current(
            RELEASES_ROOT,
            target_manifest,
            rollback_manifest,
            expected_uid=0,
            expected_gid=0,
        )
        switched = True
        verifier.verify_current(
            RELEASES_ROOT,
            target_manifest,
            expected_uid=0,
            expected_gid=0,
        )

        _restore_api(state, target_dir)
        _restore_timer(state)

        print(
            json.dumps(
                {"commit": commit, "deployed": True, "switched": True},
                sort_keys=True,
            )
        )
        uploaded_archive.unlink(missing_ok=True)
        uploaded_manifest.unlink(missing_ok=True)
        REQUEST_FILE.unlink(missing_ok=True)
        return 0
    except BaseException as exc:
        if (
            switched
            and state is not None
            and target_manifest is not None
            and rollback_manifest is not None
            and rollback_dir is not None
        ):
            try:
                _rollback(
                    verifier,
                    state,
                    target_manifest,
                    rollback_manifest,
                    rollback_dir,
                )
            except BaseException as rollback_exc:
                print(str(rollback_exc), file=sys.stderr)
        elif state is not None:
            try:
                _restore_pre_cutover_runtime(state)
            except BaseException as restore_exc:
                print(
                    f"SEVERE: pre-cutover runtime restoration failed: {restore_exc}",
                    file=sys.stderr,
                )
        print(f"tradingdatas-core-release: {exc}", file=sys.stderr)
        return 1
    finally:
        root_archive.unlink(missing_ok=True)
        root_manifest.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
