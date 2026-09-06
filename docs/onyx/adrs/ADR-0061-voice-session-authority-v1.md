# ADR-0061 — Voice-opened session authority V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

The capability matrix records the permission broker's limitation exactly:
*"No persisted bounded grants or approval inbox."* Every consequential action
therefore stops and asks, one at a time, which is why ordinary file and
development work feels blocked even though `file_controller`, `code_helper`
and `file_processor` are all `WORKING_WITH_LIMITATIONS` and installed.

The accepted `session_grants_v11` cannot fix this: it is a shadow evaluator
whose decisions carry `authority_granted=False` and `callback_required=True`
as `init=False` fields — it can only say *"I would allow"*. The accepted
`approval_inbox_v15` is likewise a read-only, non-authoritative projection.
The matrix names the missing piece: *"Build and independently accept the
exact low-risk enablement slice; never waive always-explicit gates."* This
ADR records that slice.

## Owner decisions (2026-08-19)

Presented with the trade-offs in the choice itself, the owner decided:

1. **Voice alone opens the envelope, with no confirmation step.** The choice
   text stated plainly that Onyx has no speaker verification and that any
   audio reaching the microphone — another person, a recording, a video —
   produces an indistinguishable transcript that could open write and
   execution authority over the authorized roots. The owner accepted that
   exposure for fluency.
2. **Scope: read + write + local development**, over the authorized roots.

## Decision

Add `core/voice_session_authority_v1.py`, default-off
(`ONYX_VOICE_SESSION_AUTHORITY_V1`), deterministic, hermetic (injected clock,
no I/O), installed as the broker's `governance_authorization_hook` — the
extension point the broker already documents as "the V16 exact
low-risk/kill authority", consulted before the human prompt. It enforces,
structurally:

1. **Kill switch first.** Engaged, every evaluation denies before any other
   rule, the open envelope closes, and no envelope may reopen.
2. **Always-explicit is absolute.** `ALWAYS_EXPLICIT` pairs defer regardless
   of envelope or roots: `file_controller.delete` (deletion stays explicit
   even inside an authorized root), `organize_desktop`, and every action of
   `browser_control`, `computer_control`, `desktop_control`,
   `computer_settings`, `send_message`, `dev_agent` and `game_updater`.
3. **Root containment by whole path components.** Every path argument across
   nine argument keys must resolve inside an authorized root; traversal,
   relative paths, unusable values and sibling-prefix lookalikes
   (`C:\Work2` against root `C:\Work`) all defer.
4. **Bounded envelopes.** Lifetime is clamped to 1 minute–8 hours and the
   operation cap to 1–10,000 at construction; expiry or cap exhaustion
   returns the session to asking.
5. **Unambiguous opening.** The transcript must contain an exact trigger
   phrase of at least three words, so a single stray word cannot open
   authority. Matching is case- and whitespace-insensitive.
6. **Allow is the only grant.** The hook returns `True` solely for an
   in-scope, in-root operation under a live envelope; `False` only for the
   kill switch; `None` for everything else, leaving the existing approval
   path untouched.

## Consequences

- Ordinary reading, writing and local development inside the owner's roots
  stops interrupting, which is the stated goal.
- **Accepted exposure, recorded not hidden:** without speaker verification,
  a spoofed or accidental transcript can open an envelope. The mitigations
  bound the blast radius — exact phrase, bounded lifetime and cap, root
  containment, the always-explicit set and the kill switch — they do not
  prevent a spoofed opening. Adding speaker verification would change this
  and belongs to a later, separately reviewed slice.
- This is the first Onyx contract that grants authority rather than
  shadowing it, so its adversarial suite is the safety argument and must
  stay exhaustive.

## Alternatives considered

- Wiring `session_grants_v11` directly: rejected — impossible by
  construction; its decisions can never grant authority.
- Requiring one confirmation per envelope: rejected by the owner, who chose
  voice-alone opening after being shown the exposure.
- Allowing deletion inside authorized roots: rejected — deletion is the
  least reversible local action, so it stays explicit even in scope.
- Trusting a single wake word: rejected — a three-word exact phrase is the
  cheapest defence against incidental audio and costs the owner nothing.
