# ADR-0020 — Activation V10 Requires Accepted HUD V7

Status: **Accepted for C003 candidate construction; runtime default-off**

## Decision

Activation V10 may compose only:

1. Activation V9 E6;
2. Phase 6 Live Wiring V1 E6;
3. Phase 5 Exit Candidate V2 E6;
4. HUD / Orb V7 C003 E6.

V10 requires exact `ONYX_HUD_V7_LIVE=1` and hash-bound HUD V7 code,
candidate manifest, E6 record and E6 metadata. Missing, partial, aliased or
unbound evidence refuses before importing `main` or `ui`, creating the wiring
state root, activating V9, constructing Wiring V1, or changing a shortcut.
The loaded module origin and exact install/uninstall code objects are attested
again in memory before the API is called.

## Rationale

V9's HUD V6 remains an accepted predecessor surface but is not approved as the
final V10 visual surface. Allowing V10 to start without a separately accepted
HUD V7 would silently present V6 as V10 and repeat the version ambiguity that
V10 is intended to remove.

## Bound transition

HUD / Orb V7 C003 has independent E6 acceptance. C002 binds exactly its module,
candidate manifest, E6 record and E6 metadata without directory discovery.
The planned order is V9 ready, HUD V7 replaces V6 through
`install_candidate(ui_module) -> bool`, Wiring V1 installs against the embedded
exact V7 authority, V10 shortcut/setup seams install, the C003 secure
onboarding seam is installed before `MainWindow` construction, and then
`main.main()` is called.

Rollback reverses V10 setup/shortcut, closes Wiring V1 sessions and restores
its three lifecycle seams, calls exact
`uninstall_candidate(ui_module) -> bool`, restores the exact V9 surface, and
retains accepted V9 installed.

Source-checkout CMD controls normalize to `%~dp0..` before resolving the
environment or launcher. The V10 surface refreshes the canonical shortcut after
construction for an already-configured Windows owner as well as after future
setup completion.

C003 treats the reconciled unknown-owner state as ready only when the secure
credential is configured, the non-secret settings file is safely readable and
`os_system` is one of Windows, macOS or Linux. Blank and known placeholder
owner values retain the literal `Sir` fallback and exact V4 first-contact
question. Missing credentials, missing/invalid OS settings and unreadable
configuration still open setup. Rollback restores the exact V9
`_check_config` method from immutable private authority.

## Consequences

- V10 C003 is complete for external gate, default-off, unwired and not live.
- The existing V9 live process and shortcut remain unchanged.
- The candidate does not claim a Phase 6 user route, provider operation,
  Phase 6 exit, physical handoff or Onyx completeness.
- Phase 5 C2 is bound by its accepted historical envelope; V10 does not rerun
  obsolete startup discovery against a future version.
