#!/usr/bin/env node
/**
 * Brings every squad manifest onto the canonical shape squad-creator generates
 * and squad-schema.json requires.
 *
 * AEXOS supports legacy nested manifests at runtime, while the current schema
 * requires `name` and `version` at the top level. This tool emits the current
 * canonical contract and keeps every richer extension block intact.
 *
 * The schema sets `additionalProperties: true`, so the richer blocks this
 * project added — tiers, handoffs, cross_cutting — stay exactly as they are.
 * This adds the required surface rather than replacing anything, and derives
 * `components` from what is actually on disk so it cannot drift.
 *
 * Re-runnable: run it again after task files land and components updates.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const CHECK = process.argv.includes('--check');
const yaml = require('js-yaml');

const AEXOS_MIN_VERSION = '2.1.0';
const AUTHOR = 'Cyryx Labs LLC';
const LICENSE = 'UNLICENSED';
const NATIVE_LIBRARY = new Set([
  'apex',
  'brand',
  'curator',
  'deep-research',
  'dispatch',
  'education',
  'kaizen',
  'kaizen-v2',
  'legal-analyst',
  'seo',
  'squad-creator',
]);

/** Canonical top-level key order, matching what squad-generator emits. */
const HEAD_ORDER = [
  'name',
  'version',
  'short-title',
  'description',
  'author',
  'license',
  'slashPrefix',
  'tags',
  'cyryx',
  'components',
  'config',
  'dependencies',
];

const COMPONENT_DIRS = {
  tasks: 'tasks',
  agents: 'agents',
  workflows: 'workflows',
  checklists: 'checklists',
  templates: 'templates',
  tools: 'tools',
  scripts: 'scripts',
};

/**
 * Bare filenames, not paths: _validateReferencedFiles joins the component's own
 * directory onto each entry, so a "tasks/foo.md" entry resolves to
 * "tasks/tasks/foo.md" and reports every file as missing.
 */
function listComponent(squadDir, dir) {
  const full = path.join(squadDir, dir);
  if (!fs.existsSync(full)) return [];
  return fs
    .readdirSync(full)
    .filter(
      (f) =>
        !f.startsWith('.') &&
        /\.(md|ya?ml|[cm]?js|ts|tsx|py|sh|json|html|css)$/.test(f),
    )
    .sort();
}

/** Trim to the schema's 500-char limit without cutting mid-word. */
function clamp(text, max) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  return `${flat.slice(0, max - 1).replace(/\s+\S*$/, '')}…`;
}

function kebabCase(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
}

function readAgentDefinition(file) {
  const content = fs.readFileSync(file, 'utf8');
  const match = content.match(/```yaml\r?\n([\s\S]*?)\r?\n```/);
  if (!match) return null;
  try {
    const parsed = yaml.load(match[1]) || {};
    return parsed.agent && typeof parsed.agent === 'object' ? parsed.agent : null;
  } catch {
    return null;
  }
}

function canonicalAgentRoster(squadDir, existing) {
  const agentsDir = path.join(squadDir, 'agents');
  if (!fs.existsSync(agentsDir)) return {};

  const prior = {};
  if (Array.isArray(existing)) {
    for (const agent of existing) {
      if (agent && agent.id) prior[agent.id] = agent;
    }
  } else if (existing && typeof existing === 'object') {
    Object.assign(prior, existing);
  }

  const roster = {};
  for (const file of listComponent(squadDir, 'agents').filter((name) => name.endsWith('.md'))) {
    const fallbackId = path.basename(file, '.md');
    const definition = readAgentDefinition(path.join(agentsDir, file)) || {};
    const id = definition.id || fallbackId;
    const previous = prior[id] && typeof prior[id] === 'object' ? prior[id] : {};
    roster[id] = {
      ...previous,
      file: `agents/${file}`,
      ...(definition.name ? { persona: definition.name } : {}),
      ...(definition.title ? { title: definition.title } : {}),
      ...(definition.icon ? { icon: definition.icon } : {}),
      ...(definition.based_on ? { based_on: definition.based_on } : {}),
    };
  }
  return roster;
}

const squadsDir = path.join(ROOT, 'squads');
const results = [];

for (const entry of fs.readdirSync(squadsDir, { withFileTypes: true })) {
  if (!entry.isDirectory() || entry.name === '_example') continue;
  const squadDir = path.join(squadsDir, entry.name);

  const legacy = path.join(squadDir, 'config.yaml');
  const canonical = path.join(squadDir, 'squad.yaml');
  const current = fs.existsSync(canonical) ? canonical : fs.existsSync(legacy) ? legacy : null;
  if (!current) continue;

  const doc = yaml.load(fs.readFileSync(current, 'utf8')) || {};
  const nested = doc.squad || {};

  // Required + descriptive surface, taken from the nested block where present
  // so nothing is invented here.
  doc.name = doc.name || nested.name || entry.name;
  doc.version = doc.version || nested.version || '1.0.0';
  doc['short-title'] = doc['short-title'] || clamp(nested.display_name || nested.domain || doc.name, 100);
  doc.description = clamp(doc.description || nested.description || nested.domain || '', 500);
  doc.author = AUTHOR;
  doc.license = LICENSE;
  doc.slashPrefix = kebabCase(doc.slashPrefix || String(doc.name).replace(/-squad$/, ''));
  doc.tags = doc.tags || nested.keywords || [];

  // Discovery intentionally reads the legacy nested routing block when one is
  // present. Keep that compatibility surface complete so every native squad is
  // routable even when its original manifest carried only descriptive fields.
  const routeMeta = doc.squad || doc.pack || doc;
  routeMeta.domain = routeMeta.domain || doc.domain || doc['short-title'] || doc.name;
  routeMeta.keywords =
    Array.isArray(routeMeta.keywords) && routeMeta.keywords.length
      ? routeMeta.keywords
      : Array.from(
        new Set(
          (doc.tags.length ? doc.tags : [doc.name, ...String(doc.name).split('-')]).filter(Boolean),
        ),
      );

  doc.cyryx = Object.assign({ minVersion: AEXOS_MIN_VERSION, type: 'squad' }, doc.cyryx || {});

  // Derived from disk every run — a components list that is maintained by hand
  // is a components list that goes stale.
  doc.components = {};
  for (const [key, dir] of Object.entries(COMPONENT_DIRS)) {
    doc.components[key] = listComponent(squadDir, dir);
  }

  if (
    NATIVE_LIBRARY.has(entry.name) ||
    !doc.agents ||
    Array.isArray(doc.agents) ||
    (typeof doc.agents === 'object' && Object.keys(doc.agents).length === 0)
  ) {
    doc.agents = canonicalAgentRoster(squadDir, doc.agents);
  }

  doc.config = Object.assign({ extends: 'extend' }, doc.config || {});
  doc.dependencies = Object.assign({ node: [], squads: [] }, doc.dependencies || {});
  doc.dependencies.squads = (doc.dependencies.squads || [])
    .map((dependency) => (typeof dependency === 'string' ? dependency : dependency && dependency.name))
    .filter(Boolean);

  // Emit head keys first, then everything this project added, in a stable order.
  const ordered = {};
  for (const key of HEAD_ORDER) if (key in doc) ordered[key] = doc[key];
  for (const key of Object.keys(doc)) if (!(key in ordered)) ordered[key] = doc[key];

  const header =
    '# ═══════════════════════════════════════════════════════════════════════════════\n' +
    `# AEXOS Squad Manifest — ${doc['short-title']}\n` +
    '# Conforms to .aexos-core/schemas/squad-schema.json (task-first architecture).\n' +
    '# components/ is derived from disk by scripts/normalize-squad-manifests.js.\n' +
    '# ═══════════════════════════════════════════════════════════════════════════════\n\n';

  const output = header + yaml.dump(ordered, { lineWidth: 100, noRefs: true });
  const existing = fs.existsSync(canonical) ? fs.readFileSync(canonical, 'utf8') : null;
  const stale = output !== existing || current === legacy;

  if (!CHECK) {
    fs.writeFileSync(canonical, output);
    if (current === legacy) fs.unlinkSync(legacy);
  }

  results.push({
    squad: entry.name,
    renamed: current === legacy,
    stale,
    tasks: doc.components.tasks.length,
    agents: doc.components.agents.length,
  });
}

for (const r of results) {
  console.log(
    `  ${r.squad.padEnd(20)} agents=${String(r.agents).padStart(2)} tasks=${String(r.tasks).padStart(2)}` +
      (r.renamed ? '  (config.yaml -> squad.yaml)' : '') +
      (CHECK && r.stale ? '  STALE' : ''),
  );
}

const stale = results.filter((r) => r.stale);
if (CHECK) {
  if (stale.length) {
    console.error(
      `\n${stale.length} manifest(s) out of date — an agent or task file was added, removed or ` +
        `renamed without regenerating: ${stale.map((r) => r.squad).join(', ')}\n` +
        'Run: node scripts/normalize-squad-manifests.js',
    );
    process.exit(1);
  }
  console.log(`  ${results.length} manifest(s) up to date.`);
} else {
  console.log(`  manifestos normalizados: ${results.length}`);
}
