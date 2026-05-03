#!/usr/bin/env node
/**
 * Pushkey postinstall — downloads the correct pre-built binary for this platform.
 * Binaries are published as GitHub Release assets on every tagged release.
 */

const { execSync, spawnSync } = require('child_process');
const { createWriteStream, chmodSync, existsSync, mkdirSync } = require('fs');
const { join } = require('path');
const https = require('https');

const VERSION = require('../package.json').version;
const REPO = 'Push-Key/pushkey';
const BIN_DIR = join(__dirname, '..', 'bin');

const PLATFORM_MAP = {
  win32:  { suffix: 'windows-x64.exe', ext: '.exe' },
  darwin: { suffix: 'macos-x64',       ext: '' },
  linux:  { suffix: 'linux-x64',       ext: '' },
};

function getTarget() {
  const p = PLATFORM_MAP[process.platform];
  if (!p) {
    console.error(`[pushkey] Unsupported platform: ${process.platform}`);
    console.error(`[pushkey] Install via pip instead: pip install pushkey`);
    process.exit(0); // non-fatal — pip fallback
  }
  return p;
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = createWriteStream(dest);
    const get = (u) => https.get(u, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        return get(res.headers.location); // follow redirect
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', reject);
    get(url);
  });
}

async function main() {
  const target = getTarget();
  const binaryName = `pushkey-${target.suffix}`;
  const url = `https://github.com/${REPO}/releases/download/v${VERSION}/${binaryName}`;
  const dest = join(BIN_DIR, `pushkey${target.ext}`);

  if (!existsSync(BIN_DIR)) mkdirSync(BIN_DIR, { recursive: true });

  // Check if Python + pip fallback is preferred
  const hasPip = spawnSync('pip', ['show', 'pushkey'], { stdio: 'pipe' }).status === 0;
  if (hasPip) {
    console.log('[pushkey] Already installed via pip — skipping binary download.');
    writePipShim(dest, target.ext);
    return;
  }

  console.log(`[pushkey] Downloading binary for ${process.platform}...`);
  console.log(`[pushkey] Source: ${url}`);

  try {
    await download(url, dest);
    if (process.platform !== 'win32') chmodSync(dest, '755');
    console.log(`[pushkey] ✓ Installed to ${dest}`);
  } catch (err) {
    console.warn(`[pushkey] Binary download failed: ${err.message}`);
    console.warn(`[pushkey] Falling back to pip install...`);
    const result = spawnSync('pip', ['install', `pushkey==${VERSION}`], { stdio: 'inherit' });
    if (result.status !== 0) {
      console.error('[pushkey] pip install also failed. Please install manually:');
      console.error('  pip install pushkey');
    } else {
      writePipShim(dest, target.ext);
    }
  }
}

function writePipShim(dest, ext) {
  const { writeFileSync } = require('fs');
  if (ext === '.exe') {
    // On Windows, write a .cmd shim
    const cmd = join(require('path').dirname(dest), 'pushkey.cmd');
    writeFileSync(cmd, '@pushkey %*\r\n');
  } else {
    writeFileSync(dest, '#!/bin/sh\nexec pushkey "$@"\n');
    chmodSync(dest, '755');
  }
}

main().catch((err) => {
  console.error('[pushkey] Install error:', err.message);
  process.exit(0); // never block npm install
});
