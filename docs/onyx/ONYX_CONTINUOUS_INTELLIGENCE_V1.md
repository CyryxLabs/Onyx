# Onyx Continuous Intelligence V1

Date: 2026-09-04  
Owner: Cyryx Labs  
Epic: `ONYX-CONTINUOUS-INTELLIGENCE-AUTONOMY-V1`

## Purpose

This successor adds a governed learning and opportunity-intelligence plane to Onyx without changing the accepted desktop/mobile HUD or humanoid.

## Implemented in source

- A rapid, resumable owner interview with ten bounded questions covering learning consent, company context, role, objective, priority departments, language, response detail, work cadence and economic target.
- Owner-confirmed answers stored in the existing workspace-bound personalization database.
- Conversation learning that remains inactive until explicit consent and persists only typed, low-risk inferred candidates. It stores a one-way provenance digest, not the raw conversation.
- Candidate confirmation, editing, revocation, export and deletion through the existing personalization contract and the new `onyx_learning_cli.py` surface.
- Prompt projection of confirmed, fresh records only. Inferred, stale and revoked records are excluded.
- Provider-free BM25/local-vector fusion over records already authorized by the caller.
- An exact-version AEXOS 5.3.0 read-only process adapter pinned to commit `5342f5a7c1ab6212087da2011265c11f1002503f` and authenticated root artifacts.
- A self-contained, exact-version AEXOS 5.3.0 sidecar with hash-pinned engine and Node runtime, production-only dependencies and fail-closed attestation before use.
- A task-first AEXOS department planner that authenticates the registry, ranks up to four squads, binds the plan to a story and hard micro-USD ceiling, and seals that exact context into the existing Phase 11 external-agent receipt boundary.
- A structured `opportunity_research` model tool and CLI path that produce current cited evidence while marking every result as untrusted and non-actionable.
- A verified economics guard that computes gross margin only from complete, same-currency, verified revenue and direct-variable-cost evidence.
- A workspace-bound opportunity queue. Promotion requires at least two independent source hosts, score >= 60, no instruction-injection signal, economics at or above the configured target, and an exact owner approval token. Even an approved candidate remains non-actionable.
- A persistent owner/workspace-bound opportunity monitor with exact source allowlists, bounded cadence and daily runs, freshness and contradiction signals, transactional leases, durable kill/resume and non-actionable digests.
- A centralized FFmpeg resolver for owner-configured or system runtimes. The restricted media binary shipped by Playwright is deliberately not reported as full audio/social-video capability because it lacks the required MP3 and H.264 codecs.

## Deliberately not claimed

- This is not online fine-tuning and does not alter Gemini or other provider weights.
- Local feature-vector retrieval is not claimed as model-embedding semantic parity. A provider/model embedding successor still needs privacy, cost, migration and evaluation gates.
- AEXOS discovery, routing and execution-context binding are operational. Actual coding dispatch remains provider-dependent and requires an execution-bound authenticated account receipt; the installed Claude Code adapter does not provide one and therefore remains health-only.
- Scheduled opportunity digests are enabled, but autonomous outreach, purchasing, publication, deployment or account mutation is not.
- Source tests and live read-only research do not equal packaged, installed, physical-device, OAuth/account or public-release certification.
- The external knowledge-product repository was not cloned into Onyx and no implementation code or branding from it is included.

## Owner controls

```powershell
python scripts/onyx_learning_cli.py --database <path> --owner <id> --workspace <id> status
python scripts/onyx_learning_cli.py --database <path> --owner <id> --workspace <id> questions
python scripts/onyx_learning_cli.py --database <path> --owner <id> --workspace <id> answer learning_consent yes
python scripts/onyx_agentic_cli.py research "enterprise AI automation demand" --mode news --limit 5
python scripts/onyx_agentic_cli.py economics --revenue-micro 1000000 --cost-micro 200000 --currency USD --revenue-source contract:1 --cost-source invoice:1 --target-bp 8000 --verified
python scripts/onyx_agentic_cli.py aexos-status
python scripts/onyx_agentic_cli.py department-plan "research and build a product marketing plan" --story ONYX-CL-02 --budget-micro-usd 500000
python scripts/onyx_agentic_cli.py monitor configure --schedule-id ai-ops --query "AI operations demand" --domain example.com --domain example.org --interval-seconds 3600
python scripts/onyx_agentic_cli.py monitor run
python scripts/onyx_agentic_cli.py monitor digests
python scripts/onyx_agentic_cli.py monitor kill
```

The `--verified` economics switch is an owner/operator assertion for local analysis. It is not accepted as proof by itself for autonomous execution or public commercial claims.

## Visual boundary

No QML, Three.js, humanoid image/data, CSS, palette, voice, animation or primary-layout source belongs to this successor. Existing visual-freeze gates remain authoritative.

## Successor release boundary

The source successor is versioned as Onyx `1.1.25` under Release Workflow V90. The workflow remains deliberately non-publishable and non-formal without the existing Authenticode/public-distribution authority. Package and installed-runtime evidence are recorded separately from source evidence. V90 narrowly retains the five inert, hash-bound test-named files required by the Cyryx-owned AEXOS 5.3.0 install manifest; all other development test payload remains excluded.
