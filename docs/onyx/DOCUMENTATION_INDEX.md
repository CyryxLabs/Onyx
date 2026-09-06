# Onyx documentation index

Updated: 2026-08-11  
Installed product: **Onyx 1.1.9 Windows x64 R10B, unsigned candidate**  
Current frozen source candidate: **V53 R15B, 2,821 files, root
`346dcba1...f45`**  
Formal/public status: **NOT RELEASE-ELIGIBLE**

## Read in this order

1. `CURRENT_RELEASE_STATUS.md` — authoritative current boundary and open gates.
2. `FINAL_EVIDENCE_INDEX_1.1.9.md` — requirement-to-evidence release map.
3. `DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md` — current versus
   historical documentation classification.
4. R15B source-freeze manifest:
   `C:/MAAX_Assistant/Onyx-V53-Source-Candidate-R15B-20260811.SOURCE_FREEZE.json`.
5. R10B predecessor installed evidence root:
   `C:/MAAX_Assistant/Onyx-V49-Windows-Candidate-R10B-20260811/acceptance/installed-r10b`.
6. `THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md` and
   `LEGAL_RELEASE_APPROVAL_1.1.9.md` — predecessor R10B worklists; unresolved
   R15B/final-artifact legal decisions remain open.
7. `FORMAL_RELEASE_CONTRACT.md` — formal release eligibility contract.
8. `FINAL_EVIDENCE_REVIEW_PROTOCOL.md` — independent-review procedure.
9. `VERIFICATION_EVIDENCE.md` — append-only historical evidence register.

## Current authorities

| Authority | State |
|---|---|
| `CURRENT_RELEASE_STATUS.md` | Current truth: R10B remains installed; V53 R15B is frozen and awaiting a fresh build after the protected soak |
| R15B source freeze | `C:/MAAX_Assistant/Onyx-V53-Source-Candidate-R15B-20260811`; root `346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45` |
| R15B source manifest | SHA-256 `416ec711f178cac874e005cdcf87e2ea04d7429fe14b585e66e04cd65b4234a5` |
| R15B first artifact attempt | Rejected at isolated Setup smoke; no release-manifest authority |
| R10B installed acceptance | Consolidated receipt SHA-256 `1dd7b080086cde9ea092aa04cba53cb0da1c5b5a822757944acc3aa2fd577a31` |
| R10B technical compliance | Receipt SHA-256 `7aeefaeebb22a1becb93b0a568756234918c259a408dfaae6a9a7dc33ddb6e6f`; SBOM `b335a9a8b33f287bd9b8e91dba7d0ef20bfa8cf163701f2134bd8cb8ee799dd3`; legal/final all-platform gate remains open |
| R10B long session | Attempt 4 in progress against installed PID 32064; terminal eight-hour receipt required |
| R15B DayOps live | Frozen-source read/refresh/rotation receipt SHA-256 `20569b3c16c82301d5f787398f689ed2afdd545dfb29b3bde2885a7c36ccfcd0`; installed binding remains open |
| R15B voice-provider live | Frozen-source native-audio receipt SHA-256 `fb9128ecfddf479528176e19991cade497e3e0c0f81890e37c309449aac06684`; physical microphone and installed playback remain open |
| R15B Linux container preflight | Receipt SHA-256 `57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f`; no-network DEB/TAR/SPDX and disposable install passed, while native Linux qualification remains open |
| R15B Linux independent verification | Receipt SHA-256 `e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c`; artifact, lock, SBOM, offline-license and clean-smoke bindings recalculated |
| R15B recovery-chain preflight | Receipt SHA-256 `0656e7917bd3ae1a837413f03a74bea981fd3b095b5ec11ed7dd3aa189e71690`; frozen source, image/cache, live watcher and seven downstream scripts verified without releasing the soak gate |
| Active story | `docs/stories/ONYX-REL-1.1.9.md` |
| Supersession registry | `DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md` |

Authenticated predecessor literals such as `Current truth: V44 source frozen;
V41 installed diagnostic`, `Phase 5 V44 transition`, `Release Workflow V44
transition`, and `Current authenticated source evidence: **current
authenticated source evidence selected by the direct verifier**` are retained
only in historical evidence/tests. They are not the navigation authority.

## Superseded current-state documents

The following remain historical evidence but are superseded as navigation or
current-state authority:

- all R8B/V48, V41, V45 and earlier installed-current/source-current statements;
- V24/V31/V41 long-session receipts as the current performance result;
- V31/V37 project-completion roadmaps as current release plans;
- any document that identifies V49/R10B as the current frozen source;
- any document that calls the rejected first R15B artifact attempt a valid
  release build;
- any older document that calls Onyx 1.1.9 formally complete, publicly released,
  signed/notarized or cross-platform qualified.

Historical hashes, manifests, failures and acceptance records are not deleted
or rebound. When a historical statement conflicts with
`CURRENT_RELEASE_STATUS.md`, this index and the R15B supersession registry
govern.
