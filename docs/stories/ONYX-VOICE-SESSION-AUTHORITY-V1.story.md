# Story ONYX-VOICE-SESSION-AUTHORITY-V1 — Voice-Opened Session Authority V1

**Status:** InProgress (owner decision captured 2026-08-19)
**Epic:** Exact low-risk enablement (the slice the capability matrix names as
the next step for bounded session grants)

## Owner decisions (2026-08-19, explicit)

Asked to choose how a work envelope opens and what runs inside it, the owner
chose:

1. **Opening: voice alone, no confirmation.** The owner was shown, in the
   choice itself, that Onyx has **no speaker verification** and that any audio
   reaching the microphone — another person, a recording, a video — produces
   an indistinguishable transcript, and therefore could open write and
   execution authority over the authorized roots. The owner accepted that
   trade for fluency. This story implements that decision; it does not
   reintroduce a confirmation step.
2. **Scope: read + write + local development.** Inside the envelope, over the
   authorized roots only: list/read/find/info, create/write/edit, and local
   development runs, plus web search. Always explicit regardless of any
   envelope: deleting outside the roots, desktop/other-application control,
   browser control, `git push`, publishing, sending messages, spending, and
   credentials.

## Story

As the Cyryx Labs owner, I want a spoken instruction to open a bounded work
envelope so Onyx stops interrupting me for every ordinary file and
development action, while every consequential or irreversible action still
stops and asks.

## Design

Module `core/voice_session_authority_v1.py`, flag
`ONYX_VOICE_SESSION_AUTHORITY_V1`, default-off, deterministic, hermetic
(injected clock, no I/O). It is installed as the broker's
`governance_authorization_hook`, which the broker consults **before** the
human prompt: returning `(True, reason)` authorizes without interrupting,
`None` defers to the existing approval path, and `(False, reason)` denies.

- `AuthorizedRootV1` — a workspace root the envelope covers, stored as an
  exact absolute path; every candidate path must resolve inside one.
- `VoiceOpenRequestV1` — derived from a transcript. Requires an unambiguous
  multi-word trigger phrase (a single stray word cannot open authority),
  the requested roots, a lifetime bounded by `MAX_LIFETIME_MS`, and an
  operation cap bounded by `MAX_OPERATIONS`.
- `SessionEnvelopeV1` — sealed: roots, `opened_at_ms`, `expires_at_ms`,
  `operation_cap`, `operations_used`, `envelope_id`.
- Decision surface `evaluate(tool, action, arguments, now_ms)` returning
  `allow` / `defer` / `deny`:
  - `deny` when the kill switch is engaged — unconditional, first check.
  - `defer` (never allow) for any `ALWAYS_EXPLICIT` tool/action pair,
    regardless of envelope or roots.
  - `defer` when no envelope is open, when it has expired, or when the
    operation cap is exhausted.
  - `defer` when a path argument resolves outside every authorized root, or
    cannot be resolved safely (traversal, non-absolute, symlinked ancestor).
  - `allow` only for an `ENVELOPE_OPERATIONS` pair whose paths all resolve
    inside the roots and while the envelope is live and under cap.
- Consuming an allowance increments `operations_used`; the envelope closes
  itself at the cap and at expiry.

## Acceptance criteria

1. [ ] Contracts as designed; default-off; hermetic; injected clock.
2. [ ] Kill switch denies unconditionally, ahead of every other rule.
3. [ ] Every `ALWAYS_EXPLICIT` pair defers even inside a live envelope with
       matching roots (delete outside roots, desktop/browser control, push,
       publish, message, spend, credentials).
4. [ ] Path containment: traversal, non-absolute, sibling-prefix
       (`C:\Work2` against root `C:\Work`) and outside paths all defer.
5. [ ] Expiry and operation cap enforced; lifetime and cap bounded at
       construction.
6. [ ] Trigger phrase must be multi-word and exact; a single word or a
       partial match cannot open an envelope.
7. [ ] ≥40 adversarial tests; standard evidence chain; 35-file gate; E6 seal
       with the autonomous-session honesty boundary **and** an explicit
       record of the accepted voice-spoofing exposure.

## Out of scope

Speaker verification (does not exist — recorded as the accepted exposure),
UI wiring of the envelope indicator, persistence across restarts, and the
guild runtime dispatch slice.

## File List

- `docs/stories/ONYX-VOICE-SESSION-AUTHORITY-V1.story.md` (this story)

## Change Log

- 2026-08-19: Opened with the owner's two explicit scope decisions recorded.
