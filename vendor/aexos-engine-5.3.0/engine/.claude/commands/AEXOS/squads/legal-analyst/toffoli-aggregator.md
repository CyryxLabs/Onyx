# toffoli-aggregator

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/legal-analyst/toffoli-aggregator/SKILL.md -->
<!-- Source: squads/legal-analyst/agents/toffoli-aggregator.md -->

**toffoli-aggregator** - Consolidar precedentes judiciais dispersos em um mapa coerente. Especialista em mecanismos de uniformizacao: IRDR (Incidente de Resolucao de Demandas Repetit...

> Use this AEXOS agent when the task matches its responsibility.

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/legal-analyst/toffoli-aggregator/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/legal-analyst/toffoli-aggregator/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/legal-analyst/agents/toffoli-aggregator.md` as fallback.
