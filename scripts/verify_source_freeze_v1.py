"""Independently verify an exact Onyx source-freeze manifest and tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
AGGREGATE_CONTRACT = (
    "sha256(path_length_u64be || path_utf8 || size_u64be || file_sha256_bytes)"
)
AUTHORITIES = {
    "phase5_v51": (
        "tests/fixtures/phase5_current_successor_transition_v51.json",
        "onyx.phase5-current-successor-transition.v51",
    ),
    "release_v53": (
        "tests/fixtures/release_workflow_transition_v53.json",
        "onyx.release-workflow-transition.v53",
    ),
}


class SourceFreezeVerificationError(RuntimeError):
    """The frozen source tree or its manifest is malformed or drifted."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceFreezeVerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SourceFreezeVerificationError(f"{label} is absent or linked")
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise SourceFreezeVerificationError(f"{label} is not canonical UTF-8 JSON")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFreezeVerificationError(f"{label} is invalid JSON") from exc
    if type(payload) is not dict:
        raise SourceFreezeVerificationError(f"{label} is not an object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(value: object) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise SourceFreezeVerificationError("freeze path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise SourceFreezeVerificationError("freeze path is not canonical")
    return value


def _aggregate(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        encoded = entry["path"].encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(entry["size"].to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry["sha256"]))
    return digest.hexdigest()


def _actual_files(root: Path) -> list[str]:
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SourceFreezeVerificationError(
                f"frozen tree contains a link: {path.relative_to(root)}"
            )
        if path.is_file():
            files.append(PurePosixPath(path.relative_to(root).as_posix()).as_posix())
    return sorted(files)


def verify_source_freeze(
    *, manifest_path: Path, candidate_root: Path, candidate_label: str
) -> dict[str, object]:
    """Verify exact membership, bytes, root, authority and recorded identity."""

    manifest_path = Path(manifest_path).resolve(strict=True)
    root = Path(candidate_root).resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise SourceFreezeVerificationError("candidate root is absent or linked")
    manifest = _load_json(manifest_path, "source freeze manifest")
    if set(manifest) != {
        "schema",
        "candidate",
        "source_root",
        "candidate_root",
        "allowlist",
        "git_state",
        "authority",
        "file_count",
        "total_bytes",
        "aggregate_contract",
        "root_sha256",
        "files",
    }:
        raise SourceFreezeVerificationError("source freeze contract drifted")
    if (
        manifest.get("schema") != "onyx.source-freeze.v1"
        or manifest.get("candidate") != candidate_label
        or manifest.get("candidate_root") != str(root)
        or type(manifest.get("source_root")) is not str
        or not manifest["source_root"]
        or manifest.get("aggregate_contract") != AGGREGATE_CONTRACT
        or SHA256.fullmatch(str(manifest.get("root_sha256", ""))) is None
    ):
        raise SourceFreezeVerificationError("source freeze identity drifted")

    allowlist = manifest.get("allowlist")
    if type(allowlist) is not dict or set(allowlist) != {
        "directories",
        "files",
        "excluded_segments",
        "excluded_prefixes",
        "secret_suffixes",
    } or any(type(value) is not list for value in allowlist.values()):
        raise SourceFreezeVerificationError("source freeze allowlist drifted")
    git_state = manifest.get("git_state")
    if (
        type(git_state) is not dict
        or set(git_state)
        != {
            "head",
            "branch",
            "porcelain_v1_z_bytes",
            "porcelain_v1_z_sha256",
            "nul_record_count",
            "clean",
        }
        or GIT_SHA.fullmatch(str(git_state.get("head", ""))) is None
        or type(git_state.get("branch")) is not str
        or type(git_state.get("porcelain_v1_z_bytes")) is not int
        or isinstance(git_state.get("porcelain_v1_z_bytes"), bool)
        or type(git_state.get("nul_record_count")) is not int
        or isinstance(git_state.get("nul_record_count"), bool)
        or SHA256.fullmatch(str(git_state.get("porcelain_v1_z_sha256", ""))) is None
        or type(git_state.get("clean")) is not bool
    ):
        raise SourceFreezeVerificationError("source freeze Git state drifted")

    records = manifest.get("files")
    if type(records) is not list or not records:
        raise SourceFreezeVerificationError("source freeze file inventory is absent")
    paths: list[str] = []
    total_bytes = 0
    for record in records:
        if (
            type(record) is not dict
            or set(record) != {"path", "size", "sha256"}
            or type(record.get("size")) is not int
            or isinstance(record.get("size"), bool)
            or record["size"] < 0
            or SHA256.fullmatch(str(record.get("sha256", ""))) is None
        ):
            raise SourceFreezeVerificationError("source freeze file record drifted")
        relative = _relative(record["path"])
        paths.append(relative)
        target = root.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise SourceFreezeVerificationError(
                f"frozen file path escapes candidate: {relative}"
            ) from exc
        if (
            target.is_symlink()
            or not resolved.is_file()
            or resolved != target.absolute()
            or resolved.stat().st_size != record["size"]
            or _sha256(resolved) != record["sha256"]
        ):
            raise SourceFreezeVerificationError(f"frozen file bytes drifted: {relative}")
        total_bytes += record["size"]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise SourceFreezeVerificationError("source freeze paths are unordered or duplicate")
    if _actual_files(root) != paths:
        raise SourceFreezeVerificationError("frozen tree exact membership drifted")
    if (
        manifest.get("file_count") != len(records)
        or manifest.get("total_bytes") != total_bytes
        or manifest.get("root_sha256") != _aggregate(records)
    ):
        raise SourceFreezeVerificationError("source freeze aggregate drifted")

    authority = manifest.get("authority")
    if type(authority) is not dict or set(authority) != set(AUTHORITIES):
        raise SourceFreezeVerificationError("source freeze authority set drifted")
    for name, (relative, schema) in AUTHORITIES.items():
        binding = authority[name]
        if type(binding) is not dict or set(binding) != {
            "path",
            "sha256",
            "schema",
            "current_root_sha256",
        }:
            raise SourceFreezeVerificationError(f"source authority drifted: {name}")
        target = root.joinpath(*PurePosixPath(relative).parts)
        payload = _load_json(target, f"{name} authority")
        if (
            binding.get("path") != relative
            or binding.get("schema") != schema
            or binding.get("sha256") != _sha256(target)
            or payload.get("schema") != schema
            or binding.get("current_root_sha256")
            != payload.get("current_root_sha256")
            or SHA256.fullmatch(str(binding.get("current_root_sha256", ""))) is None
        ):
            raise SourceFreezeVerificationError(f"source authority bytes drifted: {name}")
    return {
        "contract": "onyx.source-freeze-verification.v1",
        "candidate": candidate_label,
        "file_count": len(records),
        "root_sha256": manifest["root_sha256"],
        "total_bytes": total_bytes,
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--candidate-label", required=True)
    args = parser.parse_args()
    try:
        result = verify_source_freeze(
            manifest_path=args.manifest,
            candidate_root=args.candidate_root,
            candidate_label=args.candidate_label,
        )
    except (OSError, SourceFreezeVerificationError) as exc:
        print(f"Source freeze verification: BLOCKED: {exc}")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
