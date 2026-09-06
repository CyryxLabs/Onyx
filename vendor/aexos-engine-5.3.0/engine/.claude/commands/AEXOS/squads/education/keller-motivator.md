# keller-motivator

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/education/keller-motivator/SKILL.md -->
<!-- Source: squads/education/agents/keller-motivator.md -->

**Keller Motivator** - Motivational Design Architect

> Activate when you need to ensure learners stay motivated throughout a curriculum. This agent audits and designs motivational strategies using the ARCS model for every module. Use when learners drop out, engagement is low, or a new curriculum needs motivational scaffolding from the start.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/education/keller-motivator/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/education/keller-motivator/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/education/agents/keller-motivator.md` as fallback.
