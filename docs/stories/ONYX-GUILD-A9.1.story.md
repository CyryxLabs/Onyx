# Story ONYX-GUILD-A9.1 — Guild Role-Profile Registry & Authority Matrix V1

**Status:** Done (accepted 2026-08-17, `VE-GUILD-PROFILES-V1-E6-001`;
autonomous-session acceptance under the owner's same-night authorization —
"seguir com tudo possível essa noite... Não precisa da minha autorização";
implementation ran during the R15B soak at BelowNormal CPU priority; no
independent human review — recorded honestly in the acceptance metadata)
**Epic:** Onyx Engineering Guild (A9 expanded — `CAPABILITY_COMPLETION_PLAN_90PCT.md`)
**Owner directive:** Onyx as virtual employee replacing ~10 squads; AEXOS as
the base; termination rule encoded as mechanism.

## Story

As the Cyryx Labs owner, I want Onyx to hold a **governed, versioned registry
of role profiles** (architect, dev, qa, devops, sm, pm, po, analyst,
data-engineer, ux) with an **enforceable authority matrix**, ingested from the
first-party AEXOS framework, so that later guild slices can orchestrate
autonomous development under exactly the same exclusive-authority discipline
that governs human-facing AEXOS sessions today — with nothing granted by
default.

## Source material (verified 2026-08-17)

- Local AEXOS install: `C:\MAAX_Assistant\.aexos-core` (canonical origin
  `https://github.com/CyryxLabs/aexos-engine.git`, Cyryx Labs first-party).
- Agent personas: `development/agents/*.md` — 12 agents, markdown with an
  embedded YAML block carrying `agent` (name/id/title/icon), `persona`
  (`core_principles`), `exclusive_authority` (note/rationale/enforcement) and
  `responsibility_scope.primary_operations` with `(EXCLUSIVE)` markers
  (verified in `devops.md`: Polaris, git-push exclusivity).
- Constitution: `.aexos-core/constitution.md` v1.1.0 — Article II defines the
  exclusivity floor: `git push` → devops; `PR creation` → devops;
  `Release/Tag` → devops; `Story creation` → {sm, po}; `Architecture
  decisions` → architect; `Quality verdicts` → qa.
- Team packs: `development/agent-teams/*.yaml` — 5 bundles
  (`bundle.name/icon/description`, `agents[]`, `workflows[]`).
- Scale for later packs: 214 task files, 15 workflows, checklists, skills.

## Design (mirrors the accepted Phase 9/10 contract pattern)

Module `core/guild_profiles_v1.py` (phase prefix to be confirmed against the
master-plan numbering at implementation), flag `ONYX_GUILD_PROFILES_V1`,
**default-off**, deterministic, hermetic: no network, no model, no
subprocess, no persistence, no filesystem reads inside the contract — callers
supply parsed records plus raw bytes; the module hashes and validates.

- `RoleProfileV1` (frozen): `role_id`, `persona_name`, `title`, `scope`,
  `allowed_operations: tuple`, `exclusive_operations: tuple`,
  `delegation_targets: mapping op→role_id`, `quality_gates: tuple`,
  `source_ref` + `source_sha256` (pin to the exact AEXOS file bytes).
- `TeamPackV1` (frozen): `pack_id`, `name`, `member_role_ids: tuple`,
  `workflow_refs: tuple`, `source_ref` + `source_sha256`.
- `AuthorityMatrixV1` (sealed): built only from validated profiles.
  - `MANDATORY_CONSTITUTIONAL_EXCLUSIVES` constant mirroring Constitution
    Art. II (op → frozenset of owner role_ids, supporting owner-sets like
    story_creation → {sm, po}). A pack that omits or contradicts any entry
    is **rejected** (same pattern as Brand Passport
    `REQUIRED_POLICY_GUARDS`).
  - Every `exclusive_operation` is claimed by exactly one declared owner-set
    globally; duplicate/conflicting claims rejected.
  - Every `delegation_targets` value must be an existing role that holds the
    delegated operation; unknown roles/ops and self-referential delegation
    rejected.
- `GuildRegistryV1` (sealed, `create_guild_registry_v1`): profiles + team
  packs + matrix + `pack_root_sha256` (over all ingested source bytes) +
  `constitution_version` pin. Duplicate `role_id`/`pack_id` rejected;
  member of a team pack must exist as a profile.
- **No execution authority anywhere in this slice**: profiles describe; the
  registry validates and seals. Activation, dispatch, sessions, grants and
  budgets are later slices (A9.3–A9.5). There is no `execute`/`dispatch`
  method by construction (verifier asserts, like the no-publish assertions
  in Phase 10).

## Acceptance criteria

1. [ ] `RoleProfileV1`/`TeamPackV1`/`AuthorityMatrixV1`/`GuildRegistryV1`
       exact contracts above; default-off behind `ONYX_GUILD_PROFILES_V1`.
2. [ ] Constitutional floor enforced: missing/contradicted Art. II entry →
       rejection with typed error.
3. [ ] Global one-claim exclusivity; owner-sets supported; duplicates
       rejected.
4. [ ] Delegation graph closed: unknown role, unknown op, self-delegation of
       unowned op → rejected.
5. [ ] Source pinning: any supplied bytes whose sha256 mismatches the
       declared `source_sha256` → rejection; registry recomputes
       `pack_root_sha256`.
6. [ ] Sealed aggregates immutable; no execution/dispatch surface (verifier
       asserts absence).
7. [ ] Adversarial tests ≥ 30, covering at minimum: duplicate exclusive
       claims, forged constitutional owner, tampered bytes, empty pack,
       team pack referencing missing role, delegation cycles, flag-off
       inertness.
8. [ ] Standard evidence chain: module + tests + ADR + SOURCES +
       checkpoint + candidate verifier + independent E6; entry-bound to the
       latest accepted cumulative root (Phase 10 slice-4 root `59308ada…`,
       confirm at implementation).
9. [ ] `CAPABILITY_MATRIX.md` row "Operator Cells" updated only after E6,
       with honest limitations (registry only; no orchestration/dispatch).

## Tasks

- [x] T1. Provenance intake: AEXOS structure surveyed and recorded in
      `GUILD_PROFILES_V1_SOURCES.md` (12 agents, 5 team packs, Constitution
      v1.1.0, first-party Cyryx; byte-pinning is enforced per-record by the
      contract itself).
- [x] T2. Implement `core/guild_profiles_v1.py` per design.
- [x] T3. Adversarial test suite `tests/test_guild_profiles_v1.py` —
      48 passed, 0 failed (fresh process, 2026-08-17).
- [x] T4. ADR-0054 — guild registry & authority matrix.
- [x] T5. Checkpoint bundle + candidate verifier written; fast-mode chain
      green (root `ecd14774…`); full 28-file cumulative gate running.
- [x] T6. E6 acceptance sealed — `VE-GUILD-PROFILES-V1-E6-001`, root
      `818196ac…`, acceptance verifier reproduced the full 28-file gate
      (674/0/0/17/96); ledger + matrix rows updated; autonomous-session
      honesty boundary recorded in record, metadata and matrix.

## Incident found and healed en route (2026-08-17 night)

The first full chain run failed closed: `core/phase10_provider_connector_v1.py`
had been **edited after its 2026-07-25 E6 acceptance** (15,892 → 15,989 bytes;
drift window 07-25 → 08-10; released R15B carries the current bytes; original
bytes locally unrecoverable). Healed forward-only via
`CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md` + the
`VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001` source-integrity successor
(Capability Nexus precedent) + a current-chain content-draft acceptance
verifier. No accepted byte was rewritten.

## Explicitly out of scope (later slices)

Handoff/story contracts (A9.2), SDC workflow engine (A9.3), Phase 11
autopilot binding (A9.4), away-mode projects/grants/budgets/decommission
mechanism (A9.5), any non-engineering squad pack, any live provider or
model call.

## File List

- `docs/stories/ONYX-GUILD-A9.1.story.md` (this story)
- `core/guild_profiles_v1.py` (new)
- `tests/test_guild_profiles_v1.py` (new)
- `scripts/verify_guild_profiles_v1.py` (new)
- `docs/onyx/adrs/ADR-0054-guild-profiles-v1.md` (new)
- `docs/onyx/research/GUILD_PROFILES_V1_SOURCES.md` (new)
- `docs/onyx/checkpoints/guild-profiles-v1/GUILD_PROFILES_V1_CHECKPOINT.md` (new)
- `docs/onyx/checkpoints/guild-profiles-v1/CAPABILITY_DELTA_SNAPSHOT.md` (new)
- `docs/onyx/checkpoints/guild-profiles-v1/cumulative-selection.json` (new)
- `docs/onyx/checkpoints/guild-profiles-v1/manifest.json` (new, generated)
- `docs/onyx/corrections/CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md` (new)
- `scripts/verify_phase10_provider_connector_current_v1.py` (new)
- `scripts/verify_phase10_provider_connector_current_v1_acceptance.py` (new)
- `scripts/verify_phase10_content_draft_current_v1_acceptance.py` (new)
- `docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001.md` (new)
- `docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001.manifest.json` (new)
- `docs/onyx/VE-ACCEPTANCE-P10-PROVIDER-CONNECTOR-CURRENT-V1-E6-001.sha256` (new)
- `scripts/verify_guild_profiles_v1_acceptance.py` (new)
- `docs/onyx/acceptance/VE-GUILD-PROFILES-V1-E6-001.md` (new)
- `docs/onyx/acceptance/VE-GUILD-PROFILES-V1-E6-001.manifest.json` (new)
- `docs/onyx/VE-ACCEPTANCE-GUILD-PROFILES-V1-E6-001.sha256` (new)
- `docs/onyx/CAPABILITY_MATRIX.md` (rows: Operator Cells → PARTIAL with
  guild evidence; provider connector row cites correction + successor)
- `docs/onyx/VERIFICATION_EVIDENCE.md` (two ledger entries appended)

## Change Log

- 2026-08-17: Draft created from verified AEXOS structure during R15B soak
  night (design-only; no test runs on the host while the soak is active).
