"""Default-off additive Phase 6 planning authorities over installed Wiring V1.

V2 preserves every host seam installed by Wiring V1. It wraps only the V1
controller's private session factory/detach callables so each real Phase 5
session also owns the accepted Provider Registry, Research Cells, Unified
Command Router and disabled External-Agent descriptor. It performs no provider,
network, subprocess, MCP or live-host dispatch call.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    ModelDescriptorV1,
)
from core.phase6_disabled_external_agent_descriptor_v1 import (
    DisabledExternalAgentDescriptorCatalogV1,
    DisabledExternalAgentFeatureGateV1,
    ExternalAgentDescriptorIdentityV1,
    create_disabled_external_agent_descriptor_v1,
)
from core.phase6_local_mcp_v1 import LocalMCPIdentityV1
from core.phase6_provider_registry_v1 import (
    MAX_HEALTH_TTL_MS,
    ZERO_DIGEST,
    ProviderHealthStatusV1,
    ProviderRecordV1,
    ProviderRegistryFeatureGateV1,
    ProviderRegistryV1,
    create_provider_health_observation_v1,
    create_provider_registry_v1,
)
from core.phase6_research_cells_v1 import (
    ResearchCellsFeatureGateV1,
    ResearchVerifierPipelineV1,
    create_research_verifier_pipeline_v1,
)
from core.phase6_unified_command_router_v1 import (
    CommandPlanV1,
    CommandReceiptV1,
    UnifiedCommandRouterFeatureGateV1,
    UnifiedCommandRouterV1,
    UserCommandV1,
    create_unified_command_router_v1,
)
from core.phase6_live_wiring_v1 import (
    LiveWiringSessionV1,
    Phase6LiveWiringV1,
)


FEATURE_FLAG: Final = "ONYX_PHASE6_LIVE_WIRING_V2"
SESSION_ATTRIBUTE: Final = "_phase6_live_wiring_v2_session"
CANDIDATE: Final = "phase6-live-wiring-v2-candidate-001"
SCHEMA_VERSION: Final = 2
_CONSTRUCTION_KEY = object()
_RLOCK_TYPE = type(threading.RLock())
_MISSING = object()

COMPONENT_ACCEPTANCE_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json",
        "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee",
    ),
    (
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md",
        "51c542420b55f58409fba1b9a5efe753fb9aabdfebd1bc5e3ab2b9abf1f15dd7",
    ),
    (
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "8e4f139033bd8450a7f4c3c325363e57166bb7d0de3d5f5e6baf4f6817e8088c",
    ),
    (
        "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json",
        "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
    ),
    (
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.md",
        "ca7f0760723c4f6ad5d2a8716248c75c695e58cdb3e9b6917a3d027443aefabd",
    ),
    (
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
        "4a2c69076a1e6b07f606d30733b357f7c50c08193ff90a250d351637f0c0d070",
    ),
    (
        "docs/onyx/checkpoints/phase6-research-cells-v1/manifest.json",
        "216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab",
    ),
    (
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.md",
        "83d936789d1c4ce851b95fe71946161ee7bb0ecb5ae23a8b26de54b954284bec",
    ),
    (
        "docs/onyx/acceptance/VE-P6-RESEARCH-CELLS-V1-E6-001.manifest.json",
        "e6419ff154499b913e0e2dbb78b1f3918b32cc869cfd3def1b3566bb33cbb32c",
    ),
    (
        "docs/onyx/checkpoints/phase6-unified-command-router-v1/manifest.json",
        "e78d887f87922290e19e1427fa030e276152b14acb5a72be1c5b53cb645d7abe",
    ),
    (
        "docs/onyx/acceptance/VE-P6-UNIFIED-ROUTER-V1-C002-E6-001.md",
        "f00c5f42e346911d15d5b7c2a9a20783c6cb135fa3d56b0bfa0c257cd97ae5a2",
    ),
    (
        "docs/onyx/acceptance/VE-P6-UNIFIED-ROUTER-V1-C002-E6-001.manifest.json",
        "5381e06180b375fd3e5be256d9023b883937129dd260cd7656ea3f169f2311f3",
    ),
    (
        "docs/onyx/checkpoints/"
        "phase6-disabled-external-agent-descriptor-v1/manifest.json",
        "d0d356b808dfbb1996dd31c57cb9f9d95774a9c2d3ad7488d0a9bb81c4177293",
    ),
    (
        "docs/onyx/acceptance/VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.md",
        "efc8f6f62908fef1afb007981b8041f2e965b9eacf7ec9dd7d05496b128ba89d",
    ),
    (
        "docs/onyx/acceptance/"
        "VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.manifest.json",
        "b79642c665b481406d2ed6fb105903dfb799c656cfb707b24db33979f6b3ccef",
    ),
)


class Phase6LiveWiringV2Error(RuntimeError):
    """The V2 planning composition could not complete safely."""


class Phase6LiveWiringV2ContractError(ValueError):
    """A V2 input or predecessor contract was not exact."""


class Phase6LiveWiringV2Denied(PermissionError):
    """V2 authority, identity or rollback state diverged."""


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_component_roots(project_root: Path) -> str:
    rows: list[str] = []
    for relative, expected in COMPONENT_ACCEPTANCE_ROOTS:
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts:
            raise Phase6LiveWiringV2Denied("component path contract drift denied")
        try:
            path = (project_root / value).resolve(strict=True)
            path.relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise Phase6LiveWiringV2Denied("component root is unavailable") from exc
        if not path.is_file() or path.is_symlink():
            raise Phase6LiveWiringV2Denied("component root is not a regular file")
        actual = _sha_file(path)
        if not hmac.compare_digest(actual, expected):
            raise Phase6LiveWiringV2Denied("component acceptance drift denied")
        rows.append(f"{relative}\0{expected}\n")
    return hashlib.sha256("".join(rows).encode()).hexdigest()


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class LiveWiringV2FeatureGate:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6LiveWiringV2ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: dict[str, str] | os._Environ[str] | None = None
    ) -> "LiveWiringV2FeatureGate":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


class Phase6OperationalSessionV2:
    """One session-bound accepted planning composition; never an executor."""

    __slots__ = (
        "base_session",
        "provider_record",
        "provider_registry",
        "research_pipeline",
        "local_mcp_identity",
        "router",
        "external_descriptor",
        "component_root_digest",
        "_health_key",
        "_health_key_digest",
        "_health_sequence",
        "_health_digest",
        "_health_observed_at_ms",
        "_closed",
        "_lock",
    )

    def __init__(
        self,
        *,
        base_session: LiveWiringSessionV1,
        provider_record: ProviderRecordV1,
        provider_registry: ProviderRegistryV1,
        research_pipeline: ResearchVerifierPipelineV1,
        local_mcp_identity: LocalMCPIdentityV1,
        router: UnifiedCommandRouterV1,
        external_descriptor: DisabledExternalAgentDescriptorCatalogV1,
        component_root_digest: str,
        health_key: bytes,
    ) -> None:
        if (
            type(base_session) is not LiveWiringSessionV1
            or type(provider_record) is not ProviderRecordV1
            or type(provider_registry) is not ProviderRegistryV1
            or type(research_pipeline) is not ResearchVerifierPipelineV1
            or type(local_mcp_identity) is not LocalMCPIdentityV1
            or type(router) is not UnifiedCommandRouterV1
            or type(external_descriptor) is not DisabledExternalAgentDescriptorCatalogV1
            or type(health_key) is not bytes
            or len(health_key) != 32
            or type(component_root_digest) is not str
            or len(component_root_digest) != 64
        ):
            raise Phase6LiveWiringV2ContractError(
                "exact accepted V2 session dependencies are required"
            )
        self.base_session = base_session
        self.provider_record = provider_record
        self.provider_registry = provider_registry
        self.research_pipeline = research_pipeline
        self.local_mcp_identity = local_mcp_identity
        self.router = router
        self.external_descriptor = external_descriptor
        self.component_root_digest = component_root_digest
        self._health_key = health_key
        self._health_key_digest = _digest(health_key)
        self._health_sequence = 0
        self._health_digest = ZERO_DIGEST
        self._health_observed_at_ms = -1
        self._closed = False
        self._lock = threading.RLock()

    @property
    def closed(self) -> bool:
        return self._closed

    def _attest(self) -> None:
        if (
            type(self.base_session) is not LiveWiringSessionV1
            or type(self.provider_record) is not ProviderRecordV1
            or type(self.provider_registry) is not ProviderRegistryV1
            or type(self.research_pipeline) is not ResearchVerifierPipelineV1
            or type(self.local_mcp_identity) is not LocalMCPIdentityV1
            or type(self.router) is not UnifiedCommandRouterV1
            or type(self.external_descriptor)
            is not DisabledExternalAgentDescriptorCatalogV1
            or type(self._health_key) is not bytes
            or len(self._health_key) != 32
            or not hmac.compare_digest(
                _digest(self._health_key), self._health_key_digest
            )
            or type(self._closed) is not bool
            or type(self._lock) is not _RLOCK_TYPE
        ):
            raise Phase6LiveWiringV2Denied("operational session authority drift denied")

    def refresh_provider_health(
        self,
        *,
        now_ms: int,
        status: ProviderHealthStatusV1 = ProviderHealthStatusV1.AVAILABLE,
    ) -> str:
        with self._lock:
            self._attest()
            if self._closed:
                raise Phase6LiveWiringV2Denied("operational session is closed")
            if type(now_ms) is not int or now_ms <= self._health_observed_at_ms:
                raise Phase6LiveWiringV2ContractError(
                    "provider health time must be monotonic"
                )
            if type(status) is not ProviderHealthStatusV1:
                raise Phase6LiveWiringV2ContractError(
                    "provider health status must be exact"
                )
            observation = create_provider_health_observation_v1(
                adapter_id=self.provider_record.adapter_id,
                record_version=self.provider_record.record_version,
                sequence=self._health_sequence + 1,
                observed_at_ms=now_ms,
                expires_at_ms=now_ms + MAX_HEALTH_TTL_MS,
                status=status,
                previous_digest=self._health_digest,
                authentication_key=self._health_key,
            )
            result = self.provider_registry.observe_health(
                observation, received_at_ms=now_ms
            )
            self._health_sequence += 1
            self._health_digest = result
            self._health_observed_at_ms = now_ms
            return result

    def preview(
        self,
        command: UserCommandV1,
        *,
        now_ms: int,
        provider_connected: bool,
    ) -> tuple[CommandPlanV1, CommandReceiptV1]:
        self._attest()
        if type(provider_connected) is not bool:
            raise Phase6LiveWiringV2ContractError(
                "provider_connected must be exact bool"
            )
        status = (
            ProviderHealthStatusV1.AVAILABLE
            if provider_connected
            else ProviderHealthStatusV1.UNAVAILABLE
        )
        self.refresh_provider_health(now_ms=now_ms, status=status)
        return self.router.plan(command, now_ms=now_ms)

    def close(self) -> None:
        with self._lock:
            self._attest()
            self._closed = True


class Phase6LiveWiringV2:
    """Transactional controller-instance overlay preserving all host seams."""

    PATCHED_CONTROLLER_SEAMS = ("_create_session", "_detach_session")

    def __init__(
        self,
        *,
        _key: object,
        wiring_v1: Phase6LiveWiringV1,
        project_root: Path,
        model_id: str,
        component_root_digest: str,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LiveWiringV2ContractError("use create_phase6_live_wiring_v2")
        if (
            type(wiring_v1) is not Phase6LiveWiringV1
            or wiring_v1.installed is not True
            or not project_root.is_absolute()
            or not project_root.is_dir()
            or project_root.is_symlink()
            or type(model_id) is not str
            or not model_id.startswith("models/")
        ):
            raise Phase6LiveWiringV2ContractError(
                "exact installed Wiring V1 and model contract are required"
            )
        self._v1 = wiring_v1
        self._project_root = project_root
        self._model_id = model_id
        self._component_root_digest = component_root_digest
        self._originals = {
            name: getattr(wiring_v1, name) for name in self.PATCHED_CONTROLLER_SEAMS
        }
        self._instance_originals = {
            name: wiring_v1.__dict__.get(name, _MISSING)
            for name in self.PATCHED_CONTROLLER_SEAMS
        }
        self._installed_values: dict[str, object] = {}
        self._sessions: weakref.WeakKeyDictionary[
            object, Phase6OperationalSessionV2
        ] = weakref.WeakKeyDictionary()
        self._installed = False
        self._lock = threading.RLock()
        self._health_key = secrets.token_bytes(32)
        self._evidence_key = secrets.token_bytes(32)
        self._research_receipt_key = secrets.token_bytes(32)
        self._router_receipt_key = secrets.token_bytes(32)
        self._external_receipt_key = secrets.token_bytes(32)
        self._key_digests = tuple(
            _digest(value)
            for value in (
                self._health_key,
                self._evidence_key,
                self._research_receipt_key,
                self._router_receipt_key,
                self._external_receipt_key,
            )
        )
        self._attest()

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    @property
    def component_root_digest(self) -> str:
        return self._component_root_digest

    def _attest(self) -> None:
        if (
            type(self._v1) is not Phase6LiveWiringV1
            or self._v1.installed is not True
            or type(self._sessions) is not weakref.WeakKeyDictionary
            or type(self._lock) is not _RLOCK_TYPE
            or any(
                type(value) is not bytes or len(value) != 32
                for value in (
                    self._health_key,
                    self._evidence_key,
                    self._research_receipt_key,
                    self._router_receipt_key,
                    self._external_receipt_key,
                )
            )
            or tuple(
                _digest(value)
                for value in (
                    self._health_key,
                    self._evidence_key,
                    self._research_receipt_key,
                    self._router_receipt_key,
                    self._external_receipt_key,
                )
            )
            != self._key_digests
            or _verify_component_roots(self._project_root)
            != self._component_root_digest
        ):
            raise Phase6LiveWiringV2Denied("V2 authority drift denied")
        if self._installed:
            for name, expected in self._installed_values.items():
                if getattr(self._v1, name) is not expected:
                    raise Phase6LiveWiringV2Denied(
                        f"installed controller seam diverged: {name}"
                    )
        else:
            for name, expected in self._originals.items():
                if getattr(self._v1, name) != expected:
                    raise Phase6LiveWiringV2Denied(
                        f"Wiring V1 controller seam diverged: {name}"
                    )

    def _provider_record(self) -> ProviderRecordV1:
        identity = self._v1.identity
        prompt_path = self._project_root / "core" / "prompt.txt"
        if (
            prompt_path.is_symlink()
            or not prompt_path.is_file()
            or prompt_path.resolve().parent != (self._project_root / "core").resolve()
        ):
            raise Phase6LiveWiringV2Denied("provider prompt authority is unavailable")
        descriptor = ModelDescriptorV1(
            "gemini-live-v1beta",
            AdapterStatusV1.BLOCKED_BY_POLICY,
            ("text",),
            DataClassV1.INTERNAL,
            (identity.workspace_id,),
            False,
            True,
            True,
            0,
            3_600_000,
            1_000_000_000,
        )
        return ProviderRecordV1(
            "google-gemini",
            "v1beta",
            self._model_id,
            1,
            _digest(prompt_path.read_bytes()),
            _digest(
                b'{"schema":"OnyxProviderEvaluationMetadata.v1",'
                b'"status":"not_measured"}'
            ),
            descriptor,
        )

    def _restore_original_seams(self) -> None:
        for name, raw in self._instance_originals.items():
            if raw is _MISSING:
                if name in self._v1.__dict__:
                    delattr(self._v1, name)
            else:
                setattr(self._v1, name, raw)

    def _create_operational_session(
        self, base_session: LiveWiringSessionV1
    ) -> Phase6OperationalSessionV2:
        identity = self._v1.identity
        provider = self._provider_record()
        registry = create_provider_registry_v1(
            gate=ProviderRegistryFeatureGateV1(True),
            records=(provider,),
            health_authentication_key=self._health_key,
        )
        research = create_research_verifier_pipeline_v1(
            gate=ResearchCellsFeatureGateV1(True),
            core=base_session.facade._core,
            evidence_authority_key=self._evidence_key,
            receipt_authentication_key=self._research_receipt_key,
        )
        local_identity = LocalMCPIdentityV1(
            identity.workspace_id, identity.principal_id
        )
        router = create_unified_command_router_v1(
            gate=UnifiedCommandRouterFeatureGateV1(True),
            core=base_session.facade._core,
            provider_registry=registry,
            research_pipeline=research,
            local_mcp_identity=local_identity,
            live_integration=base_session.facade,
            project_root=self._project_root,
            receipt_authentication_key=self._router_receipt_key,
        )
        external = create_disabled_external_agent_descriptor_v1(
            gate=DisabledExternalAgentFeatureGateV1(True),
            identity=ExternalAgentDescriptorIdentityV1(
                "external-agent-disabled",
                "external-agent-provider",
                identity.workspace_id,
                identity.account_id,
                identity.profile_id,
                identity.principal_id,
            ),
            project_root=self._project_root,
            receipt_authentication_key=self._external_receipt_key,
        )
        if (
            type(registry) is not ProviderRegistryV1
            or type(research) is not ResearchVerifierPipelineV1
            or type(router) is not UnifiedCommandRouterV1
            or type(external) is not DisabledExternalAgentDescriptorCatalogV1
        ):
            raise Phase6LiveWiringV2Denied(
                "accepted Phase 6 factory closure is incomplete"
            )
        return Phase6OperationalSessionV2(
            base_session=base_session,
            provider_record=provider,
            provider_registry=registry,
            research_pipeline=research,
            local_mcp_identity=local_identity,
            router=router,
            external_descriptor=external,
            component_root_digest=self._component_root_digest,
            health_key=self._health_key,
        )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and (
            type(fail_after) is not int
            or not 0 <= fail_after <= len(self.PATCHED_CONTROLLER_SEAMS)
        ):
            raise Phase6LiveWiringV2ContractError(
                "V2 failpoint is outside the patch transaction"
            )
        with self._lock:
            if self._installed:
                raise Phase6LiveWiringV2Denied("V2 is already installed")
            self._attest()
            originals = self._originals
            controller = self

            def create_session(instance: object, bridge: object) -> LiveWiringSessionV1:
                controller._attest()
                base = originals["_create_session"](instance, bridge)
                operational: Phase6OperationalSessionV2 | None = None
                try:
                    if hasattr(instance, SESSION_ATTRIBUTE):
                        raise Phase6LiveWiringV2Denied("V2 session attribute collided")
                    operational = controller._create_operational_session(base)
                    setattr(instance, SESSION_ATTRIBUTE, operational)
                    controller._sessions[instance] = operational
                    return base
                except Exception:
                    if (
                        operational is not None
                        and getattr(instance, SESSION_ATTRIBUTE, _MISSING)
                        is operational
                    ):
                        delattr(instance, SESSION_ATTRIBUTE)
                    if operational is not None and not operational.closed:
                        operational.close()
                    base.close()
                    raise

            def detach_session(instance: object) -> LiveWiringSessionV1 | None:
                controller._attest()
                operational = controller._sessions.pop(instance, None)
                observed = getattr(instance, SESSION_ATTRIBUTE, _MISSING)
                drifted = (operational is None and observed is not _MISSING) or (
                    operational is not None and observed is not operational
                )
                if observed is not _MISSING:
                    delattr(instance, SESSION_ATTRIBUTE)
                if operational is not None:
                    operational.close()
                base = originals["_detach_session"](instance)
                if drifted:
                    if base is not None:
                        base.close()
                    raise Phase6LiveWiringV2Denied("V2 session attribute drift denied")
                return base

            installed = {
                "_create_session": create_session,
                "_detach_session": detach_session,
            }
            try:
                if fail_after == 0:
                    raise Phase6LiveWiringV2Error(
                        "injected V2 failure before first controller seam"
                    )
                for index, (name, value) in enumerate(installed.items(), start=1):
                    setattr(self._v1, name, value)
                    self._installed_values[name] = value
                    if fail_after == index:
                        raise Phase6LiveWiringV2Error(
                            f"injected V2 controller seam failure: {name}"
                        )
                self._installed = True
            except Exception:
                self._restore_original_seams()
                self._installed_values.clear()
                self._installed = False
                raise

    def session_for(self, instance: object) -> Phase6OperationalSessionV2 | None:
        with self._lock:
            self._attest()
            session = self._sessions.get(instance)
            if (
                session is not None
                and getattr(instance, SESSION_ATTRIBUTE, _MISSING) is not session
            ):
                raise Phase6LiveWiringV2Denied("V2 session projection drift denied")
            return session

    def rollback_installation(self) -> None:
        with self._lock:
            if not self._installed:
                return
            self._attest()
            for instance, session in list(self._sessions.items()):
                session.close()
                if hasattr(instance, SESSION_ATTRIBUTE):
                    delattr(instance, SESSION_ATTRIBUTE)
            self._sessions.clear()
            self._restore_original_seams()
            self._installed_values.clear()
            self._installed = False


def create_phase6_live_wiring_v2(
    *,
    gate: LiveWiringV2FeatureGate,
    wiring_v1: Phase6LiveWiringV1 | None = None,
    project_root: Path | str | None = None,
    model_id: str = "",
) -> Phase6LiveWiringV2 | None:
    if type(gate) is not LiveWiringV2FeatureGate:
        raise Phase6LiveWiringV2ContractError("exact V2 feature gate is required")
    if not gate.enabled:
        return None
    if type(wiring_v1) is not Phase6LiveWiringV1 or project_root is None:
        raise Phase6LiveWiringV2ContractError(
            "enabled V2 requires exact Wiring V1 and project root"
        )
    root = Path(project_root)
    if not root.is_absolute():
        raise Phase6LiveWiringV2ContractError(
            "explicit absolute project root is required"
        )
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Phase6LiveWiringV2ContractError("project root is unavailable") from exc
    component_root = _verify_component_roots(root)
    return Phase6LiveWiringV2(
        _key=_CONSTRUCTION_KEY,
        wiring_v1=wiring_v1,
        project_root=root,
        model_id=model_id,
        component_root_digest=component_root,
    )


__all__ = [
    "CANDIDATE",
    "COMPONENT_ACCEPTANCE_ROOTS",
    "FEATURE_FLAG",
    "SCHEMA_VERSION",
    "SESSION_ATTRIBUTE",
    "LiveWiringV2FeatureGate",
    "Phase6LiveWiringV2",
    "Phase6LiveWiringV2ContractError",
    "Phase6LiveWiringV2Denied",
    "Phase6LiveWiringV2Error",
    "Phase6OperationalSessionV2",
    "create_phase6_live_wiring_v2",
]
