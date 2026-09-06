# Voice session authority V1 checkpoint

The exact low-risk enablement slice the capability matrix names as the next
step for bounded session grants: the first Onyx contract that grants
authority rather than shadowing it. It adds one module, one feature flag and
no runtime wiring.

`core/voice_session_authority_v1.py` (`ONYX_VOICE_SESSION_AUTHORITY_V1`,
default-off, deterministic, hermetic, injected clock) is designed to install
as the permission broker's `governance_authorization_hook`, which the broker
consults before the trusted-host prompt. It returns `True` only for an
in-scope, in-root operation under a live envelope, `False` only when the kill
switch is engaged, and `None` for everything else so the existing approval
path is unchanged.

An envelope opens from a transcript carrying an exact trigger phrase of at
least three words, over one to sixteen absolute authorized roots, with a
lifetime clamped to one minute through eight hours and an operation cap of
one through ten thousand. `ENVELOPE_OPERATIONS` covers reading, writing and
local development plus web search — the owner's chosen scope.
`ALWAYS_EXPLICIT` defers unconditionally and includes
`file_controller.delete` inside authorized roots, `organize_desktop`, and
every action of `browser_control`, `computer_control`, `desktop_control`,
`computer_settings`, `send_message`, `dev_agent` and `game_updater`. Path
containment compares whole path components across nine argument keys, so a
sibling prefix such as `C:\Work2` never passes as inside `C:\Work`. The kill
switch denies ahead of every other rule, closes the envelope and blocks
reopening. The module calls no model, opens no network, spawns no process,
persists nothing and reads no clock.

The cumulative selection reproduces 977 passing tests and 96 passing subtests
across thirty-five fresh Python processes — the thirty-four files of the
accepted guild project-envelope selection plus this slice's sixty-seven
adversarial tests — with seventeen platform-specific skips and zero
failure/error.

**Accepted exposure, recorded not hidden.** Onyx has no speaker
verification, so a transcript from any source near the microphone is
indistinguishable from the owner speaking. The owner was shown this and
chose voice-alone opening without a confirmation step (2026-08-19). The
mitigations here bound the blast radius; they do not prevent a spoofed
opening. Adding speaker verification is later, separately reviewed work.

Scope and limits: decision contract only. No runtime wiring, no UI envelope
indicator, no persistence across restarts, no approval-inbox coupling, and
no claim that the full Onyx PRD is complete.
