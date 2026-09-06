"""Verify the exact, acyclic Phase 5.1 R2 evidence DAG."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R2-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R2-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-grants-r2/phase5-grants-r2.bundle.json"

TOP_PATHS = (ARTIFACT_MANIFEST,)
ARTIFACT_PATHS = (
    "core/session_grants_v2.py",
    "docs/onyx/checkpoints/phase5-grants-r2/PHASE5_1_GRANTS_SHADOW_R2_CHECKPOINT.md",
    "docs/onyx/checkpoints/phase5-grants-r2/phase5-grants-r2.bundle.json",
    "docs/onyx/checkpoints/phase5-grants-r2/phase5-grants-r2.junit.xml",
    "docs/onyx/checkpoints/phase5-grants-r2/phase5-grants-r2.raw.log",
    "docs/onyx/checkpoints/phase5-grants-r2/phase5-grants-r2.static.log",
    "scripts/verify_phase5_grants_r2.py",
    "tests/test_session_grants_v2.py",
)
_LINE = re.compile(r"([0-9a-f]{64})  ([a-zA-Z0-9][a-zA-Z0-9._/-]*)\Z")
_BUNDLE_KEYS = frozenset(
    {
        "base_commit",
        "contract",
        "counts",
        "dag",
        "environment",
        "feature_flag",
        "files",
        "limits",
        "status",
        "timestamp",
    }
)


class Phase5GrantEvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_manifest(path: Path, expected: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase5GrantEvidenceError(f"manifest unavailable: {path.name}") from exc
    if b"\r" in raw or not raw.endswith(b"\n") or raw.startswith(b"\xef\xbb\xbf"):
        raise Phase5GrantEvidenceError(f"manifest is not canonical UTF-8 LF: {path.name}")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Phase5GrantEvidenceError(f"manifest is not UTF-8: {path.name}") from exc
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise Phase5GrantEvidenceError(f"manifest line is not canonical: {path.name}")
        digest, relative = match.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
            raise Phase5GrantEvidenceError(f"manifest path is unsafe: {relative}")
        entries.append((digest, relative))
    paths = tuple(relative for _digest, relative in entries)
    if paths != expected or len(set(paths)) != len(paths):
        raise Phase5GrantEvidenceError(f"manifest exact set/order mismatch: {path.name}")
    return tuple(entries)


def _verify_entries(root: Path, entries: tuple[tuple[str, str], ...]) -> None:
    for expected, relative in entries:
        candidate = root / Path(*PurePosixPath(relative).parts)
        if not candidate.is_file():
            raise Phase5GrantEvidenceError(f"evidence file missing: {relative}")
        if _sha(candidate) != expected:
            raise Phase5GrantEvidenceError(f"evidence hash mismatch: {relative}")


def _verify_bundle(root: Path) -> None:
    path = root / Path(*PurePosixPath(BUNDLE).parts)
    raw = path.read_bytes()
    try:
        bundle = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantEvidenceError("bundle is not canonical JSON") from exc
    canonical = (
        json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if raw != canonical or not isinstance(bundle, dict) or frozenset(bundle) != _BUNDLE_KEYS:
        raise Phase5GrantEvidenceError("bundle shape/serialization is not exact")
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v2":
        raise Phase5GrantEvidenceError("bundle contract is invalid")
    if bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantEvidenceError("bundle status is invalid")
    if bundle.get("feature_flag") != {"name": "ONYX_GRANT_EVALUATOR", "default": False}:
        raise Phase5GrantEvidenceError("bundle feature flag is invalid")
    if bundle.get("dag") != {
        "root": TOP_MANIFEST,
        "root_points_to": [ARTIFACT_MANIFEST],
        "artifact_points_to": list(ARTIFACT_PATHS),
        "leaf_hashes_are_only_in_bundle": True,
    }:
        raise Phase5GrantEvidenceError("bundle DAG declaration is invalid")
    files = bundle.get("files")
    leaf_paths = tuple(path for path in ARTIFACT_PATHS if path != BUNDLE)
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantEvidenceError("bundle leaf file set is not exact")
    for relative, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Phase5GrantEvidenceError("bundle leaf digest is invalid")
        candidate = root / Path(*PurePosixPath(relative).parts)
        if _sha(candidate) != digest:
            raise Phase5GrantEvidenceError(f"bundle leaf hash mismatch: {relative}")
    if "root_manifest_sha256" in bundle or "artifact_manifest_sha256" in bundle:
        raise Phase5GrantEvidenceError("bundle introduces a manifest hash cycle")


def verify_evidence(root: Path = PROJECT) -> dict[str, object]:
    root = root.resolve()
    top = _parse_manifest(root / TOP_MANIFEST, TOP_PATHS)
    _verify_entries(root, top)
    artifacts = _parse_manifest(root / ARTIFACT_MANIFEST, ARTIFACT_PATHS)
    _verify_entries(root, artifacts)
    _verify_bundle(root)
    return {
        "artifact_files": len(artifacts),
        "artifact_manifest_sha256": _sha(root / ARTIFACT_MANIFEST),
        "root_files": len(top),
        "root_manifest_sha256": _sha(root / TOP_MANIFEST),
    }


def main() -> int:
    result = verify_evidence()
    print(
        "P51_GRANTS_R2_EVIDENCE_OK "
        f"root={result['root_files']} artifacts={result['artifact_files']} "
        f"root_sha256={result['root_manifest_sha256']} "
        f"artifact_sha256={result['artifact_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
