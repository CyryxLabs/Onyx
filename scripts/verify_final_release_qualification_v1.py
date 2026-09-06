"""Fail closed unless final native qualification evidence matches release bytes."""

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
REQUIRED_LIFECYCLE_GATES = (
    "clean_install_current",
    "uninstall_app_only",
    "reinstall_current",
    "upgrade_prior_to_current",
    "rollback_current_to_prior",
    "final_uninstall_app_only",
)
LIFECYCLE_CONTRACT = {
    "Windows": "onyx.windows-lifecycle-evidence.v1",
    "Darwin": "onyx.macos-lifecycle-evidence.v1",
    "Linux": "onyx.linux-lifecycle-evidence.v1",
}
PRIMARY_SUFFIX = {
    "Windows": "-Setup.exe",
    "Darwin": ".dmg",
    "Linux": ".deb",
}


class FinalReleaseQualificationError(RuntimeError):
    """Final lifecycle, soak, or independent-review evidence is not eligible."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FinalReleaseQualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append(f"missing {label}: {path.name}")
        return None
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, FinalReleaseQualificationError):
        errors.append(f"invalid {label}: strict UTF-8 JSON is required")
        return None
    if type(payload) is not dict:
        errors.append(f"invalid {label}: root must be an object")
        return None
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> bool:
    return type(value) is str and SHA256.fullmatch(value) is not None


def _architecture(value: object) -> str:
    raw = str(value or "").casefold()
    if raw in {"amd64", "x86_64", "x64"}:
        return "x64"
    if raw in {"arm64", "aarch64"}:
        return "arm64"
    return raw


def _artifact(
    release_dir: Path,
    manifest: dict[str, Any],
    suffix: str,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    records = manifest.get("artifacts")
    matches = [
        item
        for item in records if type(item) is dict
        and type(item.get("name")) is str
        and item["name"].endswith(suffix)
    ] if type(records) is list else []
    if len(matches) != 1 or not _canonical_sha(matches[0].get("sha256")):
        errors.append(f"invalid {label}: exact primary artifact is absent")
        return None
    record = matches[0]
    name = record["name"]
    artifact = release_dir / name
    if (
        Path(name).name != name
        or not artifact.is_file()
        or artifact.is_symlink()
        or _sha256(artifact) != record["sha256"]
        or record.get("size") != artifact.stat().st_size
    ):
        errors.append(f"invalid {label}: exact primary artifact bytes drifted")
        return None
    return record


def _validate_lifecycle(
    *,
    release_dir: Path,
    target: str,
    system: str,
    architecture: str,
    version: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    label = f"{target} lifecycle evidence"
    payload = _load(release_dir / f"lifecycle-evidence-{target}.json", label, errors)
    if payload is None:
        return
    primary = _artifact(
        release_dir,
        manifest,
        PRIMARY_SUFFIX[system],
        label,
        errors,
    )
    current = payload.get("current")
    prior = payload.get("prior")
    host = payload.get("host")
    events = payload.get("events")
    if payload.get("contract") != LIFECYCLE_CONTRACT[system]:
        errors.append(f"invalid {label}: contract drifted")
    if (
        type(host) is not dict
        or host.get("system") != system
        or _architecture(host.get("architecture")) != _architecture(architecture)
    ):
        errors.append(f"invalid {label}: native host identity drifted")
    if (
        type(current) is not dict
        or current.get("version") != version
        or primary is None
        or current.get("sha256") != primary.get("sha256")
    ):
        errors.append(f"invalid {label}: current artifact binding drifted")
    if (
        type(prior) is not dict
        or not isinstance(prior.get("version"), str)
        or not prior.get("version")
        or prior.get("version") == version
        or not _canonical_sha(prior.get("sha256"))
    ):
        errors.append(f"invalid {label}: prior artifact binding is incomplete")
    observed_gates = tuple(
        item.get("gate") for item in events if type(item) is dict
    ) if type(events) is list else ()
    if observed_gates != REQUIRED_LIFECYCLE_GATES:
        errors.append(f"invalid {label}: lifecycle gate sequence drifted")
    required_final = {
        "Windows": ("final_app_removed", "final_registry_removed"),
        "Darwin": ("final_app_removed", "final_launch_agent_removed"),
        "Linux": ("final_app_removed", "final_package_removed"),
    }[system]
    if any(payload.get(field) is not True for field in required_final) or (
        payload.get("final_owner_data_preserved") is not True
    ):
        errors.append(f"invalid {label}: final lifecycle state did not pass")
    if system == "Windows" and (
        type(current) is not dict
        or type(current.get("signature")) is not dict
        or current["signature"].get("status") != "Valid"
        or re.fullmatch(
            r"[0-9A-F]{40}",
            str(current["signature"].get("thumbprint", "")),
        ) is None
    ):
        errors.append(f"invalid {label}: trusted current signature is absent")


def _validate_windows_long_session(
    *,
    release_dir: Path,
    target: str,
    version: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    label = f"{target} long-session evidence"
    payload = _load(release_dir / f"long-session-evidence-{target}.json", label, errors)
    if payload is None:
        return
    setup = _artifact(release_dir, manifest, "-Setup.exe", label, errors)
    portable = _artifact(release_dir, manifest, "-Portable.zip", label, errors)
    artifacts = payload.get("artifacts")
    thresholds = payload.get("thresholds")
    if (
        payload.get("contract") != "OnyxWindowsLongSession.v1"
        or payload.get("status") != "passed"
        or payload.get("full_duration") is not True
        or payload.get("alive_at_update") is not True
        or payload.get("all_responsive") is not True
        or payload.get("failure_reason") is not None
        or payload.get("application_error_count") != 0
        or payload.get("process_left_running") is not True
        or version not in str(payload.get("candidate", ""))
    ):
        errors.append(f"invalid {label}: terminal pass contract is absent")
    required = payload.get("duration_required_seconds")
    observed = payload.get("duration_observed_seconds")
    interval = payload.get("sample_interval_seconds")
    samples = payload.get("sample_count")
    if (
        not isinstance(required, (int, float))
        or isinstance(required, bool)
        or required < 28_800
        or not isinstance(observed, (int, float))
        or isinstance(observed, bool)
        or observed < required
        or not isinstance(interval, (int, float))
        or isinstance(interval, bool)
        or interval <= 0
        or not isinstance(samples, int)
        or isinstance(samples, bool)
        or samples < max(1, int(required / interval) - 1)
    ):
        errors.append(f"invalid {label}: eight-hour sampling coverage is incomplete")
    sbom = release_dir / "SBOM-Windows-x64.spdx.json"
    if (
        type(artifacts) is not dict
        or setup is None
        or portable is None
        or artifacts.get("setup_sha256") != setup.get("sha256")
        or artifacts.get("portable_sha256") != portable.get("sha256")
        or artifacts.get("bundle_root_sha256")
        != (manifest.get("bundle_inventory") or {}).get("bundle_root_sha256")
        or not _canonical_sha(artifacts.get("source_transition_sha256"))
        or not sbom.is_file()
        or sbom.is_symlink()
        or artifacts.get("sbom_sha256") != _sha256(sbom)
        or not _canonical_sha(payload.get("executable_sha256"))
    ):
        errors.append(f"invalid {label}: final artifact binding drifted")
    metric_pairs = (
        ("average_whole_host_cpu_pct", "average_whole_host_cpu_pct"),
        ("maximum_working_set_bytes", "maximum_working_set_bytes"),
        ("maximum_private_memory_bytes", "maximum_private_memory_bytes"),
        ("working_set_growth_bytes", "maximum_working_set_growth_bytes"),
        ("application_error_count", "maximum_application_errors"),
    )
    if type(thresholds) is not dict:
        errors.append(f"invalid {label}: thresholds are absent")
    else:
        for observed_name, limit_name in metric_pairs:
            value = payload.get(observed_name)
            limit = thresholds.get(limit_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isinstance(limit, (int, float))
                or isinstance(limit, bool)
                or value > limit
            ):
                errors.append(f"invalid {label}: {observed_name} exceeds threshold")


def _validate_provenance(
    *,
    release_dir: Path,
    version: str,
    required_targets: tuple[str, ...],
    build_run_id: str,
    build_sha: str,
    qualification_run_id: str,
    qualification_sha: str,
    errors: list[str],
) -> None:
    label = "final qualification provenance"
    payload = _load(
        release_dir / "final-qualification-provenance.json",
        label,
        errors,
    )
    if payload is None:
        return
    expected_targets = sorted(set(required_targets))
    if (
        payload.get("contract") != "onyx.final-qualification-provenance.v1"
        or payload.get("version") != version
        or payload.get("build")
        != {"run_id": build_run_id, "workflow_sha": build_sha}
        or payload.get("qualification")
        != {
            "run_id": qualification_run_id,
            "workflow_sha": qualification_sha,
        }
        or payload.get("targets") != expected_targets
    ):
        errors.append(f"invalid {label}: workflow identity drifted")
    aggregate = payload.get("aggregate_sbom")
    sbom = release_dir / "SBOM.spdx.json"
    digest = release_dir / "SBOM.spdx.json.sha256"
    if (
        type(aggregate) is not dict
        or set(aggregate) != {"digest_name", "digest_sha256", "name", "sha256"}
        or aggregate.get("name") != sbom.name
        or aggregate.get("digest_name") != digest.name
        or not _canonical_sha(aggregate.get("sha256"))
        or not _canonical_sha(aggregate.get("digest_sha256"))
        or not sbom.is_file()
        or sbom.is_symlink()
        or not digest.is_file()
        or digest.is_symlink()
        or _sha256(sbom) != aggregate.get("sha256")
        or _sha256(digest) != aggregate.get("digest_sha256")
    ):
        errors.append(f"invalid {label}: aggregate SBOM binding drifted")
    else:
        try:
            digest_text = digest.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"invalid {label}: aggregate SBOM digest is not UTF-8")
        else:
            expected = f"{aggregate['sha256']}  {sbom.name}\n"
            if digest_text != expected:
                errors.append(f"invalid {label}: aggregate SBOM digest drifted")
    manifests = payload.get("manifests")
    if type(manifests) is not list or len(manifests) != len(expected_targets):
        errors.append(f"invalid {label}: manifest bindings are incomplete")
        return
    observed: dict[str, dict[str, Any]] = {}
    for item in manifests:
        if (
            type(item) is not dict
            or set(item) != {"name", "sha256", "target"}
            or item.get("target") in observed
        ):
            errors.append(f"invalid {label}: manifest binding is malformed")
            continue
        observed[str(item["target"])] = item
    if sorted(observed) != expected_targets:
        errors.append(f"invalid {label}: manifest target coverage drifted")
        return
    for target, item in observed.items():
        expected_name = f"release-manifest-{target}.json"
        manifest = release_dir / expected_name
        if (
            item.get("name") != expected_name
            or not _canonical_sha(item.get("sha256"))
            or not manifest.is_file()
            or manifest.is_symlink()
            or _sha256(manifest) != item.get("sha256")
        ):
            errors.append(
                f"invalid {label}: manifest bytes drifted for {target}"
            )


def verify_final_release_qualification(
    *,
    release_dir: Path,
    version: str,
    required_targets: tuple[str, ...],
    build_run_id: str,
    build_sha: str,
    qualification_run_id: str,
    qualification_sha: str,
    independent_review_approval: str,
    independent_review_reference: str,
) -> dict[str, object]:
    """Verify lifecycle, soak and independent-review gates for final bytes."""

    root = Path(release_dir).resolve(strict=True)
    errors: list[str] = []
    if not version or version.strip() != version:
        errors.append("release version is absent or malformed")
    if not required_targets:
        errors.append("required release target matrix is absent")
    if (
        not build_run_id.isdecimal()
        or WORKFLOW_SHA.fullmatch(build_sha) is None
        or not qualification_run_id.isdecimal()
        or WORKFLOW_SHA.fullmatch(qualification_sha) is None
    ):
        errors.append("build or qualification workflow identity is malformed")
    expected_reference = f"/actions/runs/{qualification_run_id}"
    if independent_review_approval.strip().casefold() != "true":
        errors.append("independent final evidence review is not approved")
    if (
        not independent_review_reference.startswith("https://github.com/")
        or expected_reference not in independent_review_reference
    ):
        errors.append("independent review durable workflow reference is absent")

    _validate_provenance(
        release_dir=root,
        version=version,
        required_targets=required_targets,
        build_run_id=build_run_id,
        build_sha=build_sha,
        qualification_run_id=qualification_run_id,
        qualification_sha=qualification_sha,
        errors=errors,
    )

    seen: set[str] = set()
    for target in required_targets:
        match = TARGET.fullmatch(target)
        if match is None or target in seen:
            errors.append(f"invalid or duplicate required target: {target}")
            continue
        seen.add(target)
        system, architecture = match.groups()
        manifest_label = f"{target} release manifest"
        manifest = _load(
            root / f"release-manifest-{target}.json",
            manifest_label,
            errors,
        )
        if manifest is None:
            continue
        if (
            manifest.get("system") != system
            or _architecture(manifest.get("architecture")) != _architecture(architecture)
            or manifest.get("version") != version
            or manifest.get("release_class") != "formal"
            or manifest.get("diagnostic_exceptions") != []
        ):
            errors.append(f"invalid {manifest_label}: formal identity drifted")
        _validate_lifecycle(
            release_dir=root,
            target=target,
            system=system,
            architecture=architecture,
            version=version,
            manifest=manifest,
            errors=errors,
        )
        if system == "Windows":
            _validate_windows_long_session(
                release_dir=root,
                target=target,
                version=version,
                manifest=manifest,
                errors=errors,
            )
    if not any(target.startswith("Windows-") for target in seen):
        errors.append("Windows long-session target is absent")
    if errors:
        raise FinalReleaseQualificationError("\n".join(sorted(set(errors))))
    return {
        "contract": "onyx.final-release-qualification.v1",
        "version": version,
        "targets": sorted(seen),
        "build_run_id": build_run_id,
        "build_sha": build_sha,
        "qualification_run_id": qualification_run_id,
        "qualification_sha": qualification_sha,
        "lifecycle_passed": True,
        "windows_long_session_passed": True,
        "independent_review_approved": True,
        "independent_review_reference": independent_review_reference,
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
    parser.add_argument("--independent-review-approval", default="")
    parser.add_argument("--independent-review-reference", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_final_release_qualification(
            release_dir=args.release_dir,
            version=args.version,
            required_targets=tuple(args.required_target),
            build_run_id=args.build_run_id,
            build_sha=args.build_sha,
            qualification_run_id=args.qualification_run_id,
            qualification_sha=args.qualification_sha,
            independent_review_approval=args.independent_review_approval,
            independent_review_reference=args.independent_review_reference,
        )
    except (OSError, FinalReleaseQualificationError) as exc:
        print("Final release qualification: BLOCKED")
        for line in str(exc).splitlines():
            print(f"- {line}")
        return 1
    if args.output is not None:
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
