# Phase 6 Research + Independent Verifier Cells V1 External E6 Acceptance

- Evidence ID: `VE-P6-RESEARCH-CELLS-V1-E6-001`
- Decision date: 2026-07-23
- Decision: **ACCEPTED — isolated provider-free default-off candidate**
- Candidate: `phase6-research-cells-candidate-001`

## Frozen candidate

This decision accepts candidate manifest
`216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab`
and its exact 5/5 artifact root
`8cbf4837eec80a560885cf000b8ba3856f595057c2dbddfa58592c2dda593e4d`.

| Artifact | SHA-256 |
|---|---|
| `core/phase6_research_cells_v1.py` | `e5eb0c05998aa07c8b63824f93842a602e5fe93f82d566b668bd7afd11ee7013` |
| `tests/test_phase6_research_cells_v1.py` | `f75d7410150c89f3478d81a3ed2fae193100180c93e98f7e699a9081de9e5dc7` |
| `scripts/verify_phase6_research_cells_v1.py` | `21fd7fcb928bf56a53df166a2a3c7e8e3a3da93e26f172e67454d18aedf1d479` |
| `docs/onyx/adrs/ADR-0023-phase6-research-cells-v1.md` | `edae93cce8ed2649c858c972e69b4e548bb28937068d8708feabe6d3012b59ae` |
| `docs/onyx/checkpoints/phase6-research-cells-v1/PHASE6_RESEARCH_CELLS_V1_CHECKPOINT.md` | `c631a83f2fb6496ccf7986fb02e7693d3e5c6c54b7e4eebf832fff0fca050c0b` |

Nine frozen anchors bind the defining Agentic Core V1 types, accepted Agentic
Core V6 code/manifest/E6, `main.py`, UI, dashboard, Live Wiring V1 and
Activation V9.

## Independent gate and resolved findings

Final decision: **P0=0, P1=0, P2=0, P3=0** for the frozen candidate.

The external audit reproduced and resolved five P1 findings before freeze:

1. evidence sources were HMAC-authenticated, but bundle identity and membership
   did not carry their own HMAC;
2. authenticated receipt/output maps did not bind their dictionary key to the
   receipt request ID, allowing replay alias drift;
3. adversarial candidate citation count and serialized candidate bytes were
   not checked against the request item/byte budget;
4. the verifier could accept omission of one of multiple same-value source
   citations because pair coverage did not require the exact projection; and
5. conflicting concurrent replay was not serialized around replay and commit.

The frozen candidate now HMAC-authenticates source and bundle separately,
binds replay maps exactly, bounds candidate claims/citations/bytes, reconstructs
the exact expected claim/citation projection, and serializes research, verify
and finalize with an exact reentrant lock. Adversarial regressions reproduce
each former boundary and require fail-closed denial.

## Accepted behavior

The independent review confirmed:

- exact open `AgenticCoreV6`, `AgenticStateStoreV6` and `WorkspaceScopeV1`
  identity and exact inherited research/verifier operator profiles;
- distinct operator, instruction and complete cell-identity digests;
- source and bundle HMAC-SHA-256, content addressing, workspace binding,
  classification, URI, source/span, timestamp and freshness validation;
- instruction-like source text remains opaque data and no public operation
  accepts an instruction parameter;
- research deterministically projects claims, exact citations,
  contradictions and freshness but always emits `candidate_not_certified` and
  `certified=false`;
- the independent verifier generates no facts, validates every claim/citation,
  exact coverage, contradictions and freshness, and emits only
  `ACCEPT`, `REVISE` or `REJECT`;
- finalization succeeds only for an authenticated verifier `ACCEPT` bound to
  the exact research candidate and evidence bundle;
- source, span, claim, citation, byte, age and deadline budgets plus explicit
  cancellation;
- idempotent identical replay and fail-closed conflict, concurrent conflict,
  forge, output/authority/map drift, future timestamp, classification and
  cross-workspace input;
- no provider/model call, endpoint, credential, network import, live route or
  activation.

The gate reproduced `P6_RESEARCH_CELLS_V1_OK`, **22/22 focused tests** and
**178/178 cumulative Agentic Core V1-V6, Provider Registry and Research Cells
tests**. Ruff lint, formatting and Python compilation passed. The live-surface
scan inspected 204 files without finding an import or enablement path.

## Exact boundary

The candidate remains **isolated, default-off, provider-free, unwired and not
live**. This acceptance does not set
`ONYX_PHASE6_RESEARCH_CELLS_V1=true`, acquire a source, browse, call a provider,
contact a network, judge truth beyond authenticated structured evidence, alter
a live route, unlock Phase 6 or claim Onyx completion.

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_phase6_research_cells_v1_acceptance.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_phase6_research_cells_v1_acceptance.py
```

The verifier must emit `P6_RESEARCH_CELLS_V1_ACCEPTANCE_OK`.
