# Onyx 1.1.9 V14 Windows installed acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V14 historical
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for
> the installed-current claim.

Status: **current local Windows candidate passed bounded acceptance; long and formal gates remain open**  
Date: 2026-08-03  
Platform: Windows x64  
Activation: V21 with Phase 5 current-successor V14

## Exact candidate

- Advanced Operations source acceptance: `VE-ADVANCED-OPS-V14-001`
  - 32-file root SHA-256:
    `e2be455f700a9601b7d4cf6b36531d413aff56d2d98dd23d7fc89cf2219ab106`
- First-party build-input seal:
  - 1,293 files
  - root SHA-256:
    `39582f30efc965c197eb5dfc4c40aedaa383a544ce19f0ecb71675edb8ea4689`
- Bundle inventory:
  - 6,782 files
  - root SHA-256:
    `70185def87bb07c5520ed9800491d2b23c08f1b86bb66cb659b05a9271deef8a`
- Setup: `Onyx-1.1.9-Windows-x64-Setup.exe`
  - bytes: `484764267`
  - SHA-256:
    `e120fbdc5b97afc25494ae71e2ccb6a5d74a807765dc384b5a5a9f9c940c3068`
- Portable: `Onyx-1.1.9-Windows-x64-Portable.zip`
  - bytes: `551619228`
  - SHA-256:
    `253376942110ea18084d6de73879b88e2386262a4b8b1d8562dd5a91693cf07e`
- Release-manifest SHA-256:
  `9255dcec35f6f6acba415da39534fa60f7f120b231ed5bcedadfc01db51dedf4`
- Release class: `untrusted-candidate`.

The packaged `_internal/ui.py` and installed `_internal/ui.py` both have the
V14 SHA-256
`b3d9c19a3220826403449e914067c0a67fe01077741a53645aa84e6d52ccbc1e`.

## Build, install and installed inventory

- Full release build exited 0 in 805 seconds.
- Packaged fallback/V21 preflight, native startup, Governance, Founder,
  Document Intake, DayOps, Advanced Operations and Advanced Commands gates
  passed.
- Canonical silent Setup upgrade exited 0.
- Installed version identity is `1.1.9`, publisher `Cyryx Labs`, product
  `Onyx`.
- Installed inventory compared 6,782 expected files: 0 missing, 0 mismatched
  and 0 unexpected application files, excluding only the canonical
  uninstaller pair.
- The packaged shortcut verifier repaired one stale Desktop argument left by
  earlier local shortcut work, then validated both Desktop and Start Menu:
  target is the installed `Onyx.exe`, arguments are empty, working directory
  is the install root and the Desktop icon is `Onyx.exe,0`.

## Installed runtime acceptance

- Installed native startup V21: passed with a real cinematic V5 UI, callbacks
  bound and zero intercepted network, provider or process calls.
- Installed Governance: passed; zero network/provider calls and zero trusted
  UI prompts.
- Installed DayOps disconnected profile: passed read-only with callbacks
  bound and no external calls.
- Installed Advanced Operations: passed with zero background workers and no
  polling interval.
- Installed Advanced Commands: passed with the tool declared exactly once,
  route owned and no host/provider/process/network side effects.
- Installed normal startup from a clean user-like environment opened PID
  `64864`, title `Onyx — Cyryx Labs - Onyx`, connected Gemini Native Audio and
  opened microphone, receive and playback channels.
- A 60.225-second live sample collected six responsive samples, averaged
  0.0843% whole-host CPU, reduced working set from 430,546,944 to 420,319,232
  bytes, reduced private memory from 1,168,072,704 to 1,157,550,080 bytes and
  produced zero Application Error events.

## V14 close-lifecycle result

Eight installed normal-renderer launches each opened a responsive real window,
accepted `CloseMainWindow`, exited within the bounded timeout with code 0 and
produced zero new Windows Application Error events. This directly reaccepts
the lifecycle that previously failed in `Qt6Core.dll` during reentrant QML
destruction.

## Mission/recovery inheritance

Installed `core/missions.py` remains byte-identical to the separately accepted
module:
`7af0c456d14f3e8a3d6dcb49eca017521b386e5d6f519f9f8057abcab5111327`.
The representative create/run/audit/reopen, pause/cancel and crash-to-waiting
recovery/retry result therefore remains applicable. See
`ONYX_1_1_9_V21_INSTALLED_MISSION_RECOVERY_ACCEPTANCE_2026-08-03.md`.

## Technical SBOM

- `release/SBOM.spdx.json` SHA-256:
  `d56839b0efaa95b834d494ca0f425881c46a4552cb1de6140836507d2c14f4e6`.
- Artifact-set root:
  `51fa86b4b033920084f5cc0f06efcc8f9aaadade0464434a5388d2bb10e92484`.
- 141 packages, 6,784 file entries and 6,924 relationships.
- Release eligibility tests: 21 passed, 1 platform skip.
- The live checker reported zero technical reconciliation errors. Its remaining
  eight errors are the intended formal Windows signature/trust/receipt gates.

This is engineering reconciliation, not legal approval.

## Portable and cross-platform source contracts

The 20-test-file portable/security selection passed 190 tests on Windows with
66 platform-native skips. It covers portable activation, host-security
boundaries, POSIX owner/single-instance/trusted-directory contracts, Linux
package permissions, macOS release-pipeline contracts, workspace/dashboard
security and lifecycle behavior. The skips require a real Linux or macOS host
and therefore remain native qualification work; this result does not claim
that either platform is operational.

The exact license/notices packaging audit is recorded in
`ONYX_1_1_9_V14_COMPLIANCE_TECHNICAL_CHECKPOINT_2026-08-03.md`.

## Long-session qualification

Attempt 1 is retained as failed evidence rather than discarded. PID `64864`
exited before the required duration after 900.684 seconds. All 15 collected
samples were responsive, Windows recorded zero Onyx Application Errors,
average whole-host CPU was 0.1444%, maximum working set was 422,166,528 bytes
and maximum private memory was 1,171,582,976 bytes. There is no crash receipt;
the evidence only proves `process_exited_before_duration`, so no cause is
invented. Its immutable copies are:

- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt1-samples.csv`
- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt1-receipt.json`

Attempt 2 started after the test suites completed as a child of the automation
shell. PID `67792` produced one responsive sample and then exited after 60.121
seconds with zero Application Errors. This is retained as launcher-bound
diagnostic evidence, not counted as the long-session gate.

Attempt 3 started Onyx through the Windows user shell, equivalent to opening
its installed icon and independent of the command job. PID `27444` produced
three responsive samples and then exited after 180.397 seconds with zero
Application Errors. It processed real Onyx tools before exit, but neither its
log nor the prior monitor captured an exit code; no cause is asserted.

Attempt 4 used the same user-shell launch with no concurrent test suite. PID
`66456` exited normally with exit code `0` after 1,200.563 seconds. All 20
samples were responsive, Windows recorded zero Onyx Application Errors,
average whole-host CPU was 0.1347%, maximum working set was 416,808,960 bytes,
maximum private memory was 1,189,289,984 bytes and private growth was
29,409,280 bytes. The authenticated tool audit contains no `shutdown_onyx`
request during this attempt; consequential tool attempts were denied and the
last completed tool was `web_search` six minutes before exit. The evidence is
consistent with a normal window close, but no unrecorded user action is
invented and the duration gate remains failed. Its records are:

- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt4-samples.csv`
- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt4-receipt.json`

Attempt 5 ran the same installed candidate minimized, without changing its
activation, provider or runtime. PID `17364` exited normally with code `0` after
4,201.795 seconds. All 70 samples were responsive, Windows recorded zero Onyx
Application Errors, average whole-host CPU was 0.1542%, maximum working set was
434,806,784 bytes, maximum private memory was 1,180,155,904 bytes and private
growth was 3,510,272 bytes. The last governance event was a new active Gemini
session at `2026-08-04T02:07:28.544Z`; no matching `session-ended`, audited
`shutdown_onyx`, Windows power transition or Onyx Application Error preceded
the process exit at approximately `02:09Z`.

Source diagnosis found that the Qt event loop could return while the live
runtime still owned an active provider session. The runtime thread was a daemon,
so process termination could report exit code zero without running its governed
cleanup. The post-V14 source now owns a non-daemon runtime thread, dispatches a
thread-safe shutdown request, does not swallow explicit asyncio cancellation,
waits for cleanup after Qt returns, prevents auxiliary last-window closure from
implicitly ending the application and emits explicit Qt lifecycle records. The
focused lifecycle/activation regression selection passes 140 tests. This fix is
not present in installed V14; attempt 5 remains failed duration evidence and a
traceable successor rebuild is required before another qualifying soak.
Evidence paths are:

- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt5-samples.csv`
- `%LOCALAPPDATA%\Cyryx Labs\Onyx\runtime\verification\onyx-1.1.9-v14-soak-attempt5-receipt.json`

The long gate is `SOURCE_FIX_READY_REBUILD_REQUIRED`. A new eight-hour run may
start only from the rebuilt successor bytes and must pass every threshold with
an orderly, recorded cleanup at the end.

## Still open

- Owner acoustic confirmation that the heard voice is Charon and spoken
  owner-name correction persists across a full restart.
- Traceable successor rebuild followed by a complete eight-hour receipt using
  the corrected Qt/runtime ownership path.
- Live Microsoft Graph/Entra acceptance.
- Authenticode and trusted native Windows receipt on a clean disposable host.
- Legal/notices approval and independent final evidence review.
- Separate native Linux and macOS build/install/audio/GUI/lifecycle evidence;
  macOS additionally requires Developer ID, notarization and stapling.
