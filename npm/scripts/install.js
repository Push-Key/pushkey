#!/usr/bin/env node
/**
 * Pushkey postinstall - downloads the correct pre-built binary for this platform.
 * Binaries are published as GitHub Release assets on every tagged release.
 */

const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const https = require('https');

const VERSION = require('../package.json').version;
const REPO = 'Push-Key/pushkey';
const BIN_DIR = path.join(__dirname, '..', 'bin');
const RELEASE_PUBLIC_KEY_PATH = path.join(__dirname, '..', 'release-public-key.pem');

const PLATFORM_MAP = {
  'win32-x64': { asset: 'pushkey-windows-x64.exe', ext: '.exe' },
  'darwin-x64': { asset: 'pushkey-macos-x64', ext: '' },
  'linux-x64': { asset: 'pushkey-linux-x64', ext: '' },
  'darwin-arm64': null,
  'linux-arm64': null,
};

const DEFAULT_IO = {
  spawnSync: childProcess.spawnSync,
  createHash: crypto.createHash,
  createWriteStream: fs.createWriteStream,
  chmodSync: fs.chmodSync,
  existsSync: fs.existsSync,
  mkdirSync: fs.mkdirSync,
  readFileSync: fs.readFileSync,
  renameSync: fs.renameSync,
  unlinkSync: fs.unlinkSync,
  writeFileSync: fs.writeFileSync,
  https,
  join: path.join,
  dirname: path.dirname,
  console,
};

function integrityError(message) {
  const err = new Error(message);
  err.code = 'EINTEGRITY';
  return err;
}

function getTarget(io = DEFAULT_IO, platform = process.platform, arch = process.arch) {
  const key = `${platform}-${arch}`;
  const target = PLATFORM_MAP[key];
  if (!target) {
    io.console.error(`[pushkey] Unsupported platform or architecture: ${key}`);
    io.console.error('[pushkey] Alpha npm binaries support win32-x64, darwin-x64, and linux-x64.');
    io.console.error('[pushkey] On arm64 or unsupported systems, install via Python: pip install pushkey');
    throw new Error(`unsupported platform or architecture: ${key}`);
  }
  return target;
}

function download(url, dest, io = DEFAULT_IO) {
  return new Promise((resolve, reject) => {
    const file = io.createWriteStream(dest);
    let settled = false;

    const finish = (err) => {
      if (settled) return;
      settled = true;
      if (err) {
        try {
          file.destroy();
        } catch {}
        reject(err);
      } else {
        resolve();
      }
    };

    const get = (currentUrl) => io.https.get(currentUrl, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        const nextUrl = res.headers.location;
        if (!nextUrl) {
          finish(new Error(`HTTP ${res.statusCode} for ${currentUrl}`));
          return;
        }
        res.resume();
        get(nextUrl);
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        finish(new Error(`HTTP ${res.statusCode} for ${currentUrl}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => {
        try {
          file.close(() => finish());
        } catch (err) {
          finish(err);
        }
      });
      file.on('error', finish);
      res.on('error', finish);
    }).on('error', finish);

    get(url);
  });
}

function parseChecksum(checksumText) {
  const expected = checksumText.trim().split(/\s+/)[0].toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(expected)) {
    throw integrityError('invalid sha256 checksum file');
  }
  return expected;
}

function parseSignature(signatureText) {
  const normalized = signatureText.trim().replace(/\s+/g, '');
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(normalized) || normalized.length % 4 === 1) {
    throw integrityError('invalid ed25519 signature file');
  }

  return Buffer.from(normalized, 'base64');
}

const REPLACEABLE_RENAME_CODES = new Set(['EEXIST', 'EPERM', 'EBUSY']);

function removeIfExists(dest, io = DEFAULT_IO) {
  if (io.existsSync(dest)) {
    try {
      io.unlinkSync(dest);
    } catch {}
  }
}

function promoteDownload(stagedDest, dest, io = DEFAULT_IO) {
  try {
    io.renameSync(stagedDest, dest);
    return;
  } catch (err) {
    if (!io.existsSync(dest) || !REPLACEABLE_RENAME_CODES.has(err && err.code)) {
      throw err;
    }
  }

  io.unlinkSync(dest);
  io.renameSync(stagedDest, dest);
}

async function verifyChecksum(dest, checksumUrl, io = DEFAULT_IO) {
  const checksumDest = `${dest}.sha256`;
  const downloadFn = io.download || download;

  try {
    await downloadFn(checksumUrl, checksumDest, io);
    const expected = parseChecksum(io.readFileSync(checksumDest, 'utf8'));
    const actual = io.createHash('sha256').update(io.readFileSync(dest)).digest('hex');
    if (expected !== actual) {
      throw integrityError(`sha256 mismatch for ${dest}`);
    }
  } catch (err) {
    if (err && err.code === 'EINTEGRITY') {
      throw err;
    }
    throw integrityError(`unable to verify checksum for ${dest}: ${err.message}`);
  } finally {
    if (io.existsSync(checksumDest)) {
      try {
        io.unlinkSync(checksumDest);
      } catch {}
    }
  }
}

function isMissingSignatureAsset(err) {
  return Boolean(err && typeof err.message === 'string' && err.message.includes('HTTP 404'));
}

async function verifySignature(dest, signatureUrl, publicKeyPath, io = DEFAULT_IO) {
  const signatureDest = `${dest}.sig`;
  const downloadFn = io.download || download;

  if (!io.existsSync(publicKeyPath)) {
    io.console.warn(`[pushkey] Release public key not found at ${publicKeyPath} - skipping signature verification.`);
    return false;
  }

  try {
    await downloadFn(signatureUrl, signatureDest, io);
  } catch (err) {
    if (isMissingSignatureAsset(err)) {
      io.console.warn(`[pushkey] Signature asset missing for ${dest} - continuing without signature verification.`);
      return false;
    }
    throw integrityError(`unable to verify signature for ${dest}: ${err.message}`);
  }

  try {
    const signature = parseSignature(io.readFileSync(signatureDest, 'utf8'));
    const publicKey = io.readFileSync(publicKeyPath, 'utf8');
    const verified = crypto.verify(null, io.readFileSync(dest), publicKey, signature);
    if (!verified) {
      throw integrityError(`signature mismatch for ${dest}`);
    }
    return true;
  } catch (err) {
    if (err && err.code === 'EINTEGRITY') {
      throw err;
    }
    throw integrityError(`unable to verify signature for ${dest}: ${err.message}`);
  } finally {
    if (io.existsSync(signatureDest)) {
      try {
        io.unlinkSync(signatureDest);
      } catch {}
    }
  }
}

function writePipShim(dest, ext, io = DEFAULT_IO) {
  if (ext === '.exe') {
    const cmd = io.join(io.dirname(dest), 'pushkey.cmd');
    io.writeFileSync(cmd, '@pushkey %*\r\n');
    return;
  }

  io.writeFileSync(dest, '#!/bin/sh\nexec pushkey "$@"\n');
  io.chmodSync(dest, '755');
}

function installViaPip(dest, target, io = DEFAULT_IO) {
  const writePipShimFn = io.writePipShim || writePipShim;
  const result = io.spawnSync('pip', ['install', `pushkey==${VERSION}`], { stdio: 'inherit' });
  if (result.status !== 0) {
    throw new Error('pip install also failed. Please install manually: pip install pushkey');
  }
  writePipShimFn(dest, target.ext, io);
}

async function main(io = DEFAULT_IO, platform = process.platform, arch = process.arch) {
  const target = getTarget(io, platform, arch);
  const url = `https://github.com/${REPO}/releases/download/v${VERSION}/${target.asset}`;
  const checksumUrl = `${url}.sha256`;
  const signatureUrl = `${url}.sig`;
  const dest = path.join(BIN_DIR, `pushkey${target.ext}`);
  const stagedDest = `${dest}.download`;
  const downloadFn = io.download || download;
  const publicKeyPath = io.releasePublicKeyPath || RELEASE_PUBLIC_KEY_PATH;
  const verifySignatureFn = io.verifySignature || verifySignature;
  const verifyChecksumFn = io.verifyChecksum || verifyChecksum;
  const installViaPipFn = io.installViaPip || installViaPip;
  const writePipShimFn = io.writePipShim || writePipShim;

  if (!io.existsSync(BIN_DIR)) {
    io.mkdirSync(BIN_DIR, { recursive: true });
  }

  const hasPip = io.spawnSync('pip', ['show', 'pushkey'], { stdio: 'pipe' }).status === 0;
  if (hasPip) {
    io.console.log('[pushkey] Already installed via pip - skipping binary download.');
    writePipShimFn(dest, target.ext, io);
    return;
  }

  io.console.log(`[pushkey] Downloading binary for ${platform}...`);
  io.console.log(`[pushkey] Source: ${url}`);

  try {
    await downloadFn(url, stagedDest, io);
  } catch (err) {
    removeIfExists(stagedDest, io);
    io.console.warn(`[pushkey] Binary download failed: ${err.message}`);
    io.console.warn('[pushkey] Falling back to pip install...');
    installViaPipFn(dest, target, io);
    return;
  }

  try {
    const signatureVerified = await verifySignatureFn(stagedDest, signatureUrl, publicKeyPath, io);
    if (signatureVerified) {
      io.console.log('[pushkey] Signature verified.');
    }
    await verifyChecksumFn(stagedDest, checksumUrl, io);
  } catch (err) {
    removeIfExists(stagedDest, io);
    io.console.error(`[pushkey] Checksum verification failed: ${err.message}`);
    throw err;
  }

  promoteDownload(stagedDest, dest, io);

  if (platform !== 'win32') {
    io.chmodSync(dest, '755');
  }
  io.console.log(`[pushkey] Installed to ${dest}`);
}

module.exports = {
  DEFAULT_IO,
  download,
  getTarget,
  installViaPip,
  integrityError,
  main,
  parseChecksum,
  promoteDownload,
  removeIfExists,
  verifyChecksum,
  verifySignature,
  writePipShim,
};

if (require.main === module) {
  main().catch((err) => {
    console.error('[pushkey] Install error:', err.message);
    process.exit(1);
  });
}
