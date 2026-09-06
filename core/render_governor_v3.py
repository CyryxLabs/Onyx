"""Versioned render governor for the isolated HUD/Orb V3 candidate.

V3 deliberately preserves the proven V2 governor policy while giving the new
candidate an explicit import surface. The V2 implementation remains frozen.
"""
from __future__ import annotations

from core.render_governor import (
    ACTIVE_STATES,
    FPS_TIERS,
    KNOWN_STATES,
    PARTICLE_BUDGETS,
    RenderGovernor,
    RenderSnapshot,
)


class RenderGovernorV3(RenderGovernor):
    """V3-named governor retaining V2's deterministic bounded policy."""


__all__ = [
    "ACTIVE_STATES",
    "FPS_TIERS",
    "KNOWN_STATES",
    "PARTICLE_BUDGETS",
    "RenderGovernorV3",
    "RenderSnapshot",
]
