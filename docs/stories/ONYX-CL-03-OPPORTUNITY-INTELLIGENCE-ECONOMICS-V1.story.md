---
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools: [architecture_review, code_review, evidence_quality_test, economics_guard_test]
---

# Story ONYX-CL-03-OPPORTUNITY-INTELLIGENCE-ECONOMICS-V1

**Status:** Done  
**Epic:** `ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1`

## Story

Compose the existing live-ingestion and opportunity-scoring foundations into a cited opportunity queue, with explicit economics and promotion gates, so Onyx can identify real business possibilities without fabricating viability or acting without authority.

## Acceptance criteria

1. Research items retain source URL, publisher, observed/published time, retrieval time, claim type, freshness, contradiction and confidence.
2. Every opportunity links to evidence and records assumptions, unknowns, disconfirming evidence and expiry.
3. Gross margin is computed only from verified revenue and direct-variable-cost inputs; missing inputs return `unknown`.
4. A configurable 8,000 bp target can block recommendation/promotion but cannot claim the target was achieved.
5. Monitoring is bounded by source/domain allowlists, cadence, budget and owner kill switch.
6. Candidate opportunities cannot trigger outreach, spend, publication or account mutation.
7. Promotion requires evaluation thresholds and explicit owner approval; failed candidates remain inspectable and revocable.
8. No visual files change.

## Tasks

- [x] Add structured cited read-only research and compose it as a governed model tool.
- [x] Implement verified economics and 8,000 bp default margin guard.
- [x] Add the non-actionable opportunity candidate/approval lifecycle.
- [x] Compose scheduled source-registry monitoring, contradiction/freshness and digest delivery.
- [x] Run complete evaluation and release gates.

## Current evidence

- A live DDGS news query returned three current, cited results without a model call or mutation.
- Missing/unverified economics, currency mismatch and sub-target margin all produce non-eligible decisions.
- Queue approval requires two independent source hosts, no injection signal, score >= 60, verified target economics and an exact owner token; approval never authorizes an external action.
- Persistent monitors are owner/workspace scoped, use exact domain allowlists, bounded cadence/results/runs, a transactional lease and a durable kill switch.
- Digests classify freshness and surface basic contradictory evidence while remaining explicitly non-actionable and unable to promote an opportunity.

## File list

- `core/web_opportunity_research_v1.py`
- `core/opportunity_economics_v1.py`
- `core/opportunity_queue_v1.py`
- `core/opportunity_monitor_v1.py`
- `scripts/onyx_agentic_cli.py`
- `tests/test_web_opportunity_research_v1.py`
- `tests/test_opportunity_economics_v1.py`
- `tests/test_opportunity_queue_v1.py`
- `tests/test_opportunity_monitor_v1.py`
