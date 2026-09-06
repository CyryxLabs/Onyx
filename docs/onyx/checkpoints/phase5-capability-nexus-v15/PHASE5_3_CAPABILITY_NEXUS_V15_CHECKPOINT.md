# Phase 5.3 Capability Nexus V15 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

V15 preserves rejected V1–V14 byte-for-byte.

The V14 closed metadata provenance/type contract is unchanged. Metadata values
remain exact frozen enums per key, with `declaration_sha256` as the sole lowercase
hexadecimal typed field. Content scanners remain confined to descriptions,
canonical schemas and legacy declarations.

V15 changes evidence enforcement only. Every subprocess is routed through one
bounded runner with an explicit positive timeout. Timeout expiration raises a
verifier error immediately; no output or artifact produced after expiration can
be accepted. Fresh focused tests and stable regressions are compared through
temporary JUnit results rather than summary-text matching.

Combined suites, stable regressions, recursive history traversal, tamper fixtures,
static gates, live boundaries, artifact membership and measured verifier runtime
are recorded in canonical structured evidence. The verifier checks schemas,
selected-suite uniqueness, exit codes, exact JUnit totals, recursive manifest and
leaf sets, fixture uniqueness, hashes and cross-artifact consistency. Bundle claims
and this checkpoint are also checked semantically.

Quantitative evidence is exclusively recorded in `docs/onyx/checkpoints/phase5-capability-nexus-v15/phase5-capability-nexus-v15.metrics.json`.
No quantitative result in this checkpoint is authoritative outside that structured artifact.

V15 remains isolated, default-off, shadow-only, not live and externally unaccepted.
It adds no authority, dispatch, writes, providers, ports, flags, inheritance or
startup wiring.
