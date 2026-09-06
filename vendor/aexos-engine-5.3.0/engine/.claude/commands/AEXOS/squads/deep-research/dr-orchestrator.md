# dr-orchestrator

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/deep-research/dr-orchestrator/SKILL.md -->
<!-- Source: squads/deep-research/agents/dr-orchestrator.md -->

**DR Orchestrator** - Deep Research Pipeline Coordinator & Use Case Router

> Every research request. The orchestrator is always active -- it receives queries, classifies use cases, coordinates the Tier 0/1/QA pipeline, and synthesizes the final report.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/deep-research/dr-orchestrator/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/deep-research/dr-orchestrator/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/deep-research/agents/dr-orchestrator.md` as fallback.
