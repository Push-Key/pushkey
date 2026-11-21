import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-pushkey"


def _node(code: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["node", "-e", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc


def test_vscode_health_watcher_reattaches_after_close_and_error():
    # fs.FSWatcher is an EventEmitter whose close() emits 'close'; the watcher must
    # reattach after an OS-initiated close or error, but never after its own close.
    _node(r"""
const EventEmitter = require('events');
const { HealthWatcher } = require(__CONTRACT__);
let watchCount = 0;
const watchers = [];
const timers = [];
const fakeFs = {
  watch() {
    watchCount += 1;
    const watcher = new EventEmitter();
    watcher.closed = false;
    watcher.close = () => { watcher.closed = true; watcher.emit('close'); };
    watchers.push(watcher);
    return watcher;
  },
};
const watcher = new HealthWatcher({
  healthFile: 'C:/tmp/user/.pushkey/health.json',
  fsModule: fakeFs,
  read: () => ({ state: 'available', schemaVersion: 1, keys: {} }),
  onUpdate() {},
  setTimeoutFn: (fn) => { timers.push(fn); return timers.length; },
  clearTimeoutFn: () => {},
});
function check(condition, message) { if (!condition) throw new Error(message); }
watcher.start();
check(watchCount === 1, `expected first watcher, got ${watchCount}`);
watchers[0].emit('close');
check(timers.length === 1, 'close did not schedule reattach');
timers.shift()();
check(watchCount === 2, `close did not reattach, got ${watchCount}`);
watchers[1].emit('error', new Error('watch failed'));
check(watchers[1].closed, 'error did not close the failed watcher');
check(timers.length === 1, `error should schedule exactly one reattach, got ${timers.length}`);
timers.shift()();
check(watchCount === 3, `error did not reattach, got ${watchCount}`);
watcher.dispose();
check(watchers[2].closed, 'dispose did not close the watcher');
check(timers.length === 0, 'dispose must not schedule a reattach');
""".replace("__CONTRACT__", json.dumps(str(EXT / "health-contract.js"))))


def test_vscode_health_loader_handles_missing_malformed_partial_and_v1_sidecars(tmp_path):
    pushkey_dir = tmp_path / ".pushkey"
    pushkey_dir.mkdir()
    code = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ext = __EXT__;
const home = __HOME__;
const healthFile = path.join(home, '.pushkey', 'health.json');
const nowStamp = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
const payloads = {
  legacy: JSON.stringify({
    OPENAI_API_KEY: { status: 'healthy', provider: 'OpenAI', category: 'AI' },
    STRIPE_KEY: { status: 'warning', days_old: 93, provider: 'Stripe', category: 'Billing' },
    ANTHROPIC_KEY: { status: 'critical', days_old: 180, provider: 'Anthropic', category: 'AI' },
  }),
  malformed: 'not-json',
  partial: JSON.stringify({ PARTIAL_KEY: { provider: 'GitHub', category: 'DevTools' } }),
};
class MarkdownString {
  constructor() { this.value = ''; }
  appendMarkdown(text) { this.value += text; return this; }
  appendText(text) { this.value += text; return this; }
  appendCodeblock(text) { this.value += text; return this; }
}
const vscode = {
  window: {
    visibleTextEditors: [],
    createTextEditorDecorationType: (opts) => ({ kind: path.basename(opts.gutterIconPath), dispose() {} }),
    onDidChangeActiveTextEditor: () => ({ dispose() {} }),
    showInformationMessage: () => {},
  },
  workspace: { onDidSaveTextDocument: () => ({ dispose() {} }) },
  commands: { registerCommand: () => ({ dispose() {} }) },
  Range: class {},
  MarkdownString,
};
const sandbox = {
  require(name) {
    if (name === 'vscode') return vscode;
    if (name === 'os') return { homedir: () => home };
    if (name === './health-contract') return require(path.join(ext, 'health-contract.js'));
    return require(name);
  },
  module: { exports: {} },
  exports: {},
  __dirname: ext,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ext, 'extension.js'), 'utf8'), sandbox);
const snapshots = {};
let activeLabel = null;
const lines = ['OPENAI_API_KEY=value', 'STRIPE_KEY=value', 'ANTHROPIC_KEY=value', 'PARTIAL_KEY=value'];
const editor = {
  document: { fileName: path.join(home, '.env'), lineCount: lines.length, lineAt: (i) => ({ text: lines[i] }) },
  setDecorations(decoration, ranges) { snapshots[activeLabel][decoration.kind] = ranges.length; },
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 800));
async function capture(label, contents) {
  if (contents === null) fs.rmSync(healthFile, { force: true });
  else fs.writeFileSync(healthFile, contents);
  sandbox.refreshAll();
  await settle();
  activeLabel = label;
  snapshots[label] = { 'healthy.svg': 0, 'warning.svg': 0, 'critical.svg': 0 };
  sandbox.applyDecorations(editor);
}
(async () => {
  fs.writeFileSync(healthFile, payloads.legacy);
  sandbox.activate({ subscriptions: [] });
  await capture('legacy', payloads.legacy);
  await capture('missing', null);
  await capture('malformed', payloads.malformed);
  await capture('partial', payloads.partial);
  await capture('v1', JSON.stringify({
    schema_version: 1,
    generated_at: nowStamp(),
    keys: {
      OPENAI_API_KEY: { status: 'healthy', days_old: 2, provider: 'OpenAI' },
      ANTHROPIC_KEY: { status: 'critical', days_old: 180, provider: null },
    },
  }));
  sandbox.deactivate();
  process.stdout.write(JSON.stringify(snapshots));
})().catch((err) => { console.error(err.stack || err.message); process.exit(1); });
"""
    code = code.replace("__EXT__", json.dumps(str(EXT))).replace("__HOME__", json.dumps(str(tmp_path)))
    snapshots = json.loads(_node(code).stdout)

    assert snapshots["legacy"] == {"healthy.svg": 1, "warning.svg": 1, "critical.svg": 1}
    assert snapshots["missing"] == {"healthy.svg": 0, "warning.svg": 0, "critical.svg": 0}
    assert snapshots["malformed"] == {"healthy.svg": 0, "warning.svg": 0, "critical.svg": 0}
    # A legacy record with no status normalizes to `unknown`, which has no gutter icon.
    assert snapshots["partial"] == {"healthy.svg": 0, "warning.svg": 0, "critical.svg": 0}
    assert snapshots["v1"] == {"healthy.svg": 1, "warning.svg": 0, "critical.svg": 1}


def test_vscode_health_contract_node_suite_passes():
    proc = subprocess.run(
        ["node", "--test", "test/health-contract.test.js"], cwd=EXT, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
