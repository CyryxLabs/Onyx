"""Resolve exact current/prior artifacts for native qualification jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
THUMBPRINT = re.compile(r"^[0-9A-F]{40}$")
SUFFIX = {"Windows": "-Setup.exe", "Darwin": ".dmg", "Linux": ".deb"}
SBOM_PLATFORM = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}


class QualificationArtifactError(RuntimeError):
    """A downloaded build/release artifact is missing, ambiguous, or drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1 or matches[0].is_symlink():
        raise QualificationArtifactError(
            f"expected one regular downloaded file named {name}, found {len(matches)}"
        )
    return matches[0].resolve(strict=True)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationArtifactError(f"invalid JSON: {path.name}") from exc
    if type(value) is not dict:
        raise QualificationArtifactError(f"JSON root is not an object: {path.name}")
    return value


def _manifest(
    root: Path,
    *,
    system: str,
    architecture: str,
    version: str,
) -> tuple[Path, dict[str, Any]]:
    path = _unique(root, f"release-manifest-{system}-{architecture}.json")
    value = _load(path)
    if (
        value.get("product") != "Onyx"
        or value.get("system") != system
        or str(value.get("architecture", "")).casefold()
        != architecture.casefold()
        or value.get("version") != version
    ):
        raise QualificationArtifactError(f"manifest identity drifted: {path.name}")
    return path, value


def _artifact(
    root: Path,
    manifest: dict[str, Any],
    suffix: str,
) -> tuple[Path, str]:
    records = manifest.get("artifacts")
    matches = [
        record
        for record in records
        if type(record) is dict
        and type(record.get("name")) is str
        and record["name"].endswith(suffix)
    ] if type(records) is list else []
    if len(matches) != 1 or SHA256.fullmatch(str(matches[0].get("sha256", ""))) is None:
        raise QualificationArtifactError(f"one manifest artifact ending {suffix} is required")
    record = matches[0]
    path = _unique(root, record["name"])
    if path.stat().st_size != record.get("size") or _sha256(path) != record["sha256"]:
        raise QualificationArtifactError(f"artifact bytes drifted: {path.name}")
    return path, record["sha256"]


def _windows_thumbprint(root: Path, architecture: str) -> str:
    evidence = _load(_unique(root, f"windows-release-evidence-{architecture}.json"))
    thumbprint = str(evidence.get("signer_thumbprint", "")).upper()
    if (
        evidence.get("contract") != "onyx.windows-release-evidence.v1"
        or evidence.get("formal") is not True
        or evidence.get("all_trusted") is not True
        or THUMBPRINT.fullmatch(thumbprint) is None
    ):
        raise QualificationArtifactError("trusted Windows signer evidence is absent")
    return thumbprint


def resolve_inputs(
    *,
    current_dir: Path,
    prior_dir: Path,
    system: str,
    architecture: str,
    current_version: str,
    prior_version: str,
) -> dict[str, str]:
    current_root = Path(current_dir).resolve(strict=True)
    prior_root = Path(prior_dir).resolve(strict=True)
    if system not in SUFFIX or not architecture or current_version == prior_version:
        raise QualificationArtifactError("qualification target/version contract is invalid")
    current_manifest_path, current_manifest = _manifest(
        current_root,
        system=system,
        architecture=architecture,
        version=current_version,
    )
    prior_manifest_path, prior_manifest = _manifest(
        prior_root,
        system=system,
        architecture=architecture,
        version=prior_version,
    )
    current_artifact, current_sha = _artifact(
        current_root, current_manifest, SUFFIX[system]
    )
    prior_artifact, prior_sha = _artifact(prior_root, prior_manifest, SUFFIX[system])
    bundle = current_manifest.get("bundle_inventory")
    build_input = current_manifest.get("build_input_seal")
    bundle_root = bundle.get("bundle_root_sha256") if type(bundle) is dict else None
    source_sha = (
        build_input.get("manifest_sha256") if type(build_input) is dict else None
    )
    if SHA256.fullmatch(str(bundle_root or "")) is None or SHA256.fullmatch(
        str(source_sha or "")
    ) is None:
        raise QualificationArtifactError("manifest build/bundle binding is incomplete")
    result = {
        "bundle_root_sha256": str(bundle_root),
        "current_artifact": str(current_artifact),
        "current_manifest": str(current_manifest_path),
        "current_manifest_sha256": _sha256(current_manifest_path),
        "current_sha256": current_sha,
        "prior_artifact": str(prior_artifact),
        "prior_manifest": str(prior_manifest_path),
        "prior_manifest_sha256": _sha256(prior_manifest_path),
        "prior_sha256": prior_sha,
        "source_transition_sha256": str(source_sha),
    }
    if system == "Windows":
        portable, portable_sha = _artifact(
            current_root, current_manifest, "-Portable.zip"
        )
        sbom = _unique(
            current_root,
            f"SBOM-{SBOM_PLATFORM[system]}-{architecture}.spdx.json",
        )
        result.update(
            {
                "current_portable": str(portable),
                "current_portable_sha256": portable_sha,
                "current_signer_thumbprint": _windows_thumbprint(
                    current_root, architecture
                ),
                "prior_signer_thumbprint": _windows_thumbprint(
                    prior_root, architecture
                ),
                "sbom": str(sbom),
                "sbom_sha256": _sha256(sbom),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--prior-dir", type=Path, required=True)
    parser.add_argument("--system", choices=tuple(SUFFIX), required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--prior-version", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        result = resolve_inputs(
            current_dir=args.current_dir,
            prior_dir=args.prior_dir,
            system=args.system,
            architecture=args.architecture,
            current_version=args.current_version,
            prior_version=args.prior_version,
        )
    except (OSError, QualificationArtifactError) as exc:
        print(f"Qualification artifact preparation: BLOCKED: {exc}")
        return 1
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
            for key, value in sorted(result.items()):
                handle.write(f"{key}={value}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
