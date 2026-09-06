"""Generate deterministic Phase V40/Retirement V7/Release V31 records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def write(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8", newline="\n",
    )


def phase_v40() -> tuple[Path, str, str]:
    predecessor = ROOT / "tests/fixtures/phase5_current_successor_transition_v39.json"
    record = json.loads(predecessor.read_text(encoding="utf-8"))
    record["schema"] = "onyx.phase5-current-successor-transition.v40"
    record["issued_at"] = "2026-08-05T08:15:00-04:00"
    record["predecessor"] = {
        "path": predecessor.relative_to(ROOT).as_posix(), "sha256": sha(predecessor)
    }
    for section in ("historical_bindings", "named_successors"):
        key = "current_sha256"
        for entry in record[section]:
            entry[key] = sha(ROOT / entry["path"])
    digest = hashlib.sha256()
    digest.update(b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V40\0")
    for entry in record["historical_bindings"]:
        for value in (
            "historical-binding", entry["path"], entry["historical_sha256"],
            entry["current_sha256"], entry["state"], entry["successor"],
        ):
            frame(digest, value)
    for entry in record["named_successors"]:
        for value in (
            "named-successor", entry["path"], entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            frame(digest, value)
    record["current_root_sha256"] = digest.hexdigest()
    target = ROOT / "tests/fixtures/phase5_current_successor_transition_v40.json"
    write(target, record)
    return target, sha(target), digest.hexdigest()


def retirement_v7(phase: Path, phase_sha: str) -> tuple[Path, str]:
    predecessor = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V6.json"
    record = json.loads(predecessor.read_text(encoding="utf-8"))
    record["schema"] = "onyx.current-successor-retirement.v7"
    record["issued_at"] = "2026-08-05T08:20:00-04:00"
    record["predecessor"] = {
        "path": predecessor.relative_to(ROOT).as_posix(), "sha256": sha(predecessor)
    }
    record["phase5_current_successor"] = {
        "path": phase.relative_to(ROOT).as_posix(), "sha256": phase_sha
    }
    for entry in record["current_successors"]:
        entry["current_sha256"] = sha(ROOT / entry["path"])
    target = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V7.json"
    write(target, record)
    return target, sha(target)


def release_v31() -> tuple[Path, str, str, int]:
    predecessor = ROOT / "tests/fixtures/release_workflow_transition_v30.json"
    paths = sorted({
        "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
        "core/onyx_packaged_runtime_hud_contract_v1.py",
        "core/onyx_hud_current_acceptance_v26.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V7.json",
        "packaging/onyx.spec",
        "scripts/bootstrap_onyx.pyw",
        "scripts/generate_frozen_runtime_successors_v1.py",
        "scripts/generate_hud_v26_manifests.py",
        "scripts/package_hygiene.py",
        "scripts/verify_release_runtime_closure_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v40.json",
        "tests/test_current_successor_retirement_v7.py",
        "tests/test_frozen_bootstrap_diagnostics_v1.py",
        "tests/test_native_release_gate_v1.py",
        "tests/test_package_hygiene_v1.py",
        "tests/test_packaged_runtime_hud_contract_v1.py",
        "tests/test_phase5_current_successor_transition_v40.py",
        "tests/test_release_workflow_transition_v30.py",
    })
    entries = [{"path": relative, "sha256": sha(ROOT / relative)} for relative in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v31",
        "issued_at": "2026-08-05T08:25:00-04:00",
        "predecessor": {
            "path": predecessor.relative_to(ROOT).as_posix(), "sha256": sha(predecessor),
        },
        "policy": {
            "predecessor_is_immutable": True,
            "historical_hashes_are_rebound": False,
            "current_release_paths_are_sha256_bound": True,
            "unsigned_windows_may_be_formal": False,
            "diagnostic_candidates_may_be_published": False,
        },
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V31\0")
    for value in (record["predecessor"]["path"], record["predecessor"]["sha256"]):
        frame(digest, value)
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
    record["current_root_sha256"] = digest.hexdigest()
    target = ROOT / "tests/fixtures/release_workflow_transition_v31.json"
    write(target, record)
    return target, sha(target), digest.hexdigest(), len(entries)


def main() -> None:
    phase, phase_sha, phase_root = phase_v40()
    retirement, retirement_sha = retirement_v7(phase, phase_sha)
    release, release_sha, release_root, release_paths = release_v31()
    print(json.dumps({
        "phase": str(phase), "phase_sha256": phase_sha,
        "phase_root_sha256": phase_root, "retirement": str(retirement),
        "retirement_sha256": retirement_sha,
        "release": str(release), "release_sha256": release_sha,
        "release_root_sha256": release_root, "release_paths": release_paths,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
