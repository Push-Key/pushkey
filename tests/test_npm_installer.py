from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "npm" / "scripts" / "install.js"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
SHIMS = [
    ROOT / "npm" / "bin" / "pushkey.js",
    ROOT / "npm" / "bin" / "cli.js",
]


def test_npm_installer_fails_nonzero_for_unsupported_or_failed_install():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "process.exit(0); // non-fatal" not in text
    assert "process.exit(0); // never block npm install" not in text
    assert "process.exit(1)" in text


def test_npm_installer_documents_architecture_and_checksum_policy():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "process.arch" in text
    assert "x64" in text
    assert "arm64" in text
    assert "sha256" in text.lower()
    assert ".sha256" in text


def test_release_workflow_publishes_assets_used_by_npm_installer():
    installer = INSTALLER.read_text(encoding="utf-8")
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assets = [
        "pushkey-windows-x64.exe",
        "pushkey-macos-x64",
        "pushkey-linux-x64",
    ]

    assert "--cli-only" in workflow
    assert re.search(r"actions/download-artifact@[0-9a-f]{40}", workflow)
    assert '"$file.sha256"' in workflow
    for asset in assets:
        assert asset in workflow
        assert asset in installer


def test_npm_shims_prevent_self_resolution_loops():
    for shim in SHIMS:
        text = shim.read_text(encoding="utf-8")
        assert "realpathSync" in text
        assert "process.execPath" in text
        assert "spawnSync('pushkey'" not in text
        assert "bin !== __filename" not in text


def test_npm_package_does_not_ship_unix_binary_placeholder():
    assert not (ROOT / "npm" / "bin" / "pushkey").exists()
