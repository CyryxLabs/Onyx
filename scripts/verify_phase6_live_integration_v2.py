"""Verify the frozen default-off Phase 6 Live Integration V2 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json"
MARKER = "P6_LIVE_INTEGRATION_V2_OK"

EXPECTED_ARTIFACTS = {
    "core/phase6_live_integration_v2.py",
    "tests/test_phase6_live_integration_v2.py",
    "docs/onyx/adrs/ADR-0017-phase6-live-integration-v2.md",
    "docs/onyx/rejections/PHASE6_LIVE_INTEGRATION_V1_REJECTION.md",
    (
        "docs/onyx/checkpoints/phase6-live-integration-v2/"
        "PHASE6_LIVE_INTEGRATION_V2_CHECKPOINT.md"
    ),
    "scripts/verify_phase6_live_integration_v2.py",
}
FROZEN_V1 = {
    "core/phase6_live_integration_v1.py": (
        "d838b3789bd286188f4b8f21426135fe2034459f1382cc68e3568707952a3715"
    ),
    "tests/test_phase6_live_integration_v1.py": (
        "830c3717737aed95bdf9fea10138c87cca3624201120778d496704e6f7990046"
    ),
    "docs/onyx/adrs/ADR-0016-phase6-live-integration-v1.md": (
        "b4257950e3f07bb0930cd832e571c633873ee1c8ae0513071445b8ca4324c6b6"
    ),
    (
        "docs/onyx/checkpoints/phase6-live-integration-v1/"
        "PHASE6_LIVE_INTEGRATION_V1_CHECKPOINT.md"
    ): "f7d7159dd78e213c4eb030a5f73217e22fd3749e46a067df81a707ec42cf808b",
    "scripts/verify_phase6_live_integration_v1.py": (
        "53520a1ae92c9bbed339dc3d56e9319c78082ebe137b77ea9a39e1f4f5733917"
    ),
    "docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json": (
        "56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7"
    ),
}
FROZEN_ANCHORS = {
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "core/phase5_integration_v3.py": (
        "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d"
    ),
    "core/llm_client.py": (
        "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
    ),
    "core/missions.py": (
        "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5"
    ),
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
    "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json": (
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
    ),
    "docs/onyx/checkpoints/phase5-integration-v3/manifest.json": (
        "9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167"
    ),
}


class VerificationError(RuntimeError):
    """Candidate evidence or a frozen dependency is inconsistent."""


def _canonical_path(relative: str) -> Path:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise VerificationError("artifact path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise VerificationError("artifact path is not canonical")
    path = PROJECT.joinpath(*parsed.parts)
    if not path.is_file() or path.is_symlink():
        raise VerificationError(f"artifact is missing or linked: {relative}")
    try:
        path.resolve(strict=True).relative_to(PROJECT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"artifact escapes project: {relative}") from exc
    return path


def _digest(relative: str) -> str:
    return hashlib.sha256(_canonical_path(relative).read_bytes()).hexdigest()


def _artifact_root(artifacts: dict[str, str]) -> str:
    records = []
    for relative, digest in artifacts.items():
        _canonical_path(relative)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise VerificationError("artifact digest is malformed")
        records.append(f"{relative}\0{digest}")
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def _function_args(
    tree: ast.Module, *, class_name: str | None, function_name: str
) -> tuple[list[str], list[str]]:
    body: list[ast.stmt] = tree.body
    if class_name is not None:
        classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(classes) != 1:
            raise VerificationError(f"class is missing or duplicated: {class_name}")
        body = classes[0].body
    functions = [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(functions) != 1:
        raise VerificationError(f"function is missing or duplicated: {function_name}")
    function = functions[0]
    positional = [argument.arg for argument in function.args.args]
    keyword_only = [argument.arg for argument in function.args.kwonlyargs]
    if function.args.vararg is not None or function.args.kwarg is not None:
        raise VerificationError(f"variadic operational seam: {function_name}")
    return positional, keyword_only


def verify() -> dict[str, object]:
    try:
        manifest = json.loads(_canonical_path(MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("manifest is unreadable") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "OnyxPhase6LiveIntegrationCheckpoint.v2"
        or manifest.get("status") != "candidate_default_off_not_live"
    ):
        raise VerificationError("manifest identity or status is invalid")
    if manifest.get("activation") != {
        "feature_flag": "ONYX_PHASE6_LIVE_INTEGRATION_V2",
        "enabled_value": "true",
        "default": "off",
        "live_wiring": False,
    }:
        raise VerificationError("activation contract is invalid")

    raw_artifacts = manifest.get("artifacts")
    if type(raw_artifacts) is not list:
        raise VerificationError("manifest artifacts are invalid")
    artifacts: dict[str, str] = {}
    for item in raw_artifacts:
        if type(item) is not dict or set(item) != {"path", "bytes", "sha256"}:
            raise VerificationError("artifact record is invalid")
        relative = item["path"]
        if relative in artifacts:
            raise VerificationError("artifact path is duplicated")
        path = _canonical_path(relative)
        if item["bytes"] != path.stat().st_size:
            raise VerificationError(f"artifact size drifted: {relative}")
        digest = _digest(relative)
        if item["sha256"] != digest:
            raise VerificationError(f"artifact digest drifted: {relative}")
        artifacts[relative] = digest
    if set(artifacts) != EXPECTED_ARTIFACTS:
        raise VerificationError("artifact closure is incomplete")
    root = _artifact_root(artifacts)
    if manifest.get("artifact_root_sha256") != root:
        raise VerificationError("artifact root mismatch")

    for relative, expected in FROZEN_V1.items():
        if _digest(relative) != expected:
            raise VerificationError(f"rejected V1 drifted: {relative}")
    for relative, expected in FROZEN_ANCHORS.items():
        if _digest(relative) != expected:
            raise VerificationError(f"frozen dependency drifted: {relative}")

    rejection = _canonical_path(
        "docs/onyx/rejections/PHASE6_LIVE_INTEGRATION_V1_REJECTION.md"
    ).read_text(encoding="utf-8")
    for required in (
        "REJECTED",
        "56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7",
        "4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd",
        "Incomplete host identity binding",
        "Operational construction admitted arbitrary dependencies",
    ):
        if required not in rejection:
            raise VerificationError("V1 rejection evidence is incomplete")

    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        source = _canonical_path(relative).read_text(encoding="utf-8")
        if "phase6_live_integration_v2" in source:
            raise VerificationError(f"live wiring exists in {relative}")

    source = _canonical_path("core/phase6_live_integration_v2.py").read_text(
        encoding="utf-8"
    )
    required_source = (
        'FEATURE_FLAG = "ONYX_PHASE6_LIVE_INTEGRATION_V2"',
        "_OPERATIONAL_INVOKER = live_v1._current_llm_text_call",
        "executor=TerminableProcessExecutorV4()",
        "identity.attest(agentic_core, phase5)",
        '"workspace_id": self.workspace_id',
        '"account_id": self.account_id',
        '"profile_id": self.profile_id',
        '"principal_id": self.principal_id',
        '"identity_digest": self.identity.digest',
        "DisabledExternalAgentAdapterV1",
        "WAITING_FOR_PHASE5",
    )
    missing = [value for value in required_source if value not in source]
    if missing:
        raise VerificationError(f"V2 contract is missing: {missing[0]}")
    if source.index("identity.attest(agentic_core, phase5)") > source.index(
        "text = CurrentTextProviderAdapterV2.operational(identity)"
    ):
        raise VerificationError("identity is not attested before text construction")
    forbidden = (
        "requests.",
        "subprocess.",
        "selenium",
        "playwright",
        "browser_control",
    )
    present = [value for value in forbidden if value in source]
    if present:
        raise VerificationError(f"unexpected direct capability: {present[0]}")

    tree = ast.parse(source, filename="core/phase6_live_integration_v2.py")
    init_positional, init_keyword = _function_args(
        tree,
        class_name="CurrentTextProviderAdapterV2",
        function_name="__init__",
    )
    if init_positional != ["self"] or init_keyword != ["identity"]:
        raise VerificationError("operational adapter constructor is not sealed")
    factory_positional, factory_keyword = _function_args(
        tree, class_name=None, function_name="create_phase6_live_integration_v2"
    )
    if factory_positional or factory_keyword != [
        "gate",
        "identity",
        "agentic_core",
        "agentic_state",
        "phase5",
        "receipt_path",
    ]:
        raise VerificationError("operational factory signature is not sealed")

    if manifest.get("v1_rejection") != {
        "status": "rejected_preserved_default_off_never_live",
        "manifest_sha256": (
            "56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7"
        ),
        "artifact_root_sha256": (
            "4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd"
        ),
    }:
        raise VerificationError("V1 rejection disposition is invalid")
    if manifest.get("external_agent") != {
        "adapter_id": "external_agent_disabled",
        "status": "blocked_by_access",
        "live": False,
    }:
        raise VerificationError("external-agent boundary is invalid")

    return {
        "marker": MARKER,
        "artifact_root_sha256": root,
        "artifacts": len(artifacts),
        "frozen_v1_anchors": len(FROZEN_V1),
        "frozen_accepted_anchors": len(FROZEN_ANCHORS),
        "identity_fields": 4,
        "factory_sealed": True,
        "live_wiring": False,
        "external_agent": "blocked_by_access",
    }


if __name__ == "__main__":
    result = verify()
    print(MARKER)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
