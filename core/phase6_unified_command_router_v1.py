"""Isolated metadata-only Phase 6 Unified Command Router V1.

The router composes exact accepted Phase 6 authorities into deterministic
command plans.  It never invokes a provider, opens an MCP process, calls the
live facade, or treats prompt/content bytes as policy authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Mapping

import core.phase6_agentic_core_v6 as agentic_v6
import core.phase6_live_integration_v2 as live_v2
import core.phase6_local_mcp_v1 as local_mcp_v1
import core.phase6_provider_registry_v1 as provider_v1
import core.phase6_research_cells_v1 as research_v1
from core.phase6_agentic_core_v1 import DataClassV1, RouteRequestV1
from core.phase6_agentic_core_v6 import AgenticCoreV6
from core.phase6_live_integration_v2 import (
    HostIdentityBindingV2,
    Phase6LiveIntegrationV2,
)
from core.phase6_local_mcp_v1 import (
    TOOL_NAME,
    LocalCatalogMCPRequestV1,
    LocalMCPIdentityV1,
)
from core.phase6_provider_registry_v1 import (
    ProviderRegistryV1,
    ProviderRoutePlanStatusV1,
    ProviderRoutePlanV1,
)
from core.phase6_research_cells_v1 import (
    EvidenceBundleV1,
    FinalizedResearchV1,
    ResearchBudgetV1,
    ResearchVerifierPipelineV1,
    VerificationDecisionV1,
)


FEATURE_FLAG: Final = "ONYX_PHASE6_UNIFIED_COMMAND_ROUTER_V1"
CANDIDATE: Final = "phase6-unified-command-router-candidate-002"
SCHEMA_VERSION: Final = 1
ZERO_DIGEST: Final = "0" * 64
_CONSTRUCTION_KEY = object()
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_MODALITY = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
_CURSOR_BYTES: Final = 4_096
_KEY_BYTES: Final = 32
_MAX_TIME: Final = 9_223_372_036_854_775_807
_DATA_RANK = {
    DataClassV1.PUBLIC: 0,
    DataClassV1.INTERNAL: 1,
    DataClassV1.CONFIDENTIAL: 2,
    DataClassV1.RESTRICTED: 3,
}
_INTENT_MODALITY = {
    "local_catalog": "catalog",
    "research_verify": "research",
    "text_plan": "text",
}

_AGENTIC_CORE_TYPE = AgenticCoreV6
_PROVIDER_REGISTRY_TYPE = ProviderRegistryV1
_RESEARCH_PIPELINE_TYPE = ResearchVerifierPipelineV1
_LOCAL_IDENTITY_TYPE = LocalMCPIdentityV1
_LOCAL_REQUEST_TYPE = LocalCatalogMCPRequestV1
_LIVE_INTEGRATION_TYPE = Phase6LiveIntegrationV2
_HOST_IDENTITY_TYPE = HostIdentityBindingV2
_DATA_CLASS_TYPE = DataClassV1
_ROUTE_REQUEST_TYPE = RouteRequestV1
_PROVIDER_PLAN_TYPE = ProviderRoutePlanV1
_EVIDENCE_BUNDLE_TYPE = EvidenceBundleV1
_RESEARCH_BUDGET_TYPE = ResearchBudgetV1
_FINALIZED_RESEARCH_TYPE = FinalizedResearchV1
_RLOCK_TYPE = type(threading.RLock())

# Exact accepted component roots.  Candidate manifests bind their source/test
# universes; E6 records (and metadata manifests where present) bind acceptance.
COMPONENT_ACCEPTANCE_ROOTS: Final = (
    (
        "agentic_core_v6",
        "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json",
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15",
    ),
    (
        "agentic_core_v6",
        "docs/onyx/acceptance/VE-P6-AGENTIC-CORE-V6-E6-001.md",
        "5a42068983942c1bf163fc7b8fddaf8ce336cb5a253a228e319943cc04d8d23d",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json",
        "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.md",
        "ca7f0760723c4f6ad5d2a8716248c75c695e58cdb3e9b6917a3d027443aefabd",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
        "4a2c69076a1e6b07f606d30733b357f7c50c08193ff90a250d351637f0c0d070",
    ),
    (
        "research_cells_v1",
        "docs/onyx/checkpoints/phase6-research-cells-v1/manifest.json",
        "216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab",
    ),
    (
        "research_cells_v1",
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.md",
        "83d936789d1c4ce851b95fe71946161ee7bb0ecb5ae23a8b26de54b954284bec",
    ),
    (
        "research_cells_v1",
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.manifest.json",
        "e6419ff154499b913e0e2dbb78b1f3918b32cc869cfd3def1b3566bb33cbb32c",
    ),
    (
        "local_mcp_v1",
        "docs/onyx/checkpoints/phase6-local-mcp-v1/manifest.json",
        "9529946b80d4ee8c4434acd2db064afab03bbb049482e82126a57151fc395921",
    ),
    (
        "local_mcp_v1",
        "docs/onyx/acceptance/VE-P6-LOCAL-MCP-V1-E6-001.md",
        "80811aa68a7ea80988f6b3ef08bdd711052c0b34d16a0a17c103f2b1b8a45950",
    ),
    (
        "local_mcp_v1",
        "docs/onyx/acceptance/VE-P6-LOCAL-MCP-V1-E6-001.manifest.json",
        "69cc00d9b440660972b3a9960e5a9cd489d709abdff02e03ded629132f14c519",
    ),
    (
        "local_mcp_v1",
        "docs/onyx/checkpoints/phase6-local-mcp-v1-c002/manifest.json",
        "4535ca73d18aca0bc82bd8544a920874e7f1c27a4403095c634987d991de2a06",
    ),
    (
        "live_integration_v2",
        "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json",
        "d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a",
    ),
    (
        "live_integration_v2",
        "docs/onyx/acceptance/VE-P6-LIVE-INTEGRATION-V2-E6-001.md",
        "cfe947b7c81bbf7ad0fb6e75469c473c0d69c8b1b813d89c08ca1c729dd9f687",
    ),
)


class UnifiedCommandRouterV1Error(RuntimeError):
    """The isolated router failed without disclosing command content."""


class UnifiedCommandRouterV1ContractError(ValueError):
    """A caller supplied a non-canonical router contract."""


class UnifiedCommandRouterV1Denied(PermissionError):
    """The command or authority was denied fail-closed."""


class UnifiedCommandRouterV1Conflict(UnifiedCommandRouterV1Denied):
    """A request identity was already bound to a different command."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnifiedCommandRouterV1ContractError(
            "router metadata is not canonical"
        ) from exc


def _digest(value: object) -> str:
    raw = value if type(value) is bytes else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise UnifiedCommandRouterV1ContractError(f"{label} must be SHA-256")
    return value


def _require_id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise UnifiedCommandRouterV1ContractError(f"{label} is not canonical")
    return value


def _require_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise UnifiedCommandRouterV1ContractError(f"{label} is outside its bound")
    return value


def _require_key(value: object) -> bytes:
    if type(value) is not bytes or len(value) != _KEY_BYTES:
        raise UnifiedCommandRouterV1ContractError(
            "receipt authentication key must be exactly 32 bytes"
        )
    return value


def _component_root_digest() -> str:
    return _digest(
        {
            "schema": "OnyxUnifiedCommandComponentRoots.v1",
            "roots": [
                {"component": component, "path": path, "sha256": digest}
                for component, path, digest in COMPONENT_ACCEPTANCE_ROOTS
            ],
        }
    )


def _verify_component_roots(project_root: Path) -> str:
    seen: set[str] = set()
    for _component, relative, expected in COMPONENT_ACCEPTANCE_ROOTS:
        if (
            relative in seen
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or _SHA256.fullmatch(expected) is None
        ):
            raise UnifiedCommandRouterV1Denied("component root contract drift denied")
        seen.add(relative)
        path = project_root / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise UnifiedCommandRouterV1Denied("component root is unavailable") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise UnifiedCommandRouterV1Denied("component root is not a regular file")
        if not hmac.compare_digest(_sha_file(resolved), expected):
            raise UnifiedCommandRouterV1Denied("component acceptance drift denied")
    return _component_root_digest()


class CommandIntentV1(StrEnum):
    LOCAL_CATALOG = "local_catalog"
    RESEARCH_VERIFY = "research_verify"
    TEXT_PLAN = "text_plan"


class CommandPlanStatusV1(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class UnifiedCommandRouterFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise UnifiedCommandRouterV1ContractError(
                "router gate must be an exact boolean"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "UnifiedCommandRouterFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class CommandBudgetV1:
    maximum_latency_millis: int
    maximum_cost_micro: int
    minimum_reliability_milli: int
    page_size: int
    maximum_sources: int
    maximum_spans: int
    maximum_evidence_bytes: int
    maximum_evidence_age_ms: int

    def __post_init__(self) -> None:
        _require_int(
            self.maximum_latency_millis,
            "maximum_latency_millis",
            1,
            3_600_000,
        )
        _require_int(
            self.maximum_cost_micro,
            "maximum_cost_micro",
            0,
            1_000_000_000,
        )
        _require_int(
            self.minimum_reliability_milli,
            "minimum_reliability_milli",
            0,
            1_000,
        )
        _require_int(self.page_size, "page_size", 1, 50)
        _require_int(self.maximum_sources, "maximum_sources", 1, 64)
        _require_int(self.maximum_spans, "maximum_spans", 1, 2_048)
        _require_int(
            self.maximum_evidence_bytes,
            "maximum_evidence_bytes",
            1,
            8_000_000,
        )
        _require_int(
            self.maximum_evidence_age_ms,
            "maximum_evidence_age_ms",
            1,
            31_536_000_000,
        )

    def payload(self) -> dict[str, int]:
        return {
            "maximum_latency_millis": self.maximum_latency_millis,
            "maximum_cost_micro": self.maximum_cost_micro,
            "minimum_reliability_milli": self.minimum_reliability_milli,
            "page_size": self.page_size,
            "maximum_sources": self.maximum_sources,
            "maximum_spans": self.maximum_spans,
            "maximum_evidence_bytes": self.maximum_evidence_bytes,
            "maximum_evidence_age_ms": self.maximum_evidence_age_ms,
        }


@dataclass(frozen=True, slots=True)
class UserCommandV1:
    request_id: str
    identity: HostIdentityBindingV2
    workspace_id: str
    data_class: DataClassV1
    modality: str
    budget: CommandBudgetV1
    deadline_at_ms: int
    cancelled: bool
    intent: CommandIntentV1
    input_digest: str
    evidence_bundle: EvidenceBundleV1 | None = None
    catalog_cursor: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request_id")
        if type(self.identity) is not _HOST_IDENTITY_TYPE:
            raise UnifiedCommandRouterV1ContractError(
                "exact HostIdentityBindingV2 is required"
            )
        _require_id(self.workspace_id, "workspace_id")
        if self.workspace_id != self.identity.workspace_id:
            raise UnifiedCommandRouterV1Denied("command identity workspace diverged")
        if type(self.data_class) is not _DATA_CLASS_TYPE:
            raise UnifiedCommandRouterV1ContractError("exact DataClassV1 is required")
        if type(self.modality) is not str or _MODALITY.fullmatch(self.modality) is None:
            raise UnifiedCommandRouterV1ContractError("modality is not canonical")
        if type(self.budget) is not CommandBudgetV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact CommandBudgetV1 is required"
            )
        _require_int(self.deadline_at_ms, "deadline_at_ms", 0, _MAX_TIME)
        if type(self.cancelled) is not bool:
            raise UnifiedCommandRouterV1ContractError(
                "cancelled must be an exact boolean"
            )
        if type(self.intent) is not CommandIntentV1:
            raise UnifiedCommandRouterV1ContractError(
                "explicit exact CommandIntentV1 is required"
            )
        _require_digest(self.input_digest, "input_digest")
        expected_modality = _INTENT_MODALITY[self.intent.value]
        if self.modality != expected_modality:
            raise UnifiedCommandRouterV1Denied("intent and modality crossing is denied")
        if self.intent is CommandIntentV1.RESEARCH_VERIFY:
            if (
                type(self.evidence_bundle) is not _EVIDENCE_BUNDLE_TYPE
                or self.catalog_cursor is not None
            ):
                raise UnifiedCommandRouterV1Denied(
                    "research intent requires only exact evidence"
                )
        elif self.evidence_bundle is not None:
            raise UnifiedCommandRouterV1Denied(
                "evidence cannot cross into non-research intent"
            )
        if self.intent is not CommandIntentV1.LOCAL_CATALOG:
            if self.catalog_cursor is not None:
                raise UnifiedCommandRouterV1Denied(
                    "catalog cursor cannot cross tool intent"
                )
        elif self.catalog_cursor is not None and (
            type(self.catalog_cursor) is not str
            or not self.catalog_cursor
            or len(self.catalog_cursor.encode("utf-8")) > _CURSOR_BYTES
            or any(character in self.catalog_cursor for character in "\x00\r\n")
        ):
            raise UnifiedCommandRouterV1ContractError("catalog cursor is not canonical")

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxUserCommand.v1",
            "request_id": self.request_id,
            "identity_digest": self.identity.digest,
            "workspace_id": self.workspace_id,
            "data_class": self.data_class.value,
            "modality": self.modality,
            "budget": self.budget.payload(),
            "deadline_at_ms": self.deadline_at_ms,
            "cancelled": self.cancelled,
            "intent": self.intent.value,
            "input_digest": self.input_digest,
            "evidence_bundle_digest": (
                ZERO_DIGEST
                if self.evidence_bundle is None
                else self.evidence_bundle.digest
            ),
            "catalog_cursor_digest": (
                ZERO_DIGEST
                if self.catalog_cursor is None
                else _digest(self.catalog_cursor.encode("utf-8"))
            ),
        }

    @property
    def digest(self) -> str:
        return _digest(self.payload())


def _provider_plan_payload(plan: ProviderRoutePlanV1 | None) -> dict[str, object]:
    if plan is None:
        return {"present": False}
    if type(plan) is not _PROVIDER_PLAN_TYPE:
        raise UnifiedCommandRouterV1ContractError(
            "exact ProviderRoutePlanV1 is required"
        )
    return {
        "present": True,
        "status": plan.status.value,
        "reason": plan.reason,
        "request_digest": plan.request_digest,
        "ordered_targets": [
            {
                "adapter_id": item.adapter_id,
                "provider_id": item.provider_id,
                "api_version": item.api_version,
                "model_id": item.model_id,
                "record_version": item.record_version,
                "provider_record_digest": item.provider_record_digest,
                "health_digest": item.health_digest,
                "health_status": item.health_status.value,
            }
            for item in plan.ordered_targets
        ],
        "considered": plan.considered,
        "exclusion_digest": plan.exclusion_digest,
    }


def _provider_plan_digest(plan: ProviderRoutePlanV1 | None) -> str:
    return ZERO_DIGEST if plan is None else _digest(_provider_plan_payload(plan))


@dataclass(frozen=True, slots=True)
class CommandPlanV1:
    status: CommandPlanStatusV1
    reason: str
    request_id: str
    intent: CommandIntentV1
    workspace_id: str
    identity_digest: str
    command_digest: str
    component_root_digest: str
    provider_route_plan: ProviderRoutePlanV1 | None
    research_bundle_digest: str
    verification_report_digest: str
    verification_decision: VerificationDecisionV1 | None
    finalized_research: FinalizedResearchV1 | None
    mcp_request: LocalCatalogMCPRequestV1 | None
    tool_name: str | None
    rationale_codes: tuple[str, ...]
    provider_calls: int = 0
    process_calls: int = 0
    network_calls: int = 0
    live_calls: int = 0

    def __post_init__(self) -> None:
        if type(self.status) is not CommandPlanStatusV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact CommandPlanStatusV1 is required"
            )
        if type(self.reason) is not str or _CODE.fullmatch(self.reason) is None:
            raise UnifiedCommandRouterV1ContractError("plan reason is not a code")
        _require_id(self.request_id, "request_id")
        if type(self.intent) is not CommandIntentV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact CommandIntentV1 is required"
            )
        _require_id(self.workspace_id, "workspace_id")
        for value, label in (
            (self.identity_digest, "identity_digest"),
            (self.command_digest, "command_digest"),
            (self.component_root_digest, "component_root_digest"),
            (self.research_bundle_digest, "research_bundle_digest"),
            (self.verification_report_digest, "verification_report_digest"),
        ):
            _require_digest(value, label)
        if (
            type(self.rationale_codes) is not tuple
            or self.rationale_codes != tuple(sorted(set(self.rationale_codes)))
            or any(_CODE.fullmatch(item) is None for item in self.rationale_codes)
        ):
            raise UnifiedCommandRouterV1ContractError(
                "rationale must be unique content-free codes"
            )
        if (
            self.provider_calls,
            self.process_calls,
            self.network_calls,
            self.live_calls,
        ) != (0, 0, 0, 0):
            raise UnifiedCommandRouterV1Denied(
                "router plans cannot claim or perform calls"
            )
        if self.intent is CommandIntentV1.LOCAL_CATALOG:
            if (
                self.status is not CommandPlanStatusV1.READY
                or self.provider_route_plan is not None
                or self.finalized_research is not None
                or self.verification_decision is not None
                or self.research_bundle_digest != ZERO_DIGEST
                or self.verification_report_digest != ZERO_DIGEST
                or type(self.mcp_request) is not _LOCAL_REQUEST_TYPE
                or self.tool_name != TOOL_NAME
            ):
                raise UnifiedCommandRouterV1Denied(
                    "local catalog plan crossed a provider or research boundary"
                )
        elif self.intent is CommandIntentV1.TEXT_PLAN:
            if (
                type(self.provider_route_plan) is not _PROVIDER_PLAN_TYPE
                or self.finalized_research is not None
                or self.verification_decision is not None
                or self.research_bundle_digest != ZERO_DIGEST
                or self.verification_report_digest != ZERO_DIGEST
                or self.mcp_request is not None
                or self.tool_name is not None
            ):
                raise UnifiedCommandRouterV1Denied(
                    "text plan crossed a tool or research boundary"
                )
            expected = (
                CommandPlanStatusV1.READY
                if self.provider_route_plan.status is ProviderRoutePlanStatusV1.READY
                else CommandPlanStatusV1.BLOCKED
            )
            if self.status is not expected:
                raise UnifiedCommandRouterV1Denied(
                    "provider plan status projection drifted"
                )
        else:
            if (
                self.provider_route_plan is not None
                or self.mcp_request is not None
                or self.tool_name is not None
                or self.research_bundle_digest == ZERO_DIGEST
                or self.verification_report_digest == ZERO_DIGEST
                or type(self.verification_decision) is not VerificationDecisionV1
            ):
                raise UnifiedCommandRouterV1Denied(
                    "research plan crossed a provider or tool boundary"
                )
            if self.status is CommandPlanStatusV1.READY:
                if (
                    self.verification_decision is not VerificationDecisionV1.ACCEPT
                    or type(self.finalized_research) is not _FINALIZED_RESEARCH_TYPE
                ):
                    raise UnifiedCommandRouterV1Denied(
                        "ready research requires independent acceptance"
                    )
            elif self.finalized_research is not None:
                raise UnifiedCommandRouterV1Denied(
                    "blocked research cannot expose finalization"
                )

    @property
    def provider_route_digest(self) -> str:
        return _provider_plan_digest(self.provider_route_plan)

    @property
    def mcp_request_digest(self) -> str:
        return ZERO_DIGEST if self.mcp_request is None else self.mcp_request.digest

    @property
    def finalized_research_digest(self) -> str:
        if self.finalized_research is None:
            return ZERO_DIGEST
        return _digest(
            {
                "schema": "OnyxFinalizedResearchDigest.v1",
                "workspace_id": self.finalized_research.workspace_id,
                "candidate_digest": self.finalized_research.candidate_digest,
                "verification_report_digest": (
                    self.finalized_research.verification_report_digest
                ),
                "research_receipt_digest": (
                    self.finalized_research.research_receipt_digest
                ),
                "verification_receipt_digest": (
                    self.finalized_research.verification_receipt_digest
                ),
                "status": self.finalized_research.status,
            }
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxCommandPlan.v1",
            "status": self.status.value,
            "reason": self.reason,
            "request_id": self.request_id,
            "intent": self.intent.value,
            "workspace_id": self.workspace_id,
            "identity_digest": self.identity_digest,
            "command_digest": self.command_digest,
            "component_root_digest": self.component_root_digest,
            "provider_route_digest": self.provider_route_digest,
            "research_bundle_digest": self.research_bundle_digest,
            "verification_report_digest": self.verification_report_digest,
            "verification_decision": (
                None
                if self.verification_decision is None
                else self.verification_decision.value
            ),
            "finalized_research_digest": self.finalized_research_digest,
            "mcp_request_digest": self.mcp_request_digest,
            "tool_name": self.tool_name,
            "rationale_codes": self.rationale_codes,
            "provider_calls": self.provider_calls,
            "process_calls": self.process_calls,
            "network_calls": self.network_calls,
            "live_calls": self.live_calls,
        }

    @property
    def digest(self) -> str:
        return _digest(self.payload())


@dataclass(frozen=True, slots=True)
class CommandReceiptV1:
    request_id: str
    workspace_id: str
    identity_digest: str
    command_digest: str
    plan_digest: str
    status: CommandPlanStatusV1
    intent: CommandIntentV1
    reason: str
    provider_route_digest: str
    finalized_research_digest: str
    mcp_request_digest: str
    component_root_digest: str
    authentication_tag: str

    def __post_init__(self) -> None:
        _require_id(self.request_id, "request_id")
        _require_id(self.workspace_id, "workspace_id")
        for value, label in (
            (self.identity_digest, "identity_digest"),
            (self.command_digest, "command_digest"),
            (self.plan_digest, "plan_digest"),
            (self.provider_route_digest, "provider_route_digest"),
            (self.finalized_research_digest, "finalized_research_digest"),
            (self.mcp_request_digest, "mcp_request_digest"),
            (self.component_root_digest, "component_root_digest"),
            (self.authentication_tag, "authentication_tag"),
        ):
            _require_digest(value, label)
        if type(self.status) is not CommandPlanStatusV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact CommandPlanStatusV1 is required"
            )
        if type(self.intent) is not CommandIntentV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact CommandIntentV1 is required"
            )
        if type(self.reason) is not str or _CODE.fullmatch(self.reason) is None:
            raise UnifiedCommandRouterV1ContractError(
                "receipt reason must be a content-free code"
            )

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxCommandReceipt.v1",
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "identity_digest": self.identity_digest,
            "command_digest": self.command_digest,
            "plan_digest": self.plan_digest,
            "status": self.status.value,
            "intent": self.intent.value,
            "reason": self.reason,
            "provider_route_digest": self.provider_route_digest,
            "finalized_research_digest": self.finalized_research_digest,
            "mcp_request_digest": self.mcp_request_digest,
            "component_root_digest": self.component_root_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedCommandReceipt.v1",
                "unsigned_digest": _digest(self.unsigned_payload()),
                "authentication_tag": self.authentication_tag,
            }
        )


class UnifiedCommandRouterV1:
    """Exact-component router that emits plans and authenticated receipts only."""

    __slots__ = (
        "_core",
        "_registry",
        "_research",
        "_local_identity",
        "_live",
        "_identity",
        "_workspace",
        "_project_root",
        "_component_root_digest",
        "_registry_digest",
        "_receipt_key",
        "_receipt_key_digest",
        "_replays",
        "_lock",
    )

    def __init__(
        self,
        *,
        _key: object,
        core: AgenticCoreV6,
        registry: ProviderRegistryV1,
        research: ResearchVerifierPipelineV1,
        local_identity: LocalMCPIdentityV1,
        live: Phase6LiveIntegrationV2,
        project_root: Path,
        receipt_authentication_key: bytes,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise UnifiedCommandRouterV1Denied("router construction is factory-only")
        if (
            type(core) is not _AGENTIC_CORE_TYPE
            or type(registry) is not _PROVIDER_REGISTRY_TYPE
            or type(research) is not _RESEARCH_PIPELINE_TYPE
            or type(local_identity) is not _LOCAL_IDENTITY_TYPE
            or type(live) is not _LIVE_INTEGRATION_TYPE
        ):
            raise UnifiedCommandRouterV1ContractError(
                "exact Phase 6 component instances are required"
            )
        self._core = core
        self._registry = registry
        self._research = research
        self._local_identity = local_identity
        self._live = live
        self._identity = live.identity
        self._workspace = core._workspace
        self._project_root = project_root
        self._component_root_digest = _verify_component_roots(project_root)
        self._registry_digest = registry.digest
        self._receipt_key = _require_key(receipt_authentication_key)
        self._receipt_key_digest = _digest(self._receipt_key)
        self._replays: dict[str, tuple[str, CommandPlanV1, CommandReceiptV1]] = {}
        self._lock = threading.RLock()
        self._attest()

    def _attest(self) -> None:
        if (
            agentic_v6.AgenticCoreV6 is not _AGENTIC_CORE_TYPE
            or provider_v1.ProviderRegistryV1 is not _PROVIDER_REGISTRY_TYPE
            or research_v1.ResearchVerifierPipelineV1 is not _RESEARCH_PIPELINE_TYPE
            or local_mcp_v1.LocalMCPIdentityV1 is not _LOCAL_IDENTITY_TYPE
            or local_mcp_v1.LocalCatalogMCPRequestV1 is not _LOCAL_REQUEST_TYPE
            or live_v2.Phase6LiveIntegrationV2 is not _LIVE_INTEGRATION_TYPE
            or type(self._core) is not _AGENTIC_CORE_TYPE
            or type(self._registry) is not _PROVIDER_REGISTRY_TYPE
            or type(self._research) is not _RESEARCH_PIPELINE_TYPE
            or type(self._local_identity) is not _LOCAL_IDENTITY_TYPE
            or type(self._live) is not _LIVE_INTEGRATION_TYPE
            or type(self._identity) is not _HOST_IDENTITY_TYPE
            or self._core._workspace is not self._workspace
            or self._research._core is not self._core
            or self._research._workspace is not self._workspace
            or self._live._core is not self._core
            or self._live.identity != self._identity
            or self._live.closed
            or self._local_identity.workspace_id != self._identity.workspace_id
            or self._local_identity.principal_id != self._identity.principal_id
            or self._registry.digest != self._registry_digest
            or type(self._receipt_key) is not bytes
            or len(self._receipt_key) != _KEY_BYTES
            or not hmac.compare_digest(
                _digest(self._receipt_key), self._receipt_key_digest
            )
            or type(self._replays) is not dict
            or type(self._lock) is not _RLOCK_TYPE
        ):
            raise UnifiedCommandRouterV1Denied("router authority drift denied")
        observed_root = _verify_component_roots(self._project_root)
        if not hmac.compare_digest(observed_root, self._component_root_digest):
            raise UnifiedCommandRouterV1Denied("component root drift denied")

    def _hard_gate(self, command: UserCommandV1, *, now_ms: int) -> None:
        if command.cancelled:
            raise UnifiedCommandRouterV1Denied("command cancellation is final")
        if (
            command.identity != self._identity
            or command.identity.digest != self._identity.digest
            or command.workspace_id != self._workspace.workspace_id
            or command.workspace_id != self._local_identity.workspace_id
        ):
            raise UnifiedCommandRouterV1Denied("command identity is denied")
        if (
            _DATA_RANK[command.data_class]
            > _DATA_RANK[self._workspace.maximum_data_class]
        ):
            raise UnifiedCommandRouterV1Denied("command privacy class is denied")
        if now_ms > command.deadline_at_ms:
            raise UnifiedCommandRouterV1Denied("command deadline is exhausted")
        if (
            command.intent is CommandIntentV1.TEXT_PLAN
            and command.budget.maximum_latency_millis > command.deadline_at_ms - now_ms
        ):
            raise UnifiedCommandRouterV1Denied("command latency budget is exhausted")
        if command.evidence_bundle is not None:
            if command.evidence_bundle.workspace_id != command.workspace_id:
                raise UnifiedCommandRouterV1Denied("cross-workspace evidence is denied")
            if any(
                _DATA_RANK[source.data_class] > _DATA_RANK[command.data_class]
                for source in command.evidence_bundle.sources
            ):
                raise UnifiedCommandRouterV1Denied(
                    "evidence data-class underdeclaration is denied"
                )

    def _route_text(self, command: UserCommandV1, *, now_ms: int) -> CommandPlanV1:
        request = _ROUTE_REQUEST_TYPE(
            command.workspace_id,
            command.data_class,
            "text",
            True,
            True,
            command.budget.maximum_latency_millis,
            command.budget.maximum_cost_micro,
            command.budget.minimum_reliability_milli,
        )
        route = self._registry.plan_route(request, now_ms=now_ms, cancelled=False)
        ready = route.status is ProviderRoutePlanStatusV1.READY
        return CommandPlanV1(
            status=(
                CommandPlanStatusV1.READY if ready else CommandPlanStatusV1.BLOCKED
            ),
            reason=(
                "provider_metadata_ready" if ready else "provider_metadata_blocked"
            ),
            request_id=command.request_id,
            intent=command.intent,
            workspace_id=command.workspace_id,
            identity_digest=command.identity.digest,
            command_digest=command.digest,
            component_root_digest=self._component_root_digest,
            provider_route_plan=route,
            research_bundle_digest=ZERO_DIGEST,
            verification_report_digest=ZERO_DIGEST,
            verification_decision=None,
            finalized_research=None,
            mcp_request=None,
            tool_name=None,
            rationale_codes=tuple(
                sorted(
                    {
                        "identity_bound",
                        "local_private_only",
                        "metadata_only",
                        "provider_not_invoked",
                    }
                )
            ),
        )

    def _route_catalog(self, command: UserCommandV1) -> CommandPlanV1:
        request = _LOCAL_REQUEST_TYPE(
            command.request_id,
            self._local_identity,
            command.budget.page_size,
            command.catalog_cursor,
        )
        return CommandPlanV1(
            status=CommandPlanStatusV1.READY,
            reason="local_catalog_projected",
            request_id=command.request_id,
            intent=command.intent,
            workspace_id=command.workspace_id,
            identity_digest=command.identity.digest,
            command_digest=command.digest,
            component_root_digest=self._component_root_digest,
            provider_route_plan=None,
            research_bundle_digest=ZERO_DIGEST,
            verification_report_digest=ZERO_DIGEST,
            verification_decision=None,
            finalized_research=None,
            mcp_request=request,
            tool_name=TOOL_NAME,
            rationale_codes=tuple(
                sorted(
                    {
                        "identity_bound",
                        "local_read_only",
                        "metadata_only",
                        "process_not_opened",
                        "tool_exact",
                    }
                )
            ),
        )

    def _route_research(self, command: UserCommandV1, *, now_ms: int) -> CommandPlanV1:
        bundle = command.evidence_bundle
        if type(bundle) is not _EVIDENCE_BUNDLE_TYPE:
            raise UnifiedCommandRouterV1Denied("exact evidence bundle is required")
        budget = _RESEARCH_BUDGET_TYPE(
            command.budget.maximum_sources,
            command.budget.maximum_spans,
            command.budget.maximum_evidence_bytes,
            command.budget.maximum_evidence_age_ms,
            command.deadline_at_ms,
        )
        research_id = f"{command.request_id}-research"
        verification_id = f"{command.request_id}-verify"
        try:
            candidate, _research_receipt = self._research.research(
                research_id,
                bundle,
                budget,
                now_ms=now_ms,
                cancelled=False,
            )
            report, _verification_receipt = self._research.verify(
                verification_id,
                candidate,
                bundle,
                budget,
                now_ms=now_ms,
                cancelled=False,
            )
        except (
            research_v1.ResearchCellsV1Error,
            research_v1.ResearchCellsV1ContractError,
            research_v1.ResearchCellsV1Denied,
        ) as exc:
            raise UnifiedCommandRouterV1Denied(
                "research pipeline denied command"
            ) from exc
        finalized: FinalizedResearchV1 | None = None
        ready = report.decision is VerificationDecisionV1.ACCEPT
        if ready:
            try:
                finalized = self._research.finalize(research_id, verification_id)
            except (
                research_v1.ResearchCellsV1Error,
                research_v1.ResearchCellsV1ContractError,
                research_v1.ResearchCellsV1Denied,
            ) as exc:
                raise UnifiedCommandRouterV1Denied(
                    "research finalization denied command"
                ) from exc
        return CommandPlanV1(
            status=(
                CommandPlanStatusV1.READY if ready else CommandPlanStatusV1.BLOCKED
            ),
            reason=(
                "research_verified_accept" if ready else "research_verifier_blocked"
            ),
            request_id=command.request_id,
            intent=command.intent,
            workspace_id=command.workspace_id,
            identity_digest=command.identity.digest,
            command_digest=command.digest,
            component_root_digest=self._component_root_digest,
            provider_route_plan=None,
            research_bundle_digest=bundle.digest,
            verification_report_digest=report.digest,
            verification_decision=report.decision,
            finalized_research=finalized,
            mcp_request=None,
            tool_name=None,
            rationale_codes=tuple(
                sorted(
                    {
                        "evidence_authenticated",
                        "identity_bound",
                        "independent_verifier",
                        "provider_free",
                    }
                )
            ),
        )

    def _receipt(self, command: UserCommandV1, plan: CommandPlanV1) -> CommandReceiptV1:
        unsigned = {
            "schema": "OnyxCommandReceipt.v1",
            "request_id": command.request_id,
            "workspace_id": command.workspace_id,
            "identity_digest": command.identity.digest,
            "command_digest": command.digest,
            "plan_digest": plan.digest,
            "status": plan.status.value,
            "intent": plan.intent.value,
            "reason": plan.reason,
            "provider_route_digest": plan.provider_route_digest,
            "finalized_research_digest": plan.finalized_research_digest,
            "mcp_request_digest": plan.mcp_request_digest,
            "component_root_digest": self._component_root_digest,
        }
        tag = hmac.new(
            self._receipt_key, _canonical(unsigned), hashlib.sha256
        ).hexdigest()
        return CommandReceiptV1(
            request_id=command.request_id,
            workspace_id=command.workspace_id,
            identity_digest=command.identity.digest,
            command_digest=command.digest,
            plan_digest=plan.digest,
            status=plan.status,
            intent=plan.intent,
            reason=plan.reason,
            provider_route_digest=plan.provider_route_digest,
            finalized_research_digest=plan.finalized_research_digest,
            mcp_request_digest=plan.mcp_request_digest,
            component_root_digest=self._component_root_digest,
            authentication_tag=tag,
        )

    def attest_receipt(self, plan: CommandPlanV1, receipt: CommandReceiptV1) -> None:
        self._attest()
        if type(plan) is not CommandPlanV1 or type(receipt) is not CommandReceiptV1:
            raise UnifiedCommandRouterV1ContractError(
                "exact plan and receipt are required"
            )
        expected = (
            receipt.request_id == plan.request_id
            and receipt.workspace_id == plan.workspace_id
            and receipt.identity_digest == plan.identity_digest
            and receipt.command_digest == plan.command_digest
            and receipt.plan_digest == plan.digest
            and receipt.status is plan.status
            and receipt.intent is plan.intent
            and receipt.reason == plan.reason
            and receipt.provider_route_digest == plan.provider_route_digest
            and receipt.finalized_research_digest == plan.finalized_research_digest
            and receipt.mcp_request_digest == plan.mcp_request_digest
            and receipt.component_root_digest == self._component_root_digest
        )
        expected_tag = hmac.new(
            self._receipt_key,
            _canonical(receipt.unsigned_payload()),
            hashlib.sha256,
        ).hexdigest()
        if not expected or not hmac.compare_digest(
            receipt.authentication_tag, expected_tag
        ):
            raise UnifiedCommandRouterV1Denied("forged command receipt denied")

    def plan(
        self, command: UserCommandV1, *, now_ms: int
    ) -> tuple[CommandPlanV1, CommandReceiptV1]:
        if type(command) is not UserCommandV1:
            raise UnifiedCommandRouterV1ContractError("exact UserCommandV1 is required")
        _require_int(now_ms, "now_ms", 0, _MAX_TIME)
        with self._lock:
            self._hard_gate(command, now_ms=now_ms)
            self._attest()
            prior = self._replays.get(command.request_id)
            if prior is not None:
                if not hmac.compare_digest(prior[0], command.digest):
                    raise UnifiedCommandRouterV1Conflict(
                        "request identity is bound to different input"
                    )
                self.attest_receipt(prior[1], prior[2])
                return prior[1], prior[2]
            if command.intent is CommandIntentV1.LOCAL_CATALOG:
                plan = self._route_catalog(command)
            elif command.intent is CommandIntentV1.RESEARCH_VERIFY:
                plan = self._route_research(command, now_ms=now_ms)
            else:
                plan = self._route_text(command, now_ms=now_ms)
            receipt = self._receipt(command, plan)
            self.attest_receipt(plan, receipt)
            self._replays[command.request_id] = (command.digest, plan, receipt)
            return plan, receipt


def create_unified_command_router_v1(
    *,
    gate: UnifiedCommandRouterFeatureGateV1,
    core: AgenticCoreV6 | None = None,
    provider_registry: ProviderRegistryV1 | None = None,
    research_pipeline: ResearchVerifierPipelineV1 | None = None,
    local_mcp_identity: LocalMCPIdentityV1 | None = None,
    live_integration: Phase6LiveIntegrationV2 | None = None,
    project_root: Path | str | None = None,
    receipt_authentication_key: bytes = b"",
) -> UnifiedCommandRouterV1 | None:
    if type(gate) is not UnifiedCommandRouterFeatureGateV1:
        raise UnifiedCommandRouterV1ContractError(
            "exact router feature gate is required"
        )
    if not gate.enabled:
        return None
    if (
        type(core) is not _AGENTIC_CORE_TYPE
        or type(provider_registry) is not _PROVIDER_REGISTRY_TYPE
        or type(research_pipeline) is not _RESEARCH_PIPELINE_TYPE
        or type(local_mcp_identity) is not _LOCAL_IDENTITY_TYPE
        or type(live_integration) is not _LIVE_INTEGRATION_TYPE
        or project_root is None
    ):
        raise UnifiedCommandRouterV1ContractError(
            "enabled router requires exact component dependencies"
        )
    root = Path(project_root)
    if not root.is_absolute():
        raise UnifiedCommandRouterV1ContractError(
            "explicit absolute project root is required"
        )
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnifiedCommandRouterV1ContractError(
            "project root is unavailable"
        ) from exc
    if not root.is_dir() or root.is_symlink():
        raise UnifiedCommandRouterV1ContractError(
            "project root must be a regular directory"
        )
    return UnifiedCommandRouterV1(
        _key=_CONSTRUCTION_KEY,
        core=core,
        registry=provider_registry,
        research=research_pipeline,
        local_identity=local_mcp_identity,
        live=live_integration,
        project_root=root,
        receipt_authentication_key=receipt_authentication_key,
    )


__all__ = [
    "CANDIDATE",
    "COMPONENT_ACCEPTANCE_ROOTS",
    "FEATURE_FLAG",
    "ZERO_DIGEST",
    "CommandBudgetV1",
    "CommandIntentV1",
    "CommandPlanStatusV1",
    "CommandPlanV1",
    "CommandReceiptV1",
    "UnifiedCommandRouterFeatureGateV1",
    "UnifiedCommandRouterV1",
    "UnifiedCommandRouterV1Conflict",
    "UnifiedCommandRouterV1ContractError",
    "UnifiedCommandRouterV1Denied",
    "UnifiedCommandRouterV1Error",
    "UserCommandV1",
    "create_unified_command_router_v1",
]
