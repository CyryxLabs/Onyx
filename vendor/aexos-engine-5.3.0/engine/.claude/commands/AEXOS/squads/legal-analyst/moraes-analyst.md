# moraes-analyst

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/legal-analyst/moraes-analyst/SKILL.md -->
<!-- Source: squads/legal-analyst/agents/moraes-analyst.md -->

**moraes-analyst** - Analisar questoes envolvendo direitos e garantias fundamentais (CF/88 Art. 5o), direitos sociais (Art. 6o-11), tratados internacionais de direitos humanos, e...

> Use this AEXOS agent when the task matches its responsibility.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/legal-analyst/moraes-analyst/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/legal-analyst/moraes-analyst/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/legal-analyst/agents/moraes-analyst.md` as fallback.
