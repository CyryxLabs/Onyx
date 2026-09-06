"""Host-native activation truth used by smoke and release evidence.

Windows reaches the current V24 activation.  The existing macOS/Linux normal
bootstrap deliberately falls through the Windows-only V14..V9 launchers and
ultimately runs V8.  The explicit portable-current candidate now proves its
V16 descriptor-bound persistence, but remains fail-closed before V10 because
the inherited V4 owner authority is Windows-only.
"""

from __future__ import annotations

from typing import Final


ACTIVATION_CONTRACT: Final = "OnyxHostActivation.v1"
SUPPORTED_SYSTEMS: Final = frozenset({"Windows", "Darwin", "Linux"})


class NativeActivationContractError(RuntimeError):
    """A host has no truthful native activation contract."""


def activation_contract_for_system_v1(
    system: str,
    *,
    portable_current: bool = False,
) -> dict[str, object]:
    """Return immutable-by-convention JSON evidence for one build host."""

    if type(portable_current) is not bool:
        raise NativeActivationContractError(
            "portable-current activation selection must be boolean"
        )
    if system not in SUPPORTED_SYSTEMS:
        raise NativeActivationContractError(
            f"unsupported native activation host: {system}"
        )
    if system == "Windows":
        return {
            "contract": ACTIVATION_CONTRACT,
            "normal_activation": "v24",
            "smoke_activation": "v24",
            "activation_profile": "current-windows",
            "capability_limited": False,
            "v15_v19_parity": True,
            "v19_v20_additive": True,
            "v20_v21_additive": True,
            "v21_v22_additive": True,
            "v22_v23_additive": True,
            "v23_v24_additive": True,
        }
    if portable_current:
        return {
            "contract": ACTIVATION_CONTRACT,
            "normal_activation": "unavailable",
            "declared_activation": "v19",
            "smoke_activation": "none",
            "highest_proven_activation": "v16_descriptor_ledger",
            "boundary_reached": "pre_v10",
            "next_unimplemented_activation": "v4_portable_owner_authority",
            "activation_profile": "portable-current-negative-boundary-default-off",
            "capability_limited": True,
            "v15_v19_parity": False,
            "native_evidence_required": True,
            "limitation_reason": (
                "portable_current_v4_owner_authority_unavailable"
            ),
        }
    return {
        "contract": ACTIVATION_CONTRACT,
        "normal_activation": "v8",
        "smoke_activation": "v8",
        "activation_profile": "portable-v8-fallback-capability-limited",
        "capability_limited": True,
        "v15_v19_parity": False,
    }


__all__ = [
    "ACTIVATION_CONTRACT",
    "NativeActivationContractError",
    "SUPPORTED_SYSTEMS",
    "activation_contract_for_system_v1",
]
