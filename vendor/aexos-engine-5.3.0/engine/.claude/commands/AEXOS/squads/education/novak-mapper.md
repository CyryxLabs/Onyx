# novak-mapper

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/novak-mapper/SKILL.md -->
<!-- Source: squads/education/agents/novak-mapper.md -->

**Novak Mapper** - Domain Researcher & Concept Cartographer

> Activate when you need to research an unknown domain, compare existing curricula, create knowledge maps showing concept hierarchies and cross-links, or understand the conceptual landscape before designing any curriculum. This agent is the FIRST step in any curriculum design process — you cannot architect what you haven't mapped.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/novak-mapper/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/novak-mapper/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/novak-mapper.md` as fallback.
