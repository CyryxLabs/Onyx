# Onyx Live Activation V1 transition checkpoint

Date: 2026-07-22

Status: implementation candidate, default-off. No feature flag was enabled, no
live Onyx process was restarted, no provider/network call was made, and no
accepted candidate byte was changed.

## Transition boundary

The new `scripts/launch_onyx_live_v1.pyw` delegates to the accepted historical
launcher when the master and all children are absent. The single rollback flag
first neutralizes every coordinated child in the new process and then delegates
to the historical launcher, so the frozen host cannot independently see a stale
HUD or Phase 5 opt-in. A child without the master is refused before `main.py` or
UI import. Full activation is refused unless the master, Owner Profile V8, HUD
V5 and all eight Integration V3 child flags are exact true values.

The transition changes no accepted `main.py`, `ui.py`, QML, Phase 5 component,
permission broker, dashboard server, launcher, Phase 6, or E6 acceptance byte.
The opt-in launcher installs runtime seams around the frozen host rather than
rewriting those accepted artifacts.

## Owner identity authority

Owner Profile V8 is the only identity authority on the opt-in path. Its 32-byte
journal key uses the native vault namespace
`CyryxLabs.Onyx.OwnerProfileV8:journal-key-primary`; its accepted monotonic chain
head remains in the V8 namespace; and its authenticated journal is fixed below
the private control-plane runtime at
`identity/owner-profile-v8.journal.json`, separate from semantic memory.

Bootstrap occurs only when journal and chain head are both absent. A valid
key-only state may resume interrupted first provisioning; a journal/head
mismatch or a missing key for either existing durable store fails closed. Vault,
lease, reconcile or integrity failure latches the coordinator `DEGRADED`;
subsequent start calls do not retry or rewrite durable identity state. The
assistant may continue read-only with the literal English fallback `Sir`.

First contact asks the accepted V8 question once per unnamed contact. The three
closed owner tools persist, correct or forget the name through V8 transactions.
The opt-in setup seam writes through V8 first and lets the frozen setup handler
persist only the same reconciled value as a projection; HUD owner-name reads are
also redirected to V8. No second live identity source is introduced.
The injected high-priority directive says that `Sir` is literal,
non-translatable and non-localizable, explicitly hard-stopping `Efendim` and
other translated honorifics.

## Accepted runtime coordination

The existing Integration V3 host creates a session-scoped Runtime V10 bridge,
enables only the accepted provider-free local catalog read contract, and binds
R11, V15, V32 and Component Adapters V3. The coordinator observes that bridge;
kill, revoke, rollback, reconnect and shutdown use the accepted single
termination boundary. A reconnect creates a new Integration V3 session.

HUD V5 remains governed by its exact existing flag and accepted fallback: QML
failure restores the legacy central widget and leaves `_hud_v5_live` false.

## Activation and rollback procedure

Activation is intentionally deferred. A later live gate must set the complete
map returned by `exact_activation_environment()`, point the desktop/startup entry
to `scripts/launch_onyx_live_v1.pyw`, then perform one controlled restart and
physical voice/HUD/mobile checks. The one-switch rollback is
`ONYX_LIVE_ROLLBACK_V1=1`; the new launcher then delegates to the historical
launcher without loading the coordinator.

No partial child activation is accepted.

## Verification

The checkpoint manifest binds all seven E6 acceptance records, all accepted
component roots, the frozen host/startup bytes and every new transition byte.
Reproduce the candidate gate with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_live_activation_v1.py --basetemp .pytest-onyx-live-activation-v1
.\.venv\Scripts\python.exe -m ruff check core\onyx_live_activation_v1.py scripts\launch_onyx_live_v1.pyw scripts\verify_onyx_live_activation_v1.py tests\test_onyx_live_activation_v1.py
.\.venv\Scripts\python.exe -m py_compile core\onyx_live_activation_v1.py scripts\launch_onyx_live_v1.pyw scripts\verify_onyx_live_activation_v1.py tests\test_onyx_live_activation_v1.py
.\.venv\Scripts\python.exe -I -S -B scripts\verify_onyx_live_activation_v1.py
```

Independent functional, integrity and quality gates remain required before any
live flag, shortcut or restart change.
