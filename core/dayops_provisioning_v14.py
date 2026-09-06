"""Local, secret-safe provisioning for the Onyx DayOps V14 read-only slice."""

from __future__ import annotations

import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from core import native_vault
from core.control_plane import ControlPlaneStore
from core.dayops_graph_factory_v1 import (
    DayOpsGraphBindingV1,
    integrity_key_reference_v1,
)
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    WorkspaceAliasRecordV1,
    WorkspaceAliasV1Conflict,
    WorkspaceAliasV1Denied,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_device_bootstrap_v2 import (
    DeviceBootstrapFeatureGateV2,
    DeviceBootstrapResultV2,
    create_microsoft_graph_device_bootstrap_v2,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    GraphOAuthHttpV1,
    NativeGraphRefreshTokenVaultV1,
    RefreshTokenVaultV1,
    StdlibGraphOAuthHttpV1,
)
from core.workspaces import (
    WorkspaceError,
    WorkspaceRegistry,
    WorkspaceUnknown,
)


SCHEMA: Final = "OnyxDayOpsProvisioning.v14"
READ_ONLY_SCOPES: Final = ("Calendars.Read", "Mail.Read")
INTEGRITY_KEY_BYTES: Final = 32
DEFAULT_SIGN_IN_TIMEOUT_SECONDS: Final = 900


class DayOpsProvisioningV14Error(RuntimeError):
    pass


class DayOpsProvisioningV14ContractError(ValueError):
    pass


class DayOpsProvisioningV14Mismatch(DayOpsProvisioningV14Error):
    pass


class DayOpsProvisioningV14Cancelled(DayOpsProvisioningV14Error):
    pass


class DayOpsProvisioningV14Timeout(DayOpsProvisioningV14Error):
    pass


class SecretBytesVaultV14(Protocol):
    def get_bytes(self) -> bytes | None: ...

    def set_bytes(self, secret: bytes | bytearray) -> None: ...


@dataclass(frozen=True, slots=True)
class DayOpsProvisioningConfigV14:
    client_id: str
    tenant_id: str
    account_id: str
    workspace_id: str
    principal_id: str
    credential_alias_name: str

    def __post_init__(self) -> None:
        values = (
            self.client_id,
            self.tenant_id,
            self.account_id,
            self.workspace_id,
            self.principal_id,
            self.credential_alias_name,
        )
        if any(type(value) is not str or not value.strip() for value in values):
            raise DayOpsProvisioningV14ContractError(
                "all public onboarding identifiers are required"
            )
        try:
            onboarding = MicrosoftGraphLiveOnboardingV1(
                self.client_id.strip(),
                self.tenant_id.strip(),
                self.account_id.strip(),
            )
            DayOpsGraphBindingV1(
                self.workspace_id.strip(),
                self.principal_id.strip(),
                self.credential_alias_name.strip(),
                onboarding,
            )
        except (TypeError, ValueError, PermissionError) as exc:
            raise DayOpsProvisioningV14ContractError(
                "public onboarding identifiers are invalid"
            ) from exc

    def binding(self) -> DayOpsGraphBindingV1:
        return DayOpsGraphBindingV1(
            self.workspace_id.strip(),
            self.principal_id.strip(),
            self.credential_alias_name.strip(),
            MicrosoftGraphLiveOnboardingV1(
                self.client_id.strip(),
                self.tenant_id.strip(),
                self.account_id.strip(),
            ),
        )


@dataclass(frozen=True, slots=True)
class DayOpsProvisioningStatusV14:
    workspace: str
    integrity_key: str
    credential_alias: str
    microsoft_sign_in: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schema": SCHEMA,
            "workspace": self.workspace,
            "integrity_key": self.integrity_key,
            "credential_alias": self.credential_alias,
            "microsoft_sign_in": self.microsoft_sign_in,
        }


class _DeadlineHttpV14:
    __slots__ = ("_guard", "_http")

    def __init__(self, http: GraphOAuthHttpV1, guard: Callable[[], None]) -> None:
        self._http = http
        self._guard = guard

    def post_form(self, **kwargs: object):
        self._guard()
        result = self._http.post_form(**kwargs)
        self._guard()
        return result

    def get_json(self, **kwargs: object):
        self._guard()
        result = self._http.get_json(**kwargs)
        self._guard()
        return result


class DayOpsProvisionerV14:
    """Idempotent local provisioning over accepted Phase 7/8 contracts."""

    __slots__ = (
        "_clock_epoch_s",
        "_config",
        "_http",
        "_integrity_vault_factory",
        "_monotonic",
        "_project_root",
        "_refresh_vault_factory",
        "_sleeper",
        "_store_factory",
    )

    def __init__(
        self,
        config: DayOpsProvisioningConfigV14,
        *,
        store_factory: Callable[[], ControlPlaneStore] | None = None,
        integrity_vault_factory: (
            Callable[[DayOpsGraphBindingV1], SecretBytesVaultV14] | None
        ) = None,
        refresh_vault_factory: (
            Callable[[WorkspaceAliasRecordV1], RefreshTokenVaultV1] | None
        ) = None,
        http: GraphOAuthHttpV1 | None = None,
        sleeper: Callable[[int], None] | None = None,
        clock_epoch_s: Callable[[], int] | None = None,
        monotonic: Callable[[], float] | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        if type(config) is not DayOpsProvisioningConfigV14:
            raise DayOpsProvisioningV14ContractError(
                "exact provisioning configuration required"
            )
        dependencies = (
            store_factory,
            integrity_vault_factory,
            refresh_vault_factory,
            sleeper,
            clock_epoch_s,
            monotonic,
        )
        if any(value is not None and not callable(value) for value in dependencies):
            raise DayOpsProvisioningV14ContractError(
                "provisioning dependency is invalid"
            )
        self._config = config
        self._store_factory = (
            (lambda: ControlPlaneStore(enabled=True))
            if store_factory is None
            else store_factory
        )
        if integrity_vault_factory is None:
            self._integrity_vault_factory = (
                lambda binding: native_vault.NativeSecretVault(
                    integrity_key_reference_v1(binding)
                )
            )
        else:
            self._integrity_vault_factory = integrity_vault_factory
        self._refresh_vault_factory = (
            NativeGraphRefreshTokenVaultV1
            if refresh_vault_factory is None
            else refresh_vault_factory
        )
        self._http = StdlibGraphOAuthHttpV1() if http is None else http
        self._sleeper = time.sleep if sleeper is None else sleeper
        self._clock_epoch_s = (
            (lambda: int(time.time()))
            if clock_epoch_s is None
            else clock_epoch_s
        )
        self._monotonic = time.monotonic if monotonic is None else monotonic
        self._project_root = (
            Path(__file__).resolve().parents[1]
            if project_root is None
            else Path(project_root).resolve()
        )

    def _store(self) -> ControlPlaneStore:
        store = self._store_factory()
        if type(store) is not ControlPlaneStore:
            raise DayOpsProvisioningV14ContractError(
                "exact ControlPlaneStore factory required"
            )
        return store

    def _integrity_vault(self) -> SecretBytesVaultV14:
        vault = self._integrity_vault_factory(self._config.binding())
        if not hasattr(vault, "get_bytes") or not hasattr(vault, "set_bytes"):
            raise DayOpsProvisioningV14ContractError(
                "integrity vault contract is invalid"
            )
        return vault

    def _catalog(
        self,
        registry: WorkspaceRegistry,
        integrity_key: bytes,
    ):
        binding = self._config.binding()
        catalog = create_workspace_alias_catalog_v1(
            gate=WorkspaceAliasFeatureGateV1(True),
            registry=registry,
            workspace_id=binding.workspace_id,
            principal_id=binding.principal_id,
            integrity_key=integrity_key,
            project_root=self._project_root,
        )
        if catalog is None:
            raise DayOpsProvisioningV14Error(
                "DayOps credential catalog is unavailable"
            )
        return catalog

    @staticmethod
    def _verify_credential(
        credential: WorkspaceAliasRecordV1,
        binding: DayOpsGraphBindingV1,
    ) -> None:
        if (
            type(credential) is not WorkspaceAliasRecordV1
            or credential.kind != "credential"
            or credential.provider != "microsoft-graph"
            or credential.alias_name != binding.credential_alias_name
            or (credential.account_id or "").casefold()
            != binding.onboarding.account_id.casefold()
            or (credential.tenant_id or "").casefold()
            != binding.onboarding.tenant_id.casefold()
            or tuple(credential.scopes) != READ_ONLY_SCOPES
        ):
            raise DayOpsProvisioningV14Mismatch(
                "existing Microsoft Graph credential binding does not match"
            )

    def _existing_credential(
        self,
        registry: WorkspaceRegistry,
        integrity_key: bytes,
        *,
        now_ms: int,
    ) -> WorkspaceAliasRecordV1:
        binding = self._config.binding()
        credential = self._catalog(registry, integrity_key).get(
            kind="credential",
            alias_name=binding.credential_alias_name,
            now_ms=now_ms,
        )
        self._verify_credential(credential, binding)
        return credential

    def prepare(self, *, now_ms: int) -> DayOpsProvisioningStatusV14:
        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsProvisioningV14ContractError("current time is invalid")
        binding = self._config.binding()
        store = self._store()
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                workspace = registry.get(binding.workspace_id)
            except WorkspaceUnknown:
                workspace = registry.register(
                    binding.workspace_id,
                    display_name="Onyx DayOps",
                    workspace_class="cyryx",
                )
            if workspace.status != "active" or workspace.workspace_class != "cyryx":
                raise DayOpsProvisioningV14Mismatch(
                    "existing workspace binding does not match"
                )

            integrity_vault = self._integrity_vault()
            integrity_key = integrity_vault.get_bytes()
            if integrity_key is None:
                generated = secrets.token_bytes(INTEGRITY_KEY_BYTES)
                integrity_vault.set_bytes(generated)
                integrity_key = integrity_vault.get_bytes()
                if (
                    type(integrity_key) is not bytes
                    or not hmac.compare_digest(integrity_key, generated)
                ):
                    raise DayOpsProvisioningV14Error(
                        "native integrity-key write verification failed"
                    )
            if (
                type(integrity_key) is not bytes
                or len(integrity_key) != INTEGRITY_KEY_BYTES
            ):
                raise DayOpsProvisioningV14Mismatch(
                    "existing alias integrity key is invalid"
                )

            catalog = self._catalog(registry, integrity_key)
            try:
                credential = catalog.get(
                    kind="credential",
                    alias_name=binding.credential_alias_name,
                    now_ms=now_ms,
                )
            except WorkspaceAliasV1Denied:
                try:
                    credential = catalog.register(
                        binding.credential_alias_name,
                        CredentialAliasSpecV1(
                            provider="microsoft-graph",
                            account_id=binding.onboarding.account_id,
                            tenant_id=binding.onboarding.tenant_id,
                            scopes=READ_ONLY_SCOPES,
                        ),
                        now_ms=now_ms,
                    )
                except (
                    WorkspaceAliasV1Conflict,
                    WorkspaceAliasV1Denied,
                ) as exc:
                    raise DayOpsProvisioningV14Mismatch(
                        "existing credential alias has different immutable content"
                    ) from exc
            self._verify_credential(credential, binding)
            refresh = self._refresh_vault_factory(credential)
            connected = refresh.get_refresh_token() is not None
            return DayOpsProvisioningStatusV14(
                "ready",
                "ready",
                "ready",
                "connected" if connected else "disconnected",
            )
        except WorkspaceError as exc:
            raise DayOpsProvisioningV14Mismatch(
                "workspace provisioning failed closed"
            ) from exc
        finally:
            store.close()

    def status(self, *, now_ms: int) -> DayOpsProvisioningStatusV14:
        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsProvisioningV14ContractError("current time is invalid")
        binding = self._config.binding()
        workspace_state = "missing"
        key_state = "missing"
        alias_state = "missing"
        sign_in_state = "disconnected"
        store = self._store()
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            try:
                workspace = registry.require_active(binding.workspace_id)
                workspace_state = (
                    "ready" if workspace.workspace_class == "cyryx" else "mismatch"
                )
            except WorkspaceError:
                return DayOpsProvisioningStatusV14(
                    workspace_state, key_state, alias_state, sign_in_state
                )
            integrity_key = self._integrity_vault().get_bytes()
            if integrity_key is None:
                return DayOpsProvisioningStatusV14(
                    workspace_state, key_state, alias_state, sign_in_state
                )
            if len(integrity_key) != INTEGRITY_KEY_BYTES:
                return DayOpsProvisioningStatusV14(
                    workspace_state, "mismatch", alias_state, sign_in_state
                )
            key_state = "ready"
            try:
                credential = self._existing_credential(
                    registry, integrity_key, now_ms=now_ms
                )
            except (WorkspaceAliasV1Denied, DayOpsProvisioningV14Mismatch):
                alias_state = "mismatch"
            else:
                alias_state = "ready"
                sign_in_state = (
                    "connected"
                    if self._refresh_vault_factory(
                        credential
                    ).get_refresh_token()
                    is not None
                    else "disconnected"
                )
            return DayOpsProvisioningStatusV14(
                workspace_state, key_state, alias_state, sign_in_state
            )
        finally:
            store.close()

    def disconnect(self, *, now_ms: int) -> DayOpsProvisioningStatusV14:
        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsProvisioningV14ContractError("current time is invalid")
        store = self._store()
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            integrity_key = self._integrity_vault().get_bytes()
            if type(integrity_key) is not bytes or len(integrity_key) != 32:
                raise DayOpsProvisioningV14Mismatch(
                    "DayOps must be prepared before disconnect"
                )
            credential = self._existing_credential(
                registry, integrity_key, now_ms=now_ms
            )
            self._refresh_vault_factory(credential).delete_refresh_token()
            return DayOpsProvisioningStatusV14(
                "ready", "ready", "ready", "disconnected"
            )
        finally:
            store.close()

    def sign_in(
        self,
        *,
        echo: Callable[[str], None],
        now_ms: int,
        timeout_seconds: int = DEFAULT_SIGN_IN_TIMEOUT_SECONDS,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> DeviceBootstrapResultV2:
        if (
            not callable(echo)
            or type(now_ms) is not int
            or now_ms < 0
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 1_800
            or cancel_requested is not None
            and not callable(cancel_requested)
        ):
            raise DayOpsProvisioningV14ContractError(
                "sign-in bindings are invalid"
            )
        started = self._monotonic()

        def guard() -> None:
            if cancel_requested is not None and cancel_requested():
                raise DayOpsProvisioningV14Cancelled(
                    "Microsoft sign-in was cancelled"
                )
            if self._monotonic() - started >= timeout_seconds:
                raise DayOpsProvisioningV14Timeout(
                    "Microsoft sign-in timed out"
                )

        def guarded_sleep(seconds: int) -> None:
            guard()
            self._sleeper(seconds)
            guard()

        store = self._store()
        try:
            store.initialize()
            registry = WorkspaceRegistry(store, enabled=True).initialize()
            integrity_key = self._integrity_vault().get_bytes()
            if (
                type(integrity_key) is not bytes
                or len(integrity_key) != INTEGRITY_KEY_BYTES
            ):
                raise DayOpsProvisioningV14Mismatch(
                    "DayOps must be prepared before sign-in"
                )
            credential = self._existing_credential(
                registry, integrity_key, now_ms=now_ms
            )
            vault = self._refresh_vault_factory(credential)
            bootstrap = create_microsoft_graph_device_bootstrap_v2(
                gate=DeviceBootstrapFeatureGateV2(True),
                onboarding=self._config.binding().onboarding,
                http=_DeadlineHttpV14(self._http, guard),
                vault=vault,
                sleeper=guarded_sleep,
                clock_epoch_s=lambda: (guard(), self._clock_epoch_s())[1],
                now_ms=now_ms,
            )
            if bootstrap is None:
                raise DayOpsProvisioningV14Error(
                    "Microsoft device bootstrap is unavailable"
                )
            guard()
            return bootstrap.sign_in(echo=echo)
        finally:
            store.close()


__all__ = [
    "DEFAULT_SIGN_IN_TIMEOUT_SECONDS",
    "DayOpsProvisionerV14",
    "DayOpsProvisioningConfigV14",
    "DayOpsProvisioningStatusV14",
    "DayOpsProvisioningV14Cancelled",
    "DayOpsProvisioningV14ContractError",
    "DayOpsProvisioningV14Error",
    "DayOpsProvisioningV14Mismatch",
    "DayOpsProvisioningV14Timeout",
    "INTEGRITY_KEY_BYTES",
    "READ_ONLY_SCOPES",
    "SCHEMA",
]
