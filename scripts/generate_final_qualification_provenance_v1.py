"""Generate a canonical build-to-qualification manifest binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
WORKFLOW_SHA = re.compile(r"^[0-9a-f]{40}$")
TARGET = re.compile(r"^(Windows|Darwin|Linux)-([A-Za-z0-9_]+)$")
AGGREGATE_SBOM = "SBOM.spdx.json"
AGGREGATE_SBOM_DIGEST = "SBOM.spdx.json.sha256"


class QualificationProvenanceError(RuntimeError):
    """The requested provenance cannot be issued from the supplied bytes."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationProvenanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path, target: str, version: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise QualificationProvenanceError(f"manifest is absent: {path.name}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationProvenanceError(
            f"manifest is not strict UTF-8 JSON: {path.name}"
        ) from exc
    match = TARGET.fullmatch(target)
    if (
        type(payload) is not dict
        or match is None
        or payload.get("system") != match.group(1)
        or str(payload.get("architecture", "")).casefold()
        != match.group(2).casefold()
        or payload.get("version") != version
        or payload.get("release_class") != "formal"
        or payload.get("diagnostic_exceptions") != []
    ):
        raise QualificationProvenanceError(
            f"formal manifest identity drifted: {path.name}"
        )
    records = payload.get("artifacts")
    if type(records) is not list or not records:
        raise QualificationProvenanceError(
            f"manifest artifact inventory is absent: {path.name}"
        )
    for record in records:
        if (
            type(record) is not dict
            or type(record.get("name")) is not str
            or Path(record["name"]).name != record["name"]
            or type(record.get("size")) is not int
            or isinstance(record.get("size"), bool)
            or type(record.get("sha256")) is not str
            or SHA256.fullmatch(record["sha256"]) is None
        ):
            raise QualificationProvenanceError(
                f"manifest artifact record is malformed: {path.name}"
            )
        artifact = path.parent / record["name"]
        if (
            not artifact.is_file()
            or artifact.is_symlink()
            or artifact.stat().st_size != record["size"]
            or _sha256(artifact) != record["sha256"]
        ):
            raise QualificationProvenanceError(
                f"manifest artifact bytes drifted: {record['name']}"
            )
    return payload


def generate_provenance(
    *,
    release_dir: Path,
    version: str,
    required_targets: tuple[str, ...],
    build_run_id: str,
    build_sha: str,
    qualification_run_id: str,
    qualification_sha: str,
) -> dict[str, object]:
    """Bind exact formal manifests to the build and qualification runs."""

    root = Path(release_dir).resolve(strict=True)
    if (
        not version
        or version.strip() != version
        or not build_run_id.isdecimal()
        or not qualification_run_id.isdecimal()
        or WORKFLOW_SHA.fullmatch(build_sha) is None
        or WORKFLOW_SHA.fullmatch(qualification_sha) is None
    ):
        raise QualificationProvenanceError("workflow identity is malformed")
    targets = sorted(set(required_targets))
    if len(targets) != len(required_targets) or not targets:
        raise QualificationProvenanceError("target matrix is absent or duplicated")
    manifests: list[dict[str, str]] = []
    for target in targets:
        if TARGET.fullmatch(target) is None:
            raise QualificationProvenanceError(f"target is malformed: {target}")
        path = root / f"release-manifest-{target}.json"
        _load_manifest(path, target, version)
        manifests.append(
            {"name": path.name, "sha256": _sha256(path), "target": target}
        )
    sbom = root / AGGREGATE_SBOM
    sbom_digest = root / AGGREGATE_SBOM_DIGEST
    if (
        not sbom.is_file()
        or sbom.is_symlink()
        or not sbom_digest.is_file()
        or sbom_digest.is_symlink()
    ):
        raise QualificationProvenanceError("aggregate SBOM bytes are absent")
    sbom_sha256 = _sha256(sbom)
    expected_digest = f"{sbom_sha256}  {AGGREGATE_SBOM}\n"
    try:
        digest_text = sbom_digest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise QualificationProvenanceError(
            "aggregate SBOM digest is not strict UTF-8"
        ) from exc
    if digest_text != expected_digest:
        raise QualificationProvenanceError("aggregate SBOM digest drifted")
    return {
        "aggregate_sbom": {
            "digest_name": AGGREGATE_SBOM_DIGEST,
            "digest_sha256": _sha256(sbom_digest),
            "name": AGGREGATE_SBOM,
            "sha256": sbom_sha256,
        },
        "build": {"run_id": build_run_id, "workflow_sha": build_sha},
        "contract": "onyx.final-qualification-provenance.v1",
        "manifests": manifests,
        "qualification": {
            "run_id": qualification_run_id,
            "workflow_sha": qualification_sha,
        },
        "targets": targets,
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, default=Path("release"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--required-target", action="append", default=[])
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--qualification-run-id", required=True)
    parser.add_argument("--qualification-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate_provenance(
            release_dir=args.release_dir,
            version=args.version,
            required_targets=tuple(args.required_target),
            build_run_id=args.build_run_id,
            build_sha=args.build_sha,
            qualification_run_id=args.qualification_run_id,
            qualification_sha=args.qualification_sha,
        )
    except (OSError, QualificationProvenanceError) as exc:
        print(f"Final qualification provenance: BLOCKED: {exc}")
        return 1
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
