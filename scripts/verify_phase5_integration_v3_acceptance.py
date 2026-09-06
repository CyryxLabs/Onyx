"""Verify the external E6 acceptance for frozen Phase 5 Integration V3."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat

from scripts import verify_phase5_exit_retirement_v1 as exit_retirement
from scripts.verify_legacy_evidence_retirement_v1 import (
    LegacyEvidenceRetirementError,
    classify_historical_artifact,
)


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P5-INTEGRATION-V3-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P5-INTEGRATION-V3-E6-001.sha256"
ACCEPTANCE_MARKER = "P5_INTEGRATION_V3_ACCEPTANCE_OK"
TRANSITION_MARKER = "P5_INTEGRATION_V3_TRANSITION_OK"

MANIFEST = "docs/onyx/checkpoints/phase5-integration-v3/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-integration-v3/"
    "PHASE5_INTEGRATION_V3_CHECKPOINT.md"
)
ROOT_MANIFEST = (
    "docs/onyx/checkpoints/phase5-integration-v3/phase5-integration-v3.sha256"
)

MANIFEST_SHA256 = "9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167"
CHECKPOINT_SHA256 = "1615bc10c349a7c88ac3c23e89d55e74c05c81c07c3c252409172100a6e17b17"
ROOT_MANIFEST_SHA256 = "e5ed8bc4196fd98b25e675159031754d21e1fd31eac048a4796eb9212d40037c"

CANDIDATE_FILES = {
    "core/phase5_integration_v3.py": "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d",
    "tests/test_phase5_integration_v3.py": "c2b92406ce5f7b6d1a8f88afe167dbf62aed8059cccea47bc2c523dd4956ad02",
    "scripts/verify_phase5_integration_v3_transition.py": "c23724bc5d5ac2a184bdca5766e53ec4324ac4ea5fe8601998421477e1ded025",
    "tests/test_phase5_integration_v3_transition.py": "11c448200591b5038ca77afedb633f8712294eeff86fa2357924a16bba789b47",
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
}

PROJECTIONS = {
    "runtime-v10-e6": {
        "path": "docs/onyx/checkpoints/phase5-integration-v3/projections/runtime-v10.json",
        "sha256": "a897faf253ad18899c9abd724c74dddbcf14593a9f0dd9b7af89ac4ca270abba",
        "root": "b37df684730d1e18d8291a68af12af814f34aada22ebb1428fe29e5858dc7ed8",
    },
    "approval-inbox-v15-e6": {
        "path": "docs/onyx/checkpoints/phase5-integration-v3/projections/approval-inbox-v15.json",
        "sha256": "895ad5b300f9ce7c0d467a80cb321d00af92f268b40fa573ea387afc5cd6c9f4",
        "root": "8a125205928d9b55e662f5da1086a9f2605e98eab34533281379cae2875d007d",
    },
    "capability-nexus-v32-e6": {
        "path": "docs/onyx/checkpoints/phase5-integration-v3/projections/capability-nexus-v32.json",
        "sha256": "5f43294603f3f61c6a59128849ee6dd1ceedc7d63185364a9240df8b3c524474",
        "root": "17946d71960d5f08ae2b6979e3ab23ee255ccca2e6bf6e22153d07acffe65bb1",
    },
}

V1_FROZEN = {
    "core/phase5_integration_v1.py": "234ba11fb9ce5336297c27951c97e0c9c63a34bf4841b6980b58cff026687cdc",
    "tests/test_phase5_integration_v1.py": "4d5a3432ee90009266cf57a33d098f57430aca1831f1ab07b354e0797e775fef",
    "docs/onyx/checkpoints/phase5-integration-v1/manifest.json": "f08832e05077223ddce4353fff1c3e99ced3efad56c7329963f836ca2cb3adb8",
    "docs/onyx/checkpoints/phase5-integration-v1/PHASE5_INTEGRATION_V1_CHECKPOINT.md": "5aa2ee76dadddbd9976d53d327b42ac2f06be9d7399ecc8ea485d4e939fe97a2",
    "docs/onyx/checkpoints/phase5-integration-v1/phase5-integration-v1.sha256": "ec0b1eadf1405fea202414a3ced08f0f41c1d38ee96bf63cb6ee09ebe6bdfd2f",
}

V2_FROZEN = {
    "core/phase5_integration_v2.py": "ae035c4be1364d87f23c308ca42d33c938a29d6181680de62b5d9de5fe5f285d",
    "tests/test_phase5_integration_v2.py": "cb9ec992e08c5b47c51a7aac4a57b813fd6648526c22a488dfff4b51fe3a1217",
    "scripts/verify_phase5_integration_v2_transition.py": "9eacbe19c29d58ff1890b0a50b48bfa37c7ba681c28c640115264a5627dca1b0",
    "tests/test_phase5_integration_v2_transition.py": "2efe373bf0740d32384929ab3ade7aabbcce16388d7d0063b33ef9ce3b3a1f9e",
    "docs/onyx/checkpoints/phase5-integration-v2/manifest.json": "8f8a7aafb1f42d0de482adf69827c43ca8c04312fe90931683a4368148ef8498",
    "docs/onyx/checkpoints/phase5-integration-v2/PHASE5_INTEGRATION_V2_CHECKPOINT.md": "3c61b694f188494e9754867adb8e85fe13968dd5d1981d3576d1f8552eb68b29",
    "docs/onyx/checkpoints/phase5-integration-v2/phase5-integration-v2.sha256": "29324c092273f046e6b68989fbe5b516a139a1ece41fb09a5d061efcc0661fb5",
}

ACCEPTED_ANCHORS = {
    "core/session_grants_v11.py": "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
    "core/approval_inbox_v15.py": "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
    "core/capability_nexus_v32.py": "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
    "core/phase5_component_adapters_v3.py": "9c570d40a410e57a18f82a4ee2c30eddfe515a0cc7798d13607d020e573e3239",
    "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
    "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
    "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
}

FOCUSED_COMMAND = [
    "python", "-m", "pytest", "-q",
    "tests/test_phase5_integration_v3.py",
    "tests/test_phase5_integration_v3_transition.py",
    "--basetemp", ".pytest-p5-v3-acceptance-focused",
]
CUMULATIVE_COMMAND = [
    "python", "-m", "pytest", "-q",
    "tests/test_session_grants_v11.py",
    "tests/test_approval_inbox_v15_acceptance.py",
    "tests/test_capability_nexus_v32_acceptance.py",
    "tests/test_phase5_component_adapters_v3.py",
    "tests/test_phase5_runtime_v10.py",
    "tests/test_phase5_integration_v3.py",
    "tests/test_phase5_integration_v3_transition.py",
    "--basetemp", ".pytest-p5-v3-cumulative",
]

_REPARSE_ATTRIBUTE = 0x400


class IntegrationV3AcceptanceError(RuntimeError):
    """The V3 acceptance or one of its immutable anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise IntegrationV3AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise IntegrationV3AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise IntegrationV3AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise IntegrationV3AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise IntegrationV3AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise IntegrationV3AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise IntegrationV3AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise IntegrationV3AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise IntegrationV3AcceptanceError(
                f"acceptance path leaves the project: {relative}"
            ) from exc
        if resolved.name != part:
            raise IntegrationV3AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise IntegrationV3AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise IntegrationV3AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise IntegrationV3AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    try:
        value = _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrationV3AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    return value


def _canonical_text(project: Path, relative: str) -> str:
    value = _text(project, relative)
    if "\r" in value or not value.endswith("\n"):
        raise IntegrationV3AcceptanceError(
            f"external acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        try:
            classify_historical_artifact(project, relative, expected)
            return
        except LegacyEvidenceRetirementError:
            pass
        try:
            exit_retirement.classify(project, relative, expected)
            return
        except exit_retirement.Phase5ExitRetirementError as error:
            raise IntegrationV3AcceptanceError(
                f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
            ) from error


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1:
        raise IntegrationV3AcceptanceError(
            "acceptance manifest must contain exactly one record"
        )
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise IntegrationV3AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise IntegrationV3AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    record_digest, record_path = _manifest_line(
        _canonical_text(project, ACCEPTANCE_MANIFEST)
    )
    if record_path != ACCEPTANCE_RECORD:
        raise IntegrationV3AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    if _digest(project, ACCEPTANCE_RECORD) != record_digest:
        raise IntegrationV3AcceptanceError(
            "external acceptance record does not match its manifest"
        )
    record = _canonical_text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Integration V3 only, frozen default-off transition handoff",
        MANIFEST_SHA256,
        CANDIDATE_FILES["core/phase5_integration_v3.py"],
        CANDIDATE_FILES["tests/test_phase5_integration_v3.py"],
        CANDIDATE_FILES["scripts/verify_phase5_integration_v3_transition.py"],
        CANDIDATE_FILES["tests/test_phase5_integration_v3_transition.py"],
        "P0=0, P1=0, P2=0",
        "35 passed, 0 failed, 0 deselected",
        "230 passed, 0 failed, 0 deselected",
        TRANSITION_MARKER,
        "All eight integration flags remain default `False`",
        "not an activation instruction",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise IntegrationV3AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    for value in PROJECTIONS.values():
        if value["sha256"] not in record or value["root"] not in record:
            raise IntegrationV3AcceptanceError(
                "acceptance record is missing an execution-closure binding"
            )
    return record_digest


def _verify_root_manifest(project: Path) -> int:
    expected = {
        **CANDIDATE_FILES,
        MANIFEST: MANIFEST_SHA256,
        CHECKPOINT: CHECKPOINT_SHA256,
        **{value["path"]: value["sha256"] for value in PROJECTIONS.values()},
    }
    records: dict[str, str] = {}
    for line in _text(project, ROOT_MANIFEST).splitlines():
        digest, relative = _manifest_line(line + "\n")
        if relative in records:
            raise IntegrationV3AcceptanceError("root manifest path is duplicated")
        records[relative] = digest
    if records != expected:
        raise IntegrationV3AcceptanceError("root manifest closure is not exact")
    for relative, digest in records.items():
        _require_digest(project, relative, digest)
    return len(records)


def _verify_candidate(project: Path) -> dict[str, object]:
    _require_digest(project, MANIFEST, MANIFEST_SHA256)
    _require_digest(project, CHECKPOINT, CHECKPOINT_SHA256)
    _require_digest(project, ROOT_MANIFEST, ROOT_MANIFEST_SHA256)
    for relative, digest in CANDIDATE_FILES.items():
        _require_digest(project, relative, digest)
    try:
        manifest = json.loads(_text(project, MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise IntegrationV3AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.phase5.integration-transition-bundle.v3"
        or manifest.get("candidate") != "phase5-integration-v3"
        or manifest.get("default_off") is not True
        or manifest.get("live_activated") is not False
        or manifest.get("live_restart_performed") is not False
    ):
        raise IntegrationV3AcceptanceError(
            "candidate manifest lost its default-off/no-activation contract"
        )
    actual_files = {
        entry.get("path"): entry.get("sha256")
        for entry in manifest.get("files", [])
        if type(entry) is dict
    }
    if actual_files != CANDIDATE_FILES or len(manifest.get("files", [])) != len(
        CANDIDATE_FILES
    ):
        raise IntegrationV3AcceptanceError("candidate file closure is not exact")
    closures = manifest.get("historical_execution_closures")
    if type(closures) is not list or len(closures) != len(PROJECTIONS):
        raise IntegrationV3AcceptanceError("historical closure set is incomplete")
    actual_closures = {
        entry.get("closure"): {
            "path": entry.get("manifest_path"),
            "sha256": entry.get("manifest_sha256"),
            "root": entry.get("closure_root_sha256"),
        }
        for entry in closures
        if type(entry) is dict
    }
    if actual_closures != PROJECTIONS:
        raise IntegrationV3AcceptanceError("historical closure roots drifted")
    for value in PROJECTIONS.values():
        _require_digest(project, value["path"], value["sha256"])
        projection = json.loads(_text(project, value["path"]))
        if projection.get("closure_root_sha256") != value["root"]:
            raise IntegrationV3AcceptanceError("projection closure root drifted")
    rejected = manifest.get("rejected_predecessors")
    if type(rejected) is not list or [entry.get("candidate") for entry in rejected] != [
        "phase5-integration-v1", "phase5-integration-v2"
    ] or not all(
        type(entry) is dict
        and entry.get("preserved_exact") is True
        and entry.get("reachable_from_v3") is False
        for entry in rejected
    ):
        raise IntegrationV3AcceptanceError("V1/V2 history contract drifted")
    verification = manifest.get("verification")
    if (
        type(verification) is not dict
        or verification.get("focused")
        != {"passed": 35, "failed": 0, "deselected": 0}
        or verification.get("cumulative")
        != {"passed": 230, "failed": 0, "deselected": 0}
        or verification.get("ruff") != "pass"
        or verification.get("py_compile") != "pass"
    ):
        raise IntegrationV3AcceptanceError("candidate gate results drifted")
    if manifest.get("reproducible_cumulative_command") != CUMULATIVE_COMMAND:
        raise IntegrationV3AcceptanceError("cumulative command drifted")
    authority = manifest.get("authority_boundary")
    if (
        type(authority) is not dict
        or authority.get("executable_extension") != "local.catalog/catalog_read"
        or authority.get("provider_free") is not True
        or authority.get("effect") != "none"
        or authority.get("egress") != "none"
        or authority.get("cost_micro") != 0
        or authority.get("remote_approve") is not False
        or authority.get("remote_grant") is not False
        or authority.get("remote_dispatch") is not False
    ):
        raise IntegrationV3AcceptanceError("authority boundary drifted")
    source = _text(project, "core/phase5_integration_v3.py")
    default_fields = (
        "integration: bool = False",
        "runtime: bool = False",
        "grant_shadow: bool = False",
        "approval_inbox: bool = False",
        "low_risk: bool = False",
        "nexus_projection: bool = False",
        "local_catalog_read: bool = False",
        "dashboard_projection: bool = False",
    )
    if any(field not in source for field in default_fields):
        raise IntegrationV3AcceptanceError("an integration flag is not default False")
    if "setdefault(\"ONYX_PHASE5" in source or "setdefault(\"ONYX_PHASE5" in _text(
        project, "main.py"
    ):
        raise IntegrationV3AcceptanceError("a Phase 5 flag is default-enabled")
    return {
        "candidate_files": len(CANDIDATE_FILES),
        "root_records": _verify_root_manifest(project),
        "execution_closures": len(PROJECTIONS),
        "flags_default_false": len(default_fields),
    }


def _verify_history_and_anchors(project: Path) -> dict[str, int]:
    for relative, digest in V1_FROZEN.items():
        _require_digest(project, relative, digest)
    for relative, digest in V2_FROZEN.items():
        _require_digest(project, relative, digest)
    for relative, digest in ACCEPTED_ANCHORS.items():
        _require_digest(project, relative, digest)
    return {
        "v1_files": len(V1_FROZEN),
        "v2_files": len(V2_FROZEN),
        "accepted_anchors": len(ACCEPTED_ANCHORS),
    }


def _run_frozen_transition(project: Path) -> dict[str, object]:
    relative = "scripts/verify_phase5_integration_v3_transition.py"
    _require_digest(project, relative, CANDIDATE_FILES[relative])
    path = _regular_path(project, relative)
    spec = importlib.util.spec_from_file_location(
        "_onyx_phase5_integration_v3_frozen_transition", path
    )
    if spec is None or spec.loader is None:
        raise IntegrationV3AcceptanceError("cannot load frozen transition verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "MARKER", None) != TRANSITION_MARKER:
        raise IntegrationV3AcceptanceError("frozen transition marker drifted")
    result = module.verify(project)
    if (
        type(result) is not dict
        or result.get("candidate") != "phase5-integration-v3"
        or result.get("scope")
        != "independent-default-off-v3-after-v10-v15-v32-acceptance"
        or result.get("root_records") != 10
        or result.get("boundary", {}).get("default_off") is not True
    ):
        raise IntegrationV3AcceptanceError("frozen transition verification failed")
    return result


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    candidate = _verify_candidate(project)
    history = _verify_history_and_anchors(project)
    transition = _run_frozen_transition(project)
    historical = transition["historical_execution_closures"]
    closure_roots = {
        name: value["closure_root_sha256"] for name, value in historical.items()
    }
    expected_roots = {name: value["root"] for name, value in PROJECTIONS.items()}
    if closure_roots != expected_roots:
        raise IntegrationV3AcceptanceError("executed closure roots drifted")
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "manifest_sha256": MANIFEST_SHA256,
        "candidate": candidate,
        "history": history,
        "closure_roots": closure_roots,
        "transition_marker": TRANSITION_MARKER,
        "focused_passed": 35,
        "cumulative_passed": 230,
        "severity": {"P0": 0, "P1": 0, "P2": 0},
        "scope": "integration-v3-frozen-default-off-no-activation",
    }


def main() -> int:
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(verify(), sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
