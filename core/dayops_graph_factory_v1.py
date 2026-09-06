"""Canonical, deferred Microsoft Graph adapter factory for DayOps V1.

Construction is intentionally performed only when ``__call__`` is invoked by
the already-authorized host branch. Public onboarding identifiers come from
the accepted Phase 8 environment contract. Alias integrity and refresh tokens
remain in the native vault; neither is copied to environment variables, logs,
or model-visible values.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core import native_vault
from core.control_plane import ControlPlaneStore
from core.dayops_live_integration_v1 import (
    DayOpsAuthenticationRequiredV1,
    DayOpsConfigurationRequiredV1,
)
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasFeatureGateV1,
    WorkspaceAliasV1Denied,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    GraphLiveE2EV1Denied,
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_live_read_v1 import (
    GraphLiveReadFeatureGateV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    GraphOAuthFeatureGateV1,
    GraphOAuthHttpV1,
    RefreshTokenVaultV1,
    StdlibGraphOAuthHttpV1,
)
from core.graph_refresh_vault_v2 import NativeGraphRefreshTokenVaultV2
from core.phase8_microsoft_graph_oauth_v2 import (
    create_microsoft_graph_oauth_v2,
    create_microsoft_graph_live_read_transport_v2,
)
from core.phase8_microsoft_graph_read_v1 import (
    GraphReadFeatureGateV1,
    MicrosoftGraphReadAdapterV1,
    create_microsoft_graph_read_adapter_v1,
)
from core.workspaces import (
    WorkspaceError,
    WorkspaceRegistry,
)


WORKSPACE_ID_KEY: Final = "ONYX_DAYOPS_WORKSPACE_ID"
PRINCIPAL_ID_KEY: Final = "ONYX_DAYOPS_PRINCIPAL_ID"
CREDENTIAL_ALIAS_KEY: Final = "ONYX_DAYOPS_CREDENTIAL_ALIAS"
SCHEMA: Final = "OnyxDayOpsGraphFactory.v1"
INTEGRITY_SERVICE: Final = "CyryxLabs.Onyx.DayOpsAliases.v1"

ControlStoreFactoryV1 = Callable[[], ControlPlaneStore]
IntegrityKeyProviderV1 = Callable[["DayOpsGraphBindingV1"], bytes | None]


class DayOpsGraphFactoryV1Error(RuntimeError):
    pass


class DayOpsGraphFactoryV1ContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DayOpsGraphBindingV1:
    workspace_id: str
    principal_id: str
    credential_alias_name: str
    onboarding: MicrosoftGraphLiveOnboardingV1

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "DayOpsGraphBindingV1":
        source = os.environ if environ is None else environ
        values = tuple(
            source.get(name)
            for name in (
                WORKSPACE_ID_KEY,
                PRINCIPAL_ID_KEY,
                CREDENTIAL_ALIAS_KEY,
            )
        )
        if any(type(value) is not str or not value.strip() for value in values):
            raise DayOpsConfigurationRequiredV1(
                "DayOps workspace binding is incomplete"
            )
        try:
            onboarding = MicrosoftGraphLiveOnboardingV1.from_environ(source)
        except GraphLiveE2EV1Denied as exc:
            raise DayOpsConfigurationRequiredV1(
                "Microsoft public-client onboarding is incomplete"
            ) from exc
        return cls(
            str(values[0]).strip(),
            str(values[1]).strip(),
            str(values[2]).strip(),
            onboarding,
        )


def integrity_key_reference_v1(
    binding: DayOpsGraphBindingV1,
) -> native_vault.SecretReference:
    if type(binding) is not DayOpsGraphBindingV1:
        raise DayOpsGraphFactoryV1ContractError(
            "exact DayOps Graph binding required"
        )
    fingerprint = hashlib.sha256(
        f"{binding.workspace_id}\0{binding.principal_id}".encode("utf-8")
    ).hexdigest()
    return native_vault.SecretReference(
        INTEGRITY_SERVICE,
        f"ik_{fingerprint[:40]}",
        "Cyryx Labs Onyx DayOps workspace alias integrity key",
    )


def _native_integrity_key(binding: DayOpsGraphBindingV1) -> bytes | None:
    reference = integrity_key_reference_v1(binding)
    try:
        value = native_vault.NativeSecretVault(reference).get_bytes()
    except native_vault.NativeVaultError as exc:
        raise DayOpsGraphFactoryV1Error(
            "DayOps alias integrity vault is unavailable"
        ) from exc
    if value is None:
        return None
    if len(value) < 32:
        raise DayOpsGraphFactoryV1Error("DayOps alias integrity key is invalid")
    return value


class CanonicalDayOpsGraphFactoryV1:
    """Deferred composition of accepted workspace, OAuth and Graph contracts."""

    __slots__ = (
        "_clock_epoch_s",
        "_clock_ms",
        "_environ",
        "_http",
        "_integrity_key_provider",
        "_project_root",
        "_sleeper",
        "_store",
        "_store_factory",
        "_vault",
    )

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        store_factory: ControlStoreFactoryV1 | None = None,
        integrity_key_provider: IntegrityKeyProviderV1 | None = None,
        http: GraphOAuthHttpV1 | None = None,
        vault: RefreshTokenVaultV1 | None = None,
        clock_ms: Callable[[], int] | None = None,
        clock_epoch_s: Callable[[], int] | None = None,
        sleeper: Callable[[int], None] | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        if (
            store_factory is not None
            and not callable(store_factory)
            or integrity_key_provider is not None
            and not callable(integrity_key_provider)
            or clock_ms is not None
            and not callable(clock_ms)
            or clock_epoch_s is not None
            and not callable(clock_epoch_s)
            or sleeper is not None
            and not callable(sleeper)
        ):
            raise DayOpsGraphFactoryV1ContractError(
                "factory dependency is invalid"
            )
        self._environ = os.environ if environ is None else environ
        self._store_factory = (
            (lambda: ControlPlaneStore(enabled=True))
            if store_factory is None
            else store_factory
        )
        self._integrity_key_provider = (
            _native_integrity_key
            if integrity_key_provider is None
            else integrity_key_provider
        )
        self._http = http
        self._vault = vault
        self._clock_ms = (
            (lambda: time.time_ns() // 1_000_000)
            if clock_ms is None
            else clock_ms
        )
        self._clock_epoch_s = (
            (lambda: int(time.time()))
            if clock_epoch_s is None
            else clock_epoch_s
        )
        self._sleeper = time.sleep if sleeper is None else sleeper
        self._project_root = (
            Path(__file__).resolve().parents[1]
            if project_root is None
            else Path(project_root).resolve()
        )
        self._store: ControlPlaneStore | None = None

    def close(self) -> None:
        store = self._store
        self._store = None
        if store is not None:
            store.close()

    def __call__(self, now_ms: int) -> MicrosoftGraphReadAdapterV1 | None:
        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsGraphFactoryV1ContractError("current time is invalid")
        self.close()
        binding = DayOpsGraphBindingV1.from_environ(self._environ)
        integrity_key = self._integrity_key_provider(binding)
        if type(integrity_key) is not bytes or len(integrity_key) < 32:
            raise DayOpsConfigurationRequiredV1(
                "DayOps alias integrity key is not provisioned"
            )
        store = self._store_factory()
        if type(store) is not ControlPlaneStore:
            raise DayOpsGraphFactoryV1ContractError(
                "exact ControlPlaneStore factory required"
            )
        self._store = store
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            registry.require_active(binding.workspace_id)
            aliases = create_workspace_alias_catalog_v1(
                gate=WorkspaceAliasFeatureGateV1(True),
                registry=registry,
                workspace_id=binding.workspace_id,
                principal_id=binding.principal_id,
                integrity_key=integrity_key,
                project_root=self._project_root,
            )
            if aliases is None:
                raise DayOpsGraphFactoryV1Error(
                    "DayOps workspace alias catalog is unavailable"
                )
            try:
                credential = aliases.get(
                    kind="credential",
                    alias_name=binding.credential_alias_name,
                    now_ms=now_ms,
                )
            except WorkspaceAliasV1Denied as exc:
                raise DayOpsConfigurationRequiredV1(
                    "DayOps Microsoft credential alias is unavailable"
                ) from exc
            if (
                (credential.account_id or "").casefold()
                != binding.onboarding.account_id.casefold()
                or (
                    credential.tenant_id is not None
                    and credential.tenant_id.casefold()
                    != binding.onboarding.tenant_id.casefold()
                )
            ):
                raise DayOpsConfigurationRequiredV1(
                    "DayOps Microsoft identity binding does not match"
                )

            selected_vault = (
                NativeGraphRefreshTokenVaultV2(credential)
                if self._vault is None
                else self._vault
            )
            refresh_present = selected_vault.get_refresh_token()
            if refresh_present is None:
                raise DayOpsAuthenticationRequiredV1(
                    "Microsoft refresh token is unavailable"
                )
            del refresh_present

            selected_http = (
                StdlibGraphOAuthHttpV1() if self._http is None else self._http
            )
            session = create_microsoft_graph_oauth_v2(
                gate=GraphOAuthFeatureGateV1(True),
                aliases=aliases,
                credential_alias_name=binding.credential_alias_name,
                settings=binding.onboarding.settings(),
                http=selected_http,
                vault=selected_vault,
                now_ms=now_ms,
                project_root=self._project_root,
            )
            if session is None:
                raise DayOpsGraphFactoryV1Error(
                    "Microsoft OAuth session is unavailable"
                )
            status = session.restore(
                now_ms=now_ms,
                now_epoch_s=self._clock_epoch_s(),
            )
            if not status.connected:
                raise DayOpsAuthenticationRequiredV1(
                    "Microsoft sign-in is required"
                )
            transport = create_microsoft_graph_live_read_transport_v2(
                gate=GraphLiveReadFeatureGateV1(True),
                session=session,
                http=selected_http,
                clock_epoch_s=self._clock_epoch_s,
                clock_ms=self._clock_ms,
                sleeper=self._sleeper,
                project_root=self._project_root,
            )
            if transport is None:
                raise DayOpsGraphFactoryV1Error(
                    "Microsoft live read transport is unavailable"
                )
            adapter = create_microsoft_graph_read_adapter_v1(
                gate=GraphReadFeatureGateV1(True),
                aliases=aliases,
                credential_alias_name=binding.credential_alias_name,
                transport=transport,
                now_ms=now_ms,
                project_root=self._project_root,
            )
            if type(adapter) is not MicrosoftGraphReadAdapterV1:
                raise DayOpsGraphFactoryV1Error(
                    "Microsoft Graph read adapter is unavailable"
                )
            return adapter
        except WorkspaceError as exc:
            self.close()
            raise DayOpsConfigurationRequiredV1(
                "DayOps workspace is unavailable"
            ) from exc
        except Exception:
            self.close()
            raise


def create_canonical_dayops_graph_factory_v1(
    **options: object,
) -> CanonicalDayOpsGraphFactoryV1:
    return CanonicalDayOpsGraphFactoryV1(**options)


__all__ = [
    "CREDENTIAL_ALIAS_KEY",
    "CanonicalDayOpsGraphFactoryV1",
    "DayOpsGraphBindingV1",
    "DayOpsGraphFactoryV1ContractError",
    "DayOpsGraphFactoryV1Error",
    "INTEGRITY_SERVICE",
    "PRINCIPAL_ID_KEY",
    "SCHEMA",
    "WORKSPACE_ID_KEY",
    "create_canonical_dayops_graph_factory_v1",
    "integrity_key_reference_v1",
]
