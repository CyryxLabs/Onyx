"""Create a deterministic, allowlisted Onyx release-source freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


ALLOWLIST_DIRECTORIES = (
    ".github",
    "actions",
    "config",
    "core",
    "dashboard",
    "docs",
    "memory",
    "packaging",
    "plans",
    "qml",
    "scripts",
    "tests",
)
ALLOWLIST_FILES = (
    ".dockerignore",
    ".gitignore",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "main.py",
    "pytest.ini",
    "readme.md",
    "requirements-build.txt",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements.txt",
    "ruff.toml",
    "setup.py",
    "ui.py",
)
EXCLUDED_SEGMENTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "release",
        "rollback",
        "runtime",
    }
)
EXCLUDED_PREFIXES = (
    ".audit",
    ".cert",
    ".codex-tmp",
    ".diag",
    ".pytest",
    ".review",
    ".tmp",
    ".verify",
)
SECRET_SUFFIXES = (".key", ".p12", ".pem", ".pfx")
AGGREGATE_CONTRACT = (
    "sha256(path_length_u64be || path_utf8 || size_u64be || file_sha256_bytes)"
)


class SourceFreezeError(RuntimeError):
    """The requested source freeze is unsafe or not reproducible."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded(relative: PurePosixPath) -> bool:
    for part in relative.parts:
        lowered = part.casefold()
        if lowered in EXCLUDED_SEGMENTS:
            return True
        if any(lowered.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return True
    return relative.suffix.casefold() in SECRET_SUFFIXES


def _source_files(source: Path) -> list[tuple[str, Path]]:
    selected: dict[str, Path] = {}
    for name in ALLOWLIST_FILES:
        candidate = source / name
        if candidate.is_symlink():
            raise SourceFreezeError(f"linked release input: {name}")
        if candidate.is_file():
            selected[PurePosixPath(name).as_posix()] = candidate
    for directory in ALLOWLIST_DIRECTORIES:
        root = source / directory
        if root.is_symlink():
            raise SourceFreezeError(f"linked release input: {directory}")
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            relative = PurePosixPath(candidate.relative_to(source).as_posix())
            if _excluded(relative):
                continue
            if candidate.is_symlink():
                raise SourceFreezeError(f"linked release input: {relative}")
            if candidate.is_file():
                selected[relative.as_posix()] = candidate
    if not selected:
        raise SourceFreezeError("release source allowlist is empty")
    return sorted(selected.items())


def _strict_authority(source: Path, relative: str, schema: str) -> dict[str, str]:
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or parsed.as_posix() != relative or ".." in parsed.parts:
        raise SourceFreezeError(f"noncanonical authority path: {relative}")
    path = source.joinpath(*parsed.parts)
    if path.is_symlink() or not path.is_file():
        raise SourceFreezeError(f"authority unavailable: {relative}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFreezeError(f"invalid authority JSON: {relative}") from exc
    if type(record) is not dict or record.get("schema") != schema:
        raise SourceFreezeError(f"authority schema drifted: {relative}")
    root = record.get("current_root_sha256")
    if type(root) is not str or len(root) != 64:
        raise SourceFreezeError(f"authority root drifted: {relative}")
    return {
        "path": relative,
        "sha256": _sha256(path),
        "schema": schema,
        "current_root_sha256": root,
    }


def _git_state(source: Path) -> dict[str, Any]:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise SourceFreezeError("git executable is unavailable")

    def run(*arguments: str) -> bytes:
        completed = subprocess.run(  # noqa: S603 - fixed executable and arguments
            [git_executable, *arguments],
            cwd=source,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return completed.stdout

    head = run("rev-parse", "HEAD").decode("ascii").strip()
    branch = run("branch", "--show-current").decode("utf-8").strip()
    porcelain = run("status", "--porcelain=v1", "-z")
    return {
        "head": head,
        "branch": branch,
        "porcelain_v1_z_bytes": len(porcelain),
        "porcelain_v1_z_sha256": hashlib.sha256(porcelain).hexdigest(),
        "nul_record_count": porcelain.count(b"\0"),
        "clean": not porcelain,
    }


def _aggregate(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        encoded = entry["path"].encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(int(entry["size"]).to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry["sha256"]))
    return digest.hexdigest()


def freeze(
    *,
    source: Path,
    candidate_root: Path,
    manifest_path: Path,
    candidate_label: str,
) -> dict[str, Any]:
    source = source.resolve(strict=True)
    candidate_root = candidate_root.resolve(strict=False)
    manifest_path = manifest_path.resolve(strict=False)
    if candidate_root.exists() or manifest_path.exists():
        raise SourceFreezeError("candidate root and manifest must not already exist")
    try:
        candidate_root.relative_to(source)
    except ValueError:
        pass
    else:
        raise SourceFreezeError("candidate root must not be inside the source tree")
    if source.is_symlink() or candidate_root.parent.is_symlink():
        raise SourceFreezeError("source or destination parent is linked")

    sources = _source_files(source)
    phase5 = _strict_authority(
        source,
        "tests/fixtures/phase5_current_successor_transition_v51.json",
        "onyx.phase5-current-successor-transition.v51",
    )
    release = _strict_authority(
        source,
        "tests/fixtures/release_workflow_transition_v53.json",
        "onyx.release-workflow-transition.v53",
    )
    candidate_root.mkdir(parents=False)
    entries: list[dict[str, Any]] = []
    try:
        for relative, origin in sources:
            destination = candidate_root.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
            size = destination.stat().st_size
            digest = _sha256(destination)
            if size != origin.stat().st_size or digest != _sha256(origin):
                raise SourceFreezeError(f"copied release input drifted: {relative}")
            entries.append({"path": relative, "size": size, "sha256": digest})
    except BaseException:
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise

    record = {
        "schema": "onyx.source-freeze.v1",
        "candidate": candidate_label,
        "source_root": str(source),
        "candidate_root": str(candidate_root),
        "allowlist": {
            "directories": list(ALLOWLIST_DIRECTORIES),
            "files": list(ALLOWLIST_FILES),
            "excluded_segments": sorted(EXCLUDED_SEGMENTS),
            "excluded_prefixes": list(EXCLUDED_PREFIXES),
            "secret_suffixes": list(SECRET_SUFFIXES),
        },
        "git_state": _git_state(source),
        "authority": {"phase5_v51": phase5, "release_v53": release},
        "file_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "aggregate_contract": AGGREGATE_CONTRACT,
        "root_sha256": _aggregate(entries),
        "files": entries,
    }
    manifest_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-label", required=True)
    return parser


if __name__ == "__main__":
    arguments = _parser().parse_args()
    result = freeze(
        source=arguments.source,
        candidate_root=arguments.candidate_root,
        manifest_path=arguments.manifest,
        candidate_label=arguments.candidate_label,
    )
    print(
        json.dumps(
            {
                "file_count": result["file_count"],
                "root_sha256": result["root_sha256"],
                "total_bytes": result["total_bytes"],
            },
            sort_keys=True,
        )
    )
