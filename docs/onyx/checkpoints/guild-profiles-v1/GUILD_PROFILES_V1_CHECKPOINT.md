# Guild profiles V1 checkpoint

First Onyx Engineering Guild slice (Operator Cells, A9.1): a default-off,
deterministic, hermetic role-profile registry with an enforceable authority
matrix. It adds one module, one feature flag and no runtime wiring.

`core/guild_profiles_v1.py` (`ONYX_GUILD_PROFILES_V1`) is entry-bound to the
accepted Phase 10 content-draft four-file acceptance tuple. It builds
`RoleProfileV1` records (role, persona, scope, allowed/exclusive operations,
delegation targets, quality gates, byte-pinned AEXOS source) and `TeamPackV1`
squad bundles into a sealed `GuildRegistrySnapshotV1` whose
`AuthorityMatrixV1` enforces the AEXOS Constitution v1.1.0 Article II floor
(`git_push`/`pr_creation`/`release_tag` → `devops`; `story_creation` →
`po`/`sm`; `architecture_decisions` → `architect`; `quality_verdicts` → `qa`),
one-claim exclusivity with owner sets and leak rejection, a closed delegation
graph and byte-exact source pinning with a deterministic pack root.
`is_operation_permitted` and `delegation_target` are pure projections; there
is no dispatch, execution, session, grant or budget surface — those are later
guild slices. The module calls no model, opens no network, spawns no process,
persists nothing and takes no action.

The cumulative selection reproduces 674 passing tests and 96 passing subtests
across twenty-eight fresh Python processes — the twenty-seven inherited Phase 7
stable-core, Phase 8 connector, Phase 9 intelligence and Phase 10 social test
files plus this slice's forty-eight adversarial tests — with seventeen
platform-specific skips (sixteen artifact-service, one control-plane POSIX)
and zero failure/error. Per-file counts were re-observed on 2026-08-17: three
inherited files grew since the July slice-4 selection (`test_control_plane.py`
31→35 passed / 52→68 subtests, `test_artifact_service.py` 51→65 passed /
7→16 skips, `test_phase8_microsoft_graph_oauth_v1.py` 40→41 passed) through
legitimate post-July development; this selection records the observed current
counts, not the inherited July ones.

Scope and limits: registry and matrix only. No orchestration, no workflow
execution, no sessions, no grants, no budgets, no decommission mechanism, no
non-engineering squad packs, no model/provider calls. Those are later guild
slices (A9.2–A9.5), each separately accepted. The slice claims no
startup/voice/UI/dashboard wiring and no full Onyx PRD completion.
