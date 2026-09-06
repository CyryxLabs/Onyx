# Onyx R15B documentation supersession registry

Updated: 2026-08-11  
Authority: `CURRENT_RELEASE_STATUS.md`  
Formal/public status: **NOT RELEASE-ELIGIBLE**

This registry defines documentation precedence only. It does not rewrite or
delete historical evidence, widen a predecessor receipt, grant legal approval,
or certify a platform without native evidence.

## Current release boundary

- Current installed runtime: **Onyx 1.1.9 Windows x64 R10B**, unsigned
  predecessor, executable SHA-256
  `2e22c12fb60dd1e365c31c63c2879d26f98053e9ef290a47118913de2bb38d6b`.
- Current frozen source candidate: **ONYX-1.1.9-V53-R15B**, 2,821 files,
  141,905,982 bytes, root SHA-256
  `346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45`.
- Source-freeze manifest SHA-256:
  `416ec711f178cac874e005cdcf87e2ea04d7429fe14b585e66e04cd65b4234a5`.
- The first R15B artifact attempt is **rejected**. It produced Setup and
  portable bytes, then failed closed in the isolated Setup smoke because the
  protected R10B soak intentionally kept Onyx resident. Those bytes are not
  release artifacts.
- The fail-closed recovery watcher is armed. It may rebuild from the exact
  manifest-bound source only after the terminal R10B eight-hour soak passes
  and an authenticated cooperative maintenance shutdown succeeds.
- The armed chain independently passed a non-mutating recovery preflight;
  receipt SHA-256 `0656e7917bd3ae1a837413f03a74bea981fd3b095b5ec11ed7dd3aa189e71690`.
  This verifies orchestration inputs and contracts, not build/install execution.
- The bounded R15B Linux container preflight passed no-network DEB/TAR/SPDX,
  exact reconciliation of 109 bundled distributions and disposable Debian
  installation. Receipt SHA-256:
  `57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f`.
  Independent re-verification receipt SHA-256:
  `e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c`.
  Native Linux GUI/audio/session/lifecycle qualification remains open.

## Current navigation authorities

| Document/evidence | Current scope |
|---|---|
| `DOCUMENTATION_INDEX.md` | Entry point and document precedence |
| `CURRENT_RELEASE_STATUS.md` | Exact current operational and release boundary |
| `FINAL_EVIDENCE_INDEX_1.1.9.md` | Current requirement-to-evidence map |
| `docs/stories/ONYX-REL-1.1.9.md` | Active release story and traceable execution record |
| V53 R15B source-freeze manifest | Exact source identity; no artifact/install claim |
| R15B DayOps live receipt | Frozen-source live Graph read, refresh and refresh-token rotation |
| R15B voice-provider live receipt | Frozen-source Gemini native-audio response; no physical-microphone or installed-playback claim |
| R15B Linux container receipt | Bounded no-network build/package/clean-install authority only; no native-host claim |
| R15B independent Linux-container verification | Recalculated artifact, lock, SPDX, offline-license and clean-smoke bindings; public/native boundary retained |
| R15B recovery-chain preflight | Exact source/hash/image/cache, one live watcher and seven downstream scripts; execution remains pending |
| R10B installed acceptance | Exact predecessor Windows installed evidence only |
| R10B legal worklist and blank approval record | Predecessor technical/legal queue only; not R15B approval |

## Superseded for current-state claims

- `DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md` and
  `DOCUMENT_SUPERSESSION_REGISTRY_R8B_2026-08-11.md`;
- every document that identifies V49/R10B or an earlier source as the current
  frozen source;
- every document that identifies R10B long-session attempt 1 or attempt 3 as
  the active terminal soak; attempt 4 is the current run;
- every statement that says Microsoft Graph DayOps live read/refresh/rotation
  is absent; the bounded R15B live receipt passed, while installed-host binding
  remains open;
- every statement that calls the rejected first R15B build a valid candidate,
  or calls R15B built, installed, signed, notarized, legally approved,
  independently reviewed, or natively qualified on Linux/macOS.

Historical records remain valid only within their original candidate and
scope. Their hashes, failures and approvals must not be rebound to R15B.

## Gates still open

- terminal R10B attempt-4 soak, exact R15B rebuild, install, restart and
  consolidated installed-host acceptance;
- physical-microphone, owner-heard natural speech, installed playback,
  interruption/cancellation and offline/failure evidence;
- native Linux GUI/audio/install/upgrade/uninstall/rollback and long-session
  evidence beyond the passed bounded container preflight;
- native macOS build/runtime, Developer ID signing, notarization, stapling,
  Gatekeeper and long-session evidence;
- trusted Windows signing and timestamp verification;
- Cyryx Labs legal approval, including the unresolved `odfpy` disposition;
- final shipped multi-platform SBOM reconciliation;
- clean install, upgrade, uninstall and rollback on disposable native hosts;
- independent final-evidence review with reviewer identity and durable decision.
