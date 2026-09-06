# ADR-0021 — Activation V11 composes HUD V8 over accepted V10 C003

## Decision

Introduce a default-off V11 activation with exactly two new transactional
seams: the accepted HUD V8 visual overlay and the canonical V11 shortcut
target. Preserve accepted V10 C003 as the complete engine, voice, Gemini,
tooling, memory, onboarding, LAN and Phase 6 Wiring V1 base.

## Context

V10 intentionally loads accepted HUD V7 from a fresh private namespace so a
poisoned import cannot replace it. HUD V8 C001 authenticates the canonical V7
module name. V11 therefore validates the actual private V10 installation
record, host identity and private token, applies the canonical predecessor
module name only during V8's install check, and restores the private name in a
`finally` block. No accepted file is edited and an unverified substitute is
denied before the alias is applied.

## Consequences

- V8 remains default-off outside exact V11.
- One QQuickWidget and the complete V7/V10 surface are retained.
- V11 rollback restores the exact installed V10 host and shortcut seam.
- V11 changes no provider, tool, memory, authorization, onboarding or network
  behavior.
- macOS/Linux continue through the accepted V10 fallback until native V11
  physical gates exist.

