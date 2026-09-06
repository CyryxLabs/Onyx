# Phase 5.3 Capability Nexus V16 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V16 preserves rejected V1–V15 byte-for-byte.

The V14 closed metadata provenance/type contract is unchanged. Metadata values
remain exact frozen enums per key, with `declaration_sha256` as the sole lowercase
hexadecimal typed field. Content scanners remain confined to descriptions,
canonical schemas and legacy declarations.

V16 changes evidence enforcement only. One CLI parent owns a single monotonic
deadline. It launches the focused pytest process directly and then launches a
pure artifact-verification worker with only the remaining budget. The worker has
no subprocess surface. Any direct phase timeout fails closed without retry or an
acceptance marker.

Stable regression evidence includes a canonical pytest report for each base test
and subtest. Stable identities, parent mapping, context, outcome and uniqueness
are reconciled with JUnit testcase children and suite counters. A synthetic JUnit
counter delta is invalid unless the separately hash-bound subtest report accounts
for it exactly.

Combined suites, stable regressions, recursive history traversal, tamper fixtures,
static gates, live boundaries, artifact membership and measured verifier runtime
are recorded in canonical structured evidence. The verifier checks schemas,
selected-suite uniqueness, exit codes, JUnit child/counter reconciliation,
recursive manifest and leaf sets, fixture uniqueness, hashes and cross-artifact
consistency. Bundle claims and this checkpoint are also checked semantically.

Quantitative evidence is exclusively recorded in `docs/onyx/checkpoints/phase5-capability-nexus-v16/phase5-capability-nexus-v16.metrics.json`.
No quantitative result in this checkpoint is authoritative outside that structured artifact.

V16 remains isolated, default-off, shadow-only, not live and externally unaccepted.
It adds no authority, dispatch, writes, providers, ports, flags, inheritance or
startup wiring.
