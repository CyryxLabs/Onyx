# Onyx 1.1.9 V21 Windows installed acceptance

Status: **superseded predecessor candidate; retained as historical evidence**  
Date: 2026-08-03  
Platform: Windows x64

The current rebuilt Advanced Operations candidate is recorded in
`ONYX_1_1_9_V21_ADVANCED_OPERATIONS_WINDOWS_ACCEPTANCE_2026-08-03.md`. Hashes
below identify this earlier package only and must not be used for the current
installation.

## Candidate identity

- Setup: `Onyx-1.1.9-Windows-x64-Setup.exe`
  - bytes: `484747890`
  - SHA-256: `96f18a52e2de9e0da4d3e5e59cdb4b96253aca0e37756c8d16abb43c5ffe9677`
- Portable: `Onyx-1.1.9-Windows-x64-Portable.zip`
  - bytes: `551600696`
  - SHA-256: `857362a8f9947755db848688ee77d64fd1be3f79e57c25cdb95586492ba4fcfb`
- Build-input seal: 1,293 files, root SHA-256
  `00cacdbe9b0dd7cc3abf9707fad41020e981d03e4c83f25726699873c3e32db4`.
- Bundle inventory: 6,782 files, root SHA-256
  `4298f52063a6ee69a22b0f92947d1abc8416fb61157e55db444b6eca52efcd8d`.
- Authenticated source succession: V11 record SHA-256
  `a6153df617e9af19f82a21ee00802a2a48c22af736a3b22e437b41705608cd89`;
  domain root
  `4941c6e585837e3c7c8d2b679749acafd7807c2b5cf79faeb6a19addcb4a200f`.
- Release class remains `untrusted-candidate` because Authenticode signing and
  final independent release review are not complete.

## Corrections included

1. The stable V21 bootstrap now migrates a recognizable canonical V19
   predecessor that legitimately lacks old workspace-root/audit values. It
   reconstructs the missing root, preserves a complete exact executable
   sandbox tuple, and refuses any divergent, incomplete or unknown control
   flag.
   The same migration now runs before the delegated governance, Founder and
   document-intake diagnostics, so installed diagnostics cannot observe a
   partially migrated activation environment.
2. V20 transfers exact `OnyxLive.__init__` seam ownership to the installed
   Phase 6 wiring controller and restores it atomically on rollback. This
   removes the installed `installed wiring seam diverged: __init__` voice
   degradation without replacing Gemini Live, Charon or the existing engine.
3. PortAudio output `start`, `write`, `stop` and `close` now have one thread
   owner. The previous cancellable `asyncio.to_thread(stream.write, ...)`
   could close a native stream while its worker still wrote to it and produced
   Windows `0xc0000374` heap-corruption crashes after the first voice turn.

## Verification results

- Final-source integrated V20/V21, Phase 6, Advanced Operations, native
  release, package hygiene, governance isolation and audio-owner selection:
  128 passed.
- Audio-owner regression proves `start/write/stop/close` execute on the event
  loop thread.
- Full Windows release build: exit 0; packaged fallback, V21 startup,
  governance, Founder, document intake, DayOps, Advanced Operations, Advanced
  Commands, package hygiene, isolated Setup install/start/uninstall and
  archive gates passed.
- Canonical Setup installation: exit 0; installed product version 1.1.9.
- Installed inventory: the first immediate post-install read briefly observed
  one unavailable path; an immediate presence check and the required second
  full hash pass then proved 6,782 expected, 0 missing and 0 mismatched. No
  transient first-pass result is treated as acceptance authority.
- Installed inventory also had 0 unexpected application files; the two
  additional files are the canonical installer uninstaller pair.
- Installed package hygiene: passed.
- Installed Governance smoke: exit 0 and `status=passed`; zero provider,
  network and trusted-UI-prompt calls.
- Installed Advanced Commands V21 smoke: exit 0; one exact tool declaration,
  owned route, zero background workers and zero network/provider/process calls
  in the intercepted diagnostic.
- Normal installed startup reached V21, connected the Gemini Native Audio
  provider and opened `Mic`, `Mic stream`, `Recv` and `Play`. No system-TTS or
  alternate-voice fallback was introduced.
- The installed application remained alive and responsive for the 90-second
  acceptance sample. The previous defective build failed at approximately 50
  seconds. A separate automation-owned launch was terminated with its shell
  job and produced no crash, dump, WER event or traceback; the canonical
  Explorer launch is the acceptance authority.
- After startup settled, cumulative CPU was 8.36 CPU seconds across 90 seconds
  (about 9.3% of one logical core and below 1% of the whole host); working set
  stabilized near 404-406 MB. This is a short acceptance sample, not
  the required multi-hour thermal/leak qualification.
- Windows Application log: zero new Onyx `Application Error` events during the
  final installed acceptance interval.
- UI observation: one window titled `Onyx — Cyryx Labs - Onyx`, cinematic HUD
  V9, official Orb, owner address `Sir`, `VOICE READY`, `PRESENT`, and owner
  autonomy active.
- Final Windows technical SBOM generation and artifact reconciliation passed:
  SPDX SHA-256
  `aaef8fd652a865551932ec38e4bcc5de38652b5880c48202ebb6b551799eb186`,
  artifact-set root
  `c1079b391ab687b3486cf0b7614a39d92360a2fc98bc070b709e3a45979dadf8`,
  141 packages, 6,784 file entries and 6,924 relationships. The focused
  release-eligibility suite reported 21 passed and 1 platform skip. This is
  technical reconciliation only; it does not close legal approval.

## Open acceptance boundaries

- The owner must still hear and accept the natural Charon voice acoustically;
  logs prove the native audio channels, not human perception.
- A real spoken owner-name correction and full restart must still prove
  persisted identity end to end.
- A representative installed mission create/run/cancel/recover sequence and a
  full-duration soak remain open.
- The exact-candidate eight-hour monitor is active outside the source tree at
  `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\monitor-onyx-1.1.9-v21-final.ps1`.
  It samples once per minute and emits a hash-bound JSON receipt; merely
  starting the monitor is not a pass.
- Live Microsoft Graph DayOps requires Entra registration and owner consent.
- Authenticode signing, a clean disposable Windows host, final notices/legal
  approval and independent evidence review remain open.
- macOS and Linux require separate native build/install/audio/GUI/lifecycle
  evidence. Windows results cannot qualify those platforms.
