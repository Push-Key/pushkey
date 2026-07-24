from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "npm" / "scripts" / "install.js"
SHIMS = [
    ROOT / "npm" / "bin" / "pushkey.js",
    ROOT / "npm" / "bin" / "cli.js",
]


def run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def node_path(path: Path) -> str:
    return json.dumps(path.as_posix())


def copy_npm_fixture(tmp_path: Path) -> tuple[Path, Path]:
    package_root = tmp_path / "npm-fixture"
    scripts_dir = package_root / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "npm" / "scripts" / "install.js", scripts_dir / "install.js")
    shutil.copy2(ROOT / "npm" / "package.json", package_root / "package.json")
    return package_root / "scripts" / "install.js", package_root


def test_npm_installer_rejects_checksum_mismatch(tmp_path):
    dest = tmp_path / "pushkey.exe"
    checksum_file = tmp_path / "pushkey.exe.sha256"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"pushkey-binary")
    checksum_file.write_text(f"{hashlib.sha256(b'other-binary').hexdigest()}  pushkey.exe\n", encoding="utf-8")

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const install = require({node_path(INSTALLER)});

        (async () => {{
          try {{
            await install.verifyChecksum({json.dumps(dest.as_posix())}, 'https://example.invalid/pushkey.exe.sha256', {{
              download: async () => {{}},
              createHash: crypto.createHash,
              readFileSync: fs.readFileSync,
              unlinkSync: fs.unlinkSync,
              existsSync: fs.existsSync,
            }});
            process.stdout.write('unexpected-success');
          }} catch (err) {{
            process.stdout.write(`${{err.code}}:${{err.message}}`);
          }}
        }})().catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    assert "EINTEGRITY:sha256 mismatch" in result.stdout
    assert not checksum_file.exists()


def test_npm_installer_rejects_unsupported_platform():
    script = textwrap.dedent(
        f"""
        const install = require({node_path(INSTALLER)});
        const calls = [];
        const io = {{
          console: {{
            log() {{}},
            warn() {{}},
            error(msg) {{ calls.push(msg); }},
          }},
        }};

        try {{
          install.getTarget(io, 'linux', 'arm64');
          process.stdout.write('unexpected-success');
        }} catch (err) {{
          process.stdout.write(JSON.stringify({{ message: err.message, calls }}));
        }}
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["message"] == "unsupported platform or architecture: linux-arm64"
    assert any("Unsupported platform or architecture: linux-arm64" in msg for msg in payload["calls"])


def test_npm_installer_rejects_malformed_checksum_file(tmp_path):
    dest = tmp_path / "pushkey.exe"
    dest.write_bytes(b"pushkey-binary")

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const install = require({node_path(INSTALLER)});

        (async () => {{
          try {{
            await install.verifyChecksum({json.dumps(dest.as_posix())}, 'https://example.invalid/pushkey.exe.sha256', {{
              download: async (_url, checksumDest) => {{
                fs.writeFileSync(checksumDest, 'not-a-sha256\\n', 'utf8');
              }},
              createHash: crypto.createHash,
              readFileSync: fs.readFileSync,
              unlinkSync: fs.unlinkSync,
              existsSync: fs.existsSync,
            }});
            process.stdout.write('unexpected-success');
          }} catch (err) {{
            process.stdout.write(`${{err.code}}:${{err.message}}`);
          }}
        }})().catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    assert "EINTEGRITY:invalid sha256 checksum file" in result.stdout
    assert not (tmp_path / "pushkey.exe.sha256").exists()


def test_npm_installer_installs_clean_room_binary_and_verifies_checksum(tmp_path):
    installer, package_root = copy_npm_fixture(tmp_path)

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const path = require('path');
        const install = require({node_path(installer)});
        const root = {json.dumps(package_root.as_posix())};
        const dest = path.join(root, 'bin', 'pushkey');
        const calls = [];
        const io = {{
          spawnSync(cmd, args) {{
            if (cmd === 'pip' && args[0] === 'show') {{
              return {{ status: 1 }};
            }}
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 0 }};
          }},
          existsSync: fs.existsSync,
          mkdirSync: fs.mkdirSync,
          unlinkSync(target) {{
            calls.push(['unlink', path.basename(target)]);
            fs.unlinkSync(target);
          }},
          renameSync(src, dst) {{
            calls.push(['rename', path.basename(src), path.basename(dst)]);
            fs.renameSync(src, dst);
          }},
          chmodSync(target, mode) {{
            calls.push(['chmod', path.basename(target), mode]);
          }},
          createHash: crypto.createHash,
          readFileSync: fs.readFileSync,
          writeFileSync: fs.writeFileSync,
          download: async (url, fileDest) => {{
            if (url.endsWith('.sha256')) {{
              calls.push(['download', 'checksum']);
              const binary = fs.readFileSync(fileDest.slice(0, -7));
              const hash = crypto.createHash('sha256').update(binary).digest('hex');
              fs.writeFileSync(fileDest, `${{hash}}\\n`, 'utf8');
              return;
            }}
            calls.push(['download', 'binary']);
            fs.writeFileSync(fileDest, 'new-binary', 'utf8');
          }},
          console: {{
            log(msg) {{ calls.push(['log', msg]); }},
            warn(msg) {{ calls.push(['warn', msg]); }},
            error(msg) {{ calls.push(['error', msg]); }},
          }},
          installViaPip() {{
            calls.push(['pip']);
          }},
          writePipShim() {{
            calls.push(['shim']);
          }},
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write(JSON.stringify({{
            calls,
            destText: fs.readFileSync(dest, 'utf8'),
            stagedExists: fs.existsSync(`${{dest}}.download`),
          }}));
        }}).catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["destText"] == "new-binary"
    assert payload["stagedExists"] is False
    assert ["download", "binary"] in payload["calls"]
    assert ["download", "checksum"] in payload["calls"]
    assert ["rename", "pushkey.download", "pushkey"] in payload["calls"]
    assert ["pip"] not in payload["calls"]


def test_npm_installer_installs_signed_binary_and_verifies_signature(tmp_path):
    installer, package_root = copy_npm_fixture(tmp_path)

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const path = require('path');
        const install = require({node_path(installer)});
        const root = {json.dumps(package_root.as_posix())};
        const dest = path.join(root, 'bin', 'pushkey');
        const publicKeyPath = path.join(root, 'release-public-key.pem');
        const calls = [];
        const {{ publicKey, privateKey }} = crypto.generateKeyPairSync('ed25519');
        fs.writeFileSync(publicKeyPath, publicKey.export({{ format: 'pem', type: 'spki' }}));

        const io = {{
          spawnSync(cmd, args) {{
            if (cmd === 'pip' && args[0] === 'show') {{
              return {{ status: 1 }};
            }}
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 0 }};
          }},
          existsSync: fs.existsSync,
          mkdirSync: fs.mkdirSync,
          unlinkSync(target) {{
            calls.push(['unlink', path.basename(target)]);
            fs.unlinkSync(target);
          }},
          renameSync(src, dst) {{
            calls.push(['rename', path.basename(src), path.basename(dst)]);
            fs.renameSync(src, dst);
          }},
          chmodSync(target, mode) {{
            calls.push(['chmod', path.basename(target), mode]);
          }},
          createHash: crypto.createHash,
          readFileSync: fs.readFileSync,
          writeFileSync: fs.writeFileSync,
          download: async (url, fileDest) => {{
            if (url.endsWith('.sig')) {{
              calls.push(['download', 'signature']);
              const binaryPath = fileDest.slice(0, -4);
              const signature = crypto.sign(null, fs.readFileSync(binaryPath), privateKey).toString('base64');
              fs.writeFileSync(fileDest, `${{signature}}\\n`, 'utf8');
              return;
            }}
            if (url.endsWith('.sha256')) {{
              calls.push(['download', 'checksum']);
              const binary = fs.readFileSync(fileDest.slice(0, -7));
              const hash = crypto.createHash('sha256').update(binary).digest('hex');
              fs.writeFileSync(fileDest, `${{hash}}\\n`, 'utf8');
              return;
            }}
            calls.push(['download', 'binary']);
            fs.writeFileSync(fileDest, 'new-binary', 'utf8');
          }},
          console: {{
            log(msg) {{ calls.push(['log', msg]); }},
            warn(msg) {{ calls.push(['warn', msg]); }},
            error(msg) {{ calls.push(['error', msg]); }},
          }},
          installViaPip() {{
            calls.push(['pip']);
          }},
          writePipShim() {{
            calls.push(['shim']);
          }},
          releasePublicKeyPath: publicKeyPath,
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write(JSON.stringify({{
            calls,
            destText: fs.readFileSync(dest, 'utf8'),
            stagedExists: fs.existsSync(`${{dest}}.download`),
          }}));
        }}).catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["destText"] == "new-binary"
    assert payload["stagedExists"] is False
    assert ["download", "binary"] in payload["calls"]
    assert ["download", "signature"] in payload["calls"]
    assert ["download", "checksum"] in payload["calls"]
    assert ["rename", "pushkey.download", "pushkey"] in payload["calls"]
    assert ["pip"] not in payload["calls"]


def test_npm_installer_upgrades_existing_binary_without_losing_it_on_success(tmp_path):
    installer, package_root = copy_npm_fixture(tmp_path)
    dest = package_root / "bin" / "pushkey"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("old-binary", encoding="utf-8")

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const path = require('path');
        const install = require({node_path(installer)});
        const root = {json.dumps(package_root.as_posix())};
        const dest = path.join(root, 'bin', 'pushkey');
        const calls = [];
        const io = {{
          spawnSync(cmd, args) {{
            if (cmd === 'pip' && args[0] === 'show') {{
              return {{ status: 1 }};
            }}
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 0 }};
          }},
          existsSync: fs.existsSync,
          mkdirSync: fs.mkdirSync,
          unlinkSync(target) {{
            calls.push(['unlink', path.basename(target)]);
            fs.unlinkSync(target);
          }},
          renameSync(src, dst) {{
            calls.push(['rename', path.basename(src), path.basename(dst)]);
            fs.renameSync(src, dst);
          }},
          chmodSync(target, mode) {{
            calls.push(['chmod', path.basename(target), mode]);
          }},
          createHash: crypto.createHash,
          readFileSync: fs.readFileSync,
          writeFileSync: fs.writeFileSync,
          download: async (url, fileDest) => {{
            if (url.endsWith('.sha256')) {{
              calls.push(['download', 'checksum']);
              const binary = fs.readFileSync(fileDest.slice(0, -7));
              const hash = crypto.createHash('sha256').update(binary).digest('hex');
              fs.writeFileSync(fileDest, `${{hash}}\\n`, 'utf8');
              return;
            }}
            calls.push(['download', 'binary']);
            fs.writeFileSync(fileDest, 'new-binary', 'utf8');
          }},
          console: {{
            log(msg) {{ calls.push(['log', msg]); }},
            warn(msg) {{ calls.push(['warn', msg]); }},
            error(msg) {{ calls.push(['error', msg]); }},
          }},
          installViaPip() {{
            calls.push(['pip']);
          }},
          writePipShim() {{
            calls.push(['shim']);
          }},
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write(JSON.stringify({{
            calls,
            destText: fs.readFileSync(dest, 'utf8'),
            stagedExists: fs.existsSync(`${{dest}}.download`),
          }}));
        }}).catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["destText"] == "new-binary"
    assert payload["stagedExists"] is False
    assert ["download", "binary"] in payload["calls"]
    assert ["download", "checksum"] in payload["calls"]
    assert ["rename", "pushkey.download", "pushkey"] in payload["calls"]
    assert ["pip"] not in payload["calls"]


def test_npm_installer_keeps_existing_binary_on_checksum_failure(tmp_path):
    installer, package_root = copy_npm_fixture(tmp_path)
    dest = package_root / "bin" / "pushkey"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("old-binary", encoding="utf-8")

    script = textwrap.dedent(
        f"""
        const crypto = require('crypto');
        const fs = require('fs');
        const path = require('path');
        const install = require({node_path(installer)});
        const root = {json.dumps(package_root.as_posix())};
        const dest = path.join(root, 'bin', 'pushkey');
        const calls = [];
        const io = {{
          spawnSync(cmd, args) {{
            if (cmd === 'pip' && args[0] === 'show') {{
              return {{ status: 1 }};
            }}
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 0 }};
          }},
          existsSync: fs.existsSync,
          mkdirSync: fs.mkdirSync,
          unlinkSync(target) {{
            calls.push(['unlink', path.basename(target)]);
            fs.unlinkSync(target);
          }},
          renameSync(src, dst) {{
            calls.push(['rename', path.basename(src), path.basename(dst)]);
            fs.renameSync(src, dst);
          }},
          chmodSync(target, mode) {{
            calls.push(['chmod', path.basename(target), mode]);
          }},
          createHash: crypto.createHash,
          readFileSync: fs.readFileSync,
          writeFileSync: fs.writeFileSync,
          download: async (url, fileDest) => {{
            if (url.endsWith('.sha256')) {{
              calls.push(['download', 'checksum']);
              fs.writeFileSync(fileDest, `${{'f'.repeat(64)}}\\n`, 'utf8');
              return;
            }}
            calls.push(['download', 'binary']);
            fs.writeFileSync(fileDest, 'new-binary', 'utf8');
          }},
          console: {{
            log(msg) {{ calls.push(['log', msg]); }},
            warn(msg) {{ calls.push(['warn', msg]); }},
            error(msg) {{ calls.push(['error', msg]); }},
          }},
          installViaPip() {{
            calls.push(['pip']);
          }},
          writePipShim() {{
            calls.push(['shim']);
          }},
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write('unexpected-success');
        }}).catch((err) => {{
          process.stdout.write(JSON.stringify({{
            code: err.code,
            error: err.message,
            calls,
            destText: fs.readFileSync(dest, 'utf8'),
            stagedExists: fs.existsSync(`${{dest}}.download`),
          }}));
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["code"] == "EINTEGRITY"
    assert "sha256 mismatch" in payload["error"]
    assert payload["destText"] == "old-binary"
    assert payload["stagedExists"] is False
    assert ["rename", "pushkey.download", "pushkey"] not in payload["calls"]
    assert ["pip"] not in payload["calls"]
    assert any(call[0] == "error" and "Checksum verification failed:" in call[1] for call in payload["calls"])


def test_npm_installer_falls_back_to_pip_only_for_download_failure():
    script = textwrap.dedent(
        f"""
        const install = require({node_path(INSTALLER)});
        const calls = [];
        const io = {{
          spawnSync(cmd, args) {{
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 1 }};
          }},
          existsSync() {{ return false; }},
          mkdirSync() {{ calls.push(['mkdir']); }},
          unlinkSync() {{ calls.push(['unlink']); }},
          chmodSync() {{ calls.push(['chmod']); }},
          console: {{ log() {{}}, warn() {{}}, error() {{}} }},
          download: async () => {{ throw new Error('HTTP 404 for binary asset'); }},
          verifyChecksum: async () => {{ calls.push(['verify']); }},
          installViaPip() {{ calls.push(['pip']); }},
          writePipShim() {{ calls.push(['shim']); }},
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write(JSON.stringify(calls));
        }}).catch((err) => {{
          console.error(err.stack || err.message);
          process.exit(1);
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout)
    assert ['verify'] not in calls
    assert ['pip'] in calls


def test_npm_installer_does_not_fallback_on_checksum_failure():
    script = textwrap.dedent(
        f"""
        const install = require({node_path(INSTALLER)});
        const calls = [];
        const io = {{
          spawnSync(cmd, args) {{
            calls.push(['spawn', cmd, args[0]]);
            return {{ status: 1 }};
          }},
          existsSync() {{ return false; }},
          mkdirSync() {{ calls.push(['mkdir']); }},
          unlinkSync() {{ calls.push(['unlink']); }},
          chmodSync() {{ calls.push(['chmod']); }},
          console: {{ log() {{}}, warn() {{}}, error() {{}} }},
          download: async () => {{}},
          verifyChecksum: async () => {{ throw Object.assign(new Error('sha256 mismatch for binary'), {{ code: 'EINTEGRITY' }}); }},
          installViaPip() {{ calls.push(['pip']); }},
          writePipShim() {{ calls.push(['shim']); }},
        }};

        install.main(io, 'linux', 'x64').then(() => {{
          process.stdout.write('unexpected-success');
        }}).catch((err) => {{
          process.stdout.write(JSON.stringify({{ message: err.message, calls }}));
        }});
        """
    )

    result = run_node(script)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["message"] == "sha256 mismatch for binary"
    assert ["pip"] not in payload["calls"]
    assert ["shim"] not in payload["calls"]


def test_npm_shims_prevent_self_resolution_loops():
    for shim in SHIMS:
        text = shim.read_text(encoding="utf-8")
        assert "realpathSync" in text
        assert "process.execPath" in text
        assert "spawnSync('pushkey'" not in text
        assert "bin !== __filename" not in text


def test_npm_package_does_not_ship_unix_binary_placeholder():
    assert not (ROOT / "npm" / "bin" / "pushkey").exists()
