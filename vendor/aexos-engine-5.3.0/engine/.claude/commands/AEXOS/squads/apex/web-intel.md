# web-intel

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/apex/web-intel/SKILL.md -->
<!-- Source: squads/apex/agents/web-intel.md -->

**Kilian** - Web Intelligence Engineer — Design Extraction Specialist

> Use when you need to extract design intelligence from external websites or apps: scraping design tokens (colors, typography, spacing, shadows), analyzing frontend patterns and component structures, curating images and visual assets from external sources, comparing external design systems with the current project, or discovering design inspiration from liv...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/apex/web-intel/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/apex/web-intel/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/apex/agents/web-intel.md` as fallback.
