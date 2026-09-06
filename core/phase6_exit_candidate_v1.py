"""Evidence-only Phase 6 exit candidate.

This module composes the independently accepted Phase 6 slices into one
read-only, default-off gate.  It grants no runtime authority and deliberately
keeps the Phase 6 exit false until a separate E6 acceptance record exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final


FEATURE_FLAG: Final = "ONYX_PHASE6_EXIT_CANDIDATE_V1"
ENABLED_VALUE: Final = "true"
CANDIDATE: Final = "phase6-exit-candidate-v1"
MATRIX_MARKER: Final = "## Phase 6 E1-E5 exit candidate V1 (E6 pending)"
ZERO_FINDINGS: Final = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
CALL_COUNTER_KEYS: Final = (
    "network_calls",
    "provider_calls",
    "process_calls",
    "live_calls",
)


class Phase6ExitCandidateV1Error(RuntimeError):
    """The Phase 6 evidence closure is missing, drifted, or overclaimed."""


class Phase6ExitCandidateV1ContractError(ValueError):
    """A candidate input is not exact."""


@dataclass(frozen=True, slots=True)
class Phase6ExitFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6ExitCandidateV1ContractError(
                "feature gate must be an exact bool"
            )

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "Phase6ExitFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class EvidenceRootV1:
    path: str
    sha256: str
    role: str

    def __post_init__(self) -> None:
        if (
            type(self.path) is not str
            or not self.path
            or type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
            or type(self.role) is not str
            or not self.role
        ):
            raise Phase6ExitCandidateV1ContractError("invalid evidence root")


@dataclass(frozen=True, slots=True)
class Phase6ExitCandidateReportV1:
    candidate: str
    component_acceptances: int
    evidence_roots: int
    e1_e5_ready: bool
    ready_for_external_gate: bool
    external_e6_accepted: bool
    phase6_exit: bool
    phase7_unlocked: bool
    runtime_authority_added: bool
    live_observation_only: bool
    permanent_provider_availability: bool
    external_agent_authority: bool
    cross_route_authority: bool
    additional_provider_authority: bool
    network_calls: int
    provider_calls: int
    process_calls: int
    live_calls: int

    def __post_init__(self) -> None:
        expected_false = (
            self.external_e6_accepted,
            self.phase6_exit,
            self.phase7_unlocked,
            self.runtime_authority_added,
            self.permanent_provider_availability,
            self.external_agent_authority,
            self.cross_route_authority,
            self.additional_provider_authority,
        )
        if (
            self.candidate != CANDIDATE
            or type(self.component_acceptances) is not int
            or self.component_acceptances != 8
            or type(self.evidence_roots) is not int
            or self.evidence_roots != len(EVIDENCE_ROOTS)
            or self.e1_e5_ready is not True
            or self.ready_for_external_gate is not True
            or self.live_observation_only is not True
            or any(value is not False for value in expected_false)
            or any(
                type(value) is not int or value != 0
                for value in (
                    self.network_calls,
                    self.provider_calls,
                    self.process_calls,
                    self.live_calls,
                )
            )
        ):
            raise Phase6ExitCandidateV1ContractError(
                "candidate report exceeds evidence-only authority"
            )


EVIDENCE_ROOTS: Final = (
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json",
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15",
        "accepted-agentic-core-v6-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-AGENTIC-CORE-V6-E6-001.md",
        "5a42068983942c1bf163fc7b8fddaf8ce336cb5a253a228e319943cc04d8d23d",
        "accepted-agentic-core-v6-record",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json",
        "d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a",
        "accepted-live-integration-v2-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LIVE-INTEGRATION-V2-E6-001.md",
        "cfe947b7c81bbf7ad0fb6e75469c473c0d69c8b1b813d89c08ca1c729dd9f687",
        "accepted-live-integration-v2-record",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-gemini-live-compat-v1/manifest.json",
        "588d1c7d897ae0533031d2a20ea94f0fb711b8e8fc299da7f37b3604e3ef9854",
        "accepted-gemini-live-compat-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001.md",
        "d8d733ec78e3e9fffc86621b8135caacc5e27b9198365d7c9240959770b31986",
        "accepted-gemini-live-compat-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001.manifest.json",
        "c457dcef538372c60dbe3278a34d628d41137bed50e1c6c1e2ff595d092eb833",
        "accepted-gemini-live-compat-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-local-text-compat-v1/manifest.json",
        "a4c972e5ef74745884faf0c03e5bce3cad5424c524a7d03eee36a59f59ae49fc",
        "accepted-local-text-compat-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001.md",
        "289c230f9db0f837e29ce03693dc27e76a5fe76789e020309fc30ab0a7160f92",
        "accepted-local-text-compat-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001.manifest.json",
        "0ac14ab27130d6e7beae37f1da66bf83ead6582818b56db0a31c467632baa302",
        "accepted-local-text-compat-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json",
        "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
        "accepted-provider-registry-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.md",
        "ca7f0760723c4f6ad5d2a8716248c75c695e58cdb3e9b6917a3d027443aefabd",
        "accepted-provider-registry-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
        "4a2c69076a1e6b07f606d30733b357f7c50c08193ff90a250d351637f0c0d070",
        "accepted-provider-registry-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-research-cells-v1/manifest.json",
        "216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab",
        "accepted-research-cells-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.md",
        "83d936789d1c4ce851b95fe71946161ee7bb0ecb5ae23a8b26de54b954284bec",
        "accepted-research-cells-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.manifest.json",
        "e6419ff154499b913e0e2dbb78b1f3918b32cc869cfd3def1b3566bb33cbb32c",
        "accepted-research-cells-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-local-mcp-v1-c002/manifest.json",
        "4535ca73d18aca0bc82bd8544a920874e7f1c27a4403095c634987d991de2a06",
        "accepted-local-mcp-c002-dependency-rebind",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LOCAL-MCP-V1-E6-001.md",
        "80811aa68a7ea80988f6b3ef08bdd711052c0b34d16a0a17c103f2b1b8a45950",
        "accepted-local-mcp-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LOCAL-MCP-V1-E6-001.manifest.json",
        "69cc00d9b440660972b3a9960e5a9cd489d709abdff02e03ded629132f14c519",
        "accepted-local-mcp-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-unified-command-router-v1/manifest.json",
        "e78d887f87922290e19e1427fa030e276152b14acb5a72be1c5b53cb645d7abe",
        "accepted-unified-router-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-UNIFIED-ROUTER-V1-C002-E6-001.md",
        "f00c5f42e346911d15d5b7c2a9a20783c6cb135fa3d56b0bfa0c257cd97ae5a2",
        "accepted-unified-router-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-UNIFIED-ROUTER-V1-C002-E6-001.manifest.json",
        "5381e06180b375fd3e5be256d9023b883937129dd260cd7656ea3f169f2311f3",
        "accepted-unified-router-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-disabled-external-agent-descriptor-v1/manifest.json",
        "d0d356b808dfbb1996dd31c57cb9f9d95774a9c2d3ad7488d0a9bb81c4177293",
        "accepted-disabled-external-agent-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.md",
        "efc8f6f62908fef1afb007981b8041f2e965b9eacf7ec9dd7d05496b128ba89d",
        "accepted-disabled-external-agent-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.manifest.json",
        "b79642c665b481406d2ed6fb105903dfb799c656cfb707b24db33979f6b3ccef",
        "accepted-disabled-external-agent-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json",
        "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee",
        "accepted-live-wiring-v1-manifest",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md",
        "51c542420b55f58409fba1b9a5efe753fb9aabdfebd1bc5e3ab2b9abf1f15dd7",
        "accepted-live-wiring-v1-record",
    ),
    EvidenceRootV1(
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "8e4f139033bd8450a7f4c3c325363e57166bb7d0de3d5f5e6baf4f6817e8088c",
        "accepted-live-wiring-v1-metadata",
    ),
    EvidenceRootV1(
        "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json",
        "d29da31c06587c7fbef5c5bf69e7f6699cd7e39fe48ad547b854e036515ff8c5",
        "frozen-live-wiring-v2-candidate",
    ),
    EvidenceRootV1(
        "core/onyx_live_activation_v13.py",
        "cc827e41b57145da8086f698add0592e8ed607370b7d520ecec682fde38456d1",
        "v13-live-composition-source",
    ),
    EvidenceRootV1(
        "scripts/bootstrap_onyx_live_v13.pyw",
        "cc85021286b2aa1b84530eedb2883d1afeabc27e4417f54b4decf2e29d16020c",
        "v13-live-bootstrap",
    ),
    EvidenceRootV1(
        "scripts/launch_onyx_live_v13.pyw",
        "e6372d9c8e38ad58f72fd43b9b303766b4dd6c57831baf5ef67786bebeebb4c9",
        "v13-live-launcher",
    ),
    EvidenceRootV1(
        "tests/test_onyx_live_activation_v13.py",
        "ccd49bdfa2001dca0f7c15f6b5e1896e50ab7e247dc9db5b20ea956a55a4fd06",
        "v13-live-composition-tests",
    ),
    EvidenceRootV1(
        "docs/onyx/operations/ONYX_V13_LIVE_PROMOTION_2026-07-23.md",
        "ddc98efd42dd1ec1c102a704812c0104c2455f19eb82120d4c46ce8314cf7d42",
        "v13-point-in-time-operational-observation",
    ),
)


ACCEPTANCE_METADATA: Final = {
    "gemini_live": (
        "docs/onyx/acceptance/VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001.manifest.json",
        "VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001",
        "588d1c7d897ae0533031d2a20ea94f0fb711b8e8fc299da7f37b3604e3ef9854",
    ),
    "local_text": (
        "docs/onyx/acceptance/VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001.manifest.json",
        "VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001",
        "a4c972e5ef74745884faf0c03e5bce3cad5424c524a7d03eee36a59f59ae49fc",
    ),
    "provider_registry": (
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
        "VE-P6-PROVIDER-REGISTRY-V1-E6-001",
        "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
    ),
    "research_cells": (
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.manifest.json",
        "VE-P6-RESEARCH-CELLS-V1-E6-001",
        "216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab",
    ),
    "local_mcp": (
        "docs/onyx/acceptance/VE-P6-LOCAL-MCP-V1-E6-001.manifest.json",
        "VE-P6-LOCAL-MCP-V1-E6-001",
        "9529946b80d4ee8c4434acd2db064afab03bbb049482e82126a57151fc395921",
    ),
    "unified_router": (
        "docs/onyx/acceptance/VE-P6-UNIFIED-ROUTER-V1-C002-E6-001.manifest.json",
        "VE-P6-UNIFIED-ROUTER-V1-C002-E6-001",
        "e78d887f87922290e19e1427fa030e276152b14acb5a72be1c5b53cb645d7abe",
    ),
    "external_agent": (
        "docs/onyx/acceptance/VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.manifest.json",
        "VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001",
        "d0d356b808dfbb1996dd31c57cb9f9d95774a9c2d3ad7488d0a9bb81c4177293",
    ),
    "live_wiring_v1": (
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "VE-P6-LIVE-WIRING-V1-E6-001",
        "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee",
    ),
}


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _project_root(value: Path | str) -> Path:
    lexical = Path(value).absolute()
    try:
        info = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Phase6ExitCandidateV1Error("project root is unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _is_reparse(info)
        or resolved != lexical
    ):
        raise Phase6ExitCandidateV1Error("project root must be canonical")
    return resolved


def _regular_bytes(project: Path, relative: str) -> bytes:
    value = Path(relative)
    if (
        type(relative) is not str
        or not relative
        or value.is_absolute()
        or ".." in value.parts
        or value.as_posix() != relative
    ):
        raise Phase6ExitCandidateV1Error(f"unsafe evidence path: {relative!r}")
    lexical = project.joinpath(*value.parts)
    try:
        before = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(project)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Phase6ExitCandidateV1Error(
            f"evidence path is unavailable: {relative}"
        ) from exc
    if (
        resolved != lexical.absolute()
        or stat.S_ISLNK(before.st_mode)
        or _is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
    ):
        raise Phase6ExitCandidateV1Error(
            f"evidence path is not a canonical regular file: {relative}"
        )
    try:
        payload = resolved.read_bytes()
        after = os.stat(resolved, follow_symlinks=False)
    except OSError as exc:
        raise Phase6ExitCandidateV1Error(
            f"evidence path cannot be read: {relative}"
        ) from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(payload) != after.st_size:
        raise Phase6ExitCandidateV1Error(
            f"evidence path changed during read: {relative}"
        )
    return payload


def _strict_json_bytes(payload: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase6ExitCandidateV1Error(
                    f"duplicate JSON key in {label}: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase6ExitCandidateV1Error(f"invalid JSON: {label}") from exc
    if type(value) is not dict:
        raise Phase6ExitCandidateV1Error(f"JSON object required: {label}")
    return value


def _strict_json(project: Path, relative: str) -> dict[str, object]:
    return _strict_json_bytes(_regular_bytes(project, relative), relative)


def _verify_root_hashes(project: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    roles: set[str] = set()
    for root in EVIDENCE_ROOTS:
        if root.path in observed or root.role in roles:
            raise Phase6ExitCandidateV1Error("duplicate evidence root")
        actual = hashlib.sha256(_regular_bytes(project, root.path)).hexdigest()
        if actual != root.sha256:
            raise Phase6ExitCandidateV1Error(f"evidence root hash drift: {root.path}")
        observed[root.path] = actual
        roles.add(root.role)
    return observed


def _require_zero_calls(data: dict[str, object], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in data and (type(data[key]) is not int or data[key] != 0):
            raise Phase6ExitCandidateV1Error(f"non-zero side effect counter: {key}")


def _validate_acceptance_metadata(
    component: str,
    data: dict[str, object],
    acceptance_id: str,
    candidate_manifest_sha256: str,
) -> None:
    if (
        data.get("acceptance_id") != acceptance_id
        or data.get("decision") != "accepted"
        or data.get("findings") != ZERO_FINDINGS
        or data.get("candidate_manifest_sha256") != candidate_manifest_sha256
    ):
        raise Phase6ExitCandidateV1Error(f"acceptance contract drift: {component}")

    if component == "gemini_live":
        golden = data.get("golden")
        if (
            golden != {"passed": 11, "failed": 0}
            or data.get("fake_client_only") is not True
            or data.get("network_calls") != 0
            or data.get("live_activated") is not False
        ):
            raise Phase6ExitCandidateV1Error("Gemini Live evidence overclaim")
    elif component == "local_text":
        contracts = data.get("contracts")
        results = data.get("results")
        if (
            type(contracts) is not dict
            or type(results) is not dict
            or contracts.get("providers") != ["ollama", "openai_compatible"]
            or contracts.get("streaming_nonstreaming") is not True
            or contracts.get("tool_call_parity") is not True
            or contracts.get("silent_retry") is not False
            or contracts.get("silent_cross_routing") is not False
            or contracts.get("privacy") != "http_loopback_only"
            or data.get("default_off") is not True
            or data.get("factory_only") is not True
            or data.get("live_activation") is not False
            or data.get("phase6_exit") is not False
            or results.get("network_calls") != 0
            or results.get("provider_calls") != 0
        ):
            raise Phase6ExitCandidateV1Error("local/text compatibility drift")
    elif component == "provider_registry":
        contracts = data.get("contracts")
        if (
            type(contracts) is not dict
            or contracts.get("hard_privacy_before_health_ranking") is not True
            or contracts.get("sensitive_remote_fallback") is not False
            or contracts.get("provider_invocation") is not False
            or contracts.get("network_calls") != 0
            or data.get("default_off") is not True
            or data.get("live_wiring") is not False
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error("provider registry privacy drift")
    elif component == "research_cells":
        contracts = data.get("contracts")
        if (
            type(contracts) is not dict
            or contracts.get("distinct_cells_and_instructions") is not True
            or contracts.get("content_never_instruction") is not True
            or contracts.get("research_self_certifies") is not False
            or contracts.get("verifier_generates_facts") is not False
            or contracts.get("decisions") != ["accept", "revise", "reject"]
            or contracts.get("provider_invocation") is not False
            or contracts.get("network_calls") != 0
            or data.get("default_off") is not True
            or data.get("live_wiring") is not False
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error("research/verifier contract drift")
    elif component == "local_mcp":
        if (
            data.get("protocol_revision") != "2025-11-25"
            or data.get("transport") != "stdio-newline-utf8-json-rpc"
            or data.get("network_calls") != 0
            or data.get("provider_calls") != 0
            or data.get("default_off") is not True
            or data.get("factory_only") is not True
            or data.get("live_activation") is not False
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error("local MCP contract drift")
    elif component == "unified_router":
        if (
            data.get("dependency_reacceptance")
            != "local_mcp_v1_c002_activation_v10_c003_accepted"
            or data.get("network_calls") != 0
            or data.get("process_calls") != 0
            or data.get("provider_calls") != 0
            or data.get("live_calls") != 0
            or data.get("default_off") is not True
            or data.get("live_activation") is not False
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error("unified router authority drift")
    elif component == "external_agent":
        if (
            data.get("authority_granted") is not False
            or data.get("network_calls") != 0
            or data.get("process_calls") != 0
            or data.get("provider_calls") != 0
            or data.get("live_calls") != 0
            or data.get("live_activation") is not False
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error(
                "external agent must remain blocked without authority"
            )
    elif component == "live_wiring_v1":
        if (
            data.get("default_off") is not True
            or data.get("live_wiring") is not False
            or data.get("network_calls") != 0
            or data.get("phase6_exit") is not False
        ):
            raise Phase6ExitCandidateV1Error("Live Wiring V1 scope drift")
    else:
        raise Phase6ExitCandidateV1Error(f"unknown component: {component}")


def _verify_acceptances(project: Path) -> None:
    if set(ACCEPTANCE_METADATA) != {
        "gemini_live",
        "local_text",
        "provider_registry",
        "research_cells",
        "local_mcp",
        "unified_router",
        "external_agent",
        "live_wiring_v1",
    }:
        raise Phase6ExitCandidateV1Error("Phase 6 component set is incomplete")
    for component, (
        path,
        acceptance_id,
        manifest_sha256,
    ) in ACCEPTANCE_METADATA.items():
        data = _strict_json(project, path)
        _validate_acceptance_metadata(
            component,
            data,
            acceptance_id,
            manifest_sha256,
        )


def _verify_foundation_acceptances(project: Path) -> None:
    agentic_manifest = _strict_json(
        project,
        "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json",
    )
    live_manifest = _strict_json(
        project,
        "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json",
    )
    agentic_record = _regular_bytes(
        project,
        "docs/onyx/acceptance/VE-P6-AGENTIC-CORE-V6-E6-001.md",
    ).decode("utf-8")
    live_record = _regular_bytes(
        project,
        "docs/onyx/acceptance/VE-P6-LIVE-INTEGRATION-V2-E6-001.md",
    ).decode("utf-8")
    agentic_guards = agentic_manifest.get("scope_guards")
    live_external_agent = live_manifest.get("external_agent")
    if (
        agentic_manifest.get("schema") != "OnyxPhase6AgenticCoreCheckpoint.v6"
        or agentic_manifest.get("artifact_root_sha256")
        != "ca7d7f3281d9926848696e25befe63373738596dbc7e9b5bdaf95325922b06b0"
        or type(agentic_guards) is not dict
        or agentic_guards.get("network_calls") is not False
        or agentic_guards.get("provider_calls") is not False
        or "Decision: **ACCEPTED — Agentic Core V6 only" not in agentic_record
        or "`P0=0, P1=0, P2=0, P3=0`" not in agentic_record
    ):
        raise Phase6ExitCandidateV1Error("Agentic Core V6 acceptance drift")
    live_scope = live_manifest.get("scope")
    if (
        live_manifest.get("schema") != "OnyxPhase6LiveIntegrationCheckpoint.v2"
        or live_manifest.get("artifact_root_sha256")
        != "0b58365a0c43ea9b7133de1c0a51e77aa6bd855852849dab2bd9c433f733a334"
        or type(live_scope) is not dict
        or live_scope.get("gemini_live_adapter") is not False
        or live_scope.get("live_activation") is not False
        or live_scope.get("phase6_exit_claimed") is not False
        or type(live_external_agent) is not dict
        or live_external_agent.get("status") != "blocked_by_access"
        or "Decision: **ACCEPTED — Live Integration V2 only" not in live_record
    ):
        raise Phase6ExitCandidateV1Error("Live Integration V2 acceptance drift")


def _verify_local_mcp_reacceptance(project: Path) -> None:
    data = _strict_json(
        project,
        "docs/onyx/checkpoints/phase6-local-mcp-v1-c002/manifest.json",
    )
    verification = data.get("verification")
    rebind = data.get("dependency_rebind")
    if (
        data.get("schema") != "OnyxPhase6LocalMCPReacceptance.v1"
        or data.get("status") != "accepted-dependency-rebind-default-off-not-live"
        or type(verification) is not dict
        or verification.get("network_calls") != 0
        or verification.get("provider_calls") != 0
        or verification.get("live_activation") is not False
        or verification.get("phase6_exit") is not False
        or type(rebind) is not dict
        or rebind.get("activation_candidate") != "onyx-live-activation-v10-c003"
        or rebind.get("activation_e6") != "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001"
        or rebind.get("activation_e6_findings") != ZERO_FINDINGS
    ):
        raise Phase6ExitCandidateV1Error("Local MCP C002 reacceptance drift")


def _verify_wiring_v2(project: Path) -> None:
    manifest = _strict_json(
        project,
        "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json",
    )
    effects = manifest.get("effects")
    provider_truth = manifest.get("provider_truth")
    scope = manifest.get("scope")
    if (
        manifest.get("schema") != "OnyxPhase6LiveWiringCheckpoint.v2"
        or manifest.get("candidate") != "phase6-live-wiring-v2-candidate-001"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("default_off") is not True
        or manifest.get("live_wiring") is not False
        or manifest.get("component_acceptance_roots") != 15
        or manifest.get("artifact_root_sha256")
        != "dfdcd199147871cc10f3bf120db21cdffda339d12e0737b6e6e44526a7e5615b"
        or type(effects) is not dict
        or any(effects.get(key) != 0 for key in CALL_COUNTER_KEYS)
        or effects.get("mcp_process_opened") is not False
        or effects.get("external_agent_installed") is not False
        or type(provider_truth) is not dict
        or provider_truth.get("v1_registry_status") != "blocked_by_policy"
        or provider_truth.get("confidential_remote_route") is not False
        or type(scope) is not dict
        or scope.get("live_activation") is not False
        or scope.get("phase6_exit_claimed") is not False
    ):
        raise Phase6ExitCandidateV1Error("Live Wiring V2 candidate drift")
    from scripts.verify_phase6_live_wiring_v2 import verify

    reproduced = verify()
    if (
        reproduced.get("candidate") != "phase6-live-wiring-v2-candidate-001"
        or reproduced.get("artifact_root_sha256")
        != "dfdcd199147871cc10f3bf120db21cdffda339d12e0737b6e6e44526a7e5615b"
        or reproduced.get("component_roots") != 15
        or reproduced.get("default_off") is not True
        or reproduced.get("live_wiring") is not False
        or reproduced.get("phase6_exit") is not False
        or any(reproduced.get(key) != 0 for key in CALL_COUNTER_KEYS)
    ):
        raise Phase6ExitCandidateV1Error("Live Wiring V2 reproduction drift")


def _verify_v13_observation(project: Path) -> None:
    source = _regular_bytes(project, "core/onyx_live_activation_v13.py").decode("utf-8")
    launcher = _regular_bytes(
        project,
        "scripts/launch_onyx_live_v13.pyw",
    ).decode("utf-8")
    record = _regular_bytes(
        project,
        "docs/onyx/operations/ONYX_V13_LIVE_PROMOTION_2026-07-23.md",
    ).decode("utf-8")
    required_source = (
        'LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V13"',
        "WIRING_V2_MANIFEST: Final = Path(",
        "verify_wiring_v2",
    )
    required_record = (
        "PIDs are observation evidence only and are not persistent identity.",
        "It does not establish permanent provider availability.",
        "The External-Agent descriptor remains `BLOCKED_BY_ACCESS`.",
        "This promotion is not Phase 6 exit",
    )
    if (
        any(value not in source for value in required_source)
        or "hud=v9 arcs=0 wiring=v2 components=5 provider_calls=0" not in launcher
        or any(value not in record for value in required_record)
    ):
        raise Phase6ExitCandidateV1Error("V13 observation scope drift")


def _verify_matrix_delta(project: Path) -> None:
    matrix = _regular_bytes(project, "docs/onyx/CAPABILITY_MATRIX.md").decode("utf-8")
    if MATRIX_MARKER not in matrix:
        raise Phase6ExitCandidateV1Error("Phase 6 capability delta is absent")
    section = matrix.split(MATRIX_MARKER, 1)[1]
    if "## Matrix governance" in section:
        section = section.split("## Matrix governance", 1)[0]
    normalized = " ".join(section.split())
    required = (
        "VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001",
        "VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001",
        "VE-P6-PROVIDER-REGISTRY-V1-E6-001",
        "VE-P6-RESEARCH-CELLS-V1-E6-001",
        "VE-P6-LOCAL-MCP-V1-E6-001",
        "VE-P6-UNIFIED-ROUTER-V1-C002-E6-001",
        "VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001",
        "VE-P6-LIVE-WIRING-V1-E6-001",
        "`BLOCKED_BY_ACCESS`",
        "E6 pending",
        "does not unlock Phase 7",
    )
    if any(value not in normalized for value in required):
        raise Phase6ExitCandidateV1Error("Phase 6 capability delta is incomplete")


def create_phase6_exit_candidate_v1(
    *,
    gate: Phase6ExitFeatureGateV1 | None = None,
    project_root: Path | str | None = None,
) -> Phase6ExitCandidateReportV1 | None:
    """Reproduce the E1-E5 evidence closure without adding live authority."""

    selected = Phase6ExitFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not Phase6ExitFeatureGateV1:
        raise Phase6ExitCandidateV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None

    project = _project_root(
        Path(__file__).resolve().parents[1]
        if project_root is None
        else Path(project_root)
    )
    _verify_root_hashes(project)
    _verify_acceptances(project)
    _verify_foundation_acceptances(project)
    _verify_local_mcp_reacceptance(project)
    _verify_wiring_v2(project)
    _verify_v13_observation(project)
    _verify_matrix_delta(project)
    return Phase6ExitCandidateReportV1(
        candidate=CANDIDATE,
        component_acceptances=8,
        evidence_roots=len(EVIDENCE_ROOTS),
        e1_e5_ready=True,
        ready_for_external_gate=True,
        external_e6_accepted=False,
        phase6_exit=False,
        phase7_unlocked=False,
        runtime_authority_added=False,
        live_observation_only=True,
        permanent_provider_availability=False,
        external_agent_authority=False,
        cross_route_authority=False,
        additional_provider_authority=False,
        network_calls=0,
        provider_calls=0,
        process_calls=0,
        live_calls=0,
    )


__all__ = [
    "ACCEPTANCE_METADATA",
    "CALL_COUNTER_KEYS",
    "CANDIDATE",
    "ENABLED_VALUE",
    "EVIDENCE_ROOTS",
    "FEATURE_FLAG",
    "MATRIX_MARKER",
    "Phase6ExitCandidateReportV1",
    "Phase6ExitCandidateV1ContractError",
    "Phase6ExitCandidateV1Error",
    "Phase6ExitFeatureGateV1",
    "ZERO_FINDINGS",
    "create_phase6_exit_candidate_v1",
]
