#!/usr/bin/env python3
"""Build and verify deterministic TradingDatas immutable-release manifests."""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from typing import Iterable
import uuid


FORMAT_VERSION = 1
PRODUCT = "TradingDatas"
ALLOWED_GIT_MODES = {"100644", "100755"}
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_COMMIT_OBJECT_BYTES = 1024 * 1024


class ReleaseManifestError(ValueError):
    """A release or manifest violates the immutable-release contract."""


def _canonical_absolute_path(raw: str | os.PathLike[str], *, name: str) -> Path:
    value = os.fspath(raw)
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or not value.startswith("/")
        or value.startswith("//")
        or os.path.normpath(value) != value
    ):
        raise ReleaseManifestError(f"{name} must be absolute lexical canonical")
    return Path(value)


def _assert_no_symlink_components(path: Path, *, name: str) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReleaseManifestError(f"{name} path is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ReleaseManifestError(f"{name} path may not contain a symlink")


def _run_git(source_root: Path, *arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", "-C", os.fspath(source_root), *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseManifestError(f"git {' '.join(arguments)} failed: {stderr}")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="strict").strip()


def _validate_hex(value: object, *, name: str, length: int = 40) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ReleaseManifestError(f"{name} must be {length} lowercase hex characters")
    return value


def _git_object_id(object_type: bytes, payload: bytes) -> str:
    header = object_type + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def _commit_object(source_root: Path) -> bytes:
    payload = _run_git(source_root, "cat-file", "commit", "HEAD", binary=True)
    assert isinstance(payload, bytes)
    if not payload or len(payload) > MAX_COMMIT_OBJECT_BYTES:
        raise ReleaseManifestError("git commit object has an invalid size")
    return payload


def _validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReleaseManifestError("manifest file path must be non-empty UTF-8")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ReleaseManifestError("manifest file path must be relative canonical")
    return value


def _git_entries(source_root: Path) -> list[dict[str, object]]:
    raw = _run_git(
        source_root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", binary=True
    )
    assert isinstance(raw, bytes)
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, blob = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ReleaseManifestError("git tree contains an invalid entry") from exc
        path = _validate_relative_path(path)
        if path in seen:
            raise ReleaseManifestError(f"git tree contains duplicate path: {path}")
        seen.add(path)
        if object_type != "blob" or mode not in ALLOWED_GIT_MODES:
            raise ReleaseManifestError(
                f"git tree contains unsupported entry {path}: {mode} {object_type}"
            )
        blob = _validate_hex(blob, name=f"git blob for {path}")
        content = _run_git(source_root, "cat-file", "blob", blob, binary=True)
        assert isinstance(content, bytes)
        entries.append(
            {
                "path": path,
                "git_mode": mode,
                "git_blob": blob,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if not entries:
        raise ReleaseManifestError("git tree is empty")
    return sorted(entries, key=lambda entry: str(entry["path"]))


def build_manifest(source_root: Path) -> dict[str, object]:
    source_root = _canonical_absolute_path(source_root, name="source root")
    _assert_no_symlink_components(source_root, name="source root")
    if not source_root.is_dir():
        raise ReleaseManifestError("source root must be a directory")
    top_level = _run_git(source_root, "rev-parse", "--show-toplevel")
    if top_level != os.fspath(source_root):
        raise ReleaseManifestError("source root must be the git top level")
    status_output = _run_git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status_output:
        raise ReleaseManifestError("source worktree must be clean")
    commit = _validate_hex(_run_git(source_root, "rev-parse", "HEAD"), name="commit")
    tree = _validate_hex(_run_git(source_root, "rev-parse", "HEAD^{tree}"), name="tree")
    commit_object = _commit_object(source_root)
    if _git_object_id(b"commit", commit_object) != commit:
        raise ReleaseManifestError("git commit object does not match HEAD")
    return {
        "format_version": FORMAT_VERSION,
        "product": PRODUCT,
        "commit": commit,
        "tree": tree,
        "commit_object_b64": base64.b64encode(commit_object).decode("ascii"),
        "files": _git_entries(source_root),
    }


def canonical_manifest_bytes(manifest: dict[str, object]) -> bytes:
    validate_manifest(manifest)
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_file_entry(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != {
        "path",
        "git_mode",
        "git_blob",
        "size",
        "sha256",
    }:
        raise ReleaseManifestError("manifest file entry has an invalid shape")
    path = _validate_relative_path(raw["path"])
    mode = raw["git_mode"]
    if mode not in ALLOWED_GIT_MODES:
        raise ReleaseManifestError(f"manifest has unsupported git mode for {path}")
    blob = _validate_hex(raw["git_blob"], name=f"git blob for {path}")
    size = raw["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ReleaseManifestError(f"manifest size is invalid for {path}")
    sha256 = _validate_hex(raw["sha256"], name=f"sha256 for {path}", length=64)
    return {
        "path": path,
        "git_mode": mode,
        "git_blob": blob,
        "size": size,
        "sha256": sha256,
    }


def _git_tree_id(files: list[dict[str, object]]) -> str:
    files_by_directory: dict[tuple[str, ...], list[dict[str, object]]] = {}
    directories: set[tuple[str, ...]] = {()}
    for entry in files:
        parts = PurePosixPath(str(entry["path"])).parts
        parent = tuple(parts[:-1])
        files_by_directory.setdefault(parent, []).append(entry)
        for depth in range(len(parent) + 1):
            directories.add(parent[:depth])

    tree_ids: dict[tuple[str, ...], str] = {}
    for directory in sorted(directories, key=lambda value: (-len(value), value)):
        records: list[tuple[bytes, bytes]] = []
        names: set[bytes] = set()
        for entry in files_by_directory.get(directory, []):
            name = PurePosixPath(str(entry["path"])).name.encode("utf-8")
            if name in names:
                raise ReleaseManifestError("release manifest has a path collision")
            names.add(name)
            record = (
                str(entry["git_mode"]).encode("ascii")
                + b" "
                + name
                + b"\0"
                + bytes.fromhex(str(entry["git_blob"]))
            )
            records.append((name, record))
        child_directories = sorted(
            value
            for value in directories
            if len(value) == len(directory) + 1 and value[:-1] == directory
        )
        for child in child_directories:
            name = child[-1].encode("utf-8")
            if name in names:
                raise ReleaseManifestError("release manifest has a path collision")
            names.add(name)
            record = b"40000 " + name + b"\0" + bytes.fromhex(tree_ids[child])
            records.append((name + b"/", record))
        payload = b"".join(record for _sort_key, record in sorted(records))
        tree_ids[directory] = _git_object_id(b"tree", payload)
    return tree_ids[()]


def validate_manifest(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != {
        "format_version",
        "product",
        "commit",
        "tree",
        "commit_object_b64",
        "files",
    }:
        raise ReleaseManifestError("release manifest has an invalid shape")
    if raw["format_version"] != FORMAT_VERSION or raw["product"] != PRODUCT:
        raise ReleaseManifestError("release manifest identity is unsupported")
    commit = _validate_hex(raw["commit"], name="commit")
    tree = _validate_hex(raw["tree"], name="tree")
    encoded_commit = raw["commit_object_b64"]
    if not isinstance(encoded_commit, str) or not encoded_commit:
        raise ReleaseManifestError("release manifest commit object is invalid")
    try:
        commit_object = base64.b64decode(encoded_commit, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReleaseManifestError("release manifest commit object is invalid") from exc
    if (
        not commit_object
        or len(commit_object) > MAX_COMMIT_OBJECT_BYTES
        or base64.b64encode(commit_object).decode("ascii") != encoded_commit
        or _git_object_id(b"commit", commit_object) != commit
    ):
        raise ReleaseManifestError("release manifest commit identity is invalid")
    tree_header = f"tree {tree}\n".encode("ascii")
    if not commit_object.startswith(tree_header):
        raise ReleaseManifestError("release manifest commit tree is invalid")
    files_raw = raw["files"]
    if not isinstance(files_raw, list) or not files_raw:
        raise ReleaseManifestError("release manifest files must be a non-empty list")
    files = [_validate_file_entry(item) for item in files_raw]
    paths = [str(item["path"]) for item in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise ReleaseManifestError("release manifest files must be unique and sorted")
    if _git_tree_id(files) != tree:
        raise ReleaseManifestError("release manifest Git tree is invalid")
    return {
        "format_version": FORMAT_VERSION,
        "product": PRODUCT,
        "commit": commit,
        "tree": tree,
        "commit_object_b64": encoded_commit,
        "files": files,
    }


def load_manifest(
    path: Path,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    path = _canonical_absolute_path(path, name="manifest")
    _assert_no_symlink_components(path, name="manifest")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise ReleaseManifestError("manifest is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ReleaseManifestError("manifest must be a single-link regular file")
    _assert_owner(
        metadata,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        name="manifest",
    )
    if metadata.st_mode & 0o022:
        raise ReleaseManifestError("manifest may not be group/world writable")
    if metadata.st_size > MAX_MANIFEST_BYTES:
        raise ReleaseManifestError("manifest exceeds the size limit")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError("manifest is unreadable or invalid JSON") from exc
    manifest = validate_manifest(raw)
    if path.read_bytes() != canonical_manifest_bytes(manifest):
        raise ReleaseManifestError("manifest bytes are not canonical")
    return manifest


def _assert_owner(
    metadata: os.stat_result,
    *,
    expected_uid: int | None,
    expected_gid: int | None,
    name: str,
) -> None:
    if expected_uid is not None and metadata.st_uid != expected_uid:
        raise ReleaseManifestError(f"{name} owner uid is invalid")
    if expected_gid is not None and metadata.st_gid != expected_gid:
        raise ReleaseManifestError(f"{name} owner gid is invalid")


def _iter_release_files(
    release_root: Path,
    *,
    expected_directories: set[str],
    expected_uid: int | None,
    expected_gid: int | None,
) -> Iterable[tuple[str, Path, os.stat_result]]:
    for current_root, directory_names, file_names in os.walk(
        release_root, topdown=True, followlinks=False
    ):
        current = Path(current_root)
        for name in tuple(directory_names):
            path = current / name
            metadata = os.lstat(path)
            relative = path.relative_to(release_root).as_posix()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ReleaseManifestError(
                    "release contains a linked or special directory"
                )
            if stat.S_IMODE(metadata.st_mode) != 0o555:
                raise ReleaseManifestError("release directory mode must be 0555")
            _assert_owner(
                metadata,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
                name=f"release directory {relative}",
            )
            if relative not in expected_directories:
                raise ReleaseManifestError(
                    f"release contains unexpected directory: {relative}"
                )
        for name in file_names:
            path = current / name
            metadata = os.lstat(path)
            relative = path.relative_to(release_root).as_posix()
            yield relative, path, metadata


def verify_release(
    release_root: Path,
    manifest: dict[str, object],
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    release_root = _canonical_absolute_path(release_root, name="release root")
    _assert_no_symlink_components(release_root, name="release root")
    manifest = validate_manifest(manifest)
    if release_root.name != manifest["commit"]:
        raise ReleaseManifestError(
            "release directory name must equal the manifest commit"
        )
    try:
        root_metadata = os.lstat(release_root)
    except OSError as exc:
        raise ReleaseManifestError("release root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) != 0o555
    ):
        raise ReleaseManifestError("release root mode must be 0555")
    _assert_owner(
        root_metadata,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        name="release root",
    )

    expected = {str(item["path"]): item for item in manifest["files"]}  # type: ignore[index]
    expected_directories: set[str] = set()
    for relative in expected:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    observed: set[str] = set()
    for relative, path, metadata in _iter_release_files(
        release_root,
        expected_directories=expected_directories,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    ):
        relative = _validate_relative_path(relative)
        if relative not in expected:
            raise ReleaseManifestError(f"release contains unexpected file: {relative}")
        if relative in observed:
            raise ReleaseManifestError(f"release contains duplicate file: {relative}")
        observed.add(relative)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ReleaseManifestError(
                f"release file is not single-link regular: {relative}"
            )
        _assert_owner(
            metadata,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            name=f"release file {relative}",
        )
        expected_entry = expected[relative]
        expected_mode = 0o555 if expected_entry["git_mode"] == "100755" else 0o444
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise ReleaseManifestError(f"release file mode is invalid: {relative}")
        content = path.read_bytes()
        if (
            len(content) != expected_entry["size"]
            or hashlib.sha256(content).hexdigest() != expected_entry["sha256"]
            or _git_object_id(b"blob", content) != expected_entry["git_blob"]
        ):
            raise ReleaseManifestError(f"release file content is invalid: {relative}")
    missing = sorted(set(expected) - observed)
    if missing:
        raise ReleaseManifestError(f"release is missing file: {missing[0]}")
    return {
        "product": PRODUCT,
        "commit": manifest["commit"],
        "tree": manifest["tree"],
        "file_count": len(expected),
        "verified": True,
    }


def _validated_releases_root(
    raw: Path,
    *,
    expected_uid: int | None,
    expected_gid: int | None,
) -> Path:
    releases_root = _canonical_absolute_path(raw, name="releases root")
    _assert_no_symlink_components(releases_root, name="releases root")
    try:
        metadata = os.lstat(releases_root)
    except OSError as exc:
        raise ReleaseManifestError("releases root is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o022:
        raise ReleaseManifestError(
            "releases root must be a non-group/world-writable directory"
        )
    _assert_owner(
        metadata,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        name="releases root",
    )
    return releases_root


def _read_current_target_at(directory_descriptor: int) -> str:
    try:
        target = os.readlink("current", dir_fd=directory_descriptor)
    except OSError as exc:
        raise ReleaseManifestError("current must be a readable symlink") from exc
    return _validate_hex(target, name="current target")


def verify_current(
    releases_root: Path,
    manifest: dict[str, object],
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    manifest = validate_manifest(manifest)
    releases_root = _validated_releases_root(
        releases_root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(releases_root, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        target = _read_current_target_at(descriptor)
        if target != manifest["commit"]:
            raise ReleaseManifestError(
                "current target does not match the manifest commit"
            )
        result = verify_release(
            releases_root / target,
            manifest,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if _read_current_target_at(descriptor) != target:
            raise ReleaseManifestError("current target changed during verification")
        return result
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _replace_current_at(directory_descriptor: int, target: str) -> bool:
    target = _validate_hex(target, name="target commit")
    temporary = f".current.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    replaced = False
    try:
        os.symlink(target, temporary, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        os.replace(
            temporary,
            "current",
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        replaced = True
        os.fsync(directory_descriptor)
        if _read_current_target_at(directory_descriptor) != target:
            raise ReleaseManifestError("current post-switch identity is invalid")
        return replaced
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass


def switch_current(
    releases_root: Path,
    target_manifest: dict[str, object],
    rollback_manifest: dict[str, object],
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    target_manifest = validate_manifest(target_manifest)
    rollback_manifest = validate_manifest(rollback_manifest)
    releases_root = _validated_releases_root(
        releases_root,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    target = str(target_manifest["commit"])
    rollback = str(rollback_manifest["commit"])
    if target == rollback:
        return verify_current(
            releases_root,
            target_manifest,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(releases_root, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        observed = _read_current_target_at(descriptor)
        if observed != rollback:
            raise ReleaseManifestError(
                "current target does not match rollback manifest"
            )
        verify_release(
            releases_root / rollback,
            rollback_manifest,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        verify_release(
            releases_root / target,
            target_manifest,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        replaced = False
        try:
            replaced = _replace_current_at(descriptor, target)
        except BaseException as exc:
            needs_restore = replaced
            if not needs_restore:
                try:
                    needs_restore = _read_current_target_at(descriptor) != rollback
                except BaseException:
                    needs_restore = True
            if needs_restore:
                try:
                    _replace_current_at(descriptor, rollback)
                except BaseException as restore_exc:
                    raise ReleaseManifestError(
                        "current switch failed and rollback restoration failed"
                    ) from restore_exc
            if isinstance(exc, ReleaseManifestError):
                raise
            raise ReleaseManifestError("current switch failed") from exc
        return {
            "product": PRODUCT,
            "previous_commit": rollback,
            "current_commit": target,
            "switched": True,
        }
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path = _canonical_absolute_path(path, name="manifest output")
    _assert_no_symlink_components(path.parent, name="manifest output parent")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = canonical_manifest_bytes(manifest)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build a manifest from clean HEAD")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="verify an immutable release")
    verify.add_argument("--release-root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-uid", type=int, required=True)
    verify.add_argument("--expected-gid", type=int, required=True)
    current = subparsers.add_parser("verify-current", help="verify current release")
    current.add_argument("--releases-root", type=Path, required=True)
    current.add_argument("--manifest", type=Path, required=True)
    current.add_argument("--expected-uid", type=int, required=True)
    current.add_argument("--expected-gid", type=int, required=True)
    switch = subparsers.add_parser("switch-current", help="atomically switch current")
    switch.add_argument("--releases-root", type=Path, required=True)
    switch.add_argument("--target-manifest", type=Path, required=True)
    switch.add_argument("--rollback-manifest", type=Path, required=True)
    switch.add_argument("--expected-uid", type=int, required=True)
    switch.add_argument("--expected-gid", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "build":
            manifest = build_manifest(arguments.source_root)
            write_manifest(arguments.output, manifest)
            result = {
                "commit": manifest["commit"],
                "file_count": len(manifest["files"]),  # type: ignore[arg-type]
                "manifest_sha256": hashlib.sha256(
                    canonical_manifest_bytes(manifest)
                ).hexdigest(),
                "written": os.fspath(arguments.output),
            }
        elif arguments.command == "verify":
            manifest = load_manifest(
                arguments.manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
            result = verify_release(
                arguments.release_root,
                manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
        elif arguments.command == "verify-current":
            manifest = load_manifest(
                arguments.manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
            result = verify_current(
                arguments.releases_root,
                manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
        else:
            target_manifest = load_manifest(
                arguments.target_manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
            rollback_manifest = load_manifest(
                arguments.rollback_manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
            result = switch_current(
                arguments.releases_root,
                target_manifest,
                rollback_manifest,
                expected_uid=arguments.expected_uid,
                expected_gid=arguments.expected_gid,
            )
    except ReleaseManifestError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 78
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
