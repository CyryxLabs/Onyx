# ADR-0019: Default-off post-V7 lifecycle wiring for Phase 6 V2

Status: Candidate — additive, strict default-off, not live

Date: 2026-07-23

## Context

Agentic Core V6 and Live Integration V2 are externally accepted only as
isolated, default-off implementation handoffs. Onyx Live Activation V7 is a
separately accepted default-off host transition. V7 performs exact pre-import
identity validation, installs and starts its accepted V4-V7 seams, then calls
the unchanged `main.main()`.

The real host lifecycle creates `main.OnyxLive`, creates one exact Phase 5 V3
bridge in `_start_phase5_session`, and revokes/terminates it in
`_stop_phase5_session`. Live Integration V2 cannot be constructed before that
runtime bridge exists. Direct edits to V7, `main.py`, UI, dashboard or launchers
would invalidate accepted anchors.

The first wiring slice therefore needs to bind V2 to the existing Phase 5
session lifecycle without changing provider, circuit, replay, tool-dispatch or
UX surfaces and without activating itself.

## Decision

Add `core/phase6_live_wiring_v1.py` behind the exact
`ONYX_PHASE6_LIVE_WIRING_V1=true` gate. Its factory returns `None` before
validating an activation, path, executor or dependency when off. No live module
imports the candidate.

The sealed factory accepts only:

- the exact feature gate;
- an exact installed and `READY` `OnyxLiveActivationV7`; and
- an explicit absolute local state root.

Identity, Agentic Core, MissionStore, workspace scope, Phase 5 bridge, V2
facade, text invoker and executor cannot be supplied by the caller.

### Identity and authority

`LiveWiringIdentityV1` is frozen and contains the complete
`workspace_id + account_id + profile_id + principal_id` tuple. It is derived
only from exact V7 flags, compared with the accepted V7 preflight probe, and
compared again with every runtime Phase 5 V3 bridge before file or executor
construction.

The wiring reuses the exact `MissionStore` already owned by the `OnyxLive`
instance. It derives one confidential `WorkspaceScopeV1` from the unchanged
host `get_base_dir()` authority. It internally invokes the exact frozen
`create_phase6_agentic_core_v6` and sealed
`create_phase6_live_integration_v2` factories.

### Transactional lifecycle patch

Construction does not patch the host. Explicit `install()` transactionally
wraps exactly three post-V7 class seams:

1. `OnyxLive.__init__` — reserves one private session slot;
2. `OnyxLive._start_phase5_session` — calls the accepted host start first,
   attests the resulting exact Phase 5 V3 bridge, then constructs Core V6 and
   Integration V2;
3. `OnyxLive._stop_phase5_session` — closes the V2 facade before calling the
   accepted Phase 5 teardown.

Failure before or after any of the three patch writes restores the exact
post-V7 functions. Runtime construction failure revokes the newly created
Phase 5 bridge and leaves no attached V2 session. Rollback closes tracked V2
sessions, removes the private instance slot and restores the exact post-V7
lifecycle functions.

The wiring never patches `_execute_tool`, `_run_live_loop` or
`_send_realtime`. V7 remains authority for tool replay, reconnect containment,
provider circuit behavior and Gemini Live transport. V2 remains authority for
the exact terminable text executor and its wall timeout/cancellation/privacy
contracts.

### Session-scoped persistence

Each runtime Phase 5 binding yields a collision-resistant session directory
derived from SHA-256 over its session ID, trace ID and full identity digest.
Agentic state and V2 receipt paths are scoped beneath that directory. A second
reconnect therefore cannot reuse the first connection's files accidentally.

The state root must be absolute and its currently existing ancestry must not
contain a symlink or Windows reparse point. The path is checked before
construction and after directory creation. This is a best-effort local path
hardening check; it is not a strong cross-process TOCTOU guarantee.

## Consequences

- Core V6, Live Integration V2, Activation V7, `main.py`, UI, dashboard, QML,
  runtime, packaging and launchers remain byte-exact.
- Off creates no file, thread, child process, executor or patch.
- Explicit construction still does not install; explicit `install()` is a
  second deliberate action.
- Installed wiring attaches the already accepted V2 facade to connection
  lifecycle only. It exposes no new UI, command, tool or planner route.
- No provider/network call is made by construction, installation or lifecycle
  attachment.
- The candidate does not activate the live host or satisfy Phase 6 exit.

## Rollback

Leave the feature flag unset or not exactly `true` and do not import/construct
the candidate. If explicitly installed in a future independently authorized
host, call `rollback_installation()` before rolling back V7. It closes attached
V2 sessions and restores the exact post-V7 lifecycle functions.

## Rejected alternatives

- Editing V7 or its launcher: rejected because accepted bytes must remain
  reproducible.
- Editing `main.py` lifecycle methods: rejected for the same reason.
- Constructing V2 before Phase 5 start: rejected because the authoritative
  runtime identity and bridge do not yet exist.
- Accepting caller-supplied identity, core, MissionStore, adapter, invoker or
  executor: rejected because it would widen authority and reopen the V1
  substitution defect.
- Patching `_execute_tool` to expose Phase 6 commands: rejected because UX and
  command routing require a separate capability contract and acceptance.
- Sharing one receipt path across reconnects: rejected because a new Phase 5
  session needs an unambiguous lifecycle boundary.
