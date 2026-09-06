---
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools: [architecture_review, code_review, privacy_boundary_test, visual_freeze]
---

# Story ONYX-CL-01-CONTINUOUS-LEARNING-ONBOARDING-V1

**Status:** Done  
**Epic:** `ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1`

## Story

**As an** Onyx owner,  
**I want** a short first-run interview and governed learning from explicit conversational preferences,  
**so that** Onyx becomes personalized over time without retaining raw transcripts or silently changing its authority.

## Acceptance criteria

1. A resumable, versioned interview captures only predefined business, communication, objective, economics and learning-consent fields.
2. Answers are owner-confirmed records in the existing workspace-bound personalization store; secrets and authority-bearing keys are rejected.
3. Conversation learning is inactive until explicit consent and then creates only typed, low-risk inferred candidates; it never stores a raw turn.
4. Inferred candidates do not affect prompts until explicitly confirmed.
5. Confirmed, fresh preferences produce a bounded trusted-local prompt fragment; stale, revoked and inferred records do not.
6. The owner can inspect, confirm, edit, revoke, export and delete records through machine-readable CLI operations.
7. Retrieval provides deterministic lexical/vector fusion over already-authorized records, with bounded inputs and no provider call.
8. Runtime integration is additive and cannot prevent Onyx from starting if personalization storage is unavailable.
9. No humanoid, visual asset, QML, Three.js, CSS, palette or primary-layout file changes.

## Tasks

- [x] Audit existing memory, refinery, owner profile and personalization foundations.
- [x] Implement interview, consent and prompt projection contracts.
- [x] Implement candidate extraction and hybrid ranker.
- [x] Wire the host through existing text/voice turn boundaries and tool dispatch.
- [x] Add focused, adversarial, regression and visual-freeze tests.

## File list

- `docs/stories/ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1.epic.md`
- `docs/stories/ONYX-CL-01-CONTINUOUS-LEARNING-ONBOARDING-V1.story.md`
- `core/continuous_learning_v1.py`
- `core/governed_personalization_v1.py`
- `core/capability_expansion_runtime_v1.py`
- `core/capability_expansion_service_v1.py`
- `scripts/onyx_learning_cli.py`
- `tests/test_continuous_learning_v1.py`
- `main.py`

## Dev agent record

- Vulcan implemented the provider-free learning path and runtime composition.
- Inferred conversation signals remain candidate-only and store no raw turns.
- The focused, integrated and adversarial learning gates passed in the successor qualification run.
- No visual source was edited.
