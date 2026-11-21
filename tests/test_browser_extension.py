import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "browser-pushkey"

# Loads background.js the way Chrome does: importScripts() pulls health-contract.js
# into the same global scope, and fetch()/chrome.* are stubbed.
_SANDBOX = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ext = __EXT__;
let respond = () => ({ ok: false });
const stored = [];
const badges = [];
const sandbox = {
  chrome: {
    action: {
      setBadgeText(value) { badges.push(value.text); },
      setBadgeBackgroundColor() {},
    },
    storage: { local: { set: async (value) => { stored.push(value); } } },
    runtime: {
      onMessage: { addListener() {} },
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      sendMessage: async () => {},
    },
    alarms: { create() {}, onAlarm: { addListener() {} } },
  },
  fetch: async () => respond(),
  TextEncoder,
  console,
};
sandbox.importScripts = (...files) => {
  for (const file of files) vm.runInContext(fs.readFileSync(path.join(ext, file), 'utf8'), sandbox);
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ext, 'background.js'), 'utf8'), sandbox);
const body = (text) => () => ({ ok: true, text: async () => text });
const json = (payload) => body(JSON.stringify(payload));
const nowStamp = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
function check(condition, message) { if (!condition) throw new Error(message); }
"""


def _run(script: str) -> None:
    code = _SANDBOX.replace("__EXT__", json.dumps(str(EXT))) + "\n(async () => {\n" + script + "\n})().catch((err) => { console.error(err.stack || err.message); process.exit(1); });\n"
    proc = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_browser_background_never_keeps_secret_values_and_normalizes_legacy_records():
    _run(r"""
respond = json({
  SAFE_KEY: { status: 'critical', days_old: 4, provider: 'OpenAI', value: 'sk-secret-value' },
  BAD_STATUS: { status: 'owned', days_old: -1 },
  PARTIAL_KEY: { provider: 'GitHub', category: 'DevTools' },
});
const result = await sandbox.fetchHealth();
check(result && result.state === 'available', 'legacy sidecar should be available');
check(result.schemaVersion === 0, 'legacy sidecar should report schema version 0');
check(!JSON.stringify(result).includes('sk-secret-value'), 'secret value leaked');
check(result.keys.SAFE_KEY.value === undefined, 'value field survived parsing');
check(result.keys.SAFE_KEY.status === 'critical', 'valid status lost');
check(result.keys.BAD_STATUS.status === 'unknown', 'invalid status should become unknown');
check(result.keys.BAD_STATUS.days_old === null, 'negative age should become null');
check(result.keys.PARTIAL_KEY.status === 'unknown', 'missing status should become unknown');
check(result.keys.PARTIAL_KEY.provider === 'GitHub', 'provider should survive normalization');
check(result.keys.PARTIAL_KEY.category === undefined, 'non-contract fields should be dropped');
""")


def test_browser_background_handles_missing_malformed_and_v1_sidecars():
    _run(r"""
respond = () => ({ ok: false });
check(await sandbox.fetchHealth() === null, 'missing sidecar should return null');

respond = body('not-json');
check(await sandbox.fetchHealth() === null, 'malformed JSON should return null');

respond = json(['not', 'an', 'object']);
check(await sandbox.fetchHealth() === null, 'non-object payload should return null');

respond = json({
  schema_version: 1,
  generated_at: nowStamp(),
  keys: { LEAKY_KEY: { status: 'healthy', days_old: 1, provider: 'OpenAI', value: 'sk-secret-value' } },
});
check(await sandbox.fetchHealth() === null, 'a v1 record carrying extra fields must be rejected');

respond = json({
  schema_version: 1,
  generated_at: nowStamp(),
  keys: {
    OPENAI_API_KEY: { status: 'healthy', days_old: 12, provider: 'OpenAI' },
    STRIPE_KEY: { status: 'warning', days_old: 93, provider: 'Stripe' },
    ANTHROPIC_KEY: { status: 'critical', days_old: 180, provider: null },
  },
});
const result = await sandbox.fetchHealth();
check(result && result.schemaVersion === 1, 'v1 sidecar should be available');
const counts = sandbox.PushkeyHealthContract.countByStatus(result.keys);
check(counts.healthy === 1 && counts.warning === 1 && counts.critical === 1, `unexpected counts ${JSON.stringify(counts)}`);
""")


def test_browser_badge_stores_only_parsed_keys_and_counts_critical():
    _run(r"""
respond = json({
  schema_version: 1,
  generated_at: nowStamp(),
  keys: {
    ANTHROPIC_KEY: { status: 'critical', days_old: 180, provider: 'Anthropic' },
    OPENAI_API_KEY: { status: 'healthy', days_old: 2, provider: 'OpenAI' },
  },
});
await sandbox.updateBadge();
const last = stored[stored.length - 1];
check(last.schemaVersion === 1, 'schema version not stored');
check(Object.keys(last.health).sort().join(',') === 'ANTHROPIC_KEY,OPENAI_API_KEY', 'stored keys differ');
check(badges[badges.length - 1] === '1', `badge should show 1 critical, got ${badges[badges.length - 1]}`);

respond = () => ({ ok: false });
await sandbox.updateBadge();
const cleared = stored[stored.length - 1];
check(cleared.health === null && cleared.counts === null, 'unavailable sidecar should clear stored health');
check(badges[badges.length - 1] === '!', 'unavailable sidecar should show the offline badge');
""")


def test_browser_health_contract_node_suite_passes():
    proc = subprocess.run(
        ["node", "--test", "browser-pushkey/test/health-contract.test.js"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
