# Phase 5.3 Capability Nexus V1 checkpoint

Status: **candidate — default-off, shadow-only, external acceptance pending**

This candidate adds an isolated, additive Capability Nexus contract around the
current system. It does not import or modify startup, the live dispatcher,
providers, UI, dashboard, launcher, session grants, approval-inbox candidates,
ports, runtime flags, or owner data. No existing behavior is routed through the
candidate.

## Scope and authority boundary

- `CapabilityDescriptor` and `OperationDescriptor` are immutable, versioned,
  bounded records for provider/API/transport identity, explicit
  read/draft/mutate/verify/reconcile operations, required scopes, data classes,
  risk and approval metadata, opaque credential aliases, workspace/account/
  profile binding, allowlisted targets/domains, pagination, rate limits,
  cancellation, timeout, idempotency, receipts, reconciliation, quota, cost,
  dry-run/test-account support, limitations, license review and degraded state.
- Secret-shaped fields and values, noncanonical identifiers, duplicate
  operations, unknown schema/enum values and unbounded metadata fail closed.
- `CapabilityNexusV1` accepts only the exact default-off/shadow-only gate. It
  registers descriptors and returns immutable discovery/health projections;
  projections always state `runtime_available=false` and
  `authority_granted=false`. There is no execution or dispatch surface.
- Duplicate or unknown capabilities, workspace/account mismatch, version drift,
  digest drift and revoked aliases fail closed. The projection kill state makes
  every entry disabled without altering a descriptor or live behavior.

## Legacy parity projection

`build_legacy_descriptors` is a pure builder. The trusted host supplies the
current `TOOL_DECLARATIONS` and exact host policy mapping; the builder imports
neither `main.py` nor the permission broker. Missing, extra or duplicate policy
coverage fails closed. Tests parse the current source in test context and prove
all 26 declarations, names, parameter schemas and policy values round-trip
without changing either source byte. Legacy operations without a separately
trusted semantic classification are conservatively labeled `mutate`; all
legacy descriptors remain disabled and state that dispatch/policy behavior is
unchanged.

## Provider-free read-only contract

`LocalReadOnlyCatalogAdapterV1` is a bounded in-memory catalog over constructor-
allowlisted metadata. It performs no file, network, browser, provider, vault,
MCP or mutation access. It requires exact workspace/account/profile/target
binding and one explicit read scope. Its pagination cursors are HMAC-bound to
the capability/version/bindings and immutable catalog snapshot. Exact
correlation/request binding makes duplicate reads idempotent; payload drift on
the same correlation ID denies.

The adapter reports authentication, scope, API version, quota and zero local
cost truthfully. Fixed-window rate limiting, cancellation before/after read,
timeout before/after read, disabled/degraded modes, kill state, immutable read
receipts and read-only reconciliation are exercised. Draft and mutation calls
always deny. A read observed before a late cancellation/timeout remains an
observed read; a pre-read stop is verified to have no external effect.

## Verification and evidence

The frozen evidence package contains:

- focused contract/adversarial JUnit and raw log;
- a static gate log for Ruff, compilation, whitespace, diff scope and stable
  regressions;
- a live-source SHA-256 scan proving no startup/runtime source imports this V1;
- a canonical verification bundle with environment, commit, commands, counts,
  claims, file hashes and limitations;
- an artifact manifest and a one-edge root manifest.

The verifier checks exact artifact hashes, JUnit counts, static claims, the
live-source scan, source-level isolation, descriptor semantics, actual legacy
parity, and a fresh focused test run. The artifact manifest is the only leaf of
the root manifest; the bundle excludes its own hash and both manifests to avoid
a circular DAG.

## Rollback

There is no migration or live state to reverse. Stop importing the isolated V1
module from explicit test/development callers or remove the new candidate files.
The current live dispatcher and permission callback continue unchanged. An
unknown read correlation remains `unknown_correlation`; there is no external
effect to retry or delete.

## Limitations and decisions retained

- This is not a live connector registry, authorization boundary, provider
  integration, MCP adapter, credential resolver, persistence layer or UI.
- Legacy descriptors describe compatibility contracts; they do not normalize
  legacy runtime outcomes and do not change tool risk classification.
- The local adapter is provider-free metadata only. It proves the shared read
  contract but does not prove external OAuth, webhooks, provider receipts or
  mutation reconciliation.
- No license or provider-access decision is changed.
- Phase 5.3 external E6 and complete Phase 5 E1-E6 remain pending independent
  review. This checkpoint cannot accept or activate itself.
