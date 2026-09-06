# ADR-0014: Phase 6 V5 lexical-state-safe schema authentication

Status: Candidate — default-off, not accepted, not live

Date: 2026-07-22

## Context

Independent review rejected V4 because its SQL normalizer lowercased and
collapsed whitespace across the complete stored DDL string. That is safe only
outside SQL literal/comment states. Within single/double/backtick/bracket
quotes, blob literals or comments it can erase security-relevant distinctions.

All V1-V4 artifacts must remain frozen. V5 is therefore a minimal isolated
correction to coordination and exact-input-ledger schema authentication; V4's
expired-only CAS recovery, process lifecycle, materialization fencing and
full-input binding are inherited unchanged.

## Decision

V5 tokenizes stored and expected SQLite SQL using an explicit lexical state
machine.

### Lexical rules

- Outside quoted/comment states, whitespace is only a token separator and SQL
  words are case-insensitive, matching SQLite's unquoted token behavior.
- Single-quoted values preserve every byte, including doubled-quote escape
  spelling, case and whitespace.
- Blob payloads preserve their quoted bytes. The external `X` marker remains an
  unquoted case-insensitive SQL token.
- Double-quoted, backtick-quoted and bracket-quoted identifiers preserve exact
  case, whitespace and doubled closing delimiters.
- Line and block comments are exact tokens. V5 deliberately rejects even a
  comment-content change rather than assuming it is benign.
- Unterminated quote or comment states fail closed.
- Operators and punctuation are distinct tokens, so removing outside whitespace
  cannot merge two identifiers or numbers.

The normalized representation is canonical JSON of the token sequence. No
operation lowercases, collapses or decodes content inside a quoted or comment
token.

### Schema signature

`AgenticStateStoreV5` authenticates the exact lexical token stream for every
`sqlite_master` table, index and trigger definition. It continues to include
V4's complete `table_xinfo`, `foreign_key_list`, `index_list` and `index_xinfo`
inventory, exact `user_version`, singleton metadata version, integrity check and
foreign-key check. Validation happens before repair or schema writes.

`StrictMissionMaterializerV5` applies the same signature to the separate exact-
input ledger. It retains V4's canonical full-input digest and replay behavior.

Tests prove:

- benign outside-literal keyword case and whitespace are equivalent;
- literal case/whitespace/escape, blob case, quoted-identifier case and comment
  content are not equivalent;
- same-name literal, trigger, quoted-table, comment and index changes fail
  closed without altering the database bytes.

### V4 closure

V5 subclasses the frozen V4 execution and state behavior only after replacing
construction and authentication with V5 types. Planner, critic, repair planner,
runner, verifier and recovery remain lineage-budgeted and process isolated.
The full V5 end-to-end flow proves planning, materialization, approval,
execution, verification and close.

### Artifact root

V5 reuses the V2 algorithm: exclude the manifest; encode canonical POSIX path,
NUL and lowercase SHA-256 as UTF-8; sort records; join with LF and no trailing
LF; SHA-256 the bytes.

## Consequences

- Only exact `ONYX_PHASE6_AGENTIC_CORE_V5=true` enables explicit construction.
- V5 accepts only explicitly tested benign normalization: outside-token
  whitespace and unquoted SQL word case. Comment differences remain fail-closed.
- Lexical authentication is stricter than semantic SQL equivalence by design;
  a schema must be rebuilt through a reviewed migration rather than silently
  accepted.
- V1-V4, MissionStore, live surfaces and provider configuration remain
  unchanged.
- V5 is unaccepted and not live until independent gates approve the checkpoint.

## Rejected alternatives

- Lowercasing the full SQL string: rejected because literal and identifier bytes
  are data, not keywords.
- Regex-only quote removal: rejected because doubled delimiters, comments and
  state transitions require lexical context.
- Dropping comments before comparison: rejected because V5 cannot prove that an
  arbitrary comment transformation is the only stored change.
- Editing V4 in place: rejected because reviewed artifacts must remain exact.
