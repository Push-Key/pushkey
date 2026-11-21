#!/usr/bin/env node
/**
 * Pushkey CLI shim — delegates to the downloaded binary or pip-installed CLI.
 * This file is replaced by the real binary during postinstall.
 */
const { spawnSync } = require('child_process');
const { join, dirname } = require('path');
const { existsSync, realpathSync } = require('fs');

const binDir = dirname(__filename);
const currentScript = realpathSync(__filename);
const nodeBinary = realpathSync(process.execPath);
const candidates = [
  join(binDir, 'pushkey.exe'),      // Windows binary
  join(binDir, 'pushkey'),          // Unix binary (replaced by postinstall)
];

// Try the downloaded binary first
for (const bin of candidates) {
  if (existsSync(bin)) {
    const resolved = realpathSync(bin);
    if (resolved === currentScript || resolved === nodeBinary) continue;
    const result = spawnSync(bin, process.argv.slice(2), { stdio: 'inherit' });
    process.exit(result.status ?? 1);
  }
}

// Fall back to pip-installed CLI without resolving back to this npm shim.
for (const python of ['python', 'python3']) {
  const result = spawnSync(python, ['-m', 'pushkey_cli', ...process.argv.slice(2)], { stdio: 'inherit' });
  if (!result.error) {
    process.exit(result.status ?? 1);
  }
}
console.error('[pushkey] Could not find a Pushkey binary or Python package. Try: pip install pushkey');
process.exit(1);
