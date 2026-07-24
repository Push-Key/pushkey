import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vscode_health_watcher_reattaches_after_close_and_error():
    script = ROOT / "vscode-pushkey" / "extension.js"
    node_code = f"""
const fs = require('fs');
const vm = require('vm');
const EventEmitter = require('events');
const code = fs.readFileSync({json.dumps(str(script))}, 'utf8');
let watchCount = 0;
let timers = [];
let watchers = [];
function makeWatcher() {{
  const watcher = new EventEmitter();
  watcher.close = () => watcher.emit('close');
  watchers.push(watcher);
  return watcher;
}}
const sandbox = {{
  require(name) {{
    if (name === 'vscode') {{
      return {{
        window: {{
          visibleTextEditors: [],
          createTextEditorDecorationType: () => ({{ dispose() {{}} }}),
        }},
        workspace: {{ onDidSaveTextDocument: () => ({{ dispose() {{}} }}) }},
        commands: {{ registerCommand: () => ({{ dispose() {{}} }}) }},
        Range: class {{}},
        MarkdownString: class {{ constructor(value) {{ this.value = value; }} }},
      }};
    }}
    if (name === 'fs') {{
      return {{
        existsSync: () => true,
        readFileSync: () => '{{}}',
        watch: () => {{
          watchCount += 1;
          return makeWatcher();
        }},
      }};
    }}
    if (name === 'os') return {{ homedir: () => 'C:/tmp/user' }};
    return require(name);
  }},
  module: {{ exports: {{}} }},
  exports: {{}},
  __dirname: {json.dumps(str(script.parent))},
  setTimeout(fn) {{
    timers.push(fn);
    return {{ unref() {{}} }};
  }},
  clearTimeout() {{}},
}};
sandbox.global = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const internals = sandbox.module.exports._internals;
internals.watchHealthFile();
if (watchCount !== 1) throw new Error(`expected first watcher, got ${{watchCount}}`);
watchers[0].emit('close');
if (timers.length !== 1) throw new Error('close did not schedule reattach');
timers.shift()();
if (watchCount !== 2) throw new Error(`close did not reattach, got ${{watchCount}}`);
watchers[1].emit('error', new Error('watch failed'));
if (timers.length < 1) throw new Error('error did not schedule reattach');
timers.shift()();
if (watchCount !== 3) throw new Error(`error did not reattach, got ${{watchCount}}`);
"""

    subprocess.run(["node", "-e", node_code], cwd=ROOT, check=True)


def test_vscode_health_loader_handles_missing_malformed_and_partial_sidecar_data():
    script = ROOT / "vscode-pushkey" / "extension.js"
    node_code = f"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const code = fs.readFileSync({json.dumps(str(script))}, 'utf8');
let mode = 'healthy';
const payloads = {{
  healthy: {{
    OPENAI_API_KEY: {{ status: 'healthy', provider: 'OpenAI', category: 'AI' }},
    STRIPE_KEY: {{ status: 'warning', days_old: 93, provider: 'Stripe', category: 'Billing' }},
    ANTHROPIC_KEY: {{ status: 'critical', days_old: 180, provider: 'Anthropic', category: 'AI' }},
  }},
  partial: {{
    PARTIAL_KEY: {{ provider: 'GitHub', category: 'DevTools' }},
  }},
}};
const snapshots = {{}};
let activeLabel = null;
const sandbox = {{
  require(name) {{
    if (name === 'vscode') {{
      return {{
        window: {{
          visibleTextEditors: [],
          createTextEditorDecorationType: (opts) => ({{
            kind: path.basename(opts.gutterIconPath),
            dispose() {{}},
          }}),
          onDidChangeActiveTextEditor: () => ({{ dispose() {{}} }}),
          showInformationMessage: () => {{}},
        }},
        workspace: {{ onDidSaveTextDocument: () => ({{ dispose() {{}} }}) }},
        commands: {{ registerCommand: () => ({{ dispose() {{}} }}) }},
        Range: class {{}},
        MarkdownString: class {{ constructor(value) {{ this.value = value; }} }},
      }};
    }}
    if (name === 'fs') {{
      return {{
        existsSync: () => mode !== 'missing',
        readFileSync: () => {{
          if (mode === 'malformed') return 'not-json';
          return JSON.stringify(payloads[mode] ?? payloads.healthy);
        }},
        watch: () => ({{ close() {{}}, on() {{}} }}),
      }};
    }}
    if (name === 'os') return {{ homedir: () => 'C:/tmp/user' }};
    return require(name);
  }},
  module: {{ exports: {{}} }},
  exports: {{}},
  __dirname: {json.dumps(str(script.parent))},
  setTimeout(fn) {{
    return {{ unref() {{}} }};
  }},
  clearTimeout() {{}},
}};
sandbox.global = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
sandbox.activate({{ subscriptions: [] }});

const editor = {{
  document: {{
    fileName: 'C:/tmp/user/.env',
    lineCount: 4,
    lineAt(index) {{
      return {{ text: [
        'OPENAI_API_KEY=value',
        'STRIPE_KEY=value',
        'ANTHROPIC_KEY=value',
        'PARTIAL_KEY=value',
      ][index] }};
    }},
  }},
  setDecorations(decoration, ranges) {{
    snapshots[activeLabel][decoration.kind] = ranges.length;
  }},
}};

function capture(label) {{
  activeLabel = label;
  snapshots[label] = {{ 'healthy.svg': 0, 'warning.svg': 0, 'critical.svg': 0 }};
  sandbox.loadHealth();
  sandbox.applyDecorations(editor);
}}

capture('healthy');
mode = 'missing';
capture('missing');
mode = 'malformed';
capture('malformed');
mode = 'partial';
capture('partial');
process.stdout.write(JSON.stringify(snapshots));
"""

    result = subprocess.run(["node", "-e", node_code], cwd=ROOT, capture_output=True, text=True, check=True)
    snapshots = json.loads(result.stdout)

    assert snapshots["healthy"] == {"healthy.svg": 1, "warning.svg": 1, "critical.svg": 1}
    assert snapshots["missing"] == {"healthy.svg": 0, "warning.svg": 0, "critical.svg": 0}
    assert snapshots["malformed"] == {"healthy.svg": 0, "warning.svg": 0, "critical.svg": 0}
    assert snapshots["partial"] == {"healthy.svg": 1, "warning.svg": 0, "critical.svg": 0}
