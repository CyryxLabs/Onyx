# content-miner-pro

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/curator/content-miner-pro/SKILL.md -->
<!-- Source: squads/curator/agents/content-miner-pro.md -->

**Content Miner Pro** - Advanced Content Mining & Moment Extraction

> Use when you need to: - Extract moments from transcripts with EXACT timestamps - Create {source-slug}/momentos.md for video editing - Identify hooks, insights, stories, quotes from content - Detect viral triggers (LACUNA, QUEBRA, PICO, CONTRAINTUITIVO, etc.) - Prepare content for narrative assembly - Process large transcripts (>2000 lines) via parallel su...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/curator/content-miner-pro/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/curator/content-miner-pro/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/curator/agents/content-miner-pro.md` as fallback.
