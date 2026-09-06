# kaizen-v2-chief

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-chief/SKILL.md -->
<!-- Source: squads/kaizen-v2/agents/kaizen-v2-chief.md -->

**Kaizen V2 Chief** - Ecosystem Intelligence Orchestrator (v2 — Daily + Weekly)

> Use to analyze ecosystem health, manage daily intelligence capture, extract patterns from learnings, generate reports with insights, or coordinate all kaizen-v2 agents. Entry point for Kaizen Squad v2 operations.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-chief/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-chief/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen-v2/agents/kaizen-v2-chief.md` as fallback.
