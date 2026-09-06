/**
 * Resolve a Bash executable without accidentally selecting the Windows WSL
 * launcher when Git Bash is available.
 *
 * @module core/utils/shell-resolver
 */

'use strict';

const fs = require('fs');
const path = require('path');

/**
 * Resolve the Bash executable used by shell-backed AEXOS orchestration.
 *
 * @param {Object} [options] - Resolution overrides for tests and embedding.
 * @param {string} [options.platform] - Node platform identifier.
 * @param {NodeJS.ProcessEnv} [options.env] - Environment variables.
 * @param {(candidate: string) => boolean} [options.existsSync] - File probe.
 * @returns {string} Absolute Git Bash path on Windows when available, otherwise `bash`.
 */
function resolveBashExecutable(options = {}) {
  const platform = options.platform || process.platform;
  const env = options.env || process.env;
  const existsSync = options.existsSync || fs.existsSync;

  if (env.AEXOS_BASH_PATH) {
    return env.AEXOS_BASH_PATH;
  }

  if (platform !== 'win32') {
    return 'bash';
  }

  const candidates = [
    path.join(env.ProgramFiles || 'C:\\Program Files', 'Git', 'bin', 'bash.exe'),
    path.join(env.ProgramFiles || 'C:\\Program Files', 'Git', 'usr', 'bin', 'bash.exe'),
    env['ProgramFiles(x86)']
      ? path.join(env['ProgramFiles(x86)'], 'Git', 'bin', 'bash.exe')
      : null,
    env.LocalAppData
      ? path.join(env.LocalAppData, 'Programs', 'Git', 'bin', 'bash.exe')
      : null,
  ].filter(Boolean);

  return candidates.find((candidate) => existsSync(candidate)) || 'bash';
}

module.exports = { resolveBashExecutable };
