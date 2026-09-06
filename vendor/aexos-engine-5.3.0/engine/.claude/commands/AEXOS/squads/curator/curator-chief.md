# curator-chief

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/curator/curator-chief/SKILL.md -->
<!-- Source: squads/curator/agents/curator-chief.md -->

**Curator Chief** - Content Curation Orchestrator

> Use when you need to: - Transform raw video/transcript into structured cut scripts - Mine content for high-impact moments - Create roteiros de corte with EXACT timestamps - Enrich content with real news/trends/data - Coordinate the full curation pipeline I am the orchestrator of the Curator Squad. I route requests to the right specialist and ensure the ou...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/curator/curator-chief/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/curator/curator-chief/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/curator/agents/curator-chief.md` as fallback.
