# ADR-0006: Add a default-off native ledger anchor before schema v3

- Status: Implemented infrastructure checkpoint; not activated
- Date: 2026-07-15
- Decision owners: Cyryx Labs / Onyx owner

## Context

The M2a shadow domain repository uses application-level canonical validation,
entity/event hashes and a mutable schema-v2 projection head. Those controls
detect ordinary corruption and isolated drift, but they do not make the SQLite
database append-only and do not prevent a principal that can coherently rewrite
the database from replacing a valid suffix and its projection head.

Schema v3, runtime integration and authority changes are separate review gates.
They must not be smuggled into an anchor-infrastructure checkpoint.

## Decision

Add `core/ledger_anchor.py` and `core/native_vault.py` as isolated M2b-a host
infrastructure with these constraints:

- `ONYX_M2B_LEDGER_ANCHOR_V1` is false by default and accepts only explicit
  `1`/`true` opt-in;
- startup, schema v2, migration journals, missions, permissions, dispatch,
  providers and UI do not import or invoke the anchor;
- production opening has no caller-supplied path, key, vault backend or database
  port; the canonical database port remains deliberately unavailable until a
  reviewed later milestone;
- the HMAC key and authenticated head use distinct fixed namespaces in the
  operating-system credential vault; there is no plaintext/file/environment
  fallback;
- the journal is owner-only, append/fsync based, HMAC chained, canonical and
  streamed with bounded frame allocation while retaining only the authenticated
  recovery tail in memory;
- bootstrap first persists an exact `bootstrap_pending` snapshot and nonce,
  then the key, then genesis, then the committed head. Recovery may complete
  only a state that matches that durable pending snapshot and nonce;
- prepare/finalize/recover are capability- and ticket-guarded, serialized and
  fail closed on divergence, malformed data, unsafe links or ambiguous durable
  state.

Authenticated journal checkpointing and rotation are deliberately a future
non-goal for M2b-a. The current implementation retains large finite safety caps
and fails closed if they are reached; it neither truncates authenticated history
nor presents an unaudited rotation path as implemented.

## Security boundary

This checkpoint provides application integrity discipline and an anchor outside
the SQLite file. It is **not** a privilege boundary or sandbox. Arbitrary code
already executing in the Onyx Python process can monkeypatch Python and inspect
process memory. Another process running as the same operating-system user can
ultimately invoke that user's credential vault. M2b-a does not claim to protect
against either actor, an administrator/root compromise, or a fully compromised
host.

The weak capability registries and private facades reduce accidental API
surface and long-run object retention; they are not presented as security
against arbitrary same-process code.

## Consequences

- M2a remains fixture-only shadow infrastructure and schema v2 remains
  unchanged.
- Passing anchor tests proves the isolated state machine, recovery and native
  vault adapters under the tested environment. It does not prove canonical
  Windows activation, schema-v3 immutability, runtime authorization, provider
  outcomes or an operational ledger.
- M2b-b/schema v3 still requires a separate design, migration, rollback,
  database-enforced immutability and integration review.

## Rollback

Leave the flag disabled and remove the isolated module/tests in a reviewed
change. No existing database needs restoration because M2b-a adds no schema,
migration row, startup call or owner-data execution.

## Verification gate

Acceptance requires focused anchor/native-vault tests, protected
credentials/control-plane/domain-ledger/mission regressions, full `tests/`
pytest, static compilation/Ruff checks, manifest binding and `git diff --check`.
Platform-specific skips and environment warnings remain explicit; no skipped
path is inferred to work.
