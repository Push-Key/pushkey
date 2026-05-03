#!/usr/bin/env node
/**
 * Pushkey CLI shim — delegates to the downloaded binary or pip-installed CLI.
 * This file is replaced by the real binary during postinstall.
 */
const { spawnSync } = require('child_process');
const { join, dirname } = require('path');
const { existsSync } = require('fs');

const binDir = dirname(__filename);
const candidates = [
  join(binDir, 'pushkey.exe'),      // Windows binary
  join(binDir, 'pushkey'),          // Unix binary (replaced by postinstall)
];

// Try the downloaded binary first
for (const bin of candidates) {
  if (existsSync(bin) && bin !== __filename) {
    const result = spawnSync(bin, process.argv.slice(2), { stdio: 'inherit' });
    process.exit(result.status ?? 1);
  }
}

// Fall back to pip-installed CLI
const result = spawnSync('pushkey', process.argv.slice(2), { stdio: 'inherit', shell: true });
if (result.error) {
  console.error('[pushkey] Could not find pushkey. Try: pip install pushkey');
  process.exit(1);
}
process.exit(result.status ?? 1);
