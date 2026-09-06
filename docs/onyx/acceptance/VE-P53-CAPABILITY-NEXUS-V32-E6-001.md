# Phase 5.3 Capability Nexus V32 External E6 Acceptance

- Evidence ID: `VE-P53-CAPABILITY-NEXUS-V32-E6-001`
- Decision date: 2026-07-21
- Decision: **ACCEPTED — Phase 5.3 only, default-off/shadow-only implementation handoff**
- Candidate: Phase 5.3 Capability Nexus, V32

## Frozen candidate anchor

This record is outside the frozen V32 evidence DAG and externally anchors the
exact accepted evidence root without modifying any V32 leaf:

- Source/root manifest: `docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V32-001.sha256`
- Source/root SHA-256: `86cc174fb212f51c56b59cb9043c8cb59e765307eea2c32a7a44857f6112bfa3`
- Artifact manifest: `docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V32-001.sha256`
- Artifact-manifest SHA-256: `3d32ebf989f198534377d35c0ffc8c1f3abf10c8aa001f24406c355bafff0249`
- V32 bundle SHA-256: `84ffc850a14782ae3f4182973acc50a2765df7f6143977a81daf5423c6706c6f`
- Frozen evidence closure: 496 unique artifacts, 120 recursively verified
  manifests, 579 unique historical leaves and 111 live-surface paths

The V32 candidate's `external acceptance pending` condition is resolved for
this exact source/root digest by this independent E6 acceptance record and its
separate SHA-256 manifest. Any change to the root digest or its transitive
closure invalidates this acceptance and requires a new review and record.

## External reviewer attestations

These are external reviewer attestations over the frozen candidate, not new
leaves in the V32 DAG:

| Review | Result | Reproduction evidence | Severity findings |
|---|---|---|---|
| Functional | PASS | `scripts/verify_phase5_capability_nexus_v32.py` completed in 214.046s; marker reported 496 artifacts, 2,021 focused passes, 111 live paths and the exact root; combined history reported 41,717 passes; regressions reported 102 base tests plus 221 subtests; adversarial 32 and timeout 4 probes passed | P0=0, P1=0, P2=0 |
| Integrity | PASS | The same parent completed in 189.625s; 496/496 closure entries, 23 adversarial path cases and the exact V31 475/475 predecessor closure were independently checked | P0=0, P1=0, P2=0 |
| Quality | PASS | The same parent completed in 209.509s; 8/8 static gates passed; the 300s offline deadline used 69.8% in that run; no live wiring or runtime impact was found | P0=0, P1=0, P2=0 |

The common reproduction command was:

```powershell
.\.venv\Scripts\python.exe scripts\verify_phase5_capability_nexus_v32.py
```

The accepted structured evidence also binds 39/39 tamper fixtures. The parent
marker and structured artifacts, rather than this narrative, remain the
authority for candidate-internal quantitative evidence.

## Exact acceptance boundary

Accepted:

- the frozen V32 implementation and evidence closure named above;
- descriptor-only Capability Nexus discovery, health and snapshot contracts;
- byte-preserving legacy tool descriptors in default-off shadow projection;
- the isolated local catalog read adapter and its read-only contract;
- implementation handoff for later Phase 5 work while these surfaces remain
  strictly default-off, shadow-only and unwired.

Not accepted or activated:

- dispatch authority, grants of live authority or permission bypass;
- startup, runtime, launcher, desktop UI or dashboard wiring;
- provider, MCP, remote connector, browser fallback or external mutation
  activation;
- the pending Phase 5.2 Approval Inbox V9 candidate or exact low-risk grant
  enablement;
- the complete Phase 5 exit, Phase 6, any later phase or the complete Onyx
  master plan.

V32 remains default-off, shadow-only and unwired. Its registry and local
adapter expose projections only; they cannot dispatch or authorize execution.
Any activation requires a separately scoped, reviewed and accepted integration
checkpoint with rollback evidence.

## Operational limitations and P3 advisory

The authoritative-path gate is a stable-filesystem-state metadata precheck. It
is not atomic with a later read, hash or process launch and is not a
concurrent-writer/TOCTOU security boundary. Verification therefore requires
that the authoritative tree not be concurrently mutated. This limitation is
part of the accepted contract and must not be represented as closed.

The 300-second deadline applies only to the offline evidence verifier; it does
not add a live Onyx loop, background task or runtime CPU cost. The immutable
historical corpus is 9.82 MiB across 130 files. Measured full-verifier growth
was approximately 33s at V29, 34s at V30, 96s at V31 and at most 224.117s in
the V32 frozen evidence. This is a P3 maintainability advisory: optimize and
compact future historical traversal before adding another large candidate. It
does not widen this acceptance or permit evidence deletion.

## History and next transition

V1 through V31 remain historical/rejected candidates and are not retroactively
accepted. Phase 5 still requires an accepted approval-inbox slice, a separately
reviewed exact low-risk enablement slice and a Phase 5 E1-E6 exit decision.
Capability Nexus acceptance alone does not unlock Phase 6 or make Onyx complete.
