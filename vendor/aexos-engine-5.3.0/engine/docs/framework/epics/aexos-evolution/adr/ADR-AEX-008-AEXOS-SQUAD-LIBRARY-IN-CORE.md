# ADR-AEX-008: Expanded AEXOS Squad Library in Core

## Status

Accepted on 2026-08-11 by direct Product Owner instruction. Implemented by
[STORY-AEX.8](../STORY-AEX.8-AEXOS-SQUAD-LIBRARY.md).

## Context

AEXOS requires a broader set of complete domain squads while preserving one
installation, one routing registry, one product identity and one ownership
boundary. The library contains eleven executable task-first squad domains.

[ADR-AEX-007](./ADR-AEX-007-PRO-TIER-SQUAD-SUBSCRIPTION.md) proposes that future
paid squads use subscription-gated distribution. The Product Owner explicitly
classifies this eleven-squad library as part of AEXOS Core.

## Decision

### 1. Eleven squads ship in Core

`apex`, `brand`, `curator`, `deep-research`, `dispatch`, `education`, `kaizen`,
`kaizen-v2`, `legal-analyst`, `seo`, and `squad-creator` live under the canonical
`squads/` root and are installed, registered and projected through the same
mechanisms as all other AEXOS Core squads.

### 2. Only executable squads are registered

A squad must have a canonical manifest plus non-empty agents, tasks and
workflows. Documentation-only and marketing-only directories are not runtime
capabilities and do not enter the registry.

### 3. Product identity and ownership are singular

All operational content uses AEXOS and Cyryx Labs LLC identity. Each manifest
declares Cyryx Labs LLC as author and carries no separate license grant. The
library forms part of the Software governed by the root AEXOS Proprietary
License, owned by Cyryx Labs LLC.

No historical product, company, repository, contributor, acquisition, commit or
licensing metadata is distributed with the squad library.

### 4. Compatibility adapters preserve executable behavior

Agent definitions are normalized to parseable AEXOS YAML while retaining their
domain instructions. Manifests are normalized to task-first `squad.yaml`.
Kaizen V2 identities are namespaced so both generations remain routable.

Added scripts are treated as content during validation; deployment, remote,
scraping and destructive scripts are not executed automatically.

## Consequences

### Positive

- AEXOS gains eleven domain squads through the existing Core pipeline.
- Installation and routing remain deterministic and automatic.
- There is one product identity, owner and license boundary.

### Costs and risks

- The library is large and internally heterogeneous; AEXOS owns ongoing
  compatibility and quality maintenance.
- Bulk identity changes can corrupt syntax, so parse and regression gates are
  mandatory.
- Agents operating in professional domains must retain appropriate safeguards
  and must not imply endorsement by people whose methods they reference.

## Relationship to ADR-AEX-007

ADR-AEX-007 remains the proposed architecture for future subscription-gated
squads. ADR-AEX-008 controls only the eleven named Core squads above.

## References

- `docs/framework/epics/aexos-evolution/STORY-AEX.8-AEXOS-SQUAD-LIBRARY.md`
- `docs/framework/epics/aexos-evolution/adr/ADR-AEX-007-PRO-TIER-SQUAD-SUBSCRIPTION.md`
- `.aexos-core/schemas/squad-schema.json`
- `scripts/normalize-squad-manifests.js`
- `scripts/generate-squad-registry.js`
- `packages/installer/src/installer/squad-scaffolder.js`
- `LICENSE`
