"""Host-only DayOps V19 onboarding and read controller.

The controller is the sole bridge between the trusted Qt connection surface and
the accepted profile/provisioning/Graph engines.  It never returns refresh
tokens, device codes, filesystem paths, or governance identifiers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Final

from core.dayops_graph_factory_v19 import PersistentDayOpsGraphFactoryV19
from core.dayops_identity_provisioning_v19 import DayOpsIdentityProvisionerV19
from core.dayops_live_integration_v1 import (
    DayOpsFeatureGateV1,
    DayOpsLiveIntegrationV1,
    create_dayops_live_integration_v1,
)
from core.dayops_live_integration_v2 import (
    DayOpsLiveIntegrationV2,
    create_dayops_live_integration_v2,
)
from core.dayops_profile_v19 import (
    DayOpsProfileStoreV19,
    DayOpsProfileV19,
    DayOpsProfileV19Error,
    DayOpsProfileV19Unavailable,
)
from core.dayops_provisioning_v14 import (
    DayOpsProvisionerV14,
    DayOpsProvisioningConfigV14,
    DayOpsProvisioningStatusV14,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.graph_refresh_vault_v2 import NativeGraphRefreshTokenVaultV2


SCHEMA: Final = "OnyxDayOpsConnection.v19"
CONFIG_FIELDS: Final = frozenset(
    {
        "client_id",
        "tenant_id",
        "account_id",
        "iana_timezone",
        "outlook_timezone",
    }
)


class DayOpsConnectionV19Error(RuntimeError):
    pass


class DayOpsConnectionV19ContractError(ValueError):
    pass


ProvisionerFactoryV19 = Callable[[DayOpsProfileV19], DayOpsProvisionerV14]


def _status_payload(status: DayOpsProvisioningStatusV14) -> dict[str, object]:
    if type(status) is not DayOpsProvisioningStatusV14:
        raise DayOpsConnectionV19ContractError(
            "exact DayOps provisioning status is required"
        )
    state = "connected" if status.microsoft_sign_in == "connected" else "disconnected"
    return {
        "schema": SCHEMA,
        "status": state,
        "read_only": True,
        "workspace": status.workspace,
        "credential_alias": status.credential_alias,
        "microsoft_sign_in": status.microsoft_sign_in,
        "permissions": ["Calendars.Read", "Mail.Read"],
    }


class DayOpsConnectionControllerV19:
    """One identity-bound owner of profile, onboarding, and daily reads."""

    __slots__ = (
        "_clock_ms",
        "_factory",
        "_identity",
        "_integration",
        "_lock",
        "_profile_store",
        "_provisioner",
        "_provisioner_factory",
    )

    def __init__(
        self,
        identity: GovernanceIdentityV1,
        profile_store: DayOpsProfileStoreV19,
        identity_provisioner: DayOpsIdentityProvisionerV19,
        graph_factory: PersistentDayOpsGraphFactoryV19,
        *,
        provisioner_factory: ProvisionerFactoryV19 | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if type(identity) is not GovernanceIdentityV1:
            raise DayOpsConnectionV19ContractError(
                "exact governance identity is required"
            )
        if (
            type(profile_store) is not DayOpsProfileStoreV19
            or profile_store.identity != identity
            or type(identity_provisioner) is not DayOpsIdentityProvisionerV19
            or type(graph_factory) is not PersistentDayOpsGraphFactoryV19
        ):
            raise DayOpsConnectionV19ContractError(
                "exact identity-bound DayOps components are required"
            )
        if provisioner_factory is not None and not callable(provisioner_factory):
            raise DayOpsConnectionV19ContractError(
                "DayOps provisioner factory is invalid"
            )
        if clock_ms is not None and not callable(clock_ms):
            raise DayOpsConnectionV19ContractError("DayOps clock is invalid")
        base_integration = create_dayops_live_integration_v1(
            gate=DayOpsFeatureGateV1(True),
            adapter_factory=graph_factory,
        )
        if type(base_integration) is not DayOpsLiveIntegrationV1:
            raise DayOpsConnectionV19Error("DayOps live integration is unavailable")
        integration = create_dayops_live_integration_v2(base=base_integration)
        if type(integration) is not DayOpsLiveIntegrationV2:
            raise DayOpsConnectionV19Error("DayOps planner wrapper is unavailable")
        self._identity = identity
        self._profile_store = profile_store
        self._provisioner = identity_provisioner
        self._factory = graph_factory
        self._integration = integration
        self._provisioner_factory = (
            self._default_provisioner
            if provisioner_factory is None
            else provisioner_factory
        )
        self._clock_ms = (
            (lambda: time.time_ns() // 1_000_000) if clock_ms is None else clock_ms
        )
        self._lock = threading.RLock()

    @staticmethod
    def _default_provisioner(profile: DayOpsProfileV19) -> DayOpsProvisionerV14:
        return DayOpsProvisionerV14(
            DayOpsProvisioningConfigV14(
                profile.client_id,
                profile.tenant_id,
                profile.account_id,
                profile.workspace_id,
                profile.principal_id,
                profile.credential_alias_name,
            ),
            refresh_vault_factory=NativeGraphRefreshTokenVaultV2,
        )

    def _now_ms(self) -> int:
        value = self._clock_ms()
        if type(value) is not int or value < 0:
            raise DayOpsConnectionV19ContractError("DayOps clock is invalid")
        return value

    def _profile(self) -> DayOpsProfileV19:
        return self._profile_store.load()

    def _legacy(self, profile: DayOpsProfileV19) -> DayOpsProvisionerV14:
        result = self._provisioner_factory(profile)
        if type(result) is not DayOpsProvisionerV14:
            raise DayOpsConnectionV19ContractError(
                "exact V14 DayOps provisioner is required"
            )
        return result

    def status(self) -> dict[str, object]:
        with self._lock:
            try:
                profile = self._profile()
            except DayOpsProfileV19Unavailable:
                return {
                    "schema": SCHEMA,
                    "status": "configuration_required",
                    "read_only": True,
                    "permissions": ["Calendars.Read", "Mail.Read"],
                }
            except DayOpsProfileV19Error as exc:
                raise DayOpsConnectionV19Error(
                    "DayOps profile requires repair"
                ) from exc
            return _status_payload(self._legacy(profile).status(now_ms=self._now_ms()))

    def connect(self, payload: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(payload, Mapping) or set(payload) != CONFIG_FIELDS:
            raise DayOpsConnectionV19ContractError(
                "exact public DayOps connection fields are required"
            )
        values = {name: payload[name] for name in CONFIG_FIELDS}
        if any(type(value) is not str for value in values.values()):
            raise DayOpsConnectionV19ContractError(
                "public DayOps connection values are invalid"
            )
        with self._lock:
            profile = DayOpsProfileV19.create(
                self._identity,
                client_id=str(values["client_id"]),
                tenant_id=str(values["tenant_id"]),
                account_id=str(values["account_id"]),
                iana_timezone=str(values["iana_timezone"]),
                outlook_timezone=str(values["outlook_timezone"]),
            )
            self._provisioner.prepare(profile, now_ms=self._now_ms())
            return _status_payload(self._legacy(profile).status(now_ms=self._now_ms()))

    def sign_in(
        self,
        echo: Callable[[str], None],
        cancel_requested: Callable[[], bool],
    ) -> dict[str, object]:
        if not callable(echo) or not callable(cancel_requested):
            raise DayOpsConnectionV19ContractError(
                "trusted sign-in callbacks are required"
            )
        with self._lock:
            profile = self._profile()
            self._legacy(profile).sign_in(
                echo=echo,
                now_ms=self._now_ms(),
                cancel_requested=cancel_requested,
            )
            return {
                "schema": SCHEMA,
                "status": "connected",
                "read_only": True,
                "permissions": ["Calendars.Read", "Mail.Read"],
            }

    def disconnect(self) -> dict[str, object]:
        with self._lock:
            profile = self._profile()
            status = self._legacy(profile).disconnect(now_ms=self._now_ms())
            return _status_payload(status)

    def today_brief(self) -> dict[str, object]:
        with self._lock:
            profile = self._profile()
            now = datetime.fromtimestamp(self._now_ms() / 1_000, tz=timezone.utc)
            execution = self._integration.execute(
                {},
                environ=profile.public_environment(),
                now=now,
            )
            result = dict(execution.result)
            result["schema"] = SCHEMA
            result["status"] = execution.status
            if execution.error_type:
                result["error_type"] = execution.error_type
            return result

    def close(self) -> None:
        self._factory.close()


__all__ = [
    "CONFIG_FIELDS",
    "DayOpsConnectionControllerV19",
    "DayOpsConnectionV19ContractError",
    "DayOpsConnectionV19Error",
    "SCHEMA",
]
