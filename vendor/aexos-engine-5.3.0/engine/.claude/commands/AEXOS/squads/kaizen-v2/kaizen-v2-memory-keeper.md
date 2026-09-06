# kaizen-v2-memory-keeper

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-memory-keeper/SKILL.md -->
<!-- Source: squads/kaizen-v2/agents/kaizen-v2-memory-keeper.md -->

**Kaizen V2 Memory Keeper** - Tier 0 Sensorial — Daily Intelligence Curator

> Use when you need to: - Capture daily intelligence (Stop hook flow) - Extract patterns from observations - Understand what the ecosystem has learned - Check pattern health and decay scores - Archive patterns that have faded - Inject briefings into sessions

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-memory-keeper/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/kaizen-v2/kaizen-v2-memory-keeper/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/kaizen-v2/agents/kaizen-v2-memory-keeper.md` as fallback.
