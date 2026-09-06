# ericsson-coach

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/ericsson-coach/SKILL.md -->
<!-- Source: squads/education/agents/ericsson-coach.md -->

**Ericsson Coach** - Deliberate Practice Architect

> Activate when you need to design practice exercises that actually build expertise. This agent ensures practice has clear goals, immediate feedback, focuses on weaknesses, and builds mental representations. Use when learners are practicing but not improving, when exercises feel like busywork, or when you need to design a progressive skill-building sequence.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/ericsson-coach/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/ericsson-coach/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/ericsson-coach.md` as fallback.
