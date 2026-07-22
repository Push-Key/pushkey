import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_browser_background_sanitizes_health_payloads():
    script = ROOT / "browser-pushkey" / "background.js"
    node_code = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(script))}, 'utf8');
const sandbox = {{
  chrome: {{
    action: {{ setBadgeText() {{}}, setBadgeBackgroundColor() {{}} }},
    storage: {{ local: {{ set: async () => {{}} }} }},
    runtime: {{ onMessage: {{ addListener() {{}} }}, onInstalled: {{ addListener() {{}} }}, onStartup: {{ addListener() {{}} }} }},
    alarms: {{ create() {{}}, onAlarm: {{ addListener() {{}} }} }},
  }},
  fetch: async () => ({{ ok: false }}),
  console,
}};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const input = {{
  SAFE_KEY: {{ status: 'critical', days_old: 4, provider: 'OpenAI', value: 'secret' }},
  BAD_STATUS: {{ status: 'owned', days_old: -1 }},
  TOO_LONG: {{ status: 'warning', days_old: 2 }},
}};
const cleaned = sandbox.sanitizeHealth(input);
if (cleaned.SAFE_KEY.value !== undefined) throw new Error('secret value leaked');
if (cleaned.SAFE_KEY.status !== 'critical') throw new Error('valid status lost');
if (cleaned.BAD_STATUS.status !== 'healthy') throw new Error('bad status not normalized');
if (cleaned.BAD_STATUS.days_old !== null) throw new Error('bad age not nulled');
if (!sandbox.sanitizeHealth(null) || Object.keys(sandbox.sanitizeHealth(null)).length) throw new Error('null should become empty object');
"""

    subprocess.run(["node", "-e", node_code], cwd=ROOT, check=True)


def test_browser_background_handles_missing_malformed_and_partial_sidecar_payloads():
    script = ROOT / "browser-pushkey" / "background.js"
    node_code = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(script))}, 'utf8');
let mode = 'missing';
const sandbox = {{
  chrome: {{
    action: {{ setBadgeText() {{}}, setBadgeBackgroundColor() {{}} }},
    storage: {{ local: {{ set: async () => {{}} }} }},
    runtime: {{ onMessage: {{ addListener() {{}} }}, onInstalled: {{ addListener() {{}} }}, onStartup: {{ addListener() {{}} }} }},
    alarms: {{ create() {{}}, onAlarm: {{ addListener() {{}} }} }},
  }},
  fetch: async () => {{
    if (mode === 'missing') return {{ ok: false }};
    if (mode === 'malformed') return {{ ok: true, json: async () => ['not', 'an', 'object'] }};
    if (mode === 'healthy') return {{
      ok: true,
      json: async () => ({{
        OPENAI_API_KEY: {{ status: 'healthy', days_old: 12, provider: 'OpenAI', category: 'AI' }},
        STRIPE_KEY: {{ status: 'warning', days_old: 93, provider: 'Stripe', category: 'Billing' }},
        ANTHROPIC_KEY: {{ status: 'critical', days_old: 180, provider: 'Anthropic', category: 'AI' }},
        PARTIAL_KEY: {{ provider: 'GitHub', category: 'DevTools' }},
      }}),
    }};
    throw new Error(`unexpected mode: ${{mode}}`);
  }},
  console,
}};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

(async () => {{
  const missing = await sandbox.fetchHealth();
  if (missing !== null) throw new Error('missing sidecar should return null');

  mode = 'malformed';
  const malformed = await sandbox.fetchHealth();
  if (Object.keys(malformed).length !== 0) throw new Error('malformed payload should sanitize to empty object');

  mode = 'healthy';
  const health = await sandbox.fetchHealth();
  if (health.OPENAI_API_KEY.status !== 'healthy') throw new Error('healthy status lost');
  if (health.STRIPE_KEY.status !== 'warning') throw new Error('warning status lost');
  if (health.ANTHROPIC_KEY.status !== 'critical') throw new Error('critical status lost');
  if (health.PARTIAL_KEY.status !== 'healthy') throw new Error('partial entry should default to healthy');
  if (health.PARTIAL_KEY.days_old !== null) throw new Error('partial entry should null missing age');
  if (health.PARTIAL_KEY.provider !== 'GitHub') throw new Error('provider should survive sanitization');
  const counts = sandbox.countByStatus(health);
  if (counts.healthy !== 2) throw new Error(`expected 2 healthy entries, got ${{counts.healthy}}`);
  if (counts.warning !== 1) throw new Error(`expected 1 warning entry, got ${{counts.warning}}`);
  if (counts.critical !== 1) throw new Error(`expected 1 critical entry, got ${{counts.critical}}`);
}})().catch((err) => {{
  console.error(err.stack || err.message);
  process.exit(1);
}});
"""

    subprocess.run(["node", "-e", node_code], cwd=ROOT, check=True)
