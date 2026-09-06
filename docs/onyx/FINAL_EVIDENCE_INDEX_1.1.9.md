# Onyx 1.1.9 final evidence index

Status: **INCOMPLETE — V53 R15B SOURCE FROZEN; R10B PREDECESSOR INSTALLED;
FORMAL GATES OPEN**  
Installed product: **Windows x64 R10B, unsigned/untrusted predecessor**  
Frozen source candidate: **V53 R15B, root `346dcba1...f45`**  
Updated: 2026-08-11

This is the current requirement-to-evidence map. It is not a public-release,
legal or independent approval record. The first R15B Windows artifact attempt
is rejected and therefore supplies no final Setup, portable or installed-product
authority. A separate bounded Linux container preflight passed, but it is not a
native-host qualification or final shipped multi-platform authority.

## Candidate identity

| Evidence | Exact value | State |
|---|---|---|
| Source freeze | 2,821 files; 141,905,982 bytes; root `346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45` | Passed |
| Source-freeze manifest | `C:/MAAX_Assistant/Onyx-V53-Source-Candidate-R15B-20260811.SOURCE_FREEZE.json`; SHA-256 `416ec711f178cac874e005cdcf87e2ea04d7429fe14b585e66e04cd65b4234a5` | Passed |
| Recorded Git revision | `355504cb86e97e368dc575f9968ecf4c0fabe994` with recorded dirty-worktree digest | Traceability reference, not a clean commit or remote release |
| Frozen verification | Windows 196 passed/54 skipped; Linux container 171 passed/79 skipped plus 2 subtests; release gate 105 passed | Passed within recorded source/container scope |
| First R15B build | Setup and portable bytes reached artifact stage, then isolated Setup smoke refused shutdown of the protected R10B runtime | Rejected; not release evidence |
| Failed-build input preservation | `Onyx-Release-Orchestration/r15b-build-recovery/ONYX_1_1_9_R15B_FAILED_BUILD_INPUT_PRESERVATION.json`; SHA-256 `44ab4a7155d30e753df689fcee286d5ad546b28df38243f7ee6b4082a75f74d0` | Passed for all 2,821 source inputs; generated outputs explicitly excluded from source identity |
| Recovery orchestration | `Onyx-Release-Orchestration/recover-r15b-build-after-r10b-soak.ps1` | Armed; waits for terminal attempt-4 soak and authenticated cooperative shutdown |
| Recovery-chain independent preflight | `Onyx-Release-Orchestration/r15b-build-recovery/ONYX_1_1_9_R15B_RECOVERY_PREFLIGHT.json`; SHA-256 `0656e7917bd3ae1a837413f03a74bea981fd3b095b5ec11ed7dd3aa189e71690` | Passed exact source/hash/image/cache, single live watcher and seven-script parse/contract verification; explicitly does not prove execution, build, install or acceptance |
| Current installed executable | R10B SHA-256 `2e22c12fb60dd1e365c31c63c2879d26f98053e9ef290a47118913de2bb38d6b` | Predecessor evidence only; R15B not installed |
| R15B Linux container preflight | `Onyx-Release-Orchestration/r15b-linux-preflight/ONYX_1_1_9_R15B_LINUX_CONTAINER_GATE_RECEIPT.json`; SHA-256 `57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f` | Passed no-network DEB/TAR/SPDX, 109-distribution lock reconciliation and disposable Debian install; native desktop/audio/lifecycle and public release remain open |
| Independent Linux container verification | `Onyx-Release-Orchestration/r15b-linux-preflight/ONYX_1_1_9_R15B_LINUX_CONTAINER_GATE_INDEPENDENT_VERIFICATION.json`; SHA-256 `e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c` | Recalculated source, image, artifact, manifest, lock, SBOM, offline-license and clean-smoke bindings; retained native/public NO-GO boundary |

## Bounded live integrations

| Gate | Authoritative evidence | State and limitation |
|---|---|---|
| Microsoft Graph DayOps | `C:/MAAX_Assistant/Onyx-Release-Orchestration/ONYX_1_1_9_R15B_DAYOPS_LIVE_E2E_RECEIPT.json`; SHA-256 `20569b3c16c82301d5f787398f689ed2afdd545dfb29b3bde2885a7c36ccfcd0` | Passed frozen-source live calendar/mail read, access refresh and refresh-token rotation with least-privilege scopes; installed binding, revocation and live failure/rate-limit events remain open |
| Voice provider native audio | `C:/MAAX_Assistant/Onyx-Release-Orchestration/ONYX_1_1_9_R15B_VOICE_PROVIDER_LIVE_RECEIPT.json`; SHA-256 `fb9128ecfddf479528176e19991cade497e3e0c0f81890e37c309449aac06684` | Passed Gemini native-audio response: 2.44 s, 24 kHz mono WAV; physical microphone, owner-heard quality and installed playback remain unproven |

## Windows installed acceptance boundary

R15B installed-host acceptance is **not yet available**. Current installed
evidence belongs to R10B and must not be widened to R15B.

| Gate | Current evidence | State |
|---|---|---|
| R10B installed acceptance | `C:/MAAX_Assistant/Onyx-V49-Windows-Candidate-R10B-20260811/acceptance/installed-r10b/ONYX_1_1_9_R10B_INSTALLED_ACCEPTANCE_RECEIPT.json`; SHA-256 `1dd7b080086cde9ea092aa04cba53cb0da1c5b5a822757944acc3aa2fd577a31` | Passed bounded predecessor scope |
| R10B technical compliance | Receipt SHA-256 `7aeefaeebb22a1becb93b0a568756234918c259a408dfaae6a9a7dc33ddb6e6f`; SPDX `b335a9a8b33f287bd9b8e91dba7d0ef20bfa8cf163701f2134bd8cb8ee799dd3` | Passed unsigned Windows predecessor scope; public false and legal approval false |
| Long session | `long-session-r10b-attempt4/ONYX_1_1_9_R10B_WINDOWS_LONG_SESSION_ATTEMPT4_RECEIPT.json` | In progress against PID 32064; requires 28,800 seconds, responsive terminal state and zero application errors |
| R15B build/install/startup | Fresh exact post-soak build and installed receipts | Pending |
| R15B name/identity restart persistence | Installed authenticated voice-command and restart receipt | Pending |
| R15B Orb motion/performance | Installed direct-frame/state/reduced-motion plus CPU/memory/soak receipts | Pending |
| R15B missions/permissions/recovery | Consolidated installed lifecycle and governance receipts | Pending |
| Clean install/upgrade/uninstall/rollback | Disposable clean-host receipts | Missing |
| Authenticode | Trusted signature and timestamp receipts for final bytes | Missing |

## Compliance and final-platform matrix

| Roadmap requirement | Authoritative evidence required | Current state |
|---|---|---|
| macOS artifacts signed and notarized | Native final build, Developer ID signature, notarization, stapling and Gatekeeper receipts | Missing — real Mac and Apple credentials required |
| Third-party notices and final license approved | Final-artifact worklist and completed `LEGAL_RELEASE_APPROVAL_1.1.9.md` with authorized decision | Open — R10B technical packet approves 0; `odfpy` unresolved; no R15B/final approval |
| SBOM reconciled to final shipped artifacts | Post-signing aggregate SBOM bound to final Windows, Linux and macOS bytes | Open — R15B Linux container SPDX `c3b67c55...422e` is reconciled within its bounded artifact gate and unsigned Windows R10B predecessor reconciliation passed; final shipped aggregate absent |
| Clean lifecycle on all platforms | Clean install, upgrade, uninstall, data-policy and rollback receipts on disposable native Windows/Linux/macOS hosts | Open — R15B disposable Debian clean install passed, but native upgrade/uninstall/rollback and Windows/macOS coverage remain absent |
| Long-session performance/stability | Terminal installed Windows R15B soak plus native Linux/macOS long-session, thermal/audio and GUI receipts | Open — R10B attempt 4 is in progress; R15B and native-platform receipts absent |
| Native Linux qualification | Native package/install/startup/file-boundary/single-instance/signal/audio/GUI/mission receipts | Missing — bounded container preflight passed, but container/source evidence is not native-host qualification |
| Native macOS qualification | Native package/install/startup/permissions/audio/GUI/mission receipts | Missing |
| Documentation consolidated/stale superseded | `Onyx-Release-Orchestration/r15b-documentation/ONYX_1_1_9_R15B_DOCUMENTATION_VERIFICATION.json` | Passed current R15B navigation authority across seven documents; final post-artifact update and independent review remain required |
| Final evidence index independently reviewed | Named independent reviewer, exact candidate scope, decision and durable signature/reference | Missing |

## Predecessor legal packet boundary

`THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md`,
`LEGAL_RELEASE_APPROVAL_1.1.9.md` and
`docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json` remain R10B-bound
technical/legal worklists. They may inform the final review, but their hashes
and blank approval fields cannot be rebound to R15B or to final signed
multi-platform artifacts. The R10B packet technically reconciles seven of eight
`NOASSERTION` rows to version-tag evidence, leaves `odfpy` unresolved and
records zero legal approvals.

## Independent reviewer record

- Reviewer legal name:
- Independence/role:
- Candidate and final artifact hashes reviewed:
- Review started (UTC):
- Review completed (UTC):
- Decision: `APPROVED` or `REJECTED`
- Durable signature/reference:

R10B/R8B, V49/V48 and earlier “current”, “complete”, “live”, “operational” or
active-soak statements are superseded for current-state claims by
`DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md`. Their immutable evidence
remains valid only for its original candidate and scope. This index stays
`INCOMPLETE` until every required row has exact final-candidate evidence and
the independent review is complete.
