#!/usr/bin/env node
/**
 * Pushkey postinstall — downloads the correct pre-built binary for this platform.
 * Binaries are published as GitHub Release assets on every tagged release.
 */

const { spawnSync } = require('child_process');
const { createHash } = require('crypto');
const { createWriteStream, chmodSync, existsSync, mkdirSync, readFileSync, unlinkSync } = require('fs');
const { join } = require('path');
const https = require('https');

const VERSION = require('../package.json').version;
const REPO = 'Push-Key/pushkey';
const BIN_DIR = join(__dirname, '..', 'bin');

const PLATFORM_MAP = {
  'win32-x64':   { suffix: 'windows-x64.exe', ext: '.exe' },
  'darwin-x64':  { suffix: 'macos-x64',       ext: '' },
  'linux-x64':   { suffix: 'linux-x64',       ext: '' },
  'darwin-arm64': null,
  'linux-arm64':  null,
};

function getTarget() {
  const key = `${process.platform}-${process.arch}`;
  const p = PLATFORM_MAP[key];
  if (!p) {
    console.error(`[pushkey] Unsupported platform or architecture: ${key}`);
    console.error('[pushkey] Alpha npm binaries support win32-x64, darwin-x64, and linux-x64.');
    console.error('[pushkey] On arm64 or unsupported systems, install via Python: pip install pushkey');
    process.exit(1);
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

async function verifyChecksum(dest, checksumUrl) {
  const checksumDest = `${dest}.sha256`;
  await download(checksumUrl, checksumDest);
  const expected = readFileSync(checksumDest, 'utf8').trim().split(/\s+/)[0].toLowerCase();
  const actual = createHash('sha256').update(readFileSync(dest)).digest('hex');
  unlinkSync(checksumDest);
  if (!expected || expected !== actual) {
    throw new Error(`sha256 mismatch for ${dest}`);
  }
}

async function main() {
  const target = getTarget();
  const binaryName = `pushkey-${target.suffix}`;
  const url = `https://github.com/${REPO}/releases/download/v${VERSION}/${binaryName}`;
  const checksumUrl = `${url}.sha256`;
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
    await verifyChecksum(dest, checksumUrl);
    if (process.platform !== 'win32') chmodSync(dest, '755');
    console.log(`[pushkey] ✓ Installed to ${dest}`);
  } catch (err) {
    console.warn(`[pushkey] Binary download failed: ${err.message}`);
    console.warn(`[pushkey] Falling back to pip install...`);
    const result = spawnSync('pip', ['install', `pushkey==${VERSION}`], { stdio: 'inherit' });
    if (result.status !== 0) {
      console.error('[pushkey] pip install also failed. Please install manually:');
      console.error('  pip install pushkey');
      process.exit(result.status || 1);
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
  process.exit(1);
});
