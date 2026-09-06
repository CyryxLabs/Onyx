Status: Accepted for isolated M2b-c verification; not activated.

## Context

The first M2b-c evidence attempt proved an incremental repository, but its cold
audit could accept a producer that omitted both a derived physical row and its
witness. It also inherited the M2b-a journal's lifetime-linear scan and had no
reviewed rotation path. That attempt is retained as historical evidence and is
not sufficient for acceptance.

## Decision

Create an externally anchored operational genesis before repository exposure.
Genesis witnesses every physical row in the independently declared 20-table
audit universe: 12 canonical/derived tables (including `artifact_index`), six
immutable legacy-v2 tables, `workspaces` and `mission_contexts`. Later
repository mutations append exactly one event and a bounded delta commit that
may contain multiple new physical-row entries. Each commit binds a deterministic entry
Merkle tree; the commit sequence is accumulated in an append-only MMR. Hot
reads prove row to entry, entry to commit and commit to the latest MMR peak.
The cold audit independently enumerates physical rows, witnesses, Merkle/MMR
nodes and semantic projections and requires exact equality in both directions.

Replace the raw vault head with HMAC-authenticated `AnchorVaultHead.v2`. It
seals the latest state, generation, archive-chain digest, active-generation
identity, frame count, tail sequence/HMAC/offset and active-prefix digest. A
legacy v1 head is read once by a full authenticated scan and then upgraded.
Normal hot operations hash only the active generation and scan only an
unsealed crash suffix; the active generation is hard-bounded to 1 MiB or 512
frames with two maximum-frame slots reserved for the next prepare/finalize
pair.

Rotation is state-neutral and occurs under the anchor lock. The verified
active bytes are copied to an immutable content-addressed archive and fsynced.
A deterministic generation-plus-one checkpoint frame binds the prior sealed
head hash, prior tail sequence/HMAC/state, archive byte length/hash and new
generation. A fsynced temporary active file is atomically replaced and the
directory is synced before the vault head advances. On Windows the replacement
uses `MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)` and then attempts
`FlushFileBuffers` on a directory handle. Some Windows/filesystem combinations
reject directory flushing, so that second step is explicitly best-effort and
is not claimed as power-loss equivalence to POSIX directory `fsync`; Windows
crash/power-loss qualification remains a release gate. A crash after replacement
but before the vault write may adopt only that unique HMAC-valid immediate
successor. Existing archive paths must have byte-identical content; archives
are never deleted by default. Unlinked content-addressed files are harmless
because cold traversal follows only authenticated checkpoint digests.

The Windows acceptance suite also exercises a real temporary-to-target
replacement through `MoveFileExW` and makes a real directory-flush attempt. It
proves API/path behavior on the test host, not sudden-power-loss durability.

Public repository methods detach ordinary internal exceptions into fresh typed
errors with no cause, context or private traceback. Cancellation-style
`BaseException` objects retain exact identity. Cleanup failures cannot replace
an active primary error.

## Consequences and limits

- Incremental row and commit membership proofs are logarithmic in the entry
  tree/MMR; active-journal work is lifetime-independent and bounded by the
  fixed generation cap. Whole-ledger and archive-history audits remain
  intentionally `O(N)` cold operations.
- Correctly anchored omission of claim links/relations, action-state history,
  event history/heads or projections fails the cold semantic reconciliation.
- Workspace/mission authority rows and the immutable migrated prefix are
  witnessed by genesis and frozen after migration.
- Archive retention is append-only and consumes storage over time. Retention,
  export and externally governed deletion require a later reviewed policy.
- POSIX archives are created and revalidated as exact mode `0400`; cold reads
  reject weakened permissions and never chmod an archive back to writable
  active-file mode. Windows relies on the protected private-directory ACL and
  content-addressed/HMAC validation rather than a POSIX read-only mode bit.
- This remains application-level integrity, not protection from arbitrary code
  already executing in the Python process, the same OS user, administrator/root
  or host compromise.
- `ONYX_M2B_LEDGER_V3` and the anchor remain strict/default-off. Production
  ownership and startup/mission/permission/provider/tool/dashboard/UI wiring
  remain unavailable. No runtime was activated by this decision.

## Supersession

This decision supersedes ADR-0008 only where ADR-0008 described flat bounded
witnesses and authenticated journal rotation as unimplemented. ADR-0008's
default-off, shadow-only, no-dispatch and no-production-owner boundaries remain
in force.
