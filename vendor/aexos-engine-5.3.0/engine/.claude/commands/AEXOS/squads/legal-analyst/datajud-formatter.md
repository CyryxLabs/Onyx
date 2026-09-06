# datajud-formatter

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/legal-analyst/datajud-formatter/SKILL.md -->
<!-- Source: squads/legal-analyst/agents/datajud-formatter.md -->

**datajud-formatter** - Formatador de dados judiciais. Estrutura toda a saida conforme o schema DATAJUD do CNJ (Res. 331/2020) e organiza a apresentacao com navegabilidade inspirada...

> Use this AEXOS agent when the task matches its responsibility.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/legal-analyst/datajud-formatter/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/legal-analyst/datajud-formatter/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/legal-analyst/agents/datajud-formatter.md` as fallback.
