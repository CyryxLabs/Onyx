# Phase 11 Local Project Audit — live integration V1

> **HISTORICAL V15 INTEGRATION EVIDENCE — NOT CURRENT RELEASE STATUS.** The
> source assertions below are preserved for auditability. Use
> [`CURRENT_RELEASE_STATUS.md`](CURRENT_RELEASE_STATUS.md) for the current
> release candidate and installed-host evidence.

Status: `PARTIAL`, default-off implementation candidate. No E6 acceptance,
installed-artifact evidence or complete Phase 11 exit is claimed.

## Explicit provisioning and activation

The stable desktop bootstrap is V15. Without Phase 11 provisioning it delegates
to the existing V14 activation and creates no Phase 11 directory, vault entry or
binding.

V15 activates the Phase 11 bridge only when both values are exact:

- `ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1=true`
- `ONYX_WORKSPACE_ROOTS` contains one or more absolute, existing roots

The requested project must be the exact configured root and exact Git
top-level. Missing, partial, relative, linked, duplicate or unavailable roots
fail before activation. V15 never invents a workspace root.

This V15 live activation is currently Windows-only because its V14 host
predecessor is Windows-only. An exact active V15 request on macOS or Linux is
refused with `ONYX_LIVE_V15_PLATFORM_UNAVAILABLE_WINDOWS_REQUIRED`; it is never
silently downgraded. Cross-platform source/package definitions are not evidence
that this live V15 path runs on those hosts.

## Immutable authority boundary

`mission_create` accepts `mission_type=local_project_audit_v1`, a title, exact
workspace root and objective/query. The host—not the model—materializes:

1. `local_system_status`
2. `workspace_inventory`
3. `workspace_text_search`

The immutable binding is created once with `O_EXCL`. It contains the
authenticated baseline, mission id, plan digest and every exact
`{tool,args,idempotency_key}`. Its HMAC key is held in the accepted OS-native
vault (`Onyx.Phase11LiveBinding:binding-v1`), not beside the file. Tests may
inject a key without changing production behavior.

The binding directory/file contract is `0700`/`0600` on POSIX. Reads reject
linked/reparse ancestors and use descriptor-bound `os.open`,
`O_NOFOLLOW` where supported, `fstat`, identity checks and a byte cap.

The MissionStore `phase11.bound` event holds the binding digest and signature.
Creation, approval, execution and status revalidate:

- binding HMAC and digest;
- the exact bound event;
- current MissionStore plan digest;
- current database tool, canonical args and idempotency key for every step;
- authenticated Git baseline.

The binding is never updated. Verification receipts and kill state exist only
as `phase11.receipt` and `phase11.kill` events in the MissionStore hash chain.
After each committed Phase 11 event, a per-mission HMAC-authenticated high-water
anchor and separate non-replayable checkpoint are verified in protected
OS-native vault namespaces. Both namespaces require an opaque native-vault
capability. Validation requires the checkpoint to name the exact current anchor
and the anchored sequence/hash to remain an ancestor of the authenticated
MissionStore head. Observed native transitions such as approval and cancellation
advance the checkpoint, so replaying only an older signed anchor or restoring a
database behind an observed transition fails closed. The database event commits
before the anchor advances; if vault persistence fails, in-memory kill state
remains unchanged and an idempotent retry advances the anchor from the already
committed event.

Phase 11 event append authority is an opaque, non-copyable process capability
bound once by object identity to the exact bridge and MissionStore instances;
the registry holds only weak owner/validator references. The capability is
defense in depth, not the cryptographic authority. Every event has an Ed25519
signature whose public key is fixed by the HMAC-authenticated immutable binding,
and MissionStore independently verifies the exact schema and signature inside
the same append transaction. Receipt events also include the complete signed
receipt fields and their receipt HMAC is validated before append. Kill accepts
only the signed owner-cancel shape, atomically makes the Phase 11 event namespace
terminal and wins any concurrent post-tool receipt race. Status authenticates
every Phase 11 event before it may advance the native checkpoint.

The worker synchronously advances the bridge checkpoint after each returned
native run transition; claim/start are covered by the signed pre-tool receipt,
and approval/cancellation are advanced by their bridge paths. A process-local
high-water additionally rejects replay of both older vault blobs across bridge
reconstruction in the same trusted process.

Anchor persistence is serialized across the complete anchor write/read-back,
checkpoint write/read-back and process high-water update, so an older writer
cannot overwrite a newer pair. If a crash or vault failure leaves an
authenticated newer anchor with an authenticated older checkpoint, validation
repairs forward only after proving the exact anchor event is still an ancestor
of the current MissionStore authority. A checkpoint ahead of the anchor, a
forked hash or any attempted regression is never repaired and fails closed.

Threat boundary: arbitrary code execution with memory introspection inside the
trusted Onyx interpreter, or coordinated rollback of the MissionStore and every
OS-vault record by the same compromised OS account after a process restart, is
outside this local integrity contract. Preventing those attacks requires process
isolation or hardware/OS monotonic storage; this candidate does not claim either.

## Execution, kill and disclosure

The existing MissionStore V5, MissionWorker, leases, permission broker,
deadline, retry and cancellation paths remain authoritative. There is no second
scheduler.

Snapshot drift is checked before approval and before/after every tool. Drift
waits fail-closed without project writes. `mission_cancel` records the Phase 11
kill before MissionStore cancellation. The runner checks kill immediately
before and after the underlying tool, so a late result is discarded.

`mission_status` exposes only state, redacted reason, stage/verdict and
12-character digest prefixes. It never returns the root, binding signature,
complete hashes or raw receipt.

Budgets are exactly 3 steps, 1–900 seconds, 0–2 retries and provider cost zero.
There is no network tool, free-form shell, project write, delete, install,
merge, deploy or publication authority.

## Evidence boundary

Focused coverage includes immutable binding replay/swap/recompute attempts,
current plan tool/args/key tampering, bound-event mismatch, descriptor path
TOCTOU, default-off zero writes, POSIX modes, drift/dirty-byte preservation,
restart, late-result kill, least-disclosure status, rollback failure,
no-network execution and legacy parity.

V15 coverage verifies exact/partial flag handling, V14 fallback, stable
bootstrap selection, explicit non-Windows refusal, linked-root rejection,
root/vault startup refusal, predecessor failpoint rollback and real
`OnyxLive.__init__` reachability from the Phase 11 bridge to its MissionWorker
without starting the worker or opening network.

This document describes the older read-only
`local_project_audit_v1` mission only. It has not gained mutation authority.
A separate default-off, Windows-only `project_autopilot_v1` candidate now adds
worktree-isolated bounded patch mutation, authenticated checkpoints, an
independent verifier and optional handle-safe clone cleanup. That separate
candidate is documented by ADR-0053 and its runbook/checkpoint; it remains
`PARTIAL`, has no E6 or installed-host acceptance and does not run project tests
or builds. Browser/computer-control envelopes and external-agent adapters
remain unimplemented.
