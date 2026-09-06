#!/usr/bin/env node

/**
 * Run the pinned Node 22 release toolchain without adding it to the AEXOS
 * Node 18-compatible dependency graph.
 *
 * @module scripts/run-semantic-release
 */

'use strict';

const { spawnSync } = require('child_process');

const RELEASE_PACKAGES = [
  'semantic-release@25.0.9',
  '@semantic-release/changelog@6.0.3',
  '@semantic-release/exec@7.1.0',
  '@semantic-release/git@10.0.1',
];

function main(argv = process.argv.slice(2)) {
  const allowFailureIndex = argv.indexOf('--allow-failure');
  const allowFailure = allowFailureIndex >= 0;
  if (allowFailure) {
    argv.splice(allowFailureIndex, 1);
  }

  const nodeMajor = Number(process.versions.node.split('.')[0]);
  if (nodeMajor < 22) {
    const message =
      'The isolated release toolchain requires Node.js 22.14 or newer; ' +
      'the AEXOS runtime remains compatible with Node.js 18+.';
    if (allowFailure) {
      console.warn(message);
      return 0;
    }
    console.error(message);
    return 1;
  }

  const npmExecPath = process.env.npm_execpath;
  const command = npmExecPath ? process.execPath : process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const prefixArgs = npmExecPath ? [npmExecPath] : [];
  const packageArgs = RELEASE_PACKAGES.flatMap((packageName) => ['--package', packageName]);
  const result = spawnSync(
    command,
    [...prefixArgs, 'exec', '--yes', ...packageArgs, '--', 'semantic-release', ...argv],
    { cwd: process.cwd(), env: process.env, stdio: 'inherit', windowsHide: true },
  );

  if (result.error) {
    console.error(`Unable to start semantic-release: ${result.error.message}`);
    return allowFailure ? 0 : 1;
  }

  const status = result.status ?? 1;
  if (status !== 0 && allowFailure) {
    console.warn('Release configuration check completed with an expected local-only failure.');
    return 0;
  }
  return status;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { main, RELEASE_PACKAGES };
