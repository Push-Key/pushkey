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
