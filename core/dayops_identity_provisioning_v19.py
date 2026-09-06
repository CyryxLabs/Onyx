"""Identity-bound DayOps provisioning for the persistent V19 profile.

Unlike the legacy V14 CLI provisioner, this layer never creates or reclasses a
workspace.  It requires the already-active Governance V16 workspace and adds
only the DayOps integrity key and credential alias before committing the public
profile.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from pathlib import Path

from core import native_vault
from core.control_plane import ControlPlaneStore
from core.dayops_graph_factory_v1 import (
    DayOpsGraphBindingV1,
    integrity_key_reference_v1,
)
from core.dayops_profile_v19 import (
    DayOpsProfileStoreV19,
    DayOpsProfileV19,
    DayOpsProfileV19Error,
    DayOpsProfileV19Unavailable,
)
from core.dayops_provisioning_v14 import (
    INTEGRITY_KEY_BYTES,
    READ_ONLY_SCOPES,
    DayOpsProvisioningStatusV14,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    WorkspaceAliasRecordV1,
    WorkspaceAliasV1Conflict,
    WorkspaceAliasV1Denied,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    NativeGraphRefreshTokenVaultV1,
    RefreshTokenVaultV1,
)
from core.workspaces import WorkspaceError, WorkspaceRegistry


class DayOpsIdentityProvisioningV19Error(RuntimeError):
    pass


class DayOpsIdentityProvisioningV19ContractError(ValueError):
    pass


class DayOpsIdentityProvisioningV19Mismatch(DayOpsIdentityProvisioningV19Error):
    pass


def _credential_matches(
    credential: WorkspaceAliasRecordV1,
    profile: DayOpsProfileV19,
) -> bool:
    return (
        type(credential) is WorkspaceAliasRecordV1
        and credential.kind == "credential"
        and credential.provider == "microsoft-graph"
        and credential.alias_name == profile.credential_alias_name
        and (credential.account_id or "").casefold() == profile.account_id.casefold()
        and (credential.tenant_id or "").casefold() == profile.tenant_id.casefold()
        and tuple(credential.scopes) == READ_ONLY_SCOPES
    )


class DayOpsIdentityProvisionerV19:
    """Provision DayOps under an exact, pre-existing governance identity."""

    __slots__ = (
        "_identity",
        "_integrity_vault_factory",
        "_profile_store",
        "_project_root",
        "_refresh_vault_factory",
        "_store_factory",
    )

    def __init__(
        self,
        identity: GovernanceIdentityV1,
        profile_store: DayOpsProfileStoreV19,
        *,
        store_factory: Callable[[], ControlPlaneStore] | None = None,
        integrity_vault_factory: Callable[[DayOpsGraphBindingV1], object] | None = None,
        refresh_vault_factory: Callable[[WorkspaceAliasRecordV1], RefreshTokenVaultV1]
        | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        if type(identity) is not GovernanceIdentityV1:
            raise DayOpsIdentityProvisioningV19ContractError(
                "exact governance identity is required"
            )
        if (
            type(profile_store) is not DayOpsProfileStoreV19
            or profile_store.identity != identity
        ):
            raise DayOpsIdentityProvisioningV19ContractError(
                "identity-bound V19 profile store is required"
            )
        if store_factory is not None and not callable(store_factory):
            raise DayOpsIdentityProvisioningV19ContractError(
                "control store factory is invalid"
            )
        if integrity_vault_factory is not None and not callable(
            integrity_vault_factory
        ):
            raise DayOpsIdentityProvisioningV19ContractError(
                "integrity vault factory is invalid"
            )
        if refresh_vault_factory is not None and not callable(refresh_vault_factory):
            raise DayOpsIdentityProvisioningV19ContractError(
                "refresh vault factory is invalid"
            )
        self._identity = identity
        self._profile_store = profile_store
        self._store_factory = (
            (lambda: ControlPlaneStore(enabled=True))
            if store_factory is None
            else store_factory
        )
        self._integrity_vault_factory = (
            (
                lambda binding: native_vault.NativeSecretVault(
                    integrity_key_reference_v1(binding)
                )
            )
            if integrity_vault_factory is None
            else integrity_vault_factory
        )
        self._refresh_vault_factory = (
            NativeGraphRefreshTokenVaultV1
            if refresh_vault_factory is None
            else refresh_vault_factory
        )
        self._project_root = (
            Path(__file__).resolve().parents[1]
            if project_root is None
            else Path(project_root).resolve()
        )

    def _binding(self, profile: DayOpsProfileV19) -> DayOpsGraphBindingV1:
        return DayOpsGraphBindingV1(
            profile.workspace_id,
            profile.principal_id,
            profile.credential_alias_name,
            MicrosoftGraphLiveOnboardingV1(
                profile.client_id,
                profile.tenant_id,
                profile.account_id,
            ),
        )

    def prepare(
        self,
        profile: DayOpsProfileV19,
        *,
        now_ms: int,
    ) -> DayOpsProvisioningStatusV14:
        if (
            type(profile) is not DayOpsProfileV19
            or type(now_ms) is not int
            or now_ms < 0
        ):
            raise DayOpsIdentityProvisioningV19ContractError(
                "V19 provisioning input is invalid"
            )
        if (
            profile.workspace_id != self._identity.workspace_id
            or profile.principal_id != self._identity.principal_id
        ):
            raise DayOpsIdentityProvisioningV19Mismatch(
                "DayOps profile does not match the active identity"
            )
        binding = self._binding(profile)
        store = self._store_factory()
        if type(store) is not ControlPlaneStore:
            raise DayOpsIdentityProvisioningV19ContractError(
                "exact ControlPlaneStore factory is required"
            )
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            # This is deliberately require-only: V19 cannot create, rename, or
            # reclass the authoritative Governance V16 workspace.
            workspace = registry.require_active(self._identity.workspace_id)
            if workspace.workspace_id != self._identity.workspace_id:
                raise DayOpsIdentityProvisioningV19Mismatch(
                    "active workspace identity does not match"
                )
            vault = self._integrity_vault_factory(binding)
            if not callable(getattr(vault, "get_bytes", None)) or not callable(
                getattr(vault, "set_bytes", None)
            ):
                raise DayOpsIdentityProvisioningV19ContractError(
                    "integrity vault contract is invalid"
                )
            integrity_key = vault.get_bytes()
            if integrity_key is None:
                candidate = secrets.token_bytes(INTEGRITY_KEY_BYTES)
                vault.set_bytes(candidate)
                integrity_key = vault.get_bytes()
                if type(integrity_key) is not bytes or not hmac.compare_digest(
                    integrity_key, candidate
                ):
                    raise DayOpsIdentityProvisioningV19Error(
                        "DayOps integrity key write could not be verified"
                    )
            if (
                type(integrity_key) is not bytes
                or len(integrity_key) != INTEGRITY_KEY_BYTES
            ):
                raise DayOpsIdentityProvisioningV19Mismatch(
                    "DayOps integrity key is invalid"
                )
            catalog = create_workspace_alias_catalog_v1(
                gate=WorkspaceAliasFeatureGateV1(True),
                registry=registry,
                workspace_id=self._identity.workspace_id,
                principal_id=self._identity.principal_id,
                integrity_key=integrity_key,
                project_root=self._project_root,
            )
            if catalog is None:
                raise DayOpsIdentityProvisioningV19Error(
                    "DayOps credential catalog is unavailable"
                )
            try:
                credential = catalog.get(
                    kind="credential",
                    alias_name=profile.credential_alias_name,
                    now_ms=now_ms,
                )
            except WorkspaceAliasV1Denied:
                try:
                    credential = catalog.register(
                        profile.credential_alias_name,
                        CredentialAliasSpecV1(
                            provider="microsoft-graph",
                            account_id=profile.account_id,
                            tenant_id=profile.tenant_id,
                            scopes=READ_ONLY_SCOPES,
                        ),
                        now_ms=now_ms,
                    )
                except (WorkspaceAliasV1Conflict, WorkspaceAliasV1Denied) as exc:
                    raise DayOpsIdentityProvisioningV19Mismatch(
                        "DayOps credential alias has different immutable content"
                    ) from exc
            if not _credential_matches(credential, profile):
                raise DayOpsIdentityProvisioningV19Mismatch(
                    "DayOps credential alias does not match"
                )
            # Commit the public profile last so the persistent factory never
            # observes a profile whose workspace alias is not ready.
            self._profile_store.save(profile)
            refresh_vault = self._refresh_vault_factory(credential)
            if not callable(getattr(refresh_vault, "get_refresh_token", None)):
                raise DayOpsIdentityProvisioningV19ContractError(
                    "refresh vault contract is invalid"
                )
            connected = refresh_vault.get_refresh_token() is not None
            return DayOpsProvisioningStatusV14(
                "ready",
                "ready",
                "ready",
                "connected" if connected else "disconnected",
            )
        except WorkspaceError as exc:
            raise DayOpsIdentityProvisioningV19Mismatch(
                "active governance workspace is unavailable"
            ) from exc
        finally:
            store.close()

    def status(self, *, now_ms: int) -> DayOpsProvisioningStatusV14:
        """Return only redacted readiness markers; never credential material."""

        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsIdentityProvisioningV19ContractError("current time is invalid")
        try:
            profile = self._profile_store.load()
        except DayOpsProfileV19Unavailable:
            return DayOpsProvisioningStatusV14(
                "missing", "missing", "missing", "disconnected"
            )
        except DayOpsProfileV19Error:
            return DayOpsProvisioningStatusV14(
                "mismatch", "mismatch", "mismatch", "disconnected"
            )
        binding = self._binding(profile)
        store = self._store_factory()
        if type(store) is not ControlPlaneStore:
            raise DayOpsIdentityProvisioningV19ContractError(
                "exact ControlPlaneStore factory is required"
            )
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                workspace = registry.require_active(self._identity.workspace_id)
            except WorkspaceError:
                return DayOpsProvisioningStatusV14(
                    "missing", "missing", "missing", "disconnected"
                )
            if workspace.workspace_id != self._identity.workspace_id:
                return DayOpsProvisioningStatusV14(
                    "mismatch", "missing", "missing", "disconnected"
                )
            vault = self._integrity_vault_factory(binding)
            if not callable(getattr(vault, "get_bytes", None)):
                raise DayOpsIdentityProvisioningV19ContractError(
                    "integrity vault contract is invalid"
                )
            integrity_key = vault.get_bytes()
            if integrity_key is None:
                return DayOpsProvisioningStatusV14(
                    "ready", "missing", "missing", "disconnected"
                )
            if type(integrity_key) is not bytes or len(integrity_key) != 32:
                return DayOpsProvisioningStatusV14(
                    "ready", "mismatch", "missing", "disconnected"
                )
            catalog = create_workspace_alias_catalog_v1(
                gate=WorkspaceAliasFeatureGateV1(True),
                registry=registry,
                workspace_id=self._identity.workspace_id,
                principal_id=self._identity.principal_id,
                integrity_key=integrity_key,
                project_root=self._project_root,
            )
            if catalog is None:
                return DayOpsProvisioningStatusV14(
                    "ready", "ready", "missing", "disconnected"
                )
            try:
                credential = catalog.get(
                    kind="credential",
                    alias_name=profile.credential_alias_name,
                    now_ms=now_ms,
                )
            except WorkspaceAliasV1Denied:
                return DayOpsProvisioningStatusV14(
                    "ready", "ready", "missing", "disconnected"
                )
            if not _credential_matches(credential, profile):
                return DayOpsProvisioningStatusV14(
                    "ready", "ready", "mismatch", "disconnected"
                )
            refresh_vault = self._refresh_vault_factory(credential)
            if not callable(getattr(refresh_vault, "get_refresh_token", None)):
                raise DayOpsIdentityProvisioningV19ContractError(
                    "refresh vault contract is invalid"
                )
            connected = refresh_vault.get_refresh_token() is not None
            return DayOpsProvisioningStatusV14(
                "ready",
                "ready",
                "ready",
                "connected" if connected else "disconnected",
            )
        finally:
            store.close()


__all__ = [
    "DayOpsIdentityProvisionerV19",
    "DayOpsIdentityProvisioningV19ContractError",
    "DayOpsIdentityProvisioningV19Error",
    "DayOpsIdentityProvisioningV19Mismatch",
]
