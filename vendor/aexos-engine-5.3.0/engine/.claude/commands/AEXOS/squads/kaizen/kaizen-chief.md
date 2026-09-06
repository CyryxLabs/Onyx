# kaizen-chief

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen/kaizen-chief/SKILL.md -->
<!-- Source: squads/kaizen/agents/kaizen-chief.md -->

**Kaizen Chief** - Ecosystem Intelligence Orchestrator

> Use when you need to analyze the health of the AI agent ecosystem, detect gaps in competencies or tools, monitor performance, track costs, or generate weekly resource recommendations. This is the entry point for all Kaizen Squad operations.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen/kaizen-chief/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen/kaizen-chief/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen/agents/kaizen-chief.md` as fallback.
