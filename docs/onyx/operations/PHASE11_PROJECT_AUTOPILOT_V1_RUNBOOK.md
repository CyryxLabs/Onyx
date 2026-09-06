# Phase 11 Project Autopilot V1 runbook

> **VERSION-BOUND V15 RUNBOOK — NOT CURRENT RELEASE STATUS.** Retain this
> document only for its exact V15 activation contract. Before operating a
> current package, reconcile it with
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) and the packaged
> configuration for that candidate.

Status: V15 live-wired Windows vertical slice; executable authority remains
exact-flag controlled and fail closed.

## Enable

Provision the existing Phase 11 local-audit requirements, including exact
`ONYX_WORKSPACE_ROOTS`, then set:

```text
ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1=true
ONYX_PHASE11_PROJECT_AUTOPILOT_V1=true
ONYX_PHASE11_EXECUTABLE_SANDBOX_V1=true
ONYX_PHASE11_EXECUTABLE_DOCKER_CLI=<absolute trusted docker.exe>
ONYX_PHASE11_EXECUTABLE_DOCKER_HOST=npipe:////./pipe/<local-pipe>
ONYX_PHASE11_EXECUTABLE_PLATFORM=linux/amd64
ONYX_PHASE11_EXECUTABLE_IMAGE_IDS=sha256:<64-lowercase-hex>[,sha256:<...>]
```

Canonical Windows V15 startup supplies this complete group as one activation
contract. A partial group, tag, duplicate image ID, remote Docker endpoint,
relative CLI path, non-Linux platform or uppercase flag value is refused before
the live host is imported. When the default trusted Docker CLI is absent, the
bootstrap keeps V15 and the assistant live with
`ONYX_PHASE11_EXECUTABLE_SANDBOX_V1=false`; executable missions then fail
explicitly unavailable and never fall back to host execution. The stable
bootstrap uses the documented local
Mailpit no-volume image digest as a deterministic smoke-only default allowlist.
It does not pull or build that image and does not make Mailpit a Python/npm test
runner. Provisioning a purpose-built test image and replacing the allowlist with
its exact local digest remains an operational prerequisite for real repository
test commands.

On non-Windows hosts the stable bootstrap retains the V14 fallback. An
explicit V15 activation on a non-Windows host is refused deterministically.

Handle-safe clone cleanup is a separate Windows-only, default-off candidate.
To exercise it, also set exactly:

```text
ONYX_PHASE11_HANDLE_SAFE_CLONE_CLEANUP_V1=true
```

Restart Onyx. A mission uses `mission_type=project_autopilot_v1` with:

- `workspace_root`: exact configured clean Git top-level;
- `patch`: bounded unified Git patch;
- `gates`: one to eight `{argv, timeout_seconds}` objects;
- optional executable extension, supplied only as one complete group:
  `executable_image_id`, `executable_platform`, and one to eight
  `executable_gates` with exact `argv`, `timeout_seconds` and
  `max_output_bytes`;
- `max_steps=1`, `max_retries=0`, provider cost `0`;
- `max_seconds` from 10 through 900;
- optional per-command `max_output_bytes`, capped at 2 MiB.

Example gate argv:

```json
["onyx-static", "diff-check"]
["onyx-static", "python-ast", "src/example.py"]
```

Shells, `env`/command wrappers, inline Python/Node code, unapproved Python
modules and secret-shaped argv remain refused. Direct argv such as
`python -m pytest`, Ruff or npm can be bound only when its immutable image
digest is in the exact V15 allowlist. The image must declare no entrypoint or
exactly the single executable bound as Docker `--entrypoint`; image default
commands are never inherited. The legacy/static mission shape remains unchanged and records
`repository_code_execution=false`; only a mission with the complete executable
binding records it as `true`.

Creation does not execute. `mission_run` is the explicit owner-authorized
command that authenticates the existing MissionStore authority and queues the
fixed worker step. It does not open a second approval window for routine
owner-authorized work, and it does not bypass identity, mission authority,
audit or immutable binding checks.

Before any Git command against the owner repository, Onyx parses local
`.git/config` and optional `.git/config.worktree` itself. Executable filter,
diff, merge, include/includeIf, hooks, fsmonitor or SSH-command configuration
is refused, including deprecated headers such as `[filter.name]`. Do not
attempt to bypass this refusal; remove the executable repository configuration
and create a newly bound mission.

## Observe

`mission_status` reports only redacted stage, completed gate count, retained
clone state and reason. The binding and MissionStore contain neither the raw
patch nor executable argv: they persist bounded approval summaries and
authenticated AES-GCM artifact references whose keys derive from the
OS-vault-protected Phase 11 key.

Waiting/failure deliberately retains the controlled clone and signed
checkpoint for inspection/reconciliation. Do not delete it manually or edit the
checkpoint.

At runner entry, Onyx authenticates durable Phase 11 history once and maps any
persisted kill to a local event plus a Windows named manual-reset Event shared
by cooperating Onyx processes. Its opaque `Local\` name is an HMAC over the
mission, authenticated binding and instance namespace; it reveals none of
those inputs. The kernel object's protected DACL admits only the current SID
and SYSTEM with synchronization/event-modify rights and carries a
medium-integrity no-write-up label. A pre-existing object is used only when its
owner, DACL and label match exactly.

The hot process-cancel callback reads the local event and calls
`WaitForSingleObject(..., 0)` only: it performs no MissionStore history query or
global-lock acquisition. Once per second at most, a bounded exact event-marker
query authenticated against the native-vault anchor covers a crash after
persisting the kill but before signaling the named Event. An owner kill is
persisted and anchored first, then signals the named/local events and terminates
the Job Object. Restart remains safe because the next runner entry reconciles
the durable kill before any tool starts. Unexpected wait results, failed handle
operations, identity drift or security-descriptor mismatch fail closed.

The kill fast-path registry has an explicit 4,096-mission process cap and fails
closed rather than evicting a possibly live event. Project Autopilot mission
locks also cap at 4,096 distinct concurrently referenced missions. Each entry is
reference-counted before lock acquisition, shared by all contenders and removed
only after the last holder or waiter releases it, preventing split locks. The
Live and Project process high-water registries cap at 4,096 and deliberately do
not evict: capacity exhaustion fails closed because eviction could weaken
same-process rollback detection. Restart clears process-local high-water state
and existing checkpoints then require the documented fresh-reapproval flow.

Named Event handles are reference-guarded during hot checks and closed with
verified `CloseHandle` only when no controlled Job is active. Shutdown refuses
to close the registry while a Job remains active; the manual-reset Event is
never reset.

After an Onyx process restart, an existing checkpoint is not resumed
automatically even if its file and native-vault anchor agree. Create a fresh
owner-approved/rebound mission; the old pair returns
`fresh_owner_reapproval_required`.

Call `mission_run` on the old mission with `fresh_reapproval=true`. Onyx
rechecks the exact root, clean HEAD, bounded `.git` digest, patch digest/paths
and static gates, then creates a new mission/runtime nonce in
`awaiting_approval`. It is not queued. A second explicit `mission_run` for the
new mission is always required, including when broad autonomy is configured.
`fresh_reapproval` belongs only to `mission_run`; `mission_status` remains a
read-only projection and does not accept that field.

## Stop and clean up

`mission_cancel` records the terminal Phase 11 kill before cancelling the
MissionStore row. By default it retains the clone.

Set `cleanup_worktree=true` only to request cleanup of a terminal authenticated
mission. With the handle-safe flag absent, V1 preserves the prior behavior:
it securely scrubs the bounded source bundle, records `cleanup_refused`, retains
the clone, and returns
`controlled_clone_cleanup_requires_handle_safe_deleter`.

With all three exact flags enabled, Onyx binds an empty clone directory before
Git population, finalizes signed provenance before patching, and allows cleanup
only after the bridge re-reads a terminal MissionStore state. Cleanup holds the
per-mission in-process and process locks, revalidates owner Git state, refuses an
active Git process, renames the exact bound clone by native handles, and deletes
manifest-bound entries in postorder. Read-only Git pack artifacts are reopened
exclusively, identity/type/size/streams are rechecked, the read-only bit is
cleared by handle, and the same identity is reopened for truncation/deletion.
Busy or replaced handles wait/fail closed. Signed journal, manifest, checkpoint
and native-vault receipts make interruption resumable and cleaned replay
idempotent. A terminal mission can safely resume cleanup from authenticated
`patch_applied`, `gates_running`, `executable_gate_pending`,
`executable_gates_running`, `executable_gate_terminal` or `verified`
finalized-clone checkpoints.
The configured owner repository is never deleted or reset.

## V15 executable-test successor

The Docker executable-test successor in
`phase11_executable_sandbox_v1.py` is wired through the real
`Phase11LiveMissionV1`, MissionStore worker, V15 activation and mission API.
The complete exact V15 flag group is still required; setting the sandbox flag
alone does not create authority.

The live bridge writes executable argv only to a bounded AES-GCM artifact.
The immutable binding and fixed MissionStore step retain only its authenticated
reference, digest, image, platform and gate count. At runner entry it
reconstructs an `ExecutableGateEnvelopeV1` authorized with the
Project Autopilot master key and exactly coupled to the primary
`AutopilotEnvelopeV1.input_digest`, mission ID, gate index, mission
`binding_digest` and executable plan digest. Only that authenticated envelope reaches the executor; a raw
`ExecutableGatePlanV1` is never executable authority. Only
an exact locally present `sha256:<64 hex>` image ID from the constructor
allowlist is accepted. The sandbox receives a domain-separated 32-byte
subkey, never the checkpoint master key.

Each gate receives an opaque deterministic HMAC execution ID covering mission,
binding, primary envelope, plan, index, image, platform, argv, timeout and
output budget. Before dispatch, Onyx writes an authenticated pending intent.
An unresolved intent returns `executable_gate_reconciliation_required` and is
never automatically retried. A valid non-PASS receipt is persisted as a
terminal outcome and is also never retried automatically. Reconciliation is
operational only for two owner-confirmed, append-only decisions:

- `still_unknown` authenticates and anchors the decision while leaving the
  original intent and mission blocked. It never dispatches.
- `abandon` authenticates and anchors the decision before the existing durable
  kill/cancel path. It is terminal and never dispatches.

Fresh reapproval/reseed is forbidden after an authenticated
`attempted_unknown` intent or either reconciliation decision.
`recovered_receipt` is live-wired locally only when the executable boundary has
constructed its host-owned execution ledger. Recovery accepts the exact
canonical receipt already authenticated and committed by that ledger for the
original mission/execution/attempt; substitution, missing evidence and invalid
evidence remain unknown and never dispatch. `proven_not_executed` remains
deferred and fail closed: a missing process/container is not evidence and no
replacement execution ID can be issued.

Mission status distinguishes `not_started`, `attempted_unknown` and
`executed_receipt`. Known manifest cancellation/deadline failures are
prelaunch and can clear intent; unknown or cleanup failures retain intent and
conservatively report attempted execution. After all PASS receipts, Onyx
re-runs the full clone/owner verifier and authenticated clone provenance before
writing `verified`.

## Operational boundary

The live Windows V15 successor can run explicitly authorized argv only inside its
read-only, network-none, resource-bounded Docker boundary; it has no live
authority to commit, push, merge, deploy, install dependencies, write the owner
repository or create a PR. Static-only missions do not execute repository code.
Installed-host executable proof still requires rebuilding the package and
running the packaged smoke/V15 preflight; source and injected-sandbox tests are
not a substitute for that release gate.

The public `ProjectAutopilotV1` constructor accepts no executable-sandbox
factory. Live Mission injects an exact `ExecutableSandboxHostV1`; that sealed
host alone instantiates the exact official `ExecutableTestSandboxV1`. The
process adapter receives Docker argv and bounded process options, never the
signing key or ledger object.

This remains a local candidate. It has no independent E6, observed real-Docker
execution, rebuilt/installed package proof, external monotonic rollback anchor,
or retry/takeover authority.

The Python AST gate checks timeout/cancellation around each file. A single
in-progress parse cannot be interrupted and each source file is therefore
hard-capped at 2 MiB.

The encrypted patch artifact is decrypted only into a bounded in-memory buffer.
With the handle-safe flag absent, the legacy/default-off path streams it to
trusted `git apply` through bounded stdin. With the handle-safe flag enabled,
`HandlePatchEngineV1` performs typed handle-relative add/modify application and
never invokes `git apply`. Onyx does not create `patch.diff` or any other
plaintext patch artifact in controlled storage. The legacy stdin writer is
covered by the same cancel, timeout, output and Windows Job Object termination
boundary as trusted Git. The live controlled-root disk walker enumerates lazily
and additionally refuses file-count, directory-count, depth and elapsed-time
budget exhaustion without first materializing an entire directory listing.

## Storage and durability boundary

On Windows, binding, provenance and metadata files are written to a reserved
regular single-link handle, flushed, and atomically renamed parent-relative.
Onyx then attempts a flush of the held directory handle. Windows filesystems may
reject a directory flush, so this second flush is best effort; the file flush
remains mandatory. This is crash-seam hardening, not a guarantee against
hardware power loss.

These metadata files inherit the ACL of the trusted parent directory. HMAC,
Ed25519/AES-GCM authentication and protected native-vault anchors provide
integrity and rollback detection. This candidate does not claim confidentiality
or isolation against another process running as the same user or against an
administrator. Do not present it as an ACL sandbox.
