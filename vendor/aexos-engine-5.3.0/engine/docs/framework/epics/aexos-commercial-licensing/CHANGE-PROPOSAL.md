# AEXOS Paid-Only Licensing — Change Proposal

**Status:** Proposed — founder direction recorded, commercial parameters pending
**Date:** 2026-08-20
**Owner:** AEXOS Product
**Architecture gate:** AEXOS Architect
**Legal gate:** qualified counsel before license replacement or external distribution

## Decision

Future AEXOS releases will not offer a Community, Core-free or other
zero-price production edition. AEXOS will be one commercially licensed product,
activated by an entitlement issued after purchase.

This decision applies prospectively. It does not rewrite Git history, revoke
rights already granted by an older release, or change the terms attached to a
copy that was previously distributed. Transition treatment for existing users
must be documented before the effective paid-only release.

## Trigger and evidence

- The current `LICENSE` explicitly grants a no-fee Core Edition.
- `package.json` still ships `docs/community/` and public framework surfaces.
- The CLI exposes Pro activation, buyer and seat commands.
- The checked-in `pro/` implementation declares itself a scaffold and its
  licensing operations intentionally throw `ProNotImplementedError`.
- Cerberus is planned as an AEXOS-owned optional subsystem and therefore must
  consume AEXOS entitlements rather than introduce a second commercial or
  licensing authority.

The product direction is approved, but immediate enforcement is unsafe until a
real entitlement service, signed offline cache, recovery path and clean-package
distribution channel exist.

## Recommended path

1. Replace the Core/Pro product split with one AEXOS Licensed Edition.
2. Implement the entitlement and distribution architecture in this epic.
3. Keep licensing control-plane commands available before activation.
4. Gate executable product capabilities, including Cerberus, only after the
   same artifact passes activation, offline, expiry and recovery tests.
5. Remove Community wording and free-edition artifacts only in the release
   candidate, after legal approval of the replacement license.

## Non-negotiable safeguards

- Expiry, revocation or validation failure never deletes or corrupts user data.
- Users can inspect status, activate, recover, deactivate, export their data and
  uninstall without an active entitlement.
- Core diagnostics needed to resolve a licensing failure remain callable.
- Development and CI use explicit signed internal entitlements; there is no
  undocumented environment-variable bypass in shipped code.
- Offline operation is bounded by a signed cache and an explicit grace policy.
- License-server failure has a typed result and never masquerades as a valid
  entitlement.
- The license service never receives ingested Cerberus content, prompts,
  project files or model output.
- Payment evidence is not itself a runtime license. Only a signed entitlement
  issued by the licensing authority activates AEXOS.

## Epic impact

- **AEXOS Evolution:** distribution, installer, CLI and documentation surfaces
  gain a paid-only release dependency.
- **Cerberus Knowledge Plane:** AEX.12 installer lifecycle and AEX.16 release
  certification must validate licensed, offline-grace, expired and revoked
  states. Cerberus remains technically optional but commercially entitled.
- **Virtual Office:** shows sanitized license state only; it does not activate,
  validate or store license secrets.
- **Pro scaffold:** becomes migration input, not the production authority.

## Decisions required before implementation stories become Ready

1. Commercial term: subscription, perpetual with maintenance, or both.
2. Entitlement unit: named user, organization seat, machine seat, or a defined
   combination.
3. Offline cache duration and grace duration.
4. Whether a time-limited trial exists. No trial is assumed by this proposal.
5. Payment provider, tax/invoicing system and license-service deployment owner.
6. Migration offer and support period for existing Core/Community users.
7. Effective version and date for the paid-only license.

## Approval boundary

This proposal authorizes PRD, architecture and story preparation. It does not
authorize changing `LICENSE`, closing a public repository, unpublishing a
package, charging a customer, deploying a license server, committing, pushing
or releasing.
