from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

import tools.release_manifest as release_manifest
from tools.release_manifest import (
    ReleaseManifestError,
    build_manifest,
    canonical_manifest_bytes,
    load_manifest,
    normalize_current,
    switch_current,
    verify_release,
    verify_current,
    write_manifest,
)


@pytest.fixture(autouse=True)
def _restore_test_tree_permissions(tmp_path: Path):
    yield
    for current_root, directory_names, file_names in os.walk(
        tmp_path, topdown=False, followlinks=False
    ):
        current = Path(current_root)
        for name in file_names:
            path = current / name
            if not path.is_symlink():
                try:
                    path.chmod(0o644)
                except FileNotFoundError:
                    # Git may remove a transient lock after os.walk lists it.
                    # An absent file needs no permission restoration; other
                    # cleanup failures must still surface.
                    pass
        for name in directory_names:
            path = current / name
            if not path.is_symlink():
                path.chmod(0o755)
    tmp_path.chmod(0o755)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # Keep fixture commits from launching background Git maintenance that can
    # race permission restoration. These settings affect only this temp repo.
    _git(repo, "config", "--local", "maintenance.auto", "false")
    _git(repo, "config", "--local", "gc.auto", "0")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "TradingDatas Test")
    (repo / "README.md").write_text("TradingDatas\n", encoding="utf-8")
    tool = repo / "tools" / "run.py"
    tool.parent.mkdir()
    tool.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
    tool.chmod(0o755)
    _git(repo, "add", "README.md", "tools/run.py")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _release(tmp_path: Path, repo: Path, manifest: dict[str, object]) -> Path:
    releases = tmp_path / "releases"
    release = releases / str(manifest["commit"])
    for entry in manifest["files"]:  # type: ignore[index]
        relative = Path(str(entry["path"]))
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_git_blob(repo, str(entry["git_blob"])))
        target.chmod(0o555 if entry["git_mode"] == "100755" else 0o444)
    directories = sorted(
        (path for path in release.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        directory.chmod(0o555)
    release.chmod(0o555)
    return release


def _git_blob(repo: Path, blob: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", blob],
        check=True,
        capture_output=True,
    ).stdout


def _next_manifest(repo: Path) -> dict[str, object]:
    (repo / "README.md").write_text("TradingDatas next\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "next")
    return build_manifest(repo)


def test_manifest_is_deterministic_and_binds_commit_tree_and_files(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    first = build_manifest(repo)
    second = build_manifest(repo)

    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert first["commit"] == _git(repo, "rev-parse", "HEAD")
    assert first["tree"] == _git(repo, "rev-parse", "HEAD^{tree}")
    assert [entry["path"] for entry in first["files"]] == [  # type: ignore[index]
        "README.md",
        "tools/run.py",
    ]
    assert [entry["git_mode"] for entry in first["files"]] == [  # type: ignore[index]
        "100644",
        "100755",
    ]


def test_build_rejects_dirty_tree_and_unsupported_symlink(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="clean"):
        build_manifest(repo)

    _git(repo, "restore", "README.md")
    (repo / "linked").symlink_to("README.md")
    _git(repo, "add", "linked")
    _git(repo, "commit", "-qm", "linked")
    with pytest.raises(ReleaseManifestError, match="unsupported entry"):
        build_manifest(repo)


def test_manifest_write_is_exclusive_canonical_and_single_link(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    output = tmp_path / "evidence" / "release.json"

    write_manifest(output, manifest)

    assert output.stat().st_mode & 0o777 == 0o600
    assert load_manifest(output) == manifest
    assert (
        hashlib.sha256(output.read_bytes()).hexdigest()
        == hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
    )
    with pytest.raises(FileExistsError):
        write_manifest(output, manifest)
    with pytest.raises(ReleaseManifestError, match="owner uid"):
        load_manifest(output, expected_uid=os.getuid() + 1)

    linked = tmp_path / "linked.json"
    os.link(output, linked)
    with pytest.raises(ReleaseManifestError, match="single-link"):
        load_manifest(output)


def test_manifest_rejects_noncanonical_or_tampered_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    output = tmp_path / "release.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output.chmod(0o600)

    with pytest.raises(ReleaseManifestError, match="not canonical"):
        load_manifest(output)

    manifest["files"][0]["sha256"] = "f" * 64  # type: ignore[index]
    output.write_bytes(canonical_manifest_bytes(manifest))
    loaded = load_manifest(output)
    release = _release(tmp_path, repo, build_manifest(repo))
    with pytest.raises(ReleaseManifestError, match="content"):
        verify_release(release, loaded)


def test_verify_accepts_exact_immutable_release(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)

    result = verify_release(release, manifest)

    assert result == {
        "product": "TradingDatas",
        "commit": manifest["commit"],
        "tree": manifest["tree"],
        "file_count": 2,
        "verified": True,
    }


@pytest.mark.parametrize("mutation", ["commit", "tree", "blob"])
def test_verify_recomputes_git_commit_tree_and_blob_identity(
    tmp_path: Path,
    mutation: str,
) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    forged = copy.deepcopy(manifest)
    if mutation == "commit":
        forged["commit"] = "a" * 40
    elif mutation == "tree":
        forged["tree"] = "f" * 40
    else:
        forged["files"][0]["git_blob"] = "e" * 40  # type: ignore[index]

    with pytest.raises(ReleaseManifestError, match="commit|tree|Git"):
        verify_release(release, forged)


def test_verify_current_accepts_only_one_relative_commit_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    current = release.parent / "current"
    current.symlink_to(str(manifest["commit"]))

    result = verify_current(release.parent, manifest)

    assert result["commit"] == manifest["commit"]
    current.unlink()
    current.symlink_to(release)
    with pytest.raises(ReleaseManifestError, match="40 lowercase hex"):
        verify_current(release.parent, manifest)


def test_verify_current_rejects_invalid_manifest_and_unsafe_releases_root(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    current = release.parent / "current"
    current.symlink_to(str(manifest["commit"]))

    invalid = dict(manifest)
    invalid["unexpected"] = True
    with pytest.raises(ReleaseManifestError, match="invalid shape"):
        verify_current(release.parent, invalid)

    release.parent.chmod(0o777)
    with pytest.raises(ReleaseManifestError, match="non-group/world-writable"):
        verify_current(release.parent, manifest)
    release.parent.chmod(0o755)


def test_normalize_current_rewrites_only_exact_legacy_absolute_pointer(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)
    database = tmp_path / "provider_native.sqlite"
    database.write_bytes(b"sqlite-authority")
    before = (database.stat().st_dev, database.stat().st_ino, database.read_bytes())

    result = normalize_current(rollback_release.parent, rollback_manifest)

    assert result == {
        "product": "TradingDatas",
        "commit": rollback_manifest["commit"],
        "previous_target": legacy_target,
        "current_target": rollback_manifest["commit"],
        "normalized": True,
    }
    assert os.readlink(current) == rollback_manifest["commit"]
    assert verify_current(rollback_release.parent, rollback_manifest)["verified"] is True
    assert (
        database.stat().st_dev,
        database.stat().st_ino,
        database.read_bytes(),
    ) == before


def test_normalize_current_rejects_nonmatching_or_relative_legacy_pointer(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"

    current.symlink_to(str(rollback_manifest["commit"]))
    with pytest.raises(ReleaseManifestError, match="legacy absolute"):
        normalize_current(rollback_release.parent, rollback_manifest)
    assert os.readlink(current) == rollback_manifest["commit"]

    current.unlink()
    arbitrary = rollback_release.parent / ("f" * 40)
    current.symlink_to(arbitrary)
    with pytest.raises(ReleaseManifestError, match="rollback manifest"):
        normalize_current(rollback_release.parent, rollback_manifest)
    assert os.readlink(current) == str(arbitrary)

    current.unlink()
    alias = rollback_release.parent / "legacy-release"
    alias.symlink_to(rollback_release)
    current.symlink_to(alias)
    with pytest.raises(ReleaseManifestError, match="rollback manifest"):
        normalize_current(rollback_release.parent, rollback_manifest)
    assert os.readlink(current) == str(alias)


def test_normalize_current_rejects_wrong_manifest_drift_and_unsafe_root(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    target_manifest = _next_manifest(repo)
    _release(tmp_path, repo, target_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)

    with pytest.raises(ReleaseManifestError, match="rollback manifest"):
        normalize_current(rollback_release.parent, target_manifest)
    assert os.readlink(current) == legacy_target

    rollback_release.chmod(0o755)
    rollback_file = rollback_release / "README.md"
    rollback_file.chmod(0o644)
    rollback_file.write_text("drift\n", encoding="utf-8")
    rollback_file.chmod(0o444)
    rollback_release.chmod(0o555)
    with pytest.raises(ReleaseManifestError, match="content"):
        normalize_current(rollback_release.parent, rollback_manifest)
    assert os.readlink(current) == legacy_target

    rollback_release.parent.chmod(0o777)
    with pytest.raises(ReleaseManifestError, match="non-group/world-writable"):
        normalize_current(rollback_release.parent, rollback_manifest)
    assert os.readlink(current) == legacy_target
    rollback_release.parent.chmod(0o755)


def test_normalize_current_rejects_release_symlink_chain(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    releases_root = rollback_release.parent
    current = releases_root / "current"
    legacy_target = str(rollback_release)
    alternate_parent = tmp_path / "alternate"
    alternate_parent.mkdir()
    alternate_release = alternate_parent / rollback_release.name
    rollback_release.chmod(0o755)
    rollback_release.rename(alternate_release)
    alternate_release.chmod(0o555)
    rollback_release.symlink_to(alternate_release, target_is_directory=True)
    current.symlink_to(legacy_target)

    with pytest.raises(ReleaseManifestError, match="symlink"):
        normalize_current(releases_root, rollback_manifest)

    assert os.readlink(current) == legacy_target


def test_normalize_current_restores_absolute_pointer_after_post_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)
    original = release_manifest._replace_current_at

    def fail_after_relative_replace(descriptor: int, target: str) -> bool:
        original(descriptor, target)
        raise ReleaseManifestError("injected normalize post-replace failure")

    monkeypatch.setattr(
        release_manifest,
        "_replace_current_at",
        fail_after_relative_replace,
    )

    with pytest.raises(ReleaseManifestError, match="injected normalize"):
        normalize_current(rollback_release.parent, rollback_manifest)

    assert os.readlink(current) == legacy_target


def test_normalize_current_fails_loudly_when_absolute_restoration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_release))
    original = release_manifest._replace_current_at

    def fail_after_relative_replace(descriptor: int, target: str) -> bool:
        original(descriptor, target)
        raise ReleaseManifestError("injected normalize post-replace failure")

    def fail_legacy_restore(descriptor: int, target: str) -> bool:
        raise OSError("injected legacy restore failure")

    monkeypatch.setattr(
        release_manifest,
        "_replace_current_at",
        fail_after_relative_replace,
    )
    monkeypatch.setattr(
        release_manifest,
        "_restore_legacy_current_at",
        fail_legacy_restore,
    )

    with pytest.raises(ReleaseManifestError, match="restoration failed"):
        normalize_current(rollback_release.parent, rollback_manifest)

    assert os.readlink(current) == rollback_manifest["commit"]


def test_normalize_current_keeps_committed_pointer_after_unlock_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)
    original_flock = release_manifest.fcntl.flock
    failed = False

    def fail_first_unlock(descriptor: int, operation: int) -> None:
        nonlocal failed
        if operation == release_manifest.fcntl.LOCK_UN and not failed:
            failed = True
            raise OSError("injected unlock failure")
        original_flock(descriptor, operation)

    monkeypatch.setattr(release_manifest.fcntl, "flock", fail_first_unlock)

    result = normalize_current(rollback_release.parent, rollback_manifest)

    assert result["normalized"] is True
    assert os.readlink(current) == rollback_manifest["commit"]


def test_normalize_current_helper_readback_is_the_only_commit_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_release))

    def reject_redundant_outer_readback(descriptor: int) -> str:
        raise OSError("outer post-commit readback must not run")

    monkeypatch.setattr(
        release_manifest,
        "_read_current_target_at",
        reject_redundant_outer_readback,
    )

    result = normalize_current(rollback_release.parent, rollback_manifest)

    assert result["normalized"] is True
    assert os.readlink(current) == rollback_manifest["commit"]


def test_normalize_current_detaches_fd_and_keeps_commit_after_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)
    original_close = release_manifest.os.close
    failed = False
    recycled_descriptor: int | None = None
    guard = tmp_path / "recycled-fd-guard"
    guard.write_bytes(b"guard")

    def close_then_fail_once(descriptor: int) -> None:
        nonlocal failed, recycled_descriptor
        if not failed:
            failed = True
            original_close(descriptor)
            recycled_descriptor = os.open(guard, os.O_RDONLY)
            assert recycled_descriptor == descriptor
            raise OSError("injected close failure")
        original_close(descriptor)

    monkeypatch.setattr(release_manifest.os, "close", close_then_fail_once)

    result = normalize_current(rollback_release.parent, rollback_manifest)

    assert result["normalized"] is True
    assert os.readlink(current) == rollback_manifest["commit"]
    assert recycled_descriptor is not None
    assert os.fstat(recycled_descriptor).st_size == len(b"guard")
    original_close(recycled_descriptor)


def test_normalize_current_cleanup_failure_does_not_mask_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    legacy_target = str(rollback_release)
    current.symlink_to(legacy_target)
    original_flock = release_manifest.fcntl.flock

    def fail_before_replace(descriptor: int, target: str) -> bool:
        raise ReleaseManifestError("primary normalization failure")

    def fail_unlock(descriptor: int, operation: int) -> None:
        if operation == release_manifest.fcntl.LOCK_UN:
            raise OSError("secondary cleanup failure")
        original_flock(descriptor, operation)

    monkeypatch.setattr(release_manifest, "_replace_current_at", fail_before_replace)
    monkeypatch.setattr(release_manifest.fcntl, "flock", fail_unlock)

    with pytest.raises(ReleaseManifestError, match="primary normalization failure"):
        normalize_current(rollback_release.parent, rollback_manifest)

    assert os.readlink(current) == legacy_target


def test_normalize_current_cli_loads_verified_rollback_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_release))
    manifest_path = tmp_path / "manifests" / "rollback.json"
    write_manifest(manifest_path, rollback_manifest)

    return_code = release_manifest.main(
        [
            "normalize-current",
            "--releases-root",
            str(rollback_release.parent),
            "--rollback-manifest",
            str(manifest_path),
            "--expected-uid",
            str(os.getuid()),
            "--expected-gid",
            str(os.getgid()),
        ]
    )

    assert return_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["normalized"] is True
    assert output["current_target"] == rollback_manifest["commit"]
    assert os.readlink(current) == rollback_manifest["commit"]


def test_switch_current_is_atomic_and_preserves_data(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    target_manifest = _next_manifest(repo)
    target_release = _release(tmp_path, repo, target_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_manifest["commit"]))
    database = tmp_path / "provider_native.sqlite"
    database.write_bytes(b"sqlite-authority")
    before = (database.stat().st_dev, database.stat().st_ino, database.read_bytes())

    result = switch_current(
        rollback_release.parent,
        target_manifest,
        rollback_manifest,
    )

    assert result["switched"] is True
    assert os.readlink(current) == target_manifest["commit"]
    assert verify_current(target_release.parent, target_manifest)["verified"] is True
    assert (
        database.stat().st_dev,
        database.stat().st_ino,
        database.read_bytes(),
    ) == before


def test_switch_rejects_wrong_rollback_or_target_drift_before_pointer_write(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    target_manifest = _next_manifest(repo)
    target_release = _release(tmp_path, repo, target_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_manifest["commit"]))

    wrong_rollback = dict(rollback_manifest)
    wrong_rollback["commit"] = "f" * 40
    with pytest.raises(ReleaseManifestError, match="commit identity|rollback"):
        switch_current(rollback_release.parent, target_manifest, wrong_rollback)
    assert os.readlink(current) == rollback_manifest["commit"]

    target_release.chmod(0o755)
    target_file = target_release / "README.md"
    target_file.chmod(0o644)
    target_file.write_text("drift\n", encoding="utf-8")
    target_file.chmod(0o444)
    target_release.chmod(0o555)
    with pytest.raises(ReleaseManifestError, match="content"):
        switch_current(rollback_release.parent, target_manifest, rollback_manifest)
    assert os.readlink(current) == rollback_manifest["commit"]


def test_switch_restores_rollback_pointer_after_post_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    rollback_manifest = build_manifest(repo)
    rollback_release = _release(tmp_path, repo, rollback_manifest)
    target_manifest = _next_manifest(repo)
    _release(tmp_path, repo, target_manifest)
    current = rollback_release.parent / "current"
    current.symlink_to(str(rollback_manifest["commit"]))
    original = release_manifest._replace_current_at

    def fail_after_target_replace(descriptor: int, target: str) -> bool:
        replaced = original(descriptor, target)
        if target == target_manifest["commit"]:
            raise ReleaseManifestError("injected post-switch failure")
        return replaced

    monkeypatch.setattr(
        release_manifest,
        "_replace_current_at",
        fail_after_target_replace,
    )

    with pytest.raises(ReleaseManifestError, match="injected"):
        switch_current(rollback_release.parent, target_manifest, rollback_manifest)

    assert os.readlink(current) == rollback_manifest["commit"]
    assert (
        verify_current(rollback_release.parent, rollback_manifest)["verified"] is True
    )


def test_verify_current_rejects_pointer_change_during_release_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    target_manifest = build_manifest(repo)
    target_release = _release(tmp_path, repo, target_manifest)
    rollback_manifest = _next_manifest(repo)
    _release(tmp_path, repo, rollback_manifest)
    current = target_release.parent / "current"
    current.symlink_to(str(target_manifest["commit"]))
    original = release_manifest.verify_release

    def verify_then_move_pointer(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        current.unlink()
        current.symlink_to(str(rollback_manifest["commit"]))
        return result

    monkeypatch.setattr(release_manifest, "verify_release", verify_then_move_pointer)

    with pytest.raises(ReleaseManifestError, match="changed during verification"):
        verify_current(target_release.parent, target_manifest)


@pytest.mark.parametrize("mutation", ["extra", "missing", "content", "writable"])
def test_verify_rejects_release_drift(tmp_path: Path, mutation: str) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    release.chmod(0o755)
    if mutation == "extra":
        (release / "extra.txt").write_text("extra", encoding="utf-8")
        (release / "extra.txt").chmod(0o444)
    elif mutation == "missing":
        (release / "README.md").unlink()
    elif mutation == "content":
        path = release / "README.md"
        path.chmod(0o644)
        path.write_text("changed\n", encoding="utf-8")
        path.chmod(0o444)
    else:
        (release / "README.md").chmod(0o644)
    release.chmod(0o555)

    with pytest.raises(ReleaseManifestError):
        verify_release(release, manifest)


def test_verify_rejects_wrong_directory_identity_and_linked_file(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    wrong = release.parent / ("f" * 40)
    release.rename(wrong)
    with pytest.raises(ReleaseManifestError, match="directory name"):
        verify_release(wrong, manifest)

    wrong.rename(release)
    release.chmod(0o755)
    target = tmp_path / "target"
    target.write_text("TradingDatas\n", encoding="utf-8")
    target.chmod(0o444)
    (release / "README.md").unlink()
    (release / "README.md").symlink_to(target)
    release.chmod(0o555)
    with pytest.raises(ReleaseManifestError, match="single-link"):
        verify_release(release, manifest)
    release.chmod(0o755)
    for path in release.rglob("*"):
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.chmod(0o755)
        else:
            path.chmod(0o644)


def test_verify_rejects_writable_or_extra_directory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)
    release.chmod(0o755)
    extra = release / "empty-extra"
    extra.mkdir()
    extra.chmod(0o555)
    release.chmod(0o555)

    # Empty directories are not Git identities and must not survive a release check.
    with pytest.raises(ReleaseManifestError):
        verify_release(release, manifest)


def test_verify_requires_exact_0555_release_directory_modes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = build_manifest(repo)
    release = _release(tmp_path, repo, manifest)

    release.chmod(0o500)
    with pytest.raises(ReleaseManifestError, match="0555"):
        verify_release(release, manifest)

    release.chmod(0o555)
    nested = release / "tools"
    nested.chmod(0o500)
    with pytest.raises(ReleaseManifestError, match="0555"):
        verify_release(release, manifest)
