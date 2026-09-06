# ADR-0005: Migrate to one Qt Quick shell only after callback and resource parity

- Status: Accepted for phased implementation after stable control-plane projections
- Date: 2026-07-14
- Decision owners: Cyryx Labs / Onyx owner

## Context

Onyx currently has a working Qt widget UI in `ui.py`, one `QQuickWidget` Orb bridge through `ui.py:OrbHost`, the 3D scene in `qml/OnyxOrb.qml` and an authenticated remote dashboard. The target experience is a cinematic Cyryx AI command center, but appearance cannot justify duplicate render loops, excessive idle CPU/GPU, broken callbacks or UI claims that exceed runtime evidence.

A wholesale UI replacement before mission, approval, evidence, connector and cost projections stabilize would couple presentation to unfinished persistence and risk losing trusted desktop approval, voice, remote and accessibility behavior.

## Decision

Keep the current `OnyxUI` callbacks, dashboard protocol and `OrbHost` as the compatibility surface. Add read-only, versioned application-service projections for mission, approval, capability, evidence, workspace, cost, security and domain state. UI code never writes persistence directly.

Migrate incrementally toward one Qt Quick/QQuickView application shell only after callback and state parity is proven. During transition:

- retain exactly one active Orb renderer and one cognition animation clock;
- do not create a second permanent shell or duplicate mission/approval state;
- use public Qt Quick/Qt Quick 3D APIs only;
- load Cyryx design tokens from one source and keep runtime truth labels explicit;
- stop or reduce animation when hidden, minimized, idle, on battery/resource pressure or reduced-motion mode;
- provide keyboard, screen-reader semantics, contrast, scaling and reduced-motion behavior;
- preserve trusted desktop approval and authenticated remote boundaries;
- package QML/modules/resources through existing `resource_root`/package contracts.

The first shell slices are read-only projections inside the current UI. Interactive actions call existing application services. A final shell cutover occurs only after every current callback has an explicit parity test and the previous shell can be restored by one feature flag.

## Truth and performance contract

- UI statuses derive from the capability/evidence source of truth and distinguish verified, partially verified, unverified, blocked and simulated states.
- No cinematic animation may imply cognition, completion, connection or authority that runtime state does not support.
- Idle Orb/UI timers stop or use cached frames; particle/quality budgets adapt to measured frame time and resource pressure.
- Background/minimized operation cannot retain a high-rate renderer without an evidenced requirement.
- Sensitive transcripts, screenshots, approvals and account identifiers follow workspace/redaction policy on desktop and remote surfaces.

## Rollout

1. Inventory current callbacks, shortcuts, overlays, remote messages and accessibility behavior.
2. Add read-only projections to the existing shell and visual-regression fixtures.
3. Implement QML components against projection fixtures without live mutation paths.
4. Connect application-service actions one domain at a time with callback parity tests.
5. Run both shells only in controlled parity tests, never as simultaneous production renderers.
6. Cut over behind `qt_quick_shell_v1` only after functional, security, accessibility, packaging and resource gates pass.
7. Remove the transitional shell only in a later versioned deprecation after rollback evidence and owner acceptance.

## Verification

- Every existing `OnyxUI` callback, approval flow, voice state, Orb state and dashboard interaction has parity coverage.
- Visual regression and responsive tests cover supported scaling, resolution, reduced motion, keyboard and critical status language.
- Authentication/authorization tests prove UI and remote actions cannot write persistence or bypass application services.
- Idle/minimized CPU/GPU, active frame-time, particle budget, memory and startup measurements meet recorded platform budgets.
- Package smoke tests load QML, Qt Quick 3D modules, fonts/assets and fallback paths on each intended host.
- A capability with absent/stale evidence renders blocked/unverified rather than complete.

## Rollback

Disable `qt_quick_shell_v1` and launch the current `OnyxUI`/dashboard callbacks. Projection stores remain read-only and compatible. Stop the new renderer before restoring the old shell so only one Orb/render loop is active. No rollback rewrites mission, memory, approval or evidence data.

## Rejected alternatives

- Rewrite the complete UI before projection contracts stabilize: high functional and truth-parity risk.
- Keep widget and Qt Quick shells permanently active: duplicate resource use and sources of truth.
- Let QML write SQLite or connector state directly: bypasses application services and policy.
- Copy a third-party fictional interface: conflicts with Cyryx identity, ownership and maintainability.
