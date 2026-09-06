# Phase 5.3 Capability Nexus V19 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V19 preserves rejected V1–V18 byte-for-byte.

The V14 closed metadata provenance/type contract is unchanged. Metadata values
remain exact frozen enums per key, with `declaration_sha256` as the sole lowercase
hexadecimal typed field. Content scanners remain confined to descriptions,
canonical schemas and legacy declarations.

V19 changes evidence enforcement only. One CLI parent owns a single monotonic
deadline and exactly two sequential process-tree roots: focused pytest and the
pure artifact-verification worker. These are two parent-owned roots, not a claim
that the operating system runs only two processes. The worker has no subprocess
surface. Any phase failure or timeout fails closed without retry or an acceptance
marker.

Every phase owns its complete process tree. The bootstrap has no command argv or
environment command envelope: its source maps only the focused and worker phase
identifiers to exact repository-relative commands. After Windows Job assignment,
an authenticated nonce-bound READY/GO exchange releases one fixed phase once.
The fresh JUnit lives only in a fixed private nonce directory whose realpath and
sentinel are verified by parent and bootstrap. Direct or legacy command-envelope
invocation runs no phase.

Every Windows CloseHandle result is checked. Failure retains an explicit ownership
record, suppresses the evidence marker and supports bounded later cleanup. POSIX
and macOS use one cleanup state machine around normal completion, timeout and all
communicate errors: residual groups are killed, drained within the fixed bound and
polled with killpg until ESRCH. Normal completion also fails if descendants remain.

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

Quantitative evidence is exclusively recorded in `docs/onyx/checkpoints/phase5-capability-nexus-v19/phase5-capability-nexus-v19.metrics.json`.
No quantitative result in this checkpoint is authoritative outside that structured artifact.

V19 remains isolated, default-off, shadow-only, not live and externally unaccepted.
It adds no authority, dispatch, writes, providers, ports, flags, inheritance or
startup wiring.
