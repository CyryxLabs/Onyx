from __future__ import annotations

from types import ModuleType

import pytest

from core import onyx_live_activation_v19 as v19


def _arbitrary_factory(**_binding: object) -> object:
    return object()


def test_v19_constructor_refuses_arbitrary_executable_sandbox_factory() -> None:
    with pytest.raises(v19.ActivationV19Error, match="arbitrary executable"):
        v19.OnyxLiveActivationV19(  # type: ignore[arg-type]
            object(), object(), executable_sandbox_factory=_arbitrary_factory
        )


def test_v19_entrypoint_refuses_arbitrary_executable_sandbox_factory() -> None:
    with pytest.raises(v19.ActivationV19Error, match="arbitrary executable"):
        v19.activate_main(  # type: ignore[arg-type]
            ModuleType("refused_host"),
            executable_sandbox_factory=_arbitrary_factory,
        )
