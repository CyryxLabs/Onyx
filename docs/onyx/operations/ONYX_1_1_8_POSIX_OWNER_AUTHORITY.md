# Onyx 1.1.8 POSIX owner authority

> **VERSION-BOUND 1.1.8 BASELINE — NOT CURRENT RELEASE STATUS.** Preserve this
> authority-contract evidence, but use
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for current
> platform qualification.

Status: implemented and natively validated on Linux; macOS host proof pending.

## Implemented boundary

- The accepted Windows `WindowsHostTransactionLease` and
  `WindowsCredentialChainHeadStore` remain unchanged.
- Portable-current injects an additive V4 `authority_factory`, which is already
  threaded by the accepted V5 through V19 activation chain.
- macOS/Linux transactions use a reentrant cross-process `flock` held on a
  0600 regular file opened relative to a pinned, owner-only 0700 directory
  descriptor. Symlink, ownership, mode, inode and link-count drift fail closed.
- The V8 monotonic chain head and journal authentication key are stored only in
  macOS Keychain or Linux Secret Service. There is no plaintext file or
  environment fallback.
- Backend reachability is proven before creating a trusted directory, lock,
  journal, key or chain head. Linux D-Bus errors are not treated as a missing
  secret.
- Genesis bootstrap failure compensates only newly created exact state.
  Existing or divergent state is preserved. An interrupted empty-genesis
  journal can restore its missing genesis chain head under the same lease.
- Portable-current closes its POSIX owner resources after V19 rollback and on
  activation failure.

## Linux evidence

The native Python 3.13 Linux container suite passed 18 tests. It covers:

- backend-unavailable before mutation;
- descriptor-bound reentrancy and contention between instances and processes;
- linked and non-private roots;
- secure-vault CAS, readback and tamper detection;
- bootstrap, reopen, owner update and empty-genesis crash recovery;
- failed-genesis journal/key compensation;
- linked-journal refusal without replacement; and
- propagation of the official owner factory through portable V19 plus cleanup.

Windows regression coverage passed 110 tests across Owner Profile V7/V8,
Activation V4/V10/V15/V19, portable-current and its release gate. A final
post-format local/Docker run passed 7 and 18 tests respectively.

## Exact remaining macOS proof

No macOS runtime claim is made from Windows or Linux evidence. Promotion on a
real Apple Silicon macOS host still requires all of the following:

1. Verify Keychain lookup of an absent item returns safely while locked or
   unavailable Keychain states raise the typed pre-mutation boundary.
2. Exercise V8 genesis, owner-name update, reopen and chain-head tamper against
   real Keychain entries.
3. Prove `/dev/fd/<dirfd>` identity, `flock` reentrancy and cross-process
   exclusion on the target filesystem.
4. Run the packaged portable-current preflight and normal V19 startup, then
   rollback and verify descriptor/keychain resource cleanup.
5. Repeat the tests from the signed/notarized `.app` and `.dmg`, archive the
   native evidence, and only then promote macOS parity.
