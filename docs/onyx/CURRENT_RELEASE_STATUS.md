# Onyx current release status

Updated: 2026-08-19  
Current installed product: **Onyx 1.1.9 Windows x64 R15B, unsigned candidate**  
Current frozen source candidate: **V53 R15B, 2,821 files, root
`346dcba1...f45`**  
Artifact status: **R15B built, installed and consolidated on this Windows host;
eight-hour soak passed; Linux container gate passed with cross-build byte
reproducibility explicitly NOT proven**  
Consolidated acceptance: `ONYX_1_1_9_V53_R15B_CONSOLIDATED_ACCEPTANCE.json`,
SHA-256 `b6266dfcdc9441901cfe57d2a502d3a74a6f9c9baf11d8b7533cba2437411cd6`,
status `passed_local_windows_and_container_acceptance`, 14 bound inputs,
10 proven items and 12 explicitly not-proven items  
Formal/public status: **NOT RELEASE-ELIGIBLE**

## R15B consolidated local acceptance — 2026-08-19

The exact frozen candidate was rebuilt, installed and accepted on this host.
The installed executable is SHA-256
`ff289de8b8c607586ae580949359568805a54f928edda92b44efe9d39cb8cda7`.

The terminal eight-hour Windows soak **passed**: 28,800.04 observed seconds,
480 samples at 60-second intervals with 5-second responsiveness polls,
`all_responsive=true`, `full_duration=true` and zero application errors.
Receipt SHA-256
`127c6b18f98375da8f488c623900d2a558f0a7b5f7ff0da7fa757e71cc68b634`.
Four earlier monitor generations were retired honestly: three runs latched
non-responsive on transient 5-second polls during owner desktop activity, and
one monitor process died at sample 469/480 when an external reader raced its
atomic receipt write. No partial run is promoted as a pass.

The Linux container gate **passed** its build, SPDX SBOM and disposable Debian
clean-install smoke, returning the honest
`passed_limited_safe_unavailability` portable boundary contract with zero
network, process and provider calls. **Cross-build byte reproducibility is NOT
proven**: rebuilding from the identical frozen source produced a different
artifact set (DEB `b98d54e2...1ce9`, TAR `92521ed4...eaf1`, SPDX
`7ea25af9...1bf7`) than the 2026-08-11 independently verified set (DEB
`4d8f4477...90c8`, TAR `e3ff2840...6b3`, SPDX `c3b67c55...422e`). Exactly two
of 6,937 packaged files diverge — `Onyx/Onyx-DayOps` and
`Onyx/_internal/base_library.zip` — which is PyInstaller archive
non-determinism, not source drift; 6,933 files reproduced byte-exactly and the
frozen source root verified byte-exact. Finding SHA-256
`9f2dbffb40d4dd566644726e51438af3c7b8d16785b2f55c09488d262c92735f`.

A second finding from the same run: the frozen candidate's own
`packaging/linux/verify_deb_clean_install.sh` (2026-08-03) asserts
`"status": "passed"` while the frozen product correctly reports
`"status": "passed_limited"` on Linux, so the candidate's script rejects its
own valid receipt. Orchestration now carries an explicit verifier that runs
every frozen check unchanged and corrects only that terminal predicate to the
narrow pair `passed | (passed_limited AND safe_unavailability)`. The frozen
candidate was not modified; repairing the stale packaging script belongs to
the next candidate.

## Exact current boundary — R15B source over R10B installed predecessor

V53 R15B is the current immutable source candidate. Its manifest binds 2,821
files and 141,905,982 bytes to root SHA-256
`346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45`;
the manifest SHA-256 is
`416ec711f178cac874e005cdcf87e2ea04d7429fe14b585e66e04cd65b4234a5`.
The official frozen Windows suite, portable-security gate, release gate and
Linux-container source suite passed within their recorded scopes.

The first parallel R15B build reached Setup and portable artifact generation
but is rejected as release evidence. Its isolated Setup smoke timed out because
the protected R10B long-session run intentionally kept Onyx resident and the
installer correctly refused an unauthenticated shutdown. The failed workspace
still matches all 2,821 manifest inputs; that preservation receipt has SHA-256
`44ab4a7155d30e753df689fcee286d5ad546b28df38243f7ee6b4082a75f74d0`.
A fail-closed recovery watcher waits for the exact R10B attempt-4 terminal pass,
then requests authenticated cooperative shutdown and rebuilds from the same
frozen source. No rejected artifact hash is promoted here.
The live chain independently passed a non-mutating preflight which rehashed
the frozen tree, bound the exact V4 validation image and offline-license cache,
confirmed one armed watcher and parsed all seven downstream PowerShell
contracts. Receipt SHA-256:
`0656e7917bd3ae1a837413f03a74bea981fd3b095b5ec11ed7dd3aa189e71690`.

The independent no-network Linux container preflight passed against validation
image `sha256:a2530e76...e008`. It produced DEB SHA-256 `4d8f4477...90c8`,
TAR SHA-256 `e3ff2840...6b3` and SPDX SHA-256 `c3b67c55...422e`; all 109 bundled
runtime distributions match the frozen lock. A disposable Debian installation
returned the exact `passed_limited` portable safe-unavailability contract with
zero network, process and provider calls. The authoritative continuation receipt
SHA-256 is `57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f`.
An independent re-verification receipt has SHA-256
`e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c`.
This is not native Linux desktop/audio/session/lifecycle evidence and is not a
final shipped cross-platform SBOM.

Live Microsoft Graph DayOps read, access-token refresh and refresh-token
rotation passed against the frozen R15B source with `Calendars.Read`,
`Mail.Read`, `offline_access` and `User.Read`. The receipt SHA-256 is
`20569b3c16c82301d5f787398f689ed2afdd545dfb29b3bde2885a7c36ccfcd0`.
It does not prove installed-host binding, revocation or live provider-failure
handling. The Gemini native-audio provider also returned a 2.44-second, 24 kHz
mono WAV; receipt SHA-256
`fb9128ecfddf479528176e19991cade497e3e0c0f81890e37c309449aac06684`.
That receipt does not prove physical-microphone capture, owner-heard quality or
the installed executable playback path.

## Current R15B gate matrix

| Gate | Current state | Exact boundary |
|---|---|---|
| Source freeze | `PASSED_R15B` | V53; 2,821 files; 141,905,982 bytes; exact root and manifest above |
| Portable security/build gates | `PASSED_FROZEN_SOURCE` | Windows 196 passed/54 skipped; Linux container 171 passed/79 skipped plus 2 subtests; release gate 105 passed |
| Linux container artifact gate | `PASSED_WITH_REPRODUCIBILITY_NOT_PROVEN` | Build, SPDX and disposable Debian clean install passed with `passed_limited_safe_unavailability`; cross-build byte reproducibility NOT proven (2 of 6,937 packaged files diverge — PyInstaller non-determinism); native GUI/audio/session/lifecycle remains open |
| Windows artifact build | `PASSED_EXACT_REBUILD` | Clean exact rebuild from the frozen candidate after the terminal predecessor soak; first attempt's rejected bytes were never promoted |
| Installed runtime | `R15B_INSTALLED_AND_ACCEPTED` | R15B executable SHA-256 `ff289de8...cda7`; technical, owner-name and orb installed acceptances passed |
| Windows long session | `PASSED_R15B_EIGHT_HOUR` | 28,800.04 s, 480 samples, `all_responsive=true`, zero application errors; receipt `127c6b18...b634`; four earlier generations retired honestly |
| Consolidated local acceptance | `PASSED_LOCAL_WINDOWS_AND_CONTAINER` | Receipt `b6266dfc...1cd6`; 14 bound inputs; 10 proven, 12 explicitly not proven |
| Microsoft Graph DayOps | `PASSED_LIVE_FROZEN_SOURCE` | Live read/refresh/rotation passed; installed-host binding remains open |
| Voice provider | `PASSED_LIVE_NATIVE_AUDIO_FROZEN_SOURCE` | Gemini native audio passed; microphone, owner-heard, installed playback, cancellation and offline gates remain open |
| Orb/name/missions/recovery | `PASSED_R15B_INSTALLED` | Installed technical, owner-name transcript-authority with fresh-activation restart persistence, and installed orb acceptances all passed on R15B; visible packaged-window ambient orb motion captured |
| Linux artifact reproducibility | `NOT_PROVEN` | Rebuild from the identical frozen source diverges in `Onyx/Onyx-DayOps` and `Onyx/_internal/base_library.zip`; finding `9f2dbffb...735f`; repair belongs to the next candidate |
| Linux native package/runtime | `NATIVE_RUNNER_REQUIRED` | Container/source evidence does not prove native GUI/audio/install lifecycle |
| macOS native/signing/notarization | `NATIVE_RUNNER_AND_APPLE_CREDENTIALS_REQUIRED` | Native build/runtime, Developer ID, notarization, stapling and Gatekeeper receipts absent |
| Windows signing/trust | `CERTIFICATE_REQUIRED` | Trusted certificate/timestamp receipts absent |
| SBOM/compliance | `BOUNDED_R15B_LINUX_AND_PREDECESSOR_WINDOWS_ONLY` | R15B Linux container SPDX matches its exact bundle/lock and R10B unsigned Windows reconciliation passed; final shipped signed all-platform aggregate absent |
| Legal approval | `OWNER_OR_LEGAL_APPROVAL_REQUIRED` | R10B packet approves 0; `odfpy` remains unresolved; no R15B/final-artifact approval |
| Clean lifecycle | `PARTIAL_CONTAINER_PREFLIGHT_ONLY` | R15B DEB clean install passed in disposable Debian; native upgrade, uninstall, rollback and all Windows/macOS lifecycle receipts remain absent |
| Documentation | `PASSED_CURRENT_R15B_AUTHORITY` | Seven current/superseded authorities passed the fail-closed verifier; final post-artifact update and independent review remain required |
| Independent evidence review | `REVIEWER_REQUIRED` | No independent signed decision exists |

Onyx 1.1.9 remains a formal/public **NO-GO** until every open row has exact
final-artifact evidence. Frozen-source tests and bounded live-provider receipts
do not substitute for installed, native-platform, signed, legal or independent
acceptance.

## R10B installed predecessor boundary

R10B is built, installed and locally operational on this Windows host. The
setup and portable artifacts match their release manifest; the installed tree
matches all 7,451 bundle files, with 14 installer-owned extras. The official
installed harness passed all nine governed scopes, startup is responsive, the
central Orb changes continuously between direct frames, and a 30-second visible
sample used 0.39% of total machine CPU capacity on this 28-logical-CPU host.
The installed executable is 1.1.9 and byte-bound to the R10B bundle.

The deterministic compliance reconciliation additionally proves that all
7,451 portable members, all 7,451 installed files, 116 runtime distributions,
181 runtime legal-evidence files and both supplemental evidence inventories
match exact candidate bytes. The receipt is
`C:/MAAX_Assistant/Onyx-V49-Windows-Candidate-R10B-20260811/acceptance/installed-r10b/ONYX_1_1_9_R10B_COMPLIANCE_RECONCILIATION.json`
(SHA-256
`7aeefaeebb22a1becb93b0a568756234918c259a408dfaae6a9a7dc33ddb6e6f`).
It explicitly leaves `publicReleaseEligible=false` and legal approval unset.

## R10B predecessor gate matrix

| Gate | Current state | Exact boundary |
|---|---|---|
| Source freeze | `PASSED_R10B` | 2,769 files; 141,540,580 bytes; root `f9b169d15a964cd25c151dfca0e2ef807229761a6325dab5005c3a93c6487a50`; manifest `5a833e117261734b1b6a9c9ba0a1afce005166531ef5e5d8d83db965b0a89844` |
| Dependency security | `PASSED_R10B` | Hash-pinned lock; `python -m pip_audit` found no known vulnerabilities |
| Windows build/install | `PASSED_LOCAL_UNSIGNED_R10B` | Setup `bd2a7c5...27d16`; portable `2dc03067...fbd2`; 7,451/7,451 installed files exact |
| Installed startup and governed smokes | `PASSED_R10B` | Official installed harness passed all nine scopes; stdout `285a540f...193` and empty stderr |
| Installed identity/name | `PASSED_INHERITED_R10B` | Authenticated name update/persistence behavior is unchanged from the accepted installed path; a fresh physical-microphone acceptance remains open |
| Installed voice/provider | `PARTIAL` | Natural-provider wiring is present and unchanged; fresh owner-heard acoustic, interruption, offline and provider-failure receipts remain open |
| Installed Orb/HUD | `PASSED_SHORT_SESSION_R10B` | Two direct frames differ across 83.8998% of sampled central-Orb pixels; machine CPU 0.39%; long/thermal threshold remains open |
| Installed missions/recovery | `PASSED_INHERITED_EXACT_BYTES` | Installed `missions.py` is byte-identical to the previously accepted recovery implementation; fresh destructive lifecycle is not implied |
| Windows long session | `IN_PROGRESS_R10B_ATTEMPT3` | Attempt 1 started 2026-08-11T14:58:47Z but both Onyx and its monitor ended before terminalization after 2,103.814 seconds; its stale `in_progress` receipt is invalid as a pass. The exact candidate was relaunched and attempt 3 started 2026-08-11T15:42:53Z against PID 32064. A terminal result is not yet claimed; voice rotation remains honestly `not_proven` in this performance-only run |
| Windows lifecycle | `PARTIAL` | Upgrade/install path passed; clean-host uninstall and rollback receipts remain absent |
| Windows signing/trust | `EXTERNAL_CREDENTIAL_REQUIRED` | Setup and executable are `NotSigned` |
| SBOM/compliance | `PASSED_UNSIGNED_WINDOWS_R10B_TECHNICAL` | SPDX `b335a9a8...9dd3`; exact candidate receipt passed; final signed all-platform aggregate remains absent |
| Legal approval | `OWNER_OR_LEGAL_APPROVAL_REQUIRED` | SBOM retains 8 `NOASSERTION` rows; the exact R10B packet technically reconciles 7 tag-bound candidates, leaves `odfpy` unresolved and approves 0 |
| Linux native package/runtime | `NATIVE_RUNNER_REQUIRED` | Resolution/source gates do not prove native GUI/audio/install lifecycle |
| macOS native/signing/notarization | `NATIVE_RUNNER_REQUIRED` | Native build/runtime, Developer ID, notarization, stapling and Gatekeeper receipts absent |
| Microsoft Graph DayOps | `EXTERNAL_ENTRA_REQUIRED` | Onyx-specific app identity, least-privilege consent and live provider receipts absent |
| Independent evidence review | `REVIEWER_REQUIRED` | No independent signed decision exists |

Onyx 1.1.9 is not complete until every open gate has candidate-bound passing
evidence. The local Windows R10B operational pass is not a public release,
cross-platform certification, legal approval or independent review.

## Superseded R8B/V48 predecessor snapshot

The remainder of this file is retained verbatim as authenticated predecessor
evidence for existing transition tests. It is superseded for current-state
claims by the R10B section above. Historical literals include `Release V47 /
Phase 5 V47, dependency-safe source`, `Current installed product: **Onyx 1.1.9
Windows x64 V41, unsigned diagnostic**`, `Current frozen source: **V44,
source-validated`, `No V45 artifact has been built or installed`, and `V46
remains source-only`.

<details>
<summary>Authenticated predecessor snapshot (superseded)</summary>

Superseded installed product: **Onyx 1.1.9 Windows x64 R8B, unsigned candidate**  
Superseded frozen source: **V46 R8, authenticated and source-validated**  
Superseded mutable successor: **Release V48 / Phase 5 V48, dependency-safe and
evidence-corrected source; clean full suite passed, freeze and build pending**

### Superseded exact boundary

R8B remains the exact product installed on this Windows host and its long-run
monitor remains useful stability evidence. It is no longer eligible to become
the final release candidate: a subsequent dependency audit found nine known
vulnerabilities across five locked distributions. The mutable V48 successor
updates `curl-cffi`, `h2`, `mcp`, `pypdf` and `werkzeug`, declares the clean-env
PDF test dependency, and regenerated the hash-pinned universal lock. A fresh
`pip-audit` reports no known vulnerabilities, and the clean Python 3.13
environment passed 170 focused tests with 1 expected platform skip. These
source results do not substitute for a rebuilt, installed and audited R9
artifact.

The first clean-lock full run reached 49,233 passed, 116 skipped and 673
subtests, but did not pass: 156 failures and one error exposed a noncanonical
temporary root plus current-authority drift in historical tests. V48 corrects
the current Capability Nexus binding, authenticates 60 unique historical nodes,
keeps Phase 5 retirement additive, refreshes the Google Workspace local closure
and drives the current cinematic Orb object instead of a superseded QML ID. A
42,003-case regression then reduced the remaining product/test findings to a
durable-replay clock mismatch and a Win32 path-length harness root; both focused
corrections subsequently passed 37 tests. This is diagnostic progress, not a
green full-suite result. The uninterrupted R4 run then completed 49,374 passed,
116 skipped and 700 subtests in 4,533.52 seconds, with seven failures confined
to six superseded test nodes and one stale path/hash-bound Ruff exception.
Those evidence routes are corrected additively in V48. The uninterrupted R5
rerun then passed 49,381 tests with 116 expected skips and 700 passed subtests
in 4,492.70 seconds. Its JUnit reports 50,197 collected cases, zero failures
and zero errors. This closes the mutable-source full-suite gate; it does not
substitute for the R9 source freeze, artifact rebuild, install or acceptance.

Cross-platform dependency dry-runs also exposed an unsatisfiable macOS policy:
`--only-binary=:all:` rejected PyAutoGUI's source-only helper packages. The V48
workflow now keeps `cryptography` wheel-only while permitting those pure-Python
packages to build. Hash-enforced dry resolution passes for macOS arm64 (145
packages) and Ubuntu 24.04-compatible Linux x64/arm64 targets (141 packages
each). This is dependency-resolution evidence, not native runtime evidence.

The current immutable source is
`C:/MAAX_Assistant/Onyx-V46-Source-Candidate-R8-20260810`: 2,729 files,
141,353,238 bytes, aggregate root
`092df168843ae1328fac93ff1005cfd810fb4f1b1396e045b993947df164f032`.
Its source manifest SHA-256 is
`b25bf943cab752bea2626ca19160d50b4fbdae4ae3eccfe2c455bef6001b34c1`.
The frozen authority suite passed 310 tests with 5 expected skips. The recorded
Git traceability reference is
`355504cb86e97e368dc575f9968ecf4c0fabe994`.

The Windows candidate was built at
`C:/MAAX_Assistant/Onyx-V46-Windows-Candidate-R8B-20260810`. Its artifact
identity is:

- Setup: 487,706,264 bytes; SHA-256
  `68620d53bbec426c73984fefb0a69f07e23bc6f8fac8b805b6dfea43fdc8c699`;
- portable ZIP: 553,331,130 bytes; SHA-256
  `e7f4a12be203e681660d30d7c0d898adf4b9f8ef7f8a65e8c4169e42f040cc5f`;
- bundle inventory: 7,473 files, 112 runtime distributions, root
  `34218af4a7ee3c9453c80219d3c9f6b7f7a588fa788a998a6c86e9f09e6eff3a`,
  inventory SHA-256
  `d71c56b873fdff2823ad05623bd738c319c136478436a3dcfc394a7e986e4114`;
- release manifest SHA-256
  `fbd90540872b6a2bf212ff6d5dcc8f4acdccedfe0ee7d4fd25ac911bc2ccc995`.

The current-user upgrade installer completed with exit code 0. The installed
tree matched all 7,473 bundle files with zero missing files and zero hash
mismatches; `unins000.dat` and `unins000.exe` are the only installer-owned
extras. The installed executable is 28,213,854 bytes, version 1.1.9, SHA-256
`48234389cb30480492fe3d4ddac546f5210f4bf08a5c5782e4e07a9838d566ed`,
and is byte-identical to the R8B bundle executable. Onyx was relaunched from
that exact path and was responsive when the current 8-hour monitor started.

The consolidated installed evidence is
`C:/MAAX_Assistant/Onyx-V46-Windows-Candidate-R8B-20260810/acceptance/installed-v46-r8b/ONYX_1_1_9_V46_WINDOWS_INSTALLED_ACCEPTANCE_RECEIPT.json`
(SHA-256
`f17582b0c272930087d50883881f92bfd44ac829c6d6a7f7dfb555523ddf522a`).

## Proven R8B Windows layer

- native startup passed against activation V24/current-windows;
- installer registry identity, installed version and package-to-install hashes
  match;
- the text command `Call me Sir` committed the authenticated owner preference,
  updated the HUD and persisted across a full application exit and restart;
- microphone capture, playback, Gemini Native Audio connection/receive and an
  intended-provider response were observed;
- the Orb changed continuously at idle and visibly entered the responding
  state while speaking;
- 65-second idle sampling averaged 0.416% whole-host CPU; the 15-second speaking
  sample averaged 0.846%; all sampled UI states were responsive;
- installed mission create/run/audit/reopen, pause/cancel, crash recovery,
  explicit retry and exhausted-budget rejection passed against exact packaged
  mission bytes;
- eight installed governed smokes passed before the current soak, with zero
  intercepted external effects; their standalone stdout still needs a durable
  rerun after the soak for independent review;
- a deterministic Windows technical SPDX now covers both R8B release artifacts,
  the bundle inventory and all 112 shipped runtime distributions. Its SHA-256
  is `86897c1a1646302081f75bc5f93fad02338d5a0fe8c7e86285a4f4886139e006`.

This evidence does not prove a physical-microphone owner-name command,
owner-heard natural speech quality, cancellation/offline behavior, clean-host
lifecycle, signing, legal approval, live Microsoft Graph DayOps or native
Linux/macOS parity.

## Current gate matrix

| Gate | Current state | Exact boundary |
|---|---|---|
| Source integrity | `PASSED_R8` | Authenticated 2,729-file freeze; root, manifest and 310-passed/5-skipped authority scope recorded |
| Mutable security successor | `PASSED_FULL_SUITE_V48` | Hash-pinned lock audits clean; R5 passed 49,381 tests, 116 expected skips and 700 subtests with zero JUnit failures/errors; freeze and artifact rebuild remain open |
| Portable security/build regressions | `PASSED_BOUNDED_V48_SOURCE` | Hash-enforced dependency resolution passes for macOS arm64 and Ubuntu 24.04 Linux x64/arm64; native build/runtime proof remains open |
| Windows build/install | `SUPERSEDED_SECURITY_REBUILD_REQUIRED` | Exact R8B artifacts remain installed and matched 7,473/7,473 files, but they predate the V48 dependency/evidence corrections and remain unsigned |
| Installed identity/name | `PASSED_TEXT_ACROSS_RESTART` | `Sir` committed and persisted; physical microphone command remains open |
| Installed voice/provider | `PARTIAL` | Gemini/mic/playback and intended response observed; owner-heard quality, cancellation and offline/error proof open |
| Installed Orb/HUD | `PASSED_SHORT_SESSION` | Idle and speaking motion plus bounded CPU/memory evidence passed; thermal/8-hour result open |
| Installed missions/recovery | `PASSED_R8B` | Representative lifecycle and corrected exhausted-retry boundary passed against installed bytes |
| Governed installed smokes | `PASSED_OBSERVED_R8B` | Eight checks passed with zero intercepted external effects; durable stdout rerun remains open |
| Windows long session | `IN_PROGRESS_R8B` | Corrected monitor started 2026-08-11T04:24:48Z for 28,800 seconds; terminal result not yet available |
| Windows lifecycle | `PARTIAL` | Current-user upgrade passed; disposable clean install, uninstall and rollback receipts remain open |
| Linux source/POSIX | `PASSED_LIMITED_SOURCE` | Portable/container evidence exists; no native GUI/audio/install lifecycle proof |
| Linux native package/runtime | `NATIVE_HOST_REQUIRED` | Real Linux runner, desktop/audio/session and lifecycle evidence absent |
| macOS | `NATIVE_RUNNER_REQUIRED` | Build/runtime, permissions, audio, lifecycle, Developer ID and notarization absent |
| Microsoft Graph DayOps | `EXTERNAL_ENTRA_REQUIRED` | Onyx-specific app identity, account binding and least-privilege consent absent |
| Windows signing/trust | `EXTERNAL_CREDENTIAL_REQUIRED` | Setup and binaries remain unsigned/untrusted |
| Legal approval | `OWNER_OR_LEGAL_APPROVAL_REQUIRED` | License/notices worklist unresolved; approval fields blank |
| SBOM | `R9_REBUILD_REQUIRED` | Exact unsigned R8B inventory remains historical; the V48 dependency-safe artifact set does not exist yet |
| Clean-machine matrix | `REAL_CLEAN_HOSTS_REQUIRED` | All-platform clean install, upgrade, uninstall and rollback receipts absent |
| Independent evidence review | `REVIEWER_REQUIRED` | Reviewer identity, decision and durable signature absent |

## External release dependencies

- Onyx-specific Microsoft Entra application identity and one-time
  least-privilege `Calendars.Read`/`Mail.Read` consent;
- representative Linux and macOS hosts with GUI and audio devices;
- Windows code-signing certificate and timestamp service;
- Apple Developer ID credentials and notarization access;
- Cyryx Labs legal/owner approval of final license and notices;
- disposable clean hosts or VMs for lifecycle qualification;
- an independent reviewer who did not author the final evidence set.

## Superseded authenticated test anchors

The following exact phrases are retained only because the immutable V46
documentation-successor gate authenticates them. They describe the superseded
pre-R8B boundary and are **not current-state claims**:

- `Onyx 1.1.9 Windows x64 V41, unsigned diagnostic`;
- `V45, source-validated; artifacts not yet built`;
- `V46 authenticated successor; not yet frozen or built`;
- `No V45 artifact has been built or installed`;
- `V46 remains source-only`.

The historical matrix literals below are likewise retained only for the
authenticated predecessor gate. Every row is superseded by the current R8B
matrix above:

| Historical gate | Historical status | Superseded context |
|---|---|---|
| Windows long session | `IN_PROGRESS_MONITOR_FALSE_NEGATIVE_V41` | Superseded historical V41 anchor; interim data cannot pass the gate; rerun with the corrected V44 monitor |
| Final SBOM | `WINDOWS_TECHNICAL_ONLY` | Superseded V41 Windows reconciliation passed; final signed all-platform shipped set absent |
| Linux packages | `FAILED_PRECHECK_V41` | Superseded V41 packaged preflight exited 70 |

## Completion rule

Onyx 1.1.9 is not complete until every open gate has candidate-bound passing
evidence. V41/V45 and earlier “current”, “complete”, “live”, “operational” or
active-soak statements are superseded for current-state claims. Their evidence
remains immutable and retains only its original scope.

</details>
