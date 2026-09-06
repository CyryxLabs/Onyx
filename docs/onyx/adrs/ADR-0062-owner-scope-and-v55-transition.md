# ADR-0062 — Owner working scope, and the V55 current-successor transition

## Status

Accepted (owner directive, 2026-08-21; implemented 2026-08-22).

## Context

Three defects made Onyx unusable as a daily assistant, and they compounded so
that fixing one did not visibly fix anything:

1. **Approvals were recorded as refusals.** The launcher activates the
   governance chain before `main()` creates the UI, so the trusted callback was
   `None` at install time, the approval inbox never wrapped it, and the dispatch
   fence denied every approved action. Fixed separately; proven in the live
   ledger (`approval-inbox` intent → approved → receipt).
2. **Owner autonomy was inert.** The broker consulted it only when no governance
   nucleus existed, and one always exists in production. The configured
   `autonomous` profile and workspace roots therefore did nothing.
3. **Onyx could not see the owner's Desktop.** `actions/file_controller.py`
   guessed `Path.home() / "Desktop"`, which on Windows resolves to an
   almost-empty stub whenever OneDrive backs the folder up. Onyx read 8 entries
   where the owner had 42, and answered confidently about the wrong directory.
   The same function already honoured `XDG_DESKTOP_DIR`; only Windows Known
   Folder redirection was missing.

Beyond the defects, the owner rejected the confinement model itself. The prior
design (ADR-0061) bounded work to authorized roots and kept deletion always
explicit. In practice that produced a prompt for nearly every useful action.

## Owner decision (2026-08-21, verbatim intent)

> The restriction will be solely never to erase, move, delete or alter **system
> files** without my permission. Everything else he is authorised to open,
> write, read, create, organise, and everything else a "Jarvis" would do.

This inverts the model: **free by default, restricted by exception**, where the
exception is operating-system and installed-program files.

## Decision

**Scope.** `_OWNER_EVALUABLE_TOOLS` declares the tools that act on the owner's
own machine as *evaluable* rather than always-explicit: file controller and
processor, browser, computer, desktop and settings control, code helper,
media and app launching, memory and reminders. Deletion of the owner's own
files is included, per the decision above.

**The one restriction.** `_is_protected_system_path` refuses any create, write,
move, rename, delete or organise whose resolved target lies inside
`%SystemRoot%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`,
`Recovery`, `$Recycle.Bin`, `System Volume Information`, or a bare drive root
(POSIX equivalents on other platforms). Matching is by whole path component,
so `C:\Windows2` is the owner's, not the system's. The pre-existing refusals to
modify Onyx's own source tree and to traverse symlinks or reparse points are
retained unchanged.

**Two gates, not one.** The nucleus refuses `always_explicit` and `critical`
work before the evaluator is consulted at all; the evaluator then independently
confirms the owner's configured profile and the system-path restriction. An
autonomous authorization is **single-shot** — reusable grants remain reserved
for exact low-risk reads — and it records an action-intent, so it satisfies the
dispatch fence exactly as a human approval does.

**Deliberately still explicit**, and not covered by the owner's rule:

| Tool | Why |
|---|---|
| `send_message` | acts outward, on the owner's behalf |
| `shutdown_onyx` | ends the session needed to intervene |
| `dev_agent` | executes arbitrary code, so no path rule can hold the system-file restriction against it |
| `mission_create` / `mission_cancel` | starts or stops long-running autonomous work |

## The V55 transition

`ui.py`, `main.py` and `dashboard/server.py` are tombstoned historical
artifacts in the Phase 5 chain, tracked by digest. Two required fixes live in
those files:

- the approval prompt now surfaces its window before blocking, and its timeout
  moves from 120 s to 600 s — bounded inside the governance binding's 900 s
  validity, so an approval can never land against an expired binding;
- the dashboard accepts and prefers a mesh (RFC 6598) address, which
  `is_private` reports as `False` and which the previous scoring would have
  ranked last, so a phone outside the LAN could never reach the host.

Editing them invalidated V54 and, fail-closed, blocked **both** the entire test
suite and the build. V55 is additive and preserves the chain's own policy
(`historical_hashes_are_rebound: false`): V54 stays immutable, its root is
re-derived from its own recorded values rather than from disk, identity tuples
carry across unchanged, and only `current_sha256` pointers advance. The root is
bound under a distinct `…-V55\0` domain. HUD V31 was rebound with the project's
existing `generate_hud_v31_manifests.py`, preserving the immutable V30
predecessor pins.

## Consequences

- Ordinary work — reading, writing, creating, organising, deleting the owner's
  own files, driving the browser and desktop — proceeds without interruption.
- **Deletion of the owner's files is now autonomous and is irreversible.** This
  was the owner's explicit instruction, recorded here rather than softened.
- The blast radius of a mistaken instruction is larger than under ADR-0061.
  The system-path restriction, the source-tree refusal, the symlink refusal and
  the always-explicit set above are what remain.
- Editing a tombstoned file now has a known, repeatable cost: generate the next
  transition and rebind HUD V31. That cost is documented rather than
  rediscovered.

## Alternatives considered

- **Deleting the `governance is None` guard** to enable autonomy: rejected — it
  reproduces the original P0, because the autonomy branch returns a non-empty
  proof with no registered intent, which the dispatch fence rejects.
- **Letting the evaluator override `always_explicit`**: rejected — it would
  dissolve the only absolute boundary in the design.
- **Rebinding V54 in place**: rejected — the chain's policy forbids rewriting
  historical hashes, and an additive successor keeps every prior root
  reproducible.
- **Widening `send_message` and `dev_agent` with the rest**: not taken. Neither
  is a local file action, and `dev_agent` can execute code that bypasses the
  path restriction the owner asked for. Available on request as a separate,
  explicit decision.
