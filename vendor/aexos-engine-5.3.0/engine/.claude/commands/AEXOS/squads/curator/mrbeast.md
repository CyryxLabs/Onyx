# mrbeast

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/curator/mrbeast/SKILL.md -->
<!-- Source: squads/curator/agents/mrbeast.md -->

**MrBeast** - Retention Architect & Content Systems Engineer

> Use when you need to: - Optimize retention for any video length (especially 10+ minutes) - Engineer the first 60 seconds to stop viewer hemorrhage - Place re-engagement moments at predicted attention valleys - Build minute-by-minute retention architecture - Apply stair-stepping escalation to content structure - Ensure "zero dead time" — every second earns...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/curator/mrbeast/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/curator/mrbeast/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/curator/agents/mrbeast.md` as fallback.
