# ADR-0053 — Phase 11 Project Autopilot V1

## Status

Proposed. Executable local vertical slice; Phase 11 remains `PARTIAL`.

## Context

The accepted Phase 11 precursor could only inspect an exact Git root through a
fixed read-only mission. The next roadmap slice requires one real but reversible
software mission without granting commit, push, merge, deployment, source-tree
deletion or an arbitrary shell.

## Decision

Add `core/phase11_project_autopilot_v1.py` and route it only through the existing
Phase 11 bridge and `MissionWorker`.

- Activation requires the existing Phase 11 flag and the separate exact flag
  `ONYX_PHASE11_PROJECT_AUTOPILOT_V1=true`. With the new flag absent, no
  autopilot directory or process is created.
- Creation binds the exact configured Git top-level, clean HEAD, bounded unified
  patch, patch paths, exact gate argv, gate timeouts, output budget and mission
  budget into the existing immutable HMAC/Ed25519 Phase 11 authority chain.
- Creation also binds an exact bounded byte-state digest of the owner's regular
  `.git` directory. Before any owner Git command, Onyx parses both local
  `config` and optional `config.worktree` without invoking Git. Modern and
  old-style subsection syntax is normalized; filter, diff, merge, include and
  includeIf sections plus executable core hooks/fsmonitor/SSH settings fail
  closed. A trusted absolute system `git.exe`, with global/system
  configuration, hooks, fsmonitor, home and PATH neutralized, exports an exact
  bundle into Onyx data. A standalone clone is created from that bundle; owner
  worktree and shared Git metadata are never registered or written.
- Patch bytes are decrypted only into a bounded in-memory buffer. With the
  handle-safe cleanup flag absent, the preserved legacy/default-off path streams
  them through a bounded stdin writer to `git apply --check -` and
  `git apply -` in the standalone clone. With the handle-safe flag enabled,
  `HandlePatchEngineV1` performs typed handle-relative add/modify application
  and never invokes `git apply`. No `patch.diff` or other plaintext patch
  artifact is created. The signed binding and MissionStore persist only patch
  digest/paths/gates plus an AES-GCM artifact reference whose key derives from
  the OS-vault-protected Phase 11 key.
- Repository-authored code is structurally refused. Gates are exact declarative
  argv beginning `onyx-static` and are implemented by trusted Onyx code:
  `diff-check` and bounded Python AST parsing. There is no pytest, unittest,
  Ruff, import, `exec`, shell, build, install or test-process authority.
- On Windows every trusted Git process is created suspended, assigned to a
  kill-on-close Job Object, then resumed. Timeout, cancel or output exhaustion
  terminates the process tree. V1 refuses non-Windows activation.
- Descriptor-bound checkpoints carry a monotonic sequence authenticated by HMAC,
  the protected native-vault high-water anchor and process-local high-water.
  Replay, same-process coordinated rollback, linked/reparse swaps and same-size
  state replacement fail closed. A signed two-phase journal rolls forward
  crashes between checkpoint-file and vault-anchor writes. Per-mission Windows
  byte-range locks exclude concurrent processes. A persisted checkpoint is
  never resumed after restart without the explicit fresh-reapproval flow,
  which revalidates the exact envelope/owner state and creates a new pending
  mission/runtime nonce.
- Runner entry authenticates durable Phase 11 history once and reconciles any
  persisted terminal kill into both a local `threading.Event` and a Windows
  named manual-reset Event. Its `Local\` name is a domain-separated HMAC over
  the instance namespace, mission ID and authenticated binding digest. The
  kernel object has an explicit protected DACL for the current SID and SYSTEM,
  medium-integrity no-write-up label, and existing-object security must match.
  The hot trusted Git cancel callback performs only local-event and
  `WaitForSingleObject(..., 0)` checks; it never scans MissionStore history or
  takes the bridge-global lock. At most once per second, an authenticated
  native-vault anchor plus exact bounded MissionStore marker check covers a
  crash after durable kill persistence but before `SetEvent`. A new kill is
  durably appended and anchored before both events are set and the Windows Job
  is terminated.
- Trusted Git plumbing supplies exact logical blob sizes and bounded owner
  object sizes before bundle creation. V1 requires a free-space margin and
  monitors controlled-root logical bytes while bundle/clone/checkout Job
  processes run. The live walker enumerates directory entries lazily and has
  explicit file-entry, directory-entry, depth and elapsed-time limits checked
  throughout enumeration; any bound exhaustion terminates the process tree.
- A separate verifier re-authenticates the checkpoint/gate receipts and
  recomputes owner and controlled-worktree state before success.
- Cleanup is explicit, terminal-only and path-bound to the authenticated
  controlled worktree. Its separate exact Windows flag is default off, so the
  prior authenticated `cleanup_refused`/clone-retention behavior remains the
  default. When enabled, prepare/finalize provenance binds the exact clone
  identity around Git population and a signed, quota-bounded native-handle
  manifest/journal deletes only that identity. Terminal state is resolved from
  MissionStore, not caller input; owner immutability, active-process and
  in-process/cross-process mission locks are rechecked. Authenticated terminal
  recovery may clean finalized clones from `patch_applied` or `gates_running`
  as well as `verified`; the cleanup backend and Project transition contract
  use the same stage set. Read-only Git objects are attribute-cleared and
  reopened by handle with identity/type/size/stream validation before
  truncation and deletion. No commit, push, merge, deploy or source deletion
  method exists in this slice.

## Consequences

Onyx can apply one signed-bound patch and perform narrow static validation
without executing project code or changing owner working-tree/shared Git files.
Cleanup remains refused and retains the controlled tree unless the separate
handle-safe candidate flag is exact. With it enabled, the bounded source bundle
is descriptor-scrubbed and the authenticated controlled clone can be removed
with resumable signed receipts. Plaintext patch files are never created by the
V1 execution path.

This is not a general test runner or full Away Mode. A separate default-off,
low-authority executable sandbox and exact host execution ledger are now
live-wired locally as a successor candidate. Only its exact committed canonical
receipt may resolve `recovered_receipt`; missing/invalid evidence remains
unknown and never redispatches. The external-agent successor is health-only and
fail-closed, not coding authority. The Live UI still lacks automatic waiting
replay, browser takeover, coding-agent dispatch, draft PRs, real-Docker proof,
external monotonic rollback anchoring and E6 installed-host evidence.
The AST gate checks cancellation/deadline before and after each bounded file,
but cannot interrupt one in-progress parse of a file capped at 2 MiB.

## Stage A-E hardening addendum (2026-07-30)

The default-off Windows candidate now consolidates five additive hardening
stages without widening its mission authority:

- **A — namespace:** worktree, mission, clone and artifact access is rooted in
  held NTFS handles. Mission locking and clone cleanup borrow the same
  authenticated containment identity.
- **B — provenance:** signed `bound` and `clone_preparing` states precede clone
  population; checkpoint/vault/provenance reconciliation and bounded lazy Git
  state fail closed.
- **C — patch and bundle:** bundle stdout is streamed directly into a reserved
  handle-relative artifact. The typed patch engine permits only bounded UTF-8
  LF add/modify operations and uses an authenticated encrypted recovery
  journal; no legacy path-based patch is used when the handle-safe flag is on.
- **D — Live authority I/O:** the configured binding root and its parent are
  pinned by FileId, volume and full resolved path. Binding JSON and AES-GCM
  patch artifacts use parent-relative create-only atomic publication and are
  held against replacement through authentication/decryption.
- **E — final hardening:** Job Object ctypes signatures preserve full HANDLE
  width; Git audit subprocess resources close explicitly; mission locks use
  capped reference-counted entries; non-evicting process high-water registries
  fail closed at capacity; Windows device-name checks include console aliases
  and superscript COM/LPT forms. File flush is mandatory before rename and a
  directory-handle flush is attempted where Windows supports it.

The directory flush is best effort and is not a hardware power-loss guarantee.
Metadata files inherit the ACL of the already trusted parent. Integrity comes
from HMAC/signatures, AES-GCM authentication and protected native-vault anchors.
This version makes no confidentiality or isolation claim against another
process running as the same user or against an administrator. Adding a complex
ACL layer is deliberately deferred.
