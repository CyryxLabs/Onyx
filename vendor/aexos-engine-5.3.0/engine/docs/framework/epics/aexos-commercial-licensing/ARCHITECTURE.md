# AEXOS Entitlement and Paid Distribution Architecture

**Status:** Proposed
**Rule:** licensing is an AEXOS control-plane capability, never an agent or
Cerberus-worker authority.

## Topology

```text
Payment Provider
      |
      v
Commercial Backend --verified event--> License Authority
                                           |
                                  signed entitlement
                                           |
                                           v
Authenticated Artifact Service ----> AEXOS License Client
                                           |
                                  verified local cache
                                           |
                                           v
                                  Entitlement Resolver
                                      /           \
                            AEXOS Runtime      Recovery Allowlist
                                  |
                          Knowledge Gateway
                                  |
                          Cerberus Worker
```

## Authority boundaries

- The payment provider proves a transaction event to the commercial backend.
- The License Authority is the only issuer of signed entitlements.
- The Artifact Service distributes signed release candidates but cannot mint
  entitlements.
- The local Entitlement Resolver verifies signatures and policy. It cannot
  create, extend or upgrade a license.
- AEXOS Master consumes an entitlement decision but cannot override it.
- Cerberus receives only an already-authorized capability request.

## Canonical entitlement envelope

The final schema must be versioned and strict. At minimum it binds:

- schema and key identifiers;
- entitlement and customer/organization identifiers;
- product and plan;
- allowed feature/capability identifiers;
- seat policy;
- issued, not-before and expiry times;
- offline-cache and grace policy;
- allowed release channel/version range;
- revocation epoch or equivalent freshness control;
- signature.

Unknown fields and algorithms fail closed. The client package contains only
public verification keys with rotation metadata.

## Runtime state machine

```text
NOT_ACTIVATED -> ACTIVATING -> ACTIVE -> OFFLINE_VALID -> GRACE
      ^              |          |            |             |
      |              v          v            v             v
   RECOVERY <------ ERROR     REVOKED       EXPIRED       EXPIRED
```

`ERROR` is not `ACTIVE`. Transport failure is distinguished from entitlement
denial, but neither creates authority beyond a still-valid signed offline
cache.

## Enforcement placement

The primary enforcement point is the canonical CLI/runtime dispatch boundary.
Generated agents, skills, prompts and IDE files must not contain independent
licensing logic. Secondary gates protect direct programmatic exports, installer
operations and worker startup.

Recovery allowlist:

- `aexos license status|activate|validate|recover|deactivate`;
- version and license-safe doctor output;
- export of user-owned project data;
- uninstall and local cleanup limited to installer-owned artifacts;
- access to the applicable license terms and support instructions.

## Internal development and CI

- Internal developer and CI entitlements are signed by a distinct key or
  constrained issuer and auditable as non-customer credentials.
- CI entitlements are short-lived and bound to approved workflows/artifacts.
- Tests use deterministic fixture keys whose private key is test-only and
  rejected by production builds.
- No `AEXOS_SKIP_LICENSE`, magic hostname, debug flag or source-tree detection
  grants production authority.

## Data and privacy

The licensing system may receive product/version, entitlement, organization,
seat, privacy-bounded device binding and security/audit metadata. It must not
receive source code, documents, prompts, agent conversations, Cerberus indexes,
transcripts or retrieved passages.

## Cerberus integration

The Knowledge Gateway requests a capability decision such as
`knowledge.text`, `knowledge.documents`, `knowledge.media`,
`knowledge.semantic` or `knowledge.conclave`. It starts the worker only after
authorization. The worker protocol does not carry payment or raw license
credentials.

## Migration and rollback

1. Ship entitlement infrastructure dark and non-enforcing.
2. Validate signed fixtures and authenticated artifact installation.
3. Run shadow decisions and compare expected coverage without blocking users.
4. Approve replacement license and commercial parameters.
5. Produce a paid-only release candidate with Community surfaces removed.
6. Test old-version detection, explicit upgrade acceptance and rollback.
7. Enable enforcement only in the exact signed candidate.

Rollback returns to the previous candidate but never changes the license terms
of an already distributed version or deletes customer data.

## Security gates

- signature forgery, key substitution and downgrade tests;
- replay, duplicate purchase and webhook-ordering tests;
- cache tamper, clock rollback and machine-clone tests;
- seat-race and activation-rate-limit tests;
- artifact substitution and version-confusion tests;
- secret and PII scans on source, logs, tarball and extracted installation;
- recovery commands proven available under every failure state;
- independent QA review of the same artifact selected for release.
