# Phase 5.2 Approval Inbox V15 External E6 Acceptance

- Evidence ID: `VE-P52-APPROVAL-INBOX-V15-E6-001`
- Decision date: 2026-07-21
- Decision: **ACCEPTED — Phase 5.2 only, default-off/read-only/non-authority implementation handoff**
- Candidate: Phase 5.2 Approval Inbox, V15

## Frozen candidate anchor

This record is outside the frozen V15 evidence DAG and externally anchors the
exact accepted evidence root without modifying any V15 leaf:

- Source/root manifest: `docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V15-001.sha256`
- Source/root SHA-256: `279052fbcaf3018f7fee6733e063e94c67e90e7ce62a2a2cdc7742b55470631f`
- Artifact manifest: `docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V15-001.sha256`
- Artifact-manifest SHA-256: `a1a0f27d0f4edc370b7470a3b7e788cf87fb62cf398eab6b5532a1fb97ff60e0`
- V15 bundle SHA-256: `7334f3abb8345754eb1c027af5139023f3a624d4f4bfe52ad45f004442540734`
- Frozen evidence closure: 142 artifacts and a fixed 26-path live-surface scan

The V15 candidate's `external acceptance pending` condition is resolved for
this exact source/root digest by this independent E6 acceptance record and its
separate SHA-256 manifest. Any change to the root digest or its transitive
closure invalidates this acceptance and requires a new review and record.

## External reviewer attestations

These are external reviewer attestations over the frozen candidate, not new
leaves in the V15 DAG:

| Review | Result | Reproduction evidence | Severity findings |
|---|---|---|---|
| Functional | PASS | Full parent completed in 720.831s; 130 focused tests, 1,032 combined tests, regressions 172 tests plus 265 subtests, 142 artifacts and 26 live paths were reproduced | P0=0, P1=0, P2=0 |
| Integrity | PASS | Manifest-only verification completed in 6.757s; independent rehash sets covered 142, 607, 10,470 and 514 entries, with 11 proportional integrity probes | P0=0, P1=0, P2=0 |
| Quality | PASS | Full parent completed in 529.711s with the same 130/1,032/172+265/142/26 quantitative contract and no live wiring | P0=0, P1=0, P2=0 |

The common full reproduction command was:

```powershell
C:\Python313\python.exe -I -S -B scripts\verify_phase5_approval_inbox_v15.py
```

The proportional frozen-closure check was:

```powershell
C:\Python313\python.exe -I -S -B scripts\verify_phase5_approval_inbox_v15_worker.py --manifest-only
```

The parent marker and frozen structured artifacts, rather than this narrative,
remain the authority for candidate-internal quantitative evidence.

## Exact acceptance boundary

Accepted:

- the frozen V15 implementation and evidence closure named above;
- a bounded calm-batch Approval Inbox projection;
- read-only review selection and handoff contracts;
- default-off, non-authoritative implementation handoff for later Phase 5
  integration.

Not accepted or activated:

- approve, deny, dispatch or live execution authority;
- startup, runtime, launcher, desktop UI or dashboard wiring;
- exact low-risk grant activation or any permission bypass;
- the Phase 5 Runtime Core, Phase 5 Integration or the complete Phase 5 exit;
- Phase 6, any later phase or completion of the Onyx project or PRD.

V15 remains default-off, read-only, non-authoritative and unwired. Its calm
batch and review handoff are projections only; they do not approve, deny,
dispatch or grant execution. Any activation requires a separately scoped,
reviewed and accepted integration checkpoint with rollback evidence.

## Operational limitations and P3 advisories

The V15 full verifier is expensive: external reviewed runs took 720.831s and
529.711s. Its 26-path live-surface scan is a fixed allowlisted surface, not a
general proof about every file outside that surface. Verification also depends
on the stable-filesystem and host trusted-computing-base limitations recorded
in the frozen checkpoint; it is not an atomic concurrent-writer/TOCTOU
security boundary.

Normal completion and verifier timeout exercise cleanup. A forced external
interruption can still orphan an approximately 479 MiB materialized sandbox.
This is a P3 operational advisory: clean orphaned verifier sandboxes before
subsequent evidence runs and optimize the historical verifier before another
large candidate. It is not live Onyx runtime CPU or memory consumption.

## History and next transition

V1 through V14 remain historical/rejected candidates and are not
retroactively accepted. Phase 5 still requires separately accepted exact
low-risk enablement, runtime integration and an E1-E6 Phase 5 exit decision.
Approval Inbox acceptance alone does not unlock Phase 6 or make Onyx complete.
