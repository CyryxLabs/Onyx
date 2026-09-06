# Phase 5.3 Capability Nexus V26 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V26 preserves rejected V1–V25 byte-for-byte.

The V14 closed metadata provenance/type contract is unchanged. Metadata values
remain exact frozen enums per key, with `declaration_sha256` as the sole lowercase
hexadecimal typed field. Content scanners remain confined to descriptions,
canonical schemas and legacy declarations.

V26 changes evidence enforcement only. Structured cleanup payloads now require
exact built-in tuple/list containers, enforce their item bound before iteration,
and count every admitted item against a bounded work budget. Canonical record
deduplication precedes capacity accounting: the boundary permits the exact
maximum plus duplicates, while the next unique record enters a separate bounded
overflow state. Overflow short-circuits all remaining traversal and is attached
to the terminal failure independently of the bounded normal-record payload.

All exception introspection in V26 is guarded. Cleanup-payload, group-child,
cause, context and suppression accessors cannot escape into the verifier. A
failed accessor preserves the original wrapper as a safely typed, bounded leaf
and adds a separate canonical access record. Exception rendering uses no repr or
pointer-bearing fallback; hostile string rendering adds its own canonical access
record. Structured record mappings and fields require exact built-in types before
truth, length, hash, equality or indexing operations.

One CLI parent owns a single monotonic
deadline and exactly two sequential process-tree roots: focused pytest and the
pure artifact-verification worker. These are two parent-owned roots, not a claim
that the operating system runs only two processes. The worker has no subprocess
surface. Any phase failure or timeout fails closed without retry or an acceptance
marker.

Every phase owns its complete process tree. V26 has no bootstrap file, process,
import, protocol, command envelope or environment surface. On Windows the parent
maps only the focused and worker identifiers to exact argv, preconfigures the Job,
creates the fixed target directly with pointer-safe CreateProcessW in suspended
state, assigns that process handle to the Job, and only then calls ResumeThread.
Create, assignment or resume failure terminates the still-suspended target and
owned Job before checked handle cleanup, so target code cannot run early.

Stdout and stderr use bounded private nonce-scoped files and checked native
handles. WaitForSingleObject shares the parent deadline; timeout terminates the
whole Job, polls active accounting to empty and reads only bounded output. The
fresh JUnit remains in the fixed private realpath/sentinel directory.

Every Windows CloseHandle result is checked. Failure retains an explicit ownership
record, suppresses the evidence marker and supports bounded later cleanup. POSIX
and macOS ownership begins immediately when Popen returns. Group discovery and
every later operation are inside one outer cleanup boundary. If group discovery
fails or returns a group other than the direct PID, only the direct child is
terminated, bounded-communicated, reaped and proven absent. Once the expected
group is acquired, normal, error and timeout paths retain the unified killpg,
bounded drain and group-empty proof. No failed discovery path can accept output.

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

Quantitative evidence is exclusively recorded in `docs/onyx/checkpoints/phase5-capability-nexus-v26/phase5-capability-nexus-v26.metrics.json`.
No quantitative result in this checkpoint is authoritative outside that structured artifact.

V26 remains isolated, default-off, shadow-only, not live and externally unaccepted.
It adds no authority, dispatch, writes, providers, ports, flags, inheritance or
startup wiring.
