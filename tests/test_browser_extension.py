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
