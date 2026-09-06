#!/usr/bin/env node
/**
 * Normalizes the native AEXOS squad library to the framework task/workflow
 * contracts without discarding the richer operational material in each file.
 *
 * Re-runnable. Use --check in CI to detect drift without writing files.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const ROOT = path.resolve(__dirname, '..');
const CHECK = process.argv.includes('--check');

const SQUADS = {
  apex: 'apex-lead',
  brand: 'brand-chief',
  curator: 'curator-chief',
  'deep-research': 'dr-orchestrator',
  dispatch: 'dispatch-chief',
  education: 'education-chief',
  kaizen: 'kaizen-chief',
  'kaizen-v2': 'kaizen-v2-chief',
  'legal-analyst': 'legal-chief',
  seo: 'seo-chief',
  'squad-creator': 'squad-chief',
};

const ICON_CODES = {
  apex: 'AX',
  brand: 'BR',
  curator: 'CU',
  'deep-research': 'DR',
  dispatch: 'DI',
  education: 'ED',
  kaizen: 'KZ',
  'kaizen-v2': 'K2',
  'legal-analyst': 'LG',
  seo: 'SE',
  'squad-creator': 'SC',
};

const DELEGATION_NOTICE =
  'MANDATORY DELEGATION NOTICE: Announce every specialist hand-off using the target agent id, persona, and icon from its definition.';

function slug(value, fallback) {
  const normalized = String(value || fallback || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
  return normalized || fallback;
}

function listFiles(dir, extension) {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((name) => name.toLowerCase().endsWith(extension))
    .sort();
}

function orderedTaskMetadata(existing, file, owner) {
  const taskName = path.basename(file, '.md');
  const current = existing && typeof existing === 'object' && !Array.isArray(existing) ? existing : {};
  return {
    task: typeof current.task === 'string' ? current.task : taskName,
    owner: current.owner || `@${owner}`,
    owner_type: current.owner_type || 'agent',
    atomic_layer: current.atomic_layer || 'task',
    Input: current.Input || 'Use the inputs and prerequisites documented in this task.',
    Output: current.Output || 'Produce every deliverable documented in this task.',
    Checklist: current.Checklist || [
      '[ ] Execute every documented step.',
      '[ ] Validate every declared output.',
    ],
    ...Object.fromEntries(
      Object.entries(current).filter(
        ([key]) => !['task', 'owner', 'owner_type', 'atomic_layer', 'Input', 'Output', 'Checklist'].includes(key),
      ),
    ),
  };
}

function normalizeTask(content, file, owner) {
  const frontmatter = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
  const match = content.match(frontmatter);
  let metadata = {};
  let body = content.replace(/^\uFEFF/, '');

  if (match) {
    try {
      metadata = yaml.load(match[1]) || {};
      body = content.slice(match[0].length).replace(/^\uFEFF/, '');
    } catch {
      metadata = {};
    }
  }

  const header = yaml.dump(orderedTaskMetadata(metadata, file, owner), {
    lineWidth: 100,
    noRefs: true,
    sortKeys: false,
  });

  return `---\n${header}---\n\n${body.replace(/^\s+/, '')}`;
}

function phaseSources(document, workflow) {
  const candidates = [document.phases, workflow.phases, document.steps, document.agent_sequence];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length) {
      return candidate.map((phase, index) => ({
        key: phase && typeof phase === 'object' ? phase.id || phase.name : phase,
        value: phase,
        index,
      }));
    }
    if (candidate && typeof candidate === 'object') {
      return Object.entries(candidate).map(([key, value], index) => ({ key, value, index }));
    }
  }
  return [];
}

function canonicalSequence(document, workflow, workflowId, owner) {
  const phases = phaseSources(document, workflow);
  const source = phases.length ? phases : [{ key: workflowId, value: null, index: 0 }];
  const used = new Set();

  return source.map(({ key, value, index }) => {
    const label =
      (value && typeof value === 'object' && (value.name || value.title || value.id)) ||
      key ||
      `phase-${index + 1}`;
    let id = slug(key || label, `phase-${index + 1}`);
    while (used.has(id)) id = `${id}-${index + 1}`;
    used.add(id);
    return {
      id,
      agent: owner,
      action: `Execute ${String(label)} according to the detailed workflow definition.`,
    };
  });
}

function indentYaml(value, spaces) {
  const prefix = ' '.repeat(spaces);
  return yaml
    .dump(value, { lineWidth: 100, noRefs: true, sortKeys: false })
    .split('\n')
    .filter((line, index, lines) => !(index === lines.length - 1 && line === ''))
    .map((line) => `${prefix}${line}`)
    .join('\n');
}

function normalizeWorkflow(content, file, owner) {
  const document = yaml.load(content) || {};
  const existing = document.workflow && typeof document.workflow === 'object' ? document.workflow : {};
  const workflowId = slug(existing.id || document.id || document['workflow-id'] || path.basename(file, path.extname(file)));
  const workflowName =
    existing.name || document.name || document.display_name || document.title || workflowId;
  const additions = {};

  if (!existing.id) additions.id = workflowId;
  if (!existing.name) additions.name = workflowName;
  if (!existing.description) {
    additions.description = document.description || `Execute the ${workflowName} workflow.`;
  }
  if (!existing.type) additions.type = 'squad-workflow';
  if (!Array.isArray(existing.sequence) || existing.sequence.length === 0) {
    additions.sequence = canonicalSequence(document, existing, workflowId, owner);
  }

  if (Object.keys(existing).length > 0) {
    if (Object.keys(additions).length === 0) return content;
    const marker = /^(workflow:\s*(?:#.*)?\r?\n)/m;
    if (!marker.test(content)) {
      throw new Error(`Unable to locate workflow mapping in ${file}`);
    }
    return content.replace(marker, `$1${indentYaml(additions, 2)}\n`);
  }

  const canonical = {
    id: workflowId,
    name: workflowName,
    description: document.description || `Execute the ${workflowName} workflow.`,
    type: 'squad-workflow',
    sequence: canonicalSequence(document, existing, workflowId, owner),
  };
  const body = content.replace(/^\uFEFF?(?:---\r?\n)?/, '');
  return `workflow:\n${indentYaml(canonical, 2)}\n\n${body}`;
}

function normalizeAgentIcon(content, file, icon) {
  const block = /```yaml\r?\n([\s\S]*?)\r?\n```/;
  const match = content.match(block);
  if (!match) throw new Error(`Missing YAML agent definition in ${file}`);
  const lines = match[1].split(/\r?\n/);
  const agentLine = lines.findIndex((line) => line === 'agent:');
  if (agentLine === -1) throw new Error(`Unable to locate agent mapping in ${file}`);
  let end = lines.length;
  for (let index = agentLine + 1; index < lines.length; index++) {
    if (/^[A-Za-z0-9_.-]+:/.test(lines[index])) {
      end = index;
      break;
    }
  }
  const iconLine = lines.findIndex(
    (line, index) => index > agentLine && index < end && /^ {2}icon:/.test(line),
  );
  if (iconLine === -1) lines.splice(agentLine + 1, 0, `  icon: '${icon}'`);
  else lines[iconLine] = `  icon: '${icon}'`;
  const normalizedBlock = lines.join('\n');
  return content.replace(match[0], `\`\`\`yaml\n${normalizedBlock}\n\`\`\``);
}

function normalizeChief(content, file) {
  const block = /```yaml\r?\n([\s\S]*?)\r?\n```/;
  const match = content.match(block);
  if (!match) throw new Error(`Missing YAML agent definition in ${file}`);
  const accidentalNested =
    `agent:\n  persona:\n    core_principles:\n      - '${DELEGATION_NOTICE}'\n`;
  let normalizedBlock = match[1].replace(accidentalNested, 'agent:\n');
  const document = yaml.load(normalizedBlock) || {};
  if (!document.agent || typeof document.agent !== 'object') {
    throw new Error(`Missing agent mapping in ${file}`);
  }

  const principles = ((document.persona || {}).core_principles || []).map(String);
  if (principles.some((principle) => principle.includes('MANDATORY DELEGATION NOTICE'))) {
    return content.replace(match[0], `\`\`\`yaml\n${normalizedBlock}\n\`\`\``);
  }

  if (/^persona:\r?\n/m.test(normalizedBlock)) {
    if (document.persona && Array.isArray(document.persona.core_principles)) {
      normalizedBlock = normalizedBlock.replace(
        /^ {2}core_principles:\r?\n/m,
        `  core_principles:\n    - '${DELEGATION_NOTICE}'\n`,
      );
    } else {
      normalizedBlock = normalizedBlock.replace(
        /^persona:\r?\n/m,
        `persona:\n  core_principles:\n    - '${DELEGATION_NOTICE}'\n`,
      );
    }
  } else {
    normalizedBlock =
      `persona:\n  core_principles:\n    - '${DELEGATION_NOTICE}'\n` + normalizedBlock;
  }
  return content.replace(match[0], `\`\`\`yaml\n${normalizedBlock}\n\`\`\``);
}

const changed = [];
let taskCount = 0;
let workflowCount = 0;
let agentCount = 0;

for (const [squad, owner] of Object.entries(SQUADS)) {
  const squadDir = path.join(ROOT, 'squads', squad);
  if (!fs.existsSync(squadDir)) throw new Error(`Missing native AEXOS squad: ${squad}`);

  for (const name of listFiles(path.join(squadDir, 'tasks'), '.md')) {
    const file = path.join(squadDir, 'tasks', name);
    const current = fs.readFileSync(file, 'utf8');
    const output = normalizeTask(current, file, owner);
    taskCount++;
    if (output !== current) {
      changed.push(path.relative(ROOT, file));
      if (!CHECK) fs.writeFileSync(file, output);
    }
  }

  for (const name of listFiles(path.join(squadDir, 'workflows'), '.yaml')) {
    const file = path.join(squadDir, 'workflows', name);
    const current = fs.readFileSync(file, 'utf8');
    const output = normalizeWorkflow(current, file, owner);
    workflowCount++;
    if (output !== current) {
      changed.push(path.relative(ROOT, file));
      if (!CHECK) fs.writeFileSync(file, output);
    }
  }

  const agentNames = listFiles(path.join(squadDir, 'agents'), '.md');
  for (const [index, name] of agentNames.entries()) {
    const agentFile = path.join(squadDir, 'agents', name);
    const currentAgent = fs.readFileSync(agentFile, 'utf8');
    const icon = `◈${ICON_CODES[squad]}${String(index + 1).padStart(2, '0')}`;
    let normalizedAgent = normalizeAgentIcon(currentAgent, agentFile, icon);
    if (path.basename(name, '.md') === owner) {
      normalizedAgent = normalizeChief(normalizedAgent, agentFile);
    }
    agentCount++;
    if (normalizedAgent !== currentAgent) {
      changed.push(path.relative(ROOT, agentFile));
      if (!CHECK) fs.writeFileSync(agentFile, normalizedAgent);
    }
  }
}

console.log(
  `  tasks=${taskCount} workflows=${workflowCount} agents=${agentCount} changed=${changed.length}`,
);
if (CHECK && changed.length) {
  console.error(`\nAEXOS squad content is out of date:\n${changed.map((file) => `  - ${file}`).join('\n')}`);
  process.exit(1);
}
