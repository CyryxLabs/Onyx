# perf-eng

<!-- ACORE-CLAUDE-AGENT-COMMAND: legacy-shim -->
<!-- Canonical Skill: .claude/skills/AEXOS/squads/apex/perf-eng/SKILL.md -->
<!-- Source: squads/apex/agents/perf-eng.md -->

**Addy** - Performance Engineer — Core Web Vitals

> Use when you need to: - Optimize Core Web Vitals (LCP, INP, CLS) to meet performance targets - Analyze and reduce JavaScript bundle size - Implement code splitting and lazy loading strategies - Optimize images (format selection, sizing, loading, decoding) - Design font loading strategies (preload, display, subsetting) - Set up performance budgets and moni...

## Compatibility Activation

This command is a legacy compatibility shim. The canonical Claude activation payload is:

`.claude/skills/AEXOS/squads/apex/perf-eng/SKILL.md`

When this command is invoked:

1. **If that skill is already loaded in this session, do not read it again** —
   its activation instructions are already available to you. Go straight to
   step 3. Re-reading a file you already hold costs the user a round-trip
   before the agent says anything.
2. Otherwise read `.claude/skills/AEXOS/squads/apex/perf-eng/SKILL.md` in full.
3. Follow the activation instructions from that skill, starting with the
   greeting. Announce the persona before doing any other work.
4. If the skill file is unavailable, read `squads/apex/agents/perf-eng.md` as fallback.
