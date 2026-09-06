# Phase 5.3 Capability Nexus V18 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V18 preserves rejected V1–V17 byte-for-byte.

The V14 closed metadata provenance/type contract is unchanged. Metadata values
remain exact frozen enums per key, with `declaration_sha256` as the sole lowercase
hexadecimal typed field. Content scanners remain confined to descriptions,
canonical schemas and legacy declarations.

V18 changes evidence enforcement only. One CLI parent owns a single monotonic
deadline and exactly two sequential process-tree roots: focused pytest and the
pure artifact-verification worker. These are two parent-owned roots, not a claim
that the operating system runs only two processes. The worker has no subprocess
surface. Any phase failure or timeout fails closed without retry or an acceptance
marker.

Every phase owns its complete process tree. On Windows, the parent configures a
pointer-safe Job Object before launching a fixed private bootstrap, assigns that
bootstrap while it is blocked on the GO barrier, and only then releases the fixed
phase command. Kill-on-close and active-process accounting cover descendants.
POSIX and macOS retain the unchanged new-session process-group path. Timeout,
error and normal completion all use bounded tree cleanup and verify that the
owned tree is empty.

Stable regression evidence includes a canonical pytest report for each base test
and subtest. Stable identities, parent mapping, context, outcome and uniqueness
are reconciled with JUnit testcase children and suite counters. A synthetic JUnit
counter delta is invalid unless the separately hash-bound subtest report accounts
for it exactly. The XML parser admits one explicit pytest schema only. Counters
use canonical unsigned-decimal lexical forms; times use canonical finite,
nonnegative millisecond decimals. Namespaces, comments, processing instructions,
unknown attributes/elements and non-whitespace text or tails are rejected.

Combined suites, stable regressions, recursive history traversal, tamper fixtures,
static gates, live boundaries, artifact membership and measured verifier runtime
are recorded in canonical structured evidence. The verifier checks schemas,
selected-suite uniqueness, exit codes, JUnit child/counter reconciliation,
recursive manifest and leaf sets, fixture uniqueness, hashes and cross-artifact
consistency. Bundle claims and this checkpoint are also checked semantically.

Quantitative evidence is exclusively recorded in `docs/onyx/checkpoints/phase5-capability-nexus-v18/phase5-capability-nexus-v18.metrics.json`.
No quantitative result in this checkpoint is authoritative outside that structured artifact.

V18 remains isolated, default-off, shadow-only, not live and externally unaccepted.
It adds no authority, dispatch, writes, providers, ports, flags, inheritance or
startup wiring.
