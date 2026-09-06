"""Persistent DayOps Graph factory backed by the authenticated V19 profile."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from core.dayops_graph_factory_v1 import create_canonical_dayops_graph_factory_v1
from core.dayops_live_integration_v1 import DayOpsConfigurationRequiredV1
from core.dayops_profile_v19 import (
    DayOpsProfileStoreV19,
    DayOpsProfileV19Error,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.phase8_microsoft_graph_read_v1 import MicrosoftGraphReadAdapterV1


class DayOpsGraphFactoryV19ContractError(ValueError):
    pass


class _GraphFactoryV19(Protocol):
    def __call__(self, now_ms: int) -> MicrosoftGraphReadAdapterV1 | None: ...

    def close(self) -> None: ...


GraphFactoryBuilderV19 = Callable[..., _GraphFactoryV19]


class PersistentDayOpsGraphFactoryV19:
    """Reload and revalidate the signed profile at each authorized invocation."""

    __slots__ = ("_builder", "_delegate", "_options", "_profile_store")

    def __init__(
        self,
        identity: GovernanceIdentityV1,
        profile_store: DayOpsProfileStoreV19,
        *,
        graph_factory_builder: GraphFactoryBuilderV19 | None = None,
        graph_factory_options: Mapping[str, object] | None = None,
    ) -> None:
        if type(identity) is not GovernanceIdentityV1:
            raise DayOpsGraphFactoryV19ContractError(
                "exact governance identity is required"
            )
        if type(profile_store) is not DayOpsProfileStoreV19:
            raise DayOpsGraphFactoryV19ContractError(
                "exact V19 profile store is required"
            )
        if profile_store.identity != identity:
            raise DayOpsGraphFactoryV19ContractError(
                "profile store identity does not match"
            )
        builder = (
            create_canonical_dayops_graph_factory_v1
            if graph_factory_builder is None
            else graph_factory_builder
        )
        if not callable(builder):
            raise DayOpsGraphFactoryV19ContractError("Graph factory builder is invalid")
        if graph_factory_options is None:
            options: dict[str, object] = {}
        elif not isinstance(graph_factory_options, Mapping):
            raise DayOpsGraphFactoryV19ContractError(
                "Graph factory options are invalid"
            )
        else:
            options = dict(graph_factory_options)
        if "environ" in options:
            raise DayOpsGraphFactoryV19ContractError(
                "environment authority cannot be injected"
            )
        self._profile_store = profile_store
        self._builder = builder
        self._options = options
        self._delegate: _GraphFactoryV19 | None = None

    def close(self) -> None:
        delegate = self._delegate
        self._delegate = None
        if delegate is not None:
            delegate.close()

    def __call__(self, now_ms: int) -> MicrosoftGraphReadAdapterV1 | None:
        if type(now_ms) is not int or now_ms < 0:
            raise DayOpsGraphFactoryV19ContractError("current time is invalid")
        self.close()
        try:
            profile = self._profile_store.load()
        except DayOpsProfileV19Error as exc:
            raise DayOpsConfigurationRequiredV1(
                "DayOps persistent profile requires repair or provisioning"
            ) from exc
        delegate = self._builder(
            environ=profile.public_environment(),
            **self._options,
        )
        if not callable(delegate) or not callable(getattr(delegate, "close", None)):
            raise DayOpsGraphFactoryV19ContractError(
                "Graph factory builder returned an invalid factory"
            )
        self._delegate = delegate
        try:
            return delegate(now_ms)
        except Exception:
            self.close()
            raise


def create_persistent_dayops_graph_factory_v19(
    identity: GovernanceIdentityV1,
    profile_store: DayOpsProfileStoreV19,
    **options: object,
) -> PersistentDayOpsGraphFactoryV19:
    return PersistentDayOpsGraphFactoryV19(identity, profile_store, **options)


__all__ = [
    "DayOpsGraphFactoryV19ContractError",
    "PersistentDayOpsGraphFactoryV19",
    "create_persistent_dayops_graph_factory_v19",
]
