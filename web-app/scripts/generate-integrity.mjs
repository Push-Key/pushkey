import { createHash } from "node:crypto";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.join(root, "out");
const pkg = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));

async function filesUnder(dir) {
  const result = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) result.push(...await filesUnder(absolute));
    else if (entry.name !== "pushkey-integrity.json") result.push(absolute);
  }
  return result;
}

const digest = (data, encoding = "hex") =>
  createHash("sha256").update(data).digest(encoding);
const cspDigest = (text) => digest(Buffer.from(text, "utf8"), "base64");
const files = {};
const scripts = new Set();
const styles = new Set();
const styleAttributes = new Set();

for (const absolute of (await filesUnder(out)).sort()) {
  const relative = path.relative(out, absolute).split(path.sep).join("/");
  const bytes = await readFile(absolute);
  files[relative] = digest(bytes);
  if (!relative.endsWith(".html")) continue;
  const html = bytes.toString("utf8");
  for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)) {
    if (match[1]) scripts.add(cspDigest(match[1]));
  }
  for (const match of html.matchAll(/<style(?:\s[^>]*)?>([\s\S]*?)<\/style>/gi)) {
    if (match[1]) styles.add(cspDigest(match[1]));
  }
  for (const match of html.matchAll(/\sstyle=(["'])(.*?)\1/gi)) {
    if (match[2]) styleAttributes.add(cspDigest(match[2]));
  }
}

const manifest = {
  schema: 1,
  web_app_version: pkg.version,
  files,
  csp: {
    scripts: [...scripts].sort(),
    styles: [...styles].sort(),
    style_attributes: [...styleAttributes].sort(),
  },
};
const manifestBytes = `${JSON.stringify(manifest, null, 2)}\n`;
await writeFile(path.join(out, "pushkey-integrity.json"), manifestBytes, {
  encoding: "utf8", mode: 0o444,
});
const packagedOut = path.resolve(root, "..", "pushkey_web", "out");
await rm(packagedOut, { recursive: true, force: true });
await mkdir(path.dirname(packagedOut), { recursive: true });
await cp(out, packagedOut, { recursive: true });
await writeFile(
  path.resolve(root, "..", "pushkey_web", "_manifest.py"),
  `"""Generated web artifact trust anchor. Do not edit."""\n` +
  `EXPECTED_MANIFEST_SHA256 = "${digest(Buffer.from(manifestBytes, "utf8"))}"\n` +
  `WEB_APP_VERSION = ${JSON.stringify(pkg.version)}\n`,
  "utf8",
);
console.log(`Integrity manifest: ${Object.keys(files).length} assets`);
