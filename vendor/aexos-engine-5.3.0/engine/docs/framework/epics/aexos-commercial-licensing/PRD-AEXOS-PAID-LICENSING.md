# PRD — AEXOS Paid-Only Licensing

**Status:** Draft
**Product:** AEXOS Licensed Edition
**Related:** [Change Proposal](CHANGE-PROPOSAL.md)

## Product objective

Make every newly distributed production capability of AEXOS available only to
customers with a valid paid entitlement, while preserving recoverability,
offline continuity, user data and the integrity of AEXOS development and
release workflows.

## Product model

- There is no Community or free production edition in the target release.
- The public product name is AEXOS; `Core` and `Pro` cease to represent
  separately usable editions.
- Commercial plans may grant different entitlements, but every usable plan is
  paid unless the founder later authorizes a trial or promotional entitlement.
- Cerberus capabilities are AEXOS entitlements, not an independent licensing
  system.

## Primary users

1. Buyer or organization administrator purchasing and allocating access.
2. Licensed practitioner activating AEXOS on an approved machine.
3. Enterprise administrator managing seats, revocation and audit receipts.
4. Cyryx Labs developer or CI runner using an internal signed entitlement.
5. Existing user transitioning from a previously distributed Core release.

## Functional requirements

### FR1 — Purchase-to-entitlement

- A completed and verified commercial transaction can cause the licensing
  authority to issue an entitlement.
- Duplicate webhooks and retries are idempotent.
- Refund, chargeback, cancellation and manual review produce explicit states.
- Runtime clients never trust browser redirects or unsigned purchase data.

### FR2 — Activation

- `aexos license activate` accepts an activation credential without logging it.
- The license service returns a signed, versioned entitlement envelope.
- Activation binds the authorized customer, product, plan, feature set, seats,
  validity and offline policy.
- Machine binding is privacy-bounded and reset/recovery is supported.

### FR3 — Runtime enforcement

- Every executable AEXOS entrypoint resolves one canonical entitlement state.
- Entitlement is checked at the authority boundary, not independently inside
  every agent or generated IDE projection.
- Unknown, malformed, forged, expired and revoked states fail closed.
- Status, activation, recovery, export, uninstall and essential diagnostics are
  available without an active license.

### FR4 — Offline operation

- A signed cache permits explicitly bounded offline operation.
- Cache age, clock rollback and signature failures are detected.
- Grace behavior is deterministic and visible to the user.
- Network failure does not silently convert an invalid license into a valid one.

### FR5 — Seats and organizations

- The service supports seat allocation, release, transfer and bounded recovery.
- Concurrent activation conflicts are explicit and auditable.
- Organization administrators cannot read project content through the license
  service.

### FR6 — Authenticated distribution

- Production artifacts are delivered only through an authenticated channel or
  another mechanism approved by the architecture and legal gates.
- Artifact manifest, version, platform, SHA-256 and signature are verified
  before installation.
- A license never authorizes a different artifact, version or release channel
  than its entitlement permits.

### FR7 — Cerberus

- `knowledge.ingest`, document/media extraction, search, RAG and Conclave map to
  explicit AEXOS entitlements.
- Cerberus never contacts the license server directly.
- AEXOS validates entitlement before launching or requesting the worker.
- License telemetry contains no ingested content or knowledge metadata beyond
  privacy-approved operational counters.

### FR8 — Transition

- The installer detects previously distributed Core/Community installations.
- It explains the applicable historical rights and target upgrade terms without
  claiming retroactive revocation.
- Upgrade requires explicit acceptance of the new release terms.
- Declining the upgrade leaves the prior installation and user data intact.

## Non-functional requirements

- Ed25519 or an architecture-approved asymmetric signature scheme; private
  signing keys never ship with the client.
- No raw license key, payment credential or access token in logs, traces,
  analytics, crash reports or Virtual Office events.
- Constant, typed public errors that do not disclose service internals.
- Idempotent activation/deactivation and crash-safe cache writes.
- Windows, Linux and macOS support.
- Clock-skew and rollback tests.
- License checks add a measured, bounded overhead and do not contact the server
  for every agent turn.
- Accessibility and non-coercive UX for activation and recovery.

## Success metrics

- 100% of production entrypoints covered by the entitlement boundary.
- Zero packaged Community/free-production claims in the paid-only artifact.
- Zero usable production capability after an invalid entitlement, excluding
  the recovery allowlist.
- 100% pass for activate, offline, grace, expiry, revoke, seat conflict,
  recovery and uninstall fixtures.
- Zero loss or mutation of project knowledge from licensing transitions.
- Same-artifact installation and license verification pass on every supported
  platform.

## Out of scope for the first paid-only release

- Usage-based metering or token resale.
- License enforcement implemented by agents or prompts.
- Blockchain licensing.
- Remote access to customer project content for entitlement validation.
- Retroactive relicensing of copies already distributed.

## Release blockers

- Replacement commercial license not approved by qualified counsel.
- Commercial parameters in the change proposal remain undecided.
- Production license API or signing authority remains a scaffold.
- No authenticated artifact distribution and rollback path.
- Incomplete recovery allowlist or destructive expiry behavior.
- Cerberus release enabled without passing the same entitlement matrix.
