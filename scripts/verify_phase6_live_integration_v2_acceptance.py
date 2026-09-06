"""Verify external E6 acceptance for frozen Phase 6 Live Integration V2."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P6-LIVE-INTEGRATION-V2-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-LIVE-INTEGRATION-V2-E6-001.sha256"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a"
)
CANDIDATE_ROOT_SHA256 = (
    "0b58365a0c43ea9b7133de1c0a51e77aa6bd855852849dab2bd9c433f733a334"
)
V1_MANIFEST = "docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json"
V1_MANIFEST_SHA256 = "56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7"
V1_ROOT_SHA256 = "4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd"
V1_REJECTION = "docs/onyx/rejections/PHASE6_LIVE_INTEGRATION_V1_REJECTION.md"
V1_REJECTION_SHA256 = "eb917cec9cb7e3c96aef33e87b40c0a6cc90146824212972f2f00eb9ff2a66b7"
ACCEPTANCE_MARKER = "P6_LIVE_INTEGRATION_V2_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400

CANDIDATE_ARTIFACTS = {
    "core/phase6_live_integration_v2.py": (
        36742,
        "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5",
    ),
    "tests/test_phase6_live_integration_v2.py": (
        16736,
        "0a69c7296c53361349472462e40d8fb9ca77eff1f0e2b462dd69293f0039dbe7",
    ),
    "docs/onyx/adrs/ADR-0017-phase6-live-integration-v2.md": (
        4686,
        "d94e414eadf092ddad0a28b9b0d6e96b772f7a549fc1b0f363f842401ee2b7c3",
    ),
    V1_REJECTION: (
        1817,
        V1_REJECTION_SHA256,
    ),
    (
        "docs/onyx/checkpoints/phase6-live-integration-v2/"
        "PHASE6_LIVE_INTEGRATION_V2_CHECKPOINT.md"
    ): (
        5618,
        "2a0f998d4c97688f0f0144186326252b4129fe21a0b295d59eba3f058611831e",
    ),
    "scripts/verify_phase6_live_integration_v2.py": (
        11876,
        "3765979778f58b9f8a238256bf11cc3f4e1fbee13afd4bc0ccd3a223cf3d289a",
    ),
}
BOUND_VERIFIERS = {
    "scripts/verify_phase6_live_integration_v2.py": (
        "3765979778f58b9f8a238256bf11cc3f4e1fbee13afd4bc0ccd3a223cf3d289a",
        "P6_LIVE_INTEGRATION_V2_OK",
    ),
    "scripts/verify_phase6_live_integration_v1.py": (
        "53520a1ae92c9bbed339dc3d56e9319c78082ebe137b77ea9a39e1f4f5733917",
        "P6_LIVE_INTEGRATION_V1_OK",
    ),
    "scripts/verify_phase6_agentic_core_v6_acceptance.py": (
        "7e218ba09747a03e1e7edd4abc7b4af6df372b83c819ed65941baef82f528ed3",
        "P6_AGENTIC_CORE_V6_ACCEPTANCE_OK",
    ),
    "scripts/verify_phase5_integration_v3_acceptance.py": (
        "9bc529d2434a83c4cdacc6e1f89240bb82235c996c3c606df902f921c6489056",
        "P5_INTEGRATION_V3_ACCEPTANCE_OK",
    ),
}


class LiveIntegrationV2AcceptanceError(RuntimeError):
    """The external acceptance or a frozen anchor is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise LiveIntegrationV2AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LiveIntegrationV2AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise LiveIntegrationV2AcceptanceError(
            "acceptance root is unavailable"
        ) from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise LiveIntegrationV2AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise LiveIntegrationV2AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise LiveIntegrationV2AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise LiveIntegrationV2AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveIntegrationV2AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise LiveIntegrationV2AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _artifact_root(artifacts: dict[str, str]) -> str:
    records = []
    for relative, digest in artifacts.items():
        _canonical_relative(relative)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise LiveIntegrationV2AcceptanceError("artifact digest is malformed")
        records.append(f"{relative}\0{digest}")
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1 or len(lines[0]) < 67 or lines[0][64:66] != "  ":
        raise LiveIntegrationV2AcceptanceError(
            "acceptance manifest must be one canonical record"
        )
    digest, relative = lines[0][:64], lines[0][66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise LiveIntegrationV2AcceptanceError(
            "acceptance manifest digest is malformed"
        )
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    digest, relative = _manifest_line(_text(project, ACCEPTANCE_MANIFEST))
    if relative != ACCEPTANCE_RECORD:
        raise LiveIntegrationV2AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    actual = _digest(project, ACCEPTANCE_RECORD)
    if actual != digest:
        raise LiveIntegrationV2AcceptanceError(
            "acceptance record does not match one-line manifest"
        )
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Live Integration V2 only, isolated/default-off implementation handoff",
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_ROOT_SHA256,
        "6/6 artifacts",
        V1_MANIFEST_SHA256,
        V1_ROOT_SHA256,
        V1_REJECTION_SHA256,
        "23/23 focused V2 tests",
        "241/241 cumulative",
        "P0=0, P1=0, P2=0, P3=0",
        "P6_LIVE_INTEGRATION_V2_OK",
        "P6_LIVE_INTEGRATION_V1_OK",
        "P6_AGENTIC_CORE_V6_ACCEPTANCE_OK",
        "P5_INTEGRATION_V3_ACCEPTANCE_OK",
        "strict default-off and unwired",
    )
    missing = [value for value in required if value not in record]
    if missing:
        raise LiveIntegrationV2AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    return actual


def _verify_candidate(project: Path) -> int:
    _require_digest(project, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256)
    try:
        manifest = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise LiveIntegrationV2AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "OnyxPhase6LiveIntegrationCheckpoint.v2"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or manifest.get("activation")
        != {
            "feature_flag": "ONYX_PHASE6_LIVE_INTEGRATION_V2",
            "enabled_value": "true",
            "default": "off",
            "live_wiring": False,
        }
    ):
        raise LiveIntegrationV2AcceptanceError(
            "candidate lost exact default-off manifest contract"
        )
    entries = manifest.get("artifacts")
    if type(entries) is not list or len(entries) != 6:
        raise LiveIntegrationV2AcceptanceError("candidate closure is not 6/6")
    observed: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise LiveIntegrationV2AcceptanceError(
                "candidate artifact entry is malformed"
            )
        relative = entry["path"]
        if relative in observed or relative not in CANDIDATE_ARTIFACTS:
            raise LiveIntegrationV2AcceptanceError(
                "candidate artifact closure diverged"
            )
        expected_bytes, expected_digest = CANDIDATE_ARTIFACTS[relative]
        path = _regular_path(project, relative)
        if (
            entry["bytes"] != expected_bytes
            or path.stat().st_size != expected_bytes
            or entry["sha256"] != expected_digest
        ):
            raise LiveIntegrationV2AcceptanceError(
                f"candidate artifact record drifted: {relative}"
            )
        _require_digest(project, relative, expected_digest)
        observed[relative] = expected_digest
    if set(observed) != set(CANDIDATE_ARTIFACTS):
        raise LiveIntegrationV2AcceptanceError("candidate closure is incomplete")
    if _artifact_root(observed) != CANDIDATE_ROOT_SHA256:
        raise LiveIntegrationV2AcceptanceError("candidate root does not recompute")
    return len(observed)


def _function_keywords(
    tree: ast.Module, function_name: str, *, class_name: str | None = None
) -> tuple[list[str], list[str]]:
    body: list[ast.stmt] = tree.body
    if class_name is not None:
        classes = [
            node
            for node in body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(classes) != 1:
            raise LiveIntegrationV2AcceptanceError(
                f"class is missing or duplicated: {class_name}"
            )
        body = classes[0].body
    functions = [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(functions) != 1:
        raise LiveIntegrationV2AcceptanceError(
            f"function is missing or duplicated: {function_name}"
        )
    function = functions[0]
    if function.args.vararg is not None or function.args.kwarg is not None:
        raise LiveIntegrationV2AcceptanceError(
            f"variadic operational seam: {function_name}"
        )
    return (
        [argument.arg for argument in function.args.args],
        [argument.arg for argument in function.args.kwonlyargs],
    )


def _verify_p1_reproduction_and_closure(project: Path) -> dict[str, bool]:
    v1_source = _text(project, "core/phase6_live_integration_v1.py")
    v2_source = _text(project, "core/phase6_live_integration_v2.py")
    v1_tree = ast.parse(v1_source, filename="core/phase6_live_integration_v1.py")
    v2_tree = ast.parse(v2_source, filename="core/phase6_live_integration_v2.py")

    _, v1_adapter = _function_keywords(
        v1_tree, "__init__", class_name="CurrentTextProviderAdapterV1"
    )
    _, v1_factory = _function_keywords(v1_tree, "create_phase6_live_integration_v1")
    if (
        any(
            value in v1_source for value in ("account_id", "profile_id", "principal_id")
        )
        or not {"invoke", "executor"}.issubset(v1_adapter)
        or not {"catalog", "text"}.issubset(v1_factory)
    ):
        raise LiveIntegrationV2AcceptanceError("V1 P1 reproduction diverged")

    identities = [
        node
        for node in v2_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HostIdentityBindingV2"
    ]
    if len(identities) != 1:
        raise LiveIntegrationV2AcceptanceError("V2 identity class is invalid")
    fields = [
        node.target.id
        for node in identities[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    if fields != ["workspace_id", "account_id", "profile_id", "principal_id"]:
        raise LiveIntegrationV2AcceptanceError("V2 identity fields diverged")

    v2_init_positional, v2_adapter = _function_keywords(
        v2_tree, "__init__", class_name="CurrentTextProviderAdapterV2"
    )
    v2_factory_positional, v2_factory = _function_keywords(
        v2_tree, "create_phase6_live_integration_v2"
    )
    if (
        v2_init_positional != ["self"]
        or v2_adapter != ["identity"]
        or v2_factory_positional
        or v2_factory
        != [
            "gate",
            "identity",
            "agentic_core",
            "agentic_state",
            "phase5",
            "receipt_path",
        ]
    ):
        raise LiveIntegrationV2AcceptanceError("V2 operational factory is not sealed")
    required = (
        "_OPERATIONAL_INVOKER = live_v1._current_llm_text_call",
        "executor=TerminableProcessExecutorV4()",
        "identity.attest(agentic_core, phase5)",
        '"schema": "OnyxPhase6TextRequest.v2"',
        '"schema": "OnyxPhase6TextReceipt.v2"',
        '"schema": "OnyxPhase6CatalogRequest.v2"',
        '"schema": "OnyxPhase6CatalogReceipt.v2"',
        '"identity_digest": self.identity.digest',
    )
    missing = [value for value in required if value not in v2_source]
    if missing:
        raise LiveIntegrationV2AcceptanceError(
            f"V2 P1 closure is missing: {missing[0]}"
        )
    if v2_source.index("identity.attest(agentic_core, phase5)") > v2_source.index(
        "text = CurrentTextProviderAdapterV2.operational(identity)"
    ):
        raise LiveIntegrationV2AcceptanceError(
            "V2 identity attestation occurs after process construction"
        )
    return {
        "v1_incomplete_identity_reproduced": True,
        "v1_arbitrary_dependencies_reproduced": True,
        "v2_complete_identity_closed": True,
        "v2_operational_factory_sealed": True,
    }


def _verify_v1_rejection(project: Path) -> None:
    _require_digest(project, V1_MANIFEST, V1_MANIFEST_SHA256)
    _require_digest(project, V1_REJECTION, V1_REJECTION_SHA256)
    try:
        manifest = json.loads(_text(project, V1_MANIFEST))
    except json.JSONDecodeError as exc:
        raise LiveIntegrationV2AcceptanceError("V1 manifest is invalid") from exc
    if (
        manifest.get("artifact_root_sha256") != V1_ROOT_SHA256
        or manifest.get("activation", {}).get("default") != "off"
        or manifest.get("activation", {}).get("live_wiring") is not False
    ):
        raise LiveIntegrationV2AcceptanceError(
            "V1 rejection baseline lost default-off closure"
        )
    rejection = _text(project, V1_REJECTION)
    if (
        "REJECTED — preserved, default-off, never live" not in rejection
        or "Incomplete host identity binding" not in rejection
        or "Operational construction admitted arbitrary dependencies" not in rejection
    ):
        raise LiveIntegrationV2AcceptanceError("V1 rejection evidence is incomplete")


def _verify_bound_verifiers(project: Path) -> dict[str, str]:
    markers: dict[str, str] = {}
    for relative, (expected_digest, marker) in BOUND_VERIFIERS.items():
        _require_digest(project, relative, expected_digest)
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(project / relative)],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LiveIntegrationV2AcceptanceError(
                f"bound verifier could not complete: {relative}"
            ) from exc
        if result.returncode != 0 or marker not in result.stdout:
            raise LiveIntegrationV2AcceptanceError(f"bound verifier failed: {relative}")
        markers[relative] = marker
    return markers


def _verify_default_off_unwired(project: Path) -> int:
    live_paths = ["main.py", "ui.py"]
    allowed_suffixes = {".py", ".pyw", ".cmd", ".ps1", ".iss", ".js", ".html", ".qml"}
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = project / root_name
        if root.is_dir():
            live_paths.extend(
                path.relative_to(project).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix.lower() in allowed_suffixes
            )
    scripts = project / "scripts"
    if scripts.is_dir():
        live_paths.extend(
            path.relative_to(project).as_posix()
            for path in sorted(scripts.glob("launch_*"))
            if path.is_file() and path.suffix.lower() in allowed_suffixes
        )
    needles = ("phase6_live_integration_v2", "ONYX_PHASE6_LIVE_INTEGRATION_V2")
    for relative in live_paths:
        try:
            source = _bytes(project, relative).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(needle in source for needle in needles):
            raise LiveIntegrationV2AcceptanceError(
                f"V2 entered a live surface: {relative}"
            )
    return len(set(live_paths))


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_digest = _verify_record(project)
    artifact_count = _verify_candidate(project)
    _verify_v1_rejection(project)
    p1 = _verify_p1_reproduction_and_closure(project)
    markers = _verify_bound_verifiers(project)
    live_files = _verify_default_off_unwired(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_digest,
        "manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "candidate_artifacts": artifact_count,
        "v1_manifest_sha256": V1_MANIFEST_SHA256,
        "v1_artifact_root_sha256": V1_ROOT_SHA256,
        "v1_rejection_sha256": V1_REJECTION_SHA256,
        "p1": p1,
        "verifiers": markers,
        "focused_passed": 23,
        "cumulative_passed": 241,
        "live_files_checked": live_files,
        "severity": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "scope": "phase6-live-integration-v2-isolated-default-off-unwired-handoff",
    }


def main() -> int:
    payload = verify()
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
