"""Default-off Founder Snapshot V17 activation over exact Governance V16."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import secrets
import subprocess
import threading
import time
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import domain_ledger
from core import founder_snapshot_live_v1 as founder
from core import onyx_live_activation_v16 as v16
from core import permission_broker
from core.artifact_service import (
    ArtifactRecord,
    ArtifactService,
    _authorize_root_for_testing,
)
from core.control_plane import ControlPlaneStore
from core.domain_ledger import DomainLedgerRepository
from core.external_agent_adapter_v1 import ExternalAgentUnavailable
from core.governance_nucleus_v1 import (
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
    create_governance_nucleus_v1,
)
from core.native_vault import NativeSecretVault, SecretReference
from core.phase7_approved_sources_v1 import (
    ApprovedSourceRegistryV1,
    ApprovedSourceSpecV1,
    ApprovedSourceFeatureGateV1,
    SourceScoresV1,
    create_approved_source_registry_v1,
)
from core.phase7_company_graph_v1 import (
    CompanyGraphAssertionV1,
    CompanyGraphFeatureGateV1,
    GraphEvidenceBindingV1,
    create_company_graph_projector_v1,
)
from core.phase7_founder_command_v1 import (
    FounderCommandFeatureGateV1,
    create_founder_command_generator_v1,
)
from core.phase7_workspace_aliases_v1 import (
    ArtifactAliasSpecV1,
    WorkspaceAliasCatalogV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1
from core.portable_host_capability_v1 import (
    PortableHostBindingsV1,
    PortableHostCapabilityV1Error,
    require_portable_host_bindings_v1,
)
from core.workspaces import WorkspaceRegistry, WorkspaceUnknown


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V17"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V17"
FEATURE_FLAG: Final = "ONYX_FOUNDER_SNAPSHOT_LIVE_V1"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v16.CONTROL_FLAGS,
)
HOST_MARKER: Final = "_founder_activation_v17"
TOOL_NAME: Final = "founder_brief_read"
FOUNDER_SMOKE_ARGUMENT: Final = "--founder-smoke-test"
FOUNDER_SMOKE_OUTPUT_ENV: Final = "ONYX_FOUNDER_SMOKE_OUTPUT"
FOUNDER_SMOKE_CORPUS_ENV: Final = "ONYX_FOUNDER_SMOKE_CORPUS_ROOT"
FOUNDER_SMOKE_FAILURE_EXIT: Final = 83
_PROTECTED_SEAMS: Final = (
    "_start_phase5_session",
    "_stop_phase5_session",
    "_execute_tool",
)
_ACTIVE_HOST_OWNER: tuple["OnyxLiveActivationV17", object] | None = None
_ACTIVE_HOST_LOCK = threading.RLock()
_FOUNDER_SMOKE_ALIAS: Final = "founder-smoke-corpus-v17"
_SUCCESSOR_AUTHORITY_SEAL = object()


class FounderSuccessorAuthoritiesV17:
    """Opaque exact V17 authority handoff for a reviewed live successor."""

    __slots__ = (
        "identity",
        "workspace_root",
        "nucleus",
        "store",
        "aliases",
        "sources",
        "integrity_key",
    )

    def __init__(
        self,
        seal: object,
        *,
        identity: GovernanceIdentityV1,
        workspace_root: Path,
        nucleus: GovernanceNucleusV1,
        store: ControlPlaneStore,
        aliases: WorkspaceAliasCatalogV1,
        sources: ApprovedSourceRegistryV1,
        integrity_key: bytes,
    ) -> None:
        if (
            seal is not _SUCCESSOR_AUTHORITY_SEAL
            or type(identity) is not GovernanceIdentityV1
            or type(nucleus) is not GovernanceNucleusV1
            or type(store) is not ControlPlaneStore
            or type(aliases) is not WorkspaceAliasCatalogV1
            or type(sources) is not ApprovedSourceRegistryV1
            or type(integrity_key) is not bytes
            or len(integrity_key) != 32
            or nucleus.identity != identity
            or aliases.workspace_id != identity.workspace_id
            or aliases.principal_id != identity.principal_id
            or sources.workspace_id != identity.workspace_id
            or sources.principal_id != identity.principal_id
        ):
            raise ActivationV17Error("V17 successor authority binding drift")
        self.identity = identity
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        self.nucleus = nucleus
        self.store = store
        self.aliases = aliases
        self.sources = sources
        self.integrity_key = integrity_key

    def __reduce__(self) -> object:
        raise TypeError("FounderSuccessorAuthoritiesV17 cannot be serialized")


def _public_artifact_citation_v17(alias_name: str, digest: str) -> str:
    """Return an active-workspace alias reference without internal identity."""

    return f"onyx-artifact://v1/alias/{alias_name}/sha256/{digest}"


def tool_declaration_v17() -> dict[str, object]:
    """Return the closed model declaration; identity and roots are host-owned."""

    return {
        "name": TOOL_NAME,
        "description": (
            "Read a cited, provider-free daily or weekly Founder Brief from one "
            "approved manifest inside the active workspace."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "cadence": {
                    "type": "STRING",
                    "enum": ["daily", "weekly"],
                },
                "manifest_ref": {
                    "type": "STRING",
                    "description": (
                        "Relative approved manifest reference inside the active "
                        "workspace Founder Snapshot root."
                    ),
                },
            },
            "required": ["cadence", "manifest_ref"],
        },
    }


class ActivationV17Error(RuntimeError):
    """The exact V17 activation contract could not be installed."""


class ActivationV17PlatformDenied(ActivationV17Error):
    """Active Founder Snapshot V17 requires its accepted Windows boundary."""


class FounderSmokePlatformRefusalV17(ActivationV17PlatformDenied):
    """Founder smoke cannot run without the accepted Windows boundaries."""


class FounderSmokeExecutionErrorV17(ActivationV17Error):
    """Redacted Founder smoke failure with observed isolation counters."""

    def __init__(
        self,
        error_type: str,
        *,
        network_calls: int,
        provider_calls: int,
        process_calls: int,
    ) -> None:
        super().__init__("Founder smoke failed safely")
        self.error_type = error_type
        self.network_calls = network_calls
        self.provider_calls = provider_calls
        self.process_calls = process_calls


def _require_founder_host_boundary_v17(
    portable_bindings: object | None,
    *,
    stage: str,
) -> None:
    if os.name == "nt":
        if portable_bindings is not None:
            raise ActivationV17PlatformDenied(
                "portable bindings are invalid on Windows"
            )
        return
    try:
        bindings = require_portable_host_bindings_v1(portable_bindings, stage=stage)
    except PortableHostCapabilityV1Error as exc:
        raise ActivationV17PlatformDenied(
            "founder_snapshot_host_boundary_denied"
        ) from exc
    if bindings.governance_descriptor_io is not True:
        raise ActivationV17PlatformDenied(
            "founder_snapshot_v16_descriptor_governance_unavailable"
        )


class _FounderSmokeIsolationV17:
    """Install network, provider, and child-process counters before V17."""

    def __init__(self, module: ModuleType) -> None:
        self._base = v16._GovernanceSmokeIsolationV1(module)
        self._real_popen = subprocess.Popen
        self._real_system = os.system
        self._real_startfile = getattr(os, "startfile", None)
        self.process_calls = 0
        self._installed = False

    @property
    def network_calls(self) -> int:
        return self._base.network_calls

    @property
    def provider_calls(self) -> int:
        return self._base.provider_calls

    def _deny_process(self, *_args: object, **_kwargs: object) -> object:
        self.process_calls += 1
        raise ActivationV17Error("Founder smoke child process refused")

    def install(self) -> None:
        if self._installed:
            raise ActivationV17Error("Founder smoke isolation already installed")
        self._base.install()
        try:
            subprocess.Popen = self._deny_process  # type: ignore[assignment]
            os.system = self._deny_process  # type: ignore[assignment]
            if self._real_startfile is not None:
                os.startfile = self._deny_process  # type: ignore[attr-defined,assignment]
        except BaseException:
            self._base.close()
            raise
        self._installed = True

    def close(self) -> None:
        if not self._installed:
            return
        subprocess.Popen = self._real_popen
        os.system = self._real_system
        if self._real_startfile is not None:
            os.startfile = self._real_startfile  # type: ignore[attr-defined]
        self._installed = False
        self._base.close()


class FounderCommitLeaseV17:
    """Atomic cancellation-versus-commit permit shared with the async host."""

    __slots__ = ("_lock", "_state")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = "open"

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def cancel(self) -> bool:
        """Return true only when cancellation wins before commit permission."""

        with self._lock:
            if self._state == "open":
                self._state = "cancelled"
                return True
            return False

    def permit_commit(self) -> None:
        """Atomically cross the point after which completion must be reconciled."""

        with self._lock:
            if self._state == "cancelled":
                raise founder.FounderSnapshotV1Denied(
                    "Founder Brief cancelled before commit permission"
                )
            if self._state == "open":
                self._state = "commit-permitted"
                return
            if self._state != "commit-permitted":
                raise ActivationV17Error("Founder commit lease is no longer active")

    def complete(self) -> None:
        with self._lock:
            if self._state == "commit-permitted":
                self._state = "completed"
            elif self._state == "open":
                self._state = "completed-without-commit"


def _workspace_id_for_root(root: Path) -> str:
    canonical = os.path.normcase(str(root.resolve(strict=True)))
    return "workspace-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _verified_vault_key(vault: NativeSecretVault) -> bytes:
    key = vault.get_bytes()
    if key is None:
        expected = secrets.token_bytes(32)
        vault.set_bytes(expected)
        key = vault.get_bytes()
        if type(key) is not bytes or not hmac.compare_digest(key, expected):
            raise ActivationV17Error(
                "Founder Snapshot native key write verification failed"
            )
    if type(key) is not bytes or len(key) != 32:
        raise ActivationV17Error("Founder Snapshot native key is invalid")
    return key


def _verified_receipt_vault_state(vault: NativeSecretVault) -> bytes:
    """Initialize a receipt key or preserve its authenticated persisted state."""

    state = vault.get_bytes()
    if state is None:
        return _verified_vault_key(vault)
    if type(state) is not bytes or len(state) < 32:
        raise ActivationV17Error("Founder Snapshot native receipt state is invalid")
    return state


class FounderBriefControllerV17:
    """Host-owned read-only adapter from Governance V16 to Founder Snapshot V1."""

    __slots__ = (
        "identity",
        "workspace_root",
        "snapshot_root",
        "_nucleus",
        "_snapshot",
        "_store",
        "_closed",
    )

    def __init__(
        self,
        *,
        identity: GovernanceIdentityV1,
        workspace_root: Path,
        nucleus: GovernanceNucleusV1,
        snapshot: founder.FounderSnapshotLiveV1,
        store: ControlPlaneStore,
    ) -> None:
        if (
            type(identity) is not GovernanceIdentityV1
            or type(nucleus) is not GovernanceNucleusV1
            or type(snapshot) is not founder.FounderSnapshotLiveV1
            or type(store) is not ControlPlaneStore
        ):
            raise ActivationV17Error("exact Founder controller bindings are required")
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir() or _workspace_id_for_root(root) != identity.workspace_id:
            raise ActivationV17Error("active Founder workspace binding is invalid")
        if nucleus.identity != identity:
            raise ActivationV17Error("Founder governance identity binding drift")
        self.identity = identity
        self.workspace_root = root
        self.snapshot_root = snapshot.root.resolve(strict=True)
        if not self.snapshot_root.is_relative_to(root):
            raise ActivationV17Error("Founder snapshot root escapes active workspace")
        self._nucleus = nucleus
        self._snapshot = snapshot
        self._store = store
        self._closed = False

    @classmethod
    def from_live_host(
        cls,
        instance: object,
        workspace_roots: Sequence[str | os.PathLike[str]],
        *,
        portable_bindings: PortableHostBindingsV1 | None = None,
        trusted_directory_factory: object | None = None,
    ) -> "FounderBriefControllerV17":
        _require_founder_host_boundary_v17(
            portable_bindings,
            stage="founder_controller",
        )
        if trusted_directory_factory is not None and not callable(
            trusted_directory_factory
        ):
            raise ActivationV17Error(
                "Founder trusted-directory factory must be callable"
            )
        nucleus = getattr(instance, "_governance_nucleus_v1", None)
        if type(nucleus) is not GovernanceNucleusV1:
            raise ActivationV17Error("Governance V16 nucleus is unavailable")
        identity = nucleus.identity
        roots = tuple(Path(value).resolve(strict=True) for value in workspace_roots)
        matches = tuple(
            root
            for root in roots
            if _workspace_id_for_root(root) == identity.workspace_id
        )
        if len(matches) != 1:
            raise ActivationV17Error("Governance workspace root is not uniquely bound")
        workspace_root = matches[0]
        record = next(
            (
                item
                for item in nucleus.workspace_records
                if item.workspace_id == identity.workspace_id
            ),
            None,
        )
        if (
            record is None
            or record.status != "active"
            or record.display_name != identity.workspace_display
        ):
            raise ActivationV17Error(
                "active Governance workspace record is unavailable"
            )

        snapshot_root = workspace_root / ".onyx" / "founder-snapshot-v1"
        if os.name == "nt":
            snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            try:
                sealed = require_portable_host_bindings_v1(
                    portable_bindings,
                    stage="founder_controller",
                )
                if trusted_directory_factory is not sealed.trusted_directory_factory:
                    raise PortableHostCapabilityV1Error(
                        "portable founder directory factory drift"
                    )
                snapshot_boundary = sealed.trusted_directory_factory(
                    root=snapshot_root,
                    enabled=True,
                )
                snapshot_boundary.close()
            except PortableHostCapabilityV1Error as exc:
                raise ActivationV17PlatformDenied(
                    "founder_snapshot_host_boundary_denied"
                ) from exc
        store = ControlPlaneStore(enabled=True).initialize()
        try:
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                workspace = registry.get(identity.workspace_id)
            except WorkspaceUnknown:
                workspace = registry.register(
                    identity.workspace_id,
                    display_name=identity.workspace_display,
                    workspace_class=record.workspace_class,
                )
            if (
                workspace.status != "active"
                or workspace.display_name != identity.workspace_display
                or workspace.workspace_class != record.workspace_class
            ):
                raise ActivationV17Error(
                    "Founder control-plane workspace binding drift"
                )

            suffix = identity.workspace_id.removeprefix("workspace-")
            integrity_vault = NativeSecretVault(
                SecretReference(
                    "CyryxLabs.Onyx.FounderSnapshot",
                    f"integrity-{suffix}",
                    "Onyx Founder Snapshot approved-source integrity key",
                )
            )
            integrity_key = _verified_vault_key(integrity_vault)
            aliases = create_workspace_alias_catalog_v1(
                gate=WorkspaceAliasFeatureGateV1(True),
                registry=registry,
                workspace_id=identity.workspace_id,
                principal_id=identity.principal_id,
                integrity_key=integrity_key,
            )
            if aliases is None:
                raise ActivationV17Error(
                    "Founder workspace alias catalog is unavailable"
                )
            sources = create_approved_source_registry_v1(
                gate=ApprovedSourceFeatureGateV1(True),
                registry=registry,
                aliases=aliases,
                workspace_id=identity.workspace_id,
                principal_id=identity.principal_id,
                integrity_key=integrity_key,
            )
            if sources is None:
                raise ActivationV17Error(
                    "Founder approved-source registry is unavailable"
                )
            ledger = DomainLedgerRepository(
                registry, identity.workspace_id, enabled=True
            ).initialize()
            projector = create_company_graph_projector_v1(
                gate=CompanyGraphFeatureGateV1(True),
                sources=sources,
                ledger=ledger,
            )
            if projector is None:
                raise ActivationV17Error("Founder company graph is unavailable")
            generator = create_founder_command_generator_v1(
                gate=FounderCommandFeatureGateV1(True),
                projector=projector,
            )
            if generator is None:
                raise ActivationV17Error("Founder Brief generator is unavailable")
            receipt_vault = NativeSecretVault(
                SecretReference(
                    "CyryxLabs.Onyx.FounderSnapshot",
                    f"receipt-{suffix}",
                    "Onyx Founder Snapshot manifest receipt key",
                )
            )
            _verified_receipt_vault_state(receipt_vault)
            snapshot = founder.FounderSnapshotLiveV1(
                identity=identity,
                root=snapshot_root,
                sources=sources,
                projector=projector,
                generator=generator,
                vault=receipt_vault,
                enabled=True,
                trusted_directory_factory=trusted_directory_factory,
            )
            return cls(
                identity=identity,
                workspace_root=workspace_root,
                nucleus=nucleus,
                snapshot=snapshot,
                store=store,
            )
        except BaseException:
            store.close()
            raise

    @property
    def available(self) -> bool:
        return not self._closed

    def successor_authorities_v17(self) -> FounderSuccessorAuthoritiesV17:
        """Return one sealed host-only authority handoff after full reattestation."""

        if self._closed:
            raise ActivationV17Error("Founder controller is closed")
        sources = getattr(self._snapshot, "_sources", None)
        aliases = getattr(sources, "_aliases", None)
        integrity_key = getattr(sources, "_integrity_key", None)
        if (
            type(sources) is not ApprovedSourceRegistryV1
            or type(aliases) is not WorkspaceAliasCatalogV1
            or type(integrity_key) is not bytes
            or len(integrity_key) != 32
        ):
            raise ActivationV17Error("V17 successor authority is unavailable")
        sources._attest()
        aliases._attest()
        if (
            self._nucleus.identity != self.identity
            or not self._store.is_open
            or sources.registry.store is not self._store
        ):
            raise ActivationV17Error("V17 successor authority binding drift")
        return FounderSuccessorAuthoritiesV17(
            _SUCCESSOR_AUTHORITY_SEAL,
            identity=self.identity,
            workspace_root=self.workspace_root,
            nucleus=self._nucleus,
            store=self._store,
            aliases=aliases,
            sources=sources,
            integrity_key=integrity_key,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._snapshot.close()
        finally:
            self._store.close()

    def _public_result(
        self, result: founder.FounderSnapshotResultV1
    ) -> dict[str, object]:
        brief = result.brief
        sources = getattr(self._snapshot, "_sources", None)
        citation_map = (
            {
                source.citation: _public_artifact_citation_v17(
                    source.artifact_alias_name,
                    source.artifact_sha256,
                )
                for source in sources.list(
                    now_ms=brief.generated_at_ms,
                    allowed_sensitivities=("public", "internal", "confidential"),
                )
                if source.locator_kind == "artifact_alias"
                and source.artifact_alias_name is not None
                and source.artifact_sha256 is not None
            }
            if sources is not None
            else {}
        )

        def public_citations(values: tuple[str, ...]) -> list[str]:
            return [citation_map.get(value, value) for value in values]

        citations = sorted(
            {
                citation_map.get(citation, citation)
                for item in brief.items
                for citation in item.citations
            }
            | {
                citation_map.get(citation, citation)
                for action in brief.recommended_top_actions
                for citation in action.citations
            }
        )
        items = [
            {
                "project": item.project_name,
                "subject": item.subject_name,
                "owner": item.owner,
                "status": item.status,
                "blockers": list(item.blockers),
                "next_milestone": item.next_milestone,
                "definition_of_done": item.definition_of_done,
                "verification_status": item.verification_status,
                "citations": public_citations(item.citations),
            }
            for item in brief.items
        ]
        actions = [
            {
                "title": item.title,
                "evidence_class": item.evidence_class,
                "known_context": item.known_context,
                "inference": item.inference,
                "unknowns": list(item.unknowns),
                "recommended_action": item.recommended_action,
                "verification_method": item.verification_method,
                "completion_evidence": item.completion_evidence,
                "downside": item.downside,
                "citations": public_citations(item.citations),
            }
            for item in brief.recommended_top_actions
        ]
        opportunities = [
            {
                "title": item.title,
                "evidence_class": item.evidence_class,
                "known_context": item.known_context,
                "inference": item.inference,
                "unknowns": list(item.unknowns),
                "recommended_action": item.recommended_action,
                "verification_method": item.verification_method,
                "completion_evidence": item.completion_evidence,
                "downside": item.downside,
                "citations": public_citations(item.citations),
            }
            for item in brief.revenue_opportunities
        ]
        item_by_claim = {
            item.claim_id: public for item, public in zip(brief.items, items)
        }
        portfolio = [
            {
                "project": item.project_name,
                "claims": len(item.claim_ids),
                "status_items": len(item.status_claim_ids),
                "blockers": len(item.blocker_claim_ids),
                "dependencies": len(item.dependency_claim_ids),
                "risks": len(item.risk_claim_ids),
                "decisions": len(item.decision_claim_ids),
                "stale": len(item.stale_claim_ids),
            }
            for item in brief.portfolio
        ]
        blockers = [item_by_claim[value] for value in brief.critical_blocker_claim_ids]
        decisions = [item_by_claim[value] for value in brief.decision_queue_claim_ids]
        risks = [item_by_claim[value] for value in brief.risk_register_claim_ids]
        public: dict[str, object] = {
            "status": "completed",
            "cadence": result.cadence,
            "generated_at_ms": brief.generated_at_ms,
            "read_only": True,
            "content_trust": "untrusted_data",
            "summary": {
                "portfolio_projects": len(brief.portfolio),
                "critical_blockers": len(brief.critical_blocker_claim_ids),
                "decisions": len(brief.decision_queue_claim_ids),
                "risks": len(brief.risk_register_claim_ids),
                "abstentions": list(brief.abstentions),
            },
            "items": items,
            "portfolio": portfolio,
            "blockers": blockers,
            "decisions": decisions,
            "opportunities": opportunities,
            "risks": risks,
            "top3": actions,
            "delta": {
                "baseline": brief.delta.baseline,
                "has_previous": brief.delta.previous_brief_sha256 is not None,
                "added": len(brief.delta.added_claim_ids),
                "removed": len(brief.delta.removed_claim_ids),
                "changed_subjects": list(brief.delta.changed_subjects),
            },
            "recommended_actions": actions,
            "citations": citations,
        }
        serialized = repr(public)
        forbidden = (
            self.identity.principal_id,
            self.identity.workspace_id,
            self.identity.account_id,
            self.identity.profile_id,
            str(self.workspace_root),
            str(self.snapshot_root),
        )
        if any(value and value in serialized for value in forbidden):
            raise ActivationV17Error("Founder Brief public redaction failed")
        return public

    def execute(
        self,
        arguments: Mapping[str, object],
        *,
        commit_lease: FounderCommitLeaseV17 | None = None,
    ) -> dict[str, object]:
        if self._closed:
            raise ActivationV17Error("Founder Brief controller is closed")
        if type(arguments) is not dict or set(arguments) != {"cadence", "manifest_ref"}:
            raise ActivationV17Error("Founder Brief arguments are not exact")
        cadence = arguments.get("cadence")
        manifest_ref = arguments.get("manifest_ref")
        if cadence not in founder.CADENCES or type(manifest_ref) is not str:
            raise ActivationV17Error("Founder Brief request is invalid")
        reference = manifest_ref.replace("\\", "/")
        path = Path(reference)
        if (
            not reference
            or reference != manifest_ref
            or path.is_absolute()
            or ".." in path.parts
            or not reference.endswith(".json")
        ):
            raise ActivationV17Error("Founder manifest reference is invalid")
        if self._nucleus.killed:
            raise ActivationV17Error("Founder Brief denied by global kill")
        authenticated = self._snapshot.preflight_manifest(reference)
        if authenticated.cadence != cadence:
            raise ActivationV17Error("Founder manifest cadence does not match request")
        lease = FounderCommitLeaseV17() if commit_lease is None else commit_lease
        if type(lease) is not FounderCommitLeaseV17:
            raise ActivationV17Error("exact Founder commit lease is required")
        try:

            @contextmanager
            def commit_fence():
                with self._nucleus.local_commit_fence():
                    lease.permit_commit()
                    yield

            result = self._snapshot.generate(
                reference,
                preflight=authenticated,
                commit_guard=commit_fence,
            )
        finally:
            lease.complete()
        if self._nucleus.killed:
            raise ActivationV17Error("Founder Brief result suppressed by global kill")
        return self._public_result(result)


@dataclass(frozen=True, slots=True)
class ActivationFlagsV17:
    master: bool
    founder_snapshot: bool
    base: v16.ActivationFlagsV16

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.founder_snapshot is not True
            or type(self.base) is not v16.ActivationFlagsV16
        ):
            raise ActivationV17Error("complete exact V17 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV17":
        source = os.environ if environ is None else environ
        endpoint_options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV17Error("rollback is not an active V17 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV17Error("activation environment is not canonical V17")
        try:
            base = v16.ActivationFlagsV16.from_canonical_environ(
                restore_v16_environment(source),
                **endpoint_options,
            )
        except v16.ActivationV16Error as exc:
            raise ActivationV17Error("V16 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v16_options: Any,
) -> dict[str, str]:
    result = v16.exact_activation_environment(workspace_roots, **v16_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v16_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV17:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v16.HostContractV16


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    platform_guard: object | None = None,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV17:
    source = os.environ if environ is None else environ
    if os.name != "nt":
        if platform_guard is not None:
            raise ActivationV17PlatformDenied(
                "arbitrary portable host bindings are denied"
            )
        _require_founder_host_boundary_v17(
            portable_bindings,
            stage="founder_preflight",
        )
        assert portable_bindings is not None
        if runtime_endpoint_factory not in (
            None,
            portable_bindings.runtime_endpoint_factory,
        ):
            raise ActivationV17PlatformDenied(
                "arbitrary portable runtime endpoint factory is denied"
            )
        runtime_endpoint_factory = portable_bindings.runtime_endpoint_factory
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV17.from_canonical_environ(
        source,
        **endpoint_options,
    )
    try:
        base = v16.preflight_host(
            module,
            restore_v16_environment(source),
            portable_bindings=portable_bindings,
            **endpoint_options,
        )
    except v16.ActivationV16Error as exc:
        raise ActivationV17Error("V16 host contract is unavailable") from exc
    onyx_live = getattr(module, "OnyxLive", None)
    if not isinstance(onyx_live, type):
        raise ActivationV17Error("V17 OnyxLive contract is unavailable")
    if hasattr(onyx_live, HOST_MARKER):
        raise ActivationV17Error("V17 official host extension already exists")
    return HostContractV17(module, onyx_live, base.project, base)


class OnyxLiveActivationV17:
    """One official post-init marker over the exact accepted V16 host."""

    BASE_SEAM_COUNT = v16.OnyxLiveActivationV16.TOTAL_SEAM_COUNT
    V17_SEAM_COUNT = 3
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V17_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV17,
        contract: HostContractV17,
        *,
        founder_factory: object | None = None,
        platform_guard: object | None = None,
        trusted_directory_factory: object | None = None,
        portable_bindings: PortableHostBindingsV1 | None = None,
        **v16_options: Any,
    ) -> None:
        if (
            type(flags) is not ActivationFlagsV17
            or type(contract) is not HostContractV17
        ):
            raise ActivationV17Error("exact V17 flags and contract are required")
        if os.name != "nt":
            if platform_guard is not None:
                raise ActivationV17PlatformDenied(
                    "arbitrary portable founder bindings are denied"
                )
            try:
                bindings = require_portable_host_bindings_v1(
                    portable_bindings,
                    stage="founder_controller",
                )
            except PortableHostCapabilityV1Error as exc:
                raise ActivationV17PlatformDenied(
                    "founder_snapshot_host_boundary_denied"
                ) from exc
            if bindings.governance_descriptor_io is not True:
                raise ActivationV17PlatformDenied(
                    "founder_snapshot_v16_descriptor_governance_unavailable"
                )
            if trusted_directory_factory not in (
                None,
                bindings.trusted_directory_factory,
            ):
                raise ActivationV17PlatformDenied(
                    "arbitrary portable founder directory is denied"
                )
            trusted_directory_factory = bindings.trusted_directory_factory
        self.flags = flags
        self.contract = contract
        self._base = v16.OnyxLiveActivationV16(
            flags.base,
            contract.base,
            portable_bindings=(bindings if os.name != "nt" else None),
            **v16_options,
        )
        if founder_factory is not None and not callable(founder_factory):
            raise ActivationV17Error("Founder controller factory must be callable")
        if platform_guard is not None and not callable(platform_guard):
            raise ActivationV17Error("Founder platform guard must be callable")
        if trusted_directory_factory is not None and not callable(
            trusted_directory_factory
        ):
            raise ActivationV17Error(
                "Founder trusted-directory factory must be callable"
            )
        self._founder_factory = founder_factory
        self._portable_bindings = bindings if os.name != "nt" else None
        self._trusted_directory_factory = trusted_directory_factory
        self._installed = False
        self._declaration: dict[str, object] | None = None
        self._policy_existed = False
        self._policy_value: str | None = None
        self._policy_captured = False
        self._controllers: list[FounderBriefControllerV17] = []
        self._instances: list[object] = []

    @property
    def executable_capability(self) -> str:
        return self._base.executable_capability

    @property
    def away_capability(self) -> str:
        return self._base.away_capability

    @property
    def external_agent_capability(self) -> str:
        return self._base.external_agent_capability

    @property
    def governance_capability(self) -> str:
        return self._base.governance_capability

    @property
    def founder_brief_capability(self) -> str:
        return "available_read_only" if self._installed else "inactive"

    def _create_controller(self, instance: object) -> FounderBriefControllerV17:
        if self._founder_factory is not None:
            value = self._founder_factory(
                instance, self.flags.base.base.workspace_roots
            )
            if type(value) is not FounderBriefControllerV17:
                raise ActivationV17Error(
                    "Founder factory returned the wrong concrete type"
                )
            return value
        return FounderBriefControllerV17.from_live_host(
            instance,
            self.flags.base.base.workspace_roots,
            portable_bindings=self._portable_bindings,
            trusted_directory_factory=self._trusted_directory_factory,
        )

    def initialize_host(self, instance: object) -> None:
        """Official post-init attach, invoked by the unwrapped host constructor."""

        global _ACTIVE_HOST_OWNER
        if not self._installed:
            raise ActivationV17Error("V17 activation is not installed")
        nucleus = getattr(instance, "_governance_nucleus_v1", None)
        if type(nucleus) is not GovernanceNucleusV1:
            raise ActivationV17Error("V16 governance must precede Founder V17")
        with _ACTIVE_HOST_LOCK:
            if _ACTIVE_HOST_OWNER is not None:
                raise ActivationV17Error(
                    "another V17 live host already owns Founder Brief"
                )
            _ACTIVE_HOST_OWNER = (self, instance)
        try:
            if hasattr(instance, "_founder_brief_controller_v17"):
                raise ActivationV17Error("Founder controller already exists")
            controller = self._create_controller(instance)
            setattr(instance, "_founder_brief_controller_v17", controller)
            self._controllers.append(controller)
            self._instances.append(instance)
        except BaseException:
            with _ACTIVE_HOST_LOCK:
                if _ACTIVE_HOST_OWNER == (self, instance):
                    _ACTIVE_HOST_OWNER = None
            raise

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV17Error("seam failpoint is outside V17 installation")
        base_failpoint = (
            fail_after
            if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT
            else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v16_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return
        protected_after_base = tuple(
            getattr(self.contract.onyx_live, name) for name in _PROTECTED_SEAMS
        )
        try:
            declaration = tool_declaration_v17()
            declarations = getattr(self.contract.module, "TOOL_DECLARATIONS", None)
            if not isinstance(declarations, list):
                raise ActivationV17Error("V17 tool declaration host is unavailable")
            if any(
                isinstance(item, dict) and item.get("name") == TOOL_NAME
                for item in declarations
            ):
                raise ActivationV17Error("Founder Brief declaration already exists")
            declarations.append(declaration)
            self._declaration = declaration
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV17Error("injected V17 declaration failure")

            self._policy_existed = TOOL_NAME in permission_broker.MODEL_TOOL_POLICIES
            self._policy_value = permission_broker.MODEL_TOOL_POLICIES.get(TOOL_NAME)
            self._policy_captured = True
            if self._policy_existed and self._policy_value != "always_confirm":
                raise ActivationV17Error("Founder Brief permission policy drift")
            permission_broker.MODEL_TOOL_POLICIES[TOOL_NAME] = "always_confirm"
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV17Error("injected V17 policy failure")

            setattr(self.contract.onyx_live, HOST_MARKER, self)
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV17Error("injected V17 marker failure")
            protected_after = tuple(
                getattr(self.contract.onyx_live, name) for name in _PROTECTED_SEAMS
            )
            if protected_after != protected_after_base:
                raise ActivationV17Error("V17 altered a protected host seam")
            self._installed = True
        except BaseException:
            self.rollback_to_v16()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV17Error("V17 activation is not installed")
        instance = self._base.instantiate_live(ui)
        controller = getattr(instance, "_founder_brief_controller_v17", None)
        if type(controller) is not FounderBriefControllerV17:
            raise ActivationV17Error("Founder controller did not reach live host")
        return instance

    def rollback_to_v16(self) -> None:
        global _ACTIVE_HOST_OWNER
        errors: list[BaseException] = []
        for controller in tuple(self._controllers):
            try:
                controller.close()
            except BaseException as exc:
                errors.append(exc)
        self._controllers.clear()
        for instance in tuple(self._instances):
            if getattr(instance, "_founder_brief_controller_v17", None) is not None:
                try:
                    delattr(instance, "_founder_brief_controller_v17")
                except BaseException as exc:
                    errors.append(exc)
        self._instances.clear()
        with _ACTIVE_HOST_LOCK:
            if _ACTIVE_HOST_OWNER is not None and _ACTIVE_HOST_OWNER[0] is self:
                _ACTIVE_HOST_OWNER = None
        marker = getattr(self.contract.onyx_live, HOST_MARKER, None)
        if marker is self:
            delattr(self.contract.onyx_live, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV17Error("V17 rollback extension drift"))
        declarations = getattr(self.contract.module, "TOOL_DECLARATIONS", None)
        if isinstance(declarations, list) and self._declaration is not None:
            declarations[:] = [
                item for item in declarations if item is not self._declaration
            ]
        self._declaration = None
        if self._policy_captured:
            if self._policy_existed:
                assert self._policy_value is not None
                permission_broker.MODEL_TOOL_POLICIES[TOOL_NAME] = self._policy_value
            else:
                permission_broker.MODEL_TOOL_POLICIES.pop(TOOL_NAME, None)
        self._policy_existed = False
        self._policy_value = None
        self._policy_captured = False
        if getattr(self.contract.module, "_onyx_live_activation_v17", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v17")
        self._installed = False
        if errors:
            raise ActivationV17Error("V17 rollback completed with errors") from errors[
                0
            ]

    def rollback_all(self) -> None:
        """V17 rollback deliberately preserves the accepted live V16 base."""
        self.rollback_to_v16()


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    platform_guard: object | None = None,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v16_options: Any,
) -> OnyxLiveActivationV17:
    source = os.environ if environ is None else environ
    if os.name != "nt":
        if platform_guard is not None or runtime_endpoint_factory is not None:
            raise ActivationV17PlatformDenied(
                "arbitrary portable host bindings are denied"
            )
        try:
            sealed = require_portable_host_bindings_v1(
                portable_bindings,
                stage="founder_preflight",
            )
        except PortableHostCapabilityV1Error as exc:
            raise ActivationV17PlatformDenied(
                "founder_snapshot_host_boundary_denied"
            ) from exc
        runtime_endpoint_factory = sealed.runtime_endpoint_factory
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV17(
        ActivationFlagsV17.from_canonical_environ(
            source,
            **endpoint_options,
        ),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **endpoint_options,
        ),
        portable_bindings=portable_bindings,
        **v16_options,
    )
    controller.install()
    module._onyx_live_activation_v17 = controller
    return controller


def _founder_smoke_paths_v17() -> tuple[Path, Path, Path, Path]:
    """Resolve explicit isolated data, workspace, corpus, and output roots."""

    from core.paths import data_root

    raw_data = os.environ.get("ONYX_DATA_DIR", "").strip()
    raw_corpus = os.environ.get(FOUNDER_SMOKE_CORPUS_ENV, "").strip()
    raw_output = os.environ.get(FOUNDER_SMOKE_OUTPUT_ENV, "").strip()
    if not raw_data or not raw_corpus or not raw_output:
        raise ActivationV17Error("explicit isolated Founder smoke roots are required")
    data = data_root().resolve(strict=True)
    corpus = Path(raw_corpus).resolve(strict=True)
    output = Path(raw_output).resolve()
    flags = ActivationFlagsV17.from_canonical_environ(os.environ)
    workspaces = tuple(
        Path(value).resolve(strict=True) for value in flags.base.base.workspace_roots
    )
    if len(workspaces) != 1:
        raise ActivationV17Error("Founder smoke requires one isolated workspace")
    workspace = workspaces[0]
    if (
        workspace == data
        or corpus == data
        or not workspace.is_relative_to(data)
        or not corpus.is_relative_to(data)
        or output.parent != data
        or workspace == corpus
    ):
        raise ActivationV17Error("Founder smoke roots must remain isolated")
    output.parent.mkdir(parents=True, exist_ok=True)
    return data, workspace, corpus, output


def _write_founder_smoke_failure_output_v17(
    error: BaseException,
    output: Path,
) -> None:
    try:
        payload: dict[str, object] = {
            "contract": "OnyxFounderSmoke.v1",
            "status": "failed",
            "error_type": getattr(error, "error_type", type(error).__name__),
        }
        network = getattr(error, "network_calls", None)
        provider = getattr(error, "provider_calls", None)
        process = getattr(error, "process_calls", None)
        if type(network) is int and type(provider) is int and type(process) is int:
            payload["network_calls"] = network
            payload["provider_calls"] = provider
            payload["process_calls"] = process
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(output)
    except Exception:
        return


def write_founder_smoke_failure_v17(error: BaseException) -> None:
    """Persist a bounded failure without exception text or private paths."""

    try:
        _data, _workspace, _corpus, output = _founder_smoke_paths_v17()
    except Exception:
        return
    _write_founder_smoke_failure_output_v17(error, output)


def _founder_smoke_manifest_v17(
    controller: FounderBriefControllerV17,
    *,
    cadence: str,
    generated_at_ms: int,
    source: object,
    assertion: CompanyGraphAssertionV1,
) -> dict[str, object]:
    identity = controller.identity
    return {
        "schema": founder.MANIFEST_SCHEMA,
        "cadence": cadence,
        "workspace_id": identity.workspace_id,
        "principal_id": identity.principal_id,
        "governance_identity": asdict(identity),
        "identity_sha256": founder._identity_digest(identity),
        "generated_at_ms": generated_at_ms,
        "allowed_sensitivities": ["internal"],
        "sources": [
            {
                "source_name": source.source_name,
                "source_id": source.source_id,
                "source_identity_sha256": source.source_identity_sha256,
                "citation": source.citation,
            }
        ],
        "assertions": [asdict(assertion)],
    }


def _prepare_founder_smoke_corpus_v17(
    controller: FounderBriefControllerV17,
    *,
    corpus: Path,
    artifact_root: Path,
    now_ms: int,
) -> tuple[
    object,
    CompanyGraphAssertionV1,
    dict[str, object],
    ArtifactService,
    ArtifactRecord,
]:
    """Publish one content-addressed local source through accepted V17 APIs."""

    source_path = Path(__file__).resolve(strict=True)
    source_bytes = source_path.read_bytes()
    if not source_bytes or len(source_bytes) > 1_000_000:
        raise ActivationV17Error("Founder smoke source bytes are invalid")
    digest = hashlib.sha256(source_bytes).hexdigest()
    relative = "onyx-live-activation-v17.py"
    boundary = WindowsTrustedDirectoryV1(root=corpus, enabled=True)
    try:
        with boundary.session() as session:
            session.publish_create(relative, source_bytes)
            observed = session.read(relative, max_bytes=1_000_000)
    finally:
        boundary.close()
    if not hmac.compare_digest(hashlib.sha256(observed).hexdigest(), digest):
        raise ActivationV17Error("Founder smoke corpus digest changed")

    artifact_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    capability = _authorize_root_for_testing(
        artifact_root,
        allowlisted_roots=(artifact_root,),
        workspace_id=controller.identity.workspace_id,
    )
    artifact_service = ArtifactService(
        capability,
        workspace_id=controller.identity.workspace_id,
        enabled=True,
        max_bytes=1_000_000,
    )
    try:
        artifact = artifact_service.publish_bytes(
            source_bytes,
            media_type="text/x-python",
            data_class="internal",
            source_provenance={
                "kind": "founder_smoke_corpus",
                "sha256": digest,
            },
            display_name=relative,
        )
    except BaseException:
        artifact_service.close()
        raise
    if (
        artifact.sha256 != digest
        or artifact.size != len(source_bytes)
        or not hmac.compare_digest(
            hashlib.sha256(artifact_service.read(artifact)).hexdigest(),
            digest,
        )
    ):
        artifact_service.close()
        raise ActivationV17Error("Founder smoke artifact bytes changed")

    snapshot = controller._snapshot
    sources = snapshot._sources
    projector = snapshot._projector
    if sources is None or projector is None:
        artifact_service.close()
        raise ActivationV17Error("Founder smoke source authorities are unavailable")
    aliases = sources._aliases
    connection = controller._store._require_connection()
    try:
        connection.execute(
            "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
            (
                artifact.artifact_id,
                artifact.workspace_id,
                artifact.schema_version,
                artifact.sha256,
                artifact.relative_path,
                artifact.media_type,
                artifact.status,
                artifact.created_at,
            ),
        )
        alias = aliases.register(
            _FOUNDER_SMOKE_ALIAS,
            ArtifactAliasSpecV1(
                artifact_id=artifact.artifact_id,
                sha256=artifact.sha256,
                relative_path=artifact.relative_path,
                media_type=artifact.media_type,
            ),
            now_ms=now_ms,
        )
    except BaseException:
        artifact_service.close()
        raise
    citation = alias.locator
    source = sources.register(
        "onyx-v17-local-corpus",
        ApprovedSourceSpecV1(
            source_kind="technical_specification",
            authority="authoritative_primary",
            rights="owner_created",
            sensitivity="internal",
            locator_kind="artifact_alias",
            locator=citation,
            citation=citation,
            diversity_group="cyryx-onyx-local",
            scores=SourceScoresV1(
                expertise_bp=9_000,
                primary_evidence_bp=10_000,
                editorial_quality_bp=8_000,
                recency_bp=10_000,
                correction_history_bp=7_000,
                incentive_independence_bp=5_000,
                corroboration_bp=5_000,
                relevance_bp=10_000,
            ),
            valid_from_ms=now_ms,
            valid_until_ms=now_ms + 3_600_000,
            fresh_until_ms=now_ms + 3_600_000,
            artifact_alias_name=_FOUNDER_SMOKE_ALIAS,
        ),
        now_ms=now_ms,
    )
    ledger = projector._ledger
    excerpt = (
        "Local Cyryx Onyx V17 source artifact contains "
        f"{len(source_bytes)} bytes with SHA-256 {digest}."
    )
    evidence = ledger.record_evidence(
        "founder-smoke-source-v17",
        "founder-smoke-v17",
        "artifact",
        citation,
        excerpt,
        credibility_bp=source.credibility_bp,
        freshness="current",
        validity_seconds=3_600,
        access_license_note=source.access_license_note,
        artifact_id=artifact.artifact_id,
    )
    caller_key = "founder-smoke-claim-v17"
    claim_id = domain_ledger._entity_id("claim", ledger.workspace_id, caller_key)
    assertion = CompanyGraphAssertionV1(
        claim_id=claim_id,
        semantic="current_status",
        project_id="onyx",
        project_name="Onyx",
        subject_id="founder-snapshot-v17",
        subject_name="Founder Snapshot V17 local source",
        owner="Cyryx Labs",
        status="in_progress",
        blockers=(),
        next_milestone="Execute the packaged Founder smoke on this source digest.",
        definition_of_done=(
            "The packaged smoke reports the same digest with zero provider, "
            "network, and child-process calls."
        ),
        last_verified_ms=now_ms,
        evidence=(
            GraphEvidenceBindingV1(
                evidence.evidence_id,
                source.source_name,
                excerpt,
            ),
        ),
    )
    claim = ledger.record_claim(
        caller_key,
        "founder-smoke-v17",
        assertion.canonical_statement(),
        (evidence.evidence_id,),
        claim_kind="fact",
        confidence_bp=9_000,
        verification_status="supported",
        validity_seconds=3_600,
    )
    if claim.claim_id != assertion.claim_id:
        raise ActivationV17Error("Founder smoke claim identity changed")
    return (
        source,
        assertion,
        {
            "bytes": len(source_bytes),
            "sha256": digest,
            "alias": _FOUNDER_SMOKE_ALIAS,
            "citation": _public_artifact_citation_v17(
                _FOUNDER_SMOKE_ALIAS,
                digest,
            ),
            "content_trust": "untrusted_data",
        },
        artifact_service,
        artifact,
    )


def _run_founder_smoke_windows_v17(
    module: ModuleType,
    *,
    data: Path,
    workspace: Path,
    corpus: Path,
    output: Path,
    isolation: object,
    **v16_options: Any,
) -> dict[str, object]:
    if type(isolation) is not _FounderSmokeIsolationV17:
        raise ActivationV17Error("exact Founder smoke isolation is required")
    flags = ActivationFlagsV17.from_canonical_environ(os.environ)
    identity, records = v16.governance_workspace_bindings_v1(
        flags.base.base.workspace_roots
    )
    governance_vaults = v16._governance_smoke_native_vaults_v1(data)
    ledger_path = data / "founder-smoke-v1" / "governance.sqlite3"

    def nucleus_factory() -> GovernanceNucleusV1:
        return create_governance_nucleus_v1(
            path=ledger_path,
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            account_id=identity.account_id,
            profile_id=identity.profile_id,
            workspace_display=identity.workspace_display,
            key_vault=governance_vaults[0],
            head_vault=governance_vaults[1],
            pending_vault=governance_vaults[2],
            require_windows_boundary=True,
            workspace_records=records,
        )

    trusted_calls: list[str] = []

    def trusted(request: dict[str, object]) -> object:
        digest = request.get("digest")
        if type(digest) is str:
            trusted_calls.append(digest)
        return digest

    if "external_agent_factory" in v16_options:
        raise ActivationV17Error("Founder smoke owns external-agent isolation")

    def external_agent_unavailable(**_binding: object) -> object:
        raise ExternalAgentUnavailable("founder_smoke_process_isolation")

    controller = OnyxLiveActivationV17(
        flags,
        preflight_host(module, os.environ),
        nucleus_factory=nucleus_factory,
        external_agent_factory=external_agent_unavailable,
        **v16_options,
    )
    controller._base._base.external_agent_capability = (
        "health_only:founder_smoke_process_isolation"
    )
    permission_broker.set_permission_callback(trusted)
    instance: object | None = None
    reopened: FounderBriefControllerV17 | None = None
    artifact_service: ArtifactService | None = None
    original_memory_dir = getattr(module, "memory_dir")
    original_runtime_dir = getattr(module, "runtime_dir")
    from core import control_plane as control_plane_module
    from core import paths as paths_module

    original_paths_control_plane_runtime = (
        paths_module.private_control_plane_runtime_dir
    )
    original_control_plane_runtime = (
        control_plane_module.private_control_plane_runtime_dir
    )
    control_plane_runtime = data / "runtime" / "control-plane-smoke-v1"
    founder_vaults = (
        NativeSecretVault(
            SecretReference(
                "CyryxLabs.Onyx.FounderSnapshot",
                f"integrity-{identity.workspace_id.removeprefix('workspace-')}",
                "Onyx Founder Snapshot approved-source integrity key",
            )
        ),
        NativeSecretVault(
            SecretReference(
                "CyryxLabs.Onyx.FounderSnapshot",
                f"receipt-{identity.workspace_id.removeprefix('workspace-')}",
                "Onyx Founder Snapshot manifest receipt key",
            )
        ),
    )
    try:
        controller.install()
        module.memory_dir = lambda: data / "memory"
        module.runtime_dir = lambda: data / "runtime"
        # Frozen hosts enable the production Control Plane. Keep the Founder
        # diagnostic provider-free and disposable by redirecting both the
        # canonical path function and the direct binding imported by
        # ``core.control_plane`` before the live host is instantiated. This is
        # the same two-reference boundary used by the native-startup smoke.
        paths_module.private_control_plane_runtime_dir = lambda: control_plane_runtime
        control_plane_module.private_control_plane_runtime_dir = lambda: (
            control_plane_runtime
        )
        instance = controller.instantiate_live(v16._GovernanceSmokeUIV1())
        instance._start_phase5_session()
        nucleus = instance._governance_nucleus_v1
        founder_controller = instance._founder_brief_controller_v17
        if (
            type(nucleus) is not GovernanceNucleusV1
            or type(founder_controller) is not FounderBriefControllerV17
            or instance._phase5 is None
        ):
            raise ActivationV17Error("Founder smoke live host is incomplete")

        first = permission_broker.authorize_model_tool(
            "system_status",
            {"_governance_invocation_ref": "founder-smoke-grant-1"},
        )
        second = permission_broker.authorize_model_tool(
            "system_status",
            {"_governance_invocation_ref": "founder-smoke-grant-2"},
        )
        if not first[0] or first != second:
            raise ActivationV17Error("Founder smoke grant was not reused")

        # The assertion statement includes its verification timestamp while the
        # ledger assigns the claim creation timestamp during the subsequent
        # transaction.  Reserve a small real-clock window, then wait for that
        # timestamp before projection so both sides of the temporal contract
        # are true without replacing the production clock.
        now_ms = time.time_ns() // 1_000_000 + 2_000
        source, assertion, corpus_public, artifact_service, artifact = (
            _prepare_founder_smoke_corpus_v17(
                founder_controller,
                corpus=corpus,
                artifact_root=data / "artifacts",
                now_ms=now_ms,
            )
        )
        while time.time_ns() // 1_000_000 < now_ms + 3:
            time.sleep(0.01)

        def publish_and_execute(
            active: FounderBriefControllerV17,
            *,
            cadence: str,
            sequence: int,
        ) -> dict[str, object]:
            reference = f"inbox/{cadence}-{sequence}.json"
            active._snapshot.publish_manifest(
                reference,
                _founder_smoke_manifest_v17(
                    active,
                    cadence=cadence,
                    generated_at_ms=now_ms + sequence,
                    source=source,
                    assertion=assertion,
                ),
            )
            return active.execute({"cadence": cadence, "manifest_ref": reference})

        daily = publish_and_execute(
            founder_controller,
            cadence="daily",
            sequence=1,
        )
        weekly = publish_and_execute(
            founder_controller,
            cadence="weekly",
            sequence=2,
        )
        founder_controller.close()
        reopened = FounderBriefControllerV17.from_live_host(
            instance,
            flags.base.base.workspace_roots,
        )
        restart = publish_and_execute(
            reopened,
            cadence="daily",
            sequence=3,
        )
        if restart.get("delta", {}).get("baseline") is not False:
            raise ActivationV17Error("Founder daily delta did not survive restart")
        reopened_sources = reopened._snapshot._sources
        if reopened_sources is None:
            raise ActivationV17Error("Founder restarted sources are unavailable")
        reopened_alias = reopened_sources._aliases.get(
            kind="artifact",
            alias_name=_FOUNDER_SMOKE_ALIAS,
            now_ms=time.time_ns() // 1_000_000,
        )
        reopened_bytes = artifact_service.read(artifact)
        if (
            reopened_alias.artifact_id != artifact.artifact_id
            or reopened_alias.sha256 != corpus_public["sha256"]
            or reopened_alias.locator != source.locator
            or len(reopened_bytes) != corpus_public["bytes"]
            or not hmac.compare_digest(
                hashlib.sha256(reopened_bytes).hexdigest(),
                str(corpus_public["sha256"]),
            )
            or corpus_public["citation"] not in restart.get("citations", [])
        ):
            raise ActivationV17Error("Founder artifact alias restart binding changed")

        commit_lease = FounderCommitLeaseV17()
        commit_lease.permit_commit()
        commit_wins = commit_lease.cancel() is False
        commit_lease.complete()
        cancel_lease = FounderCommitLeaseV17()
        cancel_wins = cancel_lease.cancel()
        try:
            cancel_lease.permit_commit()
        except founder.FounderSnapshotV1Denied:
            pass
        else:
            cancel_wins = False

        with nucleus.local_commit_fence():
            commit_fence = True
        kill = nucleus.global_kill()
        try:
            with nucleus.local_commit_fence():
                pass
        except GovernanceV1Denied:
            kill_wins = True
        else:
            kill_wins = False
        if not all((commit_wins, cancel_wins, commit_fence, kill_wins)):
            raise ActivationV17Error("Founder commit/kill fences are incomplete")
        if trusted_calls:
            raise ActivationV17Error("Founder smoke requested trusted UI")

        payload: dict[str, object] = {
            "contract": "OnyxFounderSmoke.v1",
            "status": "passed",
            "corpus": corpus_public,
            "daily": daily,
            "weekly": weekly,
            "restart": restart,
            "grant_reused": True,
            "fences": {
                "cancel_wins": cancel_wins,
                "commit_wins": commit_wins,
                "kill_wins": kill_wins,
                "kill_latched": kill.get("mutations_frozen") is True,
                "source_gate": [
                    "test_local_commit_fence_kill_first_denies_without_mutation",
                    "test_local_commit_fence_commit_first_linearizes_before_kill",
                ],
            },
            "trusted_ui_prompts": len(trusted_calls),
            "network_calls": isolation.network_calls,
            "provider_calls": isolation.provider_calls,
            "process_calls": isolation.process_calls,
            "founder_brief": controller.founder_brief_capability,
            "governance": controller.governance_capability,
            "away": controller.away_capability,
            "external_agent": controller.external_agent_capability,
        }
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(output)
        return payload
    finally:
        module.memory_dir = original_memory_dir
        module.runtime_dir = original_runtime_dir
        try:
            if reopened is not None:
                reopened.close()
            if instance is not None:
                try:
                    instance._stop_phase5_session("founder-smoke-finished")
                except Exception:
                    pass
            try:
                controller.rollback_to_v16()
            finally:
                controller._base.rollback_all()
            permission_broker.set_permission_callback(None)
            if artifact_service is not None:
                artifact_service.close()
            for vault in (*founder_vaults, *governance_vaults):
                vault.delete()
        finally:
            paths_module.private_control_plane_runtime_dir = (
                original_paths_control_plane_runtime
            )
            control_plane_module.private_control_plane_runtime_dir = (
                original_control_plane_runtime
            )


def run_founder_smoke_v17(
    module: ModuleType,
    **v16_options: Any,
) -> dict[str, object]:
    """Run the provider-free V17 contract with isolation installed first."""

    if platform.system() != "Windows":
        raise FounderSmokePlatformRefusalV17("founder_snapshot_windows_required")
    data, workspace, corpus, output = _founder_smoke_paths_v17()
    isolation = _FounderSmokeIsolationV17(module)
    isolation.install()
    try:
        return _run_founder_smoke_windows_v17(
            module,
            data=data,
            workspace=workspace,
            corpus=corpus,
            output=output,
            isolation=isolation,
            **v16_options,
        )
    except FounderSmokeExecutionErrorV17:
        raise
    except BaseException as exc:
        failure = FounderSmokeExecutionErrorV17(
            type(exc).__name__,
            network_calls=isolation.network_calls,
            provider_calls=isolation.provider_calls,
            process_calls=isolation.process_calls,
        )
        # Controller rollback may intentionally restore the predecessor
        # environment before this boundary receives the failure. Preserve the
        # already-validated output authority instead of trying to resolve it
        # again from an environment that no longer owns the V17 smoke flags.
        _write_founder_smoke_failure_output_v17(failure, output)
        raise failure from exc
    finally:
        isolation.close()


__all__ = [
    "ActivationFlagsV17",
    "ActivationV17Error",
    "ActivationV17PlatformDenied",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "FOUNDER_SMOKE_ARGUMENT",
    "FOUNDER_SMOKE_CORPUS_ENV",
    "FOUNDER_SMOKE_FAILURE_EXIT",
    "FOUNDER_SMOKE_OUTPUT_ENV",
    "FounderSmokeExecutionErrorV17",
    "FounderSmokePlatformRefusalV17",
    "FounderBriefControllerV17",
    "FounderCommitLeaseV17",
    "FounderSuccessorAuthoritiesV17",
    "HOST_MARKER",
    "HostContractV17",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV17",
    "TOOL_NAME",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v16_environment",
    "run_founder_smoke_v17",
    "tool_declaration_v17",
    "write_founder_smoke_failure_v17",
]
