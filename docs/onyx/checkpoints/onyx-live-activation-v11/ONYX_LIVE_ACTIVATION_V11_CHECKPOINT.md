# Onyx Live Activation V11 C001 — Voice-reactive Orb candidate

Status: **DEFAULT-OFF / UNWIRED / READY FOR EXTERNAL GATE**

V11 composes the accepted V10 C003 operational engine and accepted HUD V8 C001
visual layer without editing either predecessor. Its only new behavior is
internal Orb particles that move while Onyx is in `SPEAKING` state and stop
completely when idle or hidden. No arc, orbit, ring or square is added around
the Orb.

## Exact activation boundary

The active truth requires the complete V10 canonical environment plus:

- `ONYX_LIVE_ACTIVATION_V11=1`;
- `ONYX_HUD_V8_LIVE=1`;
- the hash-bound V11 Python, bootstrap and launcher runtime bundle;
- exact accepted V10 C003 and HUD V8 C001 candidate/E6 envelopes.

All predecessor envelopes and every V8 manifest leaf are verified before the
live host is imported. The V8 source is loaded from its verified path into a
fresh namespace. A poisoned `sys.modules` entry cannot substitute it.

## Authenticated private-module bridge

V10's accepted V7 is intentionally installed from a private verified module.
Before V8 installation, V11 requires the exact V10 private module name, private
installation record, installed host identity, immutable marker token and V7
host qualname. Only then is the host's module label temporarily presented as
the canonical V7 label expected by V8. The original private label is restored
in `finally`, whether installation succeeds or fails.

## Composition and rollback

V11 adds two seams after V10's 35 seams:

1. install accepted HUD V8 over the exact V10-installed V7 host;
2. replace only V10's source shortcut method with the verified V11 bootstrap.

Rollback first restores the V10 shortcut method and exact V7 host, then can
delegate full rollback through V10. Voice, Gemini, tools, memory, permission
policy, onboarding and remote services remain V10-owned and unchanged.

## Evidence

- V11 focused tests: 18 passed;
- accepted V10 regression: 33 passed in an isolated process;
- HUD V8 candidate: 7 passed;
- HUD V8 E6 regression: 8 passed;
- physical real-host smoke: one V8 root, one QQuickWidget, phase advances only
  while speaking, idle phase zero, exact V10 rollback;
- canonical preflight: pass before live window and with zero network calls;
- Ruff and Python compilation: pass;
- live activation, shortcut write and provider calls: none at this checkpoint.

The accepted V8 physical D3D11 measurements remain 0.404% speaking, 0.083%
idle and 0.000% hidden host CPU. This candidate checkpoint does not claim a
new V11 live-process CPU measurement or macOS/Linux physical reproduction.

