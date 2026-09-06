# tech-radar

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen/tech-radar/SKILL.md -->
<!-- Source: squads/kaizen/agents/tech-radar.md -->

**Tech Radar** - Technology Evaluator & Fitness Function Architect

> Use when you need to evaluate the technology landscape of the ecosystem: - Evaluate whether a tool, API, MCP, library, or AI model should be adopted - Maintain the living Technology Radar with quadrant/ring classifications - Run architectural fitness functions to validate quality characteristics - Compare competing tools with structured head-to-head analy...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen/tech-radar/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen/tech-radar/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen/agents/tech-radar.md` as fallback.
